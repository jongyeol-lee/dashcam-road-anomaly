import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scripts import evaluate_dashcam_resolution as experiment
from tests.test_dashcam_evaluation import frame


class ResolutionTest(unittest.TestCase):
    def setUp(self):
        self.frame = frame()
        self.images = {self.frame.image_id: object()}

    def test_actual_tensor_and_default_options(self):
        import torch

        # 외부 모델 없이 실제 infer() 진입점에 입력 크기가 맞거나 틀린 결과를 전달한다.
        for args, actual_size, succeeds in (({}, 640, True), ({"imgsz": 960, "measure_resolution": True}, 960, True),
                                             ({"imgsz": 960, "measure_resolution": True}, 640, False)):
            size = args.get("imgsz", 640)
            model = MagicMock()
            result = MagicMock(orig_shape=(1080, 1920), speed={"inference": 1.0})
            predictor = model.predictor
            predictor.device = "cuda:0"
            predictor.model.fp16 = predictor.model.end2end = False
            predictor.dataset.bs = 1
            predictor.imgsz = (size, size)
            predictor.observed_input = ((1, 3, actual_size, actual_size), "torch.float32", "cuda:0")
            predictor.args = SimpleNamespace(**{**experiment.gt.OPTIONS, "imgsz": size})
            predictor.model.model.parameters.return_value = iter([torch.zeros(1)])
            model.predict.return_value = (r for r in [result])
            fake_torch = MagicMock()
            fake_torch.inference_mode.return_value = nullcontext()
            with self.subTest(args=args, actual_size=actual_size):
                if succeeds:
                    record = experiment.gt.infer("mixed", model, (self.frame,), self.images, fake_torch, **args)
                    self.assertEqual(record["input_tensor_shape"], (1, 3, size, size))
                else:
                    with self.assertRaisesRegex(RuntimeError, "텐서"):
                        experiment.gt.infer("mixed", model, (self.frame,), self.images, fake_torch, **args)
                self.assertEqual(model.predict.call_args.kwargs["imgsz"], size)
                self.assertEqual(experiment.gt.OPTIONS["imgsz"], 640)

    def test_same_gt_matching_and_confidence_filter_at_all_sizes(self):
        box = {"xyxy": self.frame.truth[0].xyxy, "class_id": 2, "confidence": 0.25, "box_id": "p001"}
        for size in experiment.SIZES:
            raw = {"options": {"imgsz": size}, "frames": [{"image_id": self.frame.image_id, "predictions": [box]}]}
            for conf in experiment.gt.CONFIDENCES:
                rows = experiment.evaluate((self.frame,), raw, conf)
                self.assertEqual(experiment.hits(rows), {self.frame.truth[0].box_id})
                self.assertNotIn("roi_b", rows[0]["predictions"][0])
            box_low = {**box, "confidence": 0.249}
            raw["frames"][0]["predictions"] = [box_low]
            low, high = (experiment.hits(experiment.evaluate((self.frame,), raw, c)) for c in experiment.gt.CONFIDENCES)
            self.assertEqual(low - high, {self.frame.truth[0].box_id})
            self.assertFalse(high)

    def test_previous_predictions_survive_json_round_trip_and_detect_delta(self):
        raw = {"frames": [{"image_id": "rear", "predictions": [{"xyxy": (1, 2, 3, 4), "confidence": 0.25}]}]}
        loaded = json.loads(json.dumps(raw))
        self.assertEqual(experiment.predictions(raw), experiment.predictions(loaded))
        loaded["frames"][0]["predictions"][0]["xyxy"][0] += 1
        self.assertNotEqual(experiment.predictions(raw), experiment.predictions(loaded))

    def test_failed_resolution_has_no_partial_metrics_or_retry(self):
        import torch

        model = MagicMock(names=dict(enumerate(experiment.gt.CLASSES)))
        for error, status in ((torch.cuda.OutOfMemoryError("OOM"), "cuda_oom"), (RuntimeError("decode"), "inference_failed")):
            with (patch.object(experiment.gt, "_load_model", return_value=(model, experiment.gt.MODEL_HASHES["mixed"])),
                  patch.object(experiment.gt, "infer", side_effect=error) as infer):
                raw, profile = experiment.measure(1280, (self.frame,), self.images, torch)
                self.assertIsNone(raw)
                self.assertEqual(profile["status"], status)
                infer.assert_called_once()

    def test_existing_run_protected_before_input_reads(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(experiment.gt, "OUTPUT_ROOT", Path(directory)):
            target = Path(directory, "used")
            target.mkdir()
            sentinel = target / "summary.json"
            sentinel.write_bytes(b"previous")
            with self.assertRaises(FileExistsError):
                experiment.run("used")
            self.assertEqual(sentinel.read_bytes(), b"previous")

