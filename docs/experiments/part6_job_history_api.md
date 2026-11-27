# Part 6.4-1 분석 이력 데이터 및 API

2026-11-26 (KST) · `main` · 기준 커밋 `a26de59`. 작업 전 `git status --short --branch`에서 `main...origin/main`과 깨끗한 작업 트리를 확인했다.

## 저장과 조회 설계

- 기존 `job.json`에 선택 필드 `original_filename`과 `file_size_bytes`를 추가했다. 같은 원자적 쓰기로 파일 정보와 대기 상태를 저장하고, 성공한 작업만 큐에 등록한다. 별도 메타데이터 파일을 두면 상태와 메타데이터 두 파일의 저장·정리 순서를 관리해야 하고 목록에서 두 번 읽어야 한다. 이번 규모에서는 기존 상태 파일에 두 필드를 두는 쪽이 적합했다.
- 표시용 파일명에서 경로, 드라이브 접두사, 제어·서식 문자 및 서로게이트를 제거한다. 255자를 넘으면 MP4 확장자를 보존해 줄인다. 크기는 디코딩 검증을 통과해 저장된 `input.mp4`의 `stat()` 값이다. 작업 UUID와 고정 파일명으로 경로를 결정한다. 상태 파일 저장 실패 시 이번 요청이 만든 작업 폴더와 업로드 사본을 정리한다.
- 신규 필드가 없는 작업은 이름을 null로 반환한다. 업로드 사본이 있으면 크기만 조회하며 기존 완료 파일을 마이그레이션하거나 기존 영상을 분석하지 않는다. 업로드·개별 상태 응답은 기존 `JobStatus`를 유지한다.
- `GET /api/jobs`는 상태·파일명 검색을 적용한 뒤 생성 시각과 UUID로 정렬하고 페이지를 자른다. 작업 메타데이터는 한 건씩 기존 잠금으로 읽는다. 페이지에 포함된 완료 작업만 결과 JSON을 한 번씩 파싱하고, 검토 파일 읽기는 검토 저장과 같은 잠금을 사용한다. 목록에서 JPEG와 영상의 내용을 읽거나 GPU 워커를 호출하지 않는다.
- 검토는 실제 결과의 장면 ID로 검증한다. 정상적으로 누락된 검토 파일은 전체 미검토로 표시하며, 판단 보류를 검토한 장면에 포함한다. 손상된 검토는 검토 요약을 null로 반환한다. 손상된 분석 결과도 해당 요약만 null로 반환하며, 작업 메타데이터를 읽을 수 없는 항목은 `total`에서 제외한다. 응답 경고는 UUID와 오류 코드·안내 문구를 제공한다. 로컬 로그에는 경고 코드와 UUID를 남기고 기존 검토 파일 읽기 실패 시의 상세 로그도 사용한다. [요청·응답 및 경고 규약](../api_contract.md#분석-이력)

## 실제 FastAPI와 Edge

기본 포트 8000의 기존 서버를 Before에 읽기 전용으로 조회했다. OpenAPI에 `POST /api/jobs`만 등록돼 있었고 `GET /api/jobs`는 405였다. After는 Windows 종료 설정이 적용되는 기존 `src.road_anomaly.api.__main__.create_server()`를 포트 8014로 실행했다. 기존 완료 작업 7건의 JSON·업로드 사본·대표 JPEG를 격리 위치로 복제했고, 이미 실행 중인 서버는 계속 사용하도록 두었다.

| 확인 항목 | 결과 |
| --- | --- |
| 기존 이력 | 전체 7건, 최근 5건과 전체 7건을 구분했다. 완료 필터, 오래된 순과 오프셋, 범위 밖 페이지를 확인했다. 7건의 파일명은 null이고 크기는 사본과 일치했다. |
| 검토 요약 | 후방 작업의 13개 장면 중 오탐 2개, 미검토 11개로 개별 검토 API와 일치했다. 전·후방의 대표 JPEG와 MP4 Range를 조회했고, Edge에서 기존 후방 결과 URL을 직접 열어 영상 프레임과 `2 / 13` 검토 집계를 확인했다. |
| 신규 실제 업로드 | `Dashcam-Front.mp4` 한 편을 RTX 3060 Ti `cuda:0`에서 분석했다. `queued → running → completed` 상태, 추론 프레임 69장, 대표 JPEG 16장 및 세 구간의 Range를 확인했다. 업로드 사본·원본·이력·`job.json`의 크기가 96,383,988바이트로 일치했다. 대소문자를 바꾼 검색에서 신규 작업 1건이 나왔다. |
| 저장 보존과 재시작 | 신규 작업을 포함한 이력 8건과 기존 검토 응답이 재시작 전후 동일했다. 기존 7건의 `job.json`, `results.json`, 존재하던 `reviews.json`의 SHA-256과 파일 유무가 원본·사본·Before에서 일치했다. |
| 예외 조건 | 격리 서버에 합성 JSON을 추가해 무탐지 0건과 분석 중 null, 손상된 작업·결과·검토 경고를 확인했다. |

동일 Windows 호스트에서 `GET /api/jobs?limit=5`의 HTTP 왕복과 JSON 파싱을 따뜻한 연결로 15회 측정했다. 미디어가 있는 실제 기존 작업 7건은 중앙값 13.06ms, 최대 18.24ms였다. 실제 결과 JSON을 재사용한 합성 작업 500건은 중앙값 238.02ms, 최대 249.31ms였다. 합성 저장소에는 영상과 JPEG가 없었다. 조회마다 상태 파일을 순회하므로 작업 증가와 동시 요청에 대한 처리량은 추가 계측이 필요하다. [측정 원시값](../../outputs/evidence/part6_4_1_job_history_api/details/latency.json)

## 회귀 검증

| 명령 | 결과 |
| --- | --- |
| `.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests` | 172개 통과. 기존 159개와 신규 13개 |
| `npm run typecheck -- --force`, `npm run lint`, `npm run build` | 모두 통과 |
| `npm test -- --workers=1` | 기존 Playwright 23개 통과. 출력은 이번 증빙 전용 경로로 지정 |

첫 Python 전체 실행에서 파일 정보 없이 등록하는 종료 회귀의 `job.json`에 null 필드가 추가되는 것을 확인했다. 기존 저장 키를 유지하도록 고친 뒤 전체 회귀를 다시 통과했다. Playwright의 페이지 이탈·복귀 테스트는 뒤로 가기 전에 이전 결과 화면이 실제로 닫히는지 확인하도록 한 줄을 추가했다. 최초 두 실행에서 같은 검증이 실패했고, 화면 전환을 기다린 뒤 23개가 모두 통과했다. [Python 로그](../../outputs/evidence/part6_4_1_job_history_api/details/python_unittest_after_compatibility_fix.log) · [Playwright 로그](../../outputs/evidence/part6_4_1_job_history_api/details/playwright_final.log)

구현과 격리 로컬 서비스 검증을 완료했다. 직접 사용자 확인과 서비스 배포는 대기 상태다. 이번 검증은 Windows 로컬 단일 워커에서 수행했다. 분석 이력 화면은 Part 6.4-2에서 이 API를 사용한다. [Swagger 전후, HTTP 응답 및 Edge 결과](../../outputs/evidence/part6_4_1_job_history_api/evidence_notes.md)
