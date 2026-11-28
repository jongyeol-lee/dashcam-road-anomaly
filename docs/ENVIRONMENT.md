# 개발환경 버전 관리

Part 6.5에서 기존 환경을 재검증했습니다. Python 3.14.5, torch 2.14.1+cu130, torchvision 0.29.1+cu130, Ultralytics 8.4.215, OpenCV 5.0.0.93, FastAPI 0.165.0, Uvicorn 0.54.0, openpyxl 3.1.5 조합으로 실제 후방 MP4를 디코딩하고 RTX 3060 Ti에서 FP32 입력 72장을 처리했습니다. 드라이버는 581.15, PyTorch 빌드는 CUDA 13.0입니다. [최종 실측과 검증 조건](experiments/part6_final_service_validation.md)

확인일 **2026-11-19 (KST)** · 개발환경 구축 및 재구성 검증

## 기존 프로젝트에서 확인한 버전

`C:\Projects\neighborhood-rescue\.venv`의 `pyvenv.cfg`, `Scripts\python.exe` 파일 속성, 패키지의 `.dist-info/METADATA`, `torch/version.py`를 읽어 확인했습니다. 과거 작업 기록은 요청에서 제공된 버전 목록을 기준으로 비교했습니다. 당시의 실행 결과와 호환성은 미확인입니다.

| 항목 | 이전 가상환경에서 확인 | 과거 작업 기록과 비교 |
| --- | --- | --- |
| Python 인터프리터 | `3.14.5` | 기록과 일치 |
| PyTorch (`torch`) | `2.14.1+cu130` | 기록에 `2.11.0+cu130`도 있으며, 해당 버전의 과거 설치·사용 시점은 미확인 |
| torchvision | `0.29.1+cu130` | 패키지 메타데이터에서 확인 |
| PyTorch CUDA 빌드 | `13.0` (빌드 태그 `cu130`) | `torch/version.py`와 패키지 태그에서 확인 |
| Ultralytics | `8.4.215` | 과거 기록은 `8.4.208` |
| OpenCV (`opencv-python`) | 배포본 `5.0.0.93` | 과거 기록은 `5.0.0`이며, 당시 배포본 버전과 현재 이전 환경의 `cv2.__version__` 출력은 미확인 |
| NumPy | `2.5.4` | 패키지 메타데이터에서 확인 |
| pandas | `3.1.1` | 패키지 메타데이터에서 확인 |

이전 프로젝트 환경에서의 NVIDIA 드라이버 버전, 드라이버가 지원했던 CUDA 버전, CUDA 텐서 연산 및 MP4 디코딩 결과는 미확인입니다.

## 현재 PC와 프로젝트 환경

| 항목 | 확인 결과 |
| --- | --- |
| OS | Windows NT `10.0.26300.0`, x64 |
| 가상환경 생성에 사용한 인터프리터 | `C:\Users\mbc\AppData\Local\Programs\Python\Python314\python.exe`, Python `3.14.5` |
| 프로젝트 가상환경 | `C:\Projects\dashcam-road-anomaly\.venv` |
| 프로젝트 인터프리터 | `C:\Projects\dashcam-road-anomaly\.venv\Scripts\python.exe`, Python `3.14.5` |
| pip | `26.1.1` |
| GPU | NVIDIA GeForce RTX 3060 Ti `8192 MiB`, Compute Capability `8.6` |
| NVIDIA 드라이버 | `581.15` |
| 드라이버 지원 CUDA | `13.0` (`nvidia-smi`의 `CUDA Version`) |
| PyTorch CUDA 빌드 | `13.0` (`torch.version.cuda`, wheel 태그 `cu130`) |
| 시스템 CUDA Toolkit | 설치 여부 미확인. 현재 셸에서 `nvcc` 명령을 찾을 수 없음 |
| 설치 전 C: 여유 공간 | `307.77 GiB` |

`nvidia-smi`는 드라이버가 지원하는 CUDA 버전을 보여 줍니다. `torch.version.cuda`는 설치된 PyTorch wheel의 빌드 버전을 보여 줍니다. PyTorch CUDA 런타임의 동작은 아래 GPU 시험으로 확인했습니다. [NVIDIA nvidia-smi 문서](https://docs.nvidia.com/deploy/nvidia-smi/index.html)

## 호환성 확인과 설치 버전

- Python 3.14.5는 공식 Windows x64 배포가 제공됩니다. 기설치 인터프리터를 실행해 `win-amd64`와 64비트를 확인했으며, `cp314`용 wheel을 사용할 수 있어 이 버전을 선택했습니다. [Python 3.14.5 배포본](https://www.python.org/downloads/release/python-3145/)
- PyTorch 공식 설치 표의 `2.14.1`·`0.29.1` 조합에 대해 CUDA 13.0 인덱스에 `cp314-cp314-win_amd64` wheel이 각각 게시되어 있습니다. 현 드라이버 `581.15`는 CUDA 13.0의 R580 계열 요구조건에 부합하며, RTX 3060 Ti에서 실제 연산을 확인했습니다. [PyTorch 설치 표](https://pytorch.org/get-started/previous-versions/) · [torch wheel](https://download.pytorch.org/whl/cu130/torch/) · [torchvision wheel](https://download.pytorch.org/whl/cu130/torchvision/) · [NVIDIA CUDA 호환성](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)
- Ultralytics 배포본은 Windows에서 Python `>=3.8`, NumPy `>=1.23.0`, OpenCV `>=4.7.0,!=4.13.0.90`, PyTorch `>=1.8.0,!=2.4.0` 및 torchvision `>=0.9.0` 조건을 적용합니다. OpenCV Windows x64 `abi3` wheel은 Python 3.9 이상에서 NumPy `>=2`를 요구합니다. NumPy `2.5.4`는 Python `>=3.12`를 지원하고 Windows x64용 `cp314` wheel을 제공합니다. [Ultralytics 배포본](https://pypi.org/project/ultralytics/8.4.215/) · [OpenCV 배포본](https://pypi.org/project/opencv-python/5.0.0.93/) · [NumPy 배포본](https://pypi.org/project/numpy/2.5.4/)

| 항목 | 설치 목표 및 실제 확인 버전 | 설치 출처 |
| --- | --- | --- |
| `torch` | `2.14.1+cu130` | `https://download.pytorch.org/whl/cu130` |
| `torchvision` | `0.29.1+cu130` | `https://download.pytorch.org/whl/cu130` |
| `ultralytics` | `8.4.215` | PyPI |
| `opencv-python` | 배포본 `5.0.0.93`, `cv2.__version__` 출력 `5.0.0` | PyPI |
| `numpy` | `2.5.4` | PyPI |

OpenCV 배포본은 `opencv-python` 한 종류를 확인했습니다. pandas는 데이터 분석 단계에서 필요성을 판단하고, FastAPI와 React의 버전은 웹 개발 단계에서 결정합니다.

## 환경 재구성

프로젝트 루트에서 실행합니다. 아래 기본 Python 경로는 이 PC 기준입니다. 다른 PC에서는 확인한 Windows x64 Python 3.14.5 실행 파일 경로를 사용합니다. 새 가상환경을 만드는 명령은 `.venv`가 없는 작업 폴더에서 실행합니다.

```powershell
$basePython = 'C:\Users\mbc\AppData\Local\Programs\Python\Python314\python.exe'
& $basePython -I -B -S -m venv --without-scm-ignore-files .venv
if ($LASTEXITCODE -ne 0) { throw 'venv creation failed' }
$projectPython = '.\.venv\Scripts\python.exe'

& $projectPython -I -B -m pip --isolated --disable-pip-version-check --no-cache-dir install --only-binary=:all: --index-url https://download.pytorch.org/whl/cu130 'torch==2.14.1+cu130' 'torchvision==0.29.1+cu130'
if ($LASTEXITCODE -ne 0) { throw 'CUDA wheel installation failed' }

& $projectPython -I -B -m pip --isolated --disable-pip-version-check --no-cache-dir install --only-binary=:all: --index-url https://pypi.org/simple -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'requirements installation failed' }

& $projectPython --version
& $projectPython -m pip list
& $projectPython -m pip check
```

[requirements.txt](../requirements.txt)는 직접 의존성 5개의 버전을 고정합니다. 새 환경의 기본 PyPI 인덱스에서는 `pip install -r requirements.txt`만으로 `+cu130` wheel을 설치할 수 없으므로 공식 cu130 인덱스에서 PyTorch와 torchvision을 먼저 설치합니다. 두 번째 명령은 설치한 CUDA wheel을 유지하면서 나머지 패키지를 설치합니다. 하위 의존성은 pip가 해결하므로 재생성 시점에 따라 해당 버전이 달라질 수 있습니다.

독립된 임시 가상환경에서 동일한 인덱스와 순서로 CUDA wheel 및 `requirements.txt`를 설치해 환경을 재구성했습니다. 프로젝트 내부 pip 캐시를 사용했고, `pip check`, 라이브러리 import, CUDA 연산과 합성 MP4 시험을 재실행했습니다.

## 검증 결과

| 항목 | 2026-11-19 결과 |
| --- | --- |
| Python·pip·의존성 | 프로젝트 인터프리터와 pip 정상 실행. `pip check` 통과 |
| 라이브러리 import | `torch`, `torchvision`, `ultralytics`, `cv2`, `numpy` 성공 |
| CUDA 인식 | `torch.cuda.is_available()` → `True`, `cuda:0`에서 RTX 3060 Ti 확인 |
| CUDA 텐서 계산 | `[1, 2, 3] * 2` → `[2, 4, 6]`. CUDA 동기화 성공 |
| torchvision NMS | 겹치는 두 박스를 CUDA에서 처리해 유지 인덱스 `[0]` 확인 |
| OpenCV 합성 MP4 | `mp4v`, 쓰기·읽기 백엔드 `FFMPEG`. `160×96`, `10 FPS`, 6프레임 |
| 프레임·타임스탬프·해제 | 첫 3프레임 디코딩과 `0 / 100 / 200 ms` 확인. 쓰기와 읽기 핸들 해제 확인 |
| 실제 블랙박스 MP4 | 프로젝트에 테스트용 MP4가 없어 미검증 |
| 환경 재구성 | 새 임시 환경에서 설치와 동일 시험 통과 |

초기 제한 셸에서 기존 Python 실행 파일 접근이 거부되어, 접근 권한이 있는 Windows 사용자 실행으로 전환해 설치와 검증을 완료했습니다. 테스트 중 Ultralytics와 Matplotlib의 설정·캐시 위치는 프로젝트 가상환경 안으로 지정했습니다. 데이터셋과 YOLO 가중치는 이후 단계에서 별도로 다룹니다.

설치 전후 기본 Python 실행 파일의 해시와 전역 및 이전 프로젝트 가상환경의 패키지 메타데이터를 비교해 일치함을 확인했습니다.

### PyTorch와 torchvision GPU 연산 재실행

```powershell
$projectPython = '.\.venv\Scripts\python.exe'
@'
import torch
import torchvision

print("CUDA build:", torch.version.cuda)
if not torch.cuda.is_available():
    raise RuntimeError("PyTorch cannot access CUDA")

values = torch.tensor([1, 2, 3], device="cuda")
result = values * 2
boxes = torch.tensor([[0., 0., 10., 10.], [1., 1., 11., 11.]], device="cuda")
scores = torch.tensor([0.9, 0.8], device="cuda")
kept = torchvision.ops.nms(boxes, scores, 0.5)
torch.cuda.synchronize()
if not result.is_cuda or not kept.is_cuda or result.tolist() != [2, 4, 6] or kept.tolist() != [0]:
    raise RuntimeError("Unexpected CUDA operation result")

print(torch.cuda.get_device_name(result.device), result.tolist(), kept.tolist())
'@ | & $projectPython -I -B -
```

### 실제 블랙박스 MP4 확보 후 확인

`$sampleMp4`를 사용이 허용된 실제 영상 경로로 바꿉니다. 첫 프레임과 다음 프레임들의 타임스탬프를 확인하고, 디코딩 실패가 있으면 파일과 코덱 정보를 함께 기록합니다.

```powershell
$projectPython = '.\.venv\Scripts\python.exe'
$sampleMp4 = '.\data\raw\sample.mp4'
@'
import sys

import cv2

video = cv2.VideoCapture(sys.argv[1])
try:
    if not video.isOpened():
        raise RuntimeError("Could not open the MP4")
    print("Backend:", video.getBackendName())
    print("FPS:", video.get(cv2.CAP_PROP_FPS))
    for index in range(3):
        decoded, frame = video.read()
        if not decoded or frame is None or frame.size == 0:
            if index == 0:
                raise RuntimeError("Could not decode the first frame")
            break
        print("Frame:", index, frame.shape, video.get(cv2.CAP_PROP_POS_MSEC), "ms")
finally:
    video.release()
'@ | & $projectPython -I -B - $sampleMp4
```

## Part 6.1 웹 의존성 추가

**2026-11-25 (KST)** · 기존 `.venv`의 Python 3.14.5와 AI 패키지를 유지하고 로컬 백엔드·테스트에 필요한 웹 패키지만 추가했습니다. 설치 전 FastAPI·Uvicorn·python-multipart·Starlette·Pydantic은 미설치, httpx 0.28.1은 설치 상태였습니다. 프로젝트 Python 경로는 샌드박스에서 접근이 제한돼 권한을 확장한 실행으로 확인했습니다. 다른 Python이나 가상환경으로 교체하지 않았습니다.

| 패키지 | 설치 목표 = 실제 버전 | 변경 |
| --- | --- | --- |
| fastapi | 0.165.0 | 신규, API·업로드 경로 본문 제한 |
| uvicorn | 0.54.0 | 신규, localhost ASGI 서버 |
| python-multipart | 0.0.34 | 신규, multipart 업로드 |
| httpx | 0.28.1 | 기존 유지, API 테스트·실제 HTTP 검증 |
| starlette | 1.10.0 | 신규, 요청·FileResponse Range 처리 |
| pydantic | 2.14.4 | 신규, 응답·저장 결과 검증 |

신규 하위 의존성은 `pydantic-core 2.50.5`, `annotated-types 0.8.0`, `typing-inspection 0.4.5`, `annotated-doc 0.0.7`, `click 8.5.1`, `opentelemetry-api 1.45.2`입니다. 원격 추적 exporter나 telemetry 전송 설정은 추가하지 않았습니다. 기존 anyio 4.16.0·typing-extensions 4.16.0·h11 0.16.0 등은 유지했습니다. 11개 신규 패키지만 설치됐고 기존 패키지 교체는 없었습니다. [설치 계획](../outputs/fastapi_validation/part61_v1/install_plan.json) · [실제 설치 보고서](../outputs/fastapi_validation/part61_v1/install_result.json)

AI 패키지는 `torch 2.14.1+cu130`, `torchvision 0.29.1+cu130`, `ultralytics 8.4.215`, `opencv-python 5.0.0.93`, `numpy 2.5.4`로 기존과 같습니다. CUDA 빌드 13.0, `torch.cuda.is_available() == True`, RTX 3060 Ti에서 실제 텐서 연산과 MVP forward 69장 모두 `cuda:0`·FP32를 확인했습니다. 이번에 NVIDIA 드라이버 버전을 별도로 재조회하거나 변경하지 않았습니다.

웹 의존성은 [requirements-web.txt](../requirements-web.txt)에 분리했습니다. 설치 전 `pip install --dry-run --only-binary=:all:`로 Python 3.14 지원 wheel을 확인했고 Pydantic Core는 `cp314-cp314-win_amd64`, 나머지 신규 패키지는 범용 Python wheel이 선택됐습니다. FastAPI와 Uvicorn 공식 릴리스 기록 및 설치된 구현을 확인해 사용했습니다. [FastAPI 릴리스](https://fastapi.tiangolo.com/release-notes/) · [FastAPI 요청 본문 제한](https://fastapi.tiangolo.com/advanced/request-body-limits/) · [Uvicorn 릴리스](https://uvicorn.dev/release-notes/) · [Starlette FileResponse](https://starlette.dev/responses/#fileresponse)

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m pip --isolated --disable-pip-version-check --no-cache-dir install --only-binary=:all: --index-url https://pypi.org/simple -r requirements-web.txt
.\.venv\Scripts\python.exe -B -X utf8 -m pip check
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests
```

`pip check`는 `No broken requirements found.`, 전체 테스트는 151개 통과입니다. 실제 MP4의 전체 디코딩과 69개 샘플 추론, HTTP Range·JPEG 조회도 성공했습니다. Starlette 1.10.0 TestClient는 기존 httpx 사용에 대해 httpx2 전환 예정 경고를 내지만 현재 테스트는 통과합니다. 경고를 숨기거나 불필요한 패키지를 추가하지 않았습니다. [실측 결과와 한계](experiments/part6_fastapi_backend.md)

## Part 6.4-3 Excel 내보내기 의존성

**2026-11-27 (KST)** · Windows의 기존 Python 3.14.5 가상환경에서 `openpyxl`과 `et-xmlfile`이 미설치임을 확인했다. PyPI의 순수 Python wheel을 미리 확인한 뒤 `openpyxl 3.1.5`와 그 필수 의존성 `et-xmlfile 2.0.0`만 설치했다. 두 버전을 `requirements-web.txt`에 고정했다. 패키지 설치 출력에서 기존 패키지 교체는 없었으며 `pip check`와 Python 회귀 181개를 통과했다. XLSX에서 날짜·서식·필터를 생성하고 Windows Excel 16.0에서 열었다. [openpyxl 배포본](https://pypi.org/project/openpyxl/3.1.5/) · [실측 결과](experiments/part6_report_export.md#사용자-재검토-후-2차-개선)
