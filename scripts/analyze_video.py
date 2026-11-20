import argparse
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from road_anomaly.detection_grouping import DEFAULT_MAX_GAP
from road_anomaly.video_analysis import DEFAULT_CONFIDENCE, DEFAULT_INTERVAL, DEFAULT_MODEL, DEVICES, analyze_video


def main() -> None:
    parser = argparse.ArgumentParser(description="MP4에서 YOLO가 탐지한 확인 필요 장면과 추정 시간을 저장합니다.")
    parser.add_argument("video_path", type=Path, help="입력 MP4 경로")
    parser.add_argument("--run-name", help="출력 실행 이름. 생략하면 UTC 시각으로 생성")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="로컬 탐지 .pt 경로. 기본값은 YOLO11n Baseline")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL, help="프레임 샘플링 간격(초), 기본값 1.0")
    parser.add_argument("--confidence", type=float, default=DEFAULT_CONFIDENCE, help="탐색용 confidence 기준, 기본값 0.05")
    parser.add_argument("--max-gap", type=float, default=DEFAULT_MAX_GAP, help="동일 클래스 통합 최대 간격(초), 기본값 1.5")
    parser.add_argument("--device", choices=DEVICES, default="auto", help="기본값 auto는 CUDA 0을 우선 사용")
    args = parser.parse_args()

    try:
        # Ultralytics 설정과 Matplotlib 캐시를 이 실행의 임시 폴더에 둔다.
        with TemporaryDirectory(prefix="road-anomaly-video-") as config:
            os.environ.update(YOLO_CONFIG_DIR=config, MPLCONFIGDIR=config, YOLO_OFFLINE="true", YOLO_AUTOINSTALL="false")
            result = analyze_video(
                args.video_path, run_name=args.run_name, model_path=args.model,
                interval=args.interval, confidence=args.confidence, max_gap=args.max_gap, device=args.device,
            )
    except (OSError, ValueError, RuntimeError, cv2.error) as error:
        parser.exit(1, f"{error}\n")

    print(f"추출 {result['video']['extracted_frame_count']}프레임 | 탐지 {result['detection_count']}건"
          f" | AI 의심 구간 {result['event_count']}개 | {result['analysis_seconds']:.2f}초")
    print(f"프레임 {result['frames_dir']}")
    print(f"분석 결과 {result['output_dir']}")


if __name__ == "__main__":
    main()
