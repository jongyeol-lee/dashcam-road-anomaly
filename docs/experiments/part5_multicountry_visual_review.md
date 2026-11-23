# Part 5.2-2 — RDD2022 Japan·India 이미지·라벨 시각 검증 및 중복 후보 분석

검증일 **2026-11-23 (KST)**

**Japan을 D10·D40 검토의 첫 후보로, India를 선별적인 D40과 역광 사례의 후보로 권합니다.** Japan에서 가로 균열과 노면 파손을 감싸는 박스를 확인했고, India에서는 함몰 의심 영역을 잘 감싸는 사례와 거친 갓길·보수 흔적을 구분하기 어려운 사례를 모두 봤습니다. 두 나라의 전방 주행 구도는 참고할 만하며, `road_sample_04`의 강한 역광과 작은 노면 영역을 다루려면 실제 블랙박스의 라벨이 있는 검증 영상이 필요합니다.

## 검증 범위와 미리보기

Part 5.2-1의 seed `42` 샘플 CSV를 그대로 사용했습니다. `C:\Projects\dashcam-road-anomaly 데이터&가이드라인`의 `Japan.zip`과 `India.zip`에서 해당 JPG·XML 92쌍을 직접 읽었습니다. 접촉 시트의 파일명과 매니페스트의 `preview` 경로로 원본 해상도의 미리보기를 열 수 있습니다. [기존 검사 보고서](part5_multicountry_data_inspection.md) · [기존 샘플 CSV](../../data/processed/rdd2022_japan_india_inspection/sample_candidates.csv) · [시각 검토 매니페스트](../../data/processed/rdd2022_japan_india_visual_review/visual_review_manifest.csv)

| 샘플 범주 | Japan 미리보기 | India 미리보기 | Japan 시트 | India 시트 |
| --- | ---: | ---: | --- | --- |
| D00 | 10 | 10 | [D00](../../data/processed/rdd2022_japan_india_visual_review/contact_sheets/japan/D00.jpg) | [D00](../../data/processed/rdd2022_japan_india_visual_review/contact_sheets/india/D00.jpg) |
| D10 | 10 | 10 | [D10](../../data/processed/rdd2022_japan_india_visual_review/contact_sheets/japan/D10.jpg) | [D10](../../data/processed/rdd2022_japan_india_visual_review/contact_sheets/india/D10.jpg) |
| D20 | 10 | 10 | [D20](../../data/processed/rdd2022_japan_india_visual_review/contact_sheets/japan/D20.jpg) | [D20](../../data/processed/rdd2022_japan_india_visual_review/contact_sheets/india/D20.jpg) |
| D40 | 10 | 10 | [D40](../../data/processed/rdd2022_japan_india_visual_review/contact_sheets/japan/D40.jpg) | [D40](../../data/processed/rdd2022_japan_india_visual_review/contact_sheets/india/D40.jpg) |
| XML에 객체가 없음 | 5 | 5 | [객체 0개](../../data/processed/rdd2022_japan_india_visual_review/contact_sheets/japan/background.jpg) | [객체 0개](../../data/processed/rdd2022_japan_india_visual_review/contact_sheets/india/background.jpg) |
| 기존 오류 의심 | 1 | 1 | [오류](../../data/processed/rdd2022_japan_india_visual_review/contact_sheets/japan/suspect.jpg) | [오류](../../data/processed/rdd2022_japan_india_visual_review/contact_sheets/india/suspect.jpg) |
| 합계 | 46 | 46 | 6개 | 6개 |

이미지 영역을 리사이즈하지 않고 위쪽에 국가, 파일명, 해상도, XML 객체 수를 붙였습니다. D00은 하늘색, D10은 초록색, D20은 자홍색, D40은 주황빛 빨간색으로 표시했습니다. 알려진 기타 클래스는 회색입니다. 여러 클래스가 섞인 이미지에도 유효한 박스를 모두 겹쳐 표시했습니다. XML 좌표와 오류는 매니페스트의 `boxes`와 `auto_issues`에 기록했습니다. JPG 경계와 같은 최대 좌표는 렌더링에서만 마지막 픽셀로 제한했습니다.

## 자동 검증과 기존 오류 확인

JPG 92장 모두 디코딩됐습니다. Japan 46장은 600×600, India 46장은 720×720이었습니다. 각 이미지의 JPEG 헤더·원본 디코딩 크기·XML 크기와 XML 파일명을 대조했습니다. EXIF Orientation은 India 35장에서 `1`이었고 나머지 57장은 태그가 없었습니다. ICC 프로파일은 0장이었으며, 92쌍 모두 회전 전 픽셀 좌표계에서 해상도가 맞았습니다. XML 객체 241개 중 **239개**를 유효 박스로 그렸습니다. [검사 요약 JSON](../../data/processed/rdd2022_japan_india_visual_review/visual_review_summary.json)

| 샘플 | 자동 검사 | 원본 크기에서 확인한 내용 |
| --- | --- | --- |
| [Japan_001265](../../data/processed/rdd2022_japan_india_visual_review/previews/japan/Japan_001265.jpg) | 네 번째 D20 좌표 `(198, 474, 198, 475)`는 너비 0 | D00 한 개와 D20 두 개를 표시했습니다. 너비 0인 객체는 좌표와 오류를 기록하고 박스 그리기에서 제외했습니다. 화면만으로 의도한 박스 범위를 결정하기 어렵습니다. |
| [India_006389](../../data/processed/rdd2022_japan_india_visual_review/previews/india/India_006389.jpg) | 유일한 객체의 좌표 `(455, 490, 570, 663)`는 범위 안이며 코드 `D0w0`는 미정의 | 해당 위치를 황색 `? D0w0`로 표시했습니다. 박스 안에 차선 도색과 어두운 선형 자국이 겹쳐 의도한 클래스를 판단하기 어렵습니다. |

## 이미지에서 확인한 라벨 품질

12개 시트에서 92장의 구도와 박스 배치를 훑고 **28장**을 원본 크기로 열었습니다. 이 28장에는 Japan 12장, India 16장과 XML에 객체가 없는 이미지 10장 전부가 포함됩니다. 개별 관찰을 매니페스트에 기록했고, 원본 크기에서 판정하지 않은 64장은 `미검토`로 표시했습니다. 원본 크기에서 본 사례도 파손 종류를 확정하기 어려우면 `판단 보류`로 기록했습니다. `user_notes` 열은 사용자가 판정을 보완할 때 사용합니다.

- **박스가 파손 의심 영역을 감싼 사례.** Japan에서는 노란 중앙선 옆 D00 박스에 가는 세로 자국이 보였고, D40 박스가 우하단의 불규칙한 파손 가장자리를 감싼 사례가 있었습니다. India에서는 D40 박스가 도로 가장자리의 물이 고인 듯한 함몰 의심 영역을 감쌌습니다. [Japan D00](../../data/processed/rdd2022_japan_india_visual_review/previews/japan/Japan_002183.jpg) · [Japan D40](../../data/processed/rdd2022_japan_india_visual_review/previews/japan/Japan_006675.jpg) · [India D40](../../data/processed/rdd2022_japan_india_visual_review/previews/india/India_004387.jpg)
- **박스 크기와 클래스 경계.** Japan의 `005848`에서 중앙 D10은 가로 선형 자국을 따라가며 양끝의 작은 박스는 도색과 만납니다. `010284`의 D20은 화면 면적의 54.7%로, 망상 균열과 함께 아래쪽 와이퍼 영역도 포함합니다. India의 `001935`에서는 D10 박스에 차선과 포장 경계가 겹치고, `005550`의 여러 D40 박스는 모래·골재처럼 보이는 거친 표면을 포함합니다. 포트홀의 함몰 경계와 D20·보수 흔적을 구별할 필요가 있습니다. [Japan D10](../../data/processed/rdd2022_japan_india_visual_review/previews/japan/Japan_005848.jpg) · [Japan D20](../../data/processed/rdd2022_japan_india_visual_review/previews/japan/Japan_010284.jpg) · [India D10](../../data/processed/rdd2022_japan_india_visual_review/previews/india/India_001935.jpg) · [India 거친 포장](../../data/processed/rdd2022_japan_india_visual_review/previews/india/India_005550.jpg)
- **누락 의심.** Japan `004978`에는 작은 가로 균열 박스 밖에 노면 중앙에서 하단까지 이어지는 긴 선이 있습니다. 객체 0개인 Japan `008266`·`009522`와 India `001018`에도 선형 자국이 보입니다. 균열과 시공 이음매, 보수 흔적을 구분한 뒤 누락 여부를 정해야 합니다. 이 관찰은 배경 후보를 자동으로 정상 도로로 분류할 때의 위험을 보여줍니다. [박스 밖 종방향 선](../../data/processed/rdd2022_japan_india_visual_review/previews/japan/Japan_004978.jpg) · [Japan 객체 없는 샘플](../../data/processed/rdd2022_japan_india_visual_review/previews/japan/Japan_008266.jpg) · [India 객체 없는 샘플](../../data/processed/rdd2022_japan_india_visual_review/previews/india/India_001018.jpg)
- **판독이 어려운 사례.** Japan `007840`은 흐림과 나무 그림자로 D20의 경계가 희미합니다. India `005389`는 역광과 앞유리 반사가 강하고 `003528`은 노면이 어둡고 차량에 일부 가립니다. `005389`의 D20 위치에 어두운 파손 의심 영역은 보이며, 포트홀과의 구분은 보류했습니다. [Japan 그림자·흐림](../../data/processed/rdd2022_japan_india_visual_review/previews/japan/Japan_007840.jpg) · [India 역광](../../data/processed/rdd2022_japan_india_visual_review/previews/india/India_005389.jpg) · [India 가림](../../data/processed/rdd2022_japan_india_visual_review/previews/india/India_003528.jpg)

## 중복과 유사 장면 후보

원본 JPG 바이트의 SHA-256, 디코딩한 BGR 배열의 크기와 픽셀 바이트를 합친 SHA-256, 128비트 dHash를 비교했습니다. Czech 검사와 같이 회색조를 9×9로 축소하고 가로·세로 인접 픽셀 비교 각 64비트를 사용했습니다. dHash 후보는 해밍 거리 8 이하입니다. 축소로 크기 차이와 가벼운 압축 변화에 덜 민감하지만, 시점 변화와 이동에 따라 해밍 거리가 커질 수 있습니다.

| 범위 | 비교 쌍 | JPG 해시 일치 | 픽셀 해시 일치 | dHash 8 이하 후보 |
| --- | ---: | ---: | ---: | ---: |
| Japan 내부 | 1,035 | 0 | 0 | 0 |
| India 내부 | 1,035 | 0 | 0 | 0 |
| 국가 간 | 2,116 | 0 | 0 | 0 |
| 합계 | 4,186 | 0 | 0 | 0 |

시트에서 발견한 India 내부 장면 두 쌍을 원본 이미지로 나란히 비교했습니다. 두 쌍은 CSV에서 `visual_context`이며, 같은 장소·주행·파손 객체인지에 대한 판정은 `미검토`입니다. 92장 밖의 자료는 이번 예비 비교 범위 밖입니다. [중복 및 유사 후보 CSV](../../data/processed/rdd2022_japan_india_visual_review/duplicate_candidates.csv)

| 이미지 쌍 | 해밍 거리 | 공통으로 보이는 배경 |
| --- | ---: | --- |
| `India_001094` / `India_009842` | 32 | 왼쪽 공사 펜스와 철근 기둥, 원거리 고층 건물. 차량과 촬영 각도가 다릅니다. [비교 이미지](../../data/processed/rdd2022_japan_india_visual_review/duplicate_candidates/comparisons/visual_context_01.jpg) |
| `India_001902` / `India_004342` | 21 | 왼쪽 작은 건물, 오른쪽 가로등과 수목, 비슷한 포장. 노면 위치와 박스 배치가 다릅니다. [비교 이미지](../../data/processed/rdd2022_japan_india_visual_review/duplicate_candidates/comparisons/visual_context_02.jpg) |

## 촬영 환경과 블랙박스 비교

| 검토 영상·이미지 | 관찰된 구도와 조건 |
| --- | --- |
| Japan | 좁은 주택가와 교외 포장도로, 선명한 차선과 노면 문자, 맑은 날과 흐린 날, 수목·건물 그림자를 봤습니다. 전방 소실점에서 하단으로 노면이 넓어지고 일부 사진은 와이퍼와 앞유리 반사가 보입니다. |
| India | 전방에 교통이 섞인 넓은 도로와 공사 주변의 모래·거친 포장을 봤습니다. 보닛이 하단에 보이는 사진이 있고, 주간의 강한 그늘과 역광·저대비 장면이 있습니다. |
| Czech v2 | 확인한 D00·D40 미리보기도 차량 전방의 600×600 주간 사진입니다. 차선·횡단보도와 하단 보닛, 상단 앞유리 패턴이 보입니다. [Czech D00](../../data/processed/rdd2022_czech_v2/bbox_previews/D00_Czech_000006.png) · [Czech D40](../../data/processed/rdd2022_czech_v2/bbox_previews/D40_Czech_000037.png) |
| `road_sample_04` 프레임 B | 1920×1080. 운전대, 대시보드, 룸미러가 크게 들어오며 낮은 태양이 앞유리에 반사됩니다. 확인할 노면은 화면 중앙의 좁은 영역에 있고, 우측 차로 Crop에서 교차하는 자국이 보입니다. [프레임 B](../../outputs/video_analysis/road_sample_04_diagnostic/frames/frame_B.jpg) · [노면 Crop](../../outputs/video_analysis/road_sample_04_diagnostic/crops/crop_B.jpg) |

카메라 높이는 이미지에서 보이는 차량 전방 원근과 보닛·와이퍼 위치로 비교했습니다. 실제 장착 높이는 미확인입니다. 장면 예시 한 장씩에서 보이는 차도의 경계를 거칠게 따라 면적을 추정하면 Japan `004978` 약 38%, India `004342` 약 28%, Czech `000037` 약 15%, `road_sample_04` B 약 2%입니다. 이 수치는 사진별 구도 차이를 나타내는 육안 추정이며, 촬영 조건의 국가별 평균과 야간 적합성은 미확인입니다.

| 유효 박스 면적 중앙값 / 전체 이미지 면적 | Japan | India |
| --- | ---: | ---: |
| D00 | 0.95% | 1.73% |
| D10 | 0.84% | 2.23% |
| D20 | 7.58% | 12.68% |
| D40 | 0.56% | 0.79% |

두 나라 샘플에 화면 면적 1% 미만의 박스가 있으며, 가는 균열은 특히 시트에서 보기 어렵습니다. `road_sample_04`에는 확인된 정답 박스가 없어 객체 면적을 직접 비교할 근거가 부족합니다. 차량 내부 가림과 노면 점유율의 차이는 실제 블랙박스에서 테스트할 가설입니다. 이번에 본 계층별 샘플로 전체 데이터의 라벨 오류 빈도나 한국 도로의 대표성을 추정하는 판단은 보류합니다. [Part 5.1 진단](part5_resolution_crop_diagnostic.md)

## Part 5.2-3 잠정 추천

1. Japan D10·D40에서 박스와 파손 영역이 잘 맞고 차선·보수 흔적을 구분할 수 있는 장면부터 검토합니다. India D40은 함몰 형태가 식별되는 장면과 촬영 조건이 다양한 장면을 선별합니다. 역광 사례는 파손을 판독할 수 있는지 먼저 확인합니다.
2. 폭 0의 Japan D20, India `D0w0`, 지나치게 넓은 박스 및 누락 의심 샘플은 원본과 기준을 다시 확인합니다. XML에 객체가 없는 이미지도 배경 후보로 사용하기 전에 따로 봅니다.
3. 전체 학습 후보의 이미지·주행 구간 중복을 검사합니다. dHash에서는 놓친 장면이 있었으므로 제공되는 경우 촬영 구간 식별자와 함께 비교합니다. 실제 블랙박스 평가용으로는 작은 파손, 역광, 가림이 있는 라벨링된 여러 주행 구간을 확보합니다.

## 재현 및 테스트

기존 Python·OpenCV·NumPy를 사용했습니다. 프로젝트에 설치된 Pillow로 JPEG 헤더와 EXIF를 읽고, 박스 검사는 Part 5.2-1, dHash는 Czech 검사 코드를 재사용했습니다. 기본 Python에 접근 가능한 실행으로 아래 명령을 수행했습니다. 새 실행에는 `--output-dir`로 새 경로를 지정합니다. 스크립트가 자동 검사 결과를 생성한 뒤, 이번 실행의 개별 관찰 28건과 육안 유사 후보 2쌍을 CSV·JSON 및 비교 이미지에 기록했습니다. [시각 검증 스크립트](../../scripts/review_rdd2022_japan_india.py) · [테스트 코드](../../tests/test_rdd2022_visual_review.py)

```powershell
$rddReviewSource = 'C:\Projects\dashcam-road-anomaly 데이터&가이드라인'
.\.venv\Scripts\python.exe -B -X utf8 scripts\review_rdd2022_japan_india.py --japan-zip (Join-Path $rddReviewSource 'Japan.zip') --india-zip (Join-Path $rddReviewSource 'India.zip')
.\.venv\Scripts\python.exe -B -X utf8 -m unittest -v tests.test_rdd2022_visual_review
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -v
```

실제 ZIP 실행과 신규 테스트 **3개**, 전체 회귀 테스트 **51개**가 통과했습니다. 작업 범위는 읽기 전용 데이터 검사, 미리보기와 판정 자료 생성, 실험 보고서 작성입니다.
