import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import train_yolo_baseline as baseline
from src.road_anomaly.yolo_evaluation import Detection, match_boxes


class BaselineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = tempfile.TemporaryDirectory()
        cls.addClassCleanup(config.cleanup)
        env = patch.dict(os.environ, YOLO_CONFIG_DIR=config.name, MPLCONFIGDIR=config.name,
                         YOLO_OFFLINE="true", YOLO_AUTOINSTALL="false")
        env.start()
        cls.addClassCleanup(env.stop)

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def dataset_fixture(self) -> Path:
        root = self.root / "rdd2022_czech_v2"
        for split in baseline.COUNTS:
            images, labels = root / "images" / split, root / "labels" / split
            images.mkdir(parents=True)
            labels.mkdir(parents=True)
            (images / f"{split}.jpg").write_bytes(b"image")
            (labels / f"{split}.txt").write_text("0 0.5 0.5 0.25 0.25\n", encoding="utf-8")
        data = root / "data.yaml"
        data.write_text("train: images/train\nval: images/val\ntest: images/test\n"
                        "names:\n  0: D00\n  1: D10\n  2: D20\n  3: D40\n", encoding="utf-8")
        return data

    def test_dataset_path_classes_and_image_label_pairs(self) -> None:
        path = self.dataset_fixture()
        with patch.dict(baseline.COUNTS, train=1, val=1, test=1):
            self.assertEqual({split: len(pairs) for split, pairs in baseline.read_dataset(path).items()},
                             {"train": 1, "val": 1, "test": 1})
            label = path.parent / "labels/val/val.txt"
            label.rename(label.with_name("wrong.txt"))
            with self.assertRaisesRegex(ValueError, "val 이미지/라벨"):
                baseline.read_dataset(path)
        path.write_text(path.read_text(encoding="utf-8").replace("0: D00", "0: D40"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "클래스 매핑"):
            baseline.read_dataset(path)
        with self.assertRaisesRegex(ValueError, "rdd2022_czech_v2"):
            baseline.read_dataset(self.root / "rdd2022_czech/data.yaml")

    def test_staging_copies_only_train_and_val_and_protects_source_files(self) -> None:
        from ultralytics.utils import YAML

        path = self.dataset_fixture()
        with patch.dict(baseline.COUNTS, train=1, val=1, test=1):
            pairs = baseline.read_dataset(path)
        with baseline.stage_dataset(self.root, pairs["train"], pairs["val"]) as config:
            self.assertEqual(YAML.load(config), {"train": "images/train", "val": "images/val",
                                                "names": dict(enumerate(baseline.CLASSES))})
            self.assertFalse((config.parent / "images/test").exists())
            self.assertFalse((config.parent / "labels/test").exists())
            for split in ("train", "val"):
                source, label = pairs[split][0]
                staged = config.parent / "images" / split / source.name
                self.assertEqual(staged.read_bytes(), source.read_bytes())
                (config.parent / "labels" / split / label.name).write_bytes(b"")
                (config.parent / "labels" / f"{split}.cache").write_bytes(b"cache")
                self.assertGreater(label.stat().st_size, 0)
        self.assertFalse(config.parent.exists())
        self.assertFalse(list((path.parent / "labels").glob("*.cache")))

    def test_fixed_training_options_and_reproducible_smoke_subset(self) -> None:
        pairs = [(Path(f"{i:04d}.jpg"), Path(f"{i:04d}.txt")) for i in range(200)]
        first = baseline.select_train(pairs, smoke=True)
        self.assertEqual(first, baseline.select_train(pairs, smoke=True))
        self.assertEqual(len(set(first)), 113)
        self.assertIs(baseline.select_train(pairs, smoke=False), pairs)
        self.assertEqual(baseline.TRAIN_OPTIONS, {
            "imgsz": 640, "batch": 4, "device": 0, "seed": 42, "workers": 2, "amp": True, "cache": False,
            "patience": 10, "optimizer": "auto", "val": True, "split": "val", "plots": True,
            "deterministic": True, "save": True,
        })
        for invalid_name in ("../other", "x/y", "NUL"):
            with self.assertRaises(ValueError):
                baseline.run_path("train", invalid_name)

    def test_qualitative_matching_prioritizes_correct_class_and_identifies_confusion(self) -> None:
        truth = [Detection(0, (0, 0, 10, 10)), Detection(2, (20, 20, 30, 30)), Detection(3, (40, 40, 50, 50))]
        predictions = [Detection(1, (0, 0, 10, 10), 0.8), Detection(0, (0, 0, 8, 8), 0.7),
                       Detection(1, (20, 20, 30, 30), 0.6), Detection(0, (42, 42, 45, 45), 0.5)]
        self.assertEqual(match_boxes(truth, predictions), ([(0, 1, 0.64, False), (1, 2, 1.0, True)], [2], [0, 3]))
        self.assertEqual(match_boxes([], predictions), ([], [], [0, 1, 2, 3]))
