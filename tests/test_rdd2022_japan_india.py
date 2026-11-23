import csv
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from scripts import inspect_rdd2022_japan_india as inspection
from tests.test_rdd2022 import jpeg, xml


def write_archive(path: Path, country: str, files: dict[str, bytes]) -> None:
    with ZipFile(path, "x") as archive:
        for name, payload in files.items():
            archive.writestr(f"{country}/{name}", payload)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


class Rdd2022JapanIndiaTest(unittest.TestCase):
    def test_train_comparison_and_reproducible_samples_separate_official_test(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            japan, india = root / "Japan.zip", root / "India.zip"
            image = jpeg(1)
            japan_files = {
                "train/images/multiple.jpg": image,
                "train/annotations/xmls/multiple.xml": xml("multiple.jpg", (
                    ("D00", 0, 0, 80, 60), ("D10", 1, 2, 40, 50), ("D44", 1, 2, 40, 50),
                )),
                "train/images/empty.jpg": image,
                "train/annotations/xmls/empty.xml": xml("empty.jpg"),
                "train/images/other.jpg": image,
                "train/annotations/xmls/other.xml": xml("other.jpg", (("D01", 1, 2, 40, 50),)),
                "test/images/official.jpg": image,
            }
            write_archive(japan, "Japan", japan_files)
            write_archive(india, "India", {
                "train/images/valid.jpg": image,
                "train/annotations/xmls/valid.xml": xml("valid.jpg", (("D40", 1, 2, 40, 50),)),
                "test/images/official.jpg": image,
            })
            (root / "split_manifest.csv").write_text("split,D00,D10,D20,D40\ntrain,2,0,0,0\nval,3,0,0,0\n")
            (root / "inspection_summary.json").write_text(json.dumps({
                "errors": [], "splits": {"actual": {"train": {
                    "images": 1, "background_images": 0,
                    "objects": dict(zip(inspection.CLASSES, (2, 0, 0, 0), strict=True)),
                    "positive_images": dict(zip(inspection.CLASSES, (1, 0, 0, 0), strict=True)),
                }}},
            }))

            output = root / "report"
            summaries = inspection.run_inspection(japan, india, root, output)
            summary = summaries["japan"]
            self.assertEqual(summary["zip"]["files_read_and_crc_ok"], 7)
            self.assertEqual(summary["splits"]["test"]["decoded_images"], 1)
            self.assertEqual(summary["train_label_validation"]["valid_xmls"], 3)
            self.assertEqual(summary["train_valid"]["background_images"], 1)
            self.assertEqual(summary["train_valid"]["images_without_target_objects"], 2)
            self.assertEqual(summary["train_valid"]["known_other_classes"]["D44"], {"objects": 1, "images": 1})
            self.assertFalse(read_csv(output / "validation_errors.csv"))

            comparison = {row["metric"]: row for row in read_csv(output / "class_comparison.csv")}
            self.assertEqual(comparison["D00_objects"]["czech_v2_train"], "2")
            self.assertEqual(comparison["D40_objects"]["india_train"], "1")
            self.assertEqual(comparison["background_images"]["japan_official_test"], "")
            saved_samples = read_csv(output / "sample_candidates.csv")
            class_rows = [row for row in saved_samples if row["country"] == "Japan" and row["selection"] == "class"]
            self.assertEqual([row["class"] for row in class_rows], ["D00", "D10"])
            self.assertTrue(all(row["cross_class_duplicate"] == "True" for row in class_rows))
            self.assertEqual(summary["sampling"]["unique_images"], 2)

            reversed_dir = root / "reversed"
            reversed_dir.mkdir()
            reversed_zip = reversed_dir / japan.name
            write_archive(reversed_zip, "Japan", dict(reversed(japan_files.items())))
            _, _, samples = inspection.inspect_archive(japan, "Japan")
            self.assertEqual(inspection.inspect_archive(reversed_zip, "Japan")[2], samples)
            with self.assertRaises(FileExistsError):
                inspection.run_inspection(japan, india, root, output)
            self.assertEqual(read_csv(output / "sample_candidates.csv"), saved_samples)

    def test_reports_crc_decode_pairing_and_label_issues_independently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "India.zip"
            image = jpeg(2)
            crc_marker = b"test ZIP CRC payload"
            boxes = xml("wrong.jpg", (
                ("D20", 6, 0, 6, 61), ("D0w0", 12, 5, 10, 15),
                ("D40", 7, "NaN", 60, 59), ("D00", 1, 1, 81, 50),
            ), width=81).replace(b"<xmin>7</xmin>", b"")
            write_archive(path, "India", {
                "train/images/boxes.jpg": image,
                "train/annotations/xmls/boxes.xml": boxes,
                "train/images/brokenxml.jpg": image,
                "train/annotations/xmls/brokenxml.xml": b"<annotation>",
                "train/images/orphan.jpg": image,
                "train/annotations/xmls/missing.xml": xml("missing.jpg"),
                "test/images/bad-decoding.jpg": b"not a JPEG",
                "test/images/bad-crc.jpg": crc_marker,
            })
            path.write_bytes(path.read_bytes().replace(crc_marker, b"!" + crc_marker[1:], 1))
            summary, errors, samples = inspection.inspect_archive(path, "India")
            self.assertEqual(summary["zip"]["unreadable_files"], 1)
            self.assertEqual(summary["splits"]["test"]["jpeg_checks_attempted"], 1)
            self.assertEqual(summary["splits"]["test"]["images_not_decoded"], 2)
            validation = summary["train_label_validation"]
            self.assertEqual(validation["matched_pairs_by_stem"], 2)
            self.assertEqual(validation["unmatched_files"], 2)
            self.assertEqual(validation["xml_size_comparisons_to_decoded_images"], 1)
            self.assertEqual(validation["invalid_xmls"], 3)
            self.assertEqual(validation["invalid_object_labels"], 4)
            self.assertEqual(validation["bbox_issues"]["bbox_outside_xml"], 1)
            self.assertEqual(validation["bbox_issues"]["bbox_outside_image"], 2)
            self.assertEqual({error["type"] for error in errors}, {
                "unreadable_zip_member", "unreadable_jpeg", "missing_xml", "missing_image", "invalid_xml",
                "filename_mismatch", "size_mismatch", "bbox_zero_size", "bbox_reversed", "bbox_outside_xml",
                "bbox_outside_image", "bbox_missing_coordinates", "bbox_invalid_coordinates", "unknown_class",
            })
            self.assertEqual(summary["train_matched_parsed"]["unknown_classes"]["D0w0"], {"objects": 1, "images": 1})
            self.assertEqual({Path(row["image"]).stem for row in samples}, {"boxes", "brokenxml", "orphan"})
            self.assertTrue(all(row["selection"] == "suspect" for row in samples))


if __name__ == "__main__":
    unittest.main()
