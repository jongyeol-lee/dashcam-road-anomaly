"""Part 5.4 혼합 모델의 전체 프레임 해상도 비교."""
import argparse
import csv
import gc
import json
import sys
from pathlib import Path
from statistics import mean, median

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import evaluate_dashcam_gt as gt
from road_anomaly.dashcam_evaluation import evaluate_image

SIZES = (640, 960, 1280)
REPEATS = 3
PREVIOUS = gt.OUTPUT_ROOT / "part533_gt_v1_review"
RAW_640_HASH = "9a38d67b1c28551b38b715da37a829137962619e0593a6080d1306cebb3fd739"


def predictions(raw):
    # 메모리의 xyxy 튜플과 저장 JSON의 배열을 같은 좌표 표현으로 대조한다.
    return [(row["image_id"], [{**p, "xyxy": tuple(p["xyxy"])} for p in row["predictions"]])
            for row in raw["frames"]]


def measure(size, frames, images, torch):
    trials = []
    primary = None
    for repeat in range(REPEATS):
        # 매회 새 백엔드를 로드하고 같은 형상의 합성 텐서로 워밍업한다.
        gc.collect()
        torch.cuda.empty_cache()
        model, digest = gt._load_model(gt.MODEL_PATHS["mixed"])
        if digest != gt.MODEL_HASHES["mixed"] or model.names != dict(enumerate(gt.CLASSES)):
            raise ValueError("혼합 모델 해시 또는 클래스 매핑 불일치")
        try:
            raw = gt.infer("mixed", model, frames, images, torch, imgsz=size, measure_resolution=True)
        except torch.cuda.OutOfMemoryError as error:
            return None, {"status": "cuda_oom", "repeat": repeat + 1, "error": str(error), "completed_trials": trials}
        except RuntimeError as error:
            return None, {"status": "inference_failed", "repeat": repeat + 1, "error": str(error), "completed_trials": trials}
        finally:
            del model
        if primary is None:
            primary = raw
        trials.append({"frames_ms": [row["timing_ms"] for row in raw["frames"]],
                       "mean_ms": raw["timing_mean_ms_per_image"], "warmup_ms": raw["warmup_ms"],
                       "peak_allocated_bytes": raw["peak_allocated_bytes"], "peak_reserved_bytes": raw["peak_reserved_bytes"],
                       "predictions_identical": predictions(raw) == predictions(primary)})
    timings = [row for trial in trials for row in trial["frames_ms"]]
    return primary, {"status": "ok", "trials": trials,
                     "mean_ms": {k: mean(row[k] for row in timings) for k in timings[0]},
                     "median_ms": {k: median(row[k] for row in timings) for k in timings[0]},
                     **{k: max(trial[k] for trial in trials) for k in ("peak_allocated_bytes", "peak_reserved_bytes")}}


def evaluate(frames, raw, confidence):
    rows = []
    for frame, saved in zip(frames, raw["frames"], strict=True):
        if frame.image_id != saved["image_id"]:
            raise ValueError("평가 프레임 순서 불일치")
        boxes = tuple(gt.IdentifiedDetection(p["class_id"], tuple(p["xyxy"]), p["confidence"], box_id=p["box_id"])
                      for p in saved["predictions"] if p["confidence"] >= confidence)
        rows.append(evaluate_image(frame, boxes))
    return rows


def hits(rows):
    return {g["box_id"] for row in rows for g in row["ground_truth"] if g["status"] == "tp"}


def gallery(directory, frames, images, confidence, results):
    directory.mkdir()
    for index, frame in enumerate(frames):
        image = images[frame.image_id]
        reference = gt.render_panel(image, f"{frame.image_id} | {frame.estimated_time_sec:.3f} s",
                                    f"Approved GT and hold regions | confidence >= {confidence:.2f}")
        marks = [(g.xyxy, gt.CLASSES[g.class_id], "gt", True) for g in frame.truth]
        marks.extend((r.xyxy, "Hold", "uncertain", False) for r in frame.uncertain_regions)
        gt.draw_marks(reference, marks)
        panels = [reference]
        legends = [[]]
        for size in SIZES:
            rows = results.get(size)
            if rows is None:
                panels.append(gt.render_panel(image, str(size), "Inference unavailable"))
                legends.append([])
                continue
            row = rows[index]
            boxes = row["predictions"]
            panel = gt.render_panel(image, f"{size} | Full frame", f"{len(boxes)} predictions")
            marks = [(g["xyxy"], f"D20 {g['status'].upper()}", g["status"], True) for g in row["ground_truth"]]
            marks.extend((p["xyxy"], p["box_id"].rsplit(":", 1)[1], p["disposition"], False) for p in boxes)
            gt.draw_marks(panel, marks)
            panels.append(panel)
            legends.append(boxes)
        bands = []
        for left in (0, 2):
            height = (max(map(len, legends[left:left + 2])) + 2) // 3
            bands.append(np.hstack([gt.add_legend(panels[i], height, legends[i]) for i in (left, left + 1)]))
        gt.write_jpg(directory / f"{frame.image_id}.jpg", np.vstack(bands))


def run(name):
    import torch

    output = gt.OUTPUT_ROOT / gt.checked_name(name)
    if output.exists():
        raise FileExistsError(output)
    frames = tuple(f for f in gt.read_release(gt.RELEASE) if f.scope != "excluded")
    images = {f.image_id: gt.read_frame(f) for f in frames}
    gt.checked_bytes(gt.MODEL_PATHS["mixed"], gt.MODEL_HASHES["mixed"])
    old = json.loads(gt.checked_bytes(PREVIOUS / "raw_mixed_predictions.json", RAW_640_HASH))
    environment = gt.runtime_info(torch)
    reports, profiles, raw_by_size, csv_rows = [], {}, {}, []
    with gt.staging_directory(gt.OUTPUT_ROOT) as staging:
        for size in SIZES:
            raw, profiles[size] = measure(size, frames, images, torch)
            if raw is not None:
                raw_by_size[size] = raw
                gt._write_json(staging / f"raw_{size}.json", raw)
            print(size, profiles[size]["status"], flush=True)
        reproducibility = None
        if 640 in raw_by_size:
            current = raw_by_size[640]
            reproducibility = {"same_predictions_and_order": predictions(current) == predictions(old),
                               "same_options": current["options"] == old["options"],
                               "previous_raw_sha256": RAW_640_HASH}
        for confidence in gt.CONFIDENCES:
            results = {size: evaluate(frames, raw, confidence) for size, raw in raw_by_size.items()}
            reference = hits(results[640]) if 640 in results else None
            for size in SIZES:
                row = {"imgsz": size, "confidence": confidence, "status": profiles[size]["status"]}
                if size in results:
                    details = results[size]
                    summary = gt.summarize(details)
                    detected = hits(details)
                    videos = sorted({f.source_video for f in frames})
                    reports.append({**row, **summary,
                                    "gained_gt": sorted(detected - reference) if reference is not None else None,
                                    "lost_gt": sorted(reference - detected) if reference is not None else None,
                                    "by_video": {v: gt.summarize([r for r in details if r["source_video"] == v]) for v in videos}})
                    gt._write_json(staging / f"diagnostics_{size}_{confidence:.2f}.json", details)
                    row.update(predictions=summary["prediction_count"], **summary["dispositions"],
                               fn=summary["classes"]["D20"]["fn"], recall=summary["classes"]["D20"]["recall"],
                               D40_recall="N/A", fp_images=summary["background_images_with_fp"],
                               confusions=summary["confusion_prediction_count"],
                               **{c: summary["classes"][c]["predictions"] for c in gt.CLASSES})
                else:
                    reports.append(dict(row))
                csv_rows.append(row)
            gallery(staging / f"comparisons_{confidence:.2f}", frames, images, confidence, results)
        with (staging / "comparison.csv").open("x", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(k for row in csv_rows for k in row)), restval="N/A")
            writer.writeheader()
            writer.writerows(csv_rows)
        gt._write_json(staging / "summary.json", {"conditions": reports, "profiles": profiles, "previous_640": reproducibility})
        gt._write_json(staging / "inputs.json", {"environment": environment, "options_at_640": gt.OPTIONS,
                       "sizes": SIZES, "repeats": REPEATS, "weights": str(gt.MODEL_PATHS["mixed"]),
                       "weights_sha256": gt.MODEL_HASHES["mixed"], "release_hashes": gt.RELEASE_HASHES,
                       "inference_order": [gt.frame_record(f) for f in frames]})
        staging.rename(output)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", default="part54_resolution_v1")
    args = parser.parse_args()
    with gt.ultralytics_environment():
        print(run(args.run_name))

