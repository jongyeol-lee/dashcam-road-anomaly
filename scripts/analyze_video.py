import argparse
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from road_anomaly.video_analysis import DEVICES, PROFILES, analyze_video


def main() -> None:
    parser = argparse.ArgumentParser(description="MP4에서 YOLO가 탐지한 확인 필요 장면과 추정 시간을 저장합니다.")
    parser.add_argument("video_path", type=Path, help="입력 MP4 경로")
    parser.add_argument("--run-name", help="출력 실행 이름. 생략하면 UTC 시각으로 생성")
    parser.add_argument("--profile", choices=PROFILES, default="baseline", help="분석 프로필. 개별 옵션이 우선합니다.")
    parser.add_argument("--model", type=Path, help="로컬 탐지 .pt 경로")
    parser.add_argument("--imgsz", type=int, help="YOLO 입력 크기(픽셀)")
    parser.add_argument("--interval", type=float, help="프레임 샘플링 간격(초)")
    parser.add_argument("--confidence", type=float, help="탐색용 confidence 기준")
    parser.add_argument("--max-gap", type=float, help="동일 클래스 통합 최대 간격(초)")
    parser.add_argument("--device", choices=DEVICES, help="추론 장치")
    args = parser.parse_args()

    try:
        # Ultralytics 설정과 Matplotlib 캐시를 이 실행의 임시 폴더에 둔다.
        with TemporaryDirectory(prefix="road-anomaly-video-") as config:
            os.environ.update(YOLO_CONFIG_DIR=config, MPLCONFIGDIR=config, YOLO_OFFLINE="true", YOLO_AUTOINSTALL="false")
            result = analyze_video(
                args.video_path, run_name=args.run_name, model_path=args.model, profile=args.profile, imgsz=args.imgsz,
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
