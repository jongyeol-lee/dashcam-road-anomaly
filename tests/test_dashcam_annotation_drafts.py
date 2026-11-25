import csv
import json
import shutil
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from scripts import annotate_dashcam_drafts as drafts
from scripts.dashcam_box_editor import DraftEditor, Viewport
from scripts.prepare_dashcam_review import write_csv


class BoxGeometryTest(unittest.TestCase):
    def test_roi_area_center_boundary_and_half_open_frame_edges(self):
        cases = (
            ((90, 120, 150, 480), True, False, 0),
            ((200, 590, 400, 648), True, True, 0),
            ((200, 600, 400, 696), True, True, 0.5),
            ((200, 580, 400, 720), False, True, 72 / 140),
            ((200, 648, 400, 700), False, True, 1),
            ((200, 649, 400, 700), False, False, 1),
            ((1919, 1079, 1920, 1080), False, False, 1),
            ((0, 0, 1920, 1080), True, True, 0.4),
        )
        for coords, keep, boundary, outside in cases:
            with self.subTest(coords=coords):
                roi = drafts.make_box("D20", coords)["roi_b"]
                self.assertEqual((roi["center_inside"], roi["touches_boundary"]), (keep, boundary))
                self.assertAlmostEqual(roi["outside_area_fraction"], outside)

    def test_valid_classes_and_invalid_coordinates(self):
        for candidate in ("D00", "D10", "D20", "D40", "판단 보류"):
            self.assertEqual(drafts.make_box(candidate, (1, 1, 2, 2))["candidate_class"], candidate)
        with self.assertRaises(ValueError):
            drafts.make_box("D99", (0, 0, 1, 1))
        for coords in ((1, 2, 1, 4), (1, 4, 4, 2), (-1, 0, 1, 2), (0, 0, 1921, 1080),
                       (0, 0, 100, 1081), (0, 0, 1.5, 2), (False, 0, 1, 2), (1, 2, 3)):
            with self.subTest(coords=coords), self.assertRaises(ValueError):
                drafts.make_box("D00", coords)

    def test_viewport_maps_letterboxing_zoom_and_boundaries_to_source_pixels(self):
        for crop in ((0, 0, 1920, 1080), drafts.DETAIL_CROPS["rear_000525"]):
            view = Viewport.fit(crop, 503, 460)
            self.assertEqual(view.to_source(0, 0), crop[:2])
            self.assertEqual(view.to_source(503, 460), crop[2:])
            self.assertEqual(view.to_source(*view.to_canvas(800, 651)), (800, 651))


class DraftWorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review = Path(cls.enterClassContext(tempfile.TemporaryDirectory())).resolve()
        image = np.zeros((1080, 1920, 3), np.uint8)
        image[:, :, 0] = np.arange(1920, dtype=np.uint16) % 241
        image[:, :, 2] = (np.arange(1080, dtype=np.uint16) % 213)[:, None]
        rows = []
        for image_id in drafts.DETAIL_CROPS:
            camera, frame = image_id.split("_")
            path = Path("frames", camera, f"{image_id}.png")
            (cls.review / path.parent).mkdir(parents=True, exist_ok=True)
            digest = drafts.write_frame(cls.review / path, image)
            rows.append(dict(image_id=image_id, image_path=path.as_posix(), image_sha256=digest,
                             source_video=camera + ".mp4", frame_index=int(frame), estimated_time_sec=int(frame) / 30,
                             similar_frame_group_ids=camera, source_drive_group_id="drive"))
        for name in ("review_manifest.csv", "frame_metadata.csv"):
            write_csv(cls.review / name, tuple(rows[0]), rows)
        cls.initial_csv = (cls.review / "review_manifest.csv").read_bytes()
        cls.root = drafts.prepare(cls.review)

    def workspace(self, *ids):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (root / "originals").mkdir()
        for image_id in ids:
            shutil.copytree(self.root / "labels" / image_id, root / "labels" / image_id)
            shutil.copyfile(self.root / "originals" / f"{image_id}.png", root / "originals" / f"{image_id}.png")
        return root

    def test_background_session_requires_explicit_negative_and_isolates_revisions(self):
        review = Path(self.enterContext(tempfile.TemporaryDirectory()))
        source = next((self.root / "originals").glob("*.png"))
        digest = drafts.sha256_file(source)
        rows = []
        for image_id in drafts.BACKGROUND_IDS:
            camera, index = image_id.split("_")
            path = Path("frames", camera, image_id + ".png")
            (review / path.parent).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, review / path)
            rows.append(dict(image_id=image_id, source_video=camera + ".mp4", frame_index=int(index),
                             estimated_time_sec=int(index) / 30, image_path=path.as_posix(), image_sha256=digest,
                             candidate_group_ids=camera + "_background", similar_frame_group_ids="", source_drive_group_id="drive"))
        for filename in ("review_manifest.csv", "frame_metadata.csv"):
            write_csv(review / filename, tuple(rows[0]), rows)
        root = drafts.prepare(review, background=True)
        for image_id in drafts.BACKGROUND_IDS:
            record, image = drafts.load_latest(root, image_id)
            self.assertEqual((record["review_status"], record["revision"], record["boxes"]), ("미검토", 0, []))
        for status in ("검토 중", drafts.PENDING, drafts.NO_DAMAGE):
            record = drafts.save_revision(root, image, dict(record, review_status=status))
            self.assertEqual(drafts.load_latest(root, image_id)[0]["review_status"], status)
        boxes = [drafts.make_box("D20", (10, 20, 30, 40))]
        with self.assertRaisesRegex(ValueError, "파손 없음"):
            drafts.save_revision(root, image, dict(record, boxes=boxes))
        drafts.save_revision(root, image, dict(record, boxes=boxes, review_status="초안 작성"))
        self.assertEqual(drafts.load_latest(root, image_id)[0]["boxes"], boxes)
        for directory, wrong_id in ((root, "rear_000525"), (review / drafts.DRAFT_DIR, image_id)):
            with self.assertRaises(ValueError):
                drafts.revision_dir(directory, wrong_id, 0)
        with self.assertRaises(FileExistsError):
            drafts.prepare(review, background=True)
        self.assertFalse((review / drafts.DRAFT_DIR).exists())

    def test_all_six_assets_load_and_2x_zoom_contains_only_copied_pixels(self):
        with self.assertRaises(FileExistsError):
            drafts.prepare(self.review)
        self.assertEqual((self.review / "review_manifest.csv").read_bytes(), self.initial_csv)
        for image_id, (x1, y1, x2, y2) in drafts.DETAIL_CROPS.items():
            record, image = drafts.load_latest(self.root, image_id)
            with self.subTest(image=image_id):
                self.assertEqual((record["review_status"], record["boxes"], record["user_notes"]), ("미검토", [], ""))
                self.assertEqual(record["image_sha256"], drafts.sha256_file(self.review / record["image_path"]))
                np.testing.assert_array_equal(image, drafts.read_image(self.review / record["image_path"]))
                zoom = cv2.imread(str(self.root / "zoom" / f"{image_id}.png"))
                np.testing.assert_array_equal(zoom, image[y1:y2, x1:x2].repeat(2, axis=0).repeat(2, axis=1))
                comparison = cv2.imread(str(self.root / "comparisons" / f"{image_id}.jpg"))
                self.assertEqual(comparison.shape[:2], (606, 1920))
                saved_roi = drafts.revision_dir(self.root, image_id, 0) / "roi_comparison.jpg"
                self.assertEqual(cv2.imread(str(saved_roi)).shape[:2], (1148, 3840))

    def test_multiple_boxes_reload_versions_conflict_and_preview_coordinates(self):
        image_id = "rear_000525"
        root = self.workspace(image_id)
        record, image = drafts.load_latest(root, image_id)
        boxes = [drafts.make_box("D20", (100, 590, 240, 706)), drafts.make_box("판단 보류", (1300, 800, 1920, 1080))]
        edited = dict(record, boxes=boxes, user_notes="같은 구간 비교", review_status="검토 중")
        saved = drafts.save_revision(root, image, edited)
        self.assertEqual(drafts.load_latest(root, image_id)[0], saved)
        with self.assertRaises(FileExistsError):
            drafts.save_revision(root, image, edited)
        with self.assertRaisesRegex(ValueError, "검토 상태"):
            drafts.save_revision(root, image, dict(saved, review_status="미검토"))
        with self.assertRaises(ValueError):
            drafts.save_revision(root, image, dict(saved, review_status="GT 확정"))
        path = drafts.revision_dir(root, image_id, 1) / "roi_comparison.jpg"
        actual = drafts.box_comparison(image, saved)
        np.testing.assert_array_equal(cv2.imread(str(path)), cv2.imdecode(cv2.imencode(".jpg", actual)[1], cv2.IMREAD_COLOR))
        for offset in (0, drafts.SIZE[0]):
            panel = actual[68:, offset:offset + 1920]
            for box in saved["boxes"]:
                x1, y1, x2, y2 = box["xyxy"]
                for x, y in ((x1, y1), (x2 - 1, y2 - 1)):
                    self.assertEqual(tuple(panel[y, x]), drafts.BOX_COLOR)
            self.assertFalse(np.array_equal(panel[706, 200], drafts.BOX_COLOR))
        saved_again = drafts.save_revision(root, image, dict(saved, boxes=boxes[1:]))
        self.assertEqual(drafts.load_latest(root, image_id)[0]["boxes"], boxes[1:])
        self.assertEqual(saved_again["revision"], 2)
        self.assertEqual(json.loads((drafts.revision_dir(root, image_id, 1) / "draft.json").read_bytes()), saved)

    def test_failed_preview_does_not_publish_half_a_revision(self):
        root = self.workspace("rear_000525")
        record, image = drafts.load_latest(root, "rear_000525")
        with patch.object(drafts, "write_jpg", side_effect=OSError("disk full")), self.assertRaises(OSError):
            drafts.save_revision(root, image, dict(record, review_status="판단 보류", user_notes="반사"))
        self.assertEqual([p.name for p in (root / "labels/rear_000525").iterdir()], ["0000"])
        self.assertEqual(drafts.load_latest(root, "rear_000525")[0], record)

    def test_prepare_checks_source_digest_and_rolls_back_only_new_output(self):
        path = Path(self.enterContext(tempfile.TemporaryDirectory()))
        shutil.copytree(self.review / "frames", path / "frames")
        for name in ("review_manifest.csv", "frame_metadata.csv"):
            shutil.copyfile(self.review / name, path / name)
        rows = list(csv.DictReader(self.initial_csv.decode("utf-8-sig").splitlines()))
        broken = path / rows[-1]["image_path"]
        broken.write_bytes(b"different")
        with self.assertRaisesRegex(ValueError, "해시"):
            drafts.prepare(path)
        self.assertEqual(sorted(p.name for p in path.iterdir()), ["frame_metadata.csv", "frames", "review_manifest.csv"])
        self.assertEqual(broken.read_bytes(), b"different")

    def test_tk_drag_zoom_edit_cancel_delete_save_and_reopen(self):
        root = self.workspace("rear_000525", "rear_000540")
        try:
            window = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk 디스플레이를 열 수 없음. {exc}")
        self.addCleanup(window.destroy)
        editor = DraftEditor(window, root)
        window.update()
        editor.zoom.set(True)
        editor.redraw()
        view = editor.view
        a, b = [tuple(round(v) for v in view.to_canvas(*p)) for p in ((650, 700), (450, 550))]
        editor.canvas.event_generate("<ButtonPress-1>", x=a[0], y=a[1])
        editor.canvas.event_generate("<B1-Motion>", x=b[0], y=b[1])
        editor.canvas.event_generate("<ButtonRelease-1>", x=b[0], y=b[1])
        expected = [*view.to_source(*b), *view.to_source(*a)]
        self.assertEqual([int(v.get()) for v in editor.coords], expected)
        editor.candidate.set("D20")
        editor.apply()
        editor.set_form("D00", (120, 300, 300, 350))
        editor.apply()
        editor.box_list.selection_set(0)
        editor.choose()
        editor.set_form("D10", (450, 580, 650, 705))
        editor.apply()
        editor.box_list.selection_set(1)
        editor.choose()
        editor.set_form("D40", (1, 1, 2, 2))
        editor.reset_form()
        self.assertEqual(editor.boxes[1]["candidate_class"], "D00")
        editor.roi.set(True)
        editor.redraw()
        editor.status.set("검토 중")
        editor.notes.insert("1.0", "사용자가 입력한 메모")
        self.assertTrue(editor.save())
        editor.navigate(1)
        editor.navigate(-1)
        self.assertEqual(editor.notes.get("1.0", "end-1c"), "사용자가 입력한 메모")
        self.assertEqual(editor.boxes, [drafts.make_box("D10", (450, 580, 650, 705)),
                                        drafts.make_box("D00", (120, 300, 300, 350))])
        editor.box_list.selection_set(1)
        editor.choose()
        editor.delete()
        self.assertTrue(editor.save())
        self.assertEqual(len(drafts.load_latest(root, "rear_000525")[0]["boxes"]), 1)
        self.assertEqual(drafts.latest_revision(self.root, "rear_000525"), 0)


if __name__ == "__main__":
    unittest.main()
