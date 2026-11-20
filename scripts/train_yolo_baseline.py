import argparse
import csv
import json
import logging
import math
import ntpath
import os
import platform
import random
import re
import shutil
import sys
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = PROJECT_ROOT / "outputs"
DATA_YAML = PROJECT_ROOT / "data/yolo/rdd2022_czech_v2/data.yaml"
WEIGHTS = OUTPUTS / "yolo11n.pt"
WEIGHTS_URL = "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt"
WEIGHTS_SHA256 = "0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1"
COUNTS = {"train": 2263, "val": 283, "test": 283}
SMOKE_IMAGES = 113
TRAIN_OPTIONS = {
    "imgsz": 640, "batch": 4, "device": 0, "seed": 42, "workers": 2,
    "amp": True, "cache": False, "patience": 10, "optimizer": "auto",
    "val": True, "split": "val", "plots": True, "deterministic": True, "save": True,
}

sys.path.insert(0, str(PROJECT_ROOT / "src"))
from road_anomaly.rdd2022 import CLASSES, JPEG_SUFFIXES


def read_dataset(data_path: Path, splits: tuple[str, ...] = tuple(COUNTS)) -> dict[str, list[tuple[Path, Path]]]:
    """고정된 Czech v2의 YAML, 분할별 이미지와 라벨의 일대일 대응을 확인한다."""
    from ultralytics.utils import YAML

    if data_path.parent.name != "rdd2022_czech_v2" or data_path.name != "data.yaml":
        raise ValueError(f"rdd2022_czech_v2/data.yaml을 지정해야 합니다. {data_path}")
    if not data_path.is_file():
        raise FileNotFoundError(data_path)
    data = YAML.load(data_path)
    expected_paths = {split: f"images/{split}" for split in COUNTS}
    if data != {**expected_paths, "names": dict(enumerate(CLASSES))}:
        raise ValueError(f"Czech v2의 분할 경로 또는 클래스 매핑이 다릅니다. {data_path}")
    pairs = {}
    for split in splits:
        count = COUNTS[split]
        images = sorted(path for path in (data_path.parent / data[split]).iterdir()
                        if path.is_file() and path.suffix.lower() in JPEG_SUFFIXES)
        labels = {path for path in (data_path.parent / "labels" / split).glob("*.txt") if path.is_file()}
        matched = [(image, data_path.parent / "labels" / split / image.with_suffix(".txt").name)
                   for image in images]
        if len(images) != count or len(labels) != count or {path for _, path in matched} != labels:
            raise ValueError(f"{split} 이미지/라벨 경로나 수량이 다릅니다. 이미지 {len(images)}, 라벨 {len(labels)}, 기대 {count}")
        pairs[split] = matched
    return pairs


@contextmanager
def ultralytics_environment():
    with TemporaryDirectory(prefix="road-anomaly-ultralytics-") as config:
        os.environ.update(YOLO_CONFIG_DIR=config, MPLCONFIGDIR=config, YOLO_OFFLINE="true", YOLO_AUTOINSTALL="false")
        from ultralytics.utils import USER_CONFIG_DIR

        system_font = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts/arial.ttf"
        if system_font.is_file():
            shutil.copyfile(system_font, USER_CONFIG_DIR / "Arial.ttf")
        yield


def runtime_info() -> dict:
    import torch
    import ultralytics
    from ultralytics.cfg import DEFAULT_CFG_DICT

    missing = (TRAIN_OPTIONS.keys() | {"epochs"}) - DEFAULT_CFG_DICT.keys()
    if missing:
        raise RuntimeError(f"현재 Ultralytics에서 지원하지 않는 옵션입니다. {sorted(missing)}")
    if not torch.cuda.is_available():
        raise RuntimeError("프로젝트 .venv에서 CUDA를 사용할 수 없습니다.")
    device = torch.device("cuda:0")
    x = torch.arange(1, 4, device=device, dtype=torch.float32, requires_grad=True)
    x.square().sum().backward()
    torch.cuda.synchronize(device)
    if x.grad.tolist() != [2.0, 4.0, 6.0]:
        raise RuntimeError("CUDA 역전파 검증에 실패했습니다.")
    free, total = torch.cuda.mem_get_info(device)
    return {
        "os": platform.platform(), "python": platform.python_version(),
        "torch": torch.__version__, "cuda_build": torch.version.cuda, "ultralytics": ultralytics.__version__,
        "gpu": torch.cuda.get_device_name(device), "free_vram_bytes": free, "total_vram_bytes": total,
    }


def load_pretrained(path: Path):
    from ultralytics import YOLO

    if not path.is_file():
        raise FileNotFoundError(f"공식 사전학습 가중치가 필요합니다. {path} ({WEIGHTS_URL})")
    if sha256(path.read_bytes()).hexdigest() != WEIGHTS_SHA256:
        raise ValueError(f"공식 YOLO11n COCO 가중치의 기록된 SHA-256과 다릅니다. {path}")
    model = YOLO(str(path), task="detect")
    if len(model.names) != 80:
        raise ValueError(f"COCO 탐지 모델의 클래스 수가 다릅니다. {path}")
    return model


def checked_name(name: str) -> str:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}", name) or ntpath.isreserved(name):
        raise ValueError("실험 이름에는 영문, 숫자, 밑줄, 하이픈을 사용할 수 있습니다.")
    return name


def run_path(stage: str, name: str) -> Path:
    folder = "yolo_smoke" if stage == "smoke" else "yolo_baseline"
    path = OUTPUTS / folder / checked_name(name)
    if not path.resolve().is_relative_to(PROJECT_ROOT / "outputs"):
        raise ValueError(f"실험 경로를 outputs 아래에 지정해야 합니다. {path}")
    return path


def select_train(pairs: list[tuple[Path, Path]], smoke: bool) -> list[tuple[Path, Path]]:
    if smoke:
        return sorted(random.Random(TRAIN_OPTIONS["seed"]).sample(pairs, SMOKE_IMAGES))
    return pairs


@contextmanager
def stage_dataset(run_dir: Path, train: list[tuple[Path, Path]], val: list[tuple[Path, Path]]):
    """Ultralytics의 라벨 스캔 캐시와 이미지 복구가 원본에 영향을 주지 않게 한다."""
    from ultralytics.utils import YAML

    with TemporaryDirectory(dir=run_dir, prefix="czech_v2_") as scratch:
        root = Path(scratch)
        for split, pairs in (("train", train), ("val", val)):
            images, labels = root / "images" / split, root / "labels" / split
            images.mkdir(parents=True)
            labels.mkdir(parents=True)
            for image, label in pairs:
                shutil.copyfile(image, images / image.name)
                shutil.copyfile(label, labels / label.name)
        config = root / "data.yaml"
        YAML.save(config, {"train": "images/train", "val": "images/val", "names": dict(enumerate(CLASSES))})
        yield config


def train_model(
    model, dataset: dict, data_path: Path, weights: Path, run_dir: Path, smoke: bool, runtime: dict, *,
    cls_pw: float | None = None,
) -> dict:
    import torch
    from ultralytics.utils import LOGGER

    epochs = 1 if smoke else 30
    train = select_train(dataset["train"], smoke)
    options = TRAIN_OPTIONS.copy()
    class_weights = []
    if cls_pw is not None:
        options["cls_pw"] = cls_pw

    def check_effective_settings(trainer) -> None:
        # Ultralytics가 AMP를 해제하거나 첫 epoch에서 배치를 자동 축소하면 별도 실험으로 다룬다.
        if trainer.batch_size != TRAIN_OPTIONS["batch"] or not trainer.amp:
            raise RuntimeError(f"요청 설정과 실제 설정이 다릅니다. batch={trainer.batch_size}, amp={trainer.amp}")
        if cls_pw is not None and not class_weights:
            weights_used = getattr(trainer.model, "class_weights", None)
            if trainer.args.cls_pw != cls_pw or weights_used is None:
                raise RuntimeError("클래스 가중치가 실제 분류 손실에 설정되지 않았습니다.")
            class_weights.extend(weights_used.detach().cpu().tolist())

    model.add_callback("on_pretrain_routine_end", check_effective_settings)
    model.add_callback("on_train_epoch_start", check_effective_settings)
    handler = logging.FileHandler(run_dir / "train.log", mode="x", encoding="utf-8")
    LOGGER.addHandler(handler)
    try:
        with stage_dataset(run_dir, train, dataset["val"]) as scratch_yaml:
            torch.cuda.reset_peak_memory_stats(0)
            start = perf_counter()
            try:
                model.train(data=str(scratch_yaml), epochs=epochs, project=str(run_dir.parent), name=run_dir.name,
                            exist_ok=True, **options)
                torch.cuda.synchronize(0)
                elapsed = perf_counter() - start
            finally:
                for attribute in ("train_loader", "test_loader"):
                    loader = getattr(model.trainer, attribute, None)
                    if loader is not None:
                        loader.close()
    except Exception:
        LOGGER.exception("YOLO 학습 실패")
        raise
    finally:
        LOGGER.removeHandler(handler)
        handler.close()

    log = run_dir / "results.csv"
    with log.open(encoding="utf-8", newline="") as handle:
        records = [{key.strip(): value for key, value in row.items()} for row in csv.DictReader(handle)]
    completed = len(records)
    if not 1 <= completed <= epochs or not all(math.isfinite(float(row[key])) for row in records
                                               for key in ("train/box_loss", "train/cls_loss", "train/dfl_loss")):
        raise RuntimeError(f"학습 로그의 epoch 또는 손실이 유효하지 않습니다. {log}")
    for name in ("best.pt", "last.pt"):
        checkpoint = run_dir / "weights" / name
        if not checkpoint.is_file() or not checkpoint.stat().st_size:
            raise FileNotFoundError(checkpoint)
    summary = {
        "stage": "smoke" if smoke else "train", "dataset": str(data_path), "split_counts": COUNTS,
        "training_images": len(train), "smoke_images": [image.name for image, _ in train] if smoke else [],
        "weights": str(weights), "weights_url": WEIGHTS_URL, "weights_sha256": WEIGHTS_SHA256,
        "runtime": runtime, "options": {**options, "epochs": epochs}, "completed_epochs": completed,
        "stop_reason": "epoch_limit" if completed == epochs else "early_stopping",
        "optimizer_used": type(model.trainer.optimizer).__name__,
        "amp_used": bool(model.trainer.amp), "batch_used": model.trainer.batch_size,
        "training_wall_seconds": elapsed, "peak_cuda_allocated_bytes": torch.cuda.max_memory_allocated(0),
        "peak_cuda_reserved_bytes": torch.cuda.max_memory_reserved(0),
    }
    if cls_pw is not None:
        summary["class_weights"] = dict(zip(CLASSES, class_weights, strict=True))
    with (run_dir / "training_summary.json").open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="RDD2022 Czech v2의 YOLO11n 스모크 테스트, 학습 및 Val 평가")
    parser.add_argument("stage", choices=("check", "smoke", "train", "evaluate"))
    parser.add_argument("--data", type=Path, default=DATA_YAML, help="rdd2022_czech_v2/data.yaml 위치")
    parser.add_argument("--weights", type=Path, default=WEIGHTS, help="공식 COCO yolo11n.pt 위치")
    parser.add_argument("--name", help="실험 폴더 이름")
    parser.add_argument("--smoke-name", help="본 학습에 앞서 성공한 스모크 실험 이름")
    parser.add_argument("--evaluation-name", type=checked_name, default="validation", help="Validation 결과 폴더 이름")
    args = parser.parse_args()
    if args.stage != "check" and not args.name:
        parser.error("check 이외에는 --name이 필요합니다.")
    if args.stage == "train" and not args.smoke_name:
        parser.error("train에는 --smoke-name이 필요합니다.")

    data_path = args.data.resolve()
    weights = args.weights.resolve()
    with ultralytics_environment():
        dataset = read_dataset(data_path)
        runtime = runtime_info()
        if args.stage == "check":
            model = load_pretrained(weights)
            sample = dataset["train"][0][0]
            prediction = model.predict(str(sample), device=0, imgsz=640, verbose=False, save=False)
            if len(prediction) != 1:
                raise RuntimeError(f"학습 이미지 로딩 검사에 실패했습니다. {sample}")
            print(json.dumps({"runtime": runtime, "data": str(data_path), "counts": COUNTS,
                              "classes": dict(enumerate(CLASSES)), "sample": str(sample), "weights": str(weights)},
                             ensure_ascii=False, indent=2))
            return
        run_dir = run_path(args.stage, args.name)
        if args.stage == "evaluate":
            from road_anomaly.yolo_evaluation import evaluate_best

            train_summary = json.loads((run_dir / "training_summary.json").read_text(encoding="utf-8"))
            if train_summary["stage"] != "train" or train_summary["dataset"] != str(data_path):
                raise ValueError("같은 Czech v2에서 완료된 본 학습 결과를 지정해야 합니다.")
            evaluation = run_dir / args.evaluation_name
            evaluation.mkdir()
            with stage_dataset(evaluation, [], dataset["val"]) as scratch_yaml:
                result = evaluate_best(run_dir / "weights/best.pt", scratch_yaml, dataset["val"], evaluation)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        if args.stage == "train":
            smoke = run_path("smoke", args.smoke_name) / "training_summary.json"
            report = json.loads(smoke.read_text(encoding="utf-8"))
            if (report["stage"], report["completed_epochs"], report["dataset"], report["weights_sha256"]) != (
                "smoke", 1, str(data_path), WEIGHTS_SHA256,
            ):
                raise ValueError(f"같은 데이터셋과 모델에서 1 epoch 스모크 테스트를 완료해야 합니다. {smoke}")
        model = load_pretrained(weights)
        run_dir.mkdir(parents=True)
        summary = train_model(model, dataset, data_path, weights, run_dir, args.stage == "smoke", runtime)
        print(f"{summary['completed_epochs']} epoch 완료 | 실험 기록 {run_dir / 'training_summary.json'}")


if __name__ == "__main__":
    main()
