import argparse
import csv
import json
import math
import sys
from collections import Counter
from collections.abc import Iterable
from contextlib import ExitStack
from dataclasses import dataclass
from hashlib import sha256
from io import StringIO
from pathlib import Path
from time import perf_counter

import cv2
import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.diagnose_video_detection import ROI_COLOR, render_panel, write_jpg
from scripts.train_yolo_baseline import checked_name
from road_anomaly.detection_grouping import FrameDetection, SuspiciousEvent, group_detections
from road_anomaly.rdd2022 import CLASSES
from road_anomaly.roi import BoxPosition, NormalizedRoi
from road_anomaly.video_analysis import DEFAULT_ANALYSIS_ROOT, DETECTION_COLUMNS, PROJECT_ROOT, _remove_run_directory, _write_json


OUTPUT_ROOT = PROJECT_ROOT / "outputs/roi_diagnostics"
SOURCE_RUNS = {"baseline": "part524_road04_baseline", "mixed": "part524_road04_mixed"}
DEFAULT_RUN_NAME = "part531_road04"
ROIS = {
    "A": None,
    # 중앙 노면과 대시보드가 맞닿는 띠 아래에 여유를 둔다.
    "B": NormalizedRoi(((0, 0), (1, 0), (1, 0.60), (0, 0.60))),
    # 전방 차로의 소실점 부근에서 가까운 차로로 넓어지는 고정 사다리꼴이다.
    "C": NormalizedRoi(((0.385, 0.445), (0.55, 0.445), (0.65, 0.545), (0.255, 0.545))),
}
INTERIOR_D40_FRAMES = frozenset({45, 60, 75, 540, 795})
REVIEW_FRAMES = frozenset({0, 30, 270, 390, 510, 720, 870})
COMPARISON_COLUMNS = (
    "model", "condition", "source_detections_sha256", "before_count", "excluded_count", "retained_count",
    *CLASSES, "event_count", "known_interior_excluded_count", "boundary_contact_count", "filter_ms", "grouping_ms",
)
BOX_COLUMNS = (
    "model", "box_index", *DETECTION_COLUMNS, "width_px", "height_px", "center_x_norm", "center_y_norm",
    "known_interior_false_positive", *(f"{condition}_{field}" for condition in ROIS for field in ("keep", "boundary")),
)


@dataclass(frozen=True)
class SampledFrame:
    time_sec: float
    path: Path
    sha256: str


@dataclass(frozen=True)
class AnalysisRun:
    directory: Path
    summary: dict
    frames: dict[int, SampledFrame]
    detections: tuple[FrameDetection, ...]
    digests: dict[str, str]


def read_frames(summary: dict, data: bytes) -> dict[int, SampledFrame]:
    folder = Path(summary["frames_dir"])
    video = summary["video"]
    fps = video["fps"]
    if not math.isfinite(fps) or fps <= 0 or min(video["width"], video["height"]) <= 0:
        raise ValueError(f"기존 영상의 FPS 또는 해상도가 유효하지 않습니다. {folder}")
    frames = {}
    for row in csv.DictReader(StringIO(data.decode("utf-8"), newline="")):
        index = int(row["frame_index"])
        time_sec = float(row["estimated_time_sec"])
        name = f"frame_{index:06d}.jpg"
        if (index in frames or not 0 <= index < video["frame_count"] or row["image_file"] != name
                or not math.isclose(time_sec, index / fps, rel_tol=0, abs_tol=1e-9)):
            raise ValueError(f"기존 프레임 목록이 올바르지 않습니다. {folder} / {index}")
        path = (folder / name).resolve()
        frames[index] = SampledFrame(time_sec, path, sha256(path.read_bytes()).hexdigest())
    if not frames or len(frames) != video["extracted_frame_count"]:
        raise ValueError(f"프레임 목록과 요약의 수량이 다릅니다. {folder}")
    return frames


def read_detections(data: bytes, frames: dict[int, SampledFrame]) -> tuple[FrameDetection, ...]:
    reader = csv.DictReader(StringIO(data.decode("utf-8"), newline=""))
    if tuple(reader.fieldnames or ()) != DETECTION_COLUMNS:
        raise ValueError("기존 detections.csv 열 이름이 일치하지 않습니다.")
    detections = []
    for row in reader:
        index = int(row["frame_index"])
        frame = frames.get(index)
        time_sec = float(row["estimated_time_sec"])
        image_path = Path(row["image_path"]).resolve()
        class_id, score = int(row["class_id"]), float(row["confidence"])
        if frame is None or (time_sec, image_path) != (frame.time_sec, frame.path):
            raise ValueError(f"탐지 시각 또는 이미지 경로가 프레임 목록과 다릅니다. {index}")
        if not (0 <= class_id < len(CLASSES) and row["class_name"] == CLASSES[class_id] and 0 <= score <= 1):
            raise ValueError(f"탐지 클래스 또는 confidence가 올바르지 않습니다. {index}")
        box = tuple(float(row[key]) for key in ("x1", "y1", "x2", "y2"))
        detections.append(FrameDetection(index, time_sec, class_id, CLASSES[class_id], score, box, image_path))
    return tuple(detections)


def event_record(event: SuspiciousEvent) -> dict:
    detection = event.representative
    return {
        "class_id": detection.class_id, "class_name": detection.class_name, "start_time_sec": event.start_time_sec,
        "last_detection_time_sec": event.last_detection_time_sec, "max_confidence": detection.confidence,
        "representative_frame_index": detection.frame_index, "representative_time_sec": detection.estimated_time_sec,
        "detection_count": event.detection_count, "detected_frame_count": event.detected_frame_count,
    }


def read_analysis(directory: Path) -> AnalysisRun:
    files = {name: (directory / name).read_bytes() for name in ("summary.json", "detections.csv", "events.json")}
    summary = json.loads(files["summary.json"])
    files["frames.csv"] = (Path(summary["frames_dir"]) / "frames.csv").read_bytes()
    frames = read_frames(summary, files["frames.csv"])
    detections = read_detections(files["detections.csv"], frames)
    events = json.loads(files["events.json"])
    grouped = group_detections(detections, summary["settings"]["max_gap_sec"])
    if summary["detection_count"] != len(detections) or summary["event_count"] != len(events) or len(events) != len(grouped):
        raise ValueError(f"기존 박스 또는 의심 구간 수가 다시 계산한 값과 일치하지 않습니다. {directory}")
    for recorded, event in zip(events, grouped, strict=True):
        if any(recorded.get(key) != value for key, value in event_record(event).items()):
            raise ValueError(f"기존 의심 구간이 다시 계산한 값과 일치하지 않습니다. {directory}")
    digests = {name: sha256(data).hexdigest() for name, data in files.items()}
    return AnalysisRun(directory, summary, frames, detections, digests)


def verify_shared_frames(baseline: AnalysisRun, mixed: AnalysisRun) -> None:
    if any(baseline.summary[key] != mixed.summary[key] for key in ("video", "settings", "timestamp_basis")):
        raise ValueError("두 기존 분석의 원본 영상 또는 추론 설정이 다릅니다.")
    if (baseline.digests["frames.csv"] != mixed.digests["frames.csv"]
            or {i: frame.sha256 for i, frame in baseline.frames.items()}
            != {i: frame.sha256 for i, frame in mixed.frames.items()}):
        raise ValueError("두 기존 분석의 프레임 목록 또는 추출 JPG가 다릅니다.")


def class_counts(detections: Iterable[FrameDetection]) -> dict[str, int]:
    counts = Counter(item.class_name for item in detections)
    return {name: counts[name] for name in CLASSES}


def compare_condition(
    detections: tuple[FrameDetection, ...], roi: NormalizedRoi | None, width: int, height: int, max_gap: float,
    known_indices: frozenset[int] = frozenset(),
) -> tuple[dict, tuple[BoxPosition, ...]]:
    started = perf_counter()
    decisions = tuple(roi.classify(item.xyxy, width, height) if roi else BoxPosition(True, False) for item in detections)
    kept, excluded = [], []
    for detection, decision in zip(detections, decisions, strict=True):
        (kept if decision.keep else excluded).append(detection)
    filter_ms = (perf_counter() - started) * 1000
    started = perf_counter()
    events = group_detections(kept, max_gap)
    grouping_ms = (perf_counter() - started) * 1000
    return {
        "before_count": len(detections), "excluded_count": len(excluded), "retained_count": len(kept),
        "before_class_counts": class_counts(detections), "excluded_class_counts": class_counts(excluded),
        "retained_class_counts": class_counts(kept),
        "event_count": len(events), "events": [event_record(event) for event in events],
        "known_interior_excluded_count": sum(not decisions[index].keep for index in known_indices),
        "boundary_contact_count": sum(item.touches_boundary for item in decisions),
        "filter_ms": filter_ms, "grouping_ms": grouping_ms,
    }, decisions


def box_rows(model: str, items: tuple[FrameDetection, ...], decisions: dict, width: int, height: int, known: frozenset[int]):
    for index, item in enumerate(items):
        x1, y1, x2, y2 = item.xyxy
        yield {
            "model": model, "box_index": index + 1, "frame_index": item.frame_index,
            "estimated_time_sec": item.estimated_time_sec, "class_id": item.class_id, "class_name": item.class_name,
            "confidence": item.confidence, "x1": x1, "y1": y1, "x2": x2, "y2": y2, "image_path": item.image_path,
            "width_px": x2 - x1, "height_px": y2 - y1, "center_x_norm": (x1 + x2) / (2 * width),
            "center_y_norm": (y1 + y2) / (2 * height), "known_interior_false_positive": index in known,
            **{f"{condition}_{field}": value for condition, positions in decisions.items()
               for field, value in (("keep", positions[index].keep), ("boundary", positions[index].touches_boundary))},
        }


def shade_excluded(image: np.ndarray, roi: NormalizedRoi) -> np.ndarray:
    height, width = image.shape[:2]
    points = np.array([(min(round(x), width - 1), min(round(y), height - 1))
                       for x, y in roi.pixel_vertices(width, height)], dtype=np.int32)
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillConvexPoly(mask, points, 255)
    tint = np.full_like(image, (46, 23, 39))
    shaded = cv2.addWeighted(image, 0.52, tint, 0.48, 0)
    shaded[mask != 0] = image[mask != 0]
    cv2.polylines(shaded, [points], True, ROI_COLOR, 3, cv2.LINE_AA)
    return shaded


def write_preview(path: Path, index: int, frame: SampledFrame, shape: tuple[int, int], rows: list[dict]) -> None:
    data = frame.path.read_bytes()
    if sha256(data).hexdigest() != frame.sha256:
        raise ValueError(f"미리보기 생성 전에 추출 JPG가 변경됐습니다. {frame.path}")
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape[:2] != shape:
        raise ValueError(f"추출 JPG를 읽을 수 없거나 해상도가 다릅니다. {frame.path}")
    panels = [render_panel(image, f"Original | Frame {index} | {frame.time_sec:.4f} s", "Saved inference frame")]
    titles = {"A": "A | Full-frame YOLO | Czech + Japan", "B": "B | Conservative exclusion", "C": "C | Road-only candidate"}
    for condition, roi in ROIS.items():
        boxes = [((row["x1"], row["y1"], row["x2"], row["y2"]), f"{row['class_name']} {row['confidence']:.4f}")
                 for row in rows if row[f"{condition}_keep"]]
        note = f"{len(boxes)} boxes | Yellow = predicted box"
        panel_image = image
        if roi is not None:
            panel_image = shade_excluded(image, roi)
            note = f"{len(boxes)} kept / {len(rows) - len(boxes)} excluded | Cyan = ROI | Shaded = excluded"
        panels.append(render_panel(panel_image, titles[condition], note, boxes))
    write_jpg(path, np.vstack((np.hstack(panels[:2]), np.hstack(panels[2:]))))


def write_csv(path: Path, columns: tuple[str, ...], rows) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, columns)
        writer.writeheader()
        writer.writerows(rows)


def diagnose(run_name: str) -> dict:
    output = OUTPUT_ROOT.resolve() / checked_name(run_name)
    if output.exists(follow_symlinks=False):
        raise FileExistsError(f"이미 사용 중인 실행 이름입니다. {output}")
    sources = {model: read_analysis(DEFAULT_ANALYSIS_ROOT / name) for model, name in SOURCE_RUNS.items()}
    mixed = sources["mixed"]
    verify_shared_frames(sources["baseline"], mixed)
    video = mixed.summary["video"]
    width, height = video["width"], video["height"]
    max_gap = mixed.summary["settings"]["max_gap_sec"]
    known = frozenset(index for index, item in enumerate(mixed.detections)
                      if item.class_name == "D40" and item.frame_index in INTERIOR_D40_FRAMES)
    if len(known) != len(INTERIOR_D40_FRAMES) or {mixed.detections[i].frame_index for i in known} != INTERIOR_D40_FRAMES:
        raise ValueError("기존 검토에서 실내 오탐으로 확인한 D40 박스 5개를 식별할 수 없습니다.")

    comparisons, all_boxes, models = [], [], {}
    for model, source in sources.items():
        decisions, conditions = {}, {}
        prediction_digest = source.digests["detections.csv"]
        known_indices = known if model == "mixed" else frozenset()
        for condition, roi in ROIS.items():
            result, decisions[condition] = compare_condition(source.detections, roi, width, height, max_gap, known_indices)
            conditions[condition] = result
            comparisons.append({
                "model": model, "condition": condition, "source_detections_sha256": prediction_digest,
                **{key: result[key] for key in COMPARISON_COLUMNS if key in result}, **result["retained_class_counts"],
            })
        all_boxes.extend(box_rows(model, source.detections, decisions, width, height, known_indices))
        models[model] = {
            "source_directory": str(source.directory), "source_sha256": source.digests, "source_model": source.summary["model"],
            "source_analysis_seconds": source.summary["analysis_seconds"], "conditions": conditions,
        }

    roi_config = {
        "resolution_wh": [width, height], "method": "post_filter_full_frame_predictions",
        "coordinate_convention": "x * width, y * height; origin at top left",
        "keep_rule": "center_inside_or_on_boundary", "boundary_rule": "box_intersects_or_touches_polygon_edge",
        "conditions": {condition: None if roi is None else {
            "vertices_normalized": roi.vertices, "vertices_px": roi.pixel_vertices(width, height),
        } for condition, roi in ROIS.items()},
    }
    summary = {
        "run_name": run_name, "output_dir": str(output), "video": video, "source_settings": mixed.summary["settings"],
        "source_timestamp_basis": mixed.summary["timestamp_basis"], "shared_sample_images_verified": len(mixed.frames),
        "full_frame_predictions_reused": True, "known_interior_false_positive_frames": sorted(INTERIOR_D40_FRAMES),
        "models": models, "previews": [],
    }
    preview_rows = {index: [] for index in sorted(REVIEW_FRAMES | {item.frame_index for item in mixed.detections})}
    for box in all_boxes:
        if box["model"] == "mixed":
            preview_rows[box["frame_index"]].append(box)

    # 이미 존재하는 실행 경로는 mkdir에서 거부하고 실패 시 이번 실행 폴더만 정리한다.
    output.mkdir(parents=True)
    with ExitStack() as cleanup:
        cleanup.callback(_remove_run_directory, output)
        (output / "previews").mkdir()
        for index, rows in preview_rows.items():
            filename = f"previews/frame_{index:06d}.jpg"
            frame = mixed.frames[index]
            write_preview(output / filename, index, frame, (height, width), rows)
            summary["previews"].append({
                "frame_index": index, "time_sec": frame.time_sec, "full_frame_box_count": len(rows), "image": filename,
            })
        write_csv(output / "roi_comparison.csv", COMPARISON_COLUMNS, comparisons)
        write_csv(output / "roi_boxes.csv", BOX_COLUMNS, all_boxes)
        _write_json(output / "roi_config.json", roi_config)
        _write_json(output / "roi_summary.json", summary)
        cleanup.pop_all()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="road_sample_04의 저장된 전체 프레임 예측에서 ROI 후처리를 비교합니다.")
    parser.add_argument("--run-name", default=DEFAULT_RUN_NAME, help="새 출력 실행 이름")
    args = parser.parse_args()
    try:
        summary = diagnose(args.run_name)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, cv2.error) as error:
        parser.exit(1, f"{error}\n")
    for model, source in summary["models"].items():
        for condition, row in source["conditions"].items():
            print(f"{model} {condition} | {row['before_count']} → {row['retained_count']} 박스 | {row['event_count']} 구간")
    print(f"출력 {summary['output_dir']}")


if __name__ == "__main__":
    main()
