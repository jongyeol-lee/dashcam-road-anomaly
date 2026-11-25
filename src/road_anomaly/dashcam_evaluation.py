"""발행 GT v1을 사용하는 블랙박스 프레임 단위 진단."""

import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from time import perf_counter_ns

from .rdd2022 import CLASSES
from .roi import BoxPosition, NormalizedRoi
from .yolo_evaluation import MATCH_IOU, Detection, box_iou


CONFIDENCES = (0.05, 0.25)
UNCERTAIN_COVERAGE = 0.5
SIZE = (1920, 1080)
RELEASE_NAME = "part532_evaluation_gt_v1"
RELEASE_HASHES = {
    "release_manifest.json": "2b9ac000c986d1c93aa5d2267e757fdf1264b32b4f4ae1dab23dbf56d849f789",
    "uncertain_regions.json": "5767e737f881b039ee1eadd632f37296f0c9b1bd12aa7bc6b7cd14cdf9b7b78b",
}
EXPECTED_D20 = {
    "rear_000525": (455, 565, 1032, 760),
    "rear_000540": (556, 520, 959, 788),
    "rear_000555": (386, 602, 1131, 786),
    "front_000510": (788, 700, 1505, 882),
    "rear_000120": (264, 552, 430, 705),
}
EXPECTED_SCOPES = {
    "positive": set(EXPECTED_D20),
    "normal_background": {"front_000210", "front_000690", "rear_000690"},
    "uncertain_regions_only": {"front_000345", "rear_000030", "rear_000405"},
    "excluded": {"rear_000135", "front_000075", "rear_000255"},
}
DISPOSITIONS = ("tp", "background_fp", "uncertain", "review")
Box = tuple[float, float, float, float]


@dataclass(frozen=True, kw_only=True)
class IdentifiedDetection(Detection):
    box_id: str


@dataclass(frozen=True)
class UncertainRegion:
    box_id: str
    xyxy: Box
    stored_class: str


@dataclass(frozen=True)
class EvaluationImage:
    image_id: str
    revision: int
    scope: str
    source_video: str
    frame_index: int
    estimated_time_sec: float
    image_path: str | None
    image_sha256: str
    truth: tuple[IdentifiedDetection, ...]
    uncertain_regions: tuple[UncertainRegion, ...]


def checked_bytes(path: Path, expected_sha256: str) -> bytes:
    data = path.read_bytes()
    actual = sha256(data).hexdigest()
    if actual != expected_sha256:
        raise ValueError(f"SHA-256 불일치: {path} (예상 {expected_sha256}, 실제 {actual})")
    return data


def validate_xyxy(values: list | tuple, *, integer: bool = False) -> Box:
    allowed_types = (int,) if integer else (int, float)
    if (not isinstance(values, (list, tuple)) or len(values) != 4
            or any(type(value) not in allowed_types for value in values)):
        raise ValueError(f"올바른 xyxy 좌표 네 개가 필요합니다. {values}")
    x1, y1, x2, y2 = values
    if not (0 <= x1 < x2 <= SIZE[0] and 0 <= y1 < y2 <= SIZE[1]):
        raise ValueError(f"xyxy 좌표가 {SIZE} 범위를 벗어나거나 면적이 0입니다. {values}")
    return x1, y1, x2, y2


def parse_release(rows: list[dict], regions: list[dict]) -> tuple[EvaluationImage, ...]:
    """승인 범위와 버전을 검증하여 같은 이미지·revision의 보류 영역을 연결한다."""
    images = {row["image_id"]: row for row in rows}
    if len(images) != len(rows):
        raise ValueError("발행 이미지 ID가 중복됩니다.")
    regions_by_image = defaultdict(list)
    for region in regions:
        row = images.get(region["image_id"])
        if row is None or type(region["revision"]) is not int or region["revision"] != row["revision"]:
            raise ValueError(f"보류 영역의 이미지 ID 또는 revision이 다릅니다. {region['image_id']}")
        regions_by_image[row["image_id"]].append(region)

    frames = []
    for image_id, row in images.items():
        revision, scope = row["revision"], row["scope"]
        if type(revision) is not int or revision < 1:
            raise ValueError(f"발행 revision이 잘못됐습니다. {image_id}")
        if scope not in EXPECTED_SCOPES or (row["width"], row["height"]) != SIZE:
            raise ValueError(f"발행 범위 또는 원본 해상도가 다릅니다. {image_id}")
        path = row["image_path"]
        expected_path = None if scope == "excluded" else f"images/{scope}/{image_id}.png"
        if path != expected_path:
            raise ValueError(f"발행 이미지 경로가 범위 또는 ID와 일치하지 않습니다. {image_id}")
        truth_rows, region_rows = row["ground_truth"], regions_by_image[image_id]
        if (bool(truth_rows) != (scope == "positive")
                or (scope == "uncertain_regions_only" and not region_rows)
                or (scope in ("normal_background", "excluded") and region_rows)):
            raise ValueError(f"GT·보류 영역이 승인 범위와 일치하지 않습니다. {image_id}")
        numbers = [box["box_id"] for box in (*truth_rows, *region_rows)]
        if any(type(number) is not int or number < 1 for number in numbers) or len(set(numbers)) != len(numbers):
            raise ValueError(f"발행 박스 번호가 잘못됐거나 중복됩니다. {image_id}")

        prefix = f"{image_id}:v{revision:04d}"
        truth = []
        for box in truth_rows:
            if box["class"] != "D20":
                raise ValueError(f"확정 GT 클래스는 D20이어야 합니다. {image_id}")
            truth.append(IdentifiedDetection(CLASSES.index(box["class"]), validate_xyxy(box["xyxy"], integer=True),
                                             box_id=f"{prefix}:gt{box['box_id']:03d}"))
        uncertain = tuple(UncertainRegion(f"{prefix}:hold{box['box_id']:03d}",
                                          validate_xyxy(box["xyxy"], integer=True), box["stored_class"])
                          for box in region_rows)
        frames.append(EvaluationImage(image_id, revision, scope, row["source_video"], row["frame_index"],
                                      row["estimated_time_sec"], path, row["image_sha256"], tuple(truth), uncertain))
    return tuple(frames)


def read_release(directory: Path) -> tuple[EvaluationImage, ...]:
    documents = {name: json.loads(checked_bytes(directory / name, digest)) for name, digest in RELEASE_HASHES.items()}
    manifest = documents["release_manifest.json"]
    frames = parse_release(manifest["images"], documents["uncertain_regions.json"])
    scopes = {scope: {image.image_id for image in frames if image.scope == scope} for scope in EXPECTED_SCOPES}
    truth = {image.image_id: tuple(box.xyxy for box in image.truth) for image in frames if image.truth}
    if (manifest["release"] != RELEASE_NAME or manifest["approval_status"] != "approved"
            or manifest["training_allowed"] is not False or scopes != EXPECTED_SCOPES
            or truth != {image_id: (box,) for image_id, box in EXPECTED_D20.items()}
            or sum(len(image.uncertain_regions) for image in frames) != 8):
        raise ValueError("발행 GT v1의 승인 범위 또는 박스가 실험 기준과 일치하지 않습니다.")
    return frames


def identify_prediction(model: str, image_id: str, number: int, class_value: float,
                        xyxy: list | tuple, confidence: float) -> IdentifiedDetection:
    if (type(class_value) not in (int, float) or class_value not in range(len(CLASSES))
            or not math.isfinite(confidence) or not CONFIDENCES[0] <= confidence <= 1):
        raise ValueError(f"예측 클래스 또는 confidence가 잘못됐습니다. {model} {image_id} #{number}")
    return IdentifiedDetection(int(class_value), validate_xyxy(xyxy), confidence,
                               box_id=f"{model}:{image_id}:p{number:03d}")


def uncertain_fraction(prediction: Detection, regions: tuple[UncertainRegion, ...]) -> float:
    """예측 안으로 잘라낸 보류 사각형들의 합집합 면적을 예측 면적으로 나눈다."""
    px1, py1, px2, py2 = prediction.xyxy
    clips = []
    for region in regions:
        x1, y1, x2, y2 = region.xyxy
        left, top, right, bottom = max(px1, x1), max(py1, y1), min(px2, x2), min(py2, y2)
        if left < right and top < bottom:
            clips.append((left, top, right, bottom))
    # x 경계 사이에서는 활성 사각형이 같으므로 겹치는 y 구간을 한 번만 센다.
    area = 0.0
    for left, right in pairwise(sorted({x for x1, _, x2, _ in clips for x in (x1, x2)})):
        end = py1
        for top, bottom in sorted((y1, y2) for x1, y1, x2, y2 in clips if x1 < right and x2 > left):
            area += (right - left) * max(0.0, bottom - max(top, end))
            end = max(end, bottom)
    return area / prediction.area


def detection_record(box: IdentifiedDetection) -> dict:
    return {**asdict(box), "class": CLASSES[box.class_id]}


def evaluate_image(image: EvaluationImage, predictions: tuple[IdentifiedDetection, ...],
                   positions: dict[str, BoxPosition]) -> dict:
    """동일 클래스 정탐을 먼저 정한 뒤 남은 박스에 승인 범위별 판정을 기록한다."""
    if image.scope == "excluded":
        raise ValueError(f"전체 제외 이미지는 평가할 수 없습니다. {image.image_id}")
    candidates, confusions = [], defaultdict(list)
    by_id = {pred.box_id: pred for pred in predictions}
    for gt in image.truth:
        for pred in predictions:
            iou = box_iou(gt, pred)
            if gt.class_id == pred.class_id:
                candidates.append((-iou, -pred.confidence, gt.box_id, pred.box_id))
            elif iou >= MATCH_IOU:
                confusions[pred.box_id].append({"gt_id": gt.box_id, "gt_class": CLASSES[gt.class_id], "iou": iou})

    matches, reverse_matches, best = {}, {}, {}
    for neg_iou, _, gt_id, pred_id in sorted(candidates):
        iou = -neg_iou
        best.setdefault(gt_id, (pred_id, iou))
        if iou >= MATCH_IOU and gt_id not in matches and pred_id not in reverse_matches:
            matches[gt_id] = (pred_id, iou)
            reverse_matches[pred_id] = gt_id

    gt_rows = []
    for gt in image.truth:
        pred_id, iou = matches.get(gt.box_id, (None, None))
        closest_id, closest_iou = best.get(gt.box_id, (None, None))
        gt_rows.append({
            **detection_record(gt), "status": "tp" if pred_id else "fn", "prediction_id": pred_id, "iou": iou,
            "confidence": by_id[pred_id].confidence if pred_id else None,
            "best_same_class": ({"prediction_id": closest_id, "iou": closest_iou,
                                 "confidence": by_id[closest_id].confidence} if closest_id else None),
        })

    pred_rows = []
    for pred in predictions:
        gt_id = reverse_matches.get(pred.box_id)
        coverage = None
        if gt_id:
            disposition = "tp"
        else:
            coverage = uncertain_fraction(pred, image.uncertain_regions)
            if coverage >= UNCERTAIN_COVERAGE:
                disposition = "uncertain"
            elif image.scope == "normal_background":
                disposition = "background_fp"
            else:
                disposition = "review"
        pred_rows.append({
            **detection_record(pred), "disposition": disposition, "matched_gt_id": gt_id,
            "matched_iou": matches[gt_id][1] if gt_id else None, "uncertain_fraction": coverage,
            "class_confusions": confusions[pred.box_id], "roi_b": asdict(positions[pred.box_id]),
        })
    return {"image_id": image.image_id, "revision": image.revision, "source_video": image.source_video,
            "scope": image.scope, "ground_truth": gt_rows, "predictions": pred_rows}


def summarize(results: list[dict]) -> dict:
    predictions = [pred for row in results for pred in row["predictions"]]
    truth = [gt for row in results for gt in row["ground_truth"]]
    counts = Counter(pred["disposition"] for pred in predictions)
    backgrounds = [row for row in results if row["scope"] == "normal_background"]
    confusions = Counter((item["gt_class"], pred["class"]) for pred in predictions for item in pred["class_confusions"])
    classes = {}
    for name in CLASSES:
        class_gt = [gt for gt in truth if gt["class"] == name]
        tp = sum(gt["status"] == "tp" for gt in class_gt)
        classes[name] = {
            "predictions": sum(pred["class"] == name for pred in predictions), "gt": len(class_gt),
            "tp": tp, "fn": len(class_gt) - tp, "recall": tp / len(class_gt) if class_gt else None,
        }
    return {
        "image_count": len(results), "prediction_count": len(predictions), "classes": classes,
        "background_image_count": len(backgrounds),
        "background_images_with_fp": sum(any(p["disposition"] == "background_fp" for p in row["predictions"])
                                         for row in backgrounds),
        "background_fp_per_image": counts["background_fp"] / len(backgrounds) if backgrounds else None,
        "dispositions": {name: counts[name] for name in DISPOSITIONS},
        "confusion_prediction_count": sum(bool(pred["class_confusions"]) for pred in predictions),
        "class_confusions": [{"gt_class": gt, "predicted_class": pred, "count": count}
                             for (gt, pred), count in sorted(confusions.items())],
    }


def roi_effect(before: list[dict], after: list[dict], roi_filter_ms: float) -> dict:
    predictions = [pred for row in before for pred in row["predictions"]]
    removed = {name: [] for name in DISPOSITIONS}
    for pred in predictions:
        if not pred["roi_b"]["keep"]:
            removed[pred["disposition"]].append(pred["box_id"])
    old_matches = {gt["box_id"]: gt["prediction_id"] for row in before for gt in row["ground_truth"]}
    new_matches = {gt["box_id"]: gt["prediction_id"] for row in after for gt in row["ground_truth"]}
    changed = [{"gt_id": gt_id, "previous_prediction_id": old, "new_prediction_id": new_matches[gt_id]}
               for gt_id, old in old_matches.items() if old != new_matches[gt_id]]
    boundaries = [pred["box_id"] for pred in predictions if pred["roi_b"]["touches_boundary"]]
    removed_count = sum(map(len, removed.values()))
    return {
        "before_count": len(predictions), "removed_count": removed_count,
        "retained_count": len(predictions) - removed_count, "removed_prediction_ids": removed,
        "gt_lost": [row for row in changed if row["new_prediction_id"] is None],
        "gt_rematched": [row for row in changed if row["previous_prediction_id"] and row["new_prediction_id"]],
        "gt_gained": [row for row in changed if row["previous_prediction_id"] is None],
        "boundary_prediction_ids": boundaries, "roi_filter_ms": roi_filter_ms,
    }


def evaluate_pair(images: tuple[EvaluationImage, ...], by_image: dict[str, tuple[IdentifiedDetection, ...]],
                  confidence: float, roi: NormalizedRoi) -> tuple[list[dict], list[dict], dict]:
    active = tuple(image for image in images if image.scope != "excluded")
    if set(by_image) != {image.image_id for image in active}:
        raise ValueError("저장 예측 목록에 평가 이미지 누락 또는 범위 밖 이미지가 있습니다.")
    before, after, filter_ns = [], [], 0
    for image in active:
        predictions = tuple(pred for pred in by_image[image.image_id] if pred.confidence >= confidence)
        start = perf_counter_ns()
        positions = {pred.box_id: roi.classify(pred.xyxy, *SIZE) for pred in predictions}
        retained = tuple(pred for pred in predictions if positions[pred.box_id].keep)
        filter_ns += perf_counter_ns() - start
        before.append(evaluate_image(image, predictions, positions))
        after.append(evaluate_image(image, retained, positions))
    return before, after, roi_effect(before, after, filter_ns / 1_000_000)
