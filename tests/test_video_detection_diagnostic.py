import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from scripts import diagnose_video_detection as diagnostic
from scripts.make_test_video import make_test_video


class VideoDetectionDiagnosticTest(unittest.TestCase):
    def test_decodes_exact_frame_indices_and_rejects_missing_frames(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = make_test_video(Path(temp) / "test.mp4")
            fps, frames = diagnostic.decode_frames(path, {0, 10, 17})
            self.assertEqual(fps, 10)
            self.assertEqual(list(frames), [0, 10, 17])
            self.assertEqual([frame.time_sec for frame in frames.values()], [0.0, 1.0, 1.7])
            for frame, expected_ms in zip(frames.values(), (0.0, 1000.0, 1700.0), strict=True):
                self.assertAlmostEqual(frame.decoder_time_ms, expected_ms, delta=1e-6)

            capture = cv2.VideoCapture(str(path))
            try:
                for index in range(18):
                    ok, expected = capture.read()
                    self.assertTrue(ok)
                    if index in frames:
                        np.testing.assert_array_equal(frames[index].image, expected)
            finally:
                capture.release()
            with self.assertRaisesRegex(RuntimeError, "프레임 30"):
                diagnostic.decode_frames(path, {30})

    def test_crops_exact_original_pixels_and_rejects_invalid_roi(self) -> None:
        image = np.arange(10 * 12 * 3, dtype=np.uint8).reshape(10, 12, 3)
        crop = diagnostic.crop_image(image, (3, 4, 11, 8))
        np.testing.assert_array_equal(crop, image[4:8, 3:11])
        self.assertTrue(crop.flags.c_contiguous)
        self.assertFalse(np.shares_memory(crop, image))
        for roi in ((-1, 1, 4, 5), (5, 1, 4, 5), (0, 2, 12, 11), (0, 2, 13, 9)):
            with self.subTest(roi=roi), self.assertRaisesRegex(ValueError, "Crop 좌표"):
                diagnostic.crop_image(image, roi)

    def test_restores_all_box_coordinates_and_preserves_empty_and_failed_csv_rows(self) -> None:
        result = SimpleNamespace(
            orig_shape=(87, 297),
            boxes=SimpleNamespace(
                xyxy=np.array([[1.5, 2.5, 10.5, 20.5], [15, 20, 40, 47]]),
                cls=np.array([2, 0]),
                conf=np.array([0.125, 0.75]),
            ),
        )
        boxes = diagnostic.collect_boxes(result, (810, 498))
        self.assertEqual([box.original_xyxy for box in boxes], [
            (811.5, 500.5, 820.5, 518.5), (825.0, 518.0, 850.0, 545.0),
        ])
        self.assertEqual([box.confidence for box in boxes], [0.125, 0.75])

        image = np.zeros((12, 12, 3), dtype=np.uint8)
        frame = diagnostic.DecodedFrame(517, 17.250567, 17250.567, image)
        trials = {
            "A1": {"B": diagnostic.Measurement("ok")},
            "A3": {"B": diagnostic.Measurement("cuda_oom", error="CUDA out of memory")},
            "B": {"B": diagnostic.Measurement("ok", boxes=boxes, input_tensor_shape=(1, 3, 640, 640))},
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "results.csv"
            diagnostic.write_results(path, trials, {"B": frame})
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            with self.assertRaises(FileExistsError):
                diagnostic.write_results(path, trials, {"B": frame})
        self.assertEqual([row["detection_count"] for row in rows], ["0", "", "2", "2"])
        self.assertEqual([row["status"] for row in rows], ["ok", "cuda_oom", "ok", "ok"])
        self.assertEqual([row["class_name"] for row in rows], ["", "", "D20", "D00"])
        self.assertEqual(rows[2]["input_x1"], "1.5")
        self.assertEqual(rows[2]["original_x1"], "811.5")
        self.assertEqual(rows[2]["input_tensor_shape"], "1x3x640x640")

    def test_oom_skips_remaining_frames_of_its_condition_and_continues_crop_and_control(self) -> None:
        image = np.zeros((12, 12, 3), dtype=np.uint8)
        frames = {key: diagnostic.DecodedFrame(index, 0.0, 0.0, image) for key, (index, _) in diagnostic.TARGETS.items()}
        crops = dict.fromkeys(frames, image)

        def predict(model, predictor, image, imgsz, offset):
            if imgsz == 1280:
                return diagnostic.Measurement("cuda_oom")
            return diagnostic.Measurement("ok")

        with patch.object(diagnostic, "measure_prediction", side_effect=predict) as mocked:
            trials = diagnostic.run_conditions(None, None, frames, crops, image)
        self.assertEqual([item.status for item in trials["A3"].values()], ["cuda_oom", "skipped_after_oom", "skipped_after_oom"])
        self.assertEqual([item.status for item in trials["B"].values()], ["ok", "ok", "ok"])
        self.assertEqual(len(trials["C"]), 1)
        expected = [(640, (0, 0))] * 3 + [(960, (0, 0))] * 3 + [(1280, (0, 0))]
        expected.extend((640, roi[:2]) for _, roi in diagnostic.TARGETS.values())
        expected.append((640, (0, 0)))
        self.assertEqual([call.args[3:] for call in mocked.call_args_list], expected)

    def test_render_panel_distinguishes_crop_outline_from_actual_predictions(self) -> None:
        image = np.zeros((120, 160, 3), dtype=np.uint8)
        no_detections = diagnostic.render_panel(image, "Original", "No detection", roi=(20, 30, 100, 105))
        detection = diagnostic.render_panel(
            image, "Crop", "1 detection", [((30, 45, 50, 70), "D20 0.25")], (20, 30, 100, 105),
        )
        self.assertTrue(np.any(np.all(no_detections == diagnostic.ROI_COLOR, axis=-1)))
        self.assertFalse(np.any(np.all(no_detections == diagnostic.BOX_COLOR, axis=-1)))
        self.assertTrue(np.any(np.all(detection == diagnostic.ROI_COLOR, axis=-1)))
        self.assertTrue(np.any(np.all(detection == diagnostic.BOX_COLOR, axis=-1)))
