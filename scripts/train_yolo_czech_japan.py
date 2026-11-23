"""Part 5.2-4의 고정 분할을 검증하고 COCO 초기값으로 스모크 및 본 학습을 실행한다."""
import argparse
import csv
import json
import math
import shutil
import sys
from collections import Counter, defaultdict
from hashlib import file_digest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import train_yolo_baseline as base
from scripts.prepare_rdd2022_czech_japan import HOLDOUT, PILOT, _split_files

YOLO = ROOT / "data/yolo"
AUDIT = ROOT / "data/processed" / PILOT
OUTPUT = ROOT / "outputs/yolo_multicountry"
BASE_RUN = base.OUTPUTS / "yolo_baseline/20261119_yolo11n_640_b4_s42"
NAME = "czech_japan_pilot_v1_yolo11n_640_b4_s42_e30"
MANIFEST_SHA = "cee2def5a99aa96493c6f50919109ef2378e94ac8d95236ceef854adf29dd077"
COUNTS = {PILOT: {"train": 4526, "val": 283}, HOLDOUT: {"val": 869}}


def digest(path):
    with path.open("rb") as handle:
        return file_digest(handle, "sha256").hexdigest()


def save(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)


def check_groups(rows):
    splits = defaultdict(set)
    for row in rows:
        if row["split"]:
            splits[row["group_id"]].add(row["split"])
    if any(len(values) > 1 for values in splits.values()):
        raise ValueError("분할 간 유사 그룹 교차")


def check_inputs():
    from ultralytics.utils import YAML

    manifest = AUDIT / "split_manifest.csv"
    if digest(manifest) != MANIFEST_SHA:
        raise ValueError("Part 5.2-3 고정 매니페스트 해시 불일치")
    with manifest.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    check_groups(rows)
    baseline_val = _split_files(base.DATA_YAML.parent, "val")
    snapshots = {path: digest(path) for path in (
        base.WEIGHTS, BASE_RUN / "weights/best.pt", BASE_RUN / "weights/last.pt",
        BASE_RUN / "args.yaml", BASE_RUN / "results.csv", BASE_RUN / "training_summary.json",
        manifest, AUDIT / "selection_manifest.csv", AUDIT / "duplicate_groups.csv", AUDIT / "exclusion_report.csv",
        base.DATA_YAML,
    )}
    datasets = {}
    for name, counts in COUNTS.items():
        root = YOLO / name
        config = root / "data.yaml"
        expected = {"train": "images/train" if name == PILOT else None, "val": "images/val",
                    "test": "images/test", "names": dict(enumerate(base.CLASSES))}
        if YAML.load(config) != expected:
            raise ValueError(f"분할 경로 또는 클래스 매핑 불일치 {config}")
        snapshots[config] = digest(config)
        datasets[name] = {}
        for split, count in counts.items():
            pairs = list(_split_files(root, split).values())
            records = {row["output_image"]: row for row in rows if row["dataset"] == name and row["split"] == split}
            if len(pairs) != count or len(records) != count:
                raise ValueError(f"이미지 수 불일치 {name}/{split}")
            if name == PILOT and split == "val" and baseline_val.keys() != {
                image.stem.casefold() for image, _ in pairs
            }:
                raise ValueError("Czech v2와 Pilot의 Validation 파일 목록 불일치")
            for image, label in pairs:
                key = image.relative_to(root).as_posix()
                row = records[key]
                if row["output_label"] != label.relative_to(root).as_posix():
                    raise ValueError(f"라벨 경로 불일치 {image}")
                for path, field in ((image, "jpeg_sha256"), (label, "label_sha256")):
                    snapshots[path] = digest(path)
                    if snapshots[path] != row[field]:
                        raise ValueError(f"발행된 데이터 해시 불일치 {path}")
                    if row["country"] == "Czech":
                        original = base.DATA_YAML.parent / path.relative_to(root)
                        snapshots[original] = digest(original)
                        if snapshots[original] != snapshots[path]:
                            raise ValueError(f"Czech v2 원본 불일치 {original}")
            datasets[name][split] = pairs
    return datasets, snapshots


def verify_saved(snapshots):
    for path, expected in snapshots.items():
        if digest(path) != expected:
            raise ValueError(f"원본 변경 감지 {path}")


def check_training_record(summary, measured, smoke):
    completed = summary["completed_epochs"]
    expected = math.ceil(summary["training_images"] / base.TRAIN_OPTIONS["batch"]) * completed
    if (summary["stage"] != ("smoke" if smoke else "train")
            or not 1 <= completed <= summary["options"]["epochs"] or (smoke and completed != 1)
            or summary["weights_sha256"] != base.WEIGHTS_SHA256
            or not summary["amp_used"] or summary["batch_used"] != base.TRAIN_OPTIONS["batch"]
            or measured["batches"] != expected or measured["optimizer_steps"] < 1
            or measured["best_epoch"] not in range(1, completed + 1)):
        raise ValueError("학습 기록의 epoch, 체크포인트 또는 실제 실행 조건이 다릅니다.")


def run_training(name, epochs):
    run = OUTPUT / base.checked_name(name)
    if run.exists():
        raise FileExistsError(run)
    datasets, snapshots = check_inputs()
    data = datasets[PILOT]
    scratch_bytes = sum(path.stat().st_size for pairs in data.values() for pair in pairs for path in pair)
    free = shutil.disk_usage(ROOT).free
    if free < scratch_bytes + 512 * 1024**2:
        raise OSError("학습용 스테이징 공간 부족")
    runtime = base.runtime_info()
    run.mkdir(parents=True)
    try:
        save(run / "preflight.json", {"runtime": runtime, "manifest_sha256": MANIFEST_SHA, "free_bytes": free,
             "staging_bytes": scratch_bytes, "protected_sha256": {str(p): h for p, h in snapshots.items()}})
        for smoke in (True, False):
            dest = run / "smoke" if smoke else run
            if smoke:
                dest.mkdir()
            sample = base.select_train(data["train"], smoke)
            countries = Counter(image.name.split("_")[0] for image, _ in sample)
            if set(countries) != {"Czech", "Japan"}:
                raise ValueError("학습 표본에 두 국가가 모두 필요합니다.")
            model = base.load_pretrained(base.WEIGHTS)
            measured = {"batches": 0, "optimizer_steps": 0, "best_epoch": None}

            def count_step(*_):
                measured["optimizer_steps"] += 1

            def start(trainer):
                measured["optimizer_groups"] = [
                    {k: group[k] for k in ("lr", "initial_lr", "betas", "momentum", "weight_decay") if k in group}
                    for group in trainer.optimizer.param_groups
                ]
                trainer.optimizer.register_step_post_hook(count_step)

            def batch_done(_):
                measured["batches"] += 1

            def checkpoint(trainer):
                if trainer.fitness == trainer.best_fitness:
                    measured["best_epoch"] = trainer.epoch + 1

            model.add_callback("on_train_start", start)
            model.add_callback("on_train_batch_end", batch_done)
            model.add_callback("on_model_save", checkpoint)
            summary = base.train_model(model, data, YOLO / PILOT / "data.yaml", base.WEIGHTS, dest, smoke,
                                       runtime, split_counts=COUNTS[PILOT], max_epochs=epochs)
            check_training_record(summary, measured, smoke)
            verify_saved(snapshots)
            save(dest / "training_checks.json", {**measured, "countries": countries, "sources_preserved": True,
                 "best_sha256": digest(dest / "weights/best.pt"), "best_bytes": (dest / "weights/best.pt").stat().st_size})
            del model
    except (Exception, KeyboardInterrupt) as error:
        save(run / "failure.json", {"type": type(error).__name__, "error": str(error)})
        verify_saved(snapshots)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default=NAME, type=base.checked_name)
    parser.add_argument("--epochs", type=int, choices=(15, 30), default=30)
    opts = parser.parse_args()
    if opts.epochs == 15 and opts.name == NAME:
        parser.error("15 epoch 보조 실험에는 별도 이름을 지정하세요.")
    with base.ultralytics_environment():
        run_training(opts.name, opts.epochs)
