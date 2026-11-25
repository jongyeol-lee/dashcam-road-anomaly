# Part 6.1 — FastAPI 영상 분석 백엔드

**2026-11-25 · 시작 `main` / `4639237`, 작업 트리 깨끗함.** 요청한 API 6개와 단일 분석 워커를 구현했습니다. 실제 전방 MP4의 HTTP 업로드부터 CUDA 분석·상태·결과·16개 JPEG·영상 Range·재시작 후 조회를 검증했고 전체 회귀 테스트 151개가 통과했습니다. React UI 및 브라우저 재생은 다음 단계입니다. [실행 방법](../../README.md#fastapi-로컬-백엔드) · [API Contract](../api_contract.md)

## 구현과 결정

| 변경 파일 | 목적 |
| --- | --- |
| `src/road_anomaly/detection_grouping.py` | 선택 인자 `max_event_duration=None`. 기존 클래스·인접 간격 통합을 유지하고 시작부터의 최대 길이 추가 |
| `src/road_anomaly/video_analysis.py` | 제한 및 웹 전용 출력 루트를 전달. CLI 기본 프로필·출력 형식은 유지 |
| `src/road_anomaly/api/main.py` | 앱 수명, 업로드·조회·미디어 API, 로컬 CORS, 통일된 JSON 오류 |
| `src/road_anomaly/api/jobs.py` | 단일 큐·스레드, JSON 원자 저장, 프로세스 잠금·재시작 처리, 업로드·결과 파일 검사 |
| `src/road_anomaly/api/schemas.py` | 상태·결과·장면·오류의 Pydantic 모델 |
| `requirements-web.txt` | AI 의존성과 분리한 검증 버전 |
| `scripts/verify_fastapi_backend.py` | 실행 중인 localhost API의 실제 GPU 통합 흐름 검증 |
| `tests/test_api.py` 및 기존 분석·통합 테스트 2개 파일 | GPU 대역을 사용하는 API 테스트와 기존 기능 회귀 |
| README·환경 문서·API 규약·협업 기록·프롬프트 원문 | 실행·연결·검증 근거 |

웹은 기존 `mvp` 프로필을 호출하므로 모델과 입력 설정을 API에 중복 정의하지 않았습니다. GPU 워커는 한 번에 하나의 작업만 실행하며 요청 처리 스레드·이벤트 루프와 분리됩니다. 같은 저장소로 복수 프로세스를 띄우면 OS 파일 잠금이 두 번째 시작을 거절합니다. 여러 저장소·서버 사이의 GPU 분산 잠금은 제공하지 않습니다.

상태와 클라이언트용 결과는 `outputs/jobs/<UUID>/`에 임시 파일·flush·fsync·replace 방식으로 저장합니다. 읽기·쓰기에는 스레드 잠금도 사용합니다. 완료는 summary·events·detections의 수량·시간·모델 해시와 대표 이미지 디코딩을 검사하고 공개 결과를 저장한 뒤 기록합니다. 실패 상세는 로컬 로그, 상태 응답은 경로를 포함하지 않는 오류 코드·메시지로 구분합니다. 실패 후에도 워커는 다음 작업을 실행합니다.

업로드 사본·샘플링 프레임·분석 결과는 각각 `data/raw/uploads/`, `data/processed/frames/jobs/`, `outputs/video_analysis/jobs/`에 둡니다. 기존 실험 폴더와 구분하며 `.gitignore`와 `.env`는 수정하지 않았습니다. Git 제외 확인은 실제 작업의 MP4·job.json·summary.json·frames.csv 네 경로에서 성공했습니다.

## 구간 제한 비교 — 기존 예측만 재사용

Part 5.5의 전·후방 `detections.csv`를 읽어 동일 클래스·최대 인접 간격 1.5초로 비교했습니다. 제한 없는 결과는 이전 `events.json`과 모든 필드가 같았습니다. 새 모델 추론은 이 비교에 사용하지 않았습니다.

| 영상 | 박스 수 | 기존 구간 → 5초 제한 | 최대 길이 기존 → 제한 | 대표 선정 |
| --- | ---: | ---: | ---: | --- |
| 전방 | 234 → 234 | 9 → 16 | 34 → 5초 | 각 구간 최고 confidence, 16장 저장 |
| 후방 | 49 → 49 | 13 → 13 | 2 → 2초 | 이전과 같은 대표 13장 |

전방 D00은 1개에서 7개, D20은 2개에서 3개로 나뉘고 D10 1개·D40 5개는 같았습니다. 각 구간의 클래스와 시작·끝 시각으로 박스 소속을 재계산해 입력 283개가 정확히 한 번씩 포함됨을 확인했습니다. 같은 클래스·프레임이 여러 구간에 들어가지 않았고 대표 시각·좌표·점수를 구간 내 최고 점수 박스와 대조했습니다. 전체 51장(두 조건 합계)의 JPEG를 생성했습니다. [전체 비교와 대표 프레임 목록](../../outputs/fastapi_validation/part61_v1/grouping_comparison.json) · [비교 실행 코드](../../outputs/fastapi_validation/part61_v1/compare_grouping.py)

5초는 검토 편의를 위한 잠정값이며 객체 식별 기준이나 최적값이 아닙니다. 같은 시각에 떨어져 있는 대상은 여전히 같은 클래스 구간으로 묶입니다. 객체 추적·IoU 매칭·ROI·모델 재학습은 추가하지 않았습니다.

## 실제 HTTP·CUDA 통합

Windows / Python 3.14.5 / RTX 3060 Ti 8GiB / torch 2.14.1+cu130 / torchvision 0.29.1+cu130 / Ultralytics 8.4.215 / OpenCV 5.0.0 환경입니다. CUDA 13.0 빌드에서 실제 `[1,2,3] * 2 → [2,4,6]` 연산을 먼저 확인했습니다. 기존 AI 패키지는 변경하지 않았습니다. [웹 설치 내역](../ENVIRONMENT.md#part-61-웹-의존성-추가)

서버를 `127.0.0.1:8000`, workers 1로 실행하고 다음 명령으로 모델 대역 없이 검증했습니다.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m uvicorn road_anomaly.api.main:app --app-dir src --host 127.0.0.1 --port 8000 --workers 1
# 다른 PowerShell에서 실행. 재실행 시 새 --output 경로 사용
.\.venv\Scripts\python.exe -B -X utf8 scripts/verify_fastapi_backend.py --output outputs/fastapi_validation/part61_v1/integration.json
```

| 항목 | 실측 결과 |
| --- | --- |
| 입력 | `data/raw/dashcam_validation/Dashcam-Front.mp4`, 96,383,988바이트, 1920×1080, 30FPS, 1,021프레임 |
| 작업 ID | `d54ca2ea-e702-46d5-a063-ef15286866ec` |
| 상태 | 202 queued → running → completed. running 상태에서 92회 조회 및 health 200·미완료 결과 409 확인 |
| 프로필·모델 | mvp, 혼합 모델 SHA-256 `3d770f1515ef2baf2fbe25d4c9ba241d289254b2002894d7cc02ff56009b2afb` |
| 실제 forward 입력 | 69장 전부 `[1,3,1280,1280]`, `torch.float32`, `cuda:0` |
| 설정 | 0.5초 샘플링, conf 0.05, NMS IoU 0.7, rect False, batch 1, max_det 300, ROI·crop 없음, 최대 구간 5초 |
| 결과 | 추출·추론 69장, 234박스, 16구간 및 JPEG 16장 |
| 업로드·사전 검증 | 약 4.571초. HTTP 요청 시작부터 202까지이며 전체 디코딩을 포함 |
| 분석 함수 | 10.1517665초. 추출 4.6579549 / 초기화 3.6780050 / 예측 1.4802057 / 통합·저장 0.3356009초 |
| 영상 응답 | HEAD 200, video/mp4, Content-Length 96,383,988. 시작·중간·끝 각 1,024바이트 Range가 206이고 원본 바이트와 같음 |
| 이미지 | 16개 모두 HTTP 200, image/jpeg, 1920×1080 디코딩 성공 |
| 재시작 | 완료 상태와 결과 전체 동일, 대표 이미지 200 |

실제 새 추론의 234개 CSV 행은 `image_path`를 제외한 모든 필드가 Part 5.5 전방 예측과 같았습니다. 새 events.json과 대표 JPEG 16개도 기존 예측으로 만든 5초 제한 결과와 각각 필드·바이트가 일치했습니다. 측정 시간은 이 영상 한 편과 현재 장비의 실행 결과이며 일반화 성능이나 반복 벤치마크가 아닙니다. [HTTP 검증](../../outputs/fastapi_validation/part61_v1/integration.json) · [실측 텐서](../../outputs/fastapi_validation/part61_v1/observed_input.json) · [파이프라인 대조](../../outputs/fastapi_validation/part61_v1/pipeline_comparison.json) · [재시작 대조](../../outputs/fastapi_validation/part61_v1/restart.json)

## 테스트와 보존

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m unittest tests.test_api tests.test_detection_grouping tests.test_video_analysis -v
# 초기 관련 테스트 36개 통과. 이후 종료 처리·UUID 충돌 보호 테스트 2개 추가
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests
# 151개 통과, 실패·건너뜀 없음
.\.venv\Scripts\python.exe -B -X utf8 -m pip check
# No broken requirements found.
```

기존 131개와 신규 20개(API 17, 구간 제한 2, 분석 출력·제한 연계 1)입니다. 정상·무탐지·실패, 상태 조회·직렬 실행, 결과 파일 누락, 크기·확장자·빈/손상 MP4·multipart 오류, chunked 크기 제한, 부분 파일 정리, Range·HEAD·416, 경로 탐색, 중단된 queued/running 복구와 완료 결과 유지, 중복 프로세스 잠금을 확인했습니다. 링크 접근 차단 테스트는 Windows 링크 생성 권한과 무관하게 Path.resolve 결과를 대역으로 만들어 검증했습니다. 실제 외부 공격 시험은 수행하지 않았습니다.

초기 테스트에서 FastAPI 앱 전체 본문 제한이 JSON 오류 미들웨어 바깥에서 PlainText 413을 만드는 것을 발견했습니다. 업로드 경로 단위 제한으로 옮기고 Starlette의 직접 오류도 JSON으로 통일한 뒤 통과했습니다. OpenAPI GET/HEAD 중복 operation ID도 HEAD를 스키마에서 제외해 수정했습니다. 최종 검토에서는 종료 신호와 등록을 같은 잠금으로 묶고, UUID 충돌로 디렉터리 생성이 실패하면 기존 파일을 정리하지 않도록 보완했습니다. 두 경우의 회귀 테스트를 추가해 최종 151개가 통과했습니다. Starlette 1.10.0 TestClient의 기존 httpx 사용 중단 예정 경고는 남으며 테스트는 통과했습니다. 새 httpx2 의존성은 추가하지 않았습니다. 잘못된 MP4를 의도적으로 입력한 테스트에서는 FFmpeg 디코딩 오류 로그가 출력됩니다.

기존 보호 대상 1,424개의 전후 SHA-256이 모두 같았습니다. Part 5.5 보호 목록의 파일들과 Part 5.5 전·후방 프레임·결과를 포함하며 공개 Test 전체나 모든 학습 데이터 파일을 새로 전수 검사한 것은 아닙니다. [보존 결과](../../outputs/fastapi_validation/part61_v1/preservation.json) · [작업 전 해시 목록](../../outputs/fastapi_validation/part61_v1/protected_before.json)

## 남은 한계와 다음 단계

업로드 전수 디코딩은 응답 대기 시간을 늘리고 추론에서 다시 디코딩합니다. MP4 선두 ftyp와 OpenCV의 프레임 수 검사 때문에 특수한 컨테이너 구성·부정확한 메타데이터 영상은 거절될 수 있으며 모든 손상·코덱 조합의 처리를 보장하지 않습니다. 가변 FPS 시각은 추정치입니다. 큐·파일은 용량·보존 기간 자동 관리가 없고 자동 재시도·취소도 없습니다. 정상 종료는 현재 추론 완료를 기다립니다. 인증 없는 localhost MVP이므로 외부 공개는 범위 밖입니다.

Part 6.1의 구현·자동 테스트·실제 CUDA HTTP 통합은 완료했습니다. Part 6.2에서는 이 규약으로 React 업로드·상태 폴링·장면 목록을 연결하고 Part 6.3에서 실제 브라우저 재생과 시각 이동을 검증해야 합니다. 개별 탐지를 사용자가 파손으로 판정한 것은 아니며 독립 주행의 탐지 성능도 이번 작업에서 평가하지 않았습니다. Git Commit·Push는 수행하지 않았습니다.
