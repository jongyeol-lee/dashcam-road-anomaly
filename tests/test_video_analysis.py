import csv
import json
import sys
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from scripts.make_test_video import make_test_video
from src.road_anomaly import video_analysis


class VideoAnalysisTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.video = make_test_video(Path(temp.name) / "test_3sec.mp4")

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.frames_root = self.root / "frames"
        self.analysis_root = self.root / "analysis"
        self.checkpoint = self.root / "test.pt"
        self.checkpoint.write_bytes(b"mock YOLO checkpoint")
        self.predictions = {}
        self.model = Mock(task="detect")
        self.model.predict.side_effect = self.mock_predictions
        self.yolo = Mock(return_value=self.model)
        self.enterContext(patch.object(video_analysis, "DEFAULT_FRAMES_ROOT", self.frames_root))
        self.enterContext(patch.object(video_analysis, "DEFAULT_ANALYSIS_ROOT", self.analysis_root))

    def mock_predictions(self, source: str, **kwargs):
        for path in sorted(Path(source).glob("*.jpg"), reverse=True):
            frame_index = int(path.stem.removeprefix("frame_"))
            predictions = self.predictions.get(frame_index, [])
            boxes = SimpleNamespace(
                xyxy=np.array([xyxy for _, xyxy, _ in predictions]),
                cls=np.array([class_id for class_id, _, _ in predictions]),
                conf=np.array([confidence for _, _, confidence in predictions]),
            )
            yield SimpleNamespace(path=str(path), names={0: "D00", 3: "D40"}, boxes=boxes)

    def analyze(self, **overrides):
        options = {"video_path": self.video, "model_path": self.checkpoint, "run_name": "mock", "device": "cpu"}
        with patch.dict(sys.modules, {"ultralytics": SimpleNamespace(YOLO=self.yolo)}):
            return video_analysis.analyze_video(**(options | overrides))

    def test_records_each_box_and_renders_the_representative_scene(self) -> None:
        self.predictions = {
            0: [(0, (10, 52, 72, 80), 0.31), (0, (88, 125, 113, 148), 0.72), (3, (145, 40, 221, 75), 0.59)],
            8: [(0, (96, 44, 132, 73), 0.95)],
            23: [(0, (100, 100, 160, 140), 0.52)],
        }
        video_digest = sha256(self.video.read_bytes()).hexdigest()
        model_digest = sha256(self.checkpoint.read_bytes()).hexdigest()

        summary = self.analyze(interval=0.75, confidence=0.2, max_gap=0.8)

        frames_dir = self.frames_root / "mock"
        output_dir = self.analysis_root / "mock"
        self.yolo.assert_called_once_with(str(self.checkpoint), task="detect")
        self.model.predict.assert_called_once_with(
            str(frames_dir), stream=True, save=False, verbose=False,
            conf=0.2, imgsz=640, iou=0.7, device="cpu", rect=False, max_det=300,
        )
        with (output_dir / "detections.csv").open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(reader.fieldnames, [
                "frame_index", "estimated_time_sec", "class_id", "class_name", "confidence",
                "x1", "y1", "x2", "y2", "image_path",
            ])
            rows = list(reader)
        self.assertEqual([int(row["frame_index"]) for row in rows], [0, 0, 0, 8, 23])
        self.assertEqual([float(row["estimated_time_sec"]) for row in rows], [0.0, 0.0, 0.0, 0.8, 2.3])
        self.assertEqual([(int(row["class_id"]), row["class_name"]) for row in rows],
                         [(0, "D00"), (0, "D00"), (3, "D40"), (0, "D00"), (0, "D00")])
        self.assertEqual([float(row["confidence"]) for row in rows], [0.31, 0.72, 0.59, 0.95, 0.52])
        self.assertEqual([tuple(float(row[key]) for key in ("x1", "y1", "x2", "y2")) for row in rows[:2]],
                         [(10, 52, 72, 80), (88, 125, 113, 148)])
        self.assertEqual(Path(rows[3]["image_path"]), frames_dir / "frame_000008.jpg")

        events = json.loads((output_dir / "events.json").read_text(encoding="utf-8"))
        self.assertEqual([event["class_name"] for event in events], ["D00", "D40", "D00"])
        self.assertEqual(events[0], {
            "event_id": "event_0001", "class_id": 0, "class_name": "D00",
            "start_time_sec": 0.0, "last_detection_time_sec": 0.8, "max_confidence": 0.95,
            "representative_frame_index": 8, "representative_time_sec": 0.8,
            "representative_xyxy": [96, 44, 132, 73],
            "representative_image": "scenes/event_0001.jpg", "detection_count": 3, "detected_frame_count": 2,
        })
        for event in events:
            scene = cv2.imread(str(output_dir / event["representative_image"]))
            self.assertIsNotNone(scene)
            self.assertEqual(scene.shape, (180, 320, 3))
        scene = cv2.imread(str(output_dir / events[0]["representative_image"]))
        original = cv2.imread(rows[3]["image_path"])
        self.assertGreater(int(scene[44, 114, 2]), int(original[44, 114, 2]) + 100)
        self.assertGreater(int(scene[:25, :, 2].max()), int(original[:25, :, 2].max()) + 100)

        self.assertEqual(json.loads((output_dir / "summary.json").read_text(encoding="utf-8")), summary)
        self.assertEqual(summary["video"], {
            "path": str(self.video.resolve()), "fps": 10.0, "width": 320, "height": 180,
            "frame_count": 30, "extracted_frame_count": 4,
        })
        self.assertEqual(summary["model"], {"path": str(self.checkpoint), "sha256": model_digest})
        self.assertEqual(summary["settings"], {
            "interval_sec": 0.75, "conf": 0.2, "max_gap_sec": 0.8,
            "imgsz": 640, "iou": 0.7, "device": "cpu", "rect": False, "max_det": 300,
        })
        self.assertEqual(summary["timestamp_basis"], "frame_index / fps")
        self.assertEqual((summary["detection_count"], summary["event_count"]), (5, 3))
        self.assertGreater(summary["analysis_seconds"], 0)
        self.assertAlmostEqual(sum(summary["timing_seconds"].values()), summary["analysis_seconds"])
        self.assertAlmostEqual(summary["analysis_to_duration_ratio"], summary["analysis_seconds"] / 3)
        self.assertEqual(summary["detected_frame_count"], 3)
        self.assertAlmostEqual(summary["box_to_event_reduction"], 0.4)
        self.assertEqual(sha256(self.video.read_bytes()).hexdigest(), video_digest)
        self.assertEqual(sha256(self.checkpoint.read_bytes()).hexdigest(), model_digest)

    def test_zero_detections_saves_valid_outputs(self) -> None:
        torch = SimpleNamespace(cuda=Mock(is_available=Mock(return_value=False)))
        with patch.dict(sys.modules, {"torch": torch}):
            summary = self.analyze(run_name=None, device="auto")

        output_dir = Path(summary["output_dir"])
        self.assertRegex(output_dir.name, r"^\d{8}_\d{6}_\d{6}Z$")
        self.assertEqual(summary["settings"]["device"], "cpu")
        self.assertEqual((summary["profile"], summary["settings"]["imgsz"]), ("baseline", 640))
        self.assertIsNone(summary["box_to_event_reduction"])
        self.assertEqual((summary["detection_count"], summary["event_count"]), (0, 0))
        self.assertEqual(summary["video"]["extracted_frame_count"], 3)
        self.assertEqual((output_dir / "events.json").read_text(encoding="utf-8").strip(), "[]")
        self.assertEqual(list((output_dir / "scenes").iterdir()), [])
        with (output_dir / "detections.csv").open(encoding="utf-8", newline="") as handle:
            self.assertEqual(list(csv.reader(handle)), [list(video_analysis.DETECTION_COLUMNS)])

    def test_explicit_duration_and_output_roots_do_not_change_cli_defaults(self):
        self.predictions = {index: [(0, (10, 52, 72, 80), 0.5)] for index in (0, 10, 20)}
        frames_root, analysis_root = self.root / "web_frames", self.root / "web_analysis"
        summary = self.analyze(max_event_duration=1, frames_root=frames_root, analysis_root=analysis_root)
        self.assertEqual(summary["event_count"], 2)
        self.assertEqual(summary["detection_count"], 3)
        self.assertEqual(summary["settings"]["max_event_duration_sec"], 1)
        self.assertEqual(Path(summary["output_dir"]), analysis_root / "mock")
        self.assertEqual(Path(summary["frames_dir"]), frames_root / "mock")
        self.assertFalse(self.frames_root.exists())
        self.assertFalse(self.analysis_root.exists())

    def test_rejects_invalid_inputs_before_creating_outputs(self) -> None:
        cases = [
            ({"imgsz": 0}, ValueError, "imgsz"),
            ({"imgsz": -1}, ValueError, "imgsz"),
            ({"imgsz": 640.5}, ValueError, "imgsz"),
            ({"imgsz": True}, ValueError, "imgsz"),
            ({"profile": "unknown"}, ValueError, "프로필"),
            ({"interval": 0}, ValueError, "추출 간격"),
            ({"interval": float("inf")}, ValueError, "추출 간격"),
            ({"confidence": -0.1}, ValueError, "Confidence"),
            ({"confidence": float("nan")}, ValueError, "Confidence"),
            ({"max_gap": -1}, ValueError, "통합 간격"),
            ({"device": "gpu"}, ValueError, "추론 장치"),
            ({"run_name": "../existing"}, ValueError, "실행 이름"),
            ({"run_name": "NUL"}, ValueError, "실행 이름"),
            ({"video_path": self.root / "sample.avi"}, ValueError, "MP4"),
            ({"video_path": self.root / "missing.mp4"}, FileNotFoundError, "MP4"),
            ({"model_path": self.root / "model.onnx"}, ValueError, "로컬 .pt"),
            ({"model_path": self.root / "missing.pt"}, FileNotFoundError, "모델 파일"),
        ]
        for options, error_type, message in cases:
            with self.subTest(options=options), self.assertRaisesRegex(error_type, message):
                self.analyze(**options)
        self.assertFalse(self.frames_root.exists())
        self.assertFalse(self.analysis_root.exists())
        self.yolo.assert_not_called()

    def test_mvp_defaults_and_explicit_overrides(self):
        self.model.names = dict(enumerate(video_analysis.CLASSES))
        profile = video_analysis.PROFILES["mvp"]
        self.assertEqual(profile["model_path"], video_analysis.MVP_MODEL)
        self.assertEqual(profile["device"], "cuda:0")
        with patch.object(video_analysis, "_prepare_mvp_predictor", return_value={"frames": 6}):
            summary = self.analyze(profile="mvp")
        settings = summary["settings"]
        self.assertEqual((settings["imgsz"], settings["interval_sec"], settings["conf"], settings["max_gap_sec"]),
                         (1280, 0.5, 0.05, 1.5))
        self.assertEqual(settings["batch"], 1)
        self.assertIsNone(settings["quantize"])
        self.assertFalse(settings["agnostic_nms"])
        self.assertEqual(summary["inferred_frame_count"], 6)
        self.assertEqual(summary["model"]["path"], str(self.checkpoint))
        with patch.object(video_analysis, "_prepare_mvp_predictor", return_value={"frames": 3}):
            summary = self.analyze(run_name="override", profile="mvp", imgsz=960, confidence=0, interval=1, max_gap=0)
        options = self.model.predict.call_args.kwargs
        self.assertEqual((options["imgsz"], options["conf"], options["device"]), (960, 0, "cpu"))
        self.assertEqual((summary["settings"]["interval_sec"], summary["settings"]["max_gap_sec"]), (1, 0))
        self.assertEqual(profile["predict"]["imgsz"], 1280)

    def test_mvp_rejects_incompatible_classes(self):
        self.model.names = {0: "other"}
        with self.assertRaisesRegex(ValueError, "클래스 매핑"):
            self.analyze(profile="mvp")
        self.model.predict.assert_not_called()
        self.assert_run_removed()

    def test_pinned_weight_hash_is_checked_before_yolo_load(self):
        with (patch.dict(sys.modules, {"ultralytics": SimpleNamespace(YOLO=self.yolo)}),
              self.assertRaisesRegex(RuntimeError, "SHA-256")):
            video_analysis._load_model(self.checkpoint, expected_sha256=video_analysis.MVP_SHA256)
        self.yolo.assert_not_called()

    def test_cli_defers_defaults_and_passes_profile_and_imgsz(self):
        import os
        from scripts import analyze_video as cli

        response = {"video": {"extracted_frame_count": 3}, "detection_count": 0, "event_count": 0,
                    "analysis_seconds": 1, "frames_dir": "frames", "output_dir": "output"}
        for args, profile, imgsz in (([], "baseline", None), (["--profile", "mvp", "--imgsz", "960"], "mvp", 960)):
            with (patch.object(sys, "argv", ["analyze_video", str(self.video), *args]), patch.dict(os.environ),
                  patch.object(cli, "analyze_video", return_value=response) as analyze, patch("builtins.print")):
                cli.main()
            options = analyze.call_args.kwargs
            self.assertEqual((options["profile"], options["imgsz"]), (profile, imgsz))
            for key in ("model_path", "interval", "confidence", "max_gap", "device"):
                self.assertIsNone(options[key])

    def test_rejects_existing_name_in_either_output_location(self) -> None:
        for name, existing_root, other_root in (
            ("existing-frames", self.frames_root, self.analysis_root),
            ("existing-analysis", self.analysis_root, self.frames_root),
        ):
            directory = existing_root / name
            directory.mkdir(parents=True)
            marker = directory / "prior.txt"
            marker.write_bytes(b"existing run")
            with self.subTest(name=name), self.assertRaisesRegex(FileExistsError, "이미 사용 중인 실행 이름"):
                self.analyze(run_name=name)
            self.assertEqual(marker.read_bytes(), b"existing run")
            self.assertFalse((other_root / name).exists())
        self.yolo.assert_not_called()

    def test_unreadable_mp4_cleans_up_run_directories(self) -> None:
        invalid = self.root / "invalid.mp4"
        invalid.write_bytes(b"not a video")
        with self.assertRaisesRegex(RuntimeError, "MP4 파일을 열 수 없습니다"):
            self.analyze(video_path=invalid)
        self.assertEqual(invalid.read_bytes(), b"not a video")
        self.assert_run_removed()
        self.yolo.assert_not_called()

    def test_model_loading_error_cleans_up_run_directories(self) -> None:
        self.yolo.side_effect = ValueError("invalid checkpoint")
        with self.assertRaisesRegex(RuntimeError, r"(?s)YOLO 모델을 불러오지 못했습니다.*invalid checkpoint"):
            self.analyze()
        self.assert_run_removed()

    def test_partial_inference_error_cleans_up_run_directories(self) -> None:
        def failing_predictions(source: str, **kwargs):
            yield next(self.mock_predictions(source))
            raise ValueError("inference interrupted")

        self.model.predict.side_effect = failing_predictions
        with self.assertRaisesRegex(RuntimeError, r"(?s)YOLO 추론에 실패했습니다.*inference interrupted"):
            self.analyze()
        self.assert_run_removed()

    def test_missing_inference_results_are_an_error_even_without_detections(self) -> None:
        self.model.predict.side_effect = lambda source, **kwargs: (row for row in ())
        with self.assertRaisesRegex(RuntimeError, "샘플링 프레임 3장의 추론 결과가 누락"):
            self.analyze()
        self.assert_run_removed()

    def test_summary_write_failure_removes_only_the_current_run(self) -> None:
        self.predictions = {0: [(0, (10, 20, 30, 40), 0.3)]}
        existing = self.analysis_root / "prior" / "summary.json"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"previous summary")
        write_json = video_analysis._write_json

        def fail_summary(path: Path, data) -> None:
            write_json(path, data)
            if path.name == "summary.json":
                raise OSError("summary write failed")

        with patch.object(video_analysis, "_write_json", side_effect=fail_summary):
            with self.assertRaisesRegex(OSError, "summary write failed"):
                self.analyze()
        self.assert_run_removed()
        self.assertEqual(existing.read_bytes(), b"previous summary")

    def assert_run_removed(self) -> None:
        self.assertFalse((self.frames_root / "mock").exists())
        self.assertFalse((self.analysis_root / "mock").exists())
