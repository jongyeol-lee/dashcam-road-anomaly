# 블랙박스 기반 AI 도로환경 이상 탐지

자동차 블랙박스 영상에서 도로 노면과 도로변 시설물의 이상 징후를 찾아 긴 영상을 검토하는 시간을 줄이는 프로젝트입니다. 초기에는 업로드가 끝난 MP4를 분석하는 비실시간 방식을 적용합니다. 사용자에게 의심 장면과 원본 영상 기준 타임스탬프를 제시해 실제 파손이나 위험 여부를 직접 확인할 수 있게 합니다.

## 주요 사용자 흐름

MP4 입력 → 프레임 추출 → YOLO 추론 → 클래스별 시간 기준 통합 → 의심 장면 및 타임스탬프 추출 → 사용자 확인

## 기술 스택과 개발환경

| 구분 | 기술 스택 계획 |
| --- | --- |
| 데이터 검증과 변환 | Python, NumPy, 필요 시 pandas |
| 모델 학습과 추론 | PyTorch, torchvision, Ultralytics YOLO |
| 영상 처리 | OpenCV |
| 최소 웹 서비스 | FastAPI, React |

초기 개발은 Windows와 NVIDIA GeForce RTX 3060 Ti 8 GB에서 진행할 계획입니다. 프로젝트 전용 `.venv`를 사용하고 Windows용 Python, PyTorch·torchvision, CUDA 빌드와 NVIDIA 드라이버의 조합을 확인한 뒤 의존성을 설치합니다. 설치 목표와 실제 버전, CUDA 연산 및 MP4 프레임 추출 검증 절차는 [개발환경 버전 관리 문서](docs/ENVIRONMENT.md)에 기록합니다.

## 데이터셋 후보

| 후보 | 검토 대상 |
| --- | --- |
| [AI-Hub 「지자체 도로부속시설물 파손 데이터」](https://aihub.or.kr/aihubdata/data/view.do?dataSetSn=71306) | 도로부속시설물의 정상·파손 라벨과 폴리곤 주석 |
| [RDD2022](https://rmets.onlinelibrary.wiley.com/doi/10.1002/gdj3.260) | 균열, 포트홀 등 도로 노면 파손 이미지와 라벨 |

데이터를 확보한 뒤 이용 조건, 라벨 품질, 클래스 분포와 실제 블랙박스 영상에서의 식별 가능성을 확인하고 초기 탐지 대상 1~2종을 선정합니다. 같은 영상이나 주행 구간의 프레임은 학습·검증·테스트 중 한 분할에만 포함합니다.

## 단계별 개발 계획

1. 데이터셋을 확보하고 이용 조건, 라벨 품질과 중복을 검증합니다.
2. YOLO Baseline을 학습하고 분리한 검증·테스트 데이터로 평가합니다.
3. 실제 블랙박스 영상의 오탐·미탐과 추론 시간을 분석해 모델을 개선합니다.
4. OpenCV로 MP4를 읽고 프레임과 원본 영상 기준 시간을 추출하는 파이프라인을 구현합니다.
5. 같은 클래스의 시간상 가까운 탐지를 통합해 사용자에게 보여 줄 의심 장면과 타임스탬프를 생성합니다.
6. FastAPI와 React로 업로드, 분석 상태 조회, 의심 장면 확인을 제공하는 MVP를 구현합니다.

## 현재 구현 상태

Windows x64의 프로젝트 가상환경에서 CUDA와 torchvision NMS를 검증하고, RDD2022 Czech 데이터 변환과 YOLO11n Baseline 학습·Validation 평가를 완료했습니다. MP4 분석 CLI와 Python 함수는 Czech Baseline과 Czech + Japan 혼합 모델을 지원합니다. 혼합 모델의 MVP 프로필로 실제 전·후방 영상 두 편에서 0.5초마다 추출한 141장 모두를 추론하고 대표 장면 22개를 원본 프레임과 대조했습니다. FastAPI 업로드·상태 조회와 React 결과 화면은 Part 6 구현 예정입니다. [Baseline 학습](docs/experiments/yolo11n_baseline.md) · [실제 MP4 검증](docs/experiments/part5_mvp_video_pipeline.md)

| 경로 | 용도 |
| --- | --- |
| `src/road_anomaly/` | 분석 패키지 코드 |
| `scripts/` | 데이터 검사·변환 및 실행 스크립트 |
| `tests/` | 테스트 코드 |
| `data/raw/` | 원본 영상·이미지와 라벨 |
| `data/processed/` | 전처리 산출물 |
| `data/yolo/` | YOLO 학습용 이미지와 라벨 |
| `outputs/` | 학습·추론·평가 산출물 |

데이터와 실험 산출물은 로컬에 보관합니다. 데이터 출처와 폴더 사용법은 `docs/` 또는 해당 경로 최상위 `README.md`에 기록할 수 있습니다.

## RDD2022 Czech 데이터 준비

프로젝트 루트에서 `--zip-path`에 원본 `Czech.zip` 경로를 지정합니다. 이미 풀린 데이터는 `train`과 `test`가 들어 있는 Czech 폴더를 `--czech-dir`로 지정할 수 있습니다. PowerShell에서 공백이나 `&`가 있는 경로는 작은따옴표로 감쌉니다.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts\prepare_rdd2022_czech.py --zip-path 'C:\path\to\Czech.zip'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

라벨이 있는 원본 Train 이미지를 seed 42와 80/10/10 목표 비율로 분할합니다. 분할마다 클래스별 객체와 등장 이미지, 빈 라벨 이미지가 고르게 들어가도록 배정합니다. JPG의 SHA-256 또는 128비트 dHash 해밍 거리 8 이하로 연결된 이미지 후보는 한 그룹에 배정합니다. 공식 Test의 이미지는 유사도 비교에 포함되고, mAP 평가용 Test는 라벨이 있는 Train에서 구성합니다. 주행 구간과 영상 ID 없이 시각적 유사도만 비교하므로 놓친 유사 장면으로 데이터 누수 가능성이 남습니다. [RDD2022 데이터 설명](https://crddc2022.sekilab.global/data/)

`data/processed/rdd2022_czech/`에 검사 결과와 `split_manifest.csv`, 변환한 라벨을 JPG에 표시한 미리보기가 저장됩니다. 파일 검사에 실패하면 `inspection_summary.json`에서 파일별 오류 유형과 원인을 확인할 수 있습니다. `data/yolo/rdd2022_czech/data.yaml`은 YAML 파일이 있는 폴더를 기준으로 Train·Val·Test 이미지 경로와 `D00`, `D10`, `D20`, `D40` 순서의 클래스를 정의합니다. 기존 출력 경로가 있다면 재실행 시 `--processed-dir`과 `--yolo-dir`로 새 경로를 지정합니다. [Ultralytics 탐지 데이터셋 형식](https://docs.ultralytics.com/datasets/detect)

## MP4 프레임 추출

프로젝트 루트에서 합성 MP4를 생성하고 1초 간격으로 프레임을 추출합니다.

```powershell
.\.venv\Scripts\python.exe -B scripts\make_test_video.py
.\.venv\Scripts\python.exe -B scripts\extract_frames.py data\raw\test_3sec.mp4 --interval 1
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

합성 영상은 `data/raw/test_3sec.mp4`에 저장됩니다. 생성 경로를 바꾸려면 `--output`을 사용합니다. 추출 결과는 기본으로 `data/processed/frames/<영상파일명에서 확장자를 뺀 이름>/`에 저장되며, `--output-dir`로 바꿀 수 있습니다. 재실행할 때는 새로운 영상 저장 경로나 비어 있는 추출 폴더를 지정합니다.

추출은 0초부터 시작하며, 각 간격의 기준 시각에 도달한 첫 프레임을 저장합니다. `frames.csv`에는 원본 프레임 번호 `frame_index`(0부터 시작), `frame_index / FPS`로 계산한 `estimated_time_sec`, 프레임을 읽은 직후 OpenCV가 반환한 `decoder_time_ms`, JPG 파일명 `image_file`이 기록됩니다. 가변 FPS 영상에서는 추출 시점과 추정 시간이 실제 표시 시각과 다를 수 있습니다. 디코더 시간은 영상과 OpenCV 백엔드가 제공하는 값입니다.

## MP4 도로환경 이상 분석

프로젝트 루트의 PowerShell에서 실행합니다. 첫 명령은 기존 Baseline을 사용하고, 둘째 명령은 MVP v1 프로필을 선택합니다. 아래 합성 영상 예시는 기존 기본값을 사용합니다.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts\analyze_video.py 'C:\path\to\dashcam.mp4' --run-name dashcam_01
.\.venv\Scripts\python.exe -B -X utf8 scripts\analyze_video.py 'data\raw\dashcam_validation\Dashcam-Front.mp4' --profile mvp --run-name front_mvp_01

.\.venv\Scripts\python.exe -B -X utf8 scripts\make_test_video.py --output 'data\raw\part5_synthetic.mp4'
.\.venv\Scripts\python.exe -B -X utf8 scripts\analyze_video.py 'data\raw\part5_synthetic.mp4' --run-name part5_smoke
```

| 설정 | Baseline (프로필 생략 또는 `--profile baseline`) | MVP v1 (`--profile mvp`) |
| --- | --- | --- |
| YOLO11n 가중치 | `outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/weights/best.pt` | `outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/weights/best.pt` |
| 입력 해상도 / 샘플링 간격 | 640 / 1초 | 1280 / 0.5초 |
| 장치 | `auto` (CUDA 0 우선, CPU 대체) | `cuda:0` |
| Confidence / NMS IoU / 최대 통합 간격 | 0.05 / 0.7 / 1.5초 | 0.05 / 0.7 / 1.5초 |

MVP는 전체 JPG를 정사각 입력으로 변환하고 배치 1, FP32, 클래스별 NMS, `rect=False`, `max_det=300`을 사용합니다. ROI·Crop·타일링·추가 증강은 꺼져 있습니다. 지정된 혼합 가중치의 SHA-256과 클래스 순서 D00·D10·D20·D40을 검사합니다. `--model`, `--imgsz`, `--interval`, `--confidence`, `--max-gap`, `--device`를 직접 지정하면 해당 값이 프로필보다 우선합니다. 예를 들어 `--profile mvp --imgsz 960`은 혼합 모델 입력 크기를 960으로 바꿉니다.

`--run-name`을 생략하면 UTC 시각으로 실행 이름을 만듭니다. 두 출력 위치 중 한 곳에 같은 이름이 있으면 실행을 중단합니다. 재실행에는 새 이름을 사용하며, 합성 영상을 다시 생성할 때는 새 MP4 경로를 지정합니다.

| 결과 경로 | 내용 |
| --- | --- |
| `data/processed/frames/<run_name>/` | 추출 원본 JPG와 `frames.csv` |
| `outputs/video_analysis/<run_name>/detections.csv` | 박스별 원본 프레임 번호, 추정 시간, 클래스, confidence, 원본 픽셀 좌표와 프레임 JPG 절대 경로 |
| `outputs/video_analysis/<run_name>/events.json` | 구간 ID와 클래스, 시작·마지막 탐지 시각, 박스·프레임 수, 최고 confidence, 대표 프레임 번호·시각·원본 픽셀 좌표 `representative_xyxy`, 대표 JPG 상대 경로 |
| `outputs/video_analysis/<run_name>/scenes/event_0001.jpg` | 구간에서 가장 높은 confidence를 기록한 박스, 클래스, confidence, 추정 시간을 표시한 대표 장면 |
| `outputs/video_analysis/<run_name>/summary.json` | 프로필, 모델 경로·해시, 적용 설정과 MVP 실측 텐서, 추출·추론·탐지 프레임 수, 클래스별 박스·구간 수, 감소 비율, 단계별 시간과 영상 길이 대비 분석 시간 |

탐지가 0건이면 `detections.csv`에는 헤더만, `events.json`에는 빈 배열을 기록하고 `scenes/`는 빈 폴더로 생성합니다. 결과 저장이 끝나면 `summary.json`을 기록합니다. 분석 중 오류가 발생하면 이번 실행 폴더를 정리합니다.

같은 클래스의 이웃 탐지 시각 차이가 1.5초 이하면 연속해서 한 구간에 들어갑니다. 검토자는 대표 시각을 기준으로 원본 전후 장면도 확인할 수 있습니다. 실제 전방 영상에서는 34초 동안 이어진 D00 박스 195개가 한 구간에 포함됐습니다. 구간 수는 사용자가 검토할 장면 수이며, 개별 파손 수와 일반화 성능은 확인되지 않았습니다. 샘플링·통합 간격은 잠정값이며 가변 FPS 영상의 `frame_index / FPS`는 실제 재생 시각과 다를 수 있습니다. [검토 이미지와 측정 결과](docs/experiments/part5_mvp_video_pipeline.md)

Part 6.1의 분석 작업에서는 `src`를 Python 모듈 경로에 둔 뒤 `road_anomaly.video_analysis.analyze_video(Path(mp4_path), profile="mvp", run_name=job_id)`를 호출합니다. 함수는 결과 저장을 마친 뒤 `summary.json`과 같은 딕셔너리를 반환합니다. `output_dir`를 기준으로 `events.json`을 읽고 각 항목의 `representative_image`를 결합하면 대표 장면을 찾을 수 있습니다. [반환값과 오류 처리](docs/experiments/part5_mvp_video_pipeline.md#part-61-호출-규약)
