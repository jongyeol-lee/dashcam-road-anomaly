# Part 5.5 — MVP 모델 설정과 실제 MP4 분석

**2026-11-25 · 전방 234개 박스 → 검토 구간 9개, 후방 49개 → 13개.** 두 영상에서 샘플링한 141장을 모두 추론했고, 구간별 대표 장면 22개의 원본 영상 시각과 박스를 확인했습니다. 전방 D00은 첫 프레임부터 마지막 프레임까지 한 구간에 묶였습니다. 판독할 때는 대표 장면에서 원본의 앞뒤 시각도 함께 봐야 합니다. [전방 실행 요약](../../outputs/video_analysis/part55_mvp_front/summary.json) · [후방 실행 요약](../../outputs/video_analysis/part55_mvp_rear/summary.json)

## 모델 선택과 실행 환경

시작 시 `main...origin/main`의 HEAD는 `f3289b2`였고 작업 트리는 깨끗했습니다. Windows, 프로젝트 Python 3.14.5, PyTorch 2.14.1+cu130, torchvision 0.29.1+cu130, Ultralytics 8.4.215, OpenCV 5.0.0, RTX 3060 Ti 8 GiB(드라이버 581.15)를 사용했습니다.

Part 5.4의 진단용 PNG 11장에서 confidence 0.05일 때 혼합 모델 960과 1280은 확정 D20 5개를 모두 탐지했습니다. 1280에서 정상 배경 FP는 4개, 추가 검토는 26개였습니다. 고정 ROI B는 이전 비교에서 실제 D20 정탐도 제거했습니다. 이 근거로 사용자가 지정한 **혼합 모델 1280, 전체 프레임**을 MVP v1의 잠정 프로필로 연결했습니다. 샘플링 0.5초와 인접 탐지 간격 1.5초의 최적성은 미검증입니다. [입력 해상도 실험](part5_dashcam_resolution_evaluation.md) · [ROI B 실험](part5_dashcam_model_roi_evaluation.md)

| 항목 | 실제 MP4 실행 조건 |
| --- | --- |
| 가중치 | `outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/weights/best.pt` |
| 파일 검증 | SHA-256 `3d770f1515ef2baf2fbe25d4c9ba241d289254b2002894d7cc02ff56009b2afb`, 탐지 모델, 0=D00, 1=D10, 2=D20, 3=D40 |
| 입력과 후처리 | 전체 JPG, 정사각 letterbox, `rect=False`, confidence 0.05, 클래스별 NMS IoU 0.7, `max_det=300`. ROI·Crop·타일링·추가 증강 꺼짐 |
| 모델 입력 관측 | 전방 69회·후방 72회 모두 forward 직전 `1×3×1280×1280`, `torch.float32`, `cuda:0`. 워밍업은 실제 프레임 수에서 제외 |

기존 `extract_frames()`로 MP4를 디코딩하고 추출한 JPG 디렉터리를 YOLO에 전달했습니다. `frames.csv`로 모든 추론 결과의 원본 번호와 시각을 대응시키고, `group_detections()`와 기존 대표 장면 그리기·저장 코드를 재사용했습니다. Baseline 호출의 기본값은 기존 Czech 가중치·640·1초·장치 자동 선택입니다. CLI와 Python은 같은 프로필을 사용합니다. 개별 옵션을 명시한 경우 해당 값이 우선하며, 선택값과 실제 MVP 텐서 형상은 실행별 요약에 기록합니다. [분석 함수](../../src/road_anomaly/video_analysis.py) · [프레임 추출](../../src/road_anomaly/video.py) · [구간 통합](../../src/road_anomaly/detection_grouping.py) · [CLI](../../scripts/analyze_video.py)

## 실제 실행 명령

프로젝트 루트의 별도 프로세스에서 다음 순서로 한 편씩 실행했습니다. 각 실행은 고유 이름을 사용합니다. 재실행 시 새 이름을 선택해야 합니다.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts\analyze_video.py data\raw\dashcam_validation\Dashcam-Front.mp4 --profile mvp --run-name part55_mvp_front
.\.venv\Scripts\python.exe -B -X utf8 scripts\analyze_video.py data\raw\dashcam_validation\Dashcam-Rear.mp4 --profile mvp --run-name part55_mvp_rear
```

## 영상별 처리 결과

두 영상 모두 1920×1080, 30 FPS입니다. 원본 번호는 0부터 시작하며, 15프레임마다 샘플링했습니다. 재생 시간은 전체 프레임 수를 FPS로 나눈 값입니다.

| 영상 | 전체 프레임 | 재생(초) | 추출 / 추론 | 첫 시각~마지막 샘플(초) | 탐지 프레임 | 박스 | 의심 구간 | 감소율 |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 전방 | 1,021 | 34.033 | 69 / 69 | 0.0~34.0 | 66 | 234 | 9 | 96.15% |
| 후방 | 1,080 | 36.000 | 72 / 72 | 0.0~35.5 | 21 | 49 | 13 | 73.47% |

| 클래스 | 전방 박스 | 전방 구간 | 후방 박스 | 후방 구간 |
| --- | ---: | ---: | ---: | ---: |
| D00 | 195 | 1 | 6 | 3 |
| D10 | 2 | 1 | 7 | 2 |
| D20 | 18 | 2 | 18 | 3 |
| D40 | 19 | 5 | 18 | 5 |
| 합계 | 234 | 9 | 49 | 13 |

감소율은 `1 − 구간 수 / 박스 수`입니다. 박스가 없으면 JSON의 값은 `null`(N/A)입니다. 22개는 이 두 영상에서 제시할 검토 구간 수입니다. 영상 전체에 대한 독립 GT가 없어 실제 파손 수, 정밀도, 재현율은 산출할 수 없습니다.

## 구간별 시각과 대표 장면

시작·마지막·대표 시각의 단위는 초입니다. 대표 프레임은 구간 안에서 confidence가 가장 높은 탐지의 원본 프레임입니다. 각 ID는 해당 JPG를 열며, JSON에는 대표 박스의 원본 좌표 `[x1,y1,x2,y2]`와 confidence도 있습니다. [전방 events.json](../../outputs/video_analysis/part55_mvp_front/events.json) · [후방 events.json](../../outputs/video_analysis/part55_mvp_rear/events.json)

| 영상 | 구간 ID | 클래스 | 시작 | 마지막 | 대표 | 원본 번호 | 박스 수 | 탐지 프레임 수 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 전방 | [0001](../../outputs/video_analysis/part55_mvp_front/scenes/event_0001.jpg) | D00 | 0.0 | 34.0 | 27.0 | 810 | 195 | 63 |
| 전방 | [0002](../../outputs/video_analysis/part55_mvp_front/scenes/event_0002.jpg) | D20 | 1.5 | 1.5 | 1.5 | 45 | 1 | 1 |
| 전방 | [0003](../../outputs/video_analysis/part55_mvp_front/scenes/event_0003.jpg) | D40 | 1.5 | 1.5 | 1.5 | 45 | 3 | 1 |
| 전방 | [0004](../../outputs/video_analysis/part55_mvp_front/scenes/event_0004.jpg) | D40 | 9.0 | 9.0 | 9.0 | 270 | 1 | 1 |
| 전방 | [0005](../../outputs/video_analysis/part55_mvp_front/scenes/event_0005.jpg) | D20 | 10.5 | 17.0 | 17.0 | 510 | 17 | 7 |
| 전방 | [0006](../../outputs/video_analysis/part55_mvp_front/scenes/event_0006.jpg) | D40 | 11.5 | 11.5 | 11.5 | 345 | 1 | 1 |
| 전방 | [0007](../../outputs/video_analysis/part55_mvp_front/scenes/event_0007.jpg) | D40 | 14.0 | 17.5 | 15.5 | 465 | 10 | 5 |
| 전방 | [0008](../../outputs/video_analysis/part55_mvp_front/scenes/event_0008.jpg) | D10 | 18.0 | 19.5 | 19.5 | 585 | 2 | 2 |
| 전방 | [0009](../../outputs/video_analysis/part55_mvp_front/scenes/event_0009.jpg) | D40 | 28.0 | 29.5 | 28.5 | 855 | 4 | 3 |
| 후방 | [0001](../../outputs/video_analysis/part55_mvp_rear/scenes/event_0001.jpg) | D00 | 1.0 | 1.0 | 1.0 | 30 | 1 | 1 |
| 후방 | [0002](../../outputs/video_analysis/part55_mvp_rear/scenes/event_0002.jpg) | D20 | 4.0 | 4.0 | 4.0 | 120 | 2 | 1 |
| 후방 | [0003](../../outputs/video_analysis/part55_mvp_rear/scenes/event_0003.jpg) | D40 | 4.0 | 5.0 | 4.5 | 135 | 6 | 3 |
| 후방 | [0004](../../outputs/video_analysis/part55_mvp_rear/scenes/event_0004.jpg) | D10 | 5.0 | 5.5 | 5.0 | 150 | 5 | 2 |
| 후방 | [0005](../../outputs/video_analysis/part55_mvp_rear/scenes/event_0005.jpg) | D40 | 13.5 | 13.5 | 13.5 | 405 | 1 | 1 |
| 후방 | [0006](../../outputs/video_analysis/part55_mvp_rear/scenes/event_0006.jpg) | D00 | 15.0 | 16.5 | 16.5 | 495 | 4 | 3 |
| 후방 | [0007](../../outputs/video_analysis/part55_mvp_rear/scenes/event_0007.jpg) | D20 | 16.5 | 18.5 | 18.5 | 555 | 14 | 4 |
| 후방 | [0008](../../outputs/video_analysis/part55_mvp_rear/scenes/event_0008.jpg) | D40 | 16.5 | 17.5 | 17.5 | 525 | 6 | 2 |
| 후방 | [0009](../../outputs/video_analysis/part55_mvp_rear/scenes/event_0009.jpg) | D00 | 19.0 | 19.0 | 19.0 | 570 | 1 | 1 |
| 후방 | [0010](../../outputs/video_analysis/part55_mvp_rear/scenes/event_0010.jpg) | D10 | 20.0 | 21.5 | 21.5 | 645 | 2 | 2 |
| 후방 | [0011](../../outputs/video_analysis/part55_mvp_rear/scenes/event_0011.jpg) | D40 | 30.0 | 30.0 | 30.0 | 900 | 1 | 1 |
| 후방 | [0012](../../outputs/video_analysis/part55_mvp_rear/scenes/event_0012.jpg) | D20 | 31.5 | 31.5 | 31.5 | 945 | 2 | 1 |
| 후방 | [0013](../../outputs/video_analysis/part55_mvp_rear/scenes/event_0013.jpg) | D40 | 33.5 | 35.5 | 35.5 | 1065 | 4 | 4 |

원본 MP4 2,101프레임을 다시 디코딩해 샘플 위치를 재구성했습니다. 추출 JPG 141장이 원본의 해당 프레임을 다시 인코딩한 바이트와 일치했고, 모든 샘플에서 번호/FPS와 디코더 시각의 차이는 0 ms였습니다. 박스 283개의 XYXY가 원본 크기 안에 있고 각 박스가 같은 클래스의 구간 한 곳에 속하는지 대조했습니다. 22개 구간의 탐지 수·시각과 최고 confidence를 다시 계산하고 해당 박스와 텍스트를 원본 샘플에 그렸을 때 저장된 대표 JPG와 모두 일치했습니다. 가변 FPS 영상은 디코더와 추정 시각이 달라질 수 있습니다. [전방 frames.csv](../../data/processed/frames/part55_mvp_front/frames.csv) · [후방 frames.csv](../../data/processed/frames/part55_mvp_rear/frames.csv) · [검증 결과](../../outputs/video_analysis/part55_mvp_front/verification.json)

### 과도하게 통합된 두 구간

- **전방 D00, 0.0~34.0초.** 63개 프레임의 195개 박스가 한 구간입니다. 17초 한 장에서 화면 좌·중·우에 9개가 잡혔고, 대표 시각 전후인 26.5·27.0·27.5초에는 각각 1·3·6개가 잡혔습니다. 0·17·34초 사이에 보이는 도로 위치와 진행 장면도 바뀝니다. 대표인 27초(810번)는 그중 박스 하나만 표시합니다. 원본 XYXY는 반올림해 (1206, 790, 1275, 885)입니다. [전방 인접 프레임과 전체 구간 비교](../../outputs/video_analysis/part55_mvp_front/group_review.jpg)
- **후방 D40, 4.0~5.0초.** 3개 프레임의 6개 박스가 한 구간입니다. 4.5초(135번)에는 왼쪽에 겹친 박스 두 개와 오른쪽에 떨어진 박스 한 개가 함께 있습니다. 대표는 오른쪽 박스 (1496, 592, 1654, 659)입니다. 5초에도 화면 왼쪽 끝과 중앙 오른쪽에 박스가 나뉩니다. 시간 간격이 짧아도 같은 프레임의 서로 다른 위치가 묶입니다. [후방 인접 프레임 비교](../../outputs/video_analysis/part55_mvp_rear/group_review.jpg)

1.5초 제한은 **인접한 두 탐지 사이**에 적용됩니다. 중간의 탐지가 이어지면 그룹 전체의 길이는 1.5초를 넘으며, 공간상 동일 대상인지 판정하는 과정은 없습니다. 대표 시각 하나로 해당 구간의 모든 위치를 설명하기 어렵습니다.

## 단계별 처리 시간

`perf_counter()`로 한 편씩 1회 측정했습니다. CUDA 초기화·워밍업 완료 직후와 실제 예측 결과를 모두 소비한 직후에 장치를 동기화했습니다. 모델은 영상마다 새로 로드했습니다.

| 영상 | 추출(초) | 모델 초기화(초) | 예측 처리(초) | 통합·저장(초) | 전체 분석(초) | 재생(초) | 분석/재생 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 전방 | 5.876 | 3.820 | 1.447 | 0.202 | 11.345 | 34.033 | 0.333 |
| 후방 | 4.838 | 3.401 | 1.459 | 0.272 | 9.970 | 36.000 | 0.277 |

- **추출**은 실행 폴더 생성, 전체 MP4 순차 디코딩, 샘플 JPG 및 `frames.csv` 저장을 포함합니다.
- **모델 초기화**는 가중치 해시 확인·로드, 클래스 확인, 장치 및 predictor 준비, 1280 워밍업을 포함합니다.
- **예측 처리**는 JPG 읽기, 전처리, GPU 연산, NMS·원본 좌표 복원, 박스의 CPU 회수와 전체 프레임 대조를 포함합니다. 추출 프레임당 평균은 전방 20.97 ms, 후방 20.26 ms입니다. Part 5.4의 19.24 ms/장은 이미 디코딩한 PNG의 단일 예측 호출 평균입니다. 영상 입력은 손실 압축된 JPG이므로 같은 원본 시각에서도 픽셀과 예측이 달라질 수 있습니다.
- **통합·저장**은 박스 CSV, 클래스별 그룹 생성, 대표 JPG와 구간 JSON 저장 및 집계를 포함합니다. 전체 분석 시간은 네 단계의 합입니다. CLI 시작·입력 사전 점검, 마지막 `summary.json` 직렬화·쓰기와 사후 검증은 측정 범위 밖입니다. 두 비율은 이 장비에서 파일별로 얻은 관측값입니다.

## Part 6.1 호출 규약

웹 분석 작업은 프로젝트의 `src`를 모듈 경로에 둔 환경에서 아래 동기 함수를 호출할 수 있습니다. 서비스의 기본 설정은 호출부에서 `profile="mvp"`로 선택합니다.

```python
import json
from pathlib import Path

from road_anomaly.video_analysis import analyze_video

def run_analysis(mp4_path: Path, job_id: str) -> dict:
    summary = analyze_video(mp4_path, run_name=job_id, profile="mvp")
    output_dir = Path(summary["output_dir"])
    events = json.loads((output_dir / "events.json").read_text(encoding="utf-8"))
    return {"summary": summary, "events": events}
```

| 반환값 또는 경로 | 사용 방법 |
| --- | --- |
| `summary` | 함수가 모든 저장을 완료한 뒤 반환하는 딕셔너리. 디스크의 `summary.json`과 같은 값이며, 실행 ID는 `run_name` |
| `summary["frames_dir"]` | 절대 경로 `data/processed/frames/<run_name>/` 아래 추출 JPG와 `frames.csv` |
| `summary["output_dir"]` | 절대 경로 `outputs/video_analysis/<run_name>/` 아래 `detections.csv`, `events.json`, `scenes/`, 마지막에 기록하는 `summary.json` |
| 구간 하나 | `start_time_sec`, `last_detection_time_sec`, `representative_time_sec`로 원본 재생 위치를 찾음. `output_dir / representative_image`로 대표 JPG를 찾고 `representative_xyxy`로 원본 픽셀 박스를 확인 |
| 탐지 0개 | 성공 반환, 헤더만 있는 박스 CSV, 빈 이벤트 배열과 장면 폴더, 감소율 `null` |
| 오류 | 잘못된 옵션은 `ValueError`, 입력·가중치 누락은 `FileNotFoundError`, 실행 이름 충돌은 `FileExistsError`. 디코딩·모델 로드·추론 실패 등은 예외로 전달되며 이번 실행에서 만든 폴더를 정리 |

이 단계에서 확인한 범위는 CLI와 Python 분석 함수입니다. FastAPI 업로드·작업 상태 조회 및 React 화면 연결은 Part 6 구현 대상입니다.

## 테스트와 보존 검사

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -p test_video_analysis.py
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests
```

분석 모듈 관련 테스트 13개, 전체 회귀 테스트 131개(기존 127개와 신규 4개)가 통과했습니다. 프로필 기본값·직접 지정값의 우선순위·CLI 전달, 매핑과 체크포인트 불일치, 비정상 입력, 640 호환성, 빈 탐지, 시간 경계, 대표 장면과 결과 형식, 누락 추론·이름 충돌·실패 정리를 확인했습니다. 무탐지 출력은 합성 MP4와 빈 예측을 반환하는 모델 대역으로 검증했습니다. 두 실제 MP4에서는 모두 탐지가 있었습니다. [영상 분석 테스트](../../tests/test_video_analysis.py) · [시간 통합 테스트](../../tests/test_detection_grouping.py)

작업 전후 `data/raw`, `data/processed`, `outputs`의 기존 파일 1,249개의 경로와 SHA-256이 일치했습니다. 여기에는 원본 두 영상, 가중치, 발행 GT와 이전 실험 파일이 포함됩니다. 공개 Test 폴더와 이번 신규 실행 폴더는 비교 범위에서 제외했습니다. [파일별 해시 목록](../../outputs/video_analysis/part55_mvp_front/protected_files.sha256) · [전후 대조 결과](../../outputs/video_analysis/part55_mvp_front/verification.json) · [기술 결정 기록](../ai_collaboration/07_mvp_video_pipeline.md)
