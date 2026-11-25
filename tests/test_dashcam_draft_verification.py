import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from scripts import annotate_dashcam_drafts as drafts
from scripts import verify_dashcam_drafts as audit


class ApprovalReviewTest(unittest.TestCase):
    def test_final_background_requires_reviewed_bytes_and_an_explicit_empty_negative(self):
        box = drafts.make_box(drafts.PENDING, (25, 40, 60, 80))
        for image_id, status, boxes, disposition, negative, excluded in (
            ("front_000210", drafts.NO_DAMAGE, [], "normal_background_candidate", True, False),
            ("front_000345", drafts.PENDING, [box], "uncertain_regions_only", False, False),
            ("front_000075", drafts.PENDING, [], "whole_image_hold", False, True),
        ):
            entry = dict(image_id=image_id, revision=1, boxes=boxes, review_status=status, user_notes="사용자 검토",
                         latest_draft_sha256=audit.BACKGROUND_REVIEWED_SHA[image_id], similar_frame_group_ids="",
                         duplicate_pairs=[])
            result = audit.final_entry(entry, {})
            self.assertEqual((result["image_disposition"], result["normal_background_candidate"],
                              result["exclude_from_evaluation"]), (disposition, negative, excluded))
            self.assertEqual([b["xyxy"] for b in result["uncertain_regions"]], [b["xyxy"] for b in boxes])
            self.assertEqual((result["candidate_boxes"], result["approval_status"]), ([], "pending"))
            with self.assertRaisesRegex(ValueError, "저장본이 변경"):
                audit.final_entry(dict(entry, latest_draft_sha256="changed"), {})
            for invalid in (dict(review_status="미검토"), dict(review_status="검토 중"),
                            dict(review_status=drafts.NO_DAMAGE, boxes=[box])):
                with self.assertRaisesRegex(ValueError, "판정·박스"):
                    audit.final_entry(dict(entry, **invalid), {})

    def test_final_d40_exception_is_a_pending_decision_bound_to_v2(self):
        image_id = "rear_000120"
        boxes = [drafts.make_box(c, (20 * i, 5, 20 * i + 10, 15))
                 for i, c in enumerate(("D20", "D40", drafts.PENDING, drafts.PENDING))]
        entry = dict(image_id=image_id, revision=2, review_status="초안 작성", boxes=boxes,
                     similar_frame_group_ids="rear_03_05", duplicate_pairs=[],
                     latest_draft_sha256=audit.REVISED_SHA[image_id])
        entry.update(audit.reconcile(entry, entry["latest_draft_sha256"]))
        prior = {image_id: entry.copy()}
        result = audit.final_entry(entry, prior)
        self.assertEqual([b["box_id"] for b in result["candidate_boxes"]], [1])
        self.assertEqual([b["box_id"] for b in result["uncertain_regions"]], [2, 3, 4])
        decision, = result["additional_confirmation"]
        self.assertEqual((decision["box_id"], decision["stored_class"], decision["xyxy"], decision["approval_status"]),
                         (2, "D40", boxes[1]["xyxy"], "pending"))
        self.assertIsNone(result["confirmed_damage_case_id"])
        with self.assertRaisesRegex(ValueError, "v2"):
            audit.final_entry(dict(entry, revision=3), prior)
        with self.assertRaisesRegex(ValueError, "중복"):
            audit.final_entry(dict(entry, duplicate_pairs=[{"box_ids": [1, 2]}]), prior)

    def test_final_review_preserves_existing_manifest(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        target = root / audit.FINAL_RUN / "approval_manifest.json"
        target.parent.mkdir()
        target.write_bytes(b"existing review")
        with self.assertRaises(FileExistsError):
            audit.prepare(root, root, final_review=True)
        self.assertEqual(target.read_bytes(), b"existing review")

    def test_revised_versions_keep_the_raw_class_and_resolve_the_unlocated_note(self):
        for image_id, classes, expected_holds in (
            ("rear_000120", ["D20", "D40", drafts.PENDING, drafts.PENDING], [2, 3, 4]),
            ("rear_000540", ["D20", drafts.PENDING], [2]),
        ):
            record = dict(image_id=image_id, review_status="초안 작성",
                          boxes=[drafts.make_box(c, (1, 2, 3, 4)) for c in classes])
            result = audit.reconcile(record, audit.REVISED_SHA[image_id])
            self.assertEqual([x["candidate_class"] for x in result["candidate_boxes"]], ["D20"])
            self.assertEqual([x["box_id"] for x in result["uncertain_regions"]], expected_holds)
            self.assertEqual(result["uncertain_regions"][0]["candidate_class"], classes[1])
            self.assertEqual(result["uncertain_without_coordinates"], [])

    def test_conflicting_d40_fields_remain_intact_and_are_withheld(self):
        boxes = [drafts.make_box(c, (i, 580, i + 12, 680)) for i, c in enumerate(("D20", "D40", "D40", "D40"))]
        record = dict(image_id="rear_000120", boxes=boxes, review_status="초안 작성")
        result = audit.reconcile(record, audit.REVIEWED_SHA["rear_000120"])
        self.assertEqual([b["box_id"] for b in result["candidate_boxes"]], [1, 2])
        self.assertTrue(result["candidate_boxes"][1]["requires_additional_D40_confirmation"])
        self.assertEqual([(b["box_id"], b["candidate_class"]) for b in result["uncertain_regions"]], [(3, "D40"), (4, "D40")])
        self.assertEqual([b["candidate_class"] for b in record["boxes"]], ["D20", "D40", "D40", "D40"])
        newer = audit.reconcile(record, "new version")
        self.assertFalse(newer["reviewed_snapshot"])
        self.assertEqual(len(newer["uncertain_regions"]), 4)
        self.assertFalse(newer["candidate_boxes"])

    def test_whole_hold_and_unlocated_note_are_distinct_from_box_level_hold(self):
        for image_id, boxes, status, expected in (
            ("rear_000135", [], "판단 보류", (True, 0, 0)),
            ("rear_000555", [drafts.make_box("판단 보류", (3, 5, 12, 25))], "초안 작성", (False, 1, 0)),
            ("rear_000540", [drafts.make_box("D20", (3, 5, 12, 25))], "초안 작성", (False, 0, 1)),
        ):
            result = audit.reconcile(dict(image_id=image_id, review_status=status, boxes=boxes), audit.REVIEWED_SHA[image_id])
            self.assertEqual((result["whole_image_hold"], len(result["uncertain_regions"]),
                              len(result["uncertain_without_coordinates"])), expected)
            if result["whole_image_hold"]:
                self.assertEqual(result["image_disposition"], "exclude_pending_confirmation")
                self.assertEqual(result["candidate_boxes"], [])

    def test_duplicate_candidates_are_reported_across_classes_without_removal(self):
        coords = [(1, 1, 101, 101), (1, 1, 101, 101), (3, 1, 101, 101), (101, 1, 201, 101)]
        boxes = [drafts.make_box(c, b) for c, b in zip(("D20", "D40", "판단 보류", "D20"), coords, strict=True)]
        pairs = audit.duplicates(boxes)
        self.assertEqual([(p["box_ids"], p["exact"]) for p in pairs], [([1, 2], True), ([1, 3], False), ([2, 3], False)])
        self.assertEqual(len(boxes), 4)

    def test_excluded_frame_cannot_enter_background_queue(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        ids = ["rear_000135", *(f"frame_{i}" for i in range(42))]
        rows = {name: dict(image_id=name, candidate_group_ids="rear_background" if i < 8 else "rear_03_05")
                for i, name in enumerate(ids)}
        with patch.object(audit, "by_id", return_value=rows), self.assertRaisesRegex(ValueError, "배경 검토"):
            audit.prepare(root, root / "output")
        self.assertFalse((root / "output").exists())

    def test_checks_saved_roi_class_bounds_and_states(self):
        b = drafts.make_box("D20", (200, 600, 400, 696))
        self.assertEqual(b["roi_b"], dict(center_inside=True, touches_boundary=True, outside_area_fraction=0.5))
        row = dict(image_id="rear_000525", revision=1, user_notes="", review_status="초안 작성", boxes=[b])
        audit.validate(row, {"revision": 1})
        for edit in (dict(boxes=[dict(b, candidate_class="unknown")]), dict(boxes=[dict(b, xyxy=[1, 2, 1, 3])]),
                     dict(boxes=[dict(b, xyxy=[1, 2, 1921, 1080])]), dict(review_status="미검토"),
                     dict(boxes=[dict(b, roi_b=dict(b["roi_b"], center_inside=False))]), dict(revision=2)):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                audit.validate(dict(row, **edit), {"revision": 1})

    def test_readonly_history_replays_saved_previews_and_preserves_groups(self):
        review = Path(self.enterContext(tempfile.TemporaryDirectory()))
        root = review / drafts.DRAFT_DIR
        image_id = "rear_000525"
        image = np.full((1080, 1920, 3), 100, np.uint8)
        source = review / "frames/rear/rear_000525.png"
        source.parent.mkdir(parents=True)
        digest = drafts.write_frame(source, image)
        (root / "originals").mkdir(parents=True)
        (root / "originals" / source.name).write_bytes(source.read_bytes())
        row = dict(image_id=image_id, source_video="Dashcam-Rear.mp4", image_path=source.relative_to(review).as_posix(),
                   estimated_time_sec="17.5", frame_index="525", candidate_group_ids="rear_17_19",
                   similar_frame_group_ids="rear_17_19", source_drive_group_id="dashcam_validation_front_rear")
        metadata = dict(row, camera="rear", image_sha256=digest, width="1920", height="1080", fps="30.0")
        initial = dict(row, revision=-1, kind="manual_annotation_draft", frame_index=525, estimated_time_sec=17.5,
                       width=1920, height=1080, image_sha256=digest, detail_crop_xyxy=list(drafts.DETAIL_CROPS[image_id]),
                       roi_b_vertices_normalized=drafts.ROI_B.vertices, boxes=[], user_notes="", review_status="미검토")
        baseline = drafts.save_revision(root, image, initial)
        drafts.save_revision(root, image, dict(baseline, boxes=[drafts.make_box("D20", (440, 550, 850, 680))],
                                               review_status="초안 작성", user_notes="연속 관찰"))
        before = {p: drafts.sha256_file(p) for p in review.rglob("*") if p.is_file()}
        result, _ = audit.audit_image(review, row, metadata)
        self.assertEqual([v["box_count"] for v in result["history"]], [0, 1])
        self.assertEqual((result["source_drive_group_id"], result["similar_frame_group_ids"]),
                         ("dashcam_validation_front_rear", "rear_17_19"))
        self.assertEqual(before, {p: drafts.sha256_file(p) for p in review.rglob("*") if p.is_file()})
        old = drafts.revision_dir(root, image_id, 0)
        (old / "roi_comparison.jpg").write_bytes(b"incorrect preview")
        with self.assertRaisesRegex(ValueError, "미리보기"):
            audit.audit_image(review, row, metadata)
        data = json.loads((old / "draft.json").read_bytes())
        (old / "draft.json").write_text(json.dumps(dict(data, source_drive_group_id="other")), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source_drive_group_id"):
            audit.audit_image(review, row, metadata)


if __name__ == "__main__":
    unittest.main()
