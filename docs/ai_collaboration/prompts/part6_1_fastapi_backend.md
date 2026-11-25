# Part 6.1 — FastAPI 기반 블랙박스 영상 분석 백엔드 구현

## 1. 프로젝트 및 현재 상태

자동차 블랙박스 기반 AI 도로환경 이상 탐지 시스템을 개발하고 있습니다.

- 로컬 경로: `C:\Projects\dashcam-road-anomaly`
- GitHub: https://github.com/jongyeol-lee/dashcam-road-anomaly
- 브랜치: `main`
- 시작 기준 Commit: `4639237`
- Commit 메시지: `feat: MVP 모델 설정 및 블랙박스 영상 분석 파이프라인 연결`
- Part 5.5까지 완료 및 Commit / Push 완료
- 기존 전체 회귀 테스트: 131개 통과

### 전체 개발 로드맵

- Part 1~4: 데이터 검증, YOLO 학습 및 모델 개선 — 완료
- Part 5~5.4: 영상 분석, 실제 영상 평가 및 모델 성능 개선 — 완료
- Part 5.5: MVP 모델 선정 및 실제 MP4 분석 연결 — 완료
- Part 6.1: FastAPI 백엔드 구현 — 현재 작업
- Part 6.2: React + Vite 프론트엔드 구현
- Part 6.3: 웹 서비스 통합 및 사용자 흐름 검증
- Part 7: 독립 영상 검증 및 포트폴리오 정리

이번 작업의 목적은 기존 AI 분석 파이프라인을 FastAPI에서 호출하여 사용자가 영상을 업로드하고, 분석 상태 및 결과를 조회할 수 있도록 만드는 것입니다.

모델 재학습이나 새로운 AI 기술 도입은 하지 않습니다.

## 2. 개발 환경 및 작업 전 확인

- OS: Windows
- GPU: RTX 3060 Ti 8GB
- Python: 3.14.5
- PyTorch: 2.14.1+cu130
- Ultralytics: 8.4.215
- OpenCV: 5.0.0
- 프로젝트 전용 `.venv` 사용

실제 환경은 로컬 설치 상태와 `docs/ENVIRONMENT.md`를 기준으로 확인합니다.

먼저 `git status`, 현재 브랜치 및 HEAD를 확인하고 다음 파일과 관련 테스트를 살펴봐 주세요.

- `AGENTS.md`
- `README.md`
- `requirements.txt`
- `docs/ENVIRONMENT.md`
- `.gitignore`
- `src/road_anomaly/video.py`
- `src/road_anomaly/video_analysis.py`
- `src/road_anomaly/detection_grouping.py`
- `scripts/analyze_video.py`
- `tests/test_video_analysis.py`
- `docs/experiments/part5_mvp_video_pipeline.md`
- `docs/experiments/part5_dashcam_resolution_evaluation.md`
- `docs/ai_collaboration/`

기존 코드 구조와 사용자 변경사항을 보호하고 필요한 부분만 수정합니다.

FastAPI, Uvicorn, python-multipart, 테스트에 필요한 httpx 등의 설치 여부를 확인합니다.

필요한 웹 의존성만 Python 3.14 환경과의 호환성을 확인하여 추가하고, 실제 설치 버전을 기록합니다. 기존 PyTorch·CUDA·Ultralytics 환경은 변경하지 않습니다.

웹 의존성 파일을 별도로 관리하는 방식을 우선 검토합니다.

## 3. 기존 AI 분석 기능

Part 5.5에서 다음 함수를 구현하고 실제 영상으로 검증했습니다.

```python
from pathlib import Path
from road_anomaly.video_analysis import analyze_video

summary = analyze_video(
    Path(mp4_path),
    profile="mvp",
    run_name=job_id,
)
```

기존 Python 모듈 경로 설정을 확인하고 위 함수를 재사용합니다.

### MVP 분석 프로필

| 항목 | 설정 |
|---|---|
| 모델 | YOLO11n Czech + Japan 혼합 모델 |
| imgsz | 1280 |
| confidence | 0.05 |
| NMS IoU | 0.7 |
| Batch | 1 |
| 정밀도 | FP32 |
| rect | False |
| max_det | 300 |
| 샘플링 간격 | 0.5초 |
| 기존 통합 간격 | 1.5초 |
| ROI | 미적용 |
| 추론 장치 | CUDA 0 |

모델 경로:

`outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/weights/best.pt`

모델 SHA-256:

`3d770f1515ef2baf2fbe25d4c9ba241d289254b2002894d7cc02ff56009b2afb`

클래스:

- D00: 종방향 균열
- D10: 횡방향 균열
- D20: 거북등 균열
- D40: 포트홀

API에서 위 설정을 중복 정의하지 않고 기존 `mvp` 프로필을 활용합니다.

클라이언트가 임의의 모델 경로나 로컬 파일 경로를 지정하지 못하도록 합니다.

### 기존 분석 결과 구조

`analyze_video()`는 `summary.json`과 동일한 딕셔너리를 반환합니다.

- `frames_dir`: 추출 JPG 및 `frames.csv`
- `output_dir`: 분석 결과 폴더
- `detections.csv`: 프레임별 탐지 결과
- `events.json`: 의심 구간 목록
- `scenes/`: 대표 장면 JPG
- `summary.json`: 영상 정보, 설정, 처리 시간 및 탐지 요약

이 구조를 최대한 재사용하며 API 응답에서는 내부 절대 경로를 노출하지 않습니다.

## 4. 기존 검증 결과 및 기술적 한계

Part 5.4에서 혼합 모델의 입력 해상도를 640에서 1280으로 높였을 때 동일 진단용 GT의 D20 정탐이 2/5개에서 5/5개로 증가했습니다.

이는 반복 사용한 소규모 진단 자료의 결과이며 전체 도로환경에 대한 일반화 성능은 아닙니다.

Part 5.5에서는 실제 전·후방 영상 두 편을 분석했습니다.

| 항목 | 전방 | 후방 |
|---|---:|---:|
| 추출 및 추론 프레임 | 69 | 72 |
| 탐지 박스 | 234 | 49 |
| 의심 구간 | 9 | 13 |
| 분석 시간 | 11.345초 | 9.970초 |

전체 141장 추론과 대표 장면 22개의 원본 시각·좌표 일치를 검증했습니다.

다만 기존 시간 기반 통합에서 전방 D00 박스 195개가 0~34초 전체에 걸친 하나의 구간으로 통합되는 문제가 발견됐습니다.

탐지 박스 및 의심 구간의 수량을 실제 파손 사례 수로 표현하지 않습니다.

## 5. 의심 구간 과도한 통합 최소 보완

FastAPI 구현에 앞서 기존 `group_detections()`의 과도한 구간 병합을 최소한으로 보완합니다.

최대 구간 길이를 선택적으로 지정할 수 있는 `max_event_duration` 또는 이에 해당하는 옵션을 검토해주세요.

- 기존 동일 클래스 및 최대 인접 간격 1.5초 조건 유지
- 구간 시작 시각부터 마지막 탐지 시각까지 최대 길이 제한
- 웹 MVP의 잠정 최대 길이: 5초
- 제한을 초과할 다음 탐지는 새 구간으로 분리
- 같은 프레임의 탐지를 불필요하게 중복 저장하지 않음
- 기존 탐지 박스 누락 금지
- 기존 CLI 기본 동작 및 과거 실험 재현성 유지
- 웹 분석에서만 해당 제한을 명시적으로 적용

5초는 검토 편의성을 위한 잠정값이며 최적값이나 동일 객체 식별 기준이 아닙니다.

기존 Part 5.5의 전·후방 `detections.csv`를 재사용하여 제한 없음과 최대 5초 조건을 비교합니다. 새로운 모델 추론은 이 비교에 필요하지 않습니다.

구간 수, 최대 구간 길이, 탐지 박스 보존 여부 및 대표 장면 선정 결과를 확인합니다.

객체 추적, IoU 기반 객체 매칭, 동적 ROI 등 추가 알고리즘은 이번 작업에서 구현하지 않습니다.

## 6. FastAPI 백엔드 구현

기존 `src/road_anomaly/` 구조를 유지하고 API와 작업 관리 코드를 AI 분석 코드에서 분리합니다.

구조 예시:

```text
src/road_anomaly/
├── video.py
├── video_analysis.py
├── detection_grouping.py
└── api/
    ├── main.py
    ├── schemas.py
    └── jobs.py
```

위 구조는 제안이며 과도한 계층 분리는 피하고 기존 프로젝트에 적합하게 조정할 수 있습니다.

초기에는 로컬 단일 사용자 MVP를 기준으로 구현합니다.

### API Contract

| Method | Endpoint | 역할 |
|---|---|---|
| GET | `/api/health` | API 서버 상태 확인 |
| POST | `/api/jobs` | MP4 업로드 및 분석 작업 생성 |
| GET | `/api/jobs/{job_id}` | 작업 상태 조회 |
| GET | `/api/jobs/{job_id}/results` | 분석 결과 조회 |
| GET | `/api/jobs/{job_id}/video` | 업로드한 원본 영상 제공 |
| GET | `/api/jobs/{job_id}/scenes/{event_id}` | 대표 이미지 제공 |

경로명은 특별한 문제가 없다면 유지하고, 변경 시 이유와 최종 API Contract를 기록합니다.

### 6.1 영상 업로드

- multipart/form-data 방식
- 업로드 필드 이름: `file`
- MP4만 허용
- 서버에서 UUID 기반 job_id 생성
- 사용자 파일명을 실제 저장 경로로 직접 사용하지 않음
- 청크 단위 파일 저장
- 최대 파일 크기 제한 및 초과 시 부분 파일 정리
- 초기 업로드 크기 제한은 200MiB로 설정 가능하게 관리
- 빈 파일, 잘못된 확장자, 손상된 영상 처리
- 파일 확장자와 MIME 타입만으로 정상 영상이라고 판단하지 않음
- 디코딩 가능 여부 검증
- 내부 경로 및 서버 상세 오류를 응답에 노출하지 않음

업로드 성공 후 HTTP 202와 job_id, 초기 작업 상태를 반환합니다.

HTTP 응답을 기다리는 동안 전체 YOLO 분석이 실행되는 방식은 피합니다.

### 6.2 작업 실행 및 상태 관리

작업 상태:

- `queued`: 분석 대기
- `running`: 분석 중
- `completed`: 분석 완료
- `failed`: 분석 실패

기존 `analyze_video()`는 동기 함수이므로 FastAPI 이벤트 루프를 차단하지 않는 실행 구조를 사용합니다.

단일 작업 큐 및 단일 실행 워커 또는 동등한 방식으로 GPU 분석 작업을 한 번에 하나만 처리합니다.

- 분석 중에도 상태 조회 가능
- 여러 요청이 들어오더라도 GPU 분석 중복 실행 방지
- 작업별 고유 저장 경로 사용
- 분석 예외 발생 시 failed 처리
- 실패 후 다음 작업 정상 실행
- 결과 파일 저장 및 검증 완료 후 completed 처리
- 생성·시작·완료 시각 기록
- 분석 실패 사유 기록

초기에는 정확한 진행률을 계산할 수 없다면 가짜 백분율을 반환하지 않습니다. 상태 정보만으로도 충분합니다.

Redis, Celery 등의 외부 작업 큐는 도입하지 않습니다.

### 6.3 파일 기반 작업 저장

업로드 영상 및 작업 메타데이터는 기존 Git 제외 경로 아래 별도 폴더에 저장합니다.

예시:

```text
data/raw/uploads/<job_id>/input.mp4

outputs/jobs/<job_id>/job.json

outputs/video_analysis/<job_id>/
├── summary.json
├── detections.csv
├── events.json
└── scenes/
```

작업 메타데이터는 JSON 기반으로 관리하고 동시 읽기 및 쓰기로 인한 파일 손상을 방지합니다.

서버 재시작 후에도 완료된 작업을 조회할 수 있도록 합니다.

종료된 프로세스의 queued/running 작업이 계속 실행 중으로 표시되지 않도록 재시작 시 중단 상태를 적절히 처리합니다. 자동 재실행은 이번 범위에 포함하지 않습니다.

기존 실험 폴더와 사용자 업로드 작업 폴더를 구분합니다.

### 6.4 분석 결과 조회

프론트엔드에서 사용할 수 있도록 Pydantic 응답 모델 또는 명확한 응답 구조를 정의합니다.

주요 응답 정보:

- job_id 및 작업 상태
- 원본 영상 메타데이터
- 전체 추출 및 추론 프레임 수
- 전체 탐지 박스 수
- 의심 구간 수
- 분석 소요 시간
- 실제 적용된 분석 설정
- 의심 구간 목록

각 의심 구간의 필수 정보:

- event_id
- class_id
- class_name
- start_time_sec
- last_detection_time_sec
- representative_time_sec
- max_confidence
- detection_count
- detected_frame_count
- 대표 이미지 조회 URL

의심 구간이 없는 경우 빈 목록을 반환합니다.

confidence는 모델 예측 점수이며 실제 파손 확률이나 위험 등급으로 표현하지 않습니다.

분석 완료 전 결과 요청과 잘못된 job_id 요청은 일관된 오류 응답을 반환하도록 합니다.

### 6.5 원본 영상 및 대표 이미지

원본 영상은 이후 React의 HTML video 요소에서 재생하고 특정 타임스탬프로 이동할 수 있어야 합니다.

- MP4의 올바른 Content-Type
- HTTP Range 요청 및 부분 응답 지원 확인
- 대표 이미지 JPEG 제공
- job_id와 event_id 검증
- 해당 작업에 속한 파일만 접근 허용
- 경로 탐색 공격 및 임의 파일 접근 방지

전체 data/ 또는 outputs/ 폴더를 무제한 정적 파일 경로로 공개하지 않습니다.

### 6.6 로컬 실행 설정

개발 서버는 기본적으로 localhost에 바인딩합니다.

CORS는 React + Vite의 로컬 개발 주소를 필요한 범위에서만 허용합니다.

아직 로그인 및 사용자 인증이 없는 로컬 MVP이므로 외부 인터넷에 공개하지 않습니다.

기존 CLI가 사용하는 Ultralytics 로컬 설정, 오프라인 실행 및 자동 설치 방지 방식도 확인하고 API 실행 환경에서 필요한 부분을 유지합니다.

## 7. 테스트 및 실제 실행 검증

모델 추론과 API 테스트를 구분합니다.

일반 API 테스트에서는 기존 분석 함수를 모킹하거나 테스트용 분석 함수를 주입하여 불필요한 GPU 반복 실행을 방지합니다.

다음 항목을 검증해주세요.

- 서버 상태 조회
- 정상 MP4 업로드 및 HTTP 202 반환
- queued → running → completed 상태 변경
- 분석 중 상태 조회 가능
- 작업 동시 실행 방지
- 분석 실패 처리 및 다음 작업 실행
- 잘못된 확장자, 빈 파일, 손상된 영상, 크기 제한 초과 처리
- 완료되지 않은 작업의 결과 요청
- 존재하지 않는 작업 및 이미지 조회
- 분석 결과 및 대표 이미지 제공
- HTTP Range 영상 요청
- 무탐지 결과 정상 응답
- 경로 탐색 및 임의 파일 접근 차단
- 서버 재시작 후 작업 상태 처리
- 최대 구간 길이 적용 시 탐지 박스 보존
- 기존 영상 분석 CLI 및 회귀 테스트 유지

전체 회귀 테스트 명령:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests
```

### 실제 GPU 통합 검증

FastAPI 서버를 실행하고 기존 실제 영상 한 편으로 다음 흐름을 검증합니다.

`MP4 업로드 → 작업 생성 → CUDA 분석 → 상태 조회 → 결과 조회 → 원본 영상 및 대표 이미지 조회`

사용할 영상:

`data/raw/dashcam_validation/Dashcam-Front.mp4`

기존 MVP 모델을 실제 호출하며 모킹된 테스트 결과로 실제 GPU 통합 완료를 대신하지 않습니다.

새로운 실행 경로를 사용하고 Part 5.5 결과를 덮어쓰지 않습니다.

## 8. 문서 및 산출물

README에 다음 내용을 반영합니다.

- FastAPI 백엔드 실행 방법
- 필요한 웹 의존성 설치 방법
- Swagger UI 접속 주소
- API 요청 및 응답 예시
- PowerShell 기반 API 테스트 방법
- 업로드 및 결과 저장 위치
- 모델 가중치 준비 방법
- 현재 구현 범위 및 한계

Part 6.2에서 React 구현에 바로 사용할 수 있도록 API Contract 문서를 작성합니다.

예시:

- `docs/api_contract.md`
- `docs/experiments/part6_fastapi_backend.md`

작업 기록은 기존 `docs/ai_collaboration/` 구조에 맞춰 중요한 설계 결정과 검증 결과 중심으로 작성합니다.

문서 작성 때문에 본래 구현이 지연되지 않도록 중복 기록을 최소화합니다.

## 9. 작업 범위 제한

다음 작업은 이번 범위에 포함하지 않습니다.

- React 프론트엔드 구현
- 사용자 검토·수정 UI 및 검토 상태 저장 기능
- 로그인 및 회원가입
- MySQL 등 데이터베이스 도입
- Redis, Celery, WebSocket
- 클라우드 배포 및 Docker 구성
- 신규 모델 학습
- 새로운 객체 추적 알고리즘
- 기존 평가 데이터 및 모델 가중치 수정
- 기존 실험 산출물 덮어쓰기
- 불필요한 환경 및 라이브러리 변경
- 자동 Git Commit 및 Push

검토 상태 저장 기능은 이후 사용자 확인 흐름을 설계할 때 필요한 최소 범위로 추가할 예정입니다.

새로운 업로드 영상 및 분석 결과가 Git에 포함되지 않는지 확인합니다. `.gitignore` 수정이 필요하면 기존 AGENTS.md의 승인 규칙을 따릅니다.

원본 영상, 기존 가중치, GT 및 과거 실험 결과를 보호합니다.

## 10. 완료 기준 및 최종 보고

다음 항목을 모두 만족하면 Part 6.1을 완료한 것으로 판단합니다.

1. FastAPI 서버 정상 실행
2. MP4 업로드 및 작업 생성
3. 분석 중 상태 조회
4. 기존 MVP 분석 함수 실제 GPU 실행
5. 결과 및 대표 이미지 조회
6. 원본 영상 재생을 위한 HTTP 응답 검증
7. 과도한 시간 구간 통합 최소 보완
8. 실패 및 잘못된 입력 처리
9. 기존 기능과 신규 테스트 통과
10. 프론트엔드 연결용 API Contract 작성

작업 완료 후 다음 내용을 간결하게 보고해주세요.

- 작업 전 Git 상태 및 환경
- 신규 설치 라이브러리와 버전
- 신규 및 변경 파일
- 구현한 API 목록
- API 요청·응답 예시
- 작업 실행 및 상태 관리 방식
- 최대 구간 길이 적용 전후 비교
- 실제 CUDA 영상 분석 결과
- 신규 테스트 및 전체 회귀 테스트 결과
- 서버 실행 명령 및 Swagger 주소
- Part 6.2에서 재사용할 API 정보
- 확인된 한계 및 미완료 사항
- 최종 git status

실제로 수행하지 않은 테스트와 검증을 완료로 표시하지 않습니다.

사용량 부족 등으로 모든 작업을 완료하기 어려우면 현재 구현 상태, 마지막으로 완료한 테스트, 미완료 작업을 기록해주세요.

Git Commit 및 Push는 수행하지 않습니다.