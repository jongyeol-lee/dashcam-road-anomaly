import csv
import json
import tempfile
import unittest
from collections import Counter
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np

from scripts import prepare_rdd2022_czech_japan as pilot
from tests.test_rdd2022 import jpeg, xml


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def photo(member: str, dhash: int, *, jpeg_hash: str = "", pixel_hash: str = "") -> pilot.Photo:
    image = pilot.Image(member, 80, 60, jpeg_hash or member, dhash)
    return pilot.Photo(image, pixel_hash or member, 0, np.zeros((32, 32, 3), dtype=np.uint8))


class PilotGroupingTest(unittest.TestCase):
    def test_index_preserves_exact_and_dhash_boundary_pairs_and_checks_neighbors(self) -> None:
        eight_bits = sum(1 << bit for bit in (0, 15, 30, 44, 58, 72, 86, 100))
        nine_bits = eight_bits | 1 << 114
        images = [
            photo("Czech/val/Czech_01.jpg", 0, pixel_hash="duplicate_pixels"),
            photo("Japan/train/images/Japan_000100.jpg", eight_bits),
            photo("Japan/train/images/Japan_000200.jpg", nine_bits),
            photo("Japan/train/images/Japan_000300.jpg", (1 << 128) - 1, pixel_hash="duplicate_pixels"),
            photo("Japan/train/images/Japan_9.jpg", 0),
            photo("Japan/train/images/Japan_10.jpg", nine_bits),
        ]
        pairs, _ = pilot._duplicate_pairs({item.image.member: item for item in images})
        by_pair = {frozenset(Path(row[key]).stem for key in ("a", "b")): row for row in pairs}
        self.assertEqual(by_pair[frozenset(("Czech_01", "Japan_000100"))]["dhash_distance"], 8)
        self.assertNotIn(frozenset(("Czech_01", "Japan_000200")), by_pair)
        exact = by_pair[frozenset(("Czech_01", "Japan_000300"))]
        self.assertTrue(exact["pixel_sha256_equal"])
        self.assertFalse(exact["dhash_candidate"])
        adjacent = by_pair[frozenset(("Japan_9", "Japan_10"))]
        self.assertTrue(adjacent["adjacent_scene_candidate"])
        self.assertFalse(adjacent["dhash_candidate"])
        self.assertEqual(adjacent["filename_gap"], 1)

    def test_group_links_are_transitive_and_holdout_assignments_are_reproducible(self) -> None:
        czech_member = "Czech/test/Czech_01.jpg"
        czech_photo = photo(czech_member, 0)
        czech = {czech_member: pilot.CzechSample(czech_photo, "test", Path("img"), Path("label"), "", 0, {})}
        names = [f"Japan/train/images/Japan_{index:04}.jpg" for index in range(14)]
        photos = {member: photo(member, index) for index, member in enumerate(names)}
        photos[czech_member] = czech_photo
        pairs = [
            {"a": a, "b": b, "pixel_sha256_equal": False}
            for a, b in ((czech_member, names[0]), (names[0], names[1]), (names[2], names[3]))
        ]

        def assign(order: list[str]):
            japan = {key: pilot.JapanSample(key, "", photos[key], counts=Counter()) for key in order}
            groups, splits, _ = pilot._group_and_split(japan, czech, photos, pairs)
            for member in names[:2]:
                self.assertEqual(japan[member].issues[0].type, "czech_eval_overlap")
            return groups, splits

        groups, splits = assign(names)
        self.assertEqual((groups, splits), assign(list(reversed(names))))
        self.assertNotIn(names[0], splits)
        self.assertNotIn(names[1], splits)
        self.assertEqual(splits[names[2]], splits[names[3]])
        self.assertEqual(set(splits.values()), {"train", "val", "test"})
        selected = pilot._pilot_selection(photos, splits, groups, limit=6)
        self.assertEqual(selected, pilot._pilot_selection(photos, dict(reversed(list(splits.items()))), groups, limit=6))
        self.assertEqual(len({groups[member] for member in selected}), 6)
        self.assertTrue(all(splits[member] == "train" for member in selected))


class PilotBuildTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "데이터 & 검사"
        self.root.mkdir()
        self.data_dir = self.root / "output"
        self.processed = self.data_dir / "processed" / pilot.PILOT
        self.czech_dir = self.root / "czech"
        self.czech_dir.mkdir()
        (self.czech_dir / "data.yaml").write_bytes(pilot._dataset_yaml(pilot.SPLITS))
        self.baseline_rows = []
        czech_images = {}
        for index, split in enumerate(pilot.SPLITS):
            name = f"Czech_{index:06d}"
            image = jpeg(index)
            czech_images[split] = image
            for folder, suffix, data in (("images", ".jpg", image), ("labels", ".txt", b"0 0.25 0.25 0.5 0.5\n")):
                path = self.czech_dir / folder / split / (name + suffix)
                path.parent.mkdir(parents=True)
                path.write_bytes(data)
            self.baseline_rows.append(dict(
                source_image=f"Czech/train/images/{name}.jpg",
                source_annotation=f"Czech/train/annotations/xmls/{name}.xml",
                split=split, group_id=name, sha256=sha256(image).hexdigest(), D00=1, D10=0, D20=0, D40=0,
            ))
        self.manifest = self.root / "split_manifest.csv"
        self.manifest.write_bytes(pilot._csv_bytes(tuple(self.baseline_rows[0]), self.baseline_rows))
        self.visual = self.root / "visual_review_manifest.csv"
        self.visual.write_bytes(pilot._csv_bytes(("country", "source_image", "label_quality"), [{
            "country": "Japan", "source_image": f"{pilot.JAPAN_IMAGES}/Japan_000103.jpg", "label_quality": "라벨 오류 의심",
        }]))
        self.zip_path = self.root / "Japan.zip"
        with ZipFile(self.zip_path, "x") as archive:
            def add(index: int, image: bytes, boxes: tuple):
                stem = f"Japan_{index:06}"
                archive.writestr(f"{pilot.JAPAN_IMAGES}/{stem}.jpg", image)
                archive.writestr(f"{pilot.JAPAN_XMLS}/{stem}.xml", xml(stem + ".jpg", boxes))

            for index in range(30):
                class_name = pilot.CLASSES[index % 4]
                boxes = ((class_name, 0, 0, 40, 30), ("D50", 30, 45, 60, 60)) if index % 5 else ()
                add(index, jpeg(index + 100), boxes)
            add(101, jpeg(301), (("D43", 0, 0, 30, 20),))
            add(102, jpeg(302), (("D20", 3, 4, 3, 21), ("D00", 1, 2, 6, 11)))
            add(103, jpeg(303), (("D00", 0, 0, 30, 20),))
            for index, split in enumerate(pilot.SPLITS, 104):
                add(index, czech_images[split], ())
            archive.writestr("Japan/test/images/Japan_999999.jpg", b"not used as labelled data")
        self.inputs = [self.zip_path, self.manifest, self.visual, *(path for path in self.czech_dir.rglob("*") if path.is_file())]
        self.before = {path: pilot._sha256_file(path) for path in self.inputs}

    def build(self) -> dict:
        with patch.object(pilot, "PILOT_LIMIT", 14):
            return pilot.prepare_pilot(self.zip_path, self.czech_dir, self.manifest, self.visual, self.data_dir)

    def assert_inputs_preserved(self) -> None:
        self.assertEqual(self.before, {path: pilot._sha256_file(path) for path in self.inputs})

    def test_build_copies_fixed_czech_and_exports_only_eligible_japan_pairs(self) -> None:
        with patch.object(pilot, "_verify_ultralytics", return_value={"fixture": True}):
            report = self.build()
            with self.assertRaises(FileExistsError):
                self.build()
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["pilot"]["images"], 14)
        self.assertEqual(report["japan_scan"]["eligible_for_splits"], 30)
        self.assertEqual(report["japan_scan"]["official_test_images"], 1)
        self.assertEqual(report["japan_scan"]["valid_other_only"], 1)
        self.assertEqual(report["czech_preservation"]["images"], 3)
        self.assert_inputs_preserved()
        rows = read_csv(self.processed / "split_manifest.csv")
        output = self.data_dir / "yolo"
        czech_rows = [row for row in rows if row["country"] == "Czech"]
        self.assertEqual({row["split"] for row in czech_rows}, set(pilot.SPLITS))
        for row in czech_rows:
            for kind in ("image", "label"):
                self.assertEqual((output / row["dataset"] / row[f"output_{kind}"]).read_bytes(),
                                 Path(row[f"baseline_{kind}"]).read_bytes())
        for row in (row for row in rows if row["country"] == "Japan" and row["dataset"]):
            data = (output / row["dataset"] / row["output_label"]).read_text(encoding="utf-8")
            if row["label_type"] == "no_objects":
                self.assertEqual(data, "")
            else:
                category = next(index for index, name in enumerate(pilot.CLASSES) if row[name] == "1")
                self.assertEqual(data, f"{category} 0.2500000000 0.2500000000 0.5000000000 0.5000000000\n")
            self.assertEqual(row["dataset"], pilot.PILOT if row["split"] == "train" else pilot.HOLDOUT)
        exclusion_types = {row["type"] for row in read_csv(self.processed / "exclusion_report.csv")}
        self.assertEqual(exclusion_types, {"bbox_zero_size", "other_classes_only", "visual_review_suspect",
                                           "czech_train_overlap", "czech_eval_overlap"})
        self.assertTrue(all(row["same_overlay"] for row in report["conversion"]["previews"]))
        self.assertIn("train: null", (output / pilot.HOLDOUT / "data.yaml").read_text())
        self.assertFalse((output / pilot.HOLDOUT / "images" / "train").exists())

    def test_low_disk_keeps_manifests_and_creates_no_yolo_outputs(self) -> None:
        with patch.object(pilot, "_space_estimate", return_value={"free_bytes": 1, "required_bytes": 2}):
            with self.assertRaisesRegex(OSError, "디스크 공간"):
                self.build()
        report = json.loads((self.processed / "inspection_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "export_failed")
        self.assertTrue((self.processed / "selection_manifest.csv").is_file())
        self.assertFalse((self.data_dir / "yolo" / pilot.PILOT).exists())
        self.assert_inputs_preserved()

    def test_validator_failure_rolls_back_generated_images_and_keeps_audit(self) -> None:
        with patch.object(pilot, "_verify_ultralytics", side_effect=ValueError("simulated validation failure")):
            with self.assertRaisesRegex(ValueError, "simulated validation failure"):
                self.build()
        for name in (pilot.PILOT, pilot.HOLDOUT):
            self.assertFalse((self.data_dir / "yolo" / name).exists())
        self.assertTrue((self.processed / "duplicate_groups.csv").is_file())
        self.assert_inputs_preserved()


if __name__ == "__main__":
    unittest.main()
