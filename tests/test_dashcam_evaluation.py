import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from scripts import evaluate_dashcam_gt as cli
from road_anomaly.dashcam_evaluation import (
    RELEASE_HASHES, EvaluationImage, IdentifiedDetection, UncertainRegion, evaluate_pair,
    identify_prediction, parse_release, read_release, summarize, uncertain_fraction,
)


BOX = (10, 10, 20, 20)


def frame(image_id="rear_000001", scope="positive", *, truth=None, regions=()):
    if truth is None:
        truth = (IdentifiedDetection(2, BOX, box_id=f"{image_id}:gt001"),) if scope == "positive" else ()
    return EvaluationImage(image_id, 2, scope, "Dashcam-Rear.mp4", 1, 1 / 30,
                           None if scope == "excluded" else f"images/{scope}/{image_id}.png",
                           "0" * 64, truth, regions)


def prediction(box_id, xyxy=BOX, score=0.1, class_id=2):
    return IdentifiedDetection(class_id, xyxy, score, box_id=box_id)


def region(box_id, xyxy=BOX):
    return UncertainRegion(box_id, xyxy, "판단 보류")


def evaluate(image, *predictions):
    before, _, _ = evaluate_pair((image,), {image.image_id: predictions}, 0.05, cli.ROI_B)
    return before[0]


def manifest_row(image_id="rear_000001", scope="positive", truth=None):
    row = cli.frame_record(frame(image_id, scope))
    if truth is None:
        truth = [{"box_id": 1, "class": "D20", "xyxy": list(BOX)}] if scope == "positive" else []
    row.update(width=1920, height=1080, ground_truth=truth)
    return row


class EvaluationRulesTest(unittest.TestCase):
    def test_iou_boundary_is_inclusive(self):
        result = evaluate(frame(), prediction("p001", (10, 10, 15, 20)))
        self.assertEqual(result["ground_truth"][0]["iou"], 0.5)
        self.assertEqual(result["ground_truth"][0]["status"], "tp")
        result = evaluate(frame(), prediction("p001", (10, 10, 14.9, 20)))
        self.assertEqual(result["ground_truth"][0]["status"], "fn")

    def test_one_prediction_matches_only_one_gt_and_gt_id_breaks_tie(self):
        image = frame(truth=(IdentifiedDetection(2, BOX, box_id="gt002"), IdentifiedDetection(2, BOX, box_id="gt001")))
        result = evaluate(image, prediction("p001"))
        self.assertEqual([(gt["box_id"], gt["status"]) for gt in result["ground_truth"]], [("gt002", "fn"), ("gt001", "tp")])

    def test_duplicate_predictions_use_iou_then_score_then_prediction_id(self):
        result = evaluate(frame(), prediction("p005", (10, 10, 19, 20), 0.99), prediction("p001", score=0.5),
                          prediction("p004", score=0.75), prediction("p003", score=0.75))
        self.assertEqual(result["ground_truth"][0]["prediction_id"], "p003")
        self.assertEqual([pred["disposition"] for pred in result["predictions"]], ["review", "review", "review", "tp"])

    def test_wrong_class_overlap_is_diagnostic_and_gt_is_still_fn(self):
        result = evaluate(frame(regions=(region("h001"),)), prediction("p001", class_id=3))
        pred, = result["predictions"]
        self.assertEqual(pred["disposition"], "uncertain")
        self.assertEqual(pred["class_confusions"][0]["iou"], 1.0)
        self.assertIsNone(pred["matched_gt_id"])
        self.assertEqual(result["ground_truth"][0]["status"], "fn")
        self.assertEqual(summarize([result])["prediction_count"], 1)

    def test_confirmed_gt_match_takes_priority_over_hold(self):
        result = evaluate(frame(regions=(region("h001"),)), prediction("p001"), prediction("p002"))
        winner, duplicate = result["predictions"]
        self.assertEqual(winner["disposition"], "tp")
        self.assertIsNone(winner["uncertain_fraction"])
        self.assertEqual(duplicate["disposition"], "uncertain")

    def test_hold_boundary_includes_half_of_prediction(self):
        image = frame(scope="uncertain_regions_only", regions=(region("h001", (10, 10, 15, 20)),))
        pred, = evaluate(image, prediction("p001"))["predictions"]
        self.assertEqual(pred["uncertain_fraction"], 0.5)
        self.assertEqual(pred["disposition"], "uncertain")

    def test_hold_area_uses_union_and_intersects_prediction(self):
        pred = prediction("p001", (0, 0, 10, 10))
        regions = (region("h001", (0, 0, 6, 5)), region("h002", (4, 0, 12, 5)), region("h003", (2, 1, 3, 2)))
        self.assertEqual(uncertain_fraction(pred, regions), 0.5)
        same_region_twice = (region("h001", (0, 0, 3, 10)), region("h002", (0, 0, 3, 10)))
        self.assertEqual(uncertain_fraction(pred, same_region_twice), 0.3)

    def test_explicit_background_scope_controls_fp(self):
        image = frame(scope="normal_background")
        metrics = summarize([evaluate(image, prediction("p001"), prediction("p002"))])
        self.assertEqual(metrics["dispositions"]["background_fp"], 2)
        self.assertEqual(metrics["background_images_with_fp"], 1)
        self.assertEqual(metrics["background_fp_per_image"], 2)
        hold = frame(scope="uncertain_regions_only", regions=(region("h001", (10, 10, 14, 20)),))
        metrics = summarize([evaluate(hold, prediction("p003"))])
        self.assertEqual(metrics["dispositions"]["review"], 1)
        self.assertEqual(metrics["dispositions"]["background_fp"], 0)
        self.assertIsNone(metrics["background_fp_per_image"])

    def test_excluded_images_are_not_evaluated_and_extra_predictions_fail(self):
        active = frame()
        excluded = frame("rear_000002", "excluded")
        inputs = {active.image_id: ()}
        before, after, _ = evaluate_pair((active, excluded), inputs, 0.05, cli.ROI_B)
        self.assertEqual([row["image_id"] for row in before], [active.image_id])
        self.assertEqual(before, after)
        with self.assertRaisesRegex(ValueError, "범위 밖"):
            evaluate_pair((active, excluded), {**inputs, excluded.image_id: ()}, 0.05, cli.ROI_B)

    def test_roi_accepts_center_at_648_and_detects_boundary_crossing(self):
        image = frame(scope="normal_background")
        inside = prediction("p001", (10, 638, 30, 658))
        outside = prediction("p002", (10, 639, 30, 659))
        before, after, effect = evaluate_pair((image,), {image.image_id: (inside, outside)}, 0.05, cli.ROI_B)
        self.assertTrue(before[0]["predictions"][0]["roi_b"]["keep"])
        self.assertEqual([p["box_id"] for p in after[0]["predictions"]], ["p001"])
        self.assertEqual(effect["boundary_prediction_ids"], ["p001", "p002"])
        self.assertEqual(effect["removed_prediction_ids"]["background_fp"], ["p002"])

    def test_roi_recomputes_matches_and_distinguishes_removed_tp_from_lost_gt(self):
        box = (10, 620, 110, 680)
        rematched = frame(truth=(IdentifiedDetection(2, box, box_id="gt001"),))
        lost = frame("rear_000002", truth=(IdentifiedDetection(2, box, box_id="gt002"),))
        raw = {rematched.image_id: (prediction("p001", box), prediction("p002", (10, 618, 110, 675))),
               lost.image_id: (prediction("p003", box),)}
        before, after, effect = evaluate_pair((rematched, lost), raw, 0.05, cli.ROI_B)
        self.assertEqual(summarize(before)["classes"]["D20"]["tp"], 2)
        self.assertEqual(summarize(after)["classes"]["D20"], {"predictions": 1, "gt": 2, "tp": 1, "fn": 1, "recall": 0.5})
        self.assertEqual(effect["removed_prediction_ids"]["tp"], ["p001", "p003"])
        self.assertEqual(effect["gt_rematched"], [{"gt_id": "gt001", "previous_prediction_id": "p001", "new_prediction_id": "p002"}])
        self.assertEqual(effect["gt_lost"], [{"gt_id": "gt002", "previous_prediction_id": "p003", "new_prediction_id": None}])

    def test_confidence_thresholds_include_equal_and_share_prediction_ids(self):
        image = frame(scope="normal_background")
        raw = {image.image_id: (prediction("p001", score=0.05), prediction("p002", score=0.2499),
                                prediction("p003", score=0.25))}
        primary, _, _ = evaluate_pair((image,), raw, 0.05, cli.ROI_B)
        secondary, _, _ = evaluate_pair((image,), raw, 0.25, cli.ROI_B)
        self.assertEqual([pred["box_id"] for pred in primary[0]["predictions"]], ["p001", "p002", "p003"])
        self.assertEqual([pred["box_id"] for pred in secondary[0]["predictions"]], ["p003"])

    def test_empty_results_retain_image_and_fn_and_undefined_recall_is_null(self):
        metrics = summarize([evaluate(frame())])
        self.assertEqual(metrics["image_count"], 1)
        self.assertEqual(metrics["prediction_count"], 0)
        self.assertEqual(metrics["classes"]["D20"]["fn"], 1)
        self.assertEqual(metrics["classes"]["D20"]["recall"], 0.0)
        self.assertIsNone(metrics["classes"]["D40"]["recall"])


class InputValidationTest(unittest.TestCase):
    def test_parse_valid_approved_d40_draft_as_hold_region(self):
        image_row = manifest_row()
        hold = {"image_id": image_row["image_id"], "revision": 2, "box_id": 2,
                "xyxy": [15, 15, 30, 30], "stored_class": "D40"}
        parsed, = parse_release([image_row], [hold])
        self.assertEqual(len(parsed.truth), 1)
        self.assertEqual(parsed.truth[0].class_id, 2)
        self.assertEqual(parsed.uncertain_regions[0].stored_class, "D40")
        with self.assertRaisesRegex(ValueError, "revision"):
            parse_release([image_row], [{**hold, "revision": 1}])
        with self.assertRaisesRegex(ValueError, "revision"):
            parse_release([image_row], [{**hold, "image_id": "rear_000002"}])

    def test_parse_rejects_invalid_gt_and_region_coordinates_or_class(self):
        original, = manifest_row()["ground_truth"]
        for changed in ({"class": "D40"}, {"xyxy": [10, 10, 10, 20]}, {"xyxy": [10, 10, 1921, 20]},
                        {"xyxy": [10, 10, 20.0, 20]}, {"xyxy": None}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                parse_release([manifest_row(truth=[{**original, **changed}])], [])
        hold = {"image_id": "rear_000001", "revision": 2, "box_id": 2, "stored_class": "판단 보류", "xyxy": list(BOX)}
        with self.assertRaisesRegex(ValueError, "좌표"):
            parse_release([manifest_row()], [{**hold, "xyxy": [0, 0, 1, -1]}])

    def test_predictor_output_rejects_invalid_class_score_and_coordinates(self):
        for label, box, score in ((2.5, BOX, 0.05), (4, BOX, 0.05), (True, BOX, 0.05),
                                  (2, BOX, float("nan")), (2, (10, 10, 20, 1081), 0.05)):
            with self.subTest(label=label, box=box, score=score), self.assertRaises(ValueError):
                identify_prediction("mixed", "rear_000001", 1, label, box, score)

    def test_release_bytes_must_match_before_parsing(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        path = root / next(iter(RELEASE_HASHES))
        path.write_text(json.dumps({"images": [manifest_row()]}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA-256 불일치"):
            read_release(root)

    def test_published_png_must_match_before_decoding(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        image = frame()
        path = root / image.image_path
        path.parent.mkdir(parents=True)
        path.write_bytes(b"altered image")
        with patch.object(cli, "RELEASE", root), self.assertRaisesRegex(ValueError, "SHA-256 불일치"):
            cli.read_frame(image)

    def test_model_hash_mismatch_stops_before_loading_and_output_creation(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        model = root / "baseline.pt"
        model.write_bytes(b"different weights")
        expected = sha256(b"approved weights").hexdigest()
        output = root / "outputs"
        with (patch.object(cli, "PROJECT", root), patch.object(cli, "OUTPUT_ROOT", output),
              patch.object(cli, "MODEL_PATHS", {"baseline": model}), patch.object(cli, "MODEL_HASHES", {"baseline": expected}),
              patch.object(cli, "read_release", return_value=(frame(),)), patch.object(cli, "read_frame"),
              patch.object(cli, "_load_model") as load_model):
            with self.assertRaisesRegex(ValueError, "SHA-256 불일치"):
                cli.run_evaluation("test_run")
        load_model.assert_not_called()
        self.assertFalse(output.exists())

    def test_existing_run_is_preserved(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        existing = root / "old"
        existing.mkdir()
        data = existing / "summary.json"
        data.write_bytes(b"existing")
        with patch.object(cli, "OUTPUT_ROOT", root), self.assertRaises(FileExistsError):
            cli.run_evaluation("old")
        self.assertEqual(data.read_bytes(), b"existing")
