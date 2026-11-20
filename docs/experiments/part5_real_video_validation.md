# Part 5 실제 도로 주행 영상 검증

검증일 **2026-11-20 (KST)** · 실제 주행 MP4 3개 · YOLO11n Baseline

기존 MP4 분석 CLI로 실제 영상 세 개를 모두 분석했습니다. 1초 간격으로 추출한 79프레임에서 탐지는 0건이었습니다. `road_sample_01`의 0.5초 비교 실행에서도 AI 의심 구간은 0개였습니다. 네 실행의 프레임과 결과 파일을 대조했고 기존 회귀 테스트 41개가 통과했습니다.

## 실행 환경과 설정

프로젝트 `.venv`에서 Windows 11 x64, Python 3.14.5, PyTorch 2.14.1+cu130, torchvision 0.29.1+cu130, Ultralytics 8.4.215, OpenCV 5.0.0을 확인했습니다. GPU는 NVIDIA GeForce RTX 3060 Ti 8 GiB이며 드라이버는 581.15, PyTorch CUDA 빌드는 13.0입니다. 네 실행 모두 `cuda:0`을 사용했습니다. [개발환경 기록](../ENVIRONMENT.md)

모델은 `outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/weights/best.pt`입니다. SHA-256 `40f0b6af12b8a33d83119138251ae345ee2ac50df5a3ae0ec81137d781b63342`가 실험 기록과 일치했습니다. 체크포인트를 직접 열어 클래스 매핑 `0 → D00`, `1 → D10`, `2 → D20`, `3 → D40`을 확인했습니다. 원본 세 파일과 가중치의 분석 전후 SHA-256이 일치했습니다. [Baseline 보고서](yolo11n_baseline.md)

| 설정 | 적용값 |
| --- | --- |
| 기본 프레임 샘플링 | 1.0초, 비교 실행은 0.5초 |
| Confidence | 0.05 |
| NMS IoU | 0.7 |
| YOLO 입력 | 640×640, `rect=False` |
| 프레임당 최대 탐지 수 | 300 |
| 동일 클래스 통합 최대 간격 | 1.5초 |
| 추론 장치와 실행 순서 | `cuda:0`, 영상별 순차 실행 |

## 영상별 분석 결과

원본은 `C:\Projects\dashcam-road-anomaly\data\raw\`에 있습니다. 재생 길이는 MP4 컨테이너의 `mvhd`에서 읽었습니다. 분석 전에 OpenCV의 FFMPEG 백엔드로 H.264 영상의 프레임을 끝까지 디코딩하고 실제 개수를 메타데이터와 비교했습니다.

| 항목 | road_sample_01 | road_sample_02 | road_sample_03 |
| --- | ---: | ---: | ---: |
| 원본 파일 | [road_sample_01.mp4](../../data/raw/road_sample_01.mp4) | [road_sample_02.mp4](../../data/raw/road_sample_02.mp4) | [road_sample_03.mp4](../../data/raw/road_sample_03.mp4) |
| 파일 크기 | 25,150,940 B | 82,480,837 B | 21,015,983 B |
| 영상 길이 | 20.020초 | 30.030초 | 28.202초 |
| FPS | 23.976024 | 23.976024 | 60 |
| 해상도 | 2732×1152 | 3840×1620 | 1920×1080 |
| 전체 프레임 수 | 480 | 720 | 1,691 |
| 디코딩 | 480/480 | 720/720 | 1,691/1,691 |
| 1초 간격 예상 추출 수 | 20 | 30 | 29 |
| 추출 프레임 수 | 20 | 30 | 29 |
| 추출 JPG 실제 용량 | 9.41 MiB | 23.78 MiB | 9.72 MiB |
| YOLO 탐지 수 | 0 | 0 | 0 |
| AI 의심 구간 수 | 0 | 0 | 0 |
| 대표 JPG 수 | 0 | 0 | 0 |
| 전체 분석 시간 | 6.99초 | 12.48초 | 10.36초 |

분석 전 각 영상에서 처음·마지막 프레임과 중간 세 프레임을 JPG로 메모리에 인코딩했습니다. 샘플 평균으로 계산한 기본 추출 JPG 예상 용량은 각각 9.41, 23.93, 9.56 MiB로 합계 42.89 MiB였습니다. 예상치는 추출 JPG 기준입니다. 실행 전 C: 여유 공간은 153.13 GiB였습니다.

전체 분석 시간은 `summary.json`의 `analysis_seconds`입니다. 프레임 추출, 모델 로딩과 추론, 상세 결과 저장을 포함하며, 요약 파일 기록 직전에 측정한 값입니다.

| 실행 이름 | 산출물 |
| --- | --- |
| `road_sample_01_test` | [frames.csv](../../data/processed/frames/road_sample_01_test/frames.csv) · [summary.json](../../outputs/video_analysis/road_sample_01_test/summary.json) · [detections.csv](../../outputs/video_analysis/road_sample_01_test/detections.csv) · [events.json](../../outputs/video_analysis/road_sample_01_test/events.json) |
| `road_sample_02_test` | [frames.csv](../../data/processed/frames/road_sample_02_test/frames.csv) · [summary.json](../../outputs/video_analysis/road_sample_02_test/summary.json) · [detections.csv](../../outputs/video_analysis/road_sample_02_test/detections.csv) · [events.json](../../outputs/video_analysis/road_sample_02_test/events.json) |
| `road_sample_03_test` | [frames.csv](../../data/processed/frames/road_sample_03_test/frames.csv) · [summary.json](../../outputs/video_analysis/road_sample_03_test/summary.json) · [detections.csv](../../outputs/video_analysis/road_sample_03_test/detections.csv) · [events.json](../../outputs/video_analysis/road_sample_03_test/events.json) |
| `road_sample_01_halfsec_test` | [frames.csv](../../data/processed/frames/road_sample_01_halfsec_test/frames.csv) · [summary.json](../../outputs/video_analysis/road_sample_01_halfsec_test/summary.json) · [detections.csv](../../outputs/video_analysis/road_sample_01_halfsec_test/detections.csv) · [events.json](../../outputs/video_analysis/road_sample_01_halfsec_test/events.json) |

## 결과 정합성과 장면 점검

- **프레임과 시간.** 샘플링 목표 시각에 도달한 첫 프레임의 번호를 다시 계산해 네 실행의 `frames.csv`와 대조했습니다. 추정 시각은 `frame_index / FPS`와 일치했고 원본 디코더 시각과의 차이는 부동소수점 반올림 범위였습니다. 모든 기록은 각 영상의 재생 범위 안에 있었습니다. 목표 시각으로부터 최대 샘플링 지연은 1초 실행에서 각각 19, 29, 0 ms, 0.5초 실행에서 19.5 ms였습니다. 네 실행의 추출 JPG 119장을 모두 열어 해상도를 확인했고, 같은 원본 프레임을 재디코딩해 인코딩한 JPG와 바이트까지 일치했습니다.
- **탐지 파일.** 네 실행에서 `detections.csv`의 헤더, `events.json`의 빈 배열 `[]`, 비어 있는 `scenes/`, `summary.json`의 탐지·구간 집계 0이 일치했습니다. 영상별 탐지 행이 0개여서 박스 범위, confidence, 탐지 행의 프레임 시각 연결, 프레임당 여러 박스 보존은 실영상에서 확인할 사례가 없었습니다.
- **구간과 대표 장면.** 실영상은 이벤트 0건 처리까지 검증했습니다. 같은 클래스의 1.5초 이내 통합, 다른 클래스 분리, 박스 보존, 최고 confidence 대표 프레임 선택과 JPG 오버레이는 기존 Mock 테스트에서 통과했습니다. 실영상에서 탐지가 발생한 구간의 시작·마지막 시각과 대표 이미지 연결은 후속 검증이 필요합니다. [구간 통합 테스트](../../tests/test_detection_grouping.py) · [분석·대표 JPG 테스트](../../tests/test_video_analysis.py)

### 시각적으로 확인한 원본 프레임

세 영상의 대표 탐지 사례는 0건입니다. 아래 관찰은 추출 JPG에서 노면과 촬영 조건을 확인한 기록이며, 파손 여부는 판단을 보류했습니다.

| 영상 | 확인한 시각 | 노면과 촬영 조건 |
| --- | --- | --- |
| `road_sample_01` | 5.005초, 14.014초 | 중앙선 주변에 규칙적인 홈이 이어지고, 5.005초에는 중앙선 왼쪽 노면에도 가늘고 불연속적인 자국이 보입니다. 차내 구조물과 계기판이 화면 하단을 크게 차지합니다. [5.005초 JPG](../../data/processed/frames/road_sample_01_test/frame_000120.jpg) · [14.014초 JPG](../../data/processed/frames/road_sample_01_test/frame_000336.jpg) |
| `road_sample_02` | 5.005초, 14.014초 | 곡선 도로 우측 차로에 주행 방향으로 긴 어두운 자국이 보입니다. 앞유리와 차내 구조물이 함께 찍혀 있고, 자국의 성격은 판단 보류입니다. [5.005초 JPG](../../data/processed/frames/road_sample_02_test/frame_000120.jpg) · [14.014초 JPG](../../data/processed/frames/road_sample_02_test/frame_000336.jpg) |
| `road_sample_03` | 5초, 14초 | 전방 노면과 차선이 선명합니다. 5초 프레임에서는 주황색과 흰색의 횡방향 노면 표시를 확인했습니다. [5초 JPG](../../data/processed/frames/road_sample_03_test/frame_000300.jpg) · [14초 JPG](../../data/processed/frames/road_sample_03_test/frame_000840.jpg) |

## 1초와 0.5초 샘플링 비교

`road_sample_01`을 선택했습니다. 5.005초 부근에 가는 노면 흔적이 보여 주변 시각을 더 촘촘히 추출했을 때 새 탐지가 생기는지 비교하기에 적합했습니다. 추가 실행 전 추출 예상치는 40장, 18.82 MiB였습니다. 샘플링 간격만 바꾸고 별도 실행 이름을 사용했습니다.

| 항목 | 1.0초 | 0.5초 |
| --- | ---: | ---: |
| 분석 프레임 | 20 | 40 |
| YOLO 탐지 | 0 | 0 |
| AI 의심 구간 | 0 | 0 |
| 새로 발견된 의심 시간대 | — | 0개 |
| 추출 JPG 용량 | 9.41 MiB | 18.79 MiB |
| 전체 분석 시간 | 6.99초 | 7.26초 |

1초 실행의 20프레임이 모두 0.5초 실행에 포함됐고, 0.5005~19.5195초 사이에서 20프레임이 추가됐습니다. 4.5045초와 5.5055초의 추가 프레임에서도 중앙선 주변의 흔적을 살펴봤습니다. 동일한 물리적 자국인지와 파손 여부는 판단을 보류했습니다. 한 차례씩 실행한 결과로 처리 시간은 0.27초, 추출 JPG 용량은 9.38 MiB 증가했습니다. [4.5045초 JPG](../../data/processed/frames/road_sample_01_halfsec_test/frame_000108.jpg) · [5.5055초 JPG](../../data/processed/frames/road_sample_01_halfsec_test/frame_000132.jpg)

## 발견된 한계

- **탐지 사례와 데이터.** 정답 라벨 없는 주행 영상 세 개에서 검토할 모델 탐지 사례는 0건이었습니다. `road_sample_01`의 중앙선 주변 자국은 미탐 여부를 확인할 후보로 남겼습니다. 이번 표본으로 Precision, Recall, mAP를 산출할 수 없습니다. 1·2번 영상에서는 차내 영역이 큰 비중을 차지해 640 입력으로 축소한 뒤의 노면 식별 가능성을 별도로 확인할 필요가 있습니다.
- **시간 기반 구간 통합.** 1.5초는 같은 클래스의 인접 탐지 두 건 사이에 적용되는 기준입니다. 인접 탐지가 이어지면 구간 전체가 1.5초를 넘거나 서로 다른 대상이 한 구간에 포함될 수 있습니다. 이번 영상에서는 실제 과통합 여부를 평가할 사례가 없었습니다.
- **타임스탬프.** 세 입력에서 원본 디코더 타임스탬프 간격은 일정했습니다. 가변 FPS 영상에서 `frame_index / FPS` 추정 시각과 실제 표시 시각이 얼마나 달라지는지는 별도 확인이 필요합니다.
- **처리 시간.** 각 조건의 단일 측정은 해당 영상과 이 PC에서의 전체 분석 시간입니다. 긴 영상, 동시 요청 및 프레임별 추론 시간은 후속 측정 대상으로 남습니다.

## 회귀 테스트와 최종 판단

실제 영상 네 차례 분석을 마친 뒤 전체 회귀 테스트를 다시 실행했습니다. **41개 모두 통과**했습니다. [실행 방법](../../README.md#mp4-도로환경-이상-분석)

| 항목 | 판단 |
| --- | --- |
| 실제 MP4 분석 | 세 영상 모두 정상 종료했습니다. 0.5초 비교 실행도 완료했습니다. |
| 결과 파일 정합성 | 추출 프레임 JPG, 프레임별 추정 시각, 영상 메타데이터, 실행 설정과 0건 결과 구조를 대조했습니다. |
| 실제 도로 파손 탐지 성능 | 시각적으로 확인한 범위는 원본 프레임의 노면 상태와 촬영 조건입니다. 성능을 평가하려면 파손과 정상 구간이 라벨링된 실제 영상이 필요합니다. |
| Part 6 FastAPI + React | **MVP 연동 진행 가능.** 기존 CLI가 실제 MP4를 처리하고 성공 상태에서 읽을 JSON·CSV를 생성했습니다. 탐지 0건인 완료 상태를 화면에서 표현할 수 있습니다. |
| Part 7 추가 검증 | 라벨이 있는 여러 주행 구간에 대해 클래스별 정탐·오탐·미탐을 확인합니다. 탐지가 있는 영상에서 대표 JPG 위치와 라벨, 구간 과통합, 재생 시각 연결을 확인합니다. 가변 FPS와 긴 영상에서 시각 오차, 프레임별 추론 시간과 전체 분석 시간도 측정합니다. |

### 실행 명령어

프로젝트 루트에서 실행했습니다. 재실행할 때는 새 `--run-name`을 사용합니다.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts\analyze_video.py .\data\raw\road_sample_01.mp4 --run-name road_sample_01_test
.\.venv\Scripts\python.exe -B -X utf8 scripts\analyze_video.py .\data\raw\road_sample_02.mp4 --run-name road_sample_02_test
.\.venv\Scripts\python.exe -B -X utf8 scripts\analyze_video.py .\data\raw\road_sample_03.mp4 --run-name road_sample_03_test
.\.venv\Scripts\python.exe -B -X utf8 scripts\analyze_video.py .\data\raw\road_sample_01.mp4 --interval 0.5 --run-name road_sample_01_halfsec_test
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -v
```

## road_sample_04 추가 검증

검증일 **2026-11-20 (KST)** · 파손 의심 자국이 보이는 주행 영상 · YOLO11n Baseline

### 영상 정보와 분석 결과

`data/raw/road_sample_04.mp4`는 29,051,909바이트이며 해상도는 1920×1080, 프레임률은 29.970030 FPS입니다. OpenCV 5.0.0의 FFmpeg 백엔드로 H.264 전체 875프레임을 디코딩했습니다. 이 파일은 `moof`를 포함하는 분할 MP4이며 `mvhd`에 기록된 재생 길이는 0초였습니다. 영상 트랙 길이 약 29.196초는 마지막 디코더 타임스탬프 29.162467초에 한 프레임 간격을 더해 구했습니다. 원본 파일과 Baseline 가중치의 분석 전후 SHA-256이 일치했습니다. [원본 MP4](../../data/raw/road_sample_04.mp4)

기존 `analyze_video.py`와 위에 기록한 `best.pt`를 사용했습니다. 두 실행의 `summary.json`에서 `cuda:0`, confidence 0.05, NMS IoU 0.7, 입력 640×640, 통합 간격 1.5초가 일치함을 확인했습니다.

| 항목 | 1.0초 | 0.5초 |
| --- | ---: | ---: |
| 실행 이름 | `road_sample_04_1s` | `road_sample_04_05s` |
| 추출 프레임 수 | 30 | 59 |
| YOLO 탐지 수 | 0 | 0 |
| 클래스별 탐지 수 | D00 0 · D10 0 · D20 0 · D40 0 | D00 0 · D10 0 · D20 0 · D40 0 |
| AI 의심 구간 수 | 0 | 0 |
| 대표 JPG 수 | 0 | 0 |
| 전체 분석 시간 | 7.51초 | 8.09초 |

1초 실행의 30장은 모두 0.5초 실행에 포함됐습니다. 0.5005~28.5285초에 29장이 추가됐고 새 탐지 타임스탬프는 없었습니다. 두 실행의 추출 JPG 89장을 원본을 재디코딩해 인코딩한 JPG와 바이트 단위로 대조했습니다. 샘플링 인덱스, 해상도, `frame_index / FPS` 추정 시각 및 디코더 시각과의 연결이 일치했습니다. 두 실행에서 `detections.csv`는 헤더만 기록됐고 `events.json`은 빈 배열이며 `scenes/`는 비어 있습니다. 실영상 박스 위치와 구간 통합 및 대표 JPG 연결을 확인할 탐지 사례는 0건이었습니다.

- 1.0초 실행. [프레임 CSV](../../data/processed/frames/road_sample_04_1s/frames.csv) · [요약 JSON](../../outputs/video_analysis/road_sample_04_1s/summary.json) · [탐지 CSV](../../outputs/video_analysis/road_sample_04_1s/detections.csv) · [구간 JSON](../../outputs/video_analysis/road_sample_04_1s/events.json)
- 0.5초 실행. [프레임 CSV](../../data/processed/frames/road_sample_04_05s/frames.csv) · [요약 JSON](../../outputs/video_analysis/road_sample_04_05s/summary.json) · [탐지 CSV](../../outputs/video_analysis/road_sample_04_05s/detections.csv) · [구간 JSON](../../outputs/video_analysis/road_sample_04_05s/events.json)

### 수동 검토 이미지와 샘플링 확인

원본 노면을 약 0.25초 간격으로 훑어보고, 파손이 의심되는 자국이 보이는 원본 크기 JPG 5장을 `outputs/video_analysis/road_sample_04_manual_review/`에 저장했습니다. 표의 시각은 원본 영상 기준입니다. 이미지는 디코딩한 프레임을 박스나 라벨 없이 인코딩했습니다. 아래 관찰은 육안 검토이며, 실제 파손 여부와 유형은 모두 판단 보류입니다. [검토 프레임과 원본 시각 CSV](../../outputs/video_analysis/road_sample_04_manual_review/review_frames.csv)

| 프레임 | 원본 시각 | 1초 입력 | 0.5초 입력 | 육안 관찰 |
| ---: | ---: | --- | --- | --- |
| 150 | 5.005000초 | 포함 | 포함 | 차로 중앙 왼쪽에 끊어진 가는 어두운 선이 보입니다. [JPG](../../outputs/video_analysis/road_sample_04_manual_review/review_frame_000150.jpg) |
| 480 | 16.016000초 | 포함 | 포함 | 차로 중앙 왼쪽의 긴 선형 자국이 여러 갈래로 나뉘어 보입니다. [JPG](../../outputs/video_analysis/road_sample_04_manual_review/review_frame_000480.jpg) |
| 510 | 17.017000초 | 포함 | 포함 | 우측 방호벽 가까운 차로에 짧고 불규칙한 선이 여러 개 보입니다. [JPG](../../outputs/video_analysis/road_sample_04_manual_review/review_frame_000510.jpg) |
| 517 | 17.250567초 | 미포함 | 미포함 | 우측 전방의 그물 모양 자국이 더 가까이 보입니다. [JPG](../../outputs/video_analysis/road_sample_04_manual_review/review_frame_000517.jpg) |
| 525 | 17.517500초 | 미포함 | 포함 | 차로 우측 가까운 노면에 불규칙하게 교차하는 굵은 선이 보입니다. [JPG](../../outputs/video_analysis/road_sample_04_manual_review/review_frame_000525.jpg) |

17.017초에 우측 노면 자국이 두 실행의 입력에 들어갔습니다. 0.5초 실행에는 같은 주행 구간의 17.5175초 프레임이 추가됐습니다. 두 샘플링에서 빠진 17.250567초 프레임을 같은 모델과 임계값에 직접 입력한 결과도 0건이었습니다. 다른 순간의 샘플링 누락 가능성은 남습니다.

### 탐지 0건의 원인 점검과 후속 검증

- **모델과 추론.** 같은 체크포인트를 다시 로드해 0.5초 실행의 JPG 59장 각각에서 CUDA 추론 결과를 받았습니다. 59장 모두 박스 0개였으며, 이 재추론에서 Ultralytics가 기록한 프레임당 평균 추론 시간은 12.15 ms였습니다. 같은 설정을 사용한 Czech v2 검증 이미지 `Czech_000370`에서는 D00 박스 7개가 반환됐고 최고 confidence는 0.5599였습니다. [검증 이미지](../../data/yolo/rdd2022_czech_v2/images/val/Czech_000370.jpg)
- **촬영 조건.** 확인한 Czech v2 학습 이미지 두 장은 600×600의 정사각형 프레임이고, 흐린 하늘 아래 차도와 가까운 노면이 화면 하단에 넓게 보입니다. `road_sample_04`에서는 대시보드와 룸미러가 화면의 큰 부분을 차지하고, 낮은 각도의 햇빛과 앞유리 반사가 보입니다. 전체 영상 폭을 1920에서 640으로 줄이면 좁은 선형 자국도 함께 축소됩니다. 이번 관찰만으로 조명, 화각, 노면 차이가 탐지에 미친 영향을 정량화하기는 어렵습니다. [Czech D00 학습 이미지](../../data/yolo/rdd2022_czech_v2/images/train/Czech_000047.jpg) · [Czech D40 학습 이미지](../../data/yolo/rdd2022_czech_v2/images/train/Czech_000814.jpg)
- **추가 검증.** 위 구간의 자국이 실제 파손인지 확인하고, 주간·역광과 촬영 각도가 다른 라벨 있는 영상에서 모델 출력을 비교할 필요가 있습니다. 탐지가 발생한 실제 영상으로 이벤트 경계, 과통합 여부, 대표 JPG와 재생 시각 연결을 검증할 항목으로 남겼습니다.

**Part 6 FastAPI + React MVP 연동은 진행 가능합니다.** 실제 MP4를 처리하고 성공 상태에서 빈 결과를 저장하는 흐름을 다시 확인했습니다. 이 영상은 의심 장면이 보이더라도 탐지 0건이 반환될 수 있는 검증 사례로 활용할 수 있습니다.

### 재현 명령어와 회귀 검증

프로젝트 루트에서 실행했습니다. 재실행할 때는 새 `--run-name`을 지정합니다.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts\analyze_video.py .\data\raw\road_sample_04.mp4 --interval 1.0 --run-name road_sample_04_1s
.\.venv\Scripts\python.exe -B -X utf8 scripts\analyze_video.py .\data\raw\road_sample_04.mp4 --interval 0.5 --run-name road_sample_04_05s
.\.venv\Scripts\python.exe -B -X utf8 -m unittest -v tests.test_video_analysis tests.test_detection_grouping
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -v
```

추가 검증 내용을 기록한 뒤 영상 분석 관련 테스트 14개와 전체 회귀 테스트 41개를 실행해 모두 통과했습니다.
