# 개발환경 버전 관리

확인일 **2026-11-19 (KST)** · 초기 구성 단계

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

## 현재 PC에서 확인한 시스템 정보

| 항목 | 2026-11-19 확인 결과 | 확인 방법 |
| --- | --- | --- |
| OS | Windows NT `10.0.26300.0`, x64 | `[System.Environment]::OSVersion.VersionString`, `[System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture` |
| GPU | NVIDIA GeForce RTX 3060 Ti, `8192 MiB` | `nvidia-smi` |
| NVIDIA 드라이버 | `581.15` | `nvidia-smi` |
| 드라이버 지원 CUDA | `13.0` | `nvidia-smi`의 `CUDA Version` |
| 시스템 CUDA Toolkit | 설치 여부 미확인 | 현재 셸에서 `nvcc` 명령을 찾을 수 없음 |
| 셸에서 실행 가능한 Python | 현재 셸에서 `py`와 `python` 명령을 찾을 수 없음 | `Get-Command py, python` |

`nvidia-smi`의 `CUDA Version`은 드라이버가 지원하는 CUDA 버전입니다. `torch.version.cuda`는 설치한 PyTorch가 빌드된 CUDA 버전이며, CUDA 런타임 의존성은 선택한 PyTorch 배포본을 기준으로 확인합니다. GPU에서 해당 런타임이 동작하는지는 CUDA 텐서 연산으로 검증합니다. 별도로 설치한 시스템 CUDA Toolkit은 `nvcc --version`으로 확인할 수 있습니다. [NVIDIA nvidia-smi 문서](https://docs.nvidia.com/deploy/nvidia-smi/index.html)

## 새 프로젝트 설치 목표와 실제 설치 버전

초기 구성 단계에서는 Windows에서 사용할 독립 `.venv`와 설치 후보만 정리했습니다. 개발환경 구축 단계에서 확인한 Python 인터프리터로 이 프로젝트의 `.venv`를 만들고, 실제 설치 버전과 검증 결과를 이 표에 기록합니다.

| 항목 | 설치 목표 또는 결정 기준 | 새 프로젝트 실제 설치 |
| --- | --- | --- |
| Python 인터프리터 | 버전 미정. `3.14.5`를 검토 후보로 두고 주요 패키지의 Windows용 배포본 지원 확인 | `.venv` 미생성 |
| PyTorch와 torchvision | 버전 미정. 선택한 Python과 Windows 아키텍처를 지원하는 공식 조합 선택 | 미설치 |
| PyTorch CUDA 빌드 | 버전 미정. 공식 배포본과 RTX 3060 Ti, NVIDIA 드라이버 호환성 확인 | 미설치 |
| Ultralytics | 버전 미정. 선택한 Python·PyTorch·torchvision 조합과 의존성 확인 | 미설치 |
| OpenCV (`opencv-python`) | 버전 미정. Windows용 배포본과 대상 MP4의 디코딩 검증 | 미설치 |
| NumPy | 버전 미정. Python 및 모델·영상 패키지의 의존성 요구사항 확인 | 미설치 |
| pandas | 버전 미정. 데이터 검증에 필요한 경우 선택한 Python과 NumPy 호환성 확인 후 설치 | 미설치 |
| FastAPI와 React | 웹 MVP 단계에서 필요한 버전과 프런트엔드 실행환경 결정 | 미설치 |

설치 전 공식 Windows용 PyTorch 배포본에서 Python, CUDA 빌드와 설치 인덱스를 확인하고, torchvision 호환 표에서 대응 버전을 확인합니다. 버전을 변경할 때는 변경 전후의 실제 버전, 변경 이유와 의존성 영향을 기록합니다. [PyTorch 설치 안내](https://pytorch.org/get-started/locally/) · [torchvision 호환 표](https://github.com/pytorch/vision#installation) · [NVIDIA CUDA 호환성](https://docs.nvidia.com/deploy/cuda-compatibility/)

## 다음 단계에서 실행할 버전 확인 명령어

프로젝트 루트의 PowerShell에서 실행합니다. 먼저 호스트의 Python 후보와 GPU를 확인합니다. `py -0p`와 `nvcc --version`은 해당 명령이 있을 때 실행됩니다.

```powershell
[System.Environment]::OSVersion.VersionString
[System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture
Get-Command py, python -ErrorAction SilentlyContinue | Select-Object Name, Source
if (Get-Command py -ErrorAction SilentlyContinue) { py -0p }
nvidia-smi
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
if (Get-Command nvcc -ErrorAction SilentlyContinue) { nvcc --version }
```

가상환경을 만들고 후보 패키지를 설치한 뒤에는 동일한 PowerShell 세션에서 프로젝트 전용 인터프리터로 확인합니다. `pip show`는 배포본 버전을, 임포트 결과는 실행 시 모듈 버전을 보여 줍니다.

```powershell
$projectPython = '.\.venv\Scripts\python.exe'
& $projectPython --version
& $projectPython -c "import sys; print(sys.executable)"
& $projectPython -m pip show torch torchvision ultralytics opencv-python numpy
# pandas를 설치한 경우
# & $projectPython -m pip show pandas
& $projectPython -m pip check

@'
import cv2
import numpy
import torch
import torchvision
import ultralytics

for module in (torch, torchvision, ultralytics, cv2, numpy):
    print(module.__name__, module.__version__)
print("PyTorch CUDA build:", torch.version.cuda)
print("CUDA available:", torch.cuda.is_available())
'@ | & $projectPython -
```

## 호환성 검증 절차와 현재 결과

| 검증 항목 | 2026-11-19 결과 |
| --- | --- |
| 현 장비의 GPU 및 드라이버 인식 | `nvidia-smi`에서 확인 |
| Windows용 Python 및 패키지 배포본 조합 | 미확정 |
| 프로젝트 패키지 설치, 임포트, `pip check` | 미실행 |
| PyTorch CUDA 텐서 연산, torchvision GPU 연산 | 미실행 |
| OpenCV MP4 열기 및 프레임 추출 | 미실행 |

### PyTorch와 torchvision GPU 연산

CUDA 텐서 연산 결과와 GPU에서 실행한 torchvision NMS 결과를 확인합니다.

```powershell
@'
import torch
import torchvision

if not torch.cuda.is_available():
    raise RuntimeError("PyTorch cannot access CUDA")

values = torch.tensor([1, 2, 3], device="cuda")
result = values * 2
boxes = torch.tensor([[0., 0., 10., 10.], [1., 1., 11., 11.]], device="cuda")
scores = torch.tensor([0.9, 0.8], device="cuda")
kept = torchvision.ops.nms(boxes, scores, 0.5)
torch.cuda.synchronize()

if result.tolist() != [2, 4, 6] or kept.tolist() != [0]:
    raise RuntimeError("Unexpected CUDA operation result")

print(torch.cuda.get_device_name(result.device), result.tolist(), kept.tolist())
'@ | & $projectPython -
```

### OpenCV MP4 열기와 프레임 추출

`$sampleMp4`를 사용이 허용된 실제 블랙박스 영상 경로로 바꿉니다. 읽기 전용으로 열어 첫 프레임이 디코딩되는지 확인하고, 영상의 코덱과 OpenCV 백엔드, 결과를 기록합니다.

```powershell
$sampleMp4 = '.\data\raw\sample.mp4'
@'
import sys

import cv2

video = cv2.VideoCapture(sys.argv[1])
try:
    if not video.isOpened():
        raise RuntimeError("Could not open the MP4")
    success, frame = video.read()
    if not success or frame is None or frame.size == 0:
        raise RuntimeError("Could not decode the first frame")
    print("Backend:", video.getBackendName())
    print("Frame shape:", frame.shape)
finally:
    video.release()
'@ | & $projectPython - $sampleMp4
```

호환성 검증 후 확인 날짜, 실제 설치 버전, PyTorch 배포본의 설치 인덱스와 테스트 결과를 기록합니다. 프로젝트에 필요한 패키지와 버전은 그 결과에 따라 `requirements.txt` 등으로 확정합니다.
