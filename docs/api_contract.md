# 로컬 분석 API 계약

2026-11-27 · 로컬 단일 사용자 MVP · 기본 주소 `http://127.0.0.1:8000`. 현재 응답의 정확한 타입과 필수 필드는 `/openapi.json`에서 확인할 수 있습니다. React + Vite의 기본 origin은 `http://localhost:5173` 또는 `http://127.0.0.1:5173`입니다. 인증과 사용자별 격리는 없습니다. [Pydantic 모델](../src/road_anomaly/api/schemas.py)

## 엔드포인트

| Method | 경로 | 성공 응답 | 역할 |
| --- | --- | --- | --- |
| GET | `/api/health` | 200 JSON | API 응답 가능 여부. CUDA·가중치 준비 보장은 아님 |
| POST | `/api/jobs` | 202 JobStatus | MP4 검증·저장 후 작업 생성 |
| GET | `/api/jobs` | 200 JobHistory | 저장된 분석 이력과 검토 요약 |
| GET | `/api/jobs/{job_id}` | 200 JobStatus | 상태와 시각·실패 정보 |
| GET | `/api/jobs/{job_id}/results` | 200 AnalysisResults | 완료 결과 |
| GET | `/api/jobs/{job_id}/report` | 200 JobReport | 완료 작업의 분석 및 저장된 검토 스냅샷 |
| GET | `/api/jobs/{job_id}/exports/csv` | 200 text/csv | 완료 작업의 전체 장면 CSV |
| GET | `/api/jobs/{job_id}/exports/xlsx` | 200 application/vnd.openxmlformats-officedocument.spreadsheetml.sheet | 완료 작업의 전체 장면 Excel |
| GET | `/api/jobs/{job_id}/reviews` | 200 JobReviews | 완료 작업의 저장된 검토 결과 |
| PUT | `/api/jobs/{job_id}/reviews/{event_id}` | 200 SceneReview | 완료 작업의 장면 한 건 저장 |
| GET / HEAD | `/api/jobs/{job_id}/video` | 200 또는 206 | 업로드 사본 MP4 및 Range 응답 |
| GET | `/api/jobs/{job_id}/scenes/{event_id}` | 200 image/jpeg | 작업의 대표 이미지 |

모든 `job_id`는 서버가 생성한 UUID이고 `event_id`는 `event_0001` 형식의 최소 네 자리 숫자입니다. 서버 로컬 경로나 모델·추론 옵션을 입력받지 않습니다. `data/`와 `outputs/`의 정적 파일 공개 경로는 없습니다.

## 업로드와 상태 조회

`multipart/form-data`의 파일 필드 `file` 하나만 보냅니다. 추가 텍스트 필드나 복수 파일은 거절합니다. 확장자는 대소문자를 구분하지 않는 `.mp4`이고 MIME만으로 정상 여부를 판단하지 않습니다. 파일별 기본 제한은 정확히 `209715200`바이트(200MiB), 요청 전체는 이 값에 multipart 오버헤드 64KiB를 더한 크기로 제한합니다. Content-Length가 없는 전송도 수신 바이트 수로 제한합니다. 파일은 1MiB 청크로 복사하며 실패한 요청의 사본은 정리합니다.

선두 `ftyp` MP4 헤더(QuickTime `qt` 제외), 유효한 FPS·크기, 전체 디코딩과 보고된 프레임 수를 검사합니다. 디코더가 오류를 복구한 파일의 모든 손상을 판별하는 검사는 아닙니다. 검증은 202 전에 수행하며 YOLO는 응답과 독립된 워커에서 실행합니다. 같은 영상을 다시 올리면 별도 작업이 생깁니다.

신규 작업의 `job.json`에는 `original_filename`과 `file_size_bytes`도 저장합니다. 표시용 파일명에는 경로의 마지막 구성 요소만 사용합니다. Windows 드라이브 접두사와 유니코드 제어·서식 문자 및 서로게이트를 제거하고 앞뒤 공백을 정리합니다. 한글과 이름 내부의 공백은 보존합니다. 255자를 넘으면 확장자를 포함해 255자로 줄입니다. 크기는 저장된 `input.mp4`의 바이트 수입니다. 파일 정보는 이력과 리포트 응답에서 제공합니다.

```javascript
const form = new FormData();
form.append("file", file);
const response = await fetch("http://127.0.0.1:8000/api/jobs", {
  method: "POST",
  body: form,
}); // Content-Type은 브라우저가 boundary와 함께 설정
const job = await response.json();
```

202 응답 예시입니다. 반환 객체는 초기 queued 스냅샷이며 즉시 조회한 상태는 running일 수 있습니다.

```json
{
  "job_id": "d54ca2ea-e702-46d5-a063-ef15286866ec",
  "status": "queued",
  "created_at": "2026-11-25T00:00:00Z",
  "started_at": null,
  "finished_at": null,
  "error": null
}
```

위 시각은 형식 설명용입니다. 모든 시각은 UTC ISO 8601이며 프론트엔드에서 필요에 따라 KST로 표시합니다. 상태 조회도 같은 구조를 반환합니다.

| 필드 | 타입·의미 |
| --- | --- |
| `job_id` | UUID 문자열 |
| `status` | `queued`, `running`, `completed`, `failed` |
| `created_at` | 작업이 저장된 시각 |
| `started_at` | 분석 워커가 시작한 시각. 실행 전 중단이면 null |
| `finished_at` | 완료·실패·중단 시각. 처리 중이면 null |
| `error` | 정상은 null, 실패는 `{code, message}` |

프론트엔드는 약 0.5~1초 간격으로 상태를 조회하고 completed/failed에서 폴링을 멈출 수 있습니다. 진행률 필드는 없습니다. 재시작 때 남아 있던 queued/running은 failed와 `error.code: interrupted`로 바뀌며 자동 재실행하지 않습니다.

## 분석 이력

| 쿼리 | 기본값 | 허용 값과 동작 |
| --- | --- | --- |
| `status` | 전체 | `queued`, `running`, `completed`, `failed` |
| `search` | 전체 | 표시용 파일명의 부분 검색. 최대 255자, 앞뒤 공백 무시, 유니코드 대소문자 구분 없음. 빈 검색어는 전체 |
| `sort` | `newest` | `newest`는 생성 시각 내림차순, `oldest`는 오름차순. 시각이 같으면 UUID도 같은 방향으로 정렬 |
| `limit` | 20 | 한 페이지에 1~100건 |
| `offset` | 0 | 정렬된 결과에서 건너뛸 건수. 0 이상의 정수 |

최근 5건은 `GET /api/jobs?limit=5&offset=0`, 완료 작업 검색은 `GET /api/jobs?status=completed&search=Dashcam&sort=oldest`로 조회합니다. 잘못된 값이나 지원하지 않는 파라미터에는 HTTP 422와 `invalid_request`를 반환합니다.

`JobHistory`는 `items`, `total`, `count`, `limit`, `offset`, `warnings`로 구성됩니다. `total`은 검색과 상태 조건이 일치하는 작업 수, `count`는 현재 페이지의 `items.length`입니다. 빈 저장소와 범위 밖 페이지 모두 HTTP 200으로 처리합니다. 범위 밖 페이지에서도 `total`은 유지됩니다.

| `items[]` 필드 | 타입·의미 |
| --- | --- |
| `job_id`, `status`, `created_at`, `started_at`, `finished_at`, `error` | 개별 상태 API와 동일 |
| `original_filename` | 업로드 시 저장한 표시용 이름. 이름이 없는 기존 작업은 null이며 비어 있지 않은 검색어에는 매칭되지 않음 |
| `file_size_bytes` | 업로드 당시 실제 크기. 기존 작업은 고정 경로의 일반 파일 크기를 조회. 확인할 수 없으면 null |
| `analysis` | `{video, event_count, analysis_seconds}`. `video`는 개별 결과 API의 구조를 재사용 |
| `reviews` | `{unreviewed, suspected, false_positive, deferred, reviewed_count}`. 전체 의심 장면 수는 `analysis.event_count` |

완료 전과 실패 상태에서는 `analysis`와 `reviews`가 null입니다. 정상적으로 분석을 마친 무탐지 작업은 `analysis.event_count`와 모든 검토 건수가 0입니다. 검토 파일이 없는 완료 작업에서는 실제 장면 전부가 미검토입니다. `reviewed_count`는 파손 의심·오탐·판단 보류의 합계이며, 명시적으로 미검토로 돌아간 장면은 미검토에 포함됩니다.

`warnings[]`는 `{job_id, error: {code, message}}` 형식입니다. 저장소 일부만 읽을 수 있으면 HTTP 200과 함께 아래 경고를 반환합니다. 비정규 UUID 경로는 목록에서 무시합니다.

| 경고 코드 | 목록과 집계에 미치는 영향 |
| --- | --- |
| `job_data_unavailable` | 유효한 작업 정보를 읽을 수 없어 행과 `total`에서 제외. 조회 조건 판정 전이므로 다른 페이지나 검색에서도 반환될 수 있음 |
| `results_unavailable` | 현재 페이지의 완료 행을 유지하고 `analysis`·`reviews`는 null |
| `review_data_invalid`, `review_read_failed` | 현재 페이지 행과 유효한 `analysis`를 유지하고 `reviews`는 null |
| `upload_size_unavailable` | 기존 업로드 경로가 허용되지 않거나 파일 종류·크기를 읽을 수 없어 `file_size_bytes`는 null. 정상적으로 누락된 기존 영상은 경고 없이 null |

프론트엔드는 null 요약을 0건으로 표시하지 않고 조회 경고와 함께 다룹니다. 완료 행의 `job_id`로 기존 React 결과 주소 `/jobs/<job_id>/results`를 열 수 있습니다. 장면 배열, JPEG, 영상과 추론 설정은 상세 API에서 가져옵니다. 전체 저장소 상태를 한 시점에 고정하지 않으므로 업로드나 검토 중에는 페이지와 요약이 바뀔 수 있습니다. 검색·정렬·필터를 바꾸면 `offset=0`부터 다시 요청합니다. [구현과 검증](experiments/part6_job_history_api.md)

## 완료 결과

| 필드 | 타입·의미 |
| --- | --- |
| `job_id`, `status` | UUID, `completed` |
| `video` | `{fps, width, height, frame_count, duration_sec}`. duration은 보고 프레임 수/FPS이며 알 수 없으면 null |
| `video_url` | 이 작업의 MP4 API 상대 URL |
| `extracted_frame_count` / `inferred_frame_count` | 추출·추론한 프레임 수 |
| `detected_frame_count` | 탐지가 있었던 서로 다른 원본 프레임 수 |
| `detection_count` / `event_count` | 박스 수 / 검토용 의심 구간 수 |
| `analysis_seconds` | 기존 분석 함수의 추출부터 결과 저장까지 벽시계 시간. HTTP 업로드·사전 디코딩·대기·API 결과 검증은 제외 |
| `profile` / `model_sha256` | `mvp` / 실제 사용한 가중치의 SHA-256 |
| `settings` | 아래의 실제 적용 설정. 경로를 포함하지 않음 |
| `timestamp_basis` | 현재 `frame_index / fps` |
| `events` | Scene 배열. 무탐지는 `[]`이며 박스·구간 수는 0 |

현재 `settings`의 키는 `interval_sec`, `max_gap_sec`, `max_event_duration_sec`, `imgsz`, `iou`, `rect`, `max_det`, `batch`, `quantize`, `classes`, `agnostic_nms`, `augment`, `tile`, `nms`, `conf`, `device`입니다. 웹은 공용 MVP 프로필과 별도 5초 제한을 사용합니다. [프로필 정의](../src/road_anomaly/video_analysis.py)

실제 검증 결과의 주요 값은 다음과 같습니다. 전체 응답은 [로컬 검증 JSON](../outputs/fastapi_validation/part61_v1/integration.json)에 있습니다.

```json
{
  "job_id": "d54ca2ea-e702-46d5-a063-ef15286866ec",
  "status": "completed",
  "video": {"fps": 30.0, "width": 1920, "height": 1080, "frame_count": 1021, "duration_sec": 34.03333333333333},
  "video_url": "/api/jobs/d54ca2ea-e702-46d5-a063-ef15286866ec/video",
  "extracted_frame_count": 69,
  "inferred_frame_count": 69,
  "detected_frame_count": 66,
  "detection_count": 234,
  "event_count": 16,
  "analysis_seconds": 10.151766499970108
}
```

위 JSON은 일부 필드만 발췌했습니다. 각 Scene의 필드는 아래와 같습니다.

| 필드 | 의미 |
| --- | --- |
| `event_id` | 해당 작업 안에서의 구간 ID |
| `class_id`, `class_name` | 0 D00 종방향 균열 / 1 D10 횡방향 균열 / 2 D20 거북등 균열 / 3 D40 포트홀 |
| `start_time_sec`, `last_detection_time_sec` | 구간 시작·마지막 탐지 시각. 영상 기준 초 |
| `representative_time_sec`, `representative_frame_index` | 대표 장면의 원본 시각·0 기반 프레임 번호 |
| `representative_xyxy` | 원본 영상 픽셀 좌표 `[x1,y1,x2,y2]` |
| `max_confidence` | 구간 내 최고 모델 점수. 파손 확률·위험 등급이 아님 |
| `detection_count`, `detected_frame_count` | 해당 구간 박스 수와 중복을 제거한 프레임 수 |
| `image_url` | 대표 JPEG API 상대 URL |

같은 클래스·최대 인접 간격 1.5초로 묶되 구간 시작부터 5초를 넘는 다음 탐지는 새 구간으로 나눕니다. 같은 시각의 박스는 함께 두고 대표는 최고 confidence, 동점은 기존 정렬의 첫 박스입니다. 객체 추적을 하지 않으므로 다른 위치의 파손이 한 구간에 들거나 같은 대상이 여러 구간에 들 수 있습니다.

## 사용자 검토 결과

`GET /api/jobs/{job_id}/reviews`는 작업 UUID와 저장된 장면 검토 배열을 반환합니다. 검토 파일이 없는 기존 완료 작업 또는 무탐지 작업은 `reviews: []`로 응답합니다. 조회에 성공한 뒤 배열에 없는 장면을 미검토로 표시할 수 있습니다. 한 번이라도 저장한 장면에는 마지막 수정 시각이 UTC ISO 8601로 포함됩니다.

```json
{
  "job_id": "d54ca2ea-e702-46d5-a063-ef15286866ec",
  "reviews": [
    { "event_id": "event_0001", "review": "suspected", "updated_at": "2026-11-26T00:00:00Z" }
  ]
}
```

`PUT /api/jobs/{job_id}/reviews/{event_id}`는 `Content-Type: application/json`과 본문 `{"review":"suspected"}`를 받습니다. 허용 값은 `unreviewed`(미검토), `suspected`(파손 의심), `false_positive`(오탐), `deferred`(판단 보류)입니다. 성공 응답은 저장한 배열 항목과 같은 `{event_id, review, updated_at}` 구조입니다. `unreviewed`로 되돌린 항목에도 수정 시각이 남습니다.

완료된 작업의 실제 장면만 변경할 수 있습니다. 기존 단일 워커와 잠금을 사용해 현재 기록을 읽고 대상 장면을 갱신한 뒤 `outputs/jobs/<job_id>/reviews.json`을 원자적으로 교체합니다. 같은 장면에 여러 요청이 들어오면 서버에서 마지막으로 저장에 성공한 요청의 값이 남습니다. 다른 장면의 변경은 함께 보존됩니다. 파일을 읽을 수 없거나 데이터가 손상되면 오류를 반환하고 기존 파일을 보존합니다. 기본 CORS 허용 origin에서 JSON PUT을 사용할 수 있습니다.

검토는 사용자 의견이며 AI 예측은 `/results`에 계속 보관됩니다. 검토 저장에는 GPU 분석이 필요하지 않습니다. 검토 조회 오류가 나도 기존 영상·분석 결과·대표 JPEG를 이용할 수 있습니다. [구현과 검증](experiments/part6_review_persistence.md)

## 분석 리포트 내보내기

리포트 조회와 두 내보내기 엔드포인트는 요청마다 `job.json`, `results.json`, `reviews.json`을 검토 저장과 같은 잠금 안에서 읽습니다. 완료 상태와 파일 간 작업·장면 식별자를 확인합니다. 성공 응답에 `Cache-Control: no-store`를 설정합니다. 검토 파일이 아직 없으면 저장된 검토가 없는 정상 상태로 처리합니다. 손상되거나 접근할 수 없는 파일은 세 엔드포인트 모두 오류를 반환합니다.

| `JobReport` 필드 | 내용 |
| --- | --- |
| `job` | `JobStatus` 필드 및 서버에 저장된 `original_filename`, `file_size_bytes`. 기존 작업에 저장되지 않은 값은 `null` |
| `results` | 기존 `AnalysisResults` 스키마. AI 원본 수치와 작업별 대표 JPEG URL 포함 |
| `reviews` | 기존 `JobReviews` 스키마. 마지막으로 저장된 의견과 수정 시각 |
| `review_summary` | `unreviewed`, `suspected`, `false_positive`, `deferred`, `reviewed_count`. 판단 보류는 검토 건수에 포함 |
| `exported_at` | 스냅샷을 읽은 UTC 시각, ISO 8601 |

CSV는 `text/csv; charset=utf-8`과 UTF-8 BOM, 쉼표 구분, CRLF 행 끝을 사용합니다. `Content-Disposition`은 `road-anomaly-<job_id>.csv` 첨부 파일명을 제공합니다. 전체 `results.events`를 저장 순서대로 한 장면당 한 행에 기록합니다. 결과 화면 필터나 정렬은 적용되지 않습니다. 정상 무탐지는 헤더만 반환합니다.

| CSV 열 순서 | 의미 |
| --- | --- |
| `job_id`, `original_filename`, `created_at`, `finished_at`, `exported_at` | 작업 UUID, 저장된 이름, 작업 등록·분석 완료·CSV 스냅샷 시각 |
| `event_id`, `class_id`, `class_name`, `class_label` | 작업 안에서의 장면 ID, AI 클래스 번호와 코드, 화면용 한글 클래스명 |
| `start_time_sec`, `last_detection_time_sec`, `representative_time_sec`, `representative_frame_index` | 원본 영상 기준 각 시각(초)과 0부터 시작하는 대표 프레임 인덱스 |
| `max_confidence`, `x1`, `y1`, `x2`, `y2` | 저장된 최대 모델 점수와 대표 박스의 영상 픽셀 좌표 |
| `detection_count`, `detected_frame_count` | 해당 구간의 탐지 박스 수와 중복을 제외한 탐지 프레임 수 |
| `review_state`, `review_label`, `review_updated_at` | 기존 검토 코드·한글 레이블·마지막 저장 시각. 저장 이력이 없으면 `unreviewed`와 빈 수정 시각 |
| `model_sha256`, `profile` | 가중치 해시와 분석 프로필 |
| `imgsz`, `conf`, `iou`, `interval_sec`, `max_gap_sec`, `max_event_duration_sec` | 입력 크기, 탐지 임계값, IoU, 샘플링 간격, 장면 병합 간격, 구간 길이 제한 |

시각은 ISO 8601로 제공하며 과거 작업에 저장된 시간대 정보가 없으면 그대로 유지합니다. 미확인 파일명·시각·설정은 빈 필드입니다. 숫자 필드는 화면 표시용 반올림 없이 저장된 수치를 사용합니다. CSV 인용 규칙으로 쉼표와 따옴표를 보존하고, 수식으로 읽힐 수 있는 파일명 선두 문자(`=`, `+`, `-`, `@`, 전각 변형 등)는 작은따옴표를 앞에 덧붙입니다. 원래 파일명이 필요한 연동에서는 JSON 리포트의 `job.original_filename`을 사용합니다. 스프레드시트에서 다시 저장한 사본에는 해당 프로그램의 변환 규칙이 적용됩니다. [OWASP CSV Injection](https://community.owasp.org/attacks/CSV_Injection)

XLSX의 `Content-Disposition`은 `road-anomaly-<job_id>.xlsx`입니다. CSV와 같은 순서로 31개 열을 제공하며, `분석 결과` 시트에 헤더 고정과 전체 행 필터를 적용합니다. 정상 무탐지는 서식이 있는 헤더 행을 반환합니다. 파일명 등 문자열은 Excel 텍스트 셀로 저장합니다. 미확인 값은 빈 셀입니다.

`created_at`, `finished_at`, `exported_at`, `review_updated_at`은 KST(UTC+09:00)로 변환한 날짜 셀이며 `yyyy-mm-dd hh:mm:ss.000 KST`로 표시합니다. 시간대가 생략된 과거 작업은 서버의 저장 기준인 UTC로 해석합니다. 영상 시각, 점수, 프레임 번호, 좌표와 설정은 숫자 셀입니다. 표시 형식은 셀 값과 별개이며, Excel의 15자리 유효 숫자와 날짜 밀리초 제한보다 정밀한 분석에는 기존 CSV를 사용합니다. [openpyxl 날짜와 시간](https://openpyxl.readthedocs.io/en/stable/datetime.html) · [Excel 숫자 정밀도](https://support.microsoft.com/en-us/excel/excel-specifications-and-limits)

React의 `/jobs/{job_id}/report`는 JSON 리포트와 기존 대표 JPEG를 조회합니다. 이미지를 모두 불러온 뒤 브라우저의 **PDF로 저장 / 인쇄**를 사용할 수 있습니다. 검토는 사용자 의견이며 Part 7 오류 분석의 후보를 찾는 데 쓸 수 있습니다. 학습용 정답 라벨로 사용하려면 별도의 검증이 필요합니다. [리포트 구현과 검증](experiments/part6_report_export.md)

## 영상과 이미지 사용

상대 URL은 API의 origin에 결합합니다. `new URL(result.video_url, apiBase)`를 video src로, `new URL(event.image_url, apiBase)`를 img src로 사용합니다. 비디오의 `loadedmetadata` 이후 `video.currentTime = event.representative_time_sec`로 이동할 수 있습니다. 실제 브라우저 코덱 재생과 타임스탬프 이동은 Part 6.2~6.3 검증 대상입니다. 가변 FPS 영상의 추정 시각 오차도 남습니다.

원본은 queued/running/failed에서도 작업이 존재하고 사본 파일이 있으면 조회할 수 있습니다. 이미지 조회는 완료된 결과에 속하는 event_id에만 허용합니다. 이미지는 원본 비율·크기이고 구간 대표 박스와 점수가 표시됩니다.

```http
GET /api/jobs/d54ca2ea-e702-46d5-a063-ef15286866ec/video
Range: bytes=0-1023

HTTP/1.1 206 Partial Content
Content-Type: video/mp4
Accept-Ranges: bytes
Content-Range: bytes 0-1023/96383988
Content-Length: 1024
```

시작·끝·suffix Range와 HEAD를 지원합니다. 무효 Range는 400, 범위 밖은 416과 `Content-Range: bytes */<size>`를 반환합니다. 재인코딩은 하지 않습니다. MP4 컨테이너가 정상이어도 브라우저가 코덱을 지원해야 합니다. Range 처리는 [Starlette FileResponse](https://starlette.dev/responses/#fileresponse)를 사용하고 실제 바이트를 원본과 대조했습니다.

## 오류

기본 오류 형식입니다. 서버 내부 경로나 traceback은 응답에 포함하지 않습니다.

```json
{"error": {"code": "results_not_ready", "message": "완료된 작업의 결과만 조회할 수 있습니다."}}
```

| HTTP | code | 조건 |
| --- | --- | --- |
| 400 | `invalid_request` | multipart 오류, 추가 필드·파일, 잘못된 Range |
| 404 | `not_found` | 없는 작업·구간·파일, 허용되지 않는 경로 |
| 409 | `results_not_ready` | queued/running/failed 작업의 결과·이미지·검토 조회, 검토 저장 또는 리포트 내보내기 |
| 413 | `upload_too_large` | 파일 또는 전체 요청 크기 초과 |
| 415 | `unsupported_file_type` | MP4 확장자 아님 |
| 422 | `invalid_request` / `empty_file` / `invalid_video` | 잘못된 UUID·event_id·검토 요청·목록 조건, 필수 파일 누락, 빈 파일, 디코딩 실패 |
| 416 | `invalid_range` | 영상 파일 범위 밖 Range |
| 500 | `internal_error` | 저장·조회 중 서버 오류. 상세는 로컬 로그 |
| 500 | `job_data_unavailable` / `results_unavailable` | 리포트용 작업 메타데이터나 분석 결과가 손상됐거나 읽을 수 없음 |
| 500 | `review_data_invalid` | 검토 JSON이 깨졌거나 작업·장면·스키마가 일치하지 않음 |
| 500 | `review_read_failed` | 검토 파일 읽기 실패 |
| 500 | `review_save_failed` | 검토 파일 쓰기 또는 교체 실패 |
| 503 | `shutting_down` | 종료 중 새 작업 등록 |

분석 중 예외는 업로드 응답을 바꾸지 않습니다. 상태 조회가 HTTP 200, `status: failed`, `error.code: analysis_failed`를 반환하고 다음 대기 작업은 계속 실행합니다. [동작·검증 보고서](experiments/part6_fastapi_backend.md)
