import csv
import json
import tempfile
import unittest
from contextlib import ExitStack
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np
from PIL import Image

from scripts import review_rdd2022_japan_india as review
from tests.test_rdd2022 import jpeg, xml


class VisualReviewTest(unittest.TestCase):
    def test_reads_orientation_without_rotating_xml_pixel_axes(self) -> None:
        frame = Image.new("RGB", (80, 60))
        exif = frame.getexif()
        exif[274] = 6
        payload = BytesIO()
        frame.save(payload, format="JPEG", exif=exif)
        pixels, metadata = review._read_pixels(payload.getvalue())
        self.assertEqual(pixels.shape, (60, 80, 3))
        self.assertEqual(metadata["exif_orientation"], 6)
        reshaped = pixels.reshape(80, 60, 3)
        self.assertNotEqual(review._pixel_sha256(pixels), review._pixel_sha256(reshaped))

    def test_review_keeps_raw_error_coordinates_and_writes_pair_and_sheets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archives, rows = {}, []
            payload = jpeg(3)
            for country, code, coords, expected_error in (
                ("Japan", "D20", (30, 6, 30, 10), "bbox_zero_size"),
                ("India", "D0w0", (15, 4, 35, 20), "unknown_class"),
            ):
                name = f"{country}.jpg"
                image_member = f"{country}/train/images/{name}"
                xml_member = f"{country}/train/annotations/xmls/{country}.xml"
                path = root / f"{country}.zip"
                with ZipFile(path, "x") as archive:
                    archive.writestr(image_member, payload)
                    archive.writestr(xml_member, xml(name, ((code, *coords), ("D00", 0, 0, 80, 60))))
                archives[country] = path
                rows.append({
                    "country": country, "image": image_member, "xml": xml_member, "class": "",
                    "selection": "suspect", "object_count": 2, "class_counts": f"D00=1|{code}=1",
                    "error_types": expected_error,
                })
            manifest = root / "samples.csv"
            manifest.write_bytes(review._csv_bytes(tuple(rows[0]), rows))
            output = root / "output"
            summary = review.run_review(manifest, archives, output)
            self.assertEqual(summary["valid_boxes_rendered"], 2)
            self.assertEqual(summary["duplicates"]["by_scope"]["cross_country"]["exact_jpeg"], 1)
            self.assertEqual(summary["duplicates"]["by_scope"]["cross_country"]["exact_pixels"], 1)
            self.assertEqual(summary["duplicates"]["candidate_rows"], 1)
            self.assertEqual(len(summary["contact_sheets"]), 2)
            with (output / "visual_review_manifest.csv").open(encoding="utf-8-sig", newline="") as stream:
                result = list(csv.DictReader(stream))
            first, second = (json.loads(row["boxes"])[0] for row in result)
            self.assertEqual(first["xyxy"], ["30", "6", "30", "10"])
            self.assertEqual(first["overlay"], "omitted")
            self.assertEqual(second["class"], "D0w0")
            self.assertEqual(second["overlay"], "flagged_class")
            self.assertTrue(all(row["label_quality"] == review.PENDING for row in result))
            preview = cv2.imdecode(np.frombuffer((output / result[0]["preview"]).read_bytes(), np.uint8),
                                   cv2.IMREAD_COLOR)
            self.assertEqual(preview.shape, (116, 80, 3))
            self.assertTrue((output / "duplicate_candidates/comparisons/pair_0001.jpg").is_file())
            with self.assertRaises(FileExistsError):
                review.run_review(manifest, archives, output)

    def test_dhash_boundary_includes_only_candidates_at_or_below_threshold(self) -> None:
        frame = np.zeros((32, 32, 3), dtype=np.uint8)
        rows = [{
            "country": "Japan", "source_image": f"{digest}.jpg", "sha256_jpeg": str(digest),
            "sha256_pixels": str(digest), "dhash_128": f"{digest:x}",
        } for digest in (0, 0xff, 0x1ff00)]
        items = [review.ReviewImage(row, frame, frame) for row in rows]
        with tempfile.TemporaryDirectory() as directory, ExitStack() as rollback:
            root = Path(directory)
            (root / "duplicate_candidates/comparisons").mkdir(parents=True)
            candidates, counts = review._pair_candidates(items, root, rollback)
            self.assertEqual(counts["Japan"]["pairs"], 3)
            self.assertEqual(counts["Japan"]["dhash_only"], 1)
            self.assertEqual(candidates[0]["dhash_distance"], 8)
            self.assertEqual(candidates[0]["review_status"], review.PENDING)


if __name__ == "__main__":
    unittest.main()
