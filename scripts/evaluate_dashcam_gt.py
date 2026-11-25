"""발행 블랙박스 GT v1에서 두 YOLO 모델과 ROI B를 비교한다."""

import argparse
import csv
import json
import platform
import re
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from statistics import mean
from time import perf_counter

import cv2
import numpy as np


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts.annotate_dashcam_drafts import staging_directory
from scripts.diagnose_video_detection import render_panel, write_jpg
from scripts.diagnose_video_roi import ROIS
from scripts.prepare_dashcam_review import sha256_file
from scripts.publish_dashcam_gt import RELEASE
from scripts.train_yolo_baseline import checked_name, ultralytics_environment
from road_anomaly.dashcam_evaluation import (
    CLASSES, CONFIDENCES, MATCH_IOU, RELEASE_HASHES, SIZE, UNCERTAIN_COVERAGE, EvaluationImage, IdentifiedDetection,
    checked_bytes, detection_record, evaluate_pair, identify_prediction, read_release, summarize,
)
from road_anomaly.video_analysis import DEFAULT_MODEL, PREDICT_OPTIONS, _load_model, _write_json


OUTPUT_ROOT = PROJECT / "outputs/dashcam_evaluation"
MODEL_PATHS = {
    "baseline": DEFAULT_MODEL,
    "mixed": PROJECT / "outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/weights/best.pt",
}
MODEL_HASHES = {
    "baseline": "40f0b6af12b8a33d83119138251ae345ee2ac50df5a3ae0ec81137d781b63342",
    "mixed": "3d770f1515ef2baf2fbe25d4c9ba241d289254b2002894d7cc02ff56009b2afb",
}
CONDITIONS = {"baseline": ("A", "B"), "mixed": ("C", "D")}
ROI_B = ROIS["B"]
DEVICE = "cuda:0"
OPTIONS = {
    **PREDICT_OPTIONS, "device": DEVICE, "conf": CONFIDENCES[0], "batch": 1, "quantize": None,
    "augment": False, "classes": None, "agnostic_nms": False, "tile": False, "nms": None,
    "save": False, "save_txt": False, "save_crop": False, "show": False, "verbose": False,
}
COLORS = {
    "gt": (250, 250, 250), "tp": (105, 240, 105), "fn": (70, 110, 255), "background_fp": (30, 165, 255),
    "uncertain": (245, 155, 245), "review": (90, 235, 255),
}
LABELS = {"tp": "TP", "background_fp": "FP", "uncertain": "Hold", "review": "Review"}


def read_frame(frame: EvaluationImage) -> np.ndarray:
    path = RELEASE / frame.image_path
    if not path.resolve().is_relative_to(RELEASE.resolve()):
        raise ValueError(f"발행 디렉터리 외부 이미지입니다. {path}")
    data = checked_bytes(path, frame.image_sha256)
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape[:2] != SIZE[::-1]:
        raise ValueError(f"원본 해상도의 발행 PNG를 디코딩할 수 없습니다. {path}")
    return image


def frame_record(frame: EvaluationImage) -> dict:
    return {"image_id": frame.image_id, "revision": frame.revision, "scope": frame.scope,
            "source_video": frame.source_video, "frame_index": frame.frame_index,
            "estimated_time_sec": frame.estimated_time_sec, "image_path": frame.image_path,
            "image_sha256": frame.image_sha256}


def runtime_info(torch) -> dict:
    if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
        raise RuntimeError(f"CUDA 0을 사용할 수 없습니다. PyTorch {torch.__version__}, CUDA 빌드 {torch.version.cuda}")
    # 로딩과 워밍업 시간에서 CUDA 컨텍스트 초기화를 분리하고 실제 장치의 텐서 연산을 검증한다.
    values = (torch.arange(3, device=DEVICE) * 2).tolist()
    if values != [0, 2, 4]:
        raise RuntimeError(f"CUDA 0 텐서 검증 실패: {values}")
    gpu = torch.cuda.get_device_properties(DEVICE)
    smi = subprocess.run(["nvidia-smi", "-q", "-i", "0"], capture_output=True, text=True, check=True).stdout
    driver = re.search(r"^Driver Version\s*:\s*(\S+)", smi, re.MULTILINE)
    driver_cuda = re.search(r"^CUDA Version\s*:\s*(\S+)", smi, re.MULTILINE)
    return {
        "os": platform.platform(), "python": platform.python_version(), "executable": sys.executable,
        "torch": torch.__version__, "torchvision": version("torchvision"), "torch_cuda_build": torch.version.cuda,
        "ultralytics": version("ultralytics"), "opencv": cv2.__version__, "opencv_python": version("opencv-python"),
        "numpy": np.__version__, "device": DEVICE, "gpu": gpu.name, "vram_bytes": gpu.total_memory,
        "compute_capability": [gpu.major, gpu.minor], "cuda_probe_result": values,
        "nvidia_driver": driver.group(1) if driver else None,
        "driver_cuda_version": driver_cuda.group(1) if driver_cuda else None,
    }


def infer(name: str, model, frames: tuple[EvaluationImage, ...], images: dict[str, np.ndarray], torch,
          *, imgsz: int = OPTIONS["imgsz"], measure_resolution: bool = False) -> dict:
    """배치 1로 매니페스트 순서대로 각 실영상 프레임을 한 번 추론한다."""
    first_image = images[frames[0].image_id]
    options = {**OPTIONS, "imgsz": imgsz}
    tensor_shape = (options["batch"], 3, imgsz, imgsz)
    predict_kwargs = {}
    if measure_resolution:
        from ultralytics.models.yolo.detect.predict import DetectionPredictor

        class MeasuredPredictor(DetectionPredictor):
            def inference(self, im, *args, **kwargs):
                self.observed_input = (tuple(im.shape), str(im.dtype), str(im.device))
                return super().inference(im, *args, **kwargs)

        predict_kwargs["predictor"] = MeasuredPredictor
    records, timings = [], []
    torch.cuda.synchronize(DEVICE)
    start = perf_counter()
    # 실제 이미지는 스트림 소비 시에만 추론된다. 여기서 장치 이동과 모델 fuse 시간을 따로 잰다.
    with closing(model.predict(first_image, stream=True, **options, **predict_kwargs)) as first_results:
        predictor = model.predictor
        torch.cuda.synchronize(DEVICE)
        backend_setup_ms = (perf_counter() - start) * 1000
        if str(predictor.device) != DEVICE or predictor.model.fp16 or predictor.model.end2end:
            raise RuntimeError(f"CUDA 0, FP32, 클래스별 NMS를 적용할 수 없습니다. {name}")
        start = perf_counter()
        with torch.inference_mode():
            dummy = torch.zeros(tensor_shape, device=DEVICE, dtype=torch.float32)
            predictor.model.warmup(im=dummy)
        torch.cuda.synchronize(DEVICE)
        warmup_ms = (perf_counter() - start) * 1000
        predictor.done_warmup = True
        if measure_resolution:
            del dummy
            torch.cuda.reset_peak_memory_stats(DEVICE)

        for index, frame in enumerate(frames):
            start = perf_counter()
            results = list(first_results) if index == 0 else model.predict(images[frame.image_id], **options)
            torch.cuda.synchronize(DEVICE)
            prediction_wall_ms = (perf_counter() - start) * 1000
            expected_hw = (imgsz,) * 2
            if measure_resolution and predictor.observed_input != (tensor_shape, "torch.float32", DEVICE):
                raise RuntimeError(f"실제 입력 텐서 불일치: {predictor.observed_input}")
            if (len(results) != 1 or results[0].orig_shape != SIZE[::-1] or predictor.dataset.bs != 1
                    or tuple(predictor.imgsz) != expected_hw or model.predictor is not predictor):
                raise RuntimeError(f"실제 추론 배치 또는 해상도가 예상과 다릅니다. {name} {frame.image_id}")
            result = results[0]
            boxes = result.boxes.cpu()
            predictions = [
                detection_record(identify_prediction(name, frame.image_id, number, cls, xyxy, score))
                for number, (xyxy, cls, score) in enumerate(zip(
                    boxes.xyxy.tolist(), boxes.cls.tolist(), boxes.conf.tolist(), strict=True,
                ), start=1)
            ]
            timing = {**result.speed, "prediction_wall": prediction_wall_ms}
            timings.append(timing)
            records.append({**frame_record(frame), "predictions": predictions, "timing_ms": timing})

    effective = {key: getattr(predictor.args, key) for key in OPTIONS}
    if effective != options:
        raise RuntimeError(f"실제 YOLO 설정이 사전 조건과 다릅니다. {name}: {effective}")
    return {
        "model": name, "frames": records, "options": effective, "class_names": model.names,
        "backend": predictor.model.format, "input_tensor_shape": tensor_shape,
        "input_dtype": predictor.observed_input[1] if measure_resolution else str(dummy.dtype),
        **({"input_tensor_shape": predictor.observed_input[0],
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(DEVICE),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(DEVICE)} if measure_resolution else {}),
        "weight_dtype": str(next(predictor.model.model.parameters()).dtype),
        "batch_size": predictor.dataset.bs, "class_aware_nms": not predictor.args.agnostic_nms,
        "cuda_matmul_allow_tf32": torch.backends.cuda.matmul.allow_tf32,
        "cudnn_allow_tf32": torch.backends.cudnn.allow_tf32,
        "backend_setup_ms": backend_setup_ms, "warmup_ms": warmup_ms,
        "timing_total_ms": {key: sum(row[key] for row in timings) for key in timings[0]},
        "timing_mean_ms_per_image": {key: mean(row[key] for row in timings) for key in timings[0]},
    }


def draw_marks(panel: np.ndarray, marks: list) -> None:
    height, width = panel.shape[:2]
    scale = width / SIZE[0]
    top = height - round(SIZE[1] * scale)
    font = cv2.FONT_HERSHEY_SIMPLEX
    labels = []
    for box, label, status, below in marks:
        x1, y1, x2, y2 = (round(value * scale) for value in box)
        color = COLORS[status]
        cv2.rectangle(panel, (x1, top + y1), (min(x2, width - 1), min(top + y2, height - 1)), color, 2)
        (text_width, text_height), _ = cv2.getTextSize(label, font, 0.44, 1)
        x = min(x1, width - text_width - 5)
        anchor = top + (y2 if below else y1)
        preferred = min(max(top + text_height + 3, anchor + (text_height + 4 if below else -5)), height - 4)
        labels.append((label, color, x, anchor, preferred, text_width + 4, text_height + 3))

    # 박스가 겹쳐도 먼저 그린 글자를 가리지 않는 가까운 위치에 번호를 배치한다.
    occupied = []
    for label, color, x, anchor, preferred, text_width, text_height in labels:
        candidates = [preferred, *sorted(range(top + text_height, height - 3, 16), key=lambda y: abs(y - preferred))]
        y = next((y for y in candidates if all(x + text_width < left or x > right or y + 3 < upper
                                               or y - text_height > lower for left, upper, right, lower in occupied)),
                 preferred)
        if abs(y - preferred) > 10:
            cv2.line(panel, (x + 2, anchor), (x + 2, y), color, 1, cv2.LINE_AA)
        occupied.append((x, y - text_height, x + text_width, y + 3))
        cv2.rectangle(panel, (x, y - text_height), (x + text_width, y + 3), (25, 28, 32), cv2.FILLED)
        cv2.putText(panel, label, (x + 2, y), font, 0.44, color, 1, cv2.LINE_AA)


def add_legend(panel: np.ndarray, rows: int, predictions: list[dict]) -> np.ndarray:
    if rows == 0:
        return panel
    line_height = 20
    footer = np.full((line_height * rows + 4, panel.shape[1], 3), (25, 28, 32), dtype=np.uint8)
    for index, pred in enumerate(predictions):
        row, col = divmod(index, 3)
        status = pred["disposition"]
        number = pred["box_id"].rsplit(":", 1)[1]
        text = f"{number}  {pred['class']}  {pred['confidence']:.4f}  {LABELS[status]}"
        cv2.putText(footer, text, (10 + col * (panel.shape[1] // 3), 16 + row * line_height),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, COLORS[status], 1, cv2.LINE_AA)
    return np.vstack((panel, footer))


def write_comparison(path: Path, image: np.ndarray, frame: EvaluationImage, confidence: float, results: dict) -> None:
    (x1, y1), _, (x2, y2), _ = ROI_B.pixel_vertices(*SIZE)
    roi_box = (x1, y1, x2, y2)
    original = render_panel(image, f"{frame.image_id} | {frame.estimated_time_sec:.3f} s | Original",
                            f"{frame.scope} | Confidence >= {confidence:.2f}")
    reference = render_panel(image, f"Approved GT and hold regions | v{frame.revision:04d}",
                             f"GT {len(frame.truth)} | Hold regions {len(frame.uncertain_regions)} | ROI B y={y2:g}",
                             roi=roi_box)
    draw_marks(reference, [*((gt.xyxy, f"GT {CLASSES[gt.class_id]}", "gt", True) for gt in frame.truth),
                           *((region.xyxy, "Hold region", "uncertain", False) for region in frame.uncertain_regions)])

    titles = {"A": "Czech | ROI off", "B": "Czech | ROI B", "C": "Czech + Japan | ROI off", "D": "Czech + Japan | ROI B"}
    legend_rows = {code: (max(len(results[key]["predictions"]) for key in pair) + 2) // 3
                   for pair in CONDITIONS.values() for code in pair}
    panels = {}
    for condition, row in results.items():
        counts = summarize([row])
        d20, tags = counts["classes"]["D20"], counts["dispositions"]
        note = (f"TP {d20['tp']} | FN {d20['fn']} | FP {tags['background_fp']} | "
                f"Hold {tags['uncertain']} | Review {tags['review']}")
        panel = render_panel(image, f"{condition} | {titles[condition]}", note, roi=roi_box)
        marks = [(gt["xyxy"], f"GT {gt['class']} {gt['status'].upper()}", gt["status"], True)
                 for gt in row["ground_truth"]]
        marks.extend((pred["xyxy"], pred["box_id"].rsplit(":", 1)[1], pred["disposition"], False)
                     for pred in row["predictions"])
        draw_marks(panel, marks)
        panels[condition] = add_legend(panel, legend_rows[condition], row["predictions"])
    write_jpg(path, np.vstack((np.hstack((add_legend(original, legend_rows["A"], []), panels["A"], panels["B"])),
                               np.hstack((add_legend(reference, legend_rows["C"], []), panels["C"], panels["D"])))))


def comparison_row(condition: dict, inference: dict, effect: dict) -> dict:
    d20, counts = condition["classes"]["D20"], condition["dispositions"]
    applied = condition["roi_b"]
    removed = effect["removed_prediction_ids"]
    return {
        **{key: condition[key] for key in ("condition", "model", "roi_b", "confidence", "image_count", "prediction_count")},
        **{name: condition["classes"][name]["predictions"] for name in CLASSES},
        **{f"D20_{key}": d20[key] for key in ("gt", "tp", "fn", "recall")},
        "D40_recall": condition["classes"]["D40"]["recall"],
        **{key: counts[key] for key in ("background_fp", "uncertain", "review")},
        **{key: condition[key] for key in ("background_image_count", "background_images_with_fp",
                                           "background_fp_per_image", "confusion_prediction_count")},
        "roi_reference_count": effect["before_count"], "roi_retained_count": condition["prediction_count"],
        "roi_removed_count": effect["removed_count"] if applied else 0,
        "roi_boundary_count_before": len(effect["boundary_prediction_ids"]),
        **{f"roi_removed_{key}": len(values) if applied else 0 for key, values in removed.items()},
        "roi_gt_lost": len(effect["gt_lost"]) if applied else 0,
        "roi_gt_rematched": len(effect["gt_rematched"]) if applied else 0,
        "inference_ms_per_image": inference["timing_mean_ms_per_image"]["inference"],
        "roi_filter_ms": effect["roi_filter_ms"] if applied else None,
    }


def write_evaluation(directory: Path, frames: tuple[EvaluationImage, ...], images: dict[str, np.ndarray],
                     raw_files: dict[str, Path]) -> None:
    records = {name: json.loads(path.read_bytes()) for name, path in raw_files.items()}
    by_model = {
        name: {row["image_id"]: tuple(IdentifiedDetection(pred["class_id"], tuple(pred["xyxy"]),
                                                        pred["confidence"], box_id=pred["box_id"])
                                     for pred in row["predictions"]) for row in record["frames"]}
        for name, record in records.items()
    }
    cameras = sorted({frame.source_video for frame in frames if frame.image_id in images})
    summary = {"inference": {name: {**{key: value for key, value in record.items() if key != "frames"},
                                    "prediction_file": raw_files[name].name, "prediction_sha256": sha256_file(raw_files[name])}
                             for name, record in records.items()}, "conditions": [], "roi_effects": []}
    ground_truth, diagnostics, reviews, csv_rows = {}, {}, {}, []
    gallery = directory / "comparisons"
    for confidence in CONFIDENCES:
        visuals = {}
        for name, (off, on) in CONDITIONS.items():
            before, after, effect = evaluate_pair(frames, by_model[name], confidence, ROI_B)
            summary["roi_effects"].append({"model": name, "confidence": confidence,
                                           "conditions": [off, on], **effect})
            for code, applied, rows in ((off, False, before), (on, True, after)):
                key = f"{code}_{confidence:.2f}"
                condition = {"condition": code, "model": name, "roi_b": applied, "confidence": confidence,
                             **summarize(rows), "roi_filter_ms": effect["roi_filter_ms"] if applied else None,
                             "by_video": {camera: summarize([row for row in rows if row["source_video"] == camera])
                                          for camera in cameras}}
                summary["conditions"].append(condition)
                csv_rows.append(comparison_row(condition, records[name], effect))
                ground_truth[key] = [{k: v for k, v in row.items() if k != "predictions"} for row in rows]
                diagnostics[key] = [{k: v for k, v in row.items() if k != "ground_truth"} for row in rows]
                reviews[key] = {status: [{"image_id": row["image_id"], "revision": row["revision"], **pred}
                                         for row in rows for pred in row["predictions"] if pred["disposition"] == status]
                                for status in ("uncertain", "review")}
                visuals[code] = {row["image_id"]: row for row in rows}

        gallery_path = gallery / f"conf_{confidence:.2f}"
        gallery_path.mkdir(parents=True)
        for frame in frames:
            if frame.image_id in images:
                write_comparison(gallery_path / f"{frame.image_id}.jpg", images[frame.image_id], frame, confidence,
                                 {code: rows[frame.image_id] for code, rows in visuals.items()})

    with (directory / "comparison.csv").open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(csv_rows[0]))
        writer.writeheader()
        writer.writerows({key: "N/A" if value is None else value for key, value in row.items()} for row in csv_rows)
    _write_json(directory / "gt_matches.json", ground_truth)
    _write_json(directory / "prediction_diagnostics.json", diagnostics)
    _write_json(directory / "review_predictions.json", reviews)
    _write_json(directory / "summary.json", summary)


def run_evaluation(run_name: str) -> Path:
    output = OUTPUT_ROOT / checked_name(run_name)
    if output.exists():
        raise FileExistsError(f"같은 실행 이름의 결과가 있습니다. {output}")
    if not OUTPUT_ROOT.resolve().is_relative_to(PROJECT):
        raise ValueError(f"프로젝트 외부에는 평가 결과를 저장할 수 없습니다. {OUTPUT_ROOT}")
    frames = read_release(RELEASE)
    active = tuple(frame for frame in frames if frame.scope != "excluded")
    images = {frame.image_id: read_frame(frame) for frame in active}
    for name, path in MODEL_PATHS.items():
        checked_bytes(path, MODEL_HASHES[name])

    import torch

    environment = runtime_info(torch)
    models, weights = {}, {}
    for name, path in MODEL_PATHS.items():
        start = perf_counter()
        model, digest = _load_model(path)
        load_ms = (perf_counter() - start) * 1000
        if digest != MODEL_HASHES[name] or model.names != dict(enumerate(CLASSES)):
            raise ValueError(f"가중치 SHA-256 또는 클래스 매핑 불일치: {path}")
        models[name] = model
        weights[name] = {"path": path.relative_to(PROJECT).as_posix(), "sha256": digest, "classes": model.names,
                         "checkpoint_load_and_hash_ms": load_ms}

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    with staging_directory(OUTPUT_ROOT) as staging:
        raw_files = {}
        for name, model in models.items():
            record = infer(name, model, active, images, torch)
            raw_files[name] = staging / f"raw_{name}_predictions.json"
            _write_json(raw_files[name], {"weights": weights[name], **record})
            print(f"{name}: {len(record['frames'])}장, 예측 {sum(len(row['predictions']) for row in record['frames'])}개",
                  flush=True)
        _write_json(staging / "inputs.json", {
            "release_path": RELEASE.relative_to(PROJECT).as_posix(), "release_hashes": RELEASE_HASHES,
            "images": [frame_record(frame) for frame in frames], "inference_order": list(images),
            "models": weights, "environment": environment, "options": OPTIONS, "source_resolution": SIZE,
            "match_iou_inclusive": MATCH_IOU, "uncertain_fraction_inclusive": UNCERTAIN_COVERAGE,
            "confidence_thresholds": CONFIDENCES, "roi_b_vertices": ROI_B.vertices,
            "confidence_filter_source": "same saved post-NMS predictions at conf 0.05",
            "timing_scope": {
                "checkpoint_load_and_hash_ms": "checkpoint file SHA-256 and YOLO load",
                "backend_setup_ms": "predictor creation and model device setup/fuse, CUDA synchronized",
                "warmup_ms": "synthetic tensor creation and Ultralytics forward/NMS warmup, CUDA synchronized",
                "preprocess/inference/postprocess": "Ultralytics CUDA-synchronized per-image profiling; postprocess includes NMS and rescale",
                "prediction_wall": "CUDA-synchronized prediction calls on already-decoded frames, excludes box export",
                "roi_filter_ms": "CPU center/boundary classification and selection; excludes score filter, matching and I/O",
            },
        })
        write_evaluation(staging, frames, images, raw_files)
        if output.exists():
            raise FileExistsError(f"같은 실행 이름의 결과가 있습니다. {output}")
        staging.rename(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", default=datetime.now(UTC).strftime("part533_gt_v1_%Y%m%dT%H%M%SZ"),
                        help="기존 결과와 겹치지 않는 실행 이름. 생략하면 UTC 시각을 사용합니다.")
    args = parser.parse_args()
    try:
        with ultralytics_environment():
            output = run_evaluation(args.run_name)
    except (OSError, ValueError, RuntimeError, cv2.error, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")
    print(output)


if __name__ == "__main__":
    main()
