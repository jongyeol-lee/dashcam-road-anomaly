import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np

from .rdd2022 import CLASSES


VAL_OPTIONS = {
    "split": "val", "imgsz": 640, "batch": 4, "device": 0, "workers": 2,
    "conf": 0.001, "iou": 0.7, "rect": False, "max_det": 300, "plots": True, "cache": False, "quantize": None,
}
CASE_CONFIDENCE = 0.25
MATCH_IOU = 0.5
METRICS = ("precision", "recall", "ap50", "ap50_95")


@dataclass(frozen=True)
class Detection:
    class_id: int
    xyxy: tuple[float, float, float, float]
    confidence: float | None = None

    @property
    def area(self) -> float:
        x0, y0, x1, y1 = self.xyxy
        return (x1 - x0) * (y1 - y0)


@dataclass(frozen=True)
class Case:
    image: Path
    truth: list[Detection]
    predictions: list[Detection]
    kind: str
    gt: Detection | None = None
    pred: Detection | None = None
    iou: float | None = None


def box_iou(gt: Detection, pred: Detection) -> float:
    gx0, gy0, gx1, gy1 = gt.xyxy
    px0, py0, px1, py1 = pred.xyxy
    overlap = max(0.0, min(gx1, px1) - max(gx0, px0)) * max(0.0, min(gy1, py1) - max(gy0, py0))
    return overlap / (gt.area + pred.area - overlap) if overlap else 0.0


def match_boxes(truth: list[Detection], predictions: list[Detection]):
    """같은 클래스를 먼저 매칭하고 남은 높은 IoU 쌍을 클래스 혼동으로 분류한다."""
    candidates = []
    for i, gt in enumerate(truth):
        for j, pred in enumerate(predictions):
            iou = box_iou(gt, pred)
            if iou >= MATCH_IOU:
                candidates.append((gt.class_id != pred.class_id, -iou, i, j))
    unused_truth, unused_predictions = set(range(len(truth))), set(range(len(predictions)))
    matches = []
    for wrong_class, neg_iou, i, j in sorted(candidates):
        if i in unused_truth and j in unused_predictions:
            matches.append((i, j, -neg_iou, wrong_class))
            unused_truth.remove(i)
            unused_predictions.remove(j)
    return matches, sorted(unused_truth), sorted(unused_predictions)


def _read_truth(path: Path, width: int, height: int) -> list[Detection]:
    labels = []
    for row in path.read_text(encoding="utf-8").splitlines():
        label, cx, cy, w, h = row.split()
        cx, cy, w, h = map(float, (cx, cy, w, h))
        labels.append(Detection(int(label), (
            (cx - w / 2) * width, (cy - h / 2) * height, (cx + w / 2) * width, (cy + h / 2) * height,
        )))
    return labels


def _render(case: Case, path: Path, *, confidence_digits: int = 2) -> None:
    render_panels(case.image, (("Ground truth", case.truth), ("Prediction", case.predictions)), path, confidence_digits)


def render_panels(image: Path, groups, path: Path, confidence_digits: int = 2) -> None:
    frame = cv2.imdecode(np.frombuffer(image.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    colors = ((64, 218, 255), (37, 230, 99), (244, 155, 80), (90, 77, 255))
    panels = []
    for title, boxes in groups:
        panel = cv2.copyMakeBorder(frame, 34, 0, 0, 0, cv2.BORDER_CONSTANT, value=(22, 25, 30))
        cv2.putText(panel, f"{title} | {len(boxes)} boxes", (12, 23), cv2.FONT_HERSHEY_SIMPLEX,
                    0.62, (255, 255, 255), 1, cv2.LINE_AA)
        for box in boxes:
            x0, y0, x1, y1 = (round(value) for value in box.xyxy)
            color = colors[box.class_id]
            cv2.rectangle(panel, (x0, y0 + 34), (x1, y1 + 34), color, 2)
            text = CLASSES[box.class_id]
            if box.confidence is not None:
                text += f" {box.confidence:.{confidence_digits}f}"
            origin = (x0, max(48, y0 + 30))
            cv2.putText(panel, text, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.48, (16, 16, 16), 3, cv2.LINE_AA)
            cv2.putText(panel, text, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1, cv2.LINE_AA)
        if panels:
            panels.append(np.full((panel.shape[0], 6, 3), 30, dtype=np.uint8))
        panels.append(panel)
    encoded, data = cv2.imencode(".png", np.hstack(panels))
    if not encoded:
        raise RuntimeError(f"Validation 사례를 인코딩할 수 없습니다. {path}")
    with path.open("xb") as handle:
        handle.write(data.tobytes())


def _select_cases(candidates: dict[str, list[Case]]) -> list[Case]:
    # 작은 정탐, 혼동, 미탐, 배경 오탐을 먼저 확보하고 이미지당 사례는 하나만 저장한다.
    limits = {"small_detection": 1, "class_confusion": 2, "false_negative": 3,
              "background_false_positive": 2, "true_positive": 2, "false_positive": 1}
    ordered = {
        "small_detection": sorted(candidates["small_detection"], key=lambda case: case.gt.area),
        "class_confusion": sorted(candidates["class_confusion"], key=lambda case: -case.iou),
    }
    misses = sorted(candidates["false_negative"], key=lambda case: -case.gt.area)
    for class_id in (3, 2):
        first = next((case for case in misses if case.gt.class_id == class_id), None)
        if first:
            ordered.setdefault("false_negative", []).append(first)
    ordered.setdefault("false_negative", []).extend(misses)
    for kind in ("background_false_positive", "true_positive", "false_positive"):
        ordered[kind] = sorted(candidates[kind], key=lambda case: (case.pred.class_id != 3, -case.pred.confidence))
    selected = []
    used = set()
    for kind, limit in limits.items():
        for case in ordered[kind]:
            if case.image not in used:
                selected.append(case)
                used.add(case.image)
                limit -= 1
                if limit == 0:
                    break
        if len(selected) >= 10:
            return selected[:10]
    for kind in ("false_negative", "true_positive", "false_positive"):
        for case in ordered[kind]:
            if case.image not in used:
                selected.append(case)
                used.add(case.image)
                if len(selected) == 10:
                    return selected
    return selected


def _qualitative(model, images_dir: Path, val_pairs: list[tuple[Path, Path]], output_dir: Path, *, save_boxes=False) -> dict:
    remaining = {image.name: (image, label) for image, label in val_pairs}
    candidates = defaultdict(list)
    counts = {label: Counter() for label in CLASSES}
    confusion = Counter()
    frames = {}
    for result in model.predict(str(images_dir), stream=True, batch=4, imgsz=640, device=0, conf=CASE_CONFIDENCE,
                                iou=0.7, max_det=300, rect=False, save=False, verbose=False, quantize=None):
        image, annotation = remaining.pop(Path(result.path).name)
        height, width = result.orig_shape
        truth = _read_truth(annotation, width, height)
        predictions = [Detection(int(k), tuple(xyxy), confidence) for xyxy, k, confidence in zip(
            result.boxes.xyxy.tolist(), result.boxes.cls.tolist(), result.boxes.conf.tolist(), strict=True,
        )]
        base = (image, truth, predictions)
        if save_boxes:
            frames[image.name] = {"truth": [asdict(box) for box in truth],
                                  "predictions": [asdict(box) for box in predictions]}
        for gt in truth:
            counts[CLASSES[gt.class_id]]["ground_truth"] += 1
        for pred in predictions:
            counts[CLASSES[pred.class_id]]["predicted"] += 1

        matches, misses, extras = match_boxes(truth, predictions)
        for i, j, iou, wrong_class in matches:
            gt, pred = truth[i], predictions[j]
            if wrong_class:
                confusion[(CLASSES[gt.class_id], CLASSES[pred.class_id])] += 1
                counts[CLASSES[gt.class_id]]["wrong_class_gt"] += 1
                counts[CLASSES[pred.class_id]]["wrong_class_prediction"] += 1
                candidates["class_confusion"].append(Case(*base, "class_confusion", gt, pred, iou))
            else:
                counts[CLASSES[gt.class_id]]["true_positive"] += 1
                candidates["true_positive"].append(Case(*base, "true_positive", gt, pred, iou))
                candidates["small_detection"].append(Case(*base, "small_detection", gt, pred, iou))
        for i in misses:
            gt = truth[i]
            counts[CLASSES[gt.class_id]]["unmatched_ground_truth"] += 1
            candidates["false_negative"].append(Case(*base, "false_negative", gt=gt))
        for j in extras:
            pred = predictions[j]
            counts[CLASSES[pred.class_id]]["unmatched_prediction"] += 1
            kind = "false_positive"
            if not truth:
                counts[CLASSES[pred.class_id]]["background_false_positive"] += 1
                kind = "background_false_positive"
            candidates[kind].append(Case(*base, kind, pred=pred))
    if remaining:
        raise RuntimeError(f"정성 분석 중 Validation 이미지 {len(remaining)}장을 읽지 못했습니다.")
    if save_boxes:
        with (output_dir / "frames.json").open("x", encoding="utf-8") as handle:
            json.dump(frames, handle, ensure_ascii=False, allow_nan=False)

    gallery = output_dir / "cases"
    gallery.mkdir()
    saved = []
    for case in _select_cases(candidates):
        path = gallery / f"{case.kind}_{case.image.stem}.png"
        _render(case, path)
        saved.append({
            "image": case.image.name, "file": f"cases/{path.name}", "kind": case.kind,
            "ground_truth": asdict(case.gt) if case.gt else None, "prediction": asdict(case.pred) if case.pred else None,
            "iou": case.iou, "ground_truth_area_px2": case.gt.area if case.gt else None,
        })
    return {
        "images": len(val_pairs), "confidence_threshold": CASE_CONFIDENCE, "matching_iou": MATCH_IOU,
        "classes": {name: dict(count) for name, count in counts.items()}, "cases": saved,
        "class_confusions": [{"ground_truth": gt, "prediction": pred, "count": n} for (gt, pred), n in confusion.items()],
        "candidate_counts": {kind: len(items) for kind, items in candidates.items()},
    }


def evaluate_best(best: Path, data_yaml: Path, val_pairs: list[tuple[Path, Path]], output_dir: Path, *, save_boxes=False) -> dict:
    """best.pt의 Validation 지표와 GT/예측을 나란히 표시한 오류 사례를 저장한다."""
    from ultralytics import YOLO

    if not best.is_file():
        raise FileNotFoundError(best)
    model = YOLO(str(best), task="detect")
    if model.names != dict(enumerate(CLASSES)):
        raise ValueError(f"best.pt 클래스 매핑이 다릅니다. {best}")
    start = perf_counter()
    metrics = model.val(data=str(data_yaml), project=str(output_dir.parent), name=output_dir.name,
                        exist_ok=True, **VAL_OPTIONS)
    classes = {}
    for index, class_id in enumerate(metrics.box.ap_class_index):
        classes[CLASSES[class_id]] = {
            "images": int(metrics.nt_per_image[class_id]), "instances": int(metrics.nt_per_class[class_id]),
            **dict(zip(METRICS, map(float, metrics.class_result(index)), strict=True)),
        }
    if set(classes) != set(CLASSES) or not (output_dir / "confusion_matrix.png").is_file():
        raise RuntimeError("Validation 클래스별 결과 또는 혼동 행렬이 생성되지 않았습니다.")
    summary = {
        "weights": str(best), "images": len(val_pairs), "options": VAL_OPTIONS,
        "overall": dict(zip(METRICS, map(float, metrics.mean_results()), strict=True)),
        "classes": classes, "speed_ms_per_image": metrics.speed, "evaluation_wall_seconds": perf_counter() - start,
        "confusion_matrix": {"labels": [*CLASSES, "background"], "rows": "predicted", "columns": "ground_truth",
                             "counts": metrics.confusion_matrix.matrix.astype(int).tolist()},
    }
    with (output_dir / "metrics.json").open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2, allow_nan=False)
    qualitative = _qualitative(model, data_yaml.parent / "images/val", val_pairs, output_dir, save_boxes=save_boxes)
    with (output_dir / "qualitative.json").open("x", encoding="utf-8") as handle:
        json.dump(qualitative, handle, ensure_ascii=False, indent=2, allow_nan=False)
    return {**summary, "qualitative_cases": len(qualitative["cases"])}
