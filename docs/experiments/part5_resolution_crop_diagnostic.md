# Part 5.1 실제 도로 영상 해상도·Crop 진단

검증일 **2026-11-20 (KST)** · `road_sample_04.mp4` · YOLO11n Baseline

## 실험 목적

Part 5에서 실제 주행 영상 네 개를 분석한 결과는 모두 0건이었습니다. `road_sample_04`에서는 우측 차로에 균열이나 포장 보수 흔적으로 의심되는 모양이 보였습니다. 해당 장면이 입력에 포함된 1초·0.5초 분석과 별도 단일 프레임 추론에서도 탐지는 0건이었습니다. 동일한 원본 세 프레임으로 입력 크기와 수동 도로 Crop이 이 결과를 바꾸는지 확인했습니다. [실제 영상 검증 보고서](part5_real_video_validation.md#road_sample_04-추가-검증)

## 모델·환경·입력 프레임

기존 `outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/weights/best.pt`를 사용했습니다. 모델 SHA-256은 `40f0b6af12b8a33d83119138251ae345ee2ac50df5a3ae0ec81137d781b63342`입니다. 체크포인트의 객체 탐지 task와 클래스 `D00`, `D10`, `D20`, `D40`을 확인했습니다. 원본 MP4와 가중치의 실험 전후 SHA-256은 일치했습니다. [Baseline 보고서](yolo11n_baseline.md)

| 항목 | 실제 설정 |
| --- | --- |
| 실행 환경 | Windows 11 x64, Python 3.14.5, PyTorch 2.14.1+cu130, torchvision 0.29.1+cu130, Ultralytics 8.4.215, OpenCV 5.0.0 |
| GPU | NVIDIA GeForce RTX 3060 Ti 8 GiB, 드라이버 581.15, PyTorch CUDA 빌드 13.0 |
| 공통 추론 | `cuda:0`, batch 1, FP32, confidence 0.05, NMS IoU 0.7, 최대 300박스 |
| 전처리 | 정사각형 패딩 `rect=False`, 증강 `augment=False`. 영상의 원본 BGR 배열과 해당 배열의 ROI 슬라이스를 사용 |
| 실행 순서 | A1 → A2 → A3 → B → C, 각 프레임·조건은 한 차례 순차 추론 |

`review_frames.csv`에서 세 시점의 프레임 번호를 확인하고, 29.970030 FPS 원본 MP4를 처음부터 순차 디코딩했습니다. 표의 해시는 디코딩한 BGR 픽셀의 SHA-256입니다. 검토용 원본 JPG 세 장의 해시는 기존 수동 검토 JPG의 해시와 일치했습니다. FPS 기반 추정 시각과 디코더 시각을 요약 JSON에 기록했습니다. [기존 검토 CSV](../../outputs/video_analysis/road_sample_04_manual_review/review_frames.csv) · [실험 요약 JSON](../../outputs/video_analysis/road_sample_04_diagnostic/summary.json)

| 프레임 | 원본 인덱스 | 추정 시각 | 해상도 | 디코딩 BGR SHA-256 | 검토용 원본 |
| --- | ---: | ---: | ---: | --- | --- |
| A | 510 | 17.017000초 | 1920×1080 | `3cbe261a4dfbc9bff8b58f30f9ef085333360afe2b2ec7802241d7ba8364f075` | [frame_A.jpg](../../outputs/video_analysis/road_sample_04_diagnostic/frames/frame_A.jpg) |
| B | 517 | 17.250567초 | 1920×1080 | `32897908b5146967465aaf49288b09e967417f4d1f02c37f03420feee66458b0` | [frame_B.jpg](../../outputs/video_analysis/road_sample_04_diagnostic/frames/frame_B.jpg) |
| C | 525 | 17.517500초 | 1920×1080 | `874bd44bac55fb37ed771fa0b4b5c157b63ba6aebacb80f4abb89b84550da6e0` | [frame_C.jpg](../../outputs/video_analysis/road_sample_04_diagnostic/frames/frame_C.jpg) |

## 해상도 비교

실험 A에서는 동일한 BGR 배열에 `imgsz`만 바꿨습니다. 아래 텐서 크기는 패딩 후 YOLO 추론 함수에 들어간 실제 NCHW입니다. 시간은 Ultralytics의 프레임별 `inference` 값이며, GPU 메모리는 각 추론 직전 통계를 초기화한 뒤 읽은 PyTorch 할당 피크 중 조건별 최댓값입니다. 프레임 디코딩과 파일 저장 시간은 별도입니다. [개별 측정 CSV](../../outputs/video_analysis/road_sample_04_diagnostic/results.csv)

| 조건 | 설정 `imgsz` | 실제 NCHW | 성공 | 탐지 A·B·C | 추론 ms A·B·C | 중앙값 ms | GPU 할당 피크 MiB |
| --- | ---: | --- | ---: | --- | --- | ---: | ---: |
| A1 원본 | 640 | 1×3×640×640 | 3/3 | 0 · 0 · 0 | 11.81 · 11.27 · 11.28 | 11.28 | 75.62 |
| A2 원본 | 960 | 1×3×960×960 | 3/3 | 0 · 0 · 0 | 25.22 · 11.14 · 10.94 | 11.14 | 105.04 |
| A3 원본 | 1280 | 1×3×1280×1280 | 3/3 | 0 · 0 · 0 | 24.85 · 11.40 · 11.55 | 11.55 | 148.22 |
| B 도로 Crop | 640 | 1×3×640×640 | 3/3 | 0 · 0 · 0 | 12.78 · 11.34 · 14.98 | 12.78 | 75.91 |

실제 영상 추론 12회는 모두 완료됐고, 예외와 CUDA OOM은 0회였습니다. 1280에서 PyTorch 할당 피크는 148.22 MiB로, 640의 75.62 MiB보다 높았습니다. 960과 1280에서 첫 프레임의 추론 시간이 뒤의 두 프레임보다 길었습니다. 한 차례씩 순차 실행한 값으로 해상도별 정상 상태 처리 시간을 비교하려면 반복 계측이 필요합니다.

## 도로 Crop과 원본 좌표

검토 JPG에서 우측 차로의 의심 자국과 주변 포장을 직접 보고 사각형을 지정했습니다. 앞유리 아래 차내 영역과 하늘을 줄이고, 자국의 바깥 경계와 주변 노면을 포함하도록 했습니다. 우측 차로 경계와 방호벽 일부가 문맥으로 남습니다. 좌표는 원본의 `(x1, y1, x2, y2)`이며 오른쪽과 아래쪽 경계는 슬라이스에 포함하지 않습니다.

| 프레임 | 원본 ROI `xyxy` | Crop 너비×높이 | Crop 추론 탐지 | 확인한 모습 |
| --- | --- | ---: | ---: | --- |
| A | `(812, 497, 1088, 581)` | 276×84 | 0 | 우측 차로 전방에 짧고 불규칙한 선이 모여 있습니다. [Crop A](../../outputs/video_analysis/road_sample_04_diagnostic/crops/crop_A.jpg) |
| B | `(810, 498, 1107, 585)` | 297×87 | 0 | 우측 노면의 그물 모양 자국이 A보다 크게 보입니다. [Crop B](../../outputs/video_analysis/road_sample_04_diagnostic/crops/crop_B.jpg) |
| C | `(816, 498, 1125, 582)` | 309×84 | 0 | 가까운 노면에서 불규칙하게 교차하는 굵은 선이 보입니다. [Crop C](../../outputs/video_analysis/road_sample_04_diagnostic/crops/crop_C.jpg) |

Crop은 모델이 보는 자국의 상대적 크기와 주변 문맥을 함께 바꿉니다. 세 Crop에 의심 자국이 남아 있는 것을 직접 확인했고, confidence 0.05에서 반환된 박스는 0개였습니다. Crop 탐지가 생기면 입력 이미지 기준 박스에 ROI의 `(x1, y1)`을 더해 원본 좌표와 함께 저장합니다. 좌표 환산과 복수 박스 보존은 단위 테스트에서 확인했습니다.

## Czech 검증 이미지 대조

기존 평가에서 D00이 탐지된 `Czech_000370.jpg`와 D00 정답 라벨 1개를 확인했습니다. 같은 Baseline과 `imgsz=640`, confidence 0.05, NMS IoU 0.7로 한 차례 추론했습니다. 실제 입력은 1×3×640×640, 추론 시간은 11.40 ms, PyTorch 할당 피크는 75.62 MiB였습니다.

D00 박스가 **7개** 반환됐습니다. 최고 confidence는 **0.5599**이며 해당 박스의 600×600 원본 좌표는 `(297.03, 414.42, 358.19, 517.04)`입니다. 기록된 D00 정답과 예측의 최대 IoU는 **0.7277**이었습니다. 7개 박스와 confidence는 CSV에 각각 보존했습니다. 이 대조는 현재 스크립트와 체크포인트가 알려진 사례에서 좌표와 점수를 반환하는지 확인하는 데 사용했습니다. [대조 이미지](../../data/yolo/rdd2022_czech_v2/images/val/Czech_000370.jpg) · [정답 라벨](../../data/yolo/rdd2022_czech_v2/labels/val/Czech_000370.txt) · [기존 평가 그림](../../outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/validation/cases/true_positive_Czech_000370.png)

## 비교 이미지와 산출물 검증

비교 JPG 세 장을 직접 열어 원본, A1·A2·A3, 원본에 환산한 Crop 결과, Crop 상세를 대조했습니다. 청록색 테두리는 수동 ROI를 표시합니다. 실제 탐지 박스의 표시 색상은 노란색으로 정했고 이번 영상에서는 네 조건 모두 `No detection`으로 표시됐습니다. 패널은 같은 화면 크기로 렌더링했습니다. 실제 추론 텐서 크기는 위 표와 JSON에 기록돼 있습니다. [프레임 A 비교](../../outputs/video_analysis/road_sample_04_diagnostic/comparisons/frame_A_comparison.jpg) · [프레임 B 비교](../../outputs/video_analysis/road_sample_04_diagnostic/comparisons/frame_B_comparison.jpg) · [프레임 C 비교](../../outputs/video_analysis/road_sample_04_diagnostic/comparisons/frame_C_comparison.jpg)

CSV와 JSON에서 실험 13회와 CSV 데이터 행 19개를 대조했습니다. 실제 영상의 0건 결과는 프레임·조건별 1행씩이며, Czech 대조 결과는 박스별 7행입니다. 원본 MP4 재디코딩으로 프레임 해시, 시각, 출력 JPG와 Crop 픽셀 범위를 확인했습니다.

## 확인된 사실과 남은 원인

| 원인 후보 | 확인한 내용과 판단 |
| --- | --- |
| 입력 축소 또는 차내 배경 | 원본을 960과 1280으로 입력하거나 차내 영역을 줄인 Crop을 입력해도 세 프레임에서 탐지는 0건이었습니다. 시험한 두 조정으로 탐지가 회복되지 않았습니다. 입력 축소와 배경이 각각 기여한 정도는 근거 부족입니다. |
| Baseline 성능과 학습 도메인 | 로컬 Czech 대조 이미지에서 박스 반환을 확인했습니다. 기존 Czech 검증에는 작은 파손과 포트홀 미탐이 기록돼 있습니다. 이번 영상은 낮은 태양, 앞유리 반사, 운전대가 크게 들어간 구도이며 대조 이미지는 흐린 주간에 노면이 더 넓게 보입니다. 이런 차이와 기존 모델의 한계가 이번 결과에 기여한 정도는 근거 부족입니다. [기존 오류 분석](yolo11n_improvement_01.md) |
| 역광·압축·움직임 | 비교 이미지에서 역광과 반사는 관찰했습니다. 조명이나 압축, 움직임만 달리한 대응 영상이 없어 어느 요인이 검출에 영향을 주었는지는 근거 부족입니다. |
| 자국의 정답 클래스 | 우측 노면에 여러 갈래의 자국이 보입니다. 균열과 포장 보수 흔적의 구분 및 `D00`, `D10`, `D20`, `D40` 해당 여부는 판단 보류입니다. |

세 프레임은 약 0.5초에 걸친 동일 주행 장면에서 선정했습니다. 이 실험에서 확인한 범위는 해당 장면과 설정에서의 모델 출력입니다. 실제 영상의 정탐·미탐 집계에는 정답 라벨이 필요합니다.

## 후속 검증과 Part 6 판단

1. 의심 구간의 실제 파손 여부를 확인하고, 균열과 보수 흔적을 구분해 라벨링한 여러 주행 구간을 확보합니다.
2. 라벨이 있는 영상으로 카메라 각도와 조명별 미탐을 확인합니다. Crop 효과를 더 비교할 때는 배경만 줄인 입력과 의심 영역의 크기를 키운 입력을 각각 비교합니다.
3. 실제 주행 영상의 같은 클래스에서 미탐이 반복되면 확보한 도메인 데이터를 보강해 재학습 후보와 기존 Baseline을 비교합니다. 이번 세 프레임만으로 재학습의 효과는 판단하기 어렵습니다.

**Part 6의 FastAPI + React MVP 연동은 진행 가능합니다.** 기존 CLI의 실제 MP4 처리와 탐지 0건인 완료 상태에 근거합니다. 탐지가 발생하는 실제 영상에서 박스와 대표 JPG 표시를 검증할 항목으로 남겼습니다.

## 재현 명령어와 테스트

프로젝트 루트에서 실행했습니다. 새 실험에는 기존 실행과 다른 `--run-name`을 지정합니다.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts\diagnose_video_detection.py --run-name road_sample_04_diagnostic
.\.venv\Scripts\python.exe -B -X utf8 -m unittest -v tests.test_video_detection_diagnostic
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -v
```

신규 진단 테스트 **5개**와 전체 회귀 테스트 **46개**가 통과했습니다. [진단 스크립트](../../scripts/diagnose_video_detection.py) · [테스트 코드](../../tests/test_video_detection_diagnostic.py)
