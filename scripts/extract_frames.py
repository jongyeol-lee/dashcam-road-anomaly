import argparse
import sys
from pathlib import Path

import cv2


# 패키지를 별도 설치하지 않아도 저장소에서 스크립트를 직접 실행할 수 있게 한다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from road_anomaly.video import extract_frames


def main() -> None:
    parser = argparse.ArgumentParser(description="MP4에서 JPG 프레임과 타임스탬프 CSV를 추출합니다.")
    parser.add_argument("video_path", type=Path, help="입력 MP4 경로")
    parser.add_argument("--interval", type=float, default=1.0, help="추출 간격(초), 기본값 1")
    parser.add_argument("--output-dir", type=Path, help="JPG와 CSV를 저장할 폴더")
    args = parser.parse_args()

    try:
        result = extract_frames(args.video_path, args.interval, args.output_dir)
    except (OSError, ValueError, RuntimeError, cv2.error) as error:
        parser.exit(1, f"{error}\n")

    print(f"FPS {result.fps:g} | 해상도 {result.width}×{result.height} | 전체 {result.frame_count}프레임")
    print(f"JPG {result.extracted_count}장과 frames.csv 저장 완료 {result.output_dir}")


if __name__ == "__main__":
    main()
