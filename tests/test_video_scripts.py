import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2

from src.road_anomaly.video import extract_frames


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_script(script: str, *args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", "-X", "utf8", str(PROJECT_ROOT / "scripts" / script), *map(str, args)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        encoding="utf-8",
        timeout=30,
    )


class VideoScriptsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp_dir.cleanup)
        cls.root = Path(temp_dir.name)
        cls.video_path = cls.root / "test_3sec.mp4"
        result = run_script("make_test_video.py", "--output", cls.video_path)
        if result.returncode != 0:
            raise RuntimeError(result.stderr)

    def test_generated_video_metadata_and_decoding(self) -> None:
        capture = cv2.VideoCapture(str(self.video_path))
        try:
            self.assertTrue(capture.isOpened())
            self.assertEqual(capture.get(cv2.CAP_PROP_FPS), 10)
            self.assertEqual(capture.get(cv2.CAP_PROP_FRAME_WIDTH), 320)
            self.assertEqual(capture.get(cv2.CAP_PROP_FRAME_HEIGHT), 180)
            self.assertEqual(capture.get(cv2.CAP_PROP_FRAME_COUNT), 30)
            for _ in range(30):
                decoded, frame = capture.read()
                self.assertTrue(decoded)
                self.assertEqual(frame.shape, (180, 320, 3))
            self.assertFalse(capture.read()[0])
        finally:
            capture.release()

    def test_extracts_at_one_second_and_records_timestamps(self) -> None:
        output_dir = self.root / "one-second"
        output_dir.mkdir()
        result = run_script("extract_frames.py", self.video_path, "--output-dir", output_dir)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("FPS 10 | 해상도 320×180 | 전체 30프레임", result.stdout)

        with (output_dir / "frames.csv").open(encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            self.assertEqual(reader.fieldnames, [
                "frame_index", "estimated_time_sec", "decoder_time_ms", "image_file",
            ])
            rows = list(reader)
        self.assertEqual([int(row["frame_index"]) for row in rows], [0, 10, 20])
        self.assertEqual([float(row["estimated_time_sec"]) for row in rows], [0.0, 1.0, 2.0])
        self.assertEqual([float(row["decoder_time_ms"]) for row in rows], [0.0, 1000.0, 2000.0])

        image_names = [row["image_file"] for row in rows]
        self.assertEqual(sorted(path.name for path in output_dir.glob("*.jpg")), image_names)
        for name in image_names:
            frame = cv2.imread(str(output_dir / name))
            self.assertIsNotNone(frame)
            self.assertEqual(frame.shape, (180, 320, 3))

    def test_fractional_interval_uses_first_frame_at_or_after_target(self) -> None:
        output_dir = self.root / "quarter-second"
        extract_frames(self.video_path, 0.25, output_dir)
        with (output_dir / "frames.csv").open(encoding="utf-8", newline="") as csv_file:
            frame_indices = [int(row["frame_index"]) for row in csv.DictReader(csv_file)]
        self.assertEqual(frame_indices, [0, 3, 5, 8, 10, 13, 15, 18, 20, 23, 25, 28])

    def test_missing_and_unreadable_videos(self) -> None:
        missing_video = self.root / "missing.mp4"
        unreadable_video = self.root / "invalid.mp4"
        unreadable_video.write_bytes(b"not a video")
        output_dir = self.root / "no-output"
        for video_path, message in (
            (missing_video, "MP4 파일을 찾을 수 없습니다"),
            (unreadable_video, "MP4 파일을 열 수 없습니다"),
        ):
            with self.subTest(video_path=video_path):
                result = run_script("extract_frames.py", video_path, "--output-dir", output_dir)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertFalse(output_dir.exists())

    def test_invalid_intervals(self) -> None:
        output_dir = self.root / "invalid-interval"
        for interval in ("0", "-1", "nan", "inf"):
            with self.subTest(interval=interval):
                result = run_script(
                    "extract_frames.py", self.video_path, "--output-dir", output_dir, f"--interval={interval}",
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("추출 간격", result.stderr)
                self.assertFalse(output_dir.exists())

    def test_invalid_fps_releases_capture(self) -> None:
        capture = Mock()
        capture.isOpened.return_value = True
        capture.get.return_value = 0.0
        output_dir = self.root / "invalid-fps"
        with patch.object(cv2, "VideoCapture", return_value=capture):
            with self.assertRaisesRegex(ValueError, "FPS"):
                extract_frames(self.video_path, output_dir=output_dir)
        capture.release.assert_called_once_with()
        self.assertFalse(output_dir.exists())

    def test_failed_image_encoding_cleans_up_partial_results(self) -> None:
        output_dir = self.root / "encoding-failure"
        with patch.object(cv2, "imencode", side_effect=[(True, b"jpeg"), (False, None)]):
            with self.assertRaisesRegex(RuntimeError, "JPG"):
                extract_frames(self.video_path, output_dir=output_dir)
        self.assertEqual(list(output_dir.iterdir()), [])

    def test_existing_extraction_is_preserved(self) -> None:
        output_dir = self.root / "existing-results"
        extract_frames(self.video_path, output_dir=output_dir)
        before = {path.name: path.read_bytes() for path in output_dir.iterdir()}
        source_before = self.video_path.read_bytes()

        result = run_script(
            "extract_frames.py", self.video_path, "--interval", "0.5", "--output-dir", output_dir,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("출력 경로가 비어 있지 않습니다", result.stderr)
        self.assertEqual({path.name: path.read_bytes() for path in output_dir.iterdir()}, before)
        self.assertEqual(self.video_path.read_bytes(), source_before)

    def test_existing_mp4_is_preserved(self) -> None:
        before = self.video_path.read_bytes()
        result = run_script("make_test_video.py", "--output", self.video_path)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.video_path.read_bytes(), before)
