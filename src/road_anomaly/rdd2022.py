import csv
import json
import ntpath
import random
from collections import Counter, defaultdict
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, replace
from hashlib import sha256
from io import StringIO
from itertools import combinations
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile
from zlib import error as DecompressionError

import cv2
import numpy as np


CLASSES = ("D00", "D10", "D20", "D40")
SPLITS = ("train", "val", "test")
SEED = 42
D_HASH_DISTANCE = 8
TRAIN_IMAGES = "Czech/train/images"
TRAIN_XMLS = "Czech/train/annotations/xmls"
TEST_IMAGES = "Czech/test/images"
EXPECTED_COUNTS = {TRAIN_IMAGES: 2829, TRAIN_XMLS: 2829, TEST_IMAGES: 709}
EXPECTED_OBJECTS = dict(zip(CLASSES, (988, 399, 161, 197), strict=True))
JPEG_SUFFIXES = {".jpg", ".jpeg"}
READ_ERRORS = (OSError, ValueError, RuntimeError, BadZipFile, DecompressionError)
ReadMember = Callable[[str], bytes]


@dataclass(frozen=True)
class Box:
    category: str
    xyxy: tuple[float, float, float, float]


@dataclass(frozen=True)
class Image:
    member: str
    width: int
    height: int
    digest: str
    dhash: int
    annotation: str | None = None
    boxes: tuple[Box, ...] = ()


def _decode_jpeg(data: bytes) -> np.ndarray:
    if not data.startswith(b"\xff\xd8\xff") or not data.endswith(b"\xff\xd9"):
        raise ValueError("JPEG 시작 또는 종료 마커가 없습니다.")
    frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or min(frame.shape[:2]) < 10:
        raise ValueError("JPEG를 디코딩할 수 없거나 이미지 한 변이 10px 미만입니다.")
    return frame


def _difference_hash(frame: np.ndarray) -> int:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    thumbnail = cv2.resize(gray, (9, 9), interpolation=cv2.INTER_AREA)
    horizontal = thumbnail[:8, 1:] > thumbnail[:8, :-1]
    vertical = thumbnail[1:, :8] > thumbnail[:-1, :8]
    bits = np.concatenate((horizontal.ravel(), vertical.ravel()))
    return int.from_bytes(np.packbits(bits).tobytes(), "big")


def _inspect(members: list[str], read: ReadMember) -> tuple[list[Image], dict]:
    errors = []

    def issue(member: str, kind: str, reason: str) -> None:
        errors.append({"file": member, "type": kind, "reason": reason})

    counts = dict.fromkeys(EXPECTED_COUNTS, 0)
    indexes = {folder: {} for folder in counts}
    unused_members = []
    for member in sorted(members):
        folder, _, filename = member.rpartition("/")
        suffix = PurePosixPath(filename).suffix.lower()
        allowed = {".xml"} if folder == TRAIN_XMLS else JPEG_SUFFIXES
        if folder not in indexes or suffix not in allowed:
            if member.startswith("Czech/test/") and suffix == ".xml":
                issue(member, "unexpected_test_xml", "공식 test 경로에 XML이 있습니다.")
            elif member.startswith("Czech/") and suffix in JPEG_SUFFIXES | {".xml"}:
                issue(member, "unexpected_layout", "JPG 또는 XML이 예상 폴더에 있지 않습니다.")
            else:
                unused_members.append(member)
            continue
        counts[folder] += 1
        # ZIP 멤버의 경로를 출력 파일명으로 사용하기 전에 Windows 경로 문자도 확인한다.
        if ntpath.isreserved(filename):
            issue(member, "invalid_filename", "Windows에서 사용할 수 없는 파일명입니다.")
            continue
        stem = PurePosixPath(filename).stem.casefold()
        if stem in indexes[folder]:
            issue(member, "duplicate_filename", f"같은 이름의 파일이 있습니다. {indexes[folder][stem]}")
            continue
        indexes[folder][stem] = member

    for folder, count in counts.items():
        if not count:
            issue(folder, "missing_files", "필수 경로에 대상 파일이 없습니다.")
    train_paths, xml_paths, test_paths = (indexes[path] for path in EXPECTED_COUNTS)
    for stem in sorted(train_paths.keys() - xml_paths.keys()):
        issue(train_paths[stem], "missing_xml", "같은 이름의 Train XML이 없습니다.")
    for stem in sorted(xml_paths.keys() - train_paths.keys()):
        issue(xml_paths[stem], "missing_jpg", "같은 이름의 Train JPG가 없습니다.")

    decoded = {}
    for member in (*train_paths.values(), *test_paths.values()):
        try:
            data = read(member)
            frame = _decode_jpeg(data)
            height, width = frame.shape[:2]
            decoded[member] = Image(member, width, height, sha256(data).hexdigest(), _difference_hash(frame))
        except (*READ_ERRORS, cv2.error) as error:
            issue(member, "unreadable_jpg", str(error))

    parsed_xmls = 0
    labelled = []
    for stem, member in xml_paths.items():
        try:
            root = ET.fromstring(read(member))
        except (ET.ParseError, LookupError) as error:
            issue(member, "invalid_xml", str(error))
            continue
        except READ_ERRORS as error:
            issue(member, "unreadable_xml", str(error))
            continue
        parsed_xmls += 1
        if root.tag != "annotation":
            issue(member, "invalid_xml", f"루트 요소가 annotation이어야 합니다. {root.tag}")
            continue

        start = len(errors)
        jpg = train_paths.get(stem)
        image = decoded.get(jpg)
        filename = (root.findtext("filename") or "").strip()
        if not filename or (jpg and filename != PurePosixPath(jpg).name):
            issue(member, "filename_mismatch", f"XML filename {filename!r}, JPG {jpg}")
        try:
            width = int(root.findtext("size/width", ""))
            height = int(root.findtext("size/height", ""))
            if min(width, height) <= 0:
                raise ValueError("너비와 높이는 양의 정수여야 합니다.")
        except ValueError as error:
            issue(member, "invalid_xml_size", str(error))
            continue
        if image and (width, height) != (image.width, image.height):
            issue(member, "size_mismatch", f"XML {width}x{height}, JPG {image.width}x{image.height}")
        if image:
            width, height = image.width, image.height

        boxes = []
        for index, obj in enumerate(root.findall("object"), 1):
            category = (obj.findtext("name") or "").strip()
            if category not in CLASSES:
                issue(member, "invalid_class", f"object {index}: {category!r}")
            try:
                x0, y0, x1, y1 = (int(obj.findtext(f"bndbox/{key}", "")) for key in (
                    "xmin", "ymin", "xmax", "ymax",
                ))
            except ValueError as error:
                issue(member, "invalid_bbox", f"object {index}: {error}")
                continue
            # RDD2022에는 0과 이미지 너비에 닿는 박스가 있어 XML의 픽셀 경계를 그대로 사용한다.
            if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
                issue(member, "invalid_bbox", f"object {index}: {(x0, y0, x1, y1)} / {width}x{height}")
            boxes.append(Box(category, (x0, y0, x1, y1)))
        if image and len(errors) == start:
            labelled.append(replace(image, annotation=member, boxes=tuple(boxes)))

    stats = _distribution(labelled)
    sizes = Counter(f"{image.width}x{image.height}" for image in decoded.values())
    comparisons = [
        ("files", EXPECTED_COUNTS, counts),
        ("objects", EXPECTED_OBJECTS, stats["objects"]),
        ("background", {"images": 1757}, {"images": stats["background_images"]}),
        ("resolution", {"600x600": 2829 + 709}, sizes),
    ]
    differences = [
        {"metric": metric, "key": key, "expected": expected.get(key, 0), "observed": observed.get(key, 0)}
        for metric, expected, observed in comparisons
        for key in sorted(expected.keys() | observed.keys())
        if expected.get(key, 0) != observed.get(key, 0)
    ]
    images = labelled + [decoded[path] for path in test_paths.values() if path in decoded]
    return images, {
        "file_counts": counts,
        "unused_members": unused_members,
        "matched_train_pairs": len(train_paths.keys() & xml_paths.keys()),
        "parsed_train_xmls": parsed_xmls,
        "decoded_jpgs": len(decoded),
        "decoded_resolutions": dict(sizes),
        "valid_train": stats,
        "reference_differences": differences,
        "errors": errors,
    }


def _distribution(images: list[Image]) -> dict:
    objects = Counter(box.category for image in images for box in image.boxes)
    positives = Counter(category for image in images for category in {box.category for box in image.boxes})
    return {
        "images": len(images),
        "background_images": sum(not image.boxes for image in images),
        "positive_images": {category: positives[category] for category in CLASSES},
        "objects": {category: objects[category] for category in CLASSES},
    }


def _group_images(images: list[Image]) -> tuple[dict[str, str], list[dict]]:
    pairs = []
    # 모든 쌍을 작은 정수의 해밍 거리로 비교한다.
    for a, b in combinations(images, 2):
        identical = a.digest == b.digest
        distance = (a.dhash ^ b.dhash).bit_count()
        if identical or distance <= D_HASH_DISTANCE:
            pairs.append({"a": a.member, "b": b.member, "identical": identical, "distance": distance})
    return _connected_groups(images, pairs), pairs


def _connected_groups(images: list[Image], pairs: list[dict]) -> dict[str, str]:
    parents = {image.member: image.member for image in images}

    def root(member: str) -> str:
        while member != parents[member]:
            parents[member] = parents[parents[member]]
            member = parents[member]
        return member

    for pair in pairs:
        left, right = sorted((root(pair["a"]), root(pair["b"])))
        parents[right] = left
    return {member: root(member) for member in parents}


def _assign_splits(images: list[Image], group_ids: dict[str, str]) -> tuple[dict[str, str], dict[str, int]]:
    groups = defaultdict(list)
    for image in images:
        groups[group_ids[image.member]].append(image)
    if len(groups) < len(SPLITS):
        raise ValueError("Train/Val/Test에 배정할 독립 이미지 그룹이 3개 미만입니다.")

    holdout = max(1, (len(images) + 5) // 10)
    targets = dict(zip(SPLITS, (len(images) - 2 * holdout, holdout, holdout), strict=True))
    features = {}
    for group_id, members in groups.items():
        stats = _distribution(members)
        features[group_id] = np.array([
            stats["images"], stats["background_images"], *stats["positive_images"].values(), *stats["objects"].values(),
        ])
    totals = np.sum(list(features.values()), axis=0)
    scale = np.maximum(totals, 1)
    desired = {split: totals * targets[split] / len(images) for split in SPLITS}
    assigned_counts = {split: np.zeros_like(totals) for split in SPLITS}
    order = sorted(groups)
    random.Random(SEED).shuffle(order)
    order.sort(key=lambda group_id: float((features[group_id] / scale).sum()), reverse=True)

    assignments = {}
    for index, group_id in enumerate(order):
        feature = features[group_id]
        empty = [split for split in SPLITS if not assigned_counts[split][0]]
        choices = empty if len(order) - index == len(empty) else SPLITS

        def cost(split: str) -> tuple[int, float]:
            current = assigned_counts[split]
            overflow = max(0, int(current[0] + feature[0]) - targets[split])
            # 작은 분할에도 객체가 많은 이미지가 배정되도록 오차 증가량을 분할 크기로 보정한다.
            change = (feature / scale) * ((2 * (current - desired[split]) + feature) / scale)
            return overflow, float(change.sum()) / targets[split]

        split = min(choices, key=cost)
        assigned_counts[split] += feature
        assignments.update((image.member, split) for image in groups[group_id])
    return assignments, targets


def _yolo_label(image: Image) -> str:
    lines = []
    for box in image.boxes:
        x0, y0, x1, y1 = box.xyxy
        cx, cy = (x0 + x1) / (2 * image.width), (y0 + y1) / (2 * image.height)
        width, height = (x1 - x0) / image.width, (y1 - y0) / image.height
        lines.append(f"{CLASSES.index(box.category)} {cx:.10f} {cy:.10f} {width:.10f} {height:.10f}\n")
    return "".join(lines)


def _verify_label(path: Path, image: Image) -> tuple[list[Box], float]:
    rows = path.read_text(encoding="utf-8").splitlines()
    if len(rows) != len(image.boxes):
        raise ValueError(f"YOLO 행 수와 XML 객체 수가 다릅니다. {path}")
    decoded_boxes = []
    max_error = 0.0
    for row, original in zip(rows, image.boxes, strict=True):
        label, cx, cy, width, height = row.split()
        cx, cy, width, height = map(float, (cx, cy, width, height))
        if label != str(CLASSES.index(original.category)) or not (
            0 <= cx <= 1 and 0 <= cy <= 1 and 0 < width <= 1 and 0 < height <= 1
        ):
            raise ValueError(f"YOLO 클래스 또는 정규화 좌표 오류. {path}: {row}")
        xyxy = (
            (cx - width / 2) * image.width, (cy - height / 2) * image.height,
            (cx + width / 2) * image.width, (cy + height / 2) * image.height,
        )
        error = max(abs(actual - expected) for actual, expected in zip(xyxy, original.xyxy, strict=True))
        if error > 0.0001:
            raise ValueError(f"YOLO 역변환이 원본 박스와 일치하지 않습니다. {path}: {row}")
        max_error = max(max_error, error)
        decoded_boxes.append(Box(CLASSES[int(label)], tuple(round(value) for value in xyxy)))
    return decoded_boxes, max_error


def _create_dir(path: Path, cleanup: ExitStack, *, parents: bool = False) -> None:
    path.mkdir(parents=parents)
    cleanup.callback(path.rmdir)


def _write_file(path: Path, data: bytes, cleanup: ExitStack) -> None:
    with path.open("xb") as handle:
        cleanup.callback(path.unlink)
        handle.write(data)


def _draw_boxes(frame: np.ndarray, boxes: tuple[Box, ...] | list[Box]) -> None:
    height, width = frame.shape[:2]
    colors = ((64, 218, 255), (37, 230, 99), (244, 155, 80), (90, 77, 255))
    for box in boxes:
        x0, y0, x1, y1 = (round(coordinate) for coordinate in box.xyxy)
        color = colors[CLASSES.index(box.category)]
        cv2.rectangle(frame, (x0, y0), (min(x1, width - 1), min(y1, height - 1)), color, 2)
        origin = (x0, max(14, y0 - 4))
        cv2.putText(frame, box.category, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.5, (15, 15, 15), 3, cv2.LINE_AA)
        cv2.putText(frame, box.category, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)


def _save_preview(data: bytes, boxes: list[Box], path: Path, cleanup: ExitStack) -> None:
    frame = _decode_jpeg(data)
    _draw_boxes(frame, boxes)
    encoded, png = cv2.imencode(".png", frame)
    if not encoded:
        raise RuntimeError(f"BBox 미리보기를 저장할 수 없습니다. {path}")
    _write_file(path, png.tobytes(), cleanup)


def _dataset_yaml(splits: tuple[str, ...]) -> bytes:
    # Ultralytics는 train 키가 필요하며, 평가 전용 데이터의 학습 경로는 null로 둔다.
    yaml = "" if "train" in splits else "train: null\n"
    # path를 생략하면 data.yaml의 부모 폴더를 데이터셋 루트로 사용한다.
    yaml += "".join(f"{split}: images/{split}\n" for split in splits)
    yaml += "names:\n" + "".join(f"  {index}: {category}\n" for index, category in enumerate(CLASSES))
    return yaml.encode("utf-8")


def _export(
    images: list[Image], assignments: dict[str, str], groups: dict[str, str],
    source_path: Path, read: ReadMember, processed_dir: Path, yolo_dir: Path, cleanup: ExitStack,
) -> dict:
    _create_dir(yolo_dir, cleanup, parents=True)
    preview_dir = processed_dir / "bbox_previews"
    _create_dir(preview_dir, cleanup)
    for folder in ("images", "labels"):
        _create_dir(yolo_dir / folder, cleanup)
        for split in SPLITS:
            _create_dir(yolo_dir / folder / split, cleanup)

    previews = {}
    for category in CLASSES:
        representative = next((
            image for image in images
            if image.member not in previews and any(box.category == category for box in image.boxes)
        ), None)
        if representative:
            previews[representative.member] = category
    background = next((image for image in images if not image.boxes), None)
    if background:
        previews[background.member] = "background"

    directory_input = source_path.is_dir()

    def origin(member: str) -> str:
        if directory_input:
            return str(source_path / member.removeprefix("Czech/"))
        return f"{source_path}!/{member}"

    manifest = StringIO(newline="")
    writer = csv.writer(manifest)
    writer.writerow(("source_image", "source_annotation", "split", "group_id", "sha256", *CLASSES))
    converted = Counter()
    max_error = 0.0
    saved_previews = []
    for image in images:
        split = assignments[image.member]
        filename = PurePosixPath(image.member).name
        data = read(image.member)
        if sha256(data).hexdigest() != image.digest:
            raise ValueError(f"검사 후 JPG 내용이 바뀌었습니다. {image.member}")
        _write_file(yolo_dir / "images" / split / filename, data, cleanup)
        label_path = yolo_dir / "labels" / split / Path(filename).with_suffix(".txt")
        _write_file(label_path, _yolo_label(image).encode("utf-8"), cleanup)
        boxes, error = _verify_label(label_path, image)
        max_error = max(max_error, error)
        counts = Counter(box.category for box in boxes)
        converted.update(counts)
        writer.writerow((
            origin(image.member), origin(image.annotation), split, groups[image.member], image.digest,
            *(counts[category] for category in CLASSES),
        ))
        if image.member in previews:
            name = f"{previews[image.member]}_{label_path.stem}.png"
            _save_preview(data, boxes, preview_dir / name, cleanup)
            saved_previews.append({"file": name, "source_image": origin(image.member), "split": split})

    after = {category: converted[category] for category in CLASSES}
    if after != _distribution(images)["objects"]:
        raise ValueError("변환 전후 클래스별 객체 수가 다릅니다.")
    _write_file(processed_dir / "split_manifest.csv", manifest.getvalue().encode("utf-8-sig"), cleanup)
    _write_file(yolo_dir / "data.yaml", _dataset_yaml(SPLITS), cleanup)
    return {"objects": after, "max_bbox_roundtrip_error_px": max_error, "previews": saved_previews}


def prepare_czech(source_path: Path, processed_dir: Path, yolo_dir: Path) -> dict:
    """Czech ZIP 또는 기존 Czech 폴더에서 검증 보고서와 YOLO 데이터셋을 생성한다."""
    for path in (processed_dir, yolo_dir):
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"출력 경로가 이미 있습니다. {path}")
    source_path = source_path.resolve(strict=True)
    processed_dir, yolo_dir = processed_dir.resolve(), yolo_dir.resolve()
    directory_input = source_path.is_dir()
    if processed_dir.is_relative_to(yolo_dir) or yolo_dir.is_relative_to(processed_dir):
        raise ValueError("두 출력 경로는 서로 독립된 폴더여야 합니다.")
    if directory_input and any(path.is_relative_to(source_path) for path in (processed_dir, yolo_dir)):
        raise ValueError("출력 폴더는 원본 Czech 폴더 밖에 지정해야 합니다.")

    with ExitStack() as source, ExitStack() as cleanup:
        if directory_input:
            members = [
                f"Czech/{path.relative_to(source_path).as_posix()}"
                for path in source_path.rglob("*") if path.is_file()
            ]

            def read(member: str) -> bytes:
                return (source_path / member.removeprefix("Czech/")).read_bytes()

        else:
            archive = source.enter_context(ZipFile(source_path, "r"))
            members = [entry.filename for entry in archive.infolist() if not entry.is_dir()]
            read = archive.read
        images, summary = _inspect(members, read)
        summary["source"] = {"path": str(source_path), "type": "directory" if directory_input else "zip"}
        if not directory_input:
            summary["source"]["zip_size_bytes"] = source_path.stat().st_size

        _create_dir(processed_dir, cleanup, parents=True)
        if not summary["errors"]:
            labelled = [image for image in images if image.annotation is not None]
            groups, pairs = _group_images(images)
            try:
                assignments, targets = _assign_splits(labelled, groups)
            except ValueError as error:
                summary["errors"].append({"file": str(source_path), "type": "split_impossible", "reason": str(error)})
            else:
                cross_split = Counter()
                pair_counts = {kind: dict.fromkeys(("labelled", "mixed", "official_test"), 0)
                               for kind in ("identical", "similar")}
                for pair in pairs:
                    a, b = assignments.get(pair["a"]), assignments.get(pair["b"])
                    pair.update(split_a=a or "official_test", split_b=b or "official_test")
                    kind = "identical" if pair["identical"] else "similar"
                    scope = "labelled" if a and b else "mixed" if a or b else "official_test"
                    pair_counts[kind][scope] += 1
                    if a and b and a != b:
                        cross_split[kind] += 1
                if cross_split:
                    raise RuntimeError("동일 또는 유사 이미지 후보가 여러 분할에 배정되었습니다.")
                summary["similarity"] = {
                    "exact_method": "SHA-256 of JPEG bytes",
                    "similarity_method": "128-bit horizontal/vertical dHash",
                    "max_hamming_distance": D_HASH_DISTANCE,
                    "scanned_images": len(images),
                    "pair_counts": pair_counts,
                    "candidate_pairs": pairs,
                    "cross_split_pairs": {kind: cross_split[kind] for kind in ("identical", "similar")},
                    "limitation": "주행 구간·영상 ID를 사용하지 않았으며 dHash가 놓친 유사 장면으로 데이터 누수 가능성이 남아 있습니다.",
                }
                summary["splits"] = {
                    "seed": SEED,
                    "target_ratios": dict(zip(SPLITS, (0.8, 0.1, 0.1), strict=True)),
                    "target_images": targets,
                    "labelled_groups": len({groups[image.member] for image in labelled}),
                    "actual": {
                        split: _distribution([image for image in labelled if assignments[image.member] == split])
                        for split in SPLITS
                    },
                }
                summary["conversion"] = _export(
                    labelled, assignments, groups, source_path, read, processed_dir, yolo_dir, cleanup,
                )
        _write_file(
            processed_dir / "inspection_summary.json",
            (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            cleanup,
        )
        cleanup.pop_all()
    return summary
