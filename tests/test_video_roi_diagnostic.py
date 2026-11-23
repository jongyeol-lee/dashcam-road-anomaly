import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from scripts import diagnose_video_roi as diagnostic
from road_anomaly.detection_grouping import FrameDetection, group_detections
from road_anomaly.roi import BoxPosition, NormalizedRoi
from road_anomaly.video_analysis import _save_detections


def detection(index, time_sec, box, image_path=Path("frame.jpg")):
    return FrameDetection(index, time_sec, 3, "D40", 0.08, box, image_path)


class NormalizedRoiTest(unittest.TestCase):
    roi = NormalizedRoi(((0.25, 0.25), (0.75, 0.25), (0.75, 0.75), (0.25, 0.75)))

    def test_center_inside_outside_and_box_touching_or_crossing_the_boundary(self) -> None:
        cases = (
            ((40, 40, 60, 60), BoxPosition(True, False)),
            ((0, 40, 10, 60), BoxPosition(False, False)),
            ((20, 40, 50, 60), BoxPosition(True, True)),
            ((10, 40, 30, 60), BoxPosition(False, True)),
            ((20, 40, 30, 60), BoxPosition(True, True)),  # 정중앙이 경계에 위치한다.
            ((10, 10, 25, 25), BoxPosition(False, True)),
            ((0, 0, 100, 100), BoxPosition(True, True)),
        )
        for box, expected in cases:
            with self.subTest(box=box):
                self.assertEqual(self.roi.classify(box, 100, 100), expected)

    def test_nonrectangular_roi_uses_its_slanted_edge(self) -> None:
        roi = NormalizedRoi(((0.4, 0.2), (0.6, 0.2), (0.8, 0.6), (0.2, 0.6)))
        self.assertEqual(roi.classify((28, 38, 32, 42), 100, 100), BoxPosition(True, True))
        self.assertEqual(roi.classify((23, 26, 25, 30), 100, 100), BoxPosition(False, False))

    def test_scales_each_axis_and_preserves_decisions(self) -> None:
        self.assertEqual(self.roi.pixel_vertices(200, 80), ((50, 20), (150, 20), (150, 60), (50, 60)))
        self.assertEqual(self.roi.pixel_vertices(400, 160), ((100, 40), (300, 40), (300, 120), (100, 120)))
        original = self.roi.classify((45, 30, 65, 45), 200, 80)
        self.assertEqual(original, BoxPosition(True, True))
        self.assertEqual(original, self.roi.classify((90, 60, 130, 90), 400, 160))

    def test_rejects_out_of_range_nonfinite_degenerate_and_unordered_rois(self) -> None:
        invalid = (
            ((0, 0), (1, 0)),
            ((-0.1, 0), (1, 0), (1, 1)),
            ((0, 0), (1.01, 0), (1, 1)),
            ((0, 0), (1, float("nan")), (1, 1)),
            ((0, 0), (1, 0), (1,)),
            ((0, 0), (0.4, 0), (1, 0)),
            ((0, 0), (1, 0), (1, 0), (0, 1)),
            ((0, 0), (1, 1), (1, 0), (0, 1)),
            ((0, 0), (1, 0), (0.5, 0.25), (1, 1), (0, 1)),
        )
        for vertices in invalid:
            with self.subTest(vertices=vertices), self.assertRaisesRegex(ValueError, "ROI"):
                NormalizedRoi(vertices)

    def test_handles_empty_and_all_excluded_predictions(self) -> None:
        outside = detection(0, 0.0, (0, 40, 10, 60))
        for items in ((), (outside,)):
            with self.subTest(items=items):
                result, decisions = diagnostic.compare_condition(items, self.roi, 100, 100, 1.5)
                self.assertEqual(result["excluded_count"], len(items))
                self.assertEqual(result["retained_count"], 0)
                self.assertEqual(result["retained_class_counts"], dict.fromkeys(("D00", "D10", "D20", "D40"), 0))
                self.assertEqual(result["events"], [])
                self.assertEqual(decisions, (BoxPosition(False, False),) * len(items))

    def test_recalculates_events_after_removing_a_bridge_without_editing_predictions(self) -> None:
        inside, outside = (40, 40, 60, 60), (0, 40, 10, 60)
        items = (detection(18, 1.8, inside), detection(9, 0.9, outside), detection(0, 0.0, inside))
        before = tuple((item.frame_index, item.xyxy, item.image_path) for item in items)
        original, original_decisions = diagnostic.compare_condition(items, None, 100, 100, 1.5)
        filtered, decisions = diagnostic.compare_condition(items, self.roi, 100, 100, 1.5, frozenset({1}))
        self.assertEqual(original["event_count"], 1)
        self.assertEqual(original_decisions, (BoxPosition(True, False),) * 3)
        self.assertEqual(filtered["event_count"], 2)
        self.assertEqual([event["representative_frame_index"] for event in filtered["events"]], [0, 18])
        self.assertEqual(filtered["known_interior_excluded_count"], 1)
        self.assertEqual([item.keep for item in decisions], [True, False, True])
        self.assertEqual(tuple((item.frame_index, item.xyxy, item.image_path) for item in items), before)


class SavedVideoRoiDiagnosticTest(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.source = root / "source"
        self.output = root / "results"
        self.enterContext(patch.object(diagnostic, "DEFAULT_ANALYSIS_ROOT", self.source))
        self.enterContext(patch.object(diagnostic, "OUTPUT_ROOT", self.output))
        self.enterContext(patch.object(diagnostic, "REVIEW_FRAMES", frozenset({0})))
        video = {"path": str(root / "sample.mp4"), "fps": 30, "width": 100, "height": 100,
                 "frame_count": 800, "extracted_frame_count": 6}
        jpeg = cv2.imencode(".jpg", np.full((100, 100, 3), 110, dtype=np.uint8))[1].tobytes()
        for model, name in diagnostic.SOURCE_RUNS.items():
            run = self.source / name
            frames = run / "frames"
            frames.mkdir(parents=True)
            detections = []
            with (frames / "frames.csv").open("x", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(("frame_index", "estimated_time_sec", "decoder_time_ms", "image_file"))
                for index in sorted({0} | diagnostic.INTERIOR_D40_FRAMES):
                    time_sec = index / video["fps"]
                    image = frames / f"frame_{index:06d}.jpg"
                    image.write_bytes(jpeg)
                    writer.writerow((index, time_sec, time_sec * 1000, image.name))
                    if model == "mixed" and index:
                        detections.append(detection(index, time_sec, (10, 90, 25, 100), image))
            _save_detections(run / "detections.csv", detections)
            events = [diagnostic.event_record(event) for event in group_detections(detections)]
            (run / "events.json").write_text(json.dumps(events), encoding="utf-8")
            summary = {"video": video, "frames_dir": str(frames), "settings": {"max_gap_sec": 1.5},
                       "model": {"name": model}, "detection_count": len(detections), "event_count": len(events),
                       "timestamp_basis": "frame_index / fps", "analysis_seconds": 1.0}
            (run / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    def source_snapshot(self) -> dict:
        return {path: path.read_bytes() for path in self.source.rglob("*") if path.is_file()}

    def test_writes_comparisons_for_same_input_and_never_overwrites_a_run(self) -> None:
        before = self.source_snapshot()
        summary = diagnostic.diagnose("review")
        run = self.output / "review"
        self.assertEqual(summary["shared_sample_images_verified"], 6)
        self.assertEqual(len(list((run / "previews").glob("*.jpg"))), 6)
        with (run / "roi_comparison.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([row["retained_count"] for row in rows], ["0", "0", "0", "5", "0", "0"])
        self.assertEqual(len({row["source_detections_sha256"] for row in rows[3:]}), 1)
        report = (run / "roi_summary.json").read_bytes()
        with self.assertRaises(FileExistsError):
            diagnostic.diagnose("review")
        self.assertEqual((run / "roi_summary.json").read_bytes(), report)
        self.assertEqual(self.source_snapshot(), before)

    def test_removes_only_the_failed_output_after_a_preview_error(self) -> None:
        before = self.source_snapshot()
        self.output.mkdir()
        sentinel = self.output / "other-run.txt"
        sentinel.write_bytes(b"existing result")
        with patch.object(diagnostic, "write_preview", side_effect=RuntimeError("preview failed")):
            with self.assertRaisesRegex(RuntimeError, "preview failed"):
                diagnostic.diagnose("failed")
        self.assertFalse((self.output / "failed").exists())
        self.assertEqual(sentinel.read_bytes(), b"existing result")
        self.assertEqual(self.source_snapshot(), before)

    def test_rejects_a_mismatch_between_saved_frame_bytes(self) -> None:
        changed = self.source / diagnostic.SOURCE_RUNS["mixed"] / "frames/frame_000000.jpg"
        changed.write_bytes(b"different frame")
        before = self.source_snapshot()
        with self.assertRaisesRegex(ValueError, "추출 JPG가 다릅니다"):
            diagnostic.diagnose("mismatch")
        self.assertFalse(self.output.exists())
        self.assertEqual(self.source_snapshot(), before)
