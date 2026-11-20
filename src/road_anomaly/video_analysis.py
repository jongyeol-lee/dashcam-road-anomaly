import csv
import json
import math
import ntpath
import re
from contextlib import ExitStack, closing
from datetime import UTC, datetime
from hashlib import file_digest
from pathlib import Path
from shutil import rmtree
from time import perf_counter

import cv2
import numpy as np

from .detection_grouping import DEFAULT_MAX_GAP, FrameDetection, group_detections, validate_max_gap
from .video import DEFAULT_FRAMES_ROOT, ExtractionResult, extract_frames


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = PROJECT_ROOT / "outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/weights/best.pt"
DEFAULT_ANALYSIS_ROOT = PROJECT_ROOT / "outputs/video_analysis"
DEFAULT_INTERVAL = 1.0
DEFAULT_CONFIDENCE = 0.05
DEVICES = ("auto", "cuda:0", "cpu")
PREDICT_OPTIONS = {"imgsz": 640, "iou": 0.7, "rect": False, "max_det": 300}
DETECTION_COLUMNS = (
    "frame_index", "estimated_time_sec", "class_id", "class_name", "confidence", "x1", "y1", "x2", "y2", "image_path",
)


def _remove_run_directory(directory: Path) -> None:
    # 현재 경로가 이번 실행에서 만든 디렉터리의 위치와 일치하는지 확인한다.
    if directory.is_dir() and directory.resolve() == directory:
        rmtree(directory)


def _load_model(model_path: Path):
    try:
        from ultralytics import YOLO

        with model_path.open("rb") as handle:
            digest = file_digest(handle, "sha256").hexdigest()
        model = YOLO(str(model_path), task="detect")
        if model.task != "detect":
            raise ValueError("객체 탐지용 모델이 필요합니다.")
    except Exception as error:
        raise RuntimeError(f"YOLO 모델을 불러오지 못했습니다. {model_path}\n{error}") from error
    return model, digest


def _select_device(device: str) -> str:
    if device == "auto":
        import torch

        return "cuda:0" if torch.cuda.is_available() else "cpu"
    return device


def _predict_detections(model, frames: ExtractionResult, options: dict) -> list[FrameDetection]:
    with (frames.output_dir / "frames.csv").open(encoding="utf-8", newline="") as handle:
        remaining = {
            frames.output_dir / row["image_file"]: (int(row["frame_index"]), float(row["estimated_time_sec"]))
            for row in csv.DictReader(handle)
        }
    detections = []
    try:
        with closing(model.predict(str(frames.output_dir), stream=True, save=False, verbose=False, **options)) as results:
            for result in results:
                image_path = Path(result.path).resolve()
                sampled_frame = remaining.pop(image_path, None)
                if sampled_frame is None:
                    raise ValueError(f"프레임 목록에 없거나 중복된 추론 결과입니다. {image_path}")
                frame_index, time_sec = sampled_frame
                boxes = result.boxes
                for xyxy, label, score in zip(boxes.xyxy.tolist(), boxes.cls.tolist(), boxes.conf.tolist(), strict=True):
                    class_id = int(label)
                    detections.append(FrameDetection(
                        frame_index, time_sec, class_id, result.names[class_id], float(score), tuple(xyxy), image_path,
                    ))
        if remaining:
            raise RuntimeError(f"샘플링 프레임 {len(remaining)}장의 추론 결과가 누락됐습니다.")
    except Exception as error:
        raise RuntimeError(f"YOLO 추론에 실패했습니다. {frames.output_dir}\n{error}") from error
    return sorted(detections, key=lambda item: item.frame_index)


def _save_detections(path: Path, detections: list[FrameDetection]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(DETECTION_COLUMNS)
        for item in detections:
            writer.writerow((
                item.frame_index, item.estimated_time_sec, item.class_id, item.class_name, item.confidence,
                *item.xyxy, item.image_path,
            ))


def _save_scene(path: Path, detection: FrameDetection) -> None:
    image = cv2.imdecode(np.frombuffer(detection.image_path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"대표 프레임을 읽을 수 없습니다. {detection.image_path}")
    x1, y1, x2, y2 = map(round, detection.xyxy)
    color = (64, 218, 255)
    cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
    text = f"{detection.class_name} {detection.confidence:.4f} | {detection.estimated_time_sec:.3f} s"
    for text_color, thickness in (((16, 16, 16), 3), (color, 1)):
        cv2.putText(image, text, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, text_color, thickness, cv2.LINE_AA)
    encoded, jpeg = cv2.imencode(".jpg", image)
    if not encoded:
        raise RuntimeError(f"대표 장면을 JPG로 인코딩할 수 없습니다. {path}")
    with path.open("xb") as handle:
        handle.write(jpeg.tobytes())


def _save_events(directory: Path, detections: list[FrameDetection], max_gap: float) -> list[dict]:
    (directory / "scenes").mkdir()
    entries = []
    for index, event in enumerate(group_detections(detections, max_gap), start=1):
        event_id = f"event_{index:04d}"
        scene_path = Path("scenes") / f"{event_id}.jpg"
        representative = event.representative
        _save_scene(directory / scene_path, representative)
        entries.append({
            "event_id": event_id,
            "class_id": representative.class_id,
            "class_name": representative.class_name,
            "start_time_sec": event.start_time_sec,
            "last_detection_time_sec": event.last_detection_time_sec,
            "max_confidence": representative.confidence,
            "representative_frame_index": representative.frame_index,
            "representative_time_sec": representative.estimated_time_sec,
            "representative_image": scene_path.as_posix(),
            "detection_count": event.detection_count,
            "detected_frame_count": event.detected_frame_count,
        })
    _write_json(directory / "events.json", entries)
    return entries


def _write_json(path: Path, data: dict | list) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def analyze_video(
    video_path: Path,
    *,
    run_name: str | None = None,
    model_path: Path = DEFAULT_MODEL,
    interval: float = DEFAULT_INTERVAL,
    confidence: float = DEFAULT_CONFIDENCE,
    max_gap: float = DEFAULT_MAX_GAP,
    device: str = "auto",
) -> dict:
    """MP4를 샘플링해 YOLO 탐지와 의심 구간을 저장하고 실행 요약을 반환한다."""
    if run_name is None:
        run_name = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%fZ")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", run_name) or ntpath.isreserved(run_name):
        raise ValueError("실행 이름에는 영문, 숫자, 밑줄, 하이픈을 사용할 수 있습니다.")
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("추출 간격은 0보다 큰 유한한 숫자(초)여야 합니다.")
    if not 0 <= confidence <= 1:
        raise ValueError("Confidence는 0~1이어야 합니다.")
    validate_max_gap(max_gap)
    if device not in DEVICES:
        raise ValueError(f"추론 장치는 {', '.join(DEVICES)} 중 하나여야 합니다.")
    if video_path.suffix.lower() != ".mp4":
        raise ValueError(f"입력 영상은 MP4 파일이어야 합니다. {video_path}")
    if not video_path.is_file():
        raise FileNotFoundError(f"MP4 파일을 찾을 수 없습니다. {video_path}")
    if model_path.suffix.lower() != ".pt":
        raise ValueError(f"모델은 로컬 .pt 파일이어야 합니다. {model_path}")
    if not model_path.is_file():
        raise FileNotFoundError(f"YOLO 모델 파일을 찾을 수 없습니다. {model_path}")
    video_path, model_path = video_path.resolve(), model_path.resolve()

    frames_dir = DEFAULT_FRAMES_ROOT.resolve() / run_name
    output_dir = DEFAULT_ANALYSIS_ROOT.resolve() / run_name
    for directory in (frames_dir, output_dir):
        if directory.exists(follow_symlinks=False):
            raise FileExistsError(f"이미 사용 중인 실행 이름입니다. {directory}")

    start = perf_counter()
    with ExitStack() as cleanup:
        for directory in (frames_dir, output_dir):
            directory.parent.mkdir(parents=True, exist_ok=True)
            try:
                # 사전 검사 이후 다른 실행이 같은 경로를 선점하는 경우도 막는다.
                directory.mkdir()
            except FileExistsError as error:
                raise FileExistsError(f"이미 사용 중인 실행 이름입니다. {directory}") from error
            cleanup.callback(_remove_run_directory, directory)

        frames = extract_frames(video_path, interval, frames_dir)
        model, digest = _load_model(model_path)
        options = {**PREDICT_OPTIONS, "conf": confidence, "device": _select_device(device)}
        detections = _predict_detections(model, frames, options)
        _save_detections(output_dir / "detections.csv", detections)
        events = _save_events(output_dir, detections, max_gap)
        summary = {
            "run_name": run_name,
            "video": {
                "path": str(video_path), "fps": frames.fps, "width": frames.width, "height": frames.height,
                "frame_count": frames.frame_count, "extracted_frame_count": frames.extracted_count,
            },
            "model": {"path": str(model_path), "sha256": digest},
            "settings": {"interval_sec": interval, "max_gap_sec": max_gap, **options},
            "timestamp_basis": "frame_index / fps",
            "frames_dir": str(frames_dir),
            "output_dir": str(output_dir),
            "detection_count": len(detections),
            "event_count": len(events),
            "analysis_seconds": perf_counter() - start,
        }
        # 대표 장면과 상세 결과가 모두 저장된 뒤 실행 요약을 기록한다.
        _write_json(output_dir / "summary.json", summary)
        cleanup.pop_all()
    return summary
