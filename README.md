# 블랙박스 기반 AI 도로환경 이상 탐지

자동차 블랙박스 영상에서 도로 노면과 도로변 시설물의 이상 징후를 찾아 긴 영상을 검토하는 시간을 줄이는 프로젝트입니다. 초기에는 업로드가 끝난 MP4를 분석하는 비실시간 방식을 적용합니다. 사용자에게 의심 장면과 원본 영상 기준 타임스탬프를 제시해 실제 파손이나 위험 여부를 직접 확인할 수 있게 합니다.

## 주요 사용자 흐름

MP4 업로드 → 프레임 추출 → YOLO 추론 → 연속 프레임 중복 탐지 통합 → 의심 장면 및 타임스탬프 추출 → 사용자 확인

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
5. 연속 프레임에서 같은 대상을 탐지한 결과를 통합해 사용자에게 보여 줄 의심 장면과 타임스탬프를 생성합니다.
6. FastAPI와 React로 업로드, 분석 상태 조회, 의심 장면 확인을 제공하는 MVP를 구현합니다.

## 현재 구현 상태

Windows x64의 독립 가상환경에서 CUDA 텐서 연산과 torchvision NMS를 검증했습니다. OpenCV로 합성 MP4를 생성하고 지정한 시간 간격으로 JPG와 타임스탬프 CSV를 추출할 수 있습니다. 데이터셋 확보와 품질 검증, 실제 블랙박스 영상 테스트, 모델 학습·평가, 웹 서비스 구현은 예정 단계입니다.

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

## MP4 프레임 추출

프로젝트 루트에서 합성 MP4를 생성하고 1초 간격으로 프레임을 추출합니다.

```powershell
.\.venv\Scripts\python.exe -B scripts\make_test_video.py
.\.venv\Scripts\python.exe -B scripts\extract_frames.py data\raw\test_3sec.mp4 --interval 1
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

합성 영상은 `data/raw/test_3sec.mp4`에 저장됩니다. 생성 경로를 바꾸려면 `--output`을 사용합니다. 추출 결과는 기본으로 `data/processed/frames/<영상파일명에서 확장자를 뺀 이름>/`에 저장되며, `--output-dir`로 바꿀 수 있습니다. 재실행할 때는 새로운 영상 저장 경로나 비어 있는 추출 폴더를 지정합니다.

추출은 0초부터 시작하며, 각 간격의 기준 시각에 도달한 첫 프레임을 저장합니다. `frames.csv`에는 원본 프레임 번호 `frame_index`(0부터 시작), `frame_index / FPS`로 계산한 `estimated_time_sec`, 프레임을 읽은 직후 OpenCV가 반환한 `decoder_time_ms`, JPG 파일명 `image_file`이 기록됩니다. 가변 FPS 영상에서는 추출 시점과 추정 시간이 실제 표시 시각과 다를 수 있습니다. 디코더 시간은 영상과 OpenCV 백엔드가 제공하는 값입니다.
