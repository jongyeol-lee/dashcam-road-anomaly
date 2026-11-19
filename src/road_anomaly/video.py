import csv
import math
from contextlib import ExitStack
from dataclasses import dataclass
from fractions import Fraction
from itertools import count
from pathlib import Path

import cv2


DEFAULT_FRAMES_ROOT = Path(__file__).resolve().parents[2] / "data/processed/frames"


@dataclass(frozen=True)
class ExtractionResult:
    output_dir: Path
    fps: float
    width: int
    height: int
    frame_count: int
    extracted_count: int


def extract_frames(
    video_path: Path, interval: float = 1.0, output_dir: Path | None = None,
) -> ExtractionResult:
    """0초부터 간격마다 해당 시각 이상의 첫 프레임을 JPG와 CSV로 저장한다.

    프레임 인덱스/FPS를 기준으로 샘플링하므로 가변 FPS 영상에서는
    추출 시점과 추정 시간이 실제 표시 시각과 다를 수 있다.
    """
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("추출 간격은 0보다 큰 유한한 숫자(초)여야 합니다.")
    if not video_path.is_file():
        raise FileNotFoundError(f"MP4 파일을 찾을 수 없습니다. {video_path}")
    if output_dir is None:
        output_dir = DEFAULT_FRAMES_ROOT / video_path.stem

    capture = cv2.VideoCapture(str(video_path))
    try:
        if not capture.isOpened():
            raise RuntimeError(f"MP4 파일을 열 수 없습니다. {video_path}")
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError(f"영상의 FPS가 유효하지 않습니다. {fps}")

        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

        output_dir.mkdir(parents=True, exist_ok=True)
        if any(output_dir.iterdir()):
            raise FileExistsError(f"출력 경로가 비어 있지 않습니다. {output_dir}")

        # 소수 간격의 경계를 정수 연산으로 비교해 반올림 때문에 한 프레임이 밀리는 것을 방지한다.
        frames_per_interval = Fraction(str(interval)) * Fraction(str(fps))
        last_interval_index = -1
        extracted_count = 0
        csv_path = output_dir / "frames.csv"
        with ExitStack() as cleanup:
            # CSV와 JPG를 독점 생성하고, 실패 시 이번 호출에서 생성한 파일만 정리한다.
            with csv_path.open("x", encoding="utf-8", newline="") as csv_file:
                cleanup.callback(csv_path.unlink, missing_ok=True)
                writer = csv.writer(csv_file)
                writer.writerow(("frame_index", "estimated_time_sec", "decoder_time_ms", "image_file"))

                for frame_index in count():
                    decoded, frame = capture.read()
                    if not decoded:
                        break
                    interval_index = (
                        frame_index * frames_per_interval.denominator // frames_per_interval.numerator
                    )
                    if interval_index == last_interval_index:
                        continue

                    decoder_time_ms = capture.get(cv2.CAP_PROP_POS_MSEC)
                    image_path = output_dir / f"frame_{frame_index:06d}.jpg"
                    encoded, jpeg = cv2.imencode(".jpg", frame)
                    if not encoded:
                        raise RuntimeError(f"JPG를 인코딩할 수 없습니다. {image_path}")
                    with image_path.open("xb") as image_file:
                        cleanup.callback(image_path.unlink, missing_ok=True)
                        image_file.write(jpeg)
                    writer.writerow((frame_index, frame_index / fps, decoder_time_ms, image_path.name))
                    last_interval_index = interval_index
                    extracted_count += 1

                if extracted_count == 0:
                    raise RuntimeError(f"MP4에서 프레임을 읽을 수 없습니다. {video_path}")
            cleanup.pop_all()
    finally:
        capture.release()

    return ExtractionResult(output_dir, fps, width, height, frame_count, extracted_count)
