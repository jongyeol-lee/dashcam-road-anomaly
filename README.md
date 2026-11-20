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

Windows x64의 독립 가상환경에서 CUDA 텐서 연산과 torchvision NMS를 검증했습니다. OpenCV로 합성 MP4를 생성하고 지정한 시간 간격으로 JPG와 타임스탬프 CSV를 추출할 수 있습니다. RDD2022 Czech 이미지와 XML을 검증하고 YOLO 학습용 데이터셋으로 변환할 수 있습니다. Czech v2에서 YOLO11n Baseline 학습과 Validation 평가를 완료했으며, MP4 분석 CLI에서 이 모델로 의심 장면을 추출할 수 있습니다. 실제 블랙박스 영상 테스트와 웹 서비스 구현은 예정 단계입니다. [YOLO11n 실험 보고서](docs/experiments/yolo11n_baseline.md)

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

프로젝트 루트의 PowerShell에서 기존 YOLO11n Baseline으로 분석합니다. 첫 번째 명령은 입력 MP4 경로를 바꿔 실행합니다. 아래 두 명령은 3초짜리 합성 영상으로 전체 흐름을 확인하는 예시입니다.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts\analyze_video.py 'C:\path\to\dashcam.mp4' --run-name dashcam_01

.\.venv\Scripts\python.exe -B -X utf8 scripts\make_test_video.py --output 'data\raw\part5_synthetic.mp4'
.\.venv\Scripts\python.exe -B -X utf8 scripts\analyze_video.py 'data\raw\part5_synthetic.mp4' --run-name part5_smoke
```

기본 모델은 `outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/weights/best.pt`입니다. `--model`로 로컬 탐지용 `.pt` 경로를 지정할 수 있습니다. `--interval`의 기본값은 1.0초, `--confidence`는 0.05, `--max-gap`은 1.5초입니다. YOLO 입력 크기는 640, NMS IoU는 0.7입니다. 기본 `--device auto`는 CUDA 0을 우선 사용하고 CUDA가 없으면 CPU를 사용합니다. `--device cuda:0` 또는 `--device cpu`로 장치를 지정할 수 있습니다.

`--run-name`을 생략하면 UTC 시각으로 실행 이름을 만듭니다. 두 출력 위치 중 한 곳에 같은 이름이 있으면 실행을 중단합니다. 재실행에는 새 이름을 사용하며, 합성 영상을 다시 생성할 때는 새 MP4 경로를 지정합니다.

| 결과 경로 | 내용 |
| --- | --- |
| `data/processed/frames/<run_name>/` | 추출 원본 JPG와 `frames.csv` |
| `outputs/video_analysis/<run_name>/detections.csv` | 박스별 원본 프레임 번호, 추정 시간, 클래스, confidence, 원본 픽셀 좌표와 프레임 JPG 절대 경로 |
| `outputs/video_analysis/<run_name>/events.json` | AI 의심 구간 ID, 클래스, 시작·마지막 탐지 시각, 최고 confidence, 대표 프레임 시각과 JPG 상대 경로, 탐지 박스 수와 탐지 프레임 수 |
| `outputs/video_analysis/<run_name>/scenes/event_0001.jpg` | 구간에서 가장 높은 confidence를 기록한 박스, 클래스, confidence, 추정 시간을 표시한 대표 장면 |
| `outputs/video_analysis/<run_name>/summary.json` | 입력 영상, 모델 경로와 SHA-256, 실제 실행 설정, OpenCV 전체 프레임 수와 추출 수, 탐지 수와 의심 구간 수, 분석 소요 시간 |

탐지가 0건이면 `detections.csv`에는 헤더만, `events.json`에는 빈 배열을 기록하고 `scenes/`는 빈 폴더로 생성합니다. 결과 저장이 끝나면 `summary.json`을 기록합니다. 분석 중 오류가 발생하면 이번 실행 폴더를 정리합니다.

같은 클래스의 이웃 탐지 간격이 기준 이하면 하나의 AI 의심 구간에 들어갑니다. 시간상 가까운 별개의 균열이나 포트홀도 한 구간에 포함될 수 있습니다. 결과는 사용자가 원본 영상에서 확인할 후보입니다. Confidence 0.05와 통합 간격 1.5초는 탐색용 초기 설정입니다. 타임스탬프는 `frame_index / FPS` 추정값으로, 가변 FPS 영상에서는 재생 시각과 다를 수 있습니다. 실제 블랙박스 영상의 탐지 성능과 처리 시간은 별도 검증이 필요합니다.
