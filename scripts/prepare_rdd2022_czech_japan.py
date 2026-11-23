import argparse
import csv
import json
import logging
import ntpath
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field, replace
from hashlib import file_digest, sha256
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zipfile import BadZipFile, ZipFile, ZipInfo

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.inspect_rdd2022_japan_india import AnnotationIssue, BBOX_COORDINATES, _csv_bytes, _read_annotation
from scripts.review_rdd2022_japan_india import _pixel_sha256, _read_pixels
from road_anomaly.rdd2022 import (
    CLASSES, D_HASH_DISTANCE, JPEG_SUFFIXES, READ_ERRORS, SEED, SPLITS, Box, Image,
    _assign_splits, _connected_groups, _create_dir, _dataset_yaml, _difference_hash, _distribution,
    _draw_boxes, _verify_label, _write_file, _yolo_label,
)


PILOT = "rdd2022_czech_japan_pilot_v1"
HOLDOUT = "rdd2022_japan_holdout_v1"
PILOT_LIMIT = 2263
PILOT_CLASS_WEIGHTS = dict(zip(CLASSES, (1.0, 1.25, 1.0, 1.5), strict=True))
NEIGHBOR_GAP = 3
NEIGHBOR_DISTANCE = 24
NEIGHBOR_MAE = 18.0
JAPAN_IMAGES = "Japan/train/images"
JAPAN_XMLS = "Japan/train/annotations/xmls"
VISUAL_SUSPECTS = {"라벨 오류 의심", "파손 라벨 누락 의심"}
CLASS_MAP = dict(enumerate(CLASSES))
AUDIT_FIELDS = ("source_image", "source_xml", "type", "detail", "object_index", "category")
LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Photo:
    image: Image
    pixel_sha256: str
    byte_size: int
    thumbnail: np.ndarray | None = field(default=None, repr=False, compare=False)


@dataclass
class JapanSample:
    member: str
    annotation: str
    photo: Photo | None = None
    xml_sha256: str = ""
    counts: Counter | None = None
    issues: list[AnnotationIssue] = field(default_factory=list)


@dataclass(frozen=True)
class CzechSample:
    photo: Photo
    split: str
    image_path: Path
    label_path: Path
    label_sha256: str
    label_size: int
    source: dict


def _sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return file_digest(handle, "sha256").hexdigest()


def _photo(member: str, data: bytes, *, thumbnail: bool = False) -> tuple[Photo, int | None]:
    frame, metadata = _read_pixels(data)
    height, width = frame.shape[:2]
    if min(height, width) < 10:
        raise ValueError("이미지 한 변이 10px 미만입니다.")
    image = Image(member, width, height, sha256(data).hexdigest(), _difference_hash(frame))
    small = cv2.resize(frame, (32, 32), interpolation=cv2.INTER_AREA) if thumbnail else None
    return Photo(image, _pixel_sha256(frame), len(data), small), metadata["exif_orientation"]


def _split_files(root: Path, split: str) -> dict[str, tuple[Path, Path]]:
    def index(folder: str, suffixes: set[str]) -> dict[str, Path]:
        paths = {}
        for path in sorted((root / folder / split).iterdir()):
            stem = path.stem.casefold()
            if not path.is_file() or path.suffix.lower() not in suffixes or stem in paths:
                raise ValueError(f"중복되거나 지원하지 않는 파일입니다. {path}")
            paths[stem] = path
        return paths

    images, labels = index("images", JPEG_SUFFIXES), index("labels", {".txt"})
    if images.keys() != labels.keys() or any(path.with_suffix(".txt").name != labels[key].name
                                            for key, path in images.items()):
        raise ValueError(f"이미지와 라벨이 일대일 대응하지 않습니다. {root} / {split}")
    return {key: (path, labels[key]) for key, path in images.items()}


def _czech_boxes(label: bytes, image: Image, path: Path) -> tuple[Box, ...]:
    boxes = []
    for row in label.decode("utf-8").splitlines():
        category, cx, cy, width, height = row.split()
        cx, cy, width, height = map(float, (cx, cy, width, height))
        # 10자리 정규화 좌표를 역산할 때 이미지 경계에서 생기는 반올림 오차를 허용한다.
        if category not in {"0", "1", "2", "3"} or not (
            0 <= cx <= 1 and 0 <= cy <= 1 and 0 < width <= 1 and 0 < height <= 1
            and -1e-9 <= cx - width / 2 < cx + width / 2 <= 1 + 1e-9
            and -1e-9 <= cy - height / 2 < cy + height / 2 <= 1 + 1e-9
        ):
            raise ValueError(f"Czech v2 라벨의 클래스 또는 좌표가 유효하지 않습니다. {path} / {row}")
        boxes.append(Box(CLASS_MAP[int(category)], (
            (cx - width / 2) * image.width, (cy - height / 2) * image.height,
            (cx + width / 2) * image.width, (cy + height / 2) * image.height,
        )))
    return tuple(boxes)


def _read_czech(root: Path, manifest: Path) -> dict[str, CzechSample]:
    pairs = {split: _split_files(root, split) for split in SPLITS}
    samples = {}
    used_stems = set()
    with manifest.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            split = row["split"]
            name = PureWindowsPath(row["source_image"]).name
            stem = Path(name).stem.casefold()
            if split not in pairs or stem in used_stems or stem not in pairs[split]:
                raise ValueError(f"Czech v2 매니페스트와 실제 분할이 다릅니다. {split} / {name}")
            image_path, label_path = pairs[split].pop(stem)
            member = f"Czech/{split}/{image_path.name}"
            photo, orientation = _photo(member, image_path.read_bytes())
            if image_path.name != name or photo.image.digest != row["sha256"] or orientation not in (None, 1):
                raise ValueError(f"Czech v2 이미지 이름, 해시 또는 좌표계가 다릅니다. {image_path}")
            label = label_path.read_bytes()
            boxes = _czech_boxes(label, photo.image, label_path)
            counts = Counter(box.category for box in boxes)
            if any(counts[category] != int(row[category]) for category in CLASSES):
                raise ValueError(f"Czech v2 라벨의 클래스별 객체 수가 다릅니다. {label_path}")
            photo = replace(photo, image=replace(photo.image, boxes=boxes))
            samples[member] = CzechSample(photo, split, image_path, label_path, sha256(label).hexdigest(), len(label), row)
            used_stems.add(stem)
    if any(pairs.values()) or {sample.split for sample in samples.values()} != set(SPLITS):
        raise ValueError("Czech v2 매니페스트가 전체 Train/Val/Test 파일을 포함해야 합니다.")
    return samples


def _zip_index(archive: ZipFile, folder: str, suffixes: set[str]) -> dict[str, ZipInfo]:
    files = {}
    for info in archive.infolist():
        parent, _, filename = info.filename.rpartition("/")
        path = PurePosixPath(filename)
        if info.is_dir() or parent != folder or path.suffix.lower() not in suffixes:
            continue
        stem = path.stem.casefold()
        if ntpath.isreserved(filename) or stem in files:
            raise ValueError(f"ZIP에 안전하지 않거나 중복된 파일명이 있습니다. {info.filename}")
        files[stem] = info
    return files


def _visual_suspects(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {
            row["source_image"]: row["label_quality"] for row in csv.DictReader(handle)
            if row["country"] == "Japan" and row["label_quality"] in VISUAL_SUSPECTS
        }


def _audit_row(member: str, annotation: str, issue: AnnotationIssue) -> dict:
    return {"source_image": member, "source_xml": annotation, **asdict(issue)}


def _scan_japan(archive: ZipFile, visual: dict[str, str]) -> tuple[dict[str, JapanSample], dict, list[dict]]:
    jpgs = _zip_index(archive, JAPAN_IMAGES, JPEG_SUFFIXES)
    xmls = _zip_index(archive, JAPAN_XMLS, {".xml"})
    if not jpgs or not xmls:
        raise ValueError("Japan ZIP에 Train JPG 또는 XML이 없습니다.")
    samples = {}
    for stem, entry in sorted(jpgs.items()):
        annotation = xmls.get(stem)
        sample = JapanSample(entry.filename, annotation.filename if annotation else "")
        samples[sample.member] = sample
        try:
            sample.photo, orientation = _photo(sample.member, archive.read(entry), thumbnail=True)
            if orientation not in (None, 1):
                sample.issues.append(AnnotationIssue("exif_orientation", f"원본 회전 태그 {orientation}"))
        except (*READ_ERRORS, cv2.error, SyntaxError) as error:
            sample.issues.append(AnnotationIssue("unreadable_jpg", str(error)))
        if not annotation:
            sample.issues.append(AnnotationIssue("missing_xml", "동일한 이름의 Train XML이 없습니다."))
            continue
        try:
            content = archive.read(annotation)
        except READ_ERRORS as error:
            sample.issues.append(AnnotationIssue("unreadable_xml", str(error)))
            continue

        sample.xml_sha256 = sha256(content).hexdigest()
        image = sample.photo.image if sample.photo else None
        size = (image.width, image.height) if image else None
        root, sample.counts, _, issues = _read_annotation(content, PurePosixPath(sample.member).name, size)
        sample.issues.extend(issues)
        if sample.issues:
            continue
        boxes = tuple(
            Box(category, tuple(float(obj.findtext(f"bndbox/{key}")) for key in BBOX_COORDINATES))
            for obj in root.findall("object") if (category := (obj.findtext("name") or "").strip()) in CLASSES
        )
        sample.photo = replace(sample.photo, image=replace(image, annotation=sample.annotation, boxes=boxes))

    valid = [sample for sample in samples.values() if not sample.issues]
    stats = {
        "train_images": len(jpgs), "train_xmls": len(xmls), "paired_by_stem": len(jpgs.keys() & xmls.keys()),
        "decoded_train_images": sum(sample.photo is not None for sample in samples.values()),
        "valid_image_xml_pairs": len(valid),
        "valid_target_objects": {category: sum(sample.counts[category] for sample in valid) for category in CLASSES},
        "valid_empty_xml": sum(not sample.counts for sample in valid),
        "valid_other_only": sum(bool(sample.counts) and not sample.photo.image.boxes for sample in valid),
        "official_test_images": len(_zip_index(archive, "Japan/test/images", JPEG_SUFFIXES)),
        "official_test_xmls": sum(entry.filename.startswith("Japan/test/") and entry.filename.lower().endswith(".xml")
                                  for entry in archive.infolist() if not entry.is_dir()),
    }
    for sample in samples.values():
        if sample.member in visual:
            sample.issues.append(AnnotationIssue("visual_review_suspect", visual[sample.member]))
        if sample.counts and not any(sample.counts[category] for category in CLASSES):
            sample.issues.append(AnnotationIssue("other_classes_only", "대상 4종이 없고 XML에 기타 클래스가 있습니다."))
    orphan_xmls = [
        _audit_row("", xmls[stem].filename, AnnotationIssue("missing_jpg", "동일한 이름의 Train JPG가 없습니다."))
        for stem in sorted(xmls.keys() - jpgs.keys())
    ]
    return samples, stats, orphan_xmls


def _japan_number(member: str) -> int | None:
    match = re.fullmatch(r"Japan_(\d+)", PurePosixPath(member).stem)
    return int(match[1]) if match else None


def _hash_blocks(value: int) -> list[tuple[int, int]]:
    # 8비트 이하가 다르면 9개의 겹치지 않는 구간 중 적어도 하나가 일치한다.
    parts = D_HASH_DISTANCE + 1
    width, extra = divmod(128, parts)
    blocks = []
    for part in range(parts):
        bits = width + (part < extra)
        blocks.append((part, value & ((1 << bits) - 1)))
        value >>= bits
    return blocks


def _duplicate_pairs(photos: dict[str, Photo]) -> tuple[list[dict], dict[str, int]]:
    indexed_jpeg, indexed_pixels, indexed_blocks, indexed_numbers = (defaultdict(list) for _ in range(4))
    pairs = []
    comparisons = Counter(hash_candidates=0, adjacent_candidates=0)
    for member, photo in sorted(photos.items()):
        image = photo.image
        blocks = _hash_blocks(image.dhash)
        japan = member.startswith("Japan/")
        number = _japan_number(member) if japan else None
        if japan:
            hash_candidates = set(indexed_jpeg[image.digest]) | set(indexed_pixels[photo.pixel_sha256])
            for block in blocks:
                hash_candidates.update(indexed_blocks[block])
            adjacent = set() if number is None else {
                previous for gap in range(1, NEIGHBOR_GAP + 1) for offset in (-gap, gap)
                for previous in indexed_numbers[number + offset]
            }
            comparisons.update(hash_candidates=len(hash_candidates), adjacent_candidates=len(adjacent))
            for previous in sorted(hash_candidates | adjacent):
                other = photos[previous]
                jpeg_same = image.digest == other.image.digest
                pixel_same = photo.pixel_sha256 == other.pixel_sha256
                distance = (image.dhash ^ other.image.dhash).bit_count()
                near = previous in adjacent and distance <= NEIGHBOR_DISTANCE
                mae = float(cv2.norm(photo.thumbnail, other.thumbnail, cv2.NORM_L1) / photo.thumbnail.size) if near else None
                similar = distance <= D_HASH_DISTANCE
                adjacent_scene = mae is not None and mae <= NEIGHBOR_MAE
                if jpeg_same or pixel_same or similar or adjacent_scene:
                    pairs.append({
                        "a": previous, "b": member, "jpeg_sha256_equal": jpeg_same, "pixel_sha256_equal": pixel_same,
                        "dhash_distance": distance, "dhash_candidate": similar, "adjacent_scene_candidate": adjacent_scene,
                        "filename_gap": abs(number - _japan_number(previous)) if previous in adjacent else None,
                        "thumbnail_bgr_mae": mae,
                    })
        indexed_jpeg[image.digest].append(member)
        indexed_pixels[photo.pixel_sha256].append(member)
        for block in blocks:
            indexed_blocks[block].append(member)
        if number is not None:
            indexed_numbers[number].append(member)
    return pairs, dict(comparisons)


def _group_and_split(
    japan: dict[str, JapanSample], czech: dict[str, CzechSample], photos: dict[str, Photo], pairs: list[dict],
) -> tuple[dict[str, str], dict[str, str], dict[str, int]]:
    groups = _connected_groups([photo.image for photo in photos.values()], pairs)
    czech_splits = defaultdict(set)
    for member, sample in czech.items():
        czech_splits[groups[member]].add(sample.split)
    for sample in japan.values():
        collisions = czech_splits.get(groups.get(sample.member))
        if collisions:
            reason = "czech_eval_overlap" if collisions & {"val", "test"} else "czech_train_overlap"
            sample.issues.append(AnnotationIssue(reason, ",".join(sorted(collisions))))
    for pair in pairs:
        left, right = japan.get(pair["a"]), japan.get(pair["b"])
        if left and right and pair["pixel_sha256_equal"] and left.photo.image.annotation and right.photo.image.annotation:
            if Counter(left.photo.image.boxes) != Counter(right.photo.image.boxes) or left.counts != right.counts:
                left.issues.append(AnnotationIssue("duplicate_label_conflict", right.member))
                right.issues.append(AnnotationIssue("duplicate_label_conflict", left.member))

    eligible = [sample.photo.image for sample in japan.values() if not sample.issues]
    assignments, targets = _assign_splits(eligible, groups)
    # 모든 직접 연결 및 이어진 경로가 배제 또는 단일 Japan 분할로 귀결되는지 확인한다.
    group_splits = defaultdict(set)
    for member, split in assignments.items():
        group_splits[groups[member]].add(split)
    if any(len(splits) > 1 or group in czech_splits for group, splits in group_splits.items()):
        raise RuntimeError("Japan 분할 간 또는 Czech와 유사 그룹이 교차합니다.")
    return groups, assignments, targets


def _pilot_selection(
    photos: dict[str, Photo], assignments: dict[str, str], groups: dict[str, str], limit: int,
) -> set[str]:
    members = sorted(member for member, split in assignments.items() if split == "train")
    order = np.random.default_rng(SEED).permutation(len(members))
    members = [members[index] for index in order]
    group_indices = defaultdict(list)
    rows, tags = [], []
    for index, member in enumerate(members):
        photo = photos[member]
        image = photo.image
        group_indices[groups[member]].append(index)
        counts = Counter(box.category for box in image.boxes)
        rows.append([not counts, *(bool(counts[c]) for c in CLASSES), *(counts[c] for c in CLASSES)])
        number = _japan_number(member)
        tags.append((
            ("filename_bin", number // 1000 if number is not None else -1),
            ("resolution", f"{image.width}x{image.height}"),
            ("brightness", int(photo.thumbnail.mean()) // 64),
        ))
    buckets = sorted({tag for labels in tags for tag in labels})
    features = np.array([row + [tag in labels for tag in buckets] for row, labels in zip(rows, tags, strict=True)],
                        dtype=np.float64)
    count = min(limit, len(group_indices))
    targets = features.sum(axis=0) * count / len(members)
    targets[1:9] *= list(PILOT_CLASS_WEIGHTS.values()) * 2
    importance = np.array([1.0] * 5 + [0.6] * 4 + [0.2] * len(buckets))
    penalty = importance / np.maximum(targets, 1) ** 2
    self_cost = (features ** 2) @ penalty
    observed = np.zeros_like(targets)
    available = np.ones(len(members), dtype=bool)
    selected = set()
    # 이미지 단위 객체·클래스·배경 분포를 함께 맞추고 유사 그룹에서는 한 장만 뽑는다.
    for _ in range(count):
        costs = np.einsum("ij,j->i", features, 2 * (observed - targets) * penalty) + self_cost
        costs[~available] = np.inf
        index = int(costs.argmin())
        member = members[index]
        selected.add(member)
        available[group_indices[groups[member]]] = False
        observed += features[index]
    return selected


def _published_splits(
    czech: dict[str, CzechSample], assignments: dict[str, str], selected: set[str],
) -> dict[str, dict[str, list[str]]]:
    pilot = {split: sorted(member for member, sample in czech.items() if sample.split == split) for split in SPLITS}
    pilot["train"].extend(sorted(selected))
    return {
        PILOT: pilot,
        HOLDOUT: {split: sorted(member for member, assigned in assignments.items() if assigned == split)
                  for split in ("val", "test")},
    }


def _label_path(image_path: Path) -> Path:
    return Path("labels", image_path.parent.name, image_path.with_suffix(".txt").name)


def _manifest_rows(
    japan: dict[str, JapanSample], czech: dict[str, CzechSample], groups: dict[str, str], assignments: dict[str, str],
    selected: set[str], published: dict[str, dict[str, list[str]]],
) -> tuple[list[dict], list[dict]]:
    output_paths = {member: (dataset, Path("images", split, PurePosixPath(member).name))
                    for dataset, splits in published.items() for split, members in splits.items() for member in members}
    selected_groups = {groups[member] for member in selected}
    split_rows, selection_rows = [], []
    for member in sorted((*japan, *czech)):
        existing = czech.get(member)
        split = existing.split if existing else assignments.get(member, "")
        photo = existing.photo if existing else japan[member].photo
        counts = Counter(box.category for box in photo.image.boxes) if existing else japan[member].counts
        counts = counts or Counter()
        other = {category: counts[category] for category in sorted(counts.keys() - set(CLASSES))}
        dataset, path = output_paths.get(member, ("", None))
        row = {
            "member": member, "country": "Czech" if existing else "Japan",
            "source_image": existing.source["source_image"] if existing else member,
            "source_xml": existing.source["source_annotation"] if existing else japan[member].annotation,
            "baseline_image": str(existing.image_path) if existing else "",
            "baseline_label": str(existing.label_path) if existing else "",
            "split": split, "group_id": groups.get(member, ""),
            "baseline_group": existing.source["group_id"] if existing else "",
            "jpeg_sha256": photo.image.digest if photo else "", "pixel_sha256": photo.pixel_sha256 if photo else "",
            "dhash_128": f"{photo.image.dhash:032x}" if photo else "",
            "xml_sha256": "" if existing else japan[member].xml_sha256,
            "label_sha256": existing.label_sha256 if existing else
            sha256(_yolo_label(photo.image).encode("utf-8")).hexdigest() if path else "",
            "width": photo.image.width if photo else "", "height": photo.image.height if photo else "",
            **{category: counts[category] for category in CLASSES}, "other_classes": json.dumps(other, sort_keys=True),
            "label_type": ("target" if any(counts[category] for category in CLASSES) else
                           "other_only" if other else "no_objects" if existing or japan[member].counts is not None else ""),
            "issues": "" if existing else "|".join(sorted({issue.type for issue in japan[member].issues})),
            "dataset": dataset, "output_image": path.as_posix() if path else "",
            "output_label": _label_path(path).as_posix() if path else "",
        }
        split_rows.append(row)
        if not existing and split == "train":
            selection_rows.append({
                "source_image": member, "group_id": row["group_id"], "selected": member in selected,
                "reason": ("selected" if member in selected else "group_member_selected" if groups[member] in
                           selected_groups else "pilot_limit_and_balance"),
                **{key: row[key] for key in (*CLASSES, "label_type", "other_classes", "output_image", "output_label")},
            })
    return split_rows, selection_rows


def _pair_scope(pair: dict, czech: dict[str, CzechSample]) -> str:
    existing = czech.get(pair["a"])
    return f"czech_{existing.split}" if existing else "japan"


def _pair_rows(
    pairs: list[dict], groups: dict[str, str], assignments: dict[str, str], czech: dict[str, CzechSample],
) -> list[dict]:
    splits = {member: sample.split for member, sample in czech.items()} | assignments
    return [{**pair, "scope": _pair_scope(pair, czech), "group_id": groups[pair["a"]],
             "split_a": splits.get(pair["a"], ""), "split_b": splits.get(pair["b"], "")} for pair in pairs]


def _pair_statistics(rows: list[dict]) -> dict:
    result = {}
    for scope in ("japan", "czech_train", "czech_val", "czech_test"):
        scope_rows = [row for row in rows if row["scope"] == scope]
        result[scope] = {
            "pairs": len(scope_rows),
            **{key: sum(row[key] for row in scope_rows) for key in
               ("jpeg_sha256_equal", "pixel_sha256_equal", "dhash_candidate", "adjacent_scene_candidate")},
            "adjacent_only": sum(row["adjacent_scene_candidate"] and not
                                 (row["jpeg_sha256_equal"] or row["pixel_sha256_equal"] or row["dhash_candidate"])
                                 for row in scope_rows),
            "groups": len({row["group_id"] for row in scope_rows}),
        }
    return result


def _stats(members: list[str], photos: dict[str, Photo], japan: dict[str, JapanSample]) -> dict:
    stats = _distribution([photos[member].image for member in members])
    other = Counter()
    for member in members:
        if member in japan:
            other.update({key: count for key, count in japan[member].counts.items() if key not in CLASSES})
    stats["background_ratio"] = stats["background_images"] / len(members) if members else 0.0
    stats["ignored_other_objects"] = dict(sorted(other.items()))
    return stats


def _side_by_side(left: np.ndarray, right: np.ndarray, titles: tuple[str, str], path: Path, cleanup: ExitStack) -> None:
    def titled(frame: np.ndarray, text: str) -> np.ndarray:
        tile = cv2.copyMakeBorder(frame, 32, 0, 0, 0, cv2.BORDER_CONSTANT, value=(28, 28, 28))
        cv2.putText(tile, text, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (242, 242, 242), 1, cv2.LINE_AA)
        return tile

    frame = np.hstack((titled(left, titles[0]), titled(right, titles[1])))
    encoded, png = cv2.imencode(".png", frame)
    if not encoded:
        raise RuntimeError(f"미리보기를 저장할 수 없습니다. {path}")
    _write_file(path, png.tobytes(), cleanup)


def _preview_examples(members: list[str], photos: dict[str, Photo]) -> dict[str, str]:
    examples = {}
    for category in (*CLASSES, "background"):
        member = next((member for member in members if member not in examples and (
            any(box.category == category for box in photos[member].image.boxes) if category != "background"
            else not photos[member].image.boxes
        )), None)
        if member:
            examples[member] = category
    return examples


def _copy_and_verify(
    archive: ZipFile, japan: dict[str, JapanSample], czech: dict[str, CzechSample], photos: dict[str, Photo],
    published: dict[str, dict[str, list[str]]], roots: dict[str, Path], processed: Path, cleanup: ExitStack,
) -> dict:
    validation = {"images": 0, "czech_pairs_copied": 0, "japan_labels": 0, "japan_boxes": 0,
                  "max_bbox_roundtrip_error_px": 0.0, "previews": []}
    preview_dir = processed / "bbox_previews"
    _create_dir(preview_dir, cleanup)
    previews = _preview_examples([member for member in published[PILOT]["train"] if member in japan], photos)
    previews.update(_preview_examples(published[HOLDOUT]["val"], photos))
    for dataset, splits in published.items():
        root = roots[dataset]
        _create_dir(root, cleanup, parents=True)
        for kind in ("images", "labels"):
            _create_dir(root / kind, cleanup)
            for split in splits:
                _create_dir(root / kind / split, cleanup)
        for split, members in splits.items():
            for member in members:
                image = photos[member].image
                relative_image_path = Path("images", split, PurePosixPath(member).name)
                output = root / relative_image_path
                label_path = root / _label_path(relative_image_path)
                existing = czech.get(member)
                if existing:
                    data, label = existing.image_path.read_bytes(), existing.label_path.read_bytes()
                    label_digest = existing.label_sha256
                    validation["czech_pairs_copied"] += 1
                else:
                    data = archive.read(member)
                    if sha256(archive.read(image.annotation)).hexdigest() != japan[member].xml_sha256:
                        raise ValueError(f"검사 후 원본 XML이 바뀌었습니다. {image.annotation}")
                    label = _yolo_label(image).encode("utf-8")
                    label_digest = sha256(label).hexdigest()
                if sha256(data).hexdigest() != image.digest or sha256(label).hexdigest() != label_digest:
                    raise ValueError(f"검사 후 원본 파일이 바뀌었습니다. {member}")
                _write_file(output, data, cleanup)
                _write_file(label_path, label, cleanup)
                if _sha256_file(output) != image.digest or _sha256_file(label_path) != label_digest:
                    raise ValueError(f"생성한 이미지 또는 라벨의 해시가 다릅니다. {output}")

                if not existing:
                    boxes, error = _verify_label(label_path, image)
                    validation["japan_labels"] += 1
                    validation["japan_boxes"] += len(boxes)
                    validation["max_bbox_roundtrip_error_px"] = max(validation["max_bbox_roundtrip_error_px"], error)
                    if member in previews:
                        original, _ = _read_pixels(data)
                        rendered = original.copy()
                        _draw_boxes(original, image.boxes)
                        _draw_boxes(rendered, boxes)
                        target = preview_dir / f"{split}_{previews[member]}_{output.stem}.png"
                        _side_by_side(original, rendered, ("XML / target classes", "YOLO / decoded"), target, cleanup)
                        validation["previews"].append({
                            "path": target.relative_to(processed).as_posix(), "image": member, "split": split,
                            "same_overlay": bool(np.array_equal(original, rendered)),
                        })
            paths = _split_files(root, split)
            if len(paths) != len(members):
                raise ValueError(f"이미지·라벨 쌍 수가 예상과 다릅니다. {root} / {split}")
            validation["images"] += len(paths)
        _write_file(root / "data.yaml", _dataset_yaml(tuple(splits)), cleanup)
    return validation


def _verify_ultralytics(roots: dict[str, Path], stats: dict, scratch_parent: Path, czech_dir: Path) -> dict:
    # 라벨 캐시, JPEG 복구 및 설정 파일 쓰기를 임시 복사본 안으로 제한한다.
    with TemporaryDirectory(dir=scratch_parent, prefix="ultralytics-") as temporary:
        scratch = Path(temporary)
        with patch.dict(os.environ, YOLO_CONFIG_DIR=str(scratch / "config"), MPLCONFIGDIR=str(scratch / "mpl"),
                        YOLO_OFFLINE="true", YOLO_AUTOINSTALL="false"):
            import ultralytics
            from ultralytics.data import utils
            from ultralytics.data.dataset import YOLODataset
            from ultralytics.utils import YAML

            baseline = YAML.load(czech_dir / "data.yaml")
            if baseline.get("names") != CLASS_MAP or any(baseline.get(split) != f"images/{split}" for split in SPLITS):
                raise ValueError(f"Czech v2 data.yaml의 클래스 또는 분할 경로가 다릅니다. {czech_dir}")

            observed = {"version": ultralytics.__version__, "yaml_checked": [], "loaded_splits": {}}
            for dataset, root in roots.items():
                with patch.object(utils, "check_font"):
                    config = utils.check_det_dataset(root / "data.yaml", autodownload=False)
                if config["names"] != CLASS_MAP or any(
                    config.get(split) != (str(root / "images" / split) if split in stats[dataset] else None)
                    for split in SPLITS
                ):
                    raise ValueError(f"Ultralytics가 해석한 클래스와 분할 경로가 다릅니다. {root}")
                observed["yaml_checked"].append(dataset)
                observed["loaded_splits"][dataset] = {}
                for split in stats[dataset]:
                    if split == "test":
                        continue
                    for kind in ("images", "labels"):
                        shutil.copytree(root / kind / split, scratch / dataset / kind / split)
                    data = YOLODataset(img_path=str(scratch / dataset / "images" / split), data=config, cache=False,
                                       augment=False, prefix=f"{dataset}/{split} ")
                    counts = Counter(int(value) for row in data.labels for value in row["cls"].ravel())
                    expected = stats[dataset][split]
                    if (len(data) != expected["images"]
                        or sum(not len(row["cls"]) for row in data.labels) != expected["background_images"]
                        or any(counts[index] != expected["objects"][category] for index, category in CLASS_MAP.items())):
                        raise ValueError(f"Ultralytics가 읽은 이미지 또는 라벨 수가 다릅니다. {dataset} / {split}")
                    observed["loaded_splits"][dataset][split] = len(data)
            return observed


def _duplicate_previews(
    archive: ZipFile, czech: dict[str, CzechSample], rows: list[dict], processed: Path, cleanup: ExitStack,
) -> list[dict]:
    examples = {}
    for row in rows:
        scope = row["scope"]
        if scope != "japan":
            examples.setdefault(scope, row)
        elif row["jpeg_sha256_equal"] or row["pixel_sha256_equal"]:
            examples.setdefault("japan_exact", row)
        elif row["dhash_candidate"]:
            examples.setdefault("japan_dhash", row)
        else:
            examples.setdefault("japan_adjacent", row)
            edge = examples.setdefault("japan_adjacent_edge", row)
            if row["dhash_distance"] > edge["dhash_distance"]:
                examples["japan_adjacent_edge"] = row
    if examples.get("japan_adjacent_edge") == examples.get("japan_adjacent"):
        examples.pop("japan_adjacent_edge", None)
    if not examples:
        return []
    folder = processed / "duplicate_previews"
    _create_dir(folder, cleanup)
    previews = []
    for kind, row in examples.items():
        members = (row["a"], row["b"])
        tiles = []
        for member in members:
            source = czech[member].image_path.read_bytes() if member in czech else archive.read(member)
            frame, _ = _read_pixels(source)
            tiles.append(cv2.resize(frame, (540, 540), interpolation=cv2.INTER_AREA))
        target = folder / f"{kind}.png"
        _side_by_side(*tiles, tuple(PurePosixPath(member).name for member in members), target, cleanup)
        previews.append({"path": target.relative_to(processed).as_posix(), **row})
    return previews


def _czech_preservation(czech: dict[str, CzechSample], root: Path) -> dict:
    after = {path for split in SPLITS for pair in _split_files(root, split).values() for path in pair}
    before = {path for sample in czech.values() for path in (sample.image_path, sample.label_path)}
    if after != before:
        raise ValueError("Czech v2 분할의 파일 목록이 검사 중 바뀌었습니다.")
    digest = sha256()
    for member, sample in sorted(czech.items()):
        image_hash = _sha256_file(sample.image_path)
        label_hash = _sha256_file(sample.label_path)
        if image_hash != sample.photo.image.digest or label_hash != sample.label_sha256:
            raise ValueError(f"Czech v2 이미지 또는 라벨의 해시가 검사 중 바뀌었습니다. {member}")
        digest.update(f"{member},{image_hash},{label_hash}\n".encode("utf-8"))
    return {"images": len(czech), "labels": len(czech), "pairs_sha256": digest.hexdigest()}


def _space_estimate(
    published: dict[str, dict[str, list[str]]], photos: dict[str, Photo], czech: dict[str, CzechSample],
    processed: Path, roots: dict[str, Path],
) -> dict:
    sizes = {}
    for dataset, splits in published.items():
        for split, members in splits.items():
            label_bytes = sum(czech[member].label_size if member in czech else len(_yolo_label(photos[member].image))
                              for member in members)
            sizes[dataset, split] = sum(photos[member].byte_size for member in members) + label_bytes
    data_bytes = sum(sizes.values())
    scratch_bytes = sum(size for (_, split), size in sizes.items() if split != "test")
    # 디스크 할당 단위, 미리보기, 설정, 라벨 캐시에 필요한 공간도 남긴다.
    reserve_bytes = 128 * 1024 ** 2
    available = min(shutil.disk_usage(next(parent for parent in root.parents if parent.exists())).free
                    for root in (processed, *roots.values()))
    return {"output_image_label_bytes": data_bytes, "scratch_image_label_bytes": scratch_bytes,
            "reserve_bytes": reserve_bytes, "required_bytes": data_bytes + scratch_bytes + reserve_bytes,
            "free_bytes": available}


def _write_summary(path: Path, summary: dict, cleanup: ExitStack) -> None:
    _write_file(path, (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8"), cleanup)


def prepare_pilot(
    japan_zip: Path, czech_dir: Path, czech_manifest: Path, visual_manifest: Path, data_dir: Path,
) -> dict:
    """Czech v2와 Japan Train을 읽어 Pilot 및 Japan 평가용 데이터셋을 발행한다."""
    japan_zip, czech_dir, czech_manifest, visual_manifest = (
        path.resolve(strict=True) for path in (japan_zip, czech_dir, czech_manifest, visual_manifest)
    )
    processed = data_dir / "processed" / PILOT
    roots = {name: data_dir / "yolo" / name for name in (PILOT, HOLDOUT)}
    for output in (processed, *roots.values()):
        if output.exists() or output.is_symlink():
            raise FileExistsError(f"출력 경로가 이미 있습니다. {output}")
    processed = processed.resolve()
    roots = {name: path.resolve() for name, path in roots.items()}
    outputs = (processed, *roots.values())
    for output in outputs:
        if output.is_relative_to(czech_dir) or any(
            other.is_relative_to(output) for other in outputs if other is not output
        ):
            raise ValueError(f"출력 경로가 Czech v2 또는 다른 출력과 겹칩니다. {output}")
    sources = {"japan_zip": japan_zip, "czech_manifest": czech_manifest, "czech_yaml": czech_dir / "data.yaml",
               "visual_manifest": visual_manifest}
    source_hashes = {key: _sha256_file(path) for key, path in sources.items()}
    czech = _read_czech(czech_dir, czech_manifest)
    with ZipFile(japan_zip, "r") as archive:
        japan, scan, exclusions = _scan_japan(archive, _visual_suspects(visual_manifest))
        photos = {member: sample.photo for member, sample in czech.items()} | {
            member: sample.photo for member, sample in japan.items() if sample.photo is not None
        }
        LOG.info("Czech %d장과 Japan Train %d장 디코딩", len(czech), scan["decoded_train_images"])
        pairs, comparisons = _duplicate_pairs(photos)
        groups, assignments, targets = _group_and_split(japan, czech, photos, pairs)
        pair_rows = _pair_rows(pairs, groups, assignments, czech)
        selected = _pilot_selection(photos, assignments, groups, PILOT_LIMIT)
        selected_groups = {groups[member] for member in selected}
        if any(assignments.get(member) != "train" for member in selected) or len(selected) != len(selected_groups):
            raise RuntimeError("Pilot이 Japan Train 또는 그룹별 선정 조건을 위반했습니다.")
        published = _published_splits(czech, assignments, selected)
        split_rows, selection_rows = _manifest_rows(japan, czech, groups, assignments, selected, published)
        exclusions.extend(_audit_row(sample.member, sample.annotation, issue)
                          for sample in japan.values() for issue in sample.issues)
        files = {
            "split_manifest.csv": (tuple(split_rows[0]), split_rows),
            "selection_manifest.csv": (tuple(selection_rows[0]), selection_rows),
            "duplicate_groups.csv": (("a", "b", "scope", "group_id", "split_a", "split_b", "jpeg_sha256_equal",
                                      "pixel_sha256_equal", "dhash_distance", "dhash_candidate", "adjacent_scene_candidate",
                                      "filename_gap", "thumbnail_bgr_mae"), pair_rows),
            "exclusion_report.csv": (AUDIT_FIELDS, exclusions),
        }
        with ExitStack() as cleanup:
            _create_dir(processed, cleanup, parents=True)
            for name, (fields, rows) in files.items():
                _write_file(processed / name, _csv_bytes(fields, rows), cleanup)
            cleanup.pop_all()

        by_split = {split: [member for member, assigned in assignments.items() if assigned == split] for split in SPLITS}
        japan_stats = {split: _stats(members, photos, japan) for split, members in by_split.items()}
        dataset_stats = {dataset: {split: _stats(members, photos, japan) for split, members in splits.items()}
                         for dataset, splits in published.items()}
        pilot_stats = _stats(sorted(selected), photos, japan)
        group_sizes = Counter(groups[member] for member in japan if member in groups)
        all_group_sizes = Counter(groups.values())
        czech_group_ids = {groups[member] for member in czech}
        summary = {
            "sources": {key: {"path": str(path), "sha256": source_hashes[key]} for key, path in sources.items()},
            "japan_scan": scan | {
                "excluded_from_splits": len(japan) - len(assignments),
                "eligible_for_splits": len(assignments),
                "excluded_by_reason": dict(Counter(issue for sample in japan.values()
                                                   for issue in {entry.type for entry in sample.issues})),
            },
            "similarity": {
                "scanned_czech_images": len(czech), "scanned_japan_images": scan["decoded_train_images"],
                **comparisons,
                "max_dhash_distance": D_HASH_DISTANCE,
                "adjacent_thresholds": {"filename_gap": NEIGHBOR_GAP, "dhash_distance": NEIGHBOR_DISTANCE,
                                        "thumbnail_bgr_mae": NEIGHBOR_MAE},
                "by_scope": _pair_statistics(pair_rows),
                "groups_with_edges": len({row["group_id"] for row in pair_rows}),
                "japan_images_in_groups_with_edges": sum(group_sizes[group] for group in
                                                        {row["group_id"] for row in pair_rows}),
                "largest_group": max(all_group_sizes.values()),
                "japan_group_cross_split": 0,
                "japan_split_groups_overlap_czech": len({groups[member] for member in assignments} & czech_group_ids),
            },
            "japan_split": {"seed": SEED, "target_ratios": dict(zip(SPLITS, (0.8, 0.1, 0.1), strict=True)),
                            "target_images": targets, "actual": japan_stats,
                            "groups": {split: len({groups[member] for member in members})
                                       for split, members in by_split.items()}},
            "pilot": {"limit": PILOT_LIMIT, "class_weights": PILOT_CLASS_WEIGHTS, **pilot_stats,
                      "fraction_of_japan_train": len(selected) / len(by_split["train"]),
                      "fraction_of_source_train": len(selected) / len(japan)},
            "czech": {split: _stats([member for member, sample in czech.items() if sample.split == split], photos, japan)
                      for split in SPLITS},
            "datasets": dataset_stats,
            "paths": {"manifests": str(processed), **{name: str(root / "data.yaml") for name, root in roots.items()}},
        }
        LOG.info("유사 후보 %d쌍 | Japan 분할 %s | Pilot %d장", len(pairs),
                 ", ".join(f"{split} {len(members)}" for split, members in by_split.items()), len(selected))
        report_path = processed / "inspection_summary.json"
        try:
            with ExitStack() as cleanup:
                space = summary["disk"] = _space_estimate(published, photos, czech, processed, roots)
                if space["free_bytes"] < space["required_bytes"]:
                    raise OSError(f"데이터셋과 임시 검증에 필요한 디스크 공간이 부족합니다. {space}")
                if any(not pilot_stats["positive_images"][category] for category in CLASSES) or not pilot_stats["background_images"]:
                    raise ValueError("Pilot에 4개 대상 클래스와 XML에 객체가 없는 배경 이미지가 모두 필요합니다.")
                LOG.info("데이터셋 및 검증 임시 사본에 필요한 공간 %d MiB", space["required_bytes"] // 1024 ** 2)
                summary["conversion"] = _copy_and_verify(archive, japan, czech, photos, published, roots, processed, cleanup)
                summary["similarity"]["previews"] = _duplicate_previews(archive, czech, pair_rows, processed, cleanup)
                summary["ultralytics"] = _verify_ultralytics(roots, dataset_stats, processed.parent, czech_dir)
                summary["czech_preservation"] = _czech_preservation(czech, czech_dir)
                if any(_sha256_file(path) != source_hashes[key] for key, path in sources.items()):
                    raise ValueError("원본 ZIP, Czech YAML 또는 입력 매니페스트의 해시가 바뀌었습니다.")
                summary["verified_source_hashes"] = True
                summary["status"] = "verified"
                _write_summary(report_path, summary, cleanup)
                cleanup.pop_all()
        except (OSError, ValueError, RuntimeError, BadZipFile, cv2.error) as error:
            summary["status"] = "export_failed"
            summary["error"] = f"{type(error).__name__}: {error}"
            with ExitStack() as cleanup:
                _write_summary(report_path, summary, cleanup)
                cleanup.pop_all()
            raise
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Czech v2와 Japan의 YOLO 비교 학습·평가 데이터셋을 구축합니다.")
    parser.add_argument("--japan-zip", type=Path, required=True, help="Japan.zip 원본 경로")
    parser.add_argument("--data-dir", type=Path, default=PROJECT_ROOT / "data", help="새 processed 및 yolo 출력의 상위 폴더")
    parser.add_argument("--czech-dir", type=Path, default=PROJECT_ROOT / "data/yolo/rdd2022_czech_v2")
    parser.add_argument("--czech-manifest", type=Path, default=PROJECT_ROOT / "data/processed/rdd2022_czech_v2/split_manifest.csv")
    parser.add_argument("--visual-manifest", type=Path,
                        default=PROJECT_ROOT / "data/processed/rdd2022_japan_india_visual_review/visual_review_manifest.csv")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cv2.setNumThreads(1)
    try:
        summary = prepare_pilot(args.japan_zip, args.czech_dir, args.czech_manifest, args.visual_manifest, args.data_dir)
    except (OSError, ValueError, RuntimeError, BadZipFile, cv2.error) as error:
        parser.exit(1, f"[{type(error).__name__}] {error}\n")
    print(f"검사 보고서 {Path(summary['paths']['manifests']) / 'inspection_summary.json'}")
    for name in (PILOT, HOLDOUT):
        print(f"YOLO 설정 {summary['paths'][name]}")


if __name__ == "__main__":
    main()
