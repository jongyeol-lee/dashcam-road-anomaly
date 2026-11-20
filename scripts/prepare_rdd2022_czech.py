import argparse
import sys
from pathlib import Path
from zipfile import BadZipFile

import cv2


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from road_anomaly.rdd2022 import prepare_czech


def main() -> None:
    parser = argparse.ArgumentParser(description="RDD2022 Czech를 검사하고 YOLO 탐지 데이터셋으로 변환합니다.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--zip-path", type=Path, help="Czech.zip 경로")
    source.add_argument("--czech-dir", type=Path, help="train과 test가 있는 기존 Czech 폴더 경로")
    parser.add_argument("--processed-dir", type=Path, default=PROJECT_ROOT / "data/processed/rdd2022_czech",
                        help="검사 보고서, 분할 CSV 및 미리보기 폴더")
    parser.add_argument("--yolo-dir", type=Path, default=PROJECT_ROOT / "data/yolo/rdd2022_czech",
                        help="YOLO 이미지, 라벨 및 data.yaml 폴더")
    args = parser.parse_args()
    source_path = args.zip_path or args.czech_dir
    try:
        if args.zip_path and not source_path.is_file():
            raise FileNotFoundError("입력 ZIP 파일을 찾을 수 없습니다.")
        if args.czech_dir and not source_path.is_dir():
            raise FileNotFoundError("입력 Czech 폴더를 찾을 수 없습니다.")
        summary = prepare_czech(source_path, args.processed_dir, args.yolo_dir)
    except (OSError, BadZipFile, ValueError, RuntimeError, cv2.error) as error:
        parser.exit(1, f"{source_path} [{type(error).__name__}] {error}\n")

    report_path = args.processed_dir.resolve() / "inspection_summary.json"
    if summary["errors"]:
        parser.exit(1, f"검사 실패 {len(summary['errors'])}건. 파일별 오류 기록 {report_path}\n")
    counts = summary["splits"]["actual"]
    print(" | ".join(f"{split} {stats['images']}장" for split, stats in counts.items()))
    print(f"검사 보고서 {report_path}")
    print(f"YOLO 설정 {args.yolo_dir.resolve() / 'data.yaml'}")


if __name__ == "__main__":
    main()
