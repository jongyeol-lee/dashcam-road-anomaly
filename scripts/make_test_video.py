import argparse
from pathlib import Path

import cv2
import numpy as np


DEFAULT_VIDEO_PATH = Path(__file__).resolve().parents[1] / "data/raw/test_3sec.mp4"
WIDTH, HEIGHT = 320, 180
FPS = 10
FRAME_COUNT = FPS * 3


def make_test_video(output_path: Path = DEFAULT_VIDEO_PATH) -> Path:
    """경과 시간이 표시된 3초짜리 MP4를 생성하고 디코딩을 확인한다."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # VideoWriter가 기존 파일을 덮어쓸 수 있으므로 경로를 먼저 독점 생성한다.
    output_path.touch(exist_ok=False)
    try:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(output_path), fourcc, FPS, (WIDTH, HEIGHT))
        try:
            if not writer.isOpened():
                raise RuntimeError(f"MP4 저장을 시작할 수 없습니다. {output_path}")

            for frame_index in range(FRAME_COUNT):
                frame = np.full((HEIGHT, WIDTH, 3), (48, 36, 24), dtype=np.uint8)
                cv2.putText(
                    frame, f"{frame_index / FPS:.1f} s", (24, 105),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (255, 255, 255), 2, cv2.LINE_AA,
                )
                writer.write(frame)
        finally:
            writer.release()

        # write()는 저장 성공 여부를 반환하지 않아 닫은 파일을 다시 디코딩한다.
        capture = cv2.VideoCapture(str(output_path))
        try:
            if not capture.isOpened():
                raise RuntimeError(f"저장한 MP4를 열 수 없습니다. {output_path}")
            for frame_index in range(FRAME_COUNT):
                decoded, _ = capture.read()
                if not decoded:
                    raise RuntimeError(f"저장한 MP4의 프레임 {frame_index}을 읽을 수 없습니다. {output_path}")
        finally:
            capture.release()
    except BaseException:
        output_path.unlink(missing_ok=True)
        raise

    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="3초짜리 합성 MP4를 생성합니다.")
    parser.add_argument("--output", type=Path, default=DEFAULT_VIDEO_PATH, help="저장할 MP4 경로")
    args = parser.parse_args()

    try:
        output_path = make_test_video(args.output)
    except (OSError, RuntimeError, cv2.error) as error:
        parser.exit(1, f"{error}\n")

    print(f"MP4 생성 완료 ({WIDTH}×{HEIGHT}, {FPS} FPS, {FRAME_COUNT}프레임) {output_path}")


if __name__ == "__main__":
    main()
