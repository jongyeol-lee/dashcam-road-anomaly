import codecs
import csv
import json
import tempfile
import unittest
from itertools import islice
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from scripts import prepare_dashcam_review as review
from scripts.diagnose_video_detection import ROI_COLOR
from scripts.make_test_video import make_test_video
from road_anomaly.video import VideoMetadata, iter_decoded_frames, open_video_capture


class FramePlanningTest(unittest.TestCase):
    def test_includes_window_endpoints_and_rounds_up_to_next_frame_at_30_fps(self) -> None:
        video = VideoMetadata(30.0, 1920, 1080, 1021)
        front, rear_early, rear_late = review.GROUPS[:3]
        for group, expected in (
            (front, [420, 428, 435, 443, 450, 458, 465, 473, 480, 488, 495, 503, 510, 518, 525, 533, 540]),
            (rear_early, [90, 98, 105, 113, 120, 128, 135, 143, 150]),
            (rear_late, [510, 518, 525, 533, 540, 548, 555, 563, 570]),
        ):
            with self.subTest(group=group.name):
                planned = review.plan_frames([group], video)
                self.assertEqual(list(planned), expected)
                for index, [(_, target)] in planned.items():
                    self.assertGreaterEqual(index / video.fps, target)
                    self.assertLess((index - 1) / video.fps, target)

    def test_merges_repeated_targets_and_overlapping_groups_with_the_same_index(self) -> None:
        first = review.ReviewGroup("first", "front", "suspect_window", (0, 0.1, 0.2, 0.2), (0.1,))
        second = review.ReviewGroup("second", "front", "suspect_window", (0.1, 0.4), (0.4,))
        planned = review.plan_frames([first, second], VideoMetadata(2.0, 1920, 1080, 20))
        self.assertEqual(planned, {0: [(first, 0)], 1: [(first, 0.1), (first, 0.2), (second, 0.1), (second, 0.4)]})

    def test_rejects_targets_outside_the_decodable_frame_range(self) -> None:
        for target in (-0.25, 3.0):
            group = review.ReviewGroup("invalid", "front", "suspect_window", (target,), ())
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "영상 범위를 벗어난"):
                review.plan_frames([group], VideoMetadata(10.0, 320, 180, 30))


class DashcamReviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = Path(cls.enterClassContext(tempfile.TemporaryDirectory())).resolve()
        cls.inputs = {camera: make_test_video(cls.source / name) for camera, name in review.VIDEOS.items()}

    def setUp(self) -> None:
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.output = root / "review"
        snapshot = root / "roi_config.json"
        snapshot.write_text(json.dumps({
            "conditions": {"B": {"vertices_normalized": review.ROIS["B"].vertices}},
        }), encoding="utf-8")
        self.enterContext(patch.multiple(
            review, INPUT_ROOT=self.source, OUTPUT_ROOT=self.output, ROI_SNAPSHOT=snapshot, GROUPS=(
                review.ReviewGroup("front_window", "front", "suspect_window", (0.25, 0.28, 0.5), (0.25,)),
                review.ReviewGroup("front_other", "front", "suspect_window", (0.27, 0.75), (0.75,)),
                review.ReviewGroup("rear_window", "rear", "suspect_window", (0.5, 1.0), (0.5,)),
                review.ReviewGroup("rear_background", "rear", "background_candidate", (2.0,), (2.0,)),
            ),
        ))

    def input_hashes(self) -> dict[str, str]:
        return {camera: review.sha256_file(path) for camera, path in self.inputs.items()}

    def test_generates_contact_sheets_lossless_frames_and_excel_review_csv(self) -> None:
        before = self.input_hashes()
        summary = review.prepare_review("valid")
        output = self.output / "valid"
        self.assertEqual(self.input_hashes(), before)
        self.assertTrue(summary["roi_b"]["matches_part531_snapshot"])
        for camera, original_hash in before.items():
            result = summary["sources"][camera]
            self.assertEqual(result["decoded_frame_count"], 30)
            self.assertEqual(result["sha256_before"], original_hash)
            self.assertEqual(result["sha256_after"], original_hash)

        for filename in ("review_manifest.csv", "frame_metadata.csv"):
            self.assertTrue((output / filename).read_bytes().startswith(codecs.BOM_UTF8))
        with (output / "review_manifest.csv").open(encoding="utf-8-sig", newline="") as stream:
            manifest = list(csv.DictReader(stream))
        with (output / "frame_metadata.csv").open(encoding="utf-8-sig", newline="") as stream:
            metadata = {row["image_id"]: row for row in csv.DictReader(stream)}
        self.assertEqual(len(manifest), 6)
        self.assertEqual(len(metadata), len(manifest))
        self.assertEqual(summary["groups"]["front_window"]["extracted_frame_count"], 2)
        self.assertEqual(summary["groups"]["front_other"]["extracted_frame_count"], 2)
        self.assertEqual(metadata["front_000003"]["requested_times_sec"], "0.25|0.27|0.28")
        self.assertEqual(metadata["front_000003"]["candidate_group_ids"], "front_window|front_other")
        self.assertEqual([row["review_priority"] for row in manifest], ["우선"] * 4 + ["추가"] * 2)
        self.assertEqual(len(list((output / "frames").rglob("*.png"))), 6)

        for row in manifest:
            self.assertEqual(row["review_status"], "미검토")
            self.assertEqual((row["user_decision"], row["user_class"], row["user_notes"]), ("", "", ""))
            frame = metadata[row["image_id"]]
            self.assertEqual(row["image_path"], frame["image_path"])
            self.assertEqual(float(frame["estimated_time_sec"]), int(frame["frame_index"]) / 10)
            self.assertAlmostEqual(float(frame["decoder_time_ms"]), int(frame["frame_index"]) * 100, delta=1e-6)
            self.assertEqual(review.sha256_file(output / row["image_path"]), frame["image_sha256"])
            self.assertEqual(cv2.imread(str(output / frame["roi_preview_path"])).shape[:2], (248, 640))

        with open_video_capture(self.inputs["front"]) as (capture, _):
            raw_samples = dict(islice(iter_decoded_frames(capture), 6))
        for index in (3, 5):
            png = cv2.imread(str(output / metadata[f"front_{index:06d}"]["image_path"]))
            self.assertEqual(png.shape, (180, 320, 3))
            np.testing.assert_array_equal(png, raw_samples[index])
        for group in summary["groups"].values():
            sheet = cv2.imread(str(output / group["contact_sheet"]))
            self.assertEqual(sheet.shape[:2], (476, 10 + group["extracted_frame_count"] * 650))

    def test_roi_overlay_uses_part531_boundary_and_preserves_original_pixels(self) -> None:
        image = np.full((100, 180, 3), 160, dtype=np.uint8)
        roi = review.ROIS["B"]
        comparison = review.roi_comparison(image, "Review example", roi)
        self.assertEqual(roi.pixel_vertices(180, 100), ((0, 0), (180, 0), (180, 60), (0, 60)))
        original, overlay = np.hsplit(comparison[68:], 2)
        np.testing.assert_array_equal(original, image)
        np.testing.assert_array_equal(image[80, 90], (160, 160, 160))
        np.testing.assert_array_equal(overlay[40, 90], image[40, 90])
        np.testing.assert_array_equal(overlay[60, 90], ROI_COLOR)
        self.assertTrue(np.all(overlay[80, 90] < image[80, 90]))

    def test_refuses_to_overwrite_a_manifest_after_the_user_has_edited_it(self) -> None:
        review.prepare_review("existing")
        manifest = self.output / "existing" / "review_manifest.csv"
        edited = manifest.read_bytes().replace("미검토".encode(), "사용자 검토 중".encode(), 1)
        manifest.write_bytes(edited)
        with self.assertRaises(FileExistsError):
            review.prepare_review("existing")
        self.assertEqual(manifest.read_bytes(), edited)

    def test_rolls_back_this_run_if_decoder_stops_early(self) -> None:
        self.output.mkdir()
        sentinel = self.output / "preserve.txt"
        sentinel.write_bytes(b"existing")
        before = self.input_hashes()
        with patch.object(review, "iter_decoded_frames", side_effect=lambda cap: islice(iter_decoded_frames(cap), 10)):
            with self.assertRaisesRegex(RuntimeError, "모두 디코딩"):
                review.prepare_review("truncated")
        self.assertFalse((self.output / "truncated").exists())
        self.assertEqual(sentinel.read_bytes(), b"existing")
        self.assertEqual(self.input_hashes(), before)

    def test_aborts_if_source_sha256_changes_during_review_export(self) -> None:
        with patch.object(review, "sha256_file", side_effect=["front before", "rear before", "different after"]):
            with self.assertRaisesRegex(RuntimeError, "원본 MP4가 변경"):
                review.prepare_review("changed")
        self.assertFalse((self.output / "changed").exists())
