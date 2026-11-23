import argparse
import csv
import json
import random
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from contextlib import ExitStack
from dataclasses import dataclass
from io import StringIO
from math import isfinite
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile, ZipInfo

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from road_anomaly.rdd2022 import CLASSES, JPEG_SUFFIXES, READ_ERRORS, SEED, _create_dir, _write_file


COUNTRIES = ("Japan", "India")
SPLITS = ("train", "test")
# 이전 RDD 어노테이션에서 사용한 코드로, 이번 비교의 대상 클래스에는 포함하지 않는다.
OTHER_CLASSES = {"D01", "D11", "D43", "D44", "D50"}
BBOX_COORDINATES = ("xmin", "ymin", "xmax", "ymax")
ERROR_FIELDS = ("country", "archive", "split", "member", "image", "xml", "object_index", "class", "type", "detail")
SAMPLE_FIELDS = (
    "country", "archive", "selection", "class", "image", "xml", "class_object_count", "object_count",
    "class_counts", "selected_times", "cross_class_duplicate", "error_types",
)


@dataclass(frozen=True)
class AnnotationIssue:
    type: str
    detail: str
    object_index: int | None = None
    category: str = ""


def _bbox_issues(
    obj: ET.Element, xml_size: tuple[int, int] | None, image_size: tuple[int, int] | None,
) -> list[tuple[str, str]]:
    coordinates = []
    missing, invalid = [], []
    for key in BBOX_COORDINATES:
        value = (obj.findtext(f"bndbox/{key}") or "").strip()
        if not value:
            missing.append(key)
            continue
        try:
            number = float(value)
            if not isfinite(number):
                raise ValueError(value)
        except ValueError:
            invalid.append(f"{key}={value!r}")
        else:
            coordinates.append(number)

    issues = []
    if missing:
        issues.append(("bbox_missing_coordinates", ", ".join(missing)))
    if invalid:
        issues.append(("bbox_invalid_coordinates", ", ".join(invalid)))
    if issues:
        return issues

    x0, y0, x1, y1 = coordinates
    detail = str(tuple(coordinates))
    if x0 == x1 or y0 == y1:
        issues.append(("bbox_zero_size", detail))
    if x0 > x1 or y0 > y1:
        issues.append(("bbox_reversed", detail))
    # Czech 검증과 동일하게 0 및 이미지 너비·높이와 일치하는 좌표를 허용한다.
    for kind, size in (("bbox_outside_xml", xml_size), ("bbox_outside_image", image_size)):
        if size:
            width, height = size
            if not (0 <= x0 <= width and 0 <= x1 <= width and 0 <= y0 <= height and 0 <= y1 <= height):
                issues.append((kind, f"{detail} / {width}x{height}"))
    return issues


def _inspect_xml(
    data: bytes, image_name: str, image_size: tuple[int, int] | None,
) -> tuple[Counter[str] | None, bool, list[AnnotationIssue]]:
    _, counts, compared_size, issues = _read_annotation(data, image_name, image_size)
    return counts, compared_size, issues


def _read_annotation(
    data: bytes, image_name: str, image_size: tuple[int, int] | None,
) -> tuple[ET.Element | None, Counter[str] | None, bool, list[AnnotationIssue]]:
    """Train 검사와 YOLO 변환에서 동일한 원본 XML과 검증 규칙을 사용한다."""
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, LookupError, ValueError) as error:
        return None, None, False, [AnnotationIssue("invalid_xml", str(error))]
    if root.tag != "annotation":
        return None, None, False, [AnnotationIssue("invalid_xml", f"루트 요소 {root.tag!r}")]

    issues = []
    filename = (root.findtext("filename") or "").strip()
    if not filename or (image_name and filename != image_name):
        issues.append(AnnotationIssue("filename_mismatch", f"XML {filename!r}, JPG {image_name!r}"))
    try:
        width, height = (int(root.findtext(f"size/{key}", "")) for key in ("width", "height"))
        if min(width, height) <= 0:
            raise ValueError("XML 너비와 높이는 양의 정수여야 합니다.")
        xml_size = (width, height)
    except ValueError as error:
        xml_size = None
        issues.append(AnnotationIssue("invalid_xml_size", str(error)))
    compared_size = xml_size is not None and image_size is not None
    if compared_size and xml_size != image_size:
        issues.append(AnnotationIssue("size_mismatch", f"XML {xml_size}, JPG {image_size}"))

    counts = Counter()
    for index, obj in enumerate(root.findall("object"), 1):
        category = (obj.findtext("name") or "").strip()
        counts[category] += 1
        if not category:
            issues.append(AnnotationIssue("missing_class", "object/name 값이 비어 있습니다.", index))
        elif category not in CLASSES and category not in OTHER_CLASSES:
            issues.append(AnnotationIssue("unknown_class", f"분류가 확인되지 않은 코드 {category!r}", index, category))
        issues.extend(AnnotationIssue(kind, detail, index, category)
                      for kind, detail in _bbox_issues(obj, xml_size, image_size))
    return root, counts, compared_size, issues


def _jpeg_size(data: bytes) -> tuple[int, int]:
    if not data.startswith(b"\xff\xd8\xff") or not data.endswith(b"\xff\xd9"):
        raise ValueError("JPEG 시작 또는 종료 마커가 없습니다.")
    # EXIF 회전 전의 픽셀 좌표계를 XML 좌표와 비교한다.
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    if image is None or not image.size:
        raise ValueError("JPEG 픽셀을 디코딩할 수 없습니다.")
    height, width = image.shape[:2]
    return width, height


def _distribution(annotations: Iterable[Counter[str]]) -> dict:
    objects, positive_images, per_image, targets_per_image = (Counter() for _ in range(4))
    for counts in annotations:
        objects.update(counts)
        positive_images.update(category for category, count in counts.items() if count)
        per_image[counts.total()] += 1
        targets_per_image[sum(counts[category] for category in CLASSES)] += 1
    other = {
        category: {"objects": objects[category], "images": positive_images[category]}
        for category in sorted(set(objects) - set(CLASSES) - {""})
    }
    return {
        "images": per_image.total(),
        "objects": {category: objects[category] for category in CLASSES},
        "positive_images": {category: positive_images[category] for category in CLASSES},
        "known_other_classes": {category: stats for category, stats in other.items() if category in OTHER_CLASSES},
        "unknown_classes": {category: stats for category, stats in other.items() if category not in OTHER_CLASSES},
        "background_images": per_image[0],
        "images_without_target_objects": targets_per_image[0],
        "objects_per_image": dict(sorted(per_image.items())),
        "target_objects_per_image": dict(sorted(targets_per_image.items())),
    }


def _by_stem(entries: list[ZipInfo]) -> dict[str, list[ZipInfo]]:
    index = defaultdict(list)
    for entry in entries:
        index[PurePosixPath(entry.filename).stem.casefold()].append(entry)
    return index


def _sample_candidates(country: str, archive: str, observed: dict, valid: dict, errors: list) -> list[dict]:
    rng = random.Random(SEED)
    by_image = defaultdict(list)
    for error in errors:
        if error["split"] == "train" and error["image"]:
            by_image[error["image"]].append(error)
    class_samples = [
        (category, [name for name in sorted(valid) if valid[name][1][category]], 10)
        for category in CLASSES
    ]
    groups = [*class_samples, ("background", sorted(name for name in valid if not valid[name][1]), 5),
              ("suspect", sorted(by_image), 10)]
    rows = []
    for group, pool, limit in groups:
        for image in rng.sample(pool, min(len(pool), limit)):
            image_errors = by_image.get(image, [])
            error_xml = next((error["xml"] for error in image_errors if error["xml"]), "")
            xml, counts = observed.get(image, (error_xml, None))
            rows.append({
                "country": country, "archive": archive, "image": image, "xml": xml,
                "selection": "class" if group in CLASSES else group,
                "class": group if group in CLASSES else "",
                "class_object_count": counts[group] if group in CLASSES else "",
                "object_count": counts.total() if counts is not None else "",
                "class_counts": "|".join(f"{category or '<missing>'}={n}" for category, n in sorted(counts.items()))
                if counts is not None else "",
                "error_types": "|".join(sorted({error["type"] for error in image_errors})),
            })
    selected = Counter(row["image"] for row in rows)
    class_selected = Counter(row["image"] for row in rows if row["selection"] == "class")
    for row in rows:
        row["selected_times"] = selected[row["image"]]
        row["cross_class_duplicate"] = class_selected[row["image"]] > 1
    return rows


def inspect_archive(path: Path, country: str) -> tuple[dict, list[dict], list[dict]]:
    """Train 라벨과 Train·Test JPG를 원본 ZIP에서 직접 검사한다."""
    path = path.resolve(strict=True)
    errors = []

    def issue(kind, member, detail, *, split="", image="", xml="", index=None, category=""):
        errors.append({
            "country": country, "archive": path.name, "split": split, "member": member,
            "image": image, "xml": xml, "object_index": index, "class": category, "type": kind, "detail": detail,
        })

    with ZipFile(path, "r") as archive:
        entries = archive.infolist()
        files = [entry for entry in entries if not entry.is_dir()]
        folders = {f"{country}/{split}/{folder}": (split, kind) for split in SPLITS
                   for folder, kind in (("images", "image"), ("annotations/xmls", "xml"))}
        grouped = {(split, kind): [] for split, kind in folders.values()}
        locations = {}
        file_counts = Counter()
        for entry in files:
            folder, _, name = entry.filename.rpartition("/")
            suffix = PurePosixPath(name).suffix.lower()
            file_counts[folder] += 1
            location = folders.get(folder)
            if location and suffix in (JPEG_SUFFIXES if location[1] == "image" else {".xml"}):
                grouped[location].append(entry)
                locations[entry] = location
            elif location or suffix in JPEG_SUFFIXES | {".xml"}:
                issue("unexpected_layout", entry.filename, "예상한 JPG·XML 경로 또는 확장자와 다릅니다.")

        train_images, train_xmls = grouped["train", "image"], grouped["train", "xml"]
        for folder, location in folders.items():
            if location != ("test", "xml") and not grouped[location]:
                issue("empty_expected_folder", folder, "예상 경로에 대상 파일이 없습니다.", split=location[0])
        image_index, xml_index = _by_stem(train_images), _by_stem(train_xmls)
        pairs = {}
        for stem in sorted(image_index.keys() | xml_index.keys()):
            images, xmls = image_index.get(stem, []), xml_index.get(stem, [])
            if len(images) == len(xmls) == 1:
                pairs[xmls[0]] = images[0]
                continue
            detail = f"stem {stem!r}: JPG {len(images)}, XML {len(xmls)}"
            for entry in images:
                issue("ambiguous_pair" if xmls else "missing_xml", entry.filename, detail,
                      split="train", image=entry.filename)
            for entry in xmls:
                issue("ambiguous_pair" if images else "missing_image", entry.filename, detail,
                      split="train", xml=entry.filename)

        unreadable_files = 0

        def read_entry(entry: ZipInfo, capture: bool) -> bytes | None:
            nonlocal unreadable_files
            try:
                # 끝까지 읽어 ZIP 멤버의 CRC를 검사한다. 이미지나 XML 외의 내용은 보관하지 않는다.
                with archive.open(entry) as stream:
                    if capture:
                        data = stream.read()
                        length = len(data)
                    else:
                        data = b""
                        length = sum(len(chunk) for chunk in iter(lambda: stream.read(1024 * 1024), b""))
                if length != entry.file_size:
                    raise BadZipFile(f"크기 불일치: {length} / {entry.file_size} bytes")
                return data
            except (*READ_ERRORS, EOFError, NotImplementedError) as error:
                unreadable_files += 1
                split, kind = locations.get(entry, ("", ""))
                image = entry if kind == "image" else pairs.get(entry)
                issue("unreadable_zip_member", entry.filename, f"{type(error).__name__}: {error}", split=split,
                      image=image.filename if image else "", xml=entry.filename if kind == "xml" else "")
                return None

        decoded = {}
        jpeg_checks = Counter()
        for entry in files:
            split, kind = locations.get(entry, ("", ""))
            if (split, kind) == ("train", "xml"):
                continue
            data = read_entry(entry, kind == "image")
            if kind == "image" and data is not None:
                jpeg_checks[split] += 1
                try:
                    decoded[entry] = _jpeg_size(data)
                except (ValueError, cv2.error) as error:
                    issue("unreadable_jpeg", entry.filename, str(error), split=split, image=entry.filename)
            if (split, kind) == ("test", "xml"):
                issue("unexpected_test_xml", entry.filename, "공식 Test 경로의 추가 XML입니다.",
                      split=split, xml=entry.filename)

        observed, valid = {}, {}
        parsed_xmls = size_checks = 0
        parsed_objects = Counter()
        for entry in train_xmls:
            data = read_entry(entry, True)
            if data is None:
                continue
            image = pairs.get(entry)
            image_path = image.filename if image else ""
            image_name = PurePosixPath(image_path).name
            counts, compared_size, xml_issues = _inspect_xml(data, image_name, decoded.get(image))
            size_checks += compared_size
            for problem in xml_issues:
                issue(problem.type, entry.filename, problem.detail, split="train", image=image_path,
                      xml=entry.filename, index=problem.object_index, category=problem.category)
            if counts is not None:
                parsed_xmls += 1
                parsed_objects.update(counts)
                if image:
                    observed[image_path] = (entry.filename, counts)
                    if image in decoded and not xml_issues:
                        valid[image_path] = observed[image_path]

    issue_counts = Counter(error["type"] for error in errors)
    samples = _sample_candidates(country, path.name, observed, valid, errors)
    summary = {
        "country": country,
        "source": {"path": str(path), "filename": path.name, "size_bytes": path.stat().st_size},
        "zip": {
            "listed_successfully": True,
            "top_level": sorted({entry.filename.split("/", 1)[0] for entry in entries}),
            "directory_entries": sorted(entry.filename for entry in entries if entry.is_dir()),
            "files_by_folder": dict(sorted(file_counts.items())),
            "file_entries": len(files), "uncompressed_file_bytes": sum(entry.file_size for entry in files),
            "files_read_and_crc_ok": len(files) - unreadable_files, "unreadable_files": unreadable_files,
        },
        "splits": {},
        "train_label_validation": {
            "matched_pairs_by_stem": len(pairs),
            "unmatched_images": len(train_images) - len(pairs), "unmatched_xmls": len(train_xmls) - len(pairs),
            "unmatched_files": len(train_images) + len(train_xmls) - 2 * len(pairs),
            "filename_mismatches": issue_counts["filename_mismatch"],
            "parsed_annotation_xmls": parsed_xmls, "valid_xmls": len(valid),
            "invalid_xmls": len(train_xmls) - len(valid),
            "invalid_object_labels": len({(error["xml"], error["object_index"]) for error in errors
                                          if error["object_index"] is not None}),
            "xml_size_comparisons_to_decoded_images": size_checks,
            "xml_image_size_mismatches": issue_counts["size_mismatch"],
            "bbox_issues": {kind: issue_counts[kind] for kind in (
                "bbox_missing_coordinates", "bbox_invalid_coordinates", "bbox_zero_size", "bbox_reversed",
                "bbox_outside_xml", "bbox_outside_image",
            )},
            "all_parsed_xml_objects_by_class": dict(sorted(parsed_objects.items())),
        },
        "train_matched_parsed": _distribution(counts for _, counts in observed.values()),
        "train_valid": _distribution(counts for _, counts in valid.values()),
        "validation_issues_by_type": dict(sorted(issue_counts.items())),
        "sampling": {
            "seed": SEED, "rows": len(samples), "unique_images": len({row["image"] for row in samples}),
            "cross_class_images": len({row["image"] for row in samples if row["cross_class_duplicate"]}),
            "rows_by_selection": dict(Counter(row["class"] or row["selection"] for row in samples)),
        },
    }
    for split in SPLITS:
        images = grouped[split, "image"]
        sizes = Counter(f"{decoded[entry][0]}x{decoded[entry][1]}" for entry in images if entry in decoded)
        summary["splits"][split] = {
            "images": len(images), "xml_files": len(grouped[split, "xml"]),
            "image_formats": dict(Counter(PurePosixPath(entry.filename).suffix.lower() for entry in images)),
            "jpeg_checks_attempted": jpeg_checks[split], "decoded_images": sizes.total(),
            "images_not_decoded": len(images) - sizes.total(), "decoded_resolutions": dict(sorted(sizes.items())),
        }
    summary["total_images"] = sum(split["images"] for split in summary["splits"].values())
    summary["total_xml_files"] = sum(split["xml_files"] for split in summary["splits"].values())
    return summary, errors, samples


def _train_metrics(images: int, xml_files: int, observed: dict, valid: dict, invalid_objects: int) -> dict:
    metrics = {
        "images": images, "xml_files": xml_files, "valid_xml_files": valid["images"],
        "invalid_xml_files": xml_files - valid["images"], "invalid_object_labels": invalid_objects,
        "background_images": observed["background_images"],
        "images_without_target_objects": observed["images_without_target_objects"],
    }
    for category in CLASSES:
        metrics[f"{category}_objects"] = observed["objects"][category]
        metrics[f"{category}_positive_images"] = observed["positive_images"][category]
        metrics[f"{category}_objects_in_valid_xmls"] = valid["objects"][category]
    return metrics


def _czech_train_metrics(directory: Path) -> dict:
    with (directory / "split_manifest.csv").open(encoding="utf-8-sig", newline="") as stream:
        manifest = csv.DictReader(stream)
        train = _distribution(Counter({category: int(row[category]) for category in CLASSES})
                              for row in manifest if row["split"] == "train")
    summary = json.loads((directory / "inspection_summary.json").read_text(encoding="utf-8-sig"))
    recorded = summary["splits"]["actual"]["train"]
    if any(train[key] != recorded[key] for key in recorded):
        raise ValueError("Czech Train 매니페스트와 검사 보고서의 집계가 다릅니다.")
    metrics = _train_metrics(train["images"], train["images"], train, train, 0)
    if summary["errors"]:
        metrics.update(invalid_xml_files=None, invalid_object_labels=None)
    return metrics


def _csv_bytes(fields, rows) -> bytes:
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def run_inspection(japan: Path, india: Path, czech_dir: Path, output_dir: Path) -> dict:
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(f"출력 경로가 이미 있습니다. {output_dir}")
    comparison = {"czech_v2_train": _czech_train_metrics(czech_dir)}
    summaries, errors, samples = {}, [], []
    for country, path in zip(COUNTRIES, (japan, india), strict=True):
        summary, archive_errors, archive_samples = inspect_archive(path, country)
        name = country.lower()
        summaries[name] = summary
        train, test = (summary["splits"][split] for split in SPLITS)
        comparison[f"{name}_train"] = _train_metrics(
            train["images"], train["xml_files"], summary["train_matched_parsed"], summary["train_valid"],
            summary["train_label_validation"]["invalid_object_labels"],
        )
        comparison[f"{name}_official_test"] = {key: test[key] for key in ("images", "xml_files")}
        errors.extend(archive_errors)
        samples.extend(archive_samples)

    rows = ({"metric": key, **{name: metrics.get(key) for name, metrics in comparison.items()}}
            for key in comparison["czech_v2_train"])
    with ExitStack() as cleanup:
        _create_dir(output_dir, cleanup, parents=True)
        for name, summary in summaries.items():
            payload = (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            _write_file(output_dir / f"{name}_summary.json", payload, cleanup)
        _write_file(output_dir / "class_comparison.csv", _csv_bytes(("metric", *comparison), rows), cleanup)
        _write_file(output_dir / "validation_errors.csv", _csv_bytes(ERROR_FIELDS, errors), cleanup)
        _write_file(output_dir / "sample_candidates.csv", _csv_bytes(SAMPLE_FIELDS, samples), cleanup)
        cleanup.pop_all()
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(description="RDD2022 Japan·India ZIP의 이미지와 라벨을 검사합니다.")
    parser.add_argument("--japan-zip", type=Path, required=True)
    parser.add_argument("--india-zip", type=Path, required=True)
    parser.add_argument("--czech-processed-dir", type=Path, default=PROJECT_ROOT / "data/processed/rdd2022_czech_v2")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data/processed/rdd2022_japan_india_inspection")
    args = parser.parse_args()
    try:
        summaries = run_inspection(args.japan_zip, args.india_zip, args.czech_processed_dir, args.output_dir)
    except (OSError, BadZipFile, KeyError, ValueError) as error:
        parser.exit(1, f"[{type(error).__name__}] {error}\n")
    for summary in summaries.values():
        validation = summary["train_label_validation"]
        print(f"{summary['country']} | JPG {summary['total_images']}장 | XML {summary['total_xml_files']}개"
              f" | 유효 XML {validation['valid_xmls']}개 | 오류 행 {sum(summary['validation_issues_by_type'].values())}개")
    print(args.output_dir.resolve())


if __name__ == "__main__":
    main()
