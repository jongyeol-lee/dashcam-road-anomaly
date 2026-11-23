import argparse
import csv
import math
import platform
import sys
from collections import Counter
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from hashlib import file_digest, sha256
from importlib.metadata import version
from pathlib import Path
from statistics import median

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.train_yolo_baseline import checked_name, ultralytics_environment
from road_anomaly.rdd2022 import CLASSES
from road_anomaly.video_analysis import (
    DEFAULT_ANALYSIS_ROOT, DEFAULT_CONFIDENCE, DEFAULT_MODEL, PREDICT_OPTIONS,
    _load_model, _remove_run_directory, _write_json,
)
from road_anomaly.yolo_evaluation import Detection, _read_truth, box_iou


VIDEO_PATH = PROJECT_ROOT / "data/raw/road_sample_04.mp4"
REVIEW_CSV = DEFAULT_ANALYSIS_ROOT / "road_sample_04_manual_review/review_frames.csv"
CONTROL_IMAGE = PROJECT_ROOT / "data/yolo/rdd2022_czech_v2/images/val/Czech_000370.jpg"
CONTROL_LABEL = CONTROL_IMAGE.parents[2] / "labels/val/Czech_000370.txt"
DEFAULT_RUN_NAME = "road_sample_04_diagnostic"
DEVICE = "cuda:0"
SETTINGS = {
    "device": DEVICE, "batch": 1, "conf": DEFAULT_CONFIDENCE, "iou": PREDICT_OPTIONS["iou"],
    "rect": False, "max_det": PREDICT_OPTIONS["max_det"], "augment": False, "quantize": None,
}
CONDITIONS = {"A1": 640, "A2": 960, "A3": 1280, "B": 640, "C": 640}
# 기존 검토 JPG의 우측 차로 자국과 주변 노면을 보고 정한 원본 픽셀 좌표다.
# 오른쪽과 아래쪽 경계는 NumPy 슬라이스처럼 포함하지 않는다.
TARGETS = {
    "A": (510, (812, 497, 1088, 581)),
    "B": (517, (810, 498, 1107, 585)),
    "C": (525, (816, 498, 1125, 582)),
}
BOX_COLUMNS = ("input_x1", "input_y1", "input_x2", "input_y2", "original_x1", "original_y1", "original_x2", "original_y2")
RESULT_COLUMNS = (
    "condition", "frame", "frame_index", "estimated_time_sec", "imgsz", "status", "detection_count",
    "input_tensor_shape", "inference_ms", "peak_cuda_allocated_bytes", "error",
    "detection_index", "class_id", "class_name", "confidence",
    *BOX_COLUMNS,
)
ROI_COLOR = (245, 212, 64)
BOX_COLOR = (0, 223, 255)


@dataclass(frozen=True)
class DecodedFrame:
    index: int
    time_sec: float
    decoder_time_ms: float
    image: np.ndarray


@dataclass(frozen=True)
class Prediction:
    class_id: int
    confidence: float
    input_xyxy: tuple[float, float, float, float]
    original_xyxy: tuple[float, float, float, float]


@dataclass(frozen=True)
class Measurement:
    status: str
    boxes: tuple[Prediction, ...] = ()
    input_tensor_shape: tuple[int, ...] | None = None
    inference_ms: float | None = None
    peak_cuda_allocated_bytes: int | None = None
    error: str | None = None

    @property
    def detection_count(self) -> int | None:
        return len(self.boxes) if self.status == "ok" else None


def decode_frames(video_path: Path, indices: set[int]) -> tuple[float, dict[int, DecodedFrame]]:
    """0번부터 순서대로 디코딩해 지정한 원본 프레임만 보존한다."""
    if not indices or min(indices) < 0:
        raise ValueError("0 이상의 원본 프레임 번호가 필요합니다.")
    if not video_path.is_file():
        raise FileNotFoundError(video_path)
    capture = cv2.VideoCapture(str(video_path))
    try:
        if not capture.isOpened():
            raise RuntimeError(f"MP4 파일을 열 수 없습니다. {video_path}")
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError(f"영상 FPS가 유효하지 않습니다. {fps}")
        frames = {}
        for index in range(max(indices) + 1):
            if not capture.grab():
                raise RuntimeError(f"원본 프레임 {index}를 디코딩할 수 없습니다. {video_path}")
            if index in indices:
                decoder_time = capture.get(cv2.CAP_PROP_POS_MSEC)
                ok, image = capture.retrieve()
                if not ok:
                    raise RuntimeError(f"원본 프레임 {index}를 읽을 수 없습니다. {video_path}")
                frames[index] = DecodedFrame(index, index / fps, decoder_time, image)
    finally:
        capture.release()
    return fps, frames


def crop_image(image: np.ndarray, roi: tuple[int, int, int, int]) -> np.ndarray:
    x1, y1, x2, y2 = roi
    height, width = image.shape[:2]
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError(f"Crop 좌표가 원본 이미지 범위를 벗어납니다. {roi} ({width}×{height})")
    return image[y1:y2, x1:x2].copy()


def collect_boxes(result, offset: tuple[int, int]) -> tuple[Prediction, ...]:
    """Ultralytics가 복원한 입력 이미지 좌표에 Crop 시작 좌표를 더한다."""
    boxes = result.boxes
    offset_x, offset_y = offset
    height, width = result.orig_shape
    predictions = []
    for box, label, score in zip(boxes.xyxy.tolist(), boxes.cls.tolist(), boxes.conf.tolist(), strict=True):
        x1, y1, x2, y2 = box
        class_id = int(label)
        if not (0 <= x1 <= x2 <= width and 0 <= y1 <= y2 <= height):
            raise ValueError(f"입력 이미지 범위를 벗어난 탐지 박스입니다. {box}")
        if not (0 <= class_id < len(CLASSES) and SETTINGS["conf"] <= score <= 1):
            raise ValueError(f"유효하지 않은 탐지 클래스 또는 confidence입니다. {label}, {score}")
        predictions.append(Prediction(class_id, score, tuple(box), (x1 + offset_x, y1 + offset_y, x2 + offset_x, y2 + offset_y)))
    return tuple(predictions)


def measure_prediction(model, predictor, image: np.ndarray, imgsz: int, offset: tuple[int, int]) -> Measurement:
    import torch

    if model.predictor is not None:
        model.predictor.input_tensor_shape = None
    try:
        torch.cuda.synchronize(DEVICE)
        torch.cuda.reset_peak_memory_stats(DEVICE)
        result, = model.predict(image, predictor=predictor, imgsz=imgsz, save=False, verbose=False, **SETTINGS)
        shape = model.predictor.input_tensor_shape
        if shape is None or str(model.predictor.device) != DEVICE or result.orig_shape != image.shape[:2]:
            raise RuntimeError("실제 추론 장치, 입력 텐서 또는 결과 이미지 크기를 확인할 수 없습니다.")
        return Measurement(
            "ok", collect_boxes(result, offset), shape, result.speed["inference"],
            torch.cuda.max_memory_allocated(DEVICE),
        )
    except Exception as error:
        oom = isinstance(error, torch.cuda.OutOfMemoryError) or "cuda out of memory" in str(error).lower()
        failure = Measurement(
            "cuda_oom" if oom else "error",
            input_tensor_shape=getattr(model.predictor, "input_tensor_shape", None),
            peak_cuda_allocated_bytes=torch.cuda.max_memory_allocated(DEVICE),
            error=f"{type(error).__name__}: {error}",
        )
    if oom:
        # 실패한 조건의 예측 상태와 캐시를 비우고 다음 조건으로 넘어간다.
        model.predictor = None
        torch.cuda.empty_cache()
    return failure


def run_conditions(model, predictor, frames, crops, control) -> dict[str, dict[str, Measurement]]:
    full_images = {key: frame.image for key, frame in frames.items()}
    trials = {}
    for condition, imgsz in CONDITIONS.items():
        images = crops if condition == "B" else full_images
        if condition == "C":
            images = {CONTROL_IMAGE.stem: control}
        results = {}
        oom = False
        for key, image in images.items():
            if oom:
                results[key] = Measurement("skipped_after_oom", error="CUDA OOM in an earlier frame of this condition")
                continue
            offset = TARGETS[key][1][:2] if condition == "B" else (0, 0)
            measurement = measure_prediction(model, predictor, image, imgsz, offset)
            results[key] = measurement
            oom = measurement.status == "cuda_oom"
        trials[condition] = results
    return trials


def write_results(path: Path, trials: dict[str, dict[str, Measurement]], frames: dict[str, DecodedFrame]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, RESULT_COLUMNS)
        writer.writeheader()
        for condition, results in trials.items():
            for key, result in results.items():
                row = {
                    "condition": condition, "frame": key, "imgsz": CONDITIONS[condition], "status": result.status,
                    "detection_count": result.detection_count,
                    "input_tensor_shape": "x".join(map(str, result.input_tensor_shape or ())),
                    "inference_ms": result.inference_ms, "peak_cuda_allocated_bytes": result.peak_cuda_allocated_bytes,
                    "error": result.error,
                }
                if key in frames:
                    row.update(frame_index=frames[key].index, estimated_time_sec=frames[key].time_sec)
                if not result.boxes:
                    writer.writerow(row)
                for number, box in enumerate(result.boxes, start=1):
                    coordinates = zip(BOX_COLUMNS, (*box.input_xyxy, *box.original_xyxy), strict=True)
                    writer.writerow({
                        **row, "detection_index": number, "class_id": box.class_id, "class_name": CLASSES[box.class_id],
                        "confidence": box.confidence, **dict(coordinates),
                    })


def write_jpg(path: Path, image: np.ndarray) -> str:
    ok, data = cv2.imencode(".jpg", image)
    if not ok:
        raise RuntimeError(f"JPG를 인코딩할 수 없습니다. {path}")
    with path.open("xb") as handle:
        handle.write(data)
    return sha256(data).hexdigest()


def render_panel(image, title, note, boxes=(), roi=None) -> np.ndarray:
    width, height, header = 640, 360, 48
    panel = np.full((height + header, width, 3), (25, 28, 32), dtype=np.uint8)
    source_height, source_width = image.shape[:2]
    scale = min(width / source_width, height / source_height)
    resized_width, resized_height = round(source_width * scale), round(source_height * scale)
    left, top = (width - resized_width) // 2, header + (height - resized_height) // 2
    interpolation = cv2.INTER_AREA if scale <= 1 else cv2.INTER_LINEAR
    panel[top:top + resized_height, left:left + resized_width] = cv2.resize(
        image, (resized_width, resized_height), interpolation=interpolation,
    )
    cv2.putText(panel, title, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (245, 245, 245), 1, cv2.LINE_AA)
    cv2.putText(panel, note, (10, 39), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (209, 219, 226), 1, cv2.LINE_AA)

    def draw_box(coordinates, color):
        x1, y1, x2, y2 = coordinates
        start = (left + round(x1 * scale), top + round(y1 * scale))
        stop = (left + round(x2 * scale), top + round(y2 * scale))
        cv2.rectangle(panel, start, stop, color, 2)
        return start

    if roi is not None:
        draw_box(roi, ROI_COLOR)
    for coordinates, label in boxes:
        x, y = draw_box(coordinates, BOX_COLOR)
        origin = (min(x, width - 112), max(header + 14, y - 5))
        cv2.putText(panel, label, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.44, (25, 25, 25), 3, cv2.LINE_AA)
        cv2.putText(panel, label, origin, cv2.FONT_HERSHEY_SIMPLEX, 0.44, BOX_COLOR, 1, cv2.LINE_AA)
    return panel


def write_comparison(path: Path, key: str, frame: DecodedFrame, crop: np.ndarray, trials) -> None:
    roi = TARGETS[key][1]
    panels = [render_panel(frame.image, f"Frame {key} | {frame.time_sec:.6f} s", "Original frame | Cyan rectangle - manual crop ROI", roi=roi)]
    titles = {
        "A1": "A1 | Full frame | imgsz 640", "A2": "A2 | Full frame | imgsz 960",
        "A3": "A3 | Full frame | imgsz 1280", "B": "B | Crop + imgsz 640 | Original coordinates",
    }
    for condition, title in titles.items():
        measurement = trials[condition][key]
        if measurement.status == "ok":
            note = f"{measurement.detection_count} detections | Yellow - YOLO" if measurement.boxes else "No detection"
        else:
            note = measurement.status.replace("_", " ")
        boxes = [(box.original_xyxy, f"{CLASSES[box.class_id]} {box.confidence:.4f}") for box in measurement.boxes]
        panels.append(render_panel(frame.image, title, note, boxes, roi if condition == "B" else None))
        if condition == "B":
            crop_boxes = [(box.input_xyxy, f"{CLASSES[box.class_id]} {box.confidence:.4f}") for box in measurement.boxes]
            panels.append(render_panel(crop, "B | Crop input detail", note, crop_boxes))
    write_jpg(path, np.vstack((np.hstack(panels[:3]), np.hstack(panels[3:]))))


def condition_summary(results: dict[str, Measurement]) -> dict:
    times = [result.inference_ms for result in results.values() if result.inference_ms is not None]
    allocations = [result.peak_cuda_allocated_bytes for result in results.values() if result.peak_cuda_allocated_bytes is not None]
    box_counts = Counter(CLASSES[box.class_id] for result in results.values() for box in result.boxes)
    return {
        "status_counts": dict(Counter(result.status for result in results.values())),
        "detection_count": sum(box_counts.values()), "class_counts": dict(box_counts),
        "median_inference_ms": median(times) if times else None,
        "peak_cuda_allocated_bytes": max(allocations, default=None),
        "frames": {key: {**asdict(result), "detection_count": result.detection_count} for key, result in results.items()},
    }


def diagnose(run_name: str) -> dict:
    import torch
    from ultralytics.models.yolo.detect.predict import DetectionPredictor

    class MeasuredPredictor(DetectionPredictor):
        def inference(self, im, *args, **kwargs):
            self.input_tensor_shape = tuple(im.shape)
            return super().inference(im, *args, **kwargs)

    output = DEFAULT_ANALYSIS_ROOT.resolve() / checked_name(run_name)
    if output.exists(follow_symlinks=False):
        raise FileExistsError(f"이미 사용 중인 실행 이름입니다. {output}")
    if not torch.cuda.is_available():
        raise RuntimeError("진단에 CUDA 0을 사용할 수 없습니다.")
    with REVIEW_CSV.open(encoding="utf-8", newline="") as handle:
        review_rows = {int(row["frame_index"]): row for row in csv.DictReader(handle) if row["source_video"] == VIDEO_PATH.name}
    fps, decoded = decode_frames(VIDEO_PATH, {index for index, _ in TARGETS.values()})
    frames, crops = {}, {}
    for key, (index, roi) in TARGETS.items():
        frame = decoded[index]
        reviewed = review_rows.get(index)
        if (frame.image.shape[:2] != (1080, 1920) or reviewed is None
                or not math.isclose(float(reviewed["estimated_time_sec"]), frame.time_sec, abs_tol=1e-6, rel_tol=0)
                or not math.isclose(float(reviewed["decoder_time_ms"]), frame.decoder_time_ms, abs_tol=1e-5, rel_tol=0)):
            raise ValueError(f"프레임 {index}의 해상도 또는 시각이 기존 검토 기록과 다릅니다.")
        frames[key] = frame
        crops[key] = crop_image(frame.image, roi)

    control_bytes = CONTROL_IMAGE.read_bytes()
    control = cv2.imdecode(np.frombuffer(control_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if control is None:
        raise RuntimeError(f"Czech 대조 이미지를 읽을 수 없습니다. {CONTROL_IMAGE}")
    truth = _read_truth(CONTROL_LABEL, control.shape[1], control.shape[0])
    if not any(box.class_id == 0 for box in truth):
        raise ValueError(f"Czech 대조 이미지의 D00 라벨을 찾을 수 없습니다. {CONTROL_LABEL}")
    model, digest = _load_model(DEFAULT_MODEL)
    if model.names != dict(enumerate(CLASSES)):
        raise ValueError("Baseline의 클래스 매핑이 Czech v2 기록과 다릅니다.")

    output.mkdir(parents=True)
    with ExitStack() as cleanup:
        cleanup.callback(_remove_run_directory, output)
        for subdir in ("frames", "crops", "comparisons"):
            (output / subdir).mkdir()
        frame_info = {}
        for key, frame in frames.items():
            frame_file = f"frames/frame_{key}.jpg"
            crop_file = f"crops/crop_{key}.jpg"
            comparison_file = f"comparisons/frame_{key}_comparison.jpg"
            jpg_digest = write_jpg(output / frame_file, frame.image)
            write_jpg(output / crop_file, crops[key])
            review_image = REVIEW_CSV.parent / f"review_frame_{frame.index:06d}.jpg"
            frame_info[key] = {
                "frame_index": frame.index, "estimated_time_sec": frame.time_sec, "decoder_time_ms": frame.decoder_time_ms,
                "resolution_wh": (frame.image.shape[1], frame.image.shape[0]), "image_file": frame_file,
                "decoded_bgr_sha256": sha256(frame.image.tobytes()).hexdigest(), "jpg_sha256": jpg_digest,
                "review_jpg_sha256_matches": jpg_digest == sha256(review_image.read_bytes()).hexdigest(),
                "roi_xyxy": TARGETS[key][1], "crop_file": crop_file, "comparison_file": comparison_file,
            }
        trials = run_conditions(model, MeasuredPredictor, frames, crops, control)
        for key, frame in frames.items():
            write_comparison(output / frame_info[key]["comparison_file"], key, frame, crops[key], trials)
        write_results(output / "results.csv", trials, frames)
        control_result = trials["C"][CONTROL_IMAGE.stem]
        d00_iou = [
            box_iou(gt, Detection(0, box.original_xyxy, box.confidence))
            for gt in truth if gt.class_id == 0 for box in control_result.boxes if box.class_id == 0
        ]
        with VIDEO_PATH.open("rb") as handle:
            video_digest = file_digest(handle, "sha256").hexdigest()
        summary = {
            "run_name": run_name, "output_dir": str(output), "video": {"path": str(VIDEO_PATH), "fps": fps, "sha256": video_digest},
            "model": {"path": str(DEFAULT_MODEL), "sha256": digest, "task": model.task, "classes": model.names},
            "settings": SETTINGS, "timestamp_basis": "frame_index / fps",
            "roi_convention": "xyxy in original pixels, right and bottom exclusive",
            "frames": frame_info,
            "conditions": {key: {"imgsz": CONDITIONS[key], **condition_summary(results)} for key, results in trials.items()},
            "control": {"image": str(CONTROL_IMAGE), "label": str(CONTROL_LABEL), "image_sha256": sha256(control_bytes).hexdigest(),
                        "labels_xyxy": [asdict(box) for box in truth], "best_labelled_d00_iou": max(d00_iou, default=None)},
            "environment": {
                "platform": platform.platform(), "python": platform.python_version(), "torch": torch.__version__,
                "torchvision": version("torchvision"), "ultralytics": version("ultralytics"), "opencv": cv2.__version__,
                "cuda_build": torch.version.cuda, "gpu": torch.cuda.get_device_name(0),
                "gpu_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
            },
        }
        _write_json(output / "summary.json", summary)
        cleanup.pop_all()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="road_sample_04의 원본 프레임 3장으로 입력 크기와 도로 Crop을 비교합니다.")
    parser.add_argument("--run-name", default=DEFAULT_RUN_NAME, help="새 출력 실행 이름")
    args = parser.parse_args()
    try:
        with ultralytics_environment():
            summary = diagnose(args.run_name)
    except (OSError, ValueError, RuntimeError, cv2.error) as error:
        parser.exit(1, f"{error}\n")
    for condition, result in summary["conditions"].items():
        print(f"{condition} | imgsz {result['imgsz']} | 탐지 {result['detection_count']}건 | {result['status_counts']}")
    print(f"출력 {summary['output_dir']}")


if __name__ == "__main__":
    main()
