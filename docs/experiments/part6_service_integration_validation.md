# Part 6.3-1 전체 서비스 통합 테스트 및 안정성 검증

2026-11-26 KST · Windows 11 x64 · 시작 커밋 `93f30db` · `main`과 `origin/main` 일치, 작업 트리 깨끗함

기존 MVP에서 실제 MP4 두 편의 업로드부터 CUDA 분석, 대표 JPEG 표시, 재생과 시점 이동까지 확인했다. Edge에서 후방 영상의 검토 상태와 검토 개수도 갱신됐다. 영상이 일시 정지된 상태에서 Uvicorn 정상 종료가 지연되는 P1 결함을 재현했다.

## 회귀 및 자동화

| 구분 | 명령 | 결과 |
| --- | --- | --- |
| Python | `.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests` | 151개 통과 |
| React | `npm run typecheck -- --force`, `npm run lint`, `npm run build` | 모두 통과 |
| Playwright | `npm test -- --workers=1`, `npm test -- --repeat-each=2 --workers=1` | Edge에서 Mock API·예시 흐름 12개 통과, 최종 반복 24/24 통과 |

Playwright 1.65.1은 Vite 빌드를 5177에서 띄운다. 개발 모드에서는 React Strict Mode가 초기 효과를 재실행해 Mock 응답 순서와 요청 수에 영향을 줬다. 요청 수 검증에는 프로덕션 빌드의 실행 조건을 사용했다. Playwright에서 네트워크 장애와 HTTP 500을 주입했고, 실제 HTTP 422와 영상 Range 416은 FastAPI에서 별도로 확인했다. 크기 초과는 브라우저 `File.size`를 209,715,201로 설정한 선택 이벤트로 재현했다. 실제 업로드 제한은 Python 회귀 테스트에서 검증한다. [Playwright 테스트](../../frontend/tests/mock-service.spec.ts)

파일 선택·변경·취소, 확장자·빈 파일·용량 검증, 중복 POST 차단, 대기·실행·완료·실패와 종료 시 폴링 중단, 페이지 이탈과 작업 ID 교체 시 요청 취소, 상태·결과 재시도, 작업과 예시 URL 구분, 장면 선택·필터·정렬·검토 수, 두 빈 상태, JPEG 재시도, 직접 접근·새로고침을 다룬다.

제한 셸에서 기존 Python 실행 파일에 접근하지 못해 권한을 확장해 재실행했다. 기존 Python 3.14.5, Node 26.13.1, npm 11.20.0을 사용했다. Python 테스트에서 Starlette의 httpx 사용 중단 예정 경고와 손상 MP4 테스트의 OpenCV 진단 로그가 나왔다.

## 실제 영상과 브라우저

| 영상 | 크기 / 영상 사양 | 추출 / 추론 | 박스 / 구간 | AI 분석 | 업로드 응답 | 사용자 대기 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `Dashcam-Rear.mp4` | 93,494,153 B · 36.000초 · 1920×1080 · 30 FPS | 72 / 72 | 49 / 13 | 10.16초 | 5.29초 | 16.78초 |
| `road_sample_04.mp4` | 29,051,909 B · 29.196초 · 1920×1080 · 29.97 FPS | 59 / 59 | 4 / 4 | 9.35초 | 3.68초 | 14.20초 |

AI 분석은 `analysis_seconds`로, 프레임 추출, 모델 로딩·추론 및 파이프라인 산출물 저장을 포함한다. 업로드 응답은 버튼 조작부터 POST 202 응답 본문 확인까지다. 사용자 대기는 같은 조작부터 결과 확인 링크가 나타날 때까지이며, 업로드, 서버 유효성 검사, 분석 및 브라우저 폴링을 포함한다. 로컬에서 한 번씩 측정했다. RTX 3060 Ti, 드라이버 581.15, PyTorch 2.14.1+cu130, OpenCV 5.0.0에서 CUDA 연산과 두 분석의 FP32 `[1, 3, 1280, 1280]` · `cuda:0` 텐서를 확인했다. 샘플링 간격은 0.5초, 웹 통합 상한은 5초였다. 박스와 의심 구간은 사용자 검토 단위다.

후방 영상은 Jihad Dib, Konstantinos Sirlantzis, Gareth Howells가 Mendeley Data에 공개한 CC BY 4.0 영상이며 기존 진단에서 사용했다. 추가 영상은 Windows 다운로드 메타데이터에서 Pexels 출처를 확인한 뒤 로컬 검증에 사용했다. 차내 구조물과 낮은 각도의 햇빛·앞유리 반사가 있는 추가 입력으로 선택했다. 전방 영상은 Part 6.2-4 결과를 재사용했다. 이번에는 정답 대조나 모델 성능 평가를 수행하지 않았다. [Mendeley Data](https://data.mendeley.com/datasets/tp95cdvgm8/1) · [Pexels 라이선스](https://www.pexels.com/license/) · [추가 영상 조건](part5_real_video_validation.md#road_sample_04-추가-검증) · [전방 영상 실측](../ai_collaboration/09_react_api_integration.md)

| 브라우저 | 검증 결과 |
| --- | --- |
| Edge 158.0.4370.33 | 두 영상의 업로드·결과·JPEG·재생 통과. 후방 5.000초, 추가 17.518초로 이동. 후방 검토 수 1/13 확인 |
| Chrome 158.0.8127.38 | 같은 후방 작업 URL에 직접 접근. JPEG·재생·5.000초 시점 이동 통과 |
| Firefox | 실행 파일과 브라우저 캐시가 확인되지 않아 미검증 |

| Edge 화면 | 영상 표시 영역 | 겹친 마커 쌍 | 장면 선택 |
| --- | ---: | ---: | --- |
| 1440×1024 | 865×487 px | 6 | 마지막 장면 선택 후 상세가 화면 안에 있음 |
| 1280×720 | 761×428 px | 8 | 첫 화면에서 목록이 하단에 걸림. 마지막 장면 선택 후 상세가 화면 안에 있음 |
| 390×844 | 356×200 px | 15 | 마지막 장면 선택 및 시점 이동은 가능. 상세가 화면 위에 남음 |

세 크기에서 가로 스크롤과 측정한 제목·메타데이터·상세 수치·검토 버튼의 가로 잘림은 관찰되지 않았다. 겹침은 마커 버튼 경계가 교차하는 쌍을 셌다. 실제 모바일 기기와 터치 조작은 미검증이다.

## Windows 연결 종료와 서버 복구

- 연속 장면 이동, 재생 중 페이지 이동·탭 닫기·Chrome 종료에서 Range 206을 확인했다. 범위를 벗어난 요청은 416 `invalid_range`였다. 두 브라우저의 미디어 연결에서 Windows asyncio Proactor 콜백의 `socket.shutdown(SHUT_RDWR)` 중 `WinError 10054`가 기록됐다. ASGI 처리 예외나 HTTP 500은 관찰되지 않았고 헬스 요청은 200이었다. 강제 TCP 리셋 대조 요청은 206을 받았으나 같은 콜백 로그를 추가로 유발하지 않았다. [Winsock 오류 정의](https://learn.microsoft.com/en-us/windows/win32/winsock/windows-sockets-error-codes-2) · [Python 3.14.5 콜백 소스](https://github.com/python/cpython/blob/v3.14.5/Lib/asyncio/proactor_events.py#L158-L171) · [영상 연결 로그](../../outputs/evidence/part6_3_1_integration_validation/2026-11-26T02-48-39-274Z/uvicorn-1-media.log)
- 영상 일시 정지 상태에서 포트가 닫힌 뒤 프로세스가 55초 넘게 남았다. 계측 재현에서 포트는 129 ms 뒤 닫혔고, H11의 영상 응답이 미완료이고 전송 버퍼가 131,072 B이며 쓰기가 일시 정지된 상태였다. Uvicorn은 `Waiting for connections to close`에 머물러 앱 종료 단계에 들어가지 못했다. 7초 후 탭을 닫고 2초 더 기다려도 남아 검증용 서버만 정리했다. 개별 10054 콜백과 잔류 연결 사이의 인과관계는 확인되지 않았다. [최초 종료 로그](../../outputs/evidence/part6_3_1_integration_validation/2026-11-26T02-45-03-210Z/uvicorn-1-media.log)
- 같은 저장소로 재시작해 후방 작업이 `completed`이고 결과 JSON이 이전과 일치함을 확인했다. 미디어 연결과 작업이 없는 대조에서는 포트가 141 ms, 프로세스가 279 ms에 종료됐다.
- 미디어 요청 없이 실제 후방 CUDA 분석이 실행되고 한 건이 대기 중일 때 종료했다. 포트는 138 ms에 닫혔고 앱 종료 단계에서 워커를 기다린 뒤 10.79초에 코드 0으로 종료했다. 후방 작업은 `completed`, 대기 작업은 `failed/interrupted`였다. 별도 비정상 종료 후 재시작하면 디스크에 남은 `running`과 `queued` 작업이 각각 `failed/interrupted`로 복구됐으며 Edge에서 재업로드 안내가 표시됐다. [워커와 재시작 기록](../../outputs/evidence/part6_3_1_integration_validation/2026-11-26T02-51-43-047Z/observations.jsonl)
- 복구된 상태 페이지를 본 다음 손상 MP4의 실제 422 `invalid_video`와 사용자 안내를 확인했다. 이 서버는 영상 엔드포인트를 사용하지 않았지만 브라우저 상태 요청 직후 같은 10054가 기록됐고, 종료 시 `Waiting for application shutdown`에 이르지 못했다. 따라서 미디어 전송이 있을 때의 종료 지연과 비미디어 연결의 종료 지연을 따로 기록했다. [복구 서버 로그](../../outputs/evidence/part6_3_1_integration_validation/2026-11-26T02-51-43-047Z/uvicorn-5-recovered.log)
- 후방 완료 작업으로 이벤트 루프만 바꿔 재현했다. Windows 기본 Proactor에서는 일시 정지 상태에서 Uvicorn 연결과 작업이 각각 1개였다. 탭을 닫자 두 값이 0개가 됐지만 asyncio 전송 객체는 4개가 남았고 앱 종료 단계에 진입하지 못했다. 이 실행에서 10054는 18회 기록됐다. Python 3.14.5 소스상 이 오류가 `socket.shutdown()`에서 발생하면 뒤의 소켓 닫기와 서버 전송 객체 분리가 실행되지 않는다. 관측값과 소스를 종합하면 이 동작이 `Server.wait_closed()` 단계의 잔류를 설명한다. 같은 흐름을 Selector로 실행했을 때 열린 탭의 스트리밍 대기는 유지되었고, 탭을 닫은 뒤 10054 없이 코드 0으로 종료됐다. Selector는 대조에서만 사용했으며 제품 종료 정책에 적용하려면 별도 검증이 필요하다. [루프 비교 관측](../../outputs/evidence/part6_3_1_integration_validation/2026-11-26T02-55-35-237Z/observations.jsonl) · [Proactor 연결 정리 소스](https://raw.githubusercontent.com/python/cpython/v3.14.5/Lib/asyncio/proactor_events.py) · [asyncio 서버 종료 소스](https://raw.githubusercontent.com/python/cpython/v3.14.5/Lib/asyncio/base_events.py)

## 발견 사항과 후속 순서

| 우선순위 | 확인한 문제 또는 개선 항목 | 다음 검토 |
| --- | --- | --- |
| P1 | Windows에서 미디어 응답 때문에 정상 종료가 지연되고 재시작에 프로세스 정리가 필요할 수 있음 | 미디어 전송 종료 경로와 제한 시간을 검증한 뒤 종료 정책 결정 |
| P2 | 타임라인 마커 겹침, 모바일 목록과 상세 사이의 이동 거리 | Part 6.3-2에서 밀집 마커 선택 방법과 모바일 상세 이동을 우선 검토 |
| P2 | 타임라인 선택 시 목록 스크롤이 선택 행을 따라가지 않음. 대표 JPEG 확대 없음 | 목록의 선택 위치 노출과 이미지 확대 검토 |
| P2 | 결과 직접 접속에서 원본 파일명이 일반 이름으로 표시. 용량은 업로드 화면에 표시. 모바일 요약 보조 문구가 여러 줄을 차지 | 결과 메타데이터와 보조 문구 가독성 개선 검토 |
| P3 | 새로고침 시 검토 상태 초기화 | 검토 저장은 후속 범위 |

P0는 이번 검증에서 관찰되지 않았다. 코드 변경은 Playwright 설정과 테스트에 해당한다. 서버 전송·종료 정책 변경은 별도 과제로 남겼다. [실행 문서](../../frontend/README.md) · [시각적 증빙과 원시 관측](../../outputs/evidence/part6_3_1_integration_validation/evidence_notes.md)

최종 상태는 `main...origin/main`이다. 추적 중인 파일 변경 2개와 새 보고서·Playwright 설정·테스트 파일이 작업 트리에 있다. 검증용 8000·5173·5177의 리스너는 종료됐다. Git 커밋과 푸시는 수행하지 않았다.
