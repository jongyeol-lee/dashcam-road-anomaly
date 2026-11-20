from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median

from .rdd2022 import CLASSES
from .yolo_evaluation import Case, Detection, MATCH_IOU, VAL_OPTIONS, _read_truth, _render, box_iou, match_boxes


THRESHOLDS = (0.05, 0.10, 0.25)
LOCALIZATION_MIN_IOU = 0.10
SMALL_AREA_FRACTION = 0.01
SHORT_SIDE_PX = 32
INFERENCE_OPTIONS = {key: VAL_OPTIONS[key] for key in ("imgsz", "batch", "device", "conf", "iou", "rect", "max_det", "quantize")}


@dataclass(frozen=True)
class Frame:
    image: Path
    truth: list[Detection]
    predictions: list[Detection]
    width: int
    height: int


def collect_frames(checkpoint: Path, pairs: list[tuple[Path, Path]]) -> list[Frame]:
    """같은 NMS로 Validation을 한 번 추론하고 score를 보존한다."""
    from ultralytics import YOLO

    if not checkpoint.is_file():
        raise FileNotFoundError(checkpoint)
    if not pairs or any(image.parent != pairs[0][0].parent for image, _ in pairs):
        raise ValueError("Validation 이미지 경로를 한 폴더에서 지정해야 합니다.")
    model = YOLO(str(checkpoint), task="detect")
    if model.names != dict(enumerate(CLASSES)):
        raise ValueError(f"탐지 클래스가 Czech v2 매핑과 다릅니다. {checkpoint}")
    remaining = {str(image): (image, label) for image, label in pairs}
    frames = []
    for result in model.predict(str(pairs[0][0].parent), stream=True, save=False, verbose=False, **INFERENCE_OPTIONS):
        pair = remaining.pop(str(Path(result.path).resolve()), None)
        if pair is None:
            raise ValueError(f"Validation 매니페스트 밖의 이미지 또는 중복 추론입니다. {result.path}")
        image, label = pair
        height, width = result.orig_shape
        truth = _read_truth(label, width, height)
        predictions = [Detection(int(cls), tuple(box), score) for box, cls, score in zip(
            result.boxes.xyxy.tolist(), result.boxes.cls.tolist(), result.boxes.conf.tolist(), strict=True,
        )]
        frames.append(Frame(image, truth, predictions, width, height))
    if remaining:
        raise RuntimeError(f"Validation 이미지 {len(remaining)}장의 추론 결과가 누락됐습니다.")
    return sorted(frames, key=lambda frame: frame.image.name)


def classify_errors(frame: Frame, confidence: float) -> list[Case]:
    """정탐과 혼동을 먼저 연결하고 남은 같은 클래스의 부분 겹침을 위치 오류로 기록한다."""
    if not 0 <= confidence <= 1:
        raise ValueError("confidence는 0~1이어야 합니다.")
    preds = [box for box in frame.predictions if box.confidence >= confidence]
    truth = frame.truth
    cases = []
    base = (frame.image, frame.truth, preds)
    matches, misses, extras = match_boxes(truth, preds)
    for i, j, iou, confusion in matches:
        kind = "class_confusion" if confusion else "true_positive"
        cases.append(Case(*base, kind, truth[i], preds[j], iou))

    # 위치 오류도 TP로 집계하지 않는다. 두 박스를 하나의 오류 사례로만 연결한다.
    overlaps = sorted((-box_iou(truth[i], preds[j]), i, j) for i in misses for j in extras
                      if truth[i].class_id == preds[j].class_id)
    pending_truth, pending_predictions = set(misses), set(extras)
    for neg_iou, i, j in overlaps:
        if -neg_iou < LOCALIZATION_MIN_IOU:
            break
        if i in pending_truth and j in pending_predictions:
            cases.append(Case(*base, "localization", truth[i], preds[j], -neg_iou))
            pending_truth.remove(i)
            pending_predictions.remove(j)
    cases.extend(Case(*base, "false_negative", gt=truth[i]) for i in sorted(pending_truth))
    for j in sorted(pending_predictions):
        pred = preds[j]
        duplicate = any(gt.class_id == pred.class_id and box_iou(gt, pred) >= MATCH_IOU for gt in truth)
        kind = "duplicate" if duplicate else "false_positive" if truth else "background_false_positive"
        cases.append(Case(*base, kind, pred=pred))
    return cases


def _ratio(a: int, b: int) -> float | None:
    return a / b if b else None


def _geometry(box: Detection, frame: Frame) -> tuple[float, int]:
    # Czech VOC의 픽셀 경계는 정수다. 정규화 역변환의 반올림 오차는 크기 분류에서 제거한다.
    x0, y0, x1, y1 = map(round, box.xyxy)
    width, height = x1 - x0, y1 - y0
    return width * height / (frame.width * frame.height), min(width, height)


def summarize_thresholds(frames: list[Frame]) -> tuple[dict, dict[float, list[Case]]]:
    if not frames:
        raise ValueError("분석할 Validation 이미지가 없습니다.")
    stats = {index: {"area": [], "short_side": []} for index in range(len(CLASSES))}
    results, candidates = {}, {}
    for frame in frames:
        for gt in frame.truth:
            area, short_side = _geometry(gt, frame)
            stats[gt.class_id]["area"].append(area)
            stats[gt.class_id]["short_side"].append(short_side)

    for threshold in THRESHOLDS:
        counts = [Counter() for _ in CLASSES]
        confusions = Counter()
        errors = Counter()
        candidates[threshold] = []
        for frame in frames:
            cases = classify_errors(frame, threshold)
            candidates[threshold].extend(cases)
            for case in cases:
                errors[case.kind] += 1
                gt, pred = case.gt, case.pred
                if gt is not None:
                    count = counts[gt.class_id]
                    count["ground_truth"] += 1
                    area, short_side = _geometry(gt, frame)
                    size = "small" if area < SMALL_AREA_FRACTION else "other"
                    thin = short_side < SHORT_SIDE_PX
                    count[f"gt_{size}"] += 1
                    count["gt_short_side"] += thin
                    if case.kind == "true_positive":
                        count["tp"] += 1
                        count[f"tp_{size}"] += 1
                        count["tp_short_side"] += thin
                    else:
                        count["fn"] += 1
                        count[f"gt_{case.kind}"] += 1
                if pred is not None and case.kind != "true_positive":
                    counts[pred.class_id]["fp"] += 1
                    counts[pred.class_id][f"pred_{case.kind}"] += 1
                if case.kind == "class_confusion":
                    confusions[(CLASSES[gt.class_id], CLASSES[pred.class_id])] += 1

        def rates(count: Counter) -> dict:
            tp, fp, fn = (count[key] for key in ("tp", "fp", "fn"))
            return {**count, "tp": tp, "fp": fp, "fn": fn,
                    "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn)}

        results[f"{threshold:.2f}"] = {
            "overall": rates(sum(counts, Counter())),
            "classes": {name: rates(count) for name, count in zip(CLASSES, counts, strict=True)},
            "errors": dict(errors),
            "confusions": [{"gt": gt, "pred": pred, "count": n} for (gt, pred), n in sorted(confusions.items())],
        }
    return {
        "images": len(frames), "background_images": sum(not frame.truth for frame in frames),
        "inference": INFERENCE_OPTIONS, "matching_iou": MATCH_IOU, "localization_min_iou": LOCALIZATION_MIN_IOU,
        "small_area_fraction": SMALL_AREA_FRACTION, "short_side_px": SHORT_SIDE_PX,
        "geometry": {CLASSES[index]: {f"median_{measure}": median(values) if values else None
                                    for measure, values in items.items()} for index, items in stats.items()},
        "thresholds": results,
    }, candidates


def save_cases(frames: list[Frame], candidates: dict[float, list[Case]], output: Path) -> list[dict]:
    """클래스와 오류 유형이 겹치지 않도록 대표 사례를 선택한다."""
    by_image = {frame.image: frame for frame in frames}
    pool = defaultdict(list)
    for threshold in reversed(THRESHOLDS):
        for case in candidates[threshold]:
            category = (case.gt or case.pred).class_id
            item = (threshold, case)
            pool[case.kind, category].append(item)
            frame = by_image[case.image]
            if case.kind == "false_negative" and _geometry(case.gt, frame)[0] < SMALL_AREA_FRACTION:
                pool["small_miss", category].append(item)

    plan = [("class_confusion", k) for k in (1, 3, 2)]
    plan += [("true_positive", k) for k in (1, 3, 2, 0)]
    plan += [("small_miss", 1), ("small_miss", 3), ("false_negative", 1), ("false_negative", 3)]
    plan += [("localization", k) for k in (1, 3, 0, 2)]
    plan += [("background_false_positive", k) for k in (2, 0, 3)]
    plan += [("false_positive", 2), ("duplicate", 0)]

    def interest(item: tuple[float, Case]) -> tuple[float, float, float, str]:
        threshold, case = item
        return (-threshold, -(case.pred.confidence if case.pred else 0), -(case.iou or 0), case.image.name)

    saved, used = [], set()
    gallery = output / "cases"
    gallery.mkdir()
    for kind, category in plan:
        ranked = sorted(pool[kind, category], key=interest)
        picked = next(((level, case) for level, case in ranked if case.image not in used), None)
        if picked is None:
            continue
        level, case = picked
        used.add(case.image)
        filename = f"{kind}_{CLASSES[category]}_{case.image.stem}_conf{level:.2f}.png"
        _render(case, gallery / filename, confidence_digits=4)
        saved.append({"file": f"cases/{filename}", "image": case.image.name, "kind": kind,
                      "class": CLASSES[category], "threshold": level, "iou": case.iou,
                      "gt": asdict(case.gt) if case.gt else None, "prediction": asdict(case.pred) if case.pred else None})
    return saved
