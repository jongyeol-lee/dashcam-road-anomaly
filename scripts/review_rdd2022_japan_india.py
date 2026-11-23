import argparse
import csv
import json
import ntpath
import sys
from collections import Counter, defaultdict
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from hashlib import sha256
from io import BytesIO
from itertools import combinations
from pathlib import Path, PurePosixPath
from statistics import median
from struct import pack
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

import cv2
import numpy as np
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.inspect_rdd2022_japan_india import (
    BBOX_COORDINATES, CLASSES, COUNTRIES, SEED, _create_dir, _csv_bytes, _inspect_xml, _write_file,
)
from road_anomaly.rdd2022 import D_HASH_DISTANCE, _difference_hash


COLORS = dict(zip(CLASSES, ((255, 210, 0), (80, 240, 95), (225, 110, 255), (50, 85, 255)), strict=True))
GROUPS = (*CLASSES, "background", "suspect")
PENDING = "미검토"
PAIR_FIELDS = (
    "scope", "country_a", "image_a", "country_b", "image_b", "same_jpeg_sha256", "same_pixel_sha256",
    "dhash_distance", "candidate_type", "comparison", "review_status", "user_notes",
)


def _read_pixels(data: bytes) -> tuple[np.ndarray, dict]:
    if not data.startswith(b"\xff\xd8\xff") or not data.endswith(b"\xff\xd9"):
        raise ValueError("JPEG 시작 또는 종료 마커가 없습니다.")
    with Image.open(BytesIO(data)) as jpeg:
        exif = jpeg.getexif()
        header_size = jpeg.size
        metadata = {
            "exif_present": "exif" in jpeg.info,
            "exif_orientation": exif.get(274),
            "icc_profile_present": bool(jpeg.info.get("icc_profile")),
        }
    # XML과 비교할 원본 픽셀에 EXIF 방향을 적용하지 않는다.
    frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    if frame is None or frame.shape[1::-1] != header_size:
        raise ValueError("JPEG 디코딩 또는 헤더 크기 대조에 실패했습니다.")
    return frame, metadata


def _pixel_sha256(frame: np.ndarray) -> str:
    digest = sha256(pack(">III", *frame.shape))
    digest.update(frame.tobytes())
    return digest.hexdigest()


@dataclass(frozen=True)
class ReviewImage:
    row: dict
    original: np.ndarray
    overlay: np.ndarray


def _add_text(frame: np.ndarray, label: str, x: int, y: int, color=(245, 245, 245)) -> None:
    for ink, thickness in (((15, 16, 20), 3), (color, 1)):
        cv2.putText(frame, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.51, ink, thickness, cv2.LINE_AA)


def _inspect_sample(sample: dict, archive: ZipFile) -> ReviewImage:
    name = PurePosixPath(sample["image"]).name
    category = sample["class"] or sample["selection"]
    if sample["country"] not in COUNTRIES or category not in GROUPS:
        raise ValueError("샘플의 국가 또는 선정 범주를 확인할 수 없습니다.")
    if ntpath.isreserved(name) or "\\" in name or PurePosixPath(name).suffix.lower() != ".jpg":
        raise ValueError(f"미리보기에 사용할 수 없는 파일명입니다. {name}")
    data, xml = (archive.read(sample[key]) for key in ("image", "xml"))
    frame, metadata = _read_pixels(data)
    height, width = frame.shape[:2]
    counts, compared_size, issues = _inspect_xml(xml, name, (width, height))
    if counts is None or counts.total() != int(sample["object_count"]):
        raise ValueError(f"샘플 CSV와 원본 XML 객체 수를 대조할 수 없습니다. {sample['xml']}")
    class_counts = "|".join(f"{key or '<missing>'}={value}" for key, value in sorted(counts.items()))
    if sample["class_counts"] != class_counts:
        raise ValueError(f"샘플 CSV와 원본 XML 클래스가 다릅니다. {sample['xml']}")

    root = ET.fromstring(xml)
    issue_types = defaultdict(set)
    for issue in issues:
        issue_types[issue.object_index].add(issue.type)
    size_matches = compared_size and "size_mismatch" not in issue_types[None]
    orientation = metadata["exif_orientation"]
    axes_match = size_matches and "filename_mismatch" not in issue_types[None] and orientation in (None, 1)
    overlay = cv2.copyMakeBorder(frame, 56, 0, 0, 0, cv2.BORDER_CONSTANT, value=(20, 22, 29))
    canvas = overlay[56:]
    boxes = []
    for index, obj in enumerate(root.findall("object"), 1):
        code = (obj.findtext("name") or "").strip()
        raw = [obj.findtext(f"bndbox/{key}") for key in BBOX_COORDINATES]
        errors = issue_types[index]
        geometric = not any(kind.startswith("bbox_") for kind in errors)
        area = None
        display = "omitted"
        if geometric:
            x0, y0, x1, y1 = map(float, raw)
            area = round(100 * (x1 - x0) * (y1 - y0) / (width * height), 4)
            if axes_match:
                # 오른쪽·아래 경계값은 렌더링할 때만 마지막 픽셀로 제한한다.
                start = min(round(x0), width - 1), min(round(y0), height - 1)
                end = min(round(x1), width - 1), min(round(y1), height - 1)
                display = "flagged_class" if errors else "valid"
                color = (25, 185, 255) if errors else COLORS.get(code, (215, 215, 215))
                cv2.rectangle(canvas, start, end, color, 2)
                label = f"? {code or 'unnamed'}" if errors else code
                _add_text(canvas, label, max(0, min(start[0], width - 85)), max(15, start[1] - 4), color)
        boxes.append({
            "index": index, "class": code, "xyxy": raw, "issues": sorted(errors),
            "area_pct": area, "overlay": display,
        })

    error_codes = sorted({issue.type for issue in issues})
    _add_text(overlay, f"{sample['country']}  {name}   |   XML objects {counts.total()}", 10, 21)
    _add_text(overlay, f"{category}  |  {width}x{height}  |  {' / '.join(error_codes) or 'XML checks passed'}", 10, 43)
    country = sample["country"].lower()
    row = {
        "country": sample["country"], "archive": str(archive.filename),
        "source_image": sample["image"], "source_xml": sample["xml"], "selection": category,
        "object_count": counts.total(), "class_counts": class_counts, "boxes": json.dumps(boxes, ensure_ascii=False),
        "decoded": True, "width": width, "height": height,
        "xml_width": root.findtext("size/width"), "xml_height": root.findtext("size/height"),
        **metadata, "xml_size_matches": size_matches,
        "coordinate_check": "raw_axes_match" if axes_match else "manual_review",
        "auto_bbox_status": "issues" if issues or not axes_match else "passed",
        "auto_issues": json.dumps([asdict(issue) for issue in issues], ensure_ascii=False),
        "valid_boxes_rendered": sum(box["overlay"] == "valid" for box in boxes),
        "sha256_jpeg": sha256(data).hexdigest(),
        "sha256_pixels": _pixel_sha256(frame), "dhash_128": f"{_difference_hash(frame):032x}",
        "preview": f"previews/{country}/{name}", "contact_sheet": f"contact_sheets/{country}/{category}.jpg",
        "visual_review_status": PENDING, "label_quality": PENDING, "environment_notes": PENDING, "user_notes": "",
    }
    return ReviewImage(row, frame, overlay)


def _grid(tiles: list[tuple[np.ndarray, str]], title: str, columns: int, edge: int) -> np.ndarray:
    gap, header, footer = 10, 44, 25
    columns = min(len(tiles), columns)
    rows = (len(tiles) + columns - 1) // columns
    pitch_y = edge + footer + gap
    sheet = np.full((header + rows * pitch_y, gap + columns * (edge + gap), 3), (27, 30, 38), dtype=np.uint8)
    _add_text(sheet, title, 10, 26)
    for index, (frame, caption) in enumerate(tiles):
        y = header + (index // columns) * pitch_y
        x = gap + (index % columns) * (edge + gap)
        height, width = frame.shape[:2]
        scale = edge / max(height, width)
        thumb_width, thumb_height = max(1, round(width * scale)), max(1, round(height * scale))
        dx, dy = (edge - thumb_width) // 2, (edge - thumb_height) // 2
        sheet[y + dy:y + dy + thumb_height, x + dx:x + dx + thumb_width] = cv2.resize(
            frame, (thumb_width, thumb_height), interpolation=cv2.INTER_AREA,
        )
        _add_text(sheet, caption, x, y + edge + 17)
    return sheet


def _write_jpeg(path: Path, frame: np.ndarray, cleanup: ExitStack) -> None:
    encoded, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not encoded:
        raise ValueError(f"JPG를 인코딩할 수 없습니다. {path}")
    _write_file(path, jpeg.tobytes(), cleanup)


def _pair_candidates(reviews: list[ReviewImage], output: Path, cleanup: ExitStack) -> tuple[list, dict]:
    candidates = []
    stats = {scope: Counter(dict.fromkeys(("pairs", "exact_jpeg", "exact_pixels", "dhash_only"), 0))
             for scope in (*COUNTRIES, "cross_country")}
    for a, b in combinations(reviews, 2):
        left, right = a.row, b.row
        scope = left["country"] if left["country"] == right["country"] else "cross_country"
        count = stats[scope]
        count["pairs"] += 1
        same_jpeg = left["sha256_jpeg"] == right["sha256_jpeg"]
        same_pixels = left["sha256_pixels"] == right["sha256_pixels"]
        distance = (int(left["dhash_128"], 16) ^ int(right["dhash_128"], 16)).bit_count()
        count["exact_jpeg"] += same_jpeg
        count["exact_pixels"] += same_pixels
        if not (same_jpeg or same_pixels or distance <= D_HASH_DISTANCE):
            continue
        candidate_type = "exact_jpeg" if same_jpeg else "exact_pixels" if same_pixels else "dhash_only"
        count["dhash_only"] += candidate_type == "dhash_only"
        path = f"duplicate_candidates/comparisons/pair_{len(candidates) + 1:04}.jpg"
        tiles = [(item.original, PurePosixPath(item.row["source_image"]).name) for item in (a, b)]
        _write_jpeg(output / path, _grid(tiles, f"{candidate_type}  |  dHash {distance}/128", 2, 540), cleanup)
        candidates.append({
            "scope": scope, "country_a": left["country"], "image_a": left["source_image"],
            "country_b": right["country"], "image_b": right["source_image"],
            "same_jpeg_sha256": same_jpeg, "same_pixel_sha256": same_pixels, "dhash_distance": distance,
            "candidate_type": candidate_type, "comparison": path, "review_status": PENDING, "user_notes": "",
        })
    return candidates, stats


def run_review(sample_csv: Path, archives: dict[str, Path], output: Path) -> dict:
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"출력 경로가 이미 있습니다. {output}")
    with sample_csv.open(encoding="utf-8-sig", newline="") as stream:
        samples = list(csv.DictReader(stream))
    if not samples:
        raise ValueError("샘플 CSV에 이미지가 없습니다.")

    with ExitStack() as inputs, ExitStack() as cleanup:
        zips = {country: inputs.enter_context(ZipFile(path.resolve(strict=True), "r")) for country, path in archives.items()}
        reviews = [_inspect_sample(sample, zips[sample["country"]]) for sample in samples]
        _create_dir(output, cleanup, parents=True)
        for folder in ("previews", "contact_sheets", "duplicate_candidates", "duplicate_candidates/comparisons"):
            _create_dir(output / folder, cleanup)
        for country in COUNTRIES:
            for folder in ("previews", "contact_sheets"):
                _create_dir(output / folder / country.lower(), cleanup)

        by_sheet = defaultdict(list)
        class_areas = defaultdict(list)
        for review in reviews:
            row = review.row
            _write_jpeg(output / row["preview"], review.overlay, cleanup)
            by_sheet[row["contact_sheet"]].append(review)
            for box in json.loads(row["boxes"]):
                if box["overlay"] == "valid" and box["class"] in CLASSES:
                    class_areas[row["country"], box["class"]].append(box["area_pct"])
        for path, members in by_sheet.items():
            first = members[0].row
            tiles = [(item.overlay, PurePosixPath(item.row["source_image"]).name) for item in members]
            _write_jpeg(output / path, _grid(tiles, f"{first['country']}   {first['selection']}   |   {len(tiles)} images",
                                           5, 275), cleanup)

        pairs, pair_stats = _pair_candidates(reviews, output, cleanup)
        rows = [review.row for review in reviews]
        counts = {country: dict(Counter(row["selection"] for row in rows if row["country"] == country))
                  for country in COUNTRIES}
        summary = {
            "source_samples": str(sample_csv.resolve()), "source_sample_seed": SEED,
            "images_decoded": len(rows), "sample_counts": counts, "contact_sheets": list(by_sheet),
            "coordinate_checks": dict(Counter(row["coordinate_check"] for row in rows)),
            "exif_present": sum(row["exif_present"] for row in rows),
            "exif_orientations": dict(Counter(str(row["exif_orientation"] or "absent") for row in rows)),
            "icc_profiles": sum(row["icc_profile_present"] for row in rows),
            "resolutions": {country: dict(Counter(f"{row['width']}x{row['height']}" for row in rows
                                                  if row["country"] == country)) for country in COUNTRIES},
            "xml_objects": {country: sum(row["object_count"] for row in rows if row["country"] == country)
                            for country in COUNTRIES},
            "valid_boxes_rendered": sum(row["valid_boxes_rendered"] for row in rows),
            "automatic_issues": [{"image": row["source_image"], "issues": json.loads(row["auto_issues"])}
                                 for row in rows if row["auto_bbox_status"] == "issues"],
            "target_box_area_pct": {
                country: {category: {"boxes": len(values), "median": median(values), "min": min(values), "max": max(values)}
                          for (name, category), values in class_areas.items() if name == country}
                for country in COUNTRIES
            },
            "duplicates": {
                "dhash_bits": 128, "max_hamming_distance": D_HASH_DISTANCE, "by_scope": pair_stats,
                "candidate_rows": len(pairs),
            },
        }
        _write_file(output / "visual_review_manifest.csv", _csv_bytes(tuple(rows[0]), rows), cleanup)
        _write_file(output / "duplicate_candidates.csv", _csv_bytes(PAIR_FIELDS, pairs), cleanup)
        _write_file(output / "visual_review_summary.json",
                    (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8"), cleanup)
        cleanup.pop_all()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Part 5.2-1 샘플의 박스 미리보기와 중복 후보를 생성합니다.")
    parser.add_argument("--japan-zip", type=Path, required=True)
    parser.add_argument("--india-zip", type=Path, required=True)
    parser.add_argument("--sample-csv", type=Path,
                        default=PROJECT_ROOT / "data/processed/rdd2022_japan_india_inspection/sample_candidates.csv")
    parser.add_argument("--output-dir", type=Path,
                        default=PROJECT_ROOT / "data/processed/rdd2022_japan_india_visual_review")
    args = parser.parse_args()
    try:
        report = run_review(args.sample_csv, {"Japan": args.japan_zip, "India": args.india_zip}, args.output_dir)
    except (OSError, BadZipFile, ValueError, KeyError, cv2.error) as error:
        parser.exit(1, f"[{type(error).__name__}] {error}\n")
    print(f"Preview {report['images_decoded']} | Contact sheets {len(report['contact_sheets'])}"
          f" | Duplicate candidates {report['duplicates']['candidate_rows']}")
    print(args.output_dir.resolve())


if __name__ == "__main__":
    main()
