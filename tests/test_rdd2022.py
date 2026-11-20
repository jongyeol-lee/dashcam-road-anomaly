import csv
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

import cv2
import numpy as np

from src.road_anomaly import rdd2022


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/prepare_rdd2022_czech.py"


def jpeg(seed: int, quality: int = 95) -> bytes:
    pattern = np.random.default_rng(seed).integers(0, 256, (12, 16, 3), dtype=np.uint8)
    frame = cv2.resize(pattern, (80, 60), interpolation=cv2.INTER_NEAREST)
    encoded, data = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not encoded:
        raise RuntimeError("테스트 JPG를 인코딩할 수 없습니다.")
    return data.tobytes()


def xml(filename: str, boxes: tuple = (), width: int = 80) -> bytes:
    objects = "".join(
        f"<object><name>{category}</name><bndbox><xmin>{x0}</xmin><ymin>{y0}</ymin>"
        f"<xmax>{x1}</xmax><ymax>{y1}</ymax></bndbox></object>"
        for category, x0, y0, x1, y1 in boxes
    )
    return (f"<annotation><filename>{filename}</filename><size><width>{width}</width>"
            f"<height>60</height></size>{objects}</annotation>").encode("utf-8")


def read_manifest(processed: Path) -> list[dict[str, str]]:
    with (processed / "split_manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class CzechDatasetTest(unittest.TestCase):
    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.root = Path(temp_dir.name) / "도로 데이터 & 검사"
        self.root.mkdir()
        self.zip_path = self.root / "Czech.zip"
        self.processed = self.root / "processed"
        self.yolo = self.root / "yolo"
        self.members = {}
        multi = (("D00", 0, 6, 40, 30), ("D40", 20, 30, 80, 60))
        for index in range(20):
            filename = f"Czech_{index:06d}.jpg"
            image_seed = 0 if index < 3 else index
            quality = 90 if index == 2 else 95
            boxes = multi if index < 3 else ()
            if 3 <= index < 12:
                boxes = ((rdd2022.CLASSES[index % 4], 1, 2, 32, 36),)
            self.members[f"Czech/train/images/{filename}"] = jpeg(image_seed, quality)
            self.members[f"Czech/train/annotations/xmls/{filename[:-4]}.xml"] = xml(filename, boxes)
        self.members["Czech/test/images/official.jpg"] = jpeg(0, 85)
        self.members["Czech/test/images/official_other.jpg"] = jpeg(99)

    def write_zip(self, path: Path, members: dict[str, bytes]) -> None:
        with ZipFile(path, "x", compression=ZIP_DEFLATED) as archive:
            for name, data in members.items():
                archive.writestr(name, data)

    def run_cli(self, *args: str | Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(SCRIPT), *map(str, args),
             "--processed-dir", str(self.processed), "--yolo-dir", str(self.yolo)],
            cwd=self.root, capture_output=True, encoding="utf-8", timeout=30,
        )

    def test_zip_cli_validates_and_converts_all_labelled_images(self) -> None:
        self.write_zip(self.zip_path, self.members)
        source_hash = sha256(self.zip_path.read_bytes()).hexdigest()
        result = self.run_cli("--zip-path", self.zip_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.processed / "inspection_summary.json").read_text(encoding="utf-8"))
        self.assertEqual(report["source"]["zip_size_bytes"], self.zip_path.stat().st_size)
        self.assertEqual(report["file_counts"], {
            "Czech/train/images": 20, "Czech/train/annotations/xmls": 20, "Czech/test/images": 2,
        })
        self.assertEqual(report["matched_train_pairs"], 20)
        self.assertEqual(report["parsed_train_xmls"], 20)
        self.assertEqual(report["decoded_resolutions"], {"80x60": 22})
        self.assertFalse(report["errors"])
        self.assertTrue(report["reference_differences"])
        self.assertEqual(report["valid_train"]["background_images"], 8)
        self.assertEqual(report["valid_train"]["objects"], {"D00": 5, "D10": 2, "D20": 2, "D40": 6})
        self.assertEqual(report["valid_train"]["objects"], report["conversion"]["objects"])

        manifest = read_manifest(self.processed)
        self.assertEqual(Counter(row["split"] for row in manifest), {"train": 16, "val": 2, "test": 2})
        self.assertEqual(len(manifest), 20)
        self.assertTrue(all("!/Czech/train/" in row["source_image"] for row in manifest))
        self.assertEqual(len({row["group_id"] for row in manifest[:3]}), 1)
        self.assertEqual(len({row["split"] for row in manifest[:3]}), 1)
        self.assertEqual(manifest[0]["sha256"], manifest[1]["sha256"])
        self.assertNotEqual(manifest[0]["sha256"], manifest[2]["sha256"])
        self.assertEqual(report["similarity"]["pair_counts"]["identical"]["labelled"], 1)
        self.assertGreaterEqual(report["similarity"]["pair_counts"]["similar"]["labelled"], 2)
        self.assertGreater(report["similarity"]["pair_counts"]["similar"]["mixed"], 0)
        self.assertEqual(report["similarity"]["cross_split_pairs"], {"identical": 0, "similar": 0})

        for row in manifest:
            member = row["source_image"].split("!/", 1)[1]
            name = Path(member).name
            stored = self.yolo / "images" / row["split"] / name
            self.assertEqual(stored.read_bytes(), self.members[member])
            path = self.yolo / "labels" / row["split"] / Path(name).with_suffix(".txt")
            self.assertEqual(len(path.read_text(encoding="utf-8").splitlines()), sum(int(row[k]) for k in rdd2022.CLASSES))
        multi = self.yolo / "labels" / manifest[0]["split"] / "Czech_000000.txt"
        self.assertEqual([list(map(float, line.split())) for line in multi.read_text().splitlines()], [
            [0, 0.25, 0.3, 0.5, 0.4], [3, 0.625, 0.75, 0.75, 0.5],
        ])
        empty = self.yolo / "labels" / manifest[-1]["split"] / "Czech_000019.txt"
        self.assertEqual(empty.read_bytes(), b"")
        self.assertTrue(list((self.processed / "bbox_previews").glob("D00_*.png")))
        self.assertEqual(sha256(self.zip_path.read_bytes()).hexdigest(), source_hash)

    def test_splits_are_reproducible_across_zip_member_order_and_directory_input(self) -> None:
        self.write_zip(self.zip_path, self.members)
        reversed_zip = self.root / "reversed.zip"
        self.write_zip(reversed_zip, dict(reversed(list(self.members.items()))))
        for member, data in self.members.items():
            path = self.root / member
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

        manifests = []
        for index, source in enumerate((self.zip_path, reversed_zip, self.root / "Czech")):
            processed = self.root / f"processed-{index}"
            report = rdd2022.prepare_czech(source, processed, self.root / f"yolo-{index}")
            self.assertFalse(report["errors"])
            self.assertEqual(report["splits"]["seed"], 42)
            manifests.append([
                (Path(row["source_image"]).name, row["split"], row["group_id"], row["sha256"])
                for row in read_manifest(processed)
            ])
        self.assertEqual(manifests[0], manifests[1])
        self.assertEqual(manifests[0], manifests[2])

    def test_reports_invalid_xml_bbox_size_and_missing_pairs_without_yolo_output(self) -> None:
        labels = "Czech/train/annotations/xmls"
        self.members[f"{labels}/Czech_000000.xml"] = b"<annotation>"
        self.members[f"{labels}/Czech_000001.xml"] = xml("Czech_000001.jpg", (("D00", 6, 0, 6, 61),))
        self.members[f"{labels}/Czech_000002.xml"] = xml("Czech_000002.jpg", width=81)
        self.members.pop(f"{labels}/Czech_000003.xml")
        self.members.pop("Czech/train/images/Czech_000004.jpg")
        self.members[f"{labels}/Czech_000005.xml"] = xml("other.jpg", (("D99", 1, 2, 10, 20),))
        self.members["Czech/train/images/Czech_000006.jpg"] = b"not a JPEG"
        self.members["Czech/test/annotations/xmls/official.xml"] = xml("official.jpg")
        self.write_zip(self.zip_path, self.members)
        result = self.run_cli("--zip-path", self.zip_path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("검사 실패", result.stderr)
        self.assertFalse(self.yolo.exists())
        report = json.loads((self.processed / "inspection_summary.json").read_text(encoding="utf-8"))
        self.assertEqual({issue["type"] for issue in report["errors"]}, {
            "invalid_xml", "invalid_bbox", "size_mismatch", "missing_xml", "missing_jpg",
            "filename_mismatch", "invalid_class", "unreadable_jpg", "unexpected_test_xml",
        })
        self.assertTrue(all(issue["file"] and issue["reason"] for issue in report["errors"]))

    def test_rejects_missing_layout_and_bad_zip(self) -> None:
        self.write_zip(self.zip_path, {"train/other.jpg": jpeg(0)})
        report = rdd2022.prepare_czech(self.zip_path, self.processed, self.yolo)
        self.assertEqual({issue["type"] for issue in report["errors"]}, {"missing_files"})
        self.assertFalse(self.yolo.exists())

        bad_zip = self.root / "broken.zip"
        bad_zip.write_bytes(b"broken ZIP")
        self.processed = self.root / "bad-zip-report"
        result = self.run_cli("--zip-path", bad_zip)
        self.assertIn("BadZipFile", result.stderr)
        self.assertIn(str(bad_zip), result.stderr)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.processed.exists())

    def test_preserves_existing_outputs_and_rejects_writes_inside_source(self) -> None:
        self.write_zip(self.zip_path, self.members)
        source = self.zip_path.read_bytes()
        for index in range(2):
            processed, yolo = self.root / f"existing-processed-{index}", self.root / f"existing-yolo-{index}"
            existing = (processed, yolo)[index]
            existing.mkdir()
            marker = existing / "prior-result.txt"
            marker.write_text("prior result", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                rdd2022.prepare_czech(self.zip_path, processed, yolo)
            self.assertEqual(list(existing.iterdir()), [marker])
            self.assertEqual(marker.read_text(encoding="utf-8"), "prior result")
            self.assertFalse((yolo, processed)[index].exists())
        self.assertEqual(self.zip_path.read_bytes(), source)
        with self.assertRaises(ValueError):
            rdd2022.prepare_czech(self.root, self.processed, self.yolo)

    def test_holdouts_include_images_with_multiple_objects_of_one_class(self) -> None:
        boxes = tuple(rdd2022.Box("D00", (x, 0, x + 10, 10)) for x in (0, 20, 40))
        images = [
            rdd2022.Image(f"{index:03d}", 80, 60, str(index), index, boxes=boxes[:count])
            for index, count in enumerate([3] * 20 + [1] * 30 + [0] * 50)
        ]
        groups = {image.member: image.member for image in images}
        assignments, _ = rdd2022._assign_splits(images, groups)
        for split in ("val", "test"):
            with self.subTest(split=split):
                sizes = [len(image.boxes) for image in images if assignments[image.member] == split]
                self.assertEqual(len(sizes), 10)
                self.assertIn(3, sizes)
                self.assertLessEqual(abs(sum(sizes) - 9), 2)

    def test_failed_export_removes_only_this_runs_outputs(self) -> None:
        self.write_zip(self.zip_path, self.members)
        with patch.object(rdd2022, "_save_preview", side_effect=OSError("인코딩 실패")):
            with self.assertRaisesRegex(OSError, "인코딩 실패"):
                rdd2022.prepare_czech(self.zip_path, self.processed, self.yolo)
        self.assertFalse(self.processed.exists())
        self.assertFalse(self.yolo.exists())
        self.assertFalse(rdd2022.prepare_czech(self.zip_path, self.processed, self.yolo)["errors"])

    def test_ultralytics_resolves_yaml_and_reads_labels(self) -> None:
        self.write_zip(self.zip_path, self.members)
        report = rdd2022.prepare_czech(self.zip_path, self.processed, self.yolo)
        code = """
import os
import sys
from pathlib import Path
from unittest.mock import patch

root = Path(sys.argv[1])
config = root.parent / "ultralytics-config"
os.environ.update(YOLO_CONFIG_DIR=str(config), MPLCONFIGDIR=str(config), YOLO_OFFLINE="true", YOLO_AUTOINSTALL="false")
from ultralytics.data import utils

with patch.object(utils, "check_font"):
    dataset = utils.check_det_dataset(root / "data.yaml", autodownload=False)
assert dataset["names"] == {0: "D00", 1: "D10", 2: "D20", 3: "D40"}, dataset
total = 0
for split in ("train", "val", "test"):
    assert Path(dataset[split]) == root / "images" / split, dataset
    images = sorted(str(path) for path in Path(dataset[split]).glob("*.jpg"))
    assert images, split
    for image, label in zip(images, utils.img2label_paths(images), strict=True):
        _, boxes, _, _, _, missing, found, _, corrupt, message = utils.verify_image_label(
            (image, label, "", False, 4, 0, 0, False)
        )
        assert (missing, found, corrupt, message) == (0, 1, 0, ""), (image, message)
        total += len(boxes)
print(total)
"""
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-X", "utf8", "-c", code, str(self.yolo)],
            cwd=self.root, capture_output=True, encoding="utf-8", timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(int(result.stdout.strip().splitlines()[-1]), sum(report["conversion"]["objects"].values()))
