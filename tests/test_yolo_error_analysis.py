import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import yolo_improvement_01 as experiment
from src.road_anomaly.yolo_error_analysis import Frame, classify_errors, summarize_thresholds
from src.road_anomaly.yolo_evaluation import Detection


class YoloErrorAnalysisTest(unittest.TestCase):
    def test_matching_counts_confusion_and_localization_without_double_counting(self) -> None:
        frame = Frame(Path("labelled.jpg"), [
            Detection(1, (0, 0, 10, 10)), Detection(3, (20, 0, 30, 10)),
            Detection(0, (0, 20, 10, 30)), Detection(2, (20, 20, 30, 30)),
        ], [
            Detection(1, (0, 0, 10, 10), 0.08), Detection(1, (0, 0, 9, 9), 0.06),
            Detection(2, (20, 0, 30, 10), 0.31), Detection(0, (0, 20, 4, 30), 0.22),
        ], 600, 600)
        background = Frame(Path("background.jpg"), [], [
            Detection(0, (10, 10, 20, 20), 0.05), Detection(0, (0, 0, 10, 10), 0.049),
        ], 600, 600)
        summaries, cases = summarize_thresholds([frame, background])
        self.assertEqual((summaries, cases), summarize_thresholds([frame, background]))
        levels = summaries["thresholds"]
        self.assertEqual(levels["0.05"]["errors"], {
            "true_positive": 1, "class_confusion": 1, "localization": 1,
            "false_negative": 1, "duplicate": 1, "background_false_positive": 1,
        })
        self.assertEqual(levels["0.05"]["confusions"], [{"gt": "D40", "pred": "D20", "count": 1}])
        overall = levels["0.05"]["overall"]
        self.assertEqual((overall["tp"], overall["fp"], overall["fn"]), (1, 4, 3))
        self.assertEqual((overall["precision"], overall["recall"]), (0.2, 0.25))
        self.assertIsNone(levels["0.10"]["classes"]["D10"]["precision"])
        self.assertEqual(levels["0.25"]["overall"]["fn"], 4)

    def test_invalid_threshold_or_empty_input(self) -> None:
        with self.assertRaisesRegex(ValueError, "confidence"):
            classify_errors(Frame(Path("background.jpg"), [], [], 600, 600), float("nan"))
        with self.assertRaisesRegex(ValueError, "Validation"):
            summarize_thresholds([])

    def test_size_buckets_use_original_pixel_edges(self) -> None:
        frame = Frame(Path("edge.jpg"), [
            Detection(1, (10.0, 10.0, 42.0 - 1e-8, 80.0)),
            Detection(3, (50.0, 50.0, 110.0 - 1e-8, 110.0)),
        ], [], 600, 600)
        summary, _ = summarize_thresholds([frame])
        stats = summary["thresholds"]["0.05"]["classes"]
        self.assertEqual(stats["D10"]["gt_short_side"], 0)
        self.assertEqual(stats["D40"]["gt_other"], 1)

    def test_missing_baseline_and_existing_analysis_output_are_protected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(experiment, "BASELINE", root / "missing"):
                with self.assertRaisesRegex(FileNotFoundError, "Part 3"):
                    experiment.baseline_state()
            existing = root / "existing"
            existing.mkdir()
            marker = existing / "threshold_analysis.json"
            marker.write_bytes(b"prior analysis")
            with patch.object(experiment, "baseline_state", return_value=({}, {})), \
                 patch.object(experiment, "read_dataset", return_value={"val": []}), \
                 patch.object(experiment, "output_path", return_value=existing):
                with self.assertRaises(FileExistsError):
                    experiment.analyze("existing")
            self.assertEqual(marker.read_bytes(), b"prior analysis")

    def test_comparison_requires_equal_validation_conditions_and_support(self) -> None:
        scores = {key: 0.2 for key in experiment.METRICS}
        before = {"options": {"conf": 0.001}, "images": 283, "overall": scores,
                  "classes": {name: {**scores, "images": 5, "instances": 8} for name in experiment.CLASSES}}
        after = copy.deepcopy(before)
        after["overall"]["ap50"] = 0.25
        result = experiment.compare_validation(before, after)
        self.assertAlmostEqual(result["overall"]["ap50"]["delta"], 0.05)
        after["classes"]["D40"]["instances"] = 9
        with self.assertRaisesRegex(ValueError, "D40"):
            experiment.compare_validation(before, after)
        after["options"]["conf"] = 0.01
        with self.assertRaisesRegex(ValueError, "비교 설정"):
            experiment.compare_validation(before, after)

    def test_training_difference_excludes_only_run_paths(self) -> None:
        initial = {"cls_pw": 0.0, "batch": 4, "seed": 42, "data": "first.yaml", "name": "baseline"}
        changed = {**initial, "cls_pw": 0.25, "data": "second.yaml", "name": "improvement"}
        self.assertEqual(experiment.training_differences(initial, changed), {
            "cls_pw": {"baseline": 0.0, "improvement": 0.25},
        })
        changed["batch"] = 8
        self.assertIn("batch", experiment.training_differences(initial, changed))
