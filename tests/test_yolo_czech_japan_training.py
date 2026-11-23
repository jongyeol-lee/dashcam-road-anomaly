import csv
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from scripts import evaluate_yolo_czech_japan as evaluation
from scripts import train_yolo_czech_japan as train
from road_anomaly.yolo_evaluation import Detection


class TrainingTest(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        base = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        stack.enter_context(patch.dict(os.environ, YOLO_CONFIG_DIR=str(base / "config"),
                                      MPLCONFIGDIR=str(base / "mpl"), YOLO_OFFLINE="true"))
        for obj, name, path in (
            (train, "YOLO", base / "yolo"), (train, "AUDIT", base / "audit"), (train, "OUTPUT", base / "out"),
            (train, "BASE_RUN", base / "baseline"), (train.base, "WEIGHTS", base / "pretrained.pt"),
            (train.base, "DATA_YAML", base / "czech/data.yaml"),
        ):
            stack.enter_context(patch.object(obj, name, path))
        stack.enter_context(patch.object(train, "COUNTS", {train.PILOT: {"train": 2, "val": 1}, train.HOLDOUT: {"val": 1}}))
        for path in (train.base.WEIGHTS, train.base.DATA_YAML, train.BASE_RUN / "weights/best.pt",
                     train.BASE_RUN / "weights/last.pt", train.BASE_RUN / "args.yaml", train.BASE_RUN / "results.csv",
                     train.BASE_RUN / "training_summary.json", *(train.AUDIT / name for name in
                     ("selection_manifest.csv", "duplicate_groups.csv", "exclusion_report.csv"))):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixed")
        rows = []
        for dataset, splits in train.COUNTS.items():
            root = train.YOLO / dataset
            root.mkdir(parents=True)
            (root / "data.yaml").write_text(
                f"train: {'images/train' if dataset == train.PILOT else 'null'}\nval: images/val\ntest: images/test\n"
                "names:\n  0: D00\n  1: D10\n  2: D20\n  3: D40\n", encoding="utf-8")
            for split in splits:
                countries = ("Czech", "Japan") if split == "train" else ("Czech" if dataset == train.PILOT else "Japan",)
                for country in countries:
                    stem = f"{country}_{split}"
                    row = dict(country=country, dataset=dataset, split=split, group_id=stem)
                    for folder, suffix, field, sha in (("images", ".jpg", "output_image", "jpeg_sha256"),
                                                      ("labels", ".txt", "output_label", "label_sha256")):
                        relative = Path(folder, split, stem + suffix)
                        path = root / relative
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(stem.encode())
                        if country == "Czech":
                            original = train.base.DATA_YAML.parent / relative
                            original.parent.mkdir(parents=True, exist_ok=True)
                            original.write_bytes(path.read_bytes())
                        row[field], row[sha] = relative.as_posix(), train.digest(path)
                    rows.append(row)
        manifest = train.AUDIT / "split_manifest.csv"
        with manifest.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        stack.enter_context(patch.object(train, "MANIFEST_SHA", train.digest(manifest)))

    def test_only_train_and_val_opened_and_protected(self):
        datasets, hashes = train.check_inputs()
        self.assertEqual(set(datasets[train.HOLDOUT]), {"val"})
        self.assertEqual(len(datasets[train.PILOT]["train"]), 2)
        train.verify_saved(hashes)
        (train.BASE_RUN / "weights/best.pt").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "원본 변경"):
            train.verify_saved(hashes)

    def test_wrong_mapping_and_czech_validation_changes_are_rejected(self):
        config = train.YOLO / train.HOLDOUT / "data.yaml"
        original = config.read_bytes()
        config.write_bytes(original.replace(b"0: D00", b"0: D40"))
        with self.assertRaisesRegex(ValueError, "클래스 매핑"):
            train.check_inputs()
        config.write_bytes(original)
        (train.base.DATA_YAML.parent / "labels/val/Czech_val.txt").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "Czech v2 원본"):
            train.check_inputs()

    def test_group_overlap_including_test_is_rejected_from_metadata(self):
        for split in ("val", "test"):
            with self.subTest(split=split), self.assertRaisesRegex(ValueError, "교차"):
                train.check_groups([{"group_id": "g", "split": "train"}, {"group_id": "g", "split": split}])

    def test_failed_smoke_blocks_training_and_preserves_existing_run(self):
        with (patch.object(train.base, "runtime_info", return_value={}),
              patch.object(train.base, "select_train", side_effect=lambda pairs, smoke: pairs),
              patch.object(train.base, "load_pretrained"),
              patch.object(train.base, "train_model", side_effect=RuntimeError("smoke failed")) as run):
            with self.assertRaisesRegex(RuntimeError, "smoke failed"):
                train.run_training("fixture", 30)
            self.assertEqual(run.call_count, 1)
            with self.assertRaises(FileExistsError):
                train.run_training("fixture", 30)
        self.assertEqual(json.loads((train.OUTPUT / "fixture/failure.json").read_text())["type"], "RuntimeError")

    def test_inconsistent_paired_evaluation_is_rejected(self):
        folder = train.OUTPUT
        for name in ("baseline", "mixed"):
            (folder / name).mkdir(parents=True)
            truth = [] if name == "baseline" else [{"class_id": 0}]
            train.save(folder / name / "frames.json", {"v.jpg": {"truth": truth, "predictions": []}})
        with self.assertRaisesRegex(ValueError, "GT 불일치"):
            evaluation.paired_cases(folder, [(Path("v.jpg"), Path("v.txt"))])

    def test_training_record_requires_real_batches_updates_and_saved_best_epoch(self):
        summary = {"completed_epochs": 1, "options": {"epochs": 1}, "stage": "smoke", "training_images": 113,
                   "weights_sha256": train.base.WEIGHTS_SHA256, "amp_used": True, "batch_used": 4}
        measured = {"batches": 29, "optimizer_steps": 1, "best_epoch": 1}
        train.check_training_record(summary, measured, smoke=True)
        for key, value in (("batches", 28), ("optimizer_steps", 0), ("best_epoch", None)):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "학습 기록"):
                train.check_training_record(summary, measured | {key: value}, smoke=True)

    def test_gains_losses_confusion_and_same_location_false_positives(self):
        d10 = Detection(1, (0, 0, 10, 10))
        d20 = Detection(2, (20, 20, 30, 30))
        d40 = Detection(3, (40, 40, 50, 50))
        extra = Detection(3, (60, 60, 75, 75))
        events = evaluation.compare_objects([d10, d20, d40], [d20, extra], [d10, Detection(3, d20.xyxy), extra])
        self.assertCountEqual([row["kind"] for row in events],
                              ["gained_tp", "lost_tp", "both_missed", "confusion", "common_fp"])
        confusion = next(row for row in events if row["kind"] == "confusion")
        self.assertEqual((confusion["model"], confusion["class"], confusion["predicted"]), ("mixed", "D20", "D40"))
