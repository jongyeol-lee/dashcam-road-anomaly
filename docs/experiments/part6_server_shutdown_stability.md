# Part 6.3-2A Windows 서버 종료 지연 개선

2026-11-26 KST · `main` · 시작 커밋 `df965be` · 시작 시 `origin/main`과 일치, 작업 트리 깨끗함

## 원인과 적용

Part 6.3-1에서 후방 MP4가 일시 정지된 상태로 서버를 종료하자 포트가 닫힌 뒤 프로세스가 55초 이상 남았다. 당시 H11의 영상 응답은 전송 버퍼 131,072 B를 비우지 못해 Uvicorn의 연결 대기 단계에 있었다. 탭을 닫은 별도 실행에서는 HTTP 연결과 요청이 0개가 된 뒤에도 Windows Proactor의 asyncio 전송 객체가 4개 남았다. Python 3.14.5의 해당 콜백은 `socket.shutdown()` 뒤에 소켓 닫기와 서버 연결 분리를 수행한다. 이 호출에서 `WinError 10054`가 나면 뒤의 정리가 실행되지 않으므로, 상태·결과 조회와 같은 비미디어 연결에서도 `Server.wait_closed()` 대기가 남을 수 있다. [Part 6.3-1 검증](part6_service_integration_validation.md) · [CPython Proactor 구현](https://github.com/python/cpython/blob/v3.14.5/Lib/asyncio/proactor_events.py) · [asyncio 서버 종료 구현](https://github.com/python/cpython/blob/v3.14.5/Lib/asyncio/base_events.py)

- Selector만 적용한 이전 대조 실험에서는 탭을 닫은 후 정상 종료했지만, 탭이 열린 동안에는 활성 영상 전송을 기다렸다.
- Proactor에서 3초 제한만 적용한 이번 대조에서는 프로세스가 종료됐지만 `WinError 10054`와 asyncio 연결 잔류가 계속 관찰됐다.
- 프로젝트 진입점은 Windows에서 Uvicorn의 공식 사용자 지정 루프 `asyncio:SelectorEventLoop`와 HTTP graceful shutdown 3초 제한을 함께 적용한다. Uvicorn 0.54.0 소스에서 이 제한은 HTTP 연결·요청과 `Server.wait_closed()` 대기에 걸리며, 초과한 요청을 취소한 뒤 FastAPI lifespan 종료를 실행한다. 진행 중인 GPU 분석 완료 대기는 HTTP 제한의 적용 대상에서 제외된다. Windows 이외에서는 기본 Uvicorn 루프와 종료 설정을 사용한다. [공식 루프 설정](https://uvicorn.dev/concepts/event-loop/) · [공식 종료 설정](https://uvicorn.dev/settings/#timeouts) · [Uvicorn 0.54.0 종료 코드](https://github.com/Kludex/uvicorn/blob/0.54.0/uvicorn/server.py) · [Python 루프 설정](https://docs.python.org/3.14/library/asyncio-runner.html)
- 초기 후보의 소켓 회귀에서 3초 HTTP 대기 도중 실행 작업이 끝나면 다음 대기 작업이 완료까지 진행되는 경계 조건을 재현했다. Windows 진입점에서 Uvicorn의 종료 단계가 열릴 때 워커 큐에 종료를 먼저 알린다. `JobManager`는 등록과 실행 시작을 같은 잠금으로 판단한다. 실행 중 GPU 작업은 계속 진행하고, 대기 작업은 `failed/interrupted`로 전환한다. 최종 회귀에서는 실제 미디어 TCP 응답을 열어 둔 채 분석 대역을 먼저 끝내도 대기 작업이 시작되지 않았다.

## 실행

프로젝트 루트의 PowerShell에서 실행한다.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m src.road_anomaly.api
```

`127.0.0.1:8000`, 단일 워커와 같은 FastAPI 앱을 사용한다. 기존 `-m uvicorn road_anomaly.api.main:app --app-dir src` 실행은 호환되며 그 명령에 전달한 설정으로 동작한다. 기존 API 응답, 영상 스트리밍 및 Range 계약에는 변경이 없다. [실행 문서](../../README.md#fastapi-로컬-백엔드) · [API 계약](../api_contract.md)

## 검증 환경과 완료 기준

Windows 11 x64, Python 3.14.5, Uvicorn 0.54.0, Starlette 1.10.0, FastAPI 0.165.0, 기존 RTX 3060 Ti를 사용했다. 브라우저는 Edge 158.0.4370.33과 Chrome 158.0.8127.38이다. 이전 후방 완료 작업의 영상·결과·대표 JPEG를 별도 저장소로 가져와 같은 결과를 조회했다. Edge의 주요 반복은 1280×720에서 진행했다. 테스트 신호는 작업별 검증 서버의 Uvicorn 종료 플래그로 전달했다. Python 전체 회귀에서는 별도 프로세스의 실제 TCP 미디어 연결을 열린 채로 두었다.

종료 요청을 기준으로 TCP 연결 거절 최초 관측, Uvicorn의 앱 종료 로그 수신, 프로세스 종료를 각각 기록했다. TCP 폴링 간격은 약 45 ms이고, 나머지 값은 로컬 프로세스 로그와 종료 이벤트에 따른 관측값이다. 분석 없는 종료의 검증 목표는 10초였다.

| 시나리오 | 반복 | 포트 닫힘 | 앱 종료 진입 | 프로세스 종료 |
| --- | ---: | ---: | ---: | ---: |
| 수정 전 Edge 일시 정지, 열린 탭 | Part 6.3-1 | 계측 재현 129 ms | 미진입 | 최초 실행 55초 초과 |
| 최종 유휴 상태 | 1 | 100 ms | 183 ms | 271 ms |
| 최종 Edge 일시 정지, 열린 탭 | 3 | 55–103 ms | 3,149–3,212 ms | 3,287–3,334 ms |
| 최종 Edge 재생 중 이탈 또는 탭 종료 | 3 | 49–99 ms | 114–3,133 ms | 222–3,247 ms |
| 최종 Edge 연속 시점 이동 | 3 | 51–156 ms | 135–207 ms | 242–315 ms |
| 최종 Edge 상태·결과 조회 | 3 | 98–109 ms | 192–201 ms | 300–303 ms |
| 최종 Chrome 일시 정지 및 5초 이동 | 1 | 157 ms | 211 ms | 317 ms |
| 최종 CUDA 실행 중 | 1 | 101 ms | 198 ms | 10,915 ms |
| 최종 CUDA 실행·대기 및 활성 영상 응답 | 1 | 110 ms | 3,196 ms | 10,784 ms |

최종 Windows 종료는 위 시나리오에서 모두 코드 0, `WinError 10054` 0건이었다. Edge 열린 탭 3회와 페이지 이탈 1회는 전송 요청이 한도에 도달해 취소됐다. 해당 실행은 Uvicorn 로그에 `CancelledError`를 남겼으며 프로세스와 리스너가 종료됐다. 이벤트 루프가 닫히기 전 Uvicorn 반환 표본에서는 일부 타임아웃 실행에 asyncio 연결 1개와 취소 처리 중인 HTTP 요청 작업 최대 1개가 잡혔다. 후방 CUDA 단독은 앱 종료 진입 후 10.717초를, 활성 영상·GPU·대기 동시에는 7.588초를 추가로 기다렸다. 이 차이는 HTTP 단계와 분석의 남은 처리 시간을 구분한 실측값이다. [최종 원시 기록](../../outputs/evidence/part6_3_2a_shutdown_stability/2026-11-26T04-30-06-437Z/measurements.jsonl)

큐 수정 전에 루프만 비교한 대조에서는 후방 완료 작업, Edge 1280×720, 시점 이동과 페이지 이탈 순서 및 3초 제한을 같게 했다. Proactor는 3.264초에 종료했으나 `WinError 10054` 21회와 반환 시 asyncio 연결 11개가 남았다. Selector는 3.293초에 종료했고 10054는 0회, 반환 시 asyncio 연결 1개였다. 시간 상한은 Uvicorn 제한이 제공했고, Proactor에서 관찰된 추가 연결 잔류는 Selector에서 관찰되지 않았다. [동일 조건 비교](../../outputs/evidence/part6_3_2a_shutdown_stability/2026-11-26T04-26-45-618Z/measurements.jsonl)

README의 정확한 모듈 명령도 별도로 실행했다. 헬스 확인 후 검증용 Windows 프로세스 그룹에 Ctrl+Break를 보냈을 때 포트 닫힘 375 ms와 앱 종료·프로세스 종료 로그 376 ms를 확인했다. Uvicorn은 받은 종료 신호를 정상 종료 뒤 다시 발생시키며, 이 콘솔 실행의 종료 코드는 3이었다. 기존 작업 파일은 동일했다. [콘솔 신호 기록](../../outputs/evidence/part6_3_2a_shutdown_stability/cli_ctrl_break_20261126T043004890987Z.json) · [Uvicorn 신호 처리](https://github.com/Kludex/uvicorn/blob/0.54.0/uvicorn/server.py)

## 기능 회귀 및 보존

- 실제 health/status/results/JPEG와 HEAD, Range 206의 헤더 및 원본 바이트, Range 416의 `invalid_range` JSON을 대조했다. 같은 저장소의 두 번째 워커는 시작 코드 3으로 거부됐다.
- Edge에서 재생, 페이지 이탈 및 탭 닫기, 장면 반복 선택에 따른 Range와 시각을 확인했다. Chrome에서 후방 원본을 재생하고 5초 지점으로 이동했다.
- 실제 CUDA 작업 두 건을 완료하고 재시작 후 각 결과를 조회했다. 이전 완료 작업 결과 JSON도 일치했다. 별도 저장소에 중단을 재현한 `running` 및 `queued` 메타데이터 두 건은 재시작할 때 각각 `failed/interrupted`로 복구됐다. 원본 후방 MP4와 가중치의 SHA-256은 검증 전후 일치했다.
- `.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests`에서 152개, React `npm run typecheck -- --force`·`npm run lint`·`npm run build`, `npm test -- --workers=1`에서 Playwright Mock·예시 12개를 통과했다. 기존 Starlette 테스트 클라이언트 경고와 손상 입력에 대한 디코더 로그는 그대로 관찰됐다.

Windows의 검증 조건에서 P1의 무기한 종료 대기를 해결했다. 일시 정지된 전송이 한도를 넘기면 진행 중 응답은 끊긴다. GPU 추론 자체가 장시간 멈출 때는 기존대로 분석 완료를 기다린다. 다른 운영체제와 브라우저는 별도 검증이 필요하다. 사용자 작업 저장소를 대상으로 실제 중단을 유도하지 않았다.

시각적 증빙과 종료 원시 로그는 로컬 경로에 보관했다. [증빙 목록](../../outputs/evidence/part6_3_2a_shutdown_stability/evidence_notes.md)
