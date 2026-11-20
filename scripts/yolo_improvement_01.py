import argparse
import json
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.train_yolo_baseline import (
    DATA_YAML, OUTPUTS, TRAIN_OPTIONS, WEIGHTS, checked_name, load_pretrained, read_dataset, runtime_info,
    stage_dataset, train_model, ultralytics_environment,
)
from road_anomaly.rdd2022 import CLASSES
from road_anomaly.yolo_error_analysis import collect_frames, save_cases, summarize_thresholds
from road_anomaly.yolo_evaluation import METRICS, VAL_OPTIONS, evaluate_best


BASELINE = OUTPUTS / "yolo_baseline/20261119_yolo11n_640_b4_s42"
BASELINE_SHA256 = "40f0b6af12b8a33d83119138251ae345ee2ac50df5a3ae0ec81137d781b63342"
ANALYSIS_NAME = "yolo11n_czech_v2"
EXPERIMENT_NAME = "20261119_cls_pw025_640_b4_s42"
CLASS_WEIGHT_POWER = 0.25


def directory_digests(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def baseline_state() -> tuple[dict, dict[str, str]]:
    digests = directory_digests(BASELINE)
    required = {"weights/best.pt", "weights/last.pt", "results.csv", "args.yaml", "training_summary.json",
                "validation/metrics.json", "validation/qualitative.json", "validation/confusion_matrix.png"}
    if missing := required - digests.keys():
        raise FileNotFoundError(f"Part 3 산출물이 누락됐습니다. {sorted(missing)} ({BASELINE})")
    if digests["weights/best.pt"] != BASELINE_SHA256:
        raise ValueError(f"Part 3 best.pt SHA-256이 보고서와 다릅니다. {BASELINE}")
    metrics = json.loads((BASELINE / "validation/metrics.json").read_text(encoding="utf-8"))
    if (metrics["options"] != VAL_OPTIONS or metrics["images"] != 283
            or Path(metrics["weights"]).resolve() != (BASELINE / "weights/best.pt").resolve()):
        raise ValueError("Part 3 Validation 평가 조건이 현재 비교 조건과 다릅니다.")
    return metrics, digests


def output_path(category: str, name: str) -> Path:
    root = OUTPUTS / category / checked_name(name)
    if not root.resolve().is_relative_to(PROJECT_ROOT / "outputs"):
        raise ValueError(f"결과 경로가 outputs 밖입니다. {root}")
    return root


def write_json(path: Path, data: dict) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def dataset_digest(pairs: list[tuple[Path, Path]]) -> str:
    digest = sha256()
    for image, label in pairs:
        for path in (image, label):
            digest.update(path.name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def analyze(name: str) -> None:
    baseline, digests = baseline_state()
    pairs = read_dataset(DATA_YAML, ("val",))["val"]
    val_sha = dataset_digest(pairs)
    output = output_path("error_analysis", name)
    output.mkdir(parents=True)
    checkpoint = BASELINE / "weights/best.pt"
    runtime = runtime_info()
    frames = collect_frames(checkpoint, pairs)
    analysis, candidates = summarize_thresholds(frames)
    repeated = collect_frames(checkpoint, pairs)
    replay, replay_cases = summarize_thresholds(repeated)
    if analysis != replay or candidates != replay_cases:
        raise RuntimeError("같은 모델의 반복 추론에서 confidence 분석 또는 매칭이 다릅니다.")
    if digests != directory_digests(BASELINE) or val_sha != dataset_digest(pairs):
        raise RuntimeError("분석 중 Baseline 산출물 또는 Validation 입력이 변경됐습니다.")
    analysis.update({"dataset": str(DATA_YAML), "validation_sha256": val_sha, "baseline_files": digests,
                     "runtime": runtime, "baseline_metrics": baseline, "identical_repeat_predictions": repeated == frames,
                     "reproduced_threshold_analysis": True, "cases": save_cases(frames, candidates, output)})
    write_json(output / "threshold_analysis.json", analysis)
    print(f"Validation {len(frames)}장 분석 | 대표 사례 {len(analysis['cases'])}장 | {output}")


def saved_analysis(name: str, digests: dict[str, str], val_digest: str) -> dict:
    path = output_path("error_analysis", name) / "threshold_analysis.json"
    analysis = json.loads(path.read_text(encoding="utf-8"))
    if (analysis["validation_sha256"] != val_digest or analysis["baseline_files"] != digests
            or not analysis["reproduced_threshold_analysis"]):
        raise ValueError(f"분석 때의 Validation 및 Baseline 산출물과 일치해야 합니다. {path}")
    return analysis


def training_differences(reference: dict, candidate: dict) -> dict:
    paths = {"project", "name", "save_dir", "data"}
    return {key: {"baseline": reference.get(key), "improvement": candidate.get(key)}
            for key in sorted((reference.keys() | candidate.keys()) - paths)
            if reference.get(key) != candidate.get(key)}


def train(name: str, analysis_name: str) -> None:
    from ultralytics.cfg import DEFAULT_CFG_DICT
    from ultralytics.utils import YAML

    _, baseline_digests = baseline_state()
    baseline_args = YAML.load(BASELINE / "args.yaml")
    expected = {**TRAIN_OPTIONS, "epochs": 30, "cls_pw": 0.0}
    expected["device"] = str(expected["device"])
    if any(baseline_args.get(key) != value for key, value in expected.items()) or DEFAULT_CFG_DICT["cls_pw"] != 0.0:
        raise ValueError("현재 학습 기본 설정과 Part 3 설정을 비교할 수 없습니다.")
    data = read_dataset(DATA_YAML, ("train", "val"))
    train_digest, val_digest = (dataset_digest(data[split]) for split in ("train", "val"))
    saved_analysis(analysis_name, baseline_digests, val_digest)
    classes = Counter(int(row.split()[0]) for _, label in data["train"]
                      for row in label.read_text(encoding="utf-8").splitlines())
    runtime = runtime_info()
    model = load_pretrained(WEIGHTS)
    run_dir = output_path("yolo_improvement", name)
    run_dir.mkdir(parents=True)
    config = {
        "baseline_dir": str(BASELINE), "baseline_best_sha256": BASELINE_SHA256,
        "analysis_dir": str(output_path("error_analysis", analysis_name)), "dataset": str(DATA_YAML),
        "train_sha256": train_digest, "validation_sha256": val_digest,
        "data_yaml_sha256": sha256(DATA_YAML.read_bytes()).hexdigest(),
        "train_objects": {label: classes[index] for index, label in enumerate(CLASSES)},
        "changed_training_option": {"cls_pw": {"baseline": 0.0, "improvement": CLASS_WEIGHT_POWER}},
    }
    write_json(run_dir / "experiment.json", config)
    result = train_model(model, data, DATA_YAML, WEIGHTS, run_dir, False, runtime, cls_pw=CLASS_WEIGHT_POWER)
    differences = training_differences(baseline_args, YAML.load(run_dir / "args.yaml"))
    if differences != config["changed_training_option"]:
        raise RuntimeError(f"실제 학습 설정 차이가 계획과 다릅니다. {differences}")
    if (baseline_digests != directory_digests(BASELINE) or train_digest != dataset_digest(data["train"])
            or val_digest != dataset_digest(data["val"]) or config["data_yaml_sha256"] != sha256(DATA_YAML.read_bytes()).hexdigest()):
        raise RuntimeError("학습 중 Baseline 또는 데이터셋 파일이 변경됐습니다.")
    print(f"{result['completed_epochs']} epoch 완료 | 실제 cls_pw 설정 확인 | {run_dir}")


def compare_rows(baseline: dict, improvement: dict, keys: tuple[str, ...]) -> dict:
    rows = {}
    for key in keys:
        before, after = baseline[key], improvement[key]
        rows[key] = {"baseline": before, "improvement": after,
                     "delta": after - before if before is not None and after is not None else None}
    return rows


def compare_validation(baseline: dict, improvement: dict) -> dict:
    if baseline["options"] != improvement["options"] or baseline["images"] != improvement["images"]:
        raise ValueError("Validation 비교 설정이나 이미지 수가 다릅니다.")
    for category in CLASSES:
        if any(baseline["classes"][category][key] != improvement["classes"][category][key]
               for key in ("images", "instances")):
            raise ValueError(f"Validation의 {category} 정답 수가 다릅니다.")
    return {"overall": compare_rows(baseline["overall"], improvement["overall"], METRICS),
            "classes": {category: compare_rows(baseline["classes"][category], improvement["classes"][category], METRICS)
                        for category in CLASSES}}


def evaluate(name: str, analysis_name: str, evaluation_name: str) -> None:
    from ultralytics.utils import YAML

    baseline_metrics, baseline_digests = baseline_state()
    data = read_dataset(DATA_YAML, ("val",))
    val_digest = dataset_digest(data["val"])
    reference = saved_analysis(analysis_name, baseline_digests, val_digest)
    run_dir = output_path("yolo_improvement", name)
    training = json.loads((run_dir / "training_summary.json").read_text(encoding="utf-8"))
    config = json.loads((run_dir / "experiment.json").read_text(encoding="utf-8"))
    differences = training_differences(YAML.load(BASELINE / "args.yaml"), YAML.load(run_dir / "args.yaml"))
    if (config["validation_sha256"] != val_digest or training["options"]["cls_pw"] != CLASS_WEIGHT_POWER
            or differences != {"cls_pw": {"baseline": 0.0, "improvement": CLASS_WEIGHT_POWER}}):
        raise ValueError("분석 때의 Validation과 cls_pw만 변경한 완료된 실험이 필요합니다.")
    evaluation = run_dir / checked_name(evaluation_name)
    evaluation.mkdir()
    checkpoint = run_dir / "weights/best.pt"
    with stage_dataset(evaluation, [], data["val"]) as yaml_path:
        metrics = evaluate_best(checkpoint, yaml_path, data["val"], evaluation)
    frames = collect_frames(checkpoint, data["val"])
    analysis, _ = summarize_thresholds(frames)
    if any(analysis[key] != reference[key] for key in ("inference", "matching_iou", "localization_min_iou", "images")):
        raise ValueError("confidence 분석에서 사용한 설정이 일치하지 않습니다.")

    fixed_metrics = ("tp", "fp", "fn", "precision", "recall")
    thresholds = {}
    for level, counts in analysis["thresholds"].items():
        original = reference["thresholds"][level]
        thresholds[level] = {
            "overall": compare_rows(original["overall"], counts["overall"], fixed_metrics),
            "classes": {label: compare_rows(original["classes"][label], counts["classes"][label], fixed_metrics)
                        for label in CLASSES},
        }
    baseline_training = json.loads((BASELINE / "training_summary.json").read_text(encoding="utf-8"))
    comparison = {
        "baseline_best_sha256": BASELINE_SHA256,
        "improvement_best_sha256": sha256(checkpoint.read_bytes()).hexdigest(),
        "validation_sha256": val_digest, "validation_options": VAL_OPTIONS, "changed_training_option": differences,
        "validation": compare_validation(baseline_metrics, metrics), "operating_thresholds": thresholds,
        "training_costs": compare_rows(baseline_training, training, (
            "completed_epochs", "training_wall_seconds", "peak_cuda_allocated_bytes", "peak_cuda_reserved_bytes",
        )),
        "validation_speed_ms_per_image": compare_rows(baseline_metrics["speed_ms_per_image"],
                                                     metrics["speed_ms_per_image"], ("preprocess", "inference", "postprocess")),
    }
    if baseline_digests != directory_digests(BASELINE) or val_digest != dataset_digest(data["val"]):
        raise RuntimeError("평가 중 Baseline 또는 데이터셋 파일이 변경됐습니다.")
    write_json(evaluation / "threshold_analysis.json", analysis)
    write_json(evaluation / "comparison.json", comparison)
    print(f"Validation {len(frames)}장 평가 | 비교 결과 {evaluation / 'comparison.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="YOLO11n Baseline 오류 분석과 클래스 가중치 개선 실험")
    parser.add_argument("stage", choices=("analyze", "train", "evaluate"))
    parser.add_argument("--name", type=checked_name, help="새 분석 또는 학습 결과 폴더 이름")
    parser.add_argument("--analysis-name", type=checked_name, default=ANALYSIS_NAME, help="완료된 분석 폴더 이름")
    parser.add_argument("--evaluation-name", type=checked_name, default="validation", help="새 평가 결과 폴더 이름")
    args = parser.parse_args()
    with ultralytics_environment():
        if args.stage == "analyze":
            analyze(args.name or ANALYSIS_NAME)
        elif args.stage == "train":
            train(args.name or EXPERIMENT_NAME, args.analysis_name)
        else:
            evaluate(args.name or EXPERIMENT_NAME, args.analysis_name, args.evaluation_name)


if __name__ == "__main__":
    main()
