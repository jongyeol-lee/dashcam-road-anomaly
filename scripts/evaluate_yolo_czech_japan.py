"""두 best.pt를 같은 두 Validation에서 평가하고 객체 단위 오류 변화를 저장한다."""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import train_yolo_czech_japan as train
from scripts.yolo_improvement_01 import (
    baseline_state, compare_validation, dataset_digest, directory_digests, training_differences,
)
from road_anomaly.yolo_evaluation import (
    CASE_CONFIDENCE, CLASSES, MATCH_IOU, Detection, evaluate_best, match_boxes, render_panels,
)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def matched(truth, predictions):
    pairs, _, extras = match_boxes(truth, predictions)
    correct = {i for i, _, _, wrong in pairs if not wrong}
    wrong_class = [(i, j) for i, j, _, wrong in pairs if wrong]
    false_positives = sorted(extras + [j for _, j in wrong_class])
    return correct, wrong_class, false_positives


def compare_objects(truth, old, new):
    old_tp, old_confused, old_fp = matched(truth, old)
    new_tp, new_confused, new_fp = matched(truth, new)
    events = []
    for i, box in enumerate(truth):
        kind = ("both_tp" if i in old_tp else "gained_tp") if i in new_tp else (
            "lost_tp" if i in old_tp else "both_missed")
        events.append({"kind": kind, "class": CLASSES[box.class_id], "gt_index": i})
    for model, confused, preds in (("baseline", old_confused, old), ("mixed", new_confused, new)):
        for i, j in confused:
            events.append({"kind": "confusion", "model": model, "class": CLASSES[truth[i].class_id],
                           "predicted": CLASSES[preds[j].class_id], "gt_index": i, "prediction_index": j})
    # 두 모델의 FP 중 같은 클래스·위치에 해당하는 예측만 공통 오탐으로 센다.
    overlaps, _, _ = match_boxes([old[j] for j in old_fp], [new[j] for j in new_fp])
    for i, j, iou, wrong in overlaps:
        if not wrong:
            events.append({"kind": "common_fp", "class": CLASSES[old[old_fp[i]].class_id],
                           "baseline_index": old_fp[i], "mixed_index": new_fp[j], "iou": iou})
    if not truth:
        for model, predictions in (("baseline", old), ("mixed", new)):
            for j, box in enumerate(predictions):
                events.append({"kind": "background_fp", "model": model, "class": CLASSES[box.class_id],
                               "prediction_index": j})
    return events


def paired_cases(folder, pairs):
    old, new = (read(folder / model / "frames.json") for model in ("baseline", "mixed"))
    if old.keys() != new.keys() or set(old) != {image.name for image, _ in pairs}:
        raise ValueError("두 모델의 평가 이미지 불일치")
    events, candidates = [], defaultdict(list)
    counts = defaultdict(Counter)
    for image, _ in pairs:
        a, b = old[image.name], new[image.name]
        if a["truth"] != b["truth"]:
            raise ValueError(f"두 모델의 GT 불일치 {image}")
        truth, baseline, mixed = ([Detection(**d) for d in boxes] for boxes in
                                  (a["truth"], a["predictions"], b["predictions"]))
        for event in compare_objects(truth, baseline, mixed):
            row = {**event, "image": image.name}
            events.append(row)
            kind = row["kind"]
            key = row["class"]
            if kind == "confusion":
                key = f"{row['model']}:{key}->{row['predicted']}"
            elif kind == "background_fp":
                key = f"{row['model']}:{key}"
            counts[kind][key] += 1
            if kind != "both_tp" and (kind != "confusion" or {row["class"], row["predicted"]} == {"D20", "D40"}):
                candidates[kind].append((row, image, truth, baseline, mixed))
    gallery = folder / "paired_cases"
    gallery.mkdir()
    examples = []
    for kind, records in candidates.items():
        used = set()
        for row, image, truth, baseline, mixed in sorted(records, key=lambda r: (
            r[0]["class"] not in ("D10", "D40"), r[1].name
        )):
            if image in used:
                continue
            target = gallery / f"{kind}_{image.stem}.png"
            render_panels(image, (("GT", truth), ("Czech baseline", baseline), ("Czech + Japan", mixed)), target)
            examples.append({**row, "path": target.relative_to(folder).as_posix()})
            used.add(image)
            if len(used) == 3:
                break
    train.save(folder / "paired_events.json", events)
    result = {"confidence": CASE_CONFIDENCE, "matching_iou": MATCH_IOU, "counts": counts, "examples": examples}
    train.save(folder / "paired_summary.json", result)
    return result


def evaluate(name, evaluation_name):
    from ultralytics.utils import YAML

    run = train.OUTPUT / train.base.checked_name(name)
    root = run / train.base.checked_name(evaluation_name)
    if root.exists():
        raise FileExistsError(root)
    previous_metrics, baseline_hashes = baseline_state()
    datasets, hashes = train.check_inputs()
    preflight = read(run / "preflight.json")
    if preflight["protected_sha256"] != {str(p): value for p, value in hashes.items()}:
        raise ValueError("학습 전후 원본이 다릅니다.")
    checkpoints = {"baseline": train.BASE_RUN / "weights/best.pt", "mixed": run / "weights/best.pt"}
    checks = read(run / "training_checks.json")
    for stage, is_smoke in ((run / "smoke", True), (run, False)):
        train.check_training_record(read(stage / "training_summary.json"), read(stage / "training_checks.json"), is_smoke)
    if not checks["sources_preserved"] or train.digest(checkpoints["mixed"]) != checks["best_sha256"]:
        raise ValueError("검증된 본 학습 best.pt가 필요합니다.")
    hashes[checkpoints["mixed"]] = checks["best_sha256"]
    root.mkdir()
    report = {"training_option_differences": training_differences(YAML.load(train.BASE_RUN / "args.yaml"),
                                                                 YAML.load(run / "args.yaml"))}
    start = perf_counter()
    for country, dataset in (("czech", train.PILOT), ("japan", train.HOLDOUT)):
        pairs = datasets[dataset]["val"]
        folder = root / country
        folder.mkdir()
        metrics = {}
        cohort = dataset_digest(pairs)
        with train.base.stage_dataset(folder, [], pairs) as config:
            for model, weights in checkpoints.items():
                output = folder / model
                output.mkdir()
                metrics[model] = evaluate_best(weights, config, pairs, output, save_boxes=True)
                if Path(metrics[model]["weights"]) != weights or metrics[model]["images"] != len(pairs):
                    raise ValueError(f"평가 모델 또는 Validation 표본 불일치 {output}")
                train.save(output / "provenance.json", {"model": model, "weights_sha256": hashes[weights],
                           "country": country, "split": "val", "dataset": dataset, "val_sha256": cohort})
        report[country] = compare_validation(metrics["baseline"], metrics["mixed"])
        paired_cases(folder, pairs)
        if country == "czech":
            report["baseline_repeat"] = compare_validation(previous_metrics, metrics["baseline"])
    train.verify_saved(hashes)
    if directory_digests(train.BASE_RUN) != baseline_hashes:
        raise ValueError("기존 Baseline 산출물 변경 감지")
    report["wall_seconds"] = perf_counter() - start
    train.save(root / "comparison.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default=train.NAME)
    parser.add_argument("--evaluation-name", default="validation")
    opts = parser.parse_args()
    with train.base.ultralytics_environment():
        evaluate(opts.name, opts.evaluation_name)
