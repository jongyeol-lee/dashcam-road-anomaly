# Part 5.3-2 — 전·후방 블랙박스 균열 후보 검토 준비

작업일 **2026-11-23 (KST)** · 실행 이름 `part532_candidate_review`

**2026-11-25 Part 5.3-2 종료.** 사용자가 승인한 v3에서 평가용 GT v1을 발행·검증했습니다. Part 5.3-3 입력 경로와 용도별 이미지 수는 발행 보고서에 있습니다. [발행 결과](part5_dashcam_manual_box_drafts.md#평가용-gt-v1-발행)

**2026-11-24 후속 검증.** 아래의 43행 CSV는 추출 당시의 기록입니다. 이후 사용자가 검토한 14장의 최신 판정은 버전별 초안에 있습니다. D20 5개와 정상 배경 3장은 승인 대기이며, 좌표가 있는 보류 8개와 전체 제외 3장은 별도로 관리합니다. [이미지·버전·박스별 승인표](part5_dashcam_manual_box_drafts.md#평가용-gt-최종-승인표) · [협업 기록](../ai_collaboration/04_manual_annotation.md#배경-수동-검토-완료와-v3-승인-대기)

사용자가 지정한 세 구간에서 35장, 구간 밖에서 배경 검토 후보 8장을 추출했습니다. 의심 구간의 14장과 배경 후보 8장을 우선 검토 대상으로 표시했습니다. 43장 모두 `미검토`이며 사용자 판정과 클래스는 비어 있습니다. [검토 매니페스트](../../data/processed/dashcam_validation/part532_candidate_review/review_manifest.csv) · [구간별 대표 목록](../../data/processed/dashcam_validation/part532_candidate_review/extraction_summary.json)

## 영상 출처와 이용 조건

사용자가 내려받은 두 MP4는 `data/raw/dashcam_validation/`에 있습니다. 두 파일의 Windows 다운로드 기록에 Mendeley Data가 출처로 남아 있고, Jihad Dib, Konstantinos Sirlantzis, Gareth Howells가 공개한 *An Annotated Water-Filled, and Dry Potholes Dataset for Deep Learning Applications* 버전 1의 설명에 두 파일명이 각각 전방·후방 영상으로 명시돼 있습니다. DOI는 `10.17632/tp95cdvgm8.1`입니다. 이 출처는 다운로드 기록과 게시된 파일명에 근거하며, 게시자가 제공한 파일별 체크섬은 확인하지 못했습니다. [Mendeley Data 원본 게시 페이지](https://data.mendeley.com/datasets/tp95cdvgm8/1)

원본 게시 페이지의 데이터셋 라이선스 표기는 **CC BY 4.0**입니다. 검토 이미지를 공유할 경우 저작자와 원본, 라이선스를 표시하고 MP4에서 프레임을 추출했거나 ROI를 덧그렸다는 변경 내용을 밝힙니다. [CC BY 4.0 이용 조건](https://creativecommons.org/licenses/by/4.0/deed.ko)

## 입력 영상과 추출 기준

OpenCV 5.0.0의 FFmpeg 백엔드로 두 영상을 처음부터 끝까지 디코딩했습니다. 길이는 확인한 비디오 프레임 수를 FPS로 나눈 값이며, 마지막 디코더 시각은 마지막 프레임의 시작 시각입니다. [영상별 메타데이터와 전후 SHA-256](../../data/processed/dashcam_validation/part532_candidate_review/extraction_summary.json)

| 영상 | 해상도 | FPS | 전체 / 디코딩 프레임 | 길이 | 마지막 디코더 시각 |
| --- | --- | ---: | ---: | ---: | ---: |
| `Dashcam-Front.mp4` | 1920×1080 | 30.0 | 1,021 / 1,021 | 34.0333초 | 34.0000초 |
| `Dashcam-Rear.mp4` | 1920×1080 | 30.0 | 1,080 / 1,080 | 36.0000초 | 35.9667초 |

세 의심 구간의 양 끝을 포함해 0.25초마다 목표 시각을 만들고, 목표 이상인 첫 프레임을 골랐습니다. 프레임 번호는 0부터 시작합니다. 예를 들어 목표 14.25초는 30 fps에서 427.5프레임에 해당하므로 프레임 428을 저장하고 실제 추정 시각 `428 ÷ 30 = 14.2667초`를 표시합니다. 인덱스 계산은 유리수로 하고, 동일 영상·인덱스에 여러 목표가 대응하면 파일을 한 번만 저장합니다. CSV에는 전체 목표 시각, `frame_index / fps`로 구한 추정 시각, OpenCV가 반환한 밀리초, 해상도, PNG의 SHA-256을 기록했습니다. [프레임 메타데이터](../../data/processed/dashcam_validation/part532_candidate_review/frame_metadata.csv)

## 세 의심 구간과 배경 검토 후보

아래 시각은 저장된 프레임의 추정 시각을 소수 넷째 자리까지 표시한 값입니다. Contact Sheet에 각 구간의 전체 프레임, 영상 파일명, 프레임 번호, 시각과 `Priority review` 표시를 넣었습니다. 우선 검토 목록과 각 이미지의 정확한 시각과 경로는 추출 요약에 있습니다. [추출 요약](../../data/processed/dashcam_validation/part532_candidate_review/extraction_summary.json)

| 사용자 지정 구간 또는 배경 검토 | 추출 | 우선 | 우선 검토 시각(초) | Contact Sheet |
| --- | ---: | ---: | --- | --- |
| Front 14–18초 | 17 | 6 | 14.2667, 15.2667, 15.7667, 16.2667, 17.0000, 17.7667 | [전방 14–18초](../../data/processed/dashcam_validation/part532_candidate_review/contact_sheets/front_14_18.jpg) |
| Rear 3–5초 | 9 | 4 | 3.5000, 4.0000, 4.5000, 5.0000 | [후방 3–5초](../../data/processed/dashcam_validation/part532_candidate_review/contact_sheets/rear_03_05.jpg) |
| Rear 17–19초 | 9 | 4 | 17.0000, 17.5000, 18.5000, 19.0000 | [후방 17–19초](../../data/processed/dashcam_validation/part532_candidate_review/contact_sheets/rear_17_19.jpg) |
| Front 배경 후보 | 4 | 4 | 2.5000, 7.0000, 11.5000, 23.0000 | [전방 배경](../../data/processed/dashcam_validation/part532_candidate_review/contact_sheets/front_background.jpg) |
| Rear 배경 후보 | 4 | 4 | 1.0000, 8.5000, 13.5000, 23.0000 | [후방 배경](../../data/processed/dashcam_validation/part532_candidate_review/contact_sheets/rear_background.jpg) |

전방에서는 주차 차량 옆 직선 구간, 굽은 길과 교차로 진입에서 노면 자국의 거리와 방향이 달라지는 프레임을 골랐습니다. 후방에서는 노면의 불규칙한 자국이 뒤로 멀어지거나 차선과 포장 경계가 함께 보이는 시점을 우선했습니다. 구도가 거의 같은 연속 프레임은 추가 검토용으로 남겼습니다. 배경 후보에는 차선, 포장 보수로 보이는 직사각형 자국, 창문에 겹쳐 보이는 줄무늬가 있는 장면을 포함했습니다. 배경 후보의 파손 유무도 수동 검토 대상입니다. [전방 17.0000초 원본](../../data/processed/dashcam_validation/part532_candidate_review/frames/front/front_000510.png) · [후방 4.0000초 원본](../../data/processed/dashcam_validation/part532_candidate_review/frames/rear/rear_000120.png) · [후방 17.5000초 원본](../../data/processed/dashcam_validation/part532_candidate_review/frames/rear/rear_000525.png)

의심 구간마다 `similar_frame_group_ids`를 부여해 연속 관찰을 연결했습니다. 이 그룹은 중복 검토와 분할을 관리하기 위한 단위입니다. 같은 영상 안에서 SHA-256이 일치하는 PNG는 0쌍이었지만, 인접 프레임에는 유사한 노면 자국이 반복됩니다. 한 그룹 안에서도 서로 다른 자국이 보일 수 있으므로 실제 파손의 동일성은 사람이 확인합니다. 두 카메라 영상은 화면의 촬영 시각과 주변 장면이 대응해 같은 주행일 가능성이 있어, 모든 행에 동일한 `source_drive_group_id`를 기록했습니다. 향후 데이터 분할 시 이 두 영상을 한 단위로 유지합니다. [후보·유사 그룹과 이미지 목록](../../data/processed/dashcam_validation/part532_candidate_review/review_manifest.csv)

## ROI B 시각 검토

Part 5.3-1 코드의 `ROIS['B']`를 읽었고 기존 실행의 `roi_config.json`과 좌표가 일치했습니다. 두 영상에서 경계는 위쪽 기준 `y = 0.60`, 즉 **648px**입니다. ROI 비교 파일은 왼쪽에 원본, 오른쪽에 청록색 경계와 음영을 넣은 사본을 배치했습니다. `frames/front`와 `frames/rear`의 개별 PNG는 디코딩된 1920×1080 픽셀을 그대로 담고 있습니다. [Part 5.3-1 ROI 설정과 결과](part5_road_roi_diagnostic.md)

- **Front 17.0000초**에는 앞유리 아래쪽으로 가까운 전방 노면이 넓게 보입니다. 교차로 점선 오른쪽의 그물처럼 보이는 선 대부분이 `y = 648px` 아래 음영에 들어갑니다. 유리 반사와 노면 자국은 인접 프레임을 함께 열어 구분할 필요가 있습니다. [전방 17.0000초 ROI 비교](../../data/processed/dashcam_validation/part532_candidate_review/roi_previews/front/front_000510.jpg)
- **Rear 3.5000초와 4.0000초**에는 화면 왼쪽 아래의 불규칙한 자국이 각각 음영 안과 경계에 걸친 위치에서 보입니다. 뒤쪽 창문을 가로지르는 흐린 띠도 노면과 겹칩니다. [후방 3.5000초 ROI 비교](../../data/processed/dashcam_validation/part532_candidate_review/roi_previews/rear/rear_000105.jpg) · [후방 4.0000초 ROI 비교](../../data/processed/dashcam_validation/part532_candidate_review/roi_previews/rear/rear_000120.jpg)
- **Rear 17.5000초**에도 가느다란 선들이 경계 양쪽에 보입니다. 두 카메라에서 하단 40%에 가까운 노면이 포함되므로, 이전 영상의 고정 B를 그대로 쓰면 검토할 노면을 제외할 수 있습니다. 이번에는 ROI를 표시만 했으며 정답 박스가 확정된 뒤에 위치별 손실과 Recall을 평가할 수 있습니다. [후방 17.5000초 ROI 비교](../../data/processed/dashcam_validation/part532_candidate_review/roi_previews/rear/rear_000525.jpg)

## 수동 검토와 후속 평가

1. `review_manifest.csv`에서 `review_priority`가 `우선`인 행부터 확인합니다. `image_path`와 `roi_preview_path`는 `part532_candidate_review/` 기준 상대 경로입니다. 얇은 선은 개별 PNG를 확대하고, 필요하면 Contact Sheet에서 전후 프레임을 찾습니다. 두 CSV는 UTF-8 BOM으로 저장했습니다. [검토 매니페스트](../../data/processed/dashcam_validation/part532_candidate_review/review_manifest.csv)
2. `user_decision`에 `균열 확인`, `파손 없음`, `판단 보류`, `라벨링 제외` 중 하나를 기록합니다. 차선, 포장 이음매, 보수 자국, 유리 반사와 구분이 어려우면 `user_notes`에 이유를 남깁니다. 같은 흠집이 반복해서 보이는 경우 해당 프레임 ID를 함께 적습니다.
3. 균열로 확인한 경우 원본 PNG에서 Bounding Box와 D00·D10·D20 클래스를 검토해 확정합니다. 정답 데이터는 이 검토가 끝난 뒤 생성합니다. 이후 같은 전체 프레임 예측으로 ROI 없음과 B를 비교해 남은 정탐, 제외된 정탐, 실내와 노면 오탐을 전·후방 및 주행 구간별로 집계합니다. 이번 작업에서는 YOLO 추론과 성능 평가를 실행하지 않았습니다.

## 재현과 검증

Python과 OpenCV를 사용했습니다. 기존 영상 읽기와 순차 디코딩을 공용 함수로 옮겨 기존 추출 CLI와 새 스크립트가 공유합니다. 같은 이름의 검토 폴더가 이미 있으면 실행을 중단하므로 작성한 매니페스트가 보존됩니다. [검토 자료 생성 스크립트](../../scripts/prepare_dashcam_review.py) · [공용 영상 읽기](../../src/road_anomaly/video.py) · [테스트](../../tests/test_dashcam_review.py)

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts\prepare_dashcam_review.py --run-name part532_candidate_review_repeat
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -p test_dashcam_review.py -v
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -v
```

신규 테스트 8개와 이를 포함한 전체 회귀 테스트 80개를 통과했습니다. 중복 인덱스, 구간과 시각 대응, 원본 해상도 및 PNG 픽셀, 두 카메라의 파일명 구분, Contact Sheet, CSV 경로, ROI 경계, 기존 검토 폴더 보호와 디코딩 실패 시 정리를 검사했습니다.

두 원본을 다시 디코딩해 43장 모두 PNG의 픽셀과 OpenCV 타임스탬프가 해당 원본 프레임과 일치하는 것을 확인했습니다. `frame_index / fps`와 디코더 시각의 차이는 0.000001ms 미만이었습니다. 43개 ROI 비교 이미지의 648px 경계, 두 CSV의 이미지 경로, 메타데이터에 기록한 PNG의 SHA-256, 원본 MP4 두 개의 작업 전후 SHA-256도 대조했습니다. [해시 및 실행 요약](../../data/processed/dashcam_validation/part532_candidate_review/extraction_summary.json)
