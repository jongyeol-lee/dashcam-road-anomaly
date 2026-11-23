# Part 5.2-1 — RDD2022 Japan·India 데이터셋 기본 검증

검사일 **2026-11-20 (KST)**

**Japan을 첫 추가 후보로 권합니다.** 이미지 100장당 D10 37.9개와 D40 21.4개가 기록됐으며, Czech v2 Train에서는 각각 14.2개와 7.0개였습니다. India는 같은 기준으로 D40이 41.4개, D10이 0.9개여서 포트홀을 집중 보강할 때 우선 검토할 만합니다. 두 나라 모두 Train XML의 99.98% 이상이 기본 검사를 통과했습니다.

## 데이터 출처와 검사 대상

`C:\Projects\dashcam-road-anomaly 데이터&가이드라인`에 있는 로컬 ZIP 두 개를 읽었습니다. 공식 RDD2022 배포는 Train에 JPG와 PASCAL VOC 형식 XML을 제공하며, 공식 Test에는 JPG를 제공합니다. 아래 수치는 로컬 ZIP에서 직접 집계했습니다. Figshare의 Version 1 배포 기록에는 CC BY 4.0으로 표시되어 있습니다. [공식 배포 안내](https://github.com/sekilab/RoadDamageDetector#dataset) · [Figshare 배포 기록](https://doi.org/10.6084/m9.figshare.21431547.v1)

| 실제 파일명 | ZIP 크기 | 전체 JPG | Train JPG | Train XML | 공식 Test JPG | 공식 Test XML |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `Japan.zip` | 1,072,598,857 B (1,022.91 MiB) | 13,133 | 10,506 | 10,506 | 2,627 | 0 |
| `India.zip` | 526,709,145 B (502.31 MiB) | 9,665 | 7,706 | 7,706 | 1,959 | 0 |

각 ZIP의 최상위 폴더는 파일명과 같은 `Japan` 또는 `India`입니다. 두 ZIP 모두 다음 경로에 파일을 보관합니다.

```text
<국가>/
  train/images/              .jpg
  train/annotations/xmls/    .xml
  test/images/               .jpg
```

## ZIP 무결성, 이미지 디코딩과 크기 대조

Python `zipfile`로 두 ZIP의 내부 목록을 읽고 모든 파일 엔트리를 끝까지 읽어 CRC와 압축 해제 길이를 검사했습니다. JPG는 시작·종료 마커를 검사하고 OpenCV로 픽셀을 디코딩했습니다. 실제 픽셀 크기는 EXIF 회전 전 좌표계에서 얻었으며, Train의 XML 너비·높이와 별도로 대조했습니다. ZIP 내부 데이터는 메모리에서 처리했습니다. 검사에 약 52초가 걸렸습니다.

| 검사 | Japan | India |
| --- | ---: | ---: |
| CRC 통과 파일 | 23,639 / 23,639 | 17,371 / 17,371 |
| 읽기·CRC 실패 파일 | 0 | 0 |
| Train JPG 디코딩 성공 | 10,506 / 10,506 | 7,706 / 7,706 |
| 공식 Test JPG 디코딩 성공 | 2,627 / 2,627 | 1,959 / 1,959 |
| Train XML과 실제 픽셀 크기 대조 | 10,506 | 7,706 |
| XML과 실제 픽셀 크기 불일치 | 0 | 0 |

| 디코딩한 해상도 | Japan Train | Japan 공식 Test | India Train | India 공식 Test |
| --- | ---: | ---: | ---: | ---: |
| 540×540 | 124 | 28 | 0 | 0 |
| 600×600 | 10,187 | 2,543 | 0 | 0 |
| 720×720 | 0 | 0 | 7,706 | 1,959 |
| 1024×1024 | 147 | 44 | 0 | 0 |
| 1080×1080 | 48 | 12 | 0 | 0 |

## Train 매칭과 라벨 오류

Train 이미지와 XML은 확장자를 뺀 파일명으로 각각 **10,506쌍**, **7,706쌍**이 일대일 대응했습니다. 두 나라 모두 짝이 없는 이미지·XML과 XML `<filename>` 불일치가 0개였으며, 모든 XML을 파싱했습니다. 유효 XML은 대응 JPG의 디코딩, 파일명·크기 일치, 클래스명, 모든 객체의 좌표 검사를 통과한 파일입니다. 알려진 기타 클래스도 좌표 검사를 받습니다.

| 좌표 또는 클래스 검사 | Japan | India |
| --- | ---: | ---: |
| 좌표 누락 | 0 | 0 |
| 숫자 변환 불가 또는 비유한 값 | 0 | 0 |
| 최소·최대 좌표 역전 | 0 | 0 |
| 너비 또는 높이 0 | 1 | 0 |
| XML에 기록된 이미지 범위 초과 | 0 | 0 |
| 실제 디코딩한 이미지 범위 초과 | 0 | 0 |
| 클래스명 누락 | 0 | 0 |
| 알려지지 않은 클래스 | 0 | 1 |

- Japan `Japan/train/annotations/xmls/Japan_001265.xml`의 4번째 객체는 D20입니다. `xmin=xmax=198`, `ymin=474`, `ymax=475`로 너비가 0입니다. 해당 XML에는 D00 1개와 D20 3개가 기록되어 있어, 오류 XML을 통째로 제외한 집계는 D00이 1개, D20이 3개 줄었습니다.
- India `India/train/annotations/xmls/India_006389.xml`의 유일한 객체에는 `D0w0`가 기록되어 있습니다. 이 코드의 의미는 시각 검증에서 확인합니다. 해당 XML을 제외해도 대상 4종의 집계는 같습니다. [파일별 오류 CSV](../../data/processed/rdd2022_japan_india_inspection/validation_errors.csv)

## Czech v2 Train과 클래스 분포 비교

Czech는 v2 매니페스트에서 `split=train`인 2,263개 행을 재집계해 기존 검사 보고서와 대조했습니다. Japan·India의 객체 수는 ZIP에서 JPG와 매칭되고 파싱된 Train XML에 적힌 원본 수치입니다. 공식 Test의 수치는 위 파일 현황 표에 기재했습니다. [Czech v2 매니페스트](../../data/processed/rdd2022_czech_v2/split_manifest.csv) · [Czech v2 검사 보고서](../../data/processed/rdd2022_czech_v2/inspection_summary.json)

| 항목 | Czech v2 Train | Japan Train | India Train |
| --- | ---: | ---: | ---: |
| 이미지 수 | 2,263 | 10,506 | 7,706 |
| 유효 XML 수 | 2,263 | 10,505 | 7,705 |
| D00 종방향 균열 객체 수 | 791 | 4,049 | 1,555 |
| D10 횡방향 균열 객체 수 | 321 | 3,979 | 68 |
| D20 거북등 균열 객체 수 | 128 | 6,199 | 2,021 |
| D40 포트홀 객체 수 | 158 | 2,243 | 3,187 |
| XML에 객체가 없는 이미지 수 | 1,410 | 794 | 3,921 |
| 대상 4종 객체가 없는 이미지 수 | 1,410 | 2,606 | 4,483 |
| 유효하지 않은 라벨 객체 수 | 0 | 1 | 1 |
| 유효하지 않은 XML 수 | 0 | 1 | 1 |

| 클래스별 등장 이미지 수 | Czech v2 Train | Japan Train | India Train |
| --- | ---: | ---: | ---: |
| D00 | 610 | 2,797 | 1,109 |
| D10 | 238 | 2,240 | 60 |
| D20 | 103 | 4,714 | 1,758 |
| D40 | 122 | 1,390 | 1,530 |

이미지 한 장에 여러 클래스가 있으면 각 클래스의 등장 이미지에 한 번씩 포함했습니다. 유효 XML만 집계하면 Japan의 D00·D20이 각각 4,048개와 6,196개입니다. 두 나라의 D10·D40 수치는 유효 XML에서도 같습니다. [클래스 비교 CSV](../../data/processed/rdd2022_japan_india_inspection/class_comparison.csv)

### 이미지당 전체 객체 수

아래 분포는 매칭된 Train XML의 모든 `<object>`를 포함합니다. 객체 0개는 XML에 객체가 기록되지 않은 경우이며, 실제 파손 여부는 시각 검토에서 확인할 항목입니다. 최대치는 Japan 13개, India 14개입니다. 객체 수별 전체 도수와 대상 4종만의 도수는 JSON에 기록했습니다. [Japan 요약](../../data/processed/rdd2022_japan_india_inspection/japan_summary.json) · [India 요약](../../data/processed/rdd2022_japan_india_inspection/india_summary.json)

| 이미지당 객체 수 | Japan Train 이미지 수 | India Train 이미지 수 |
| --- | ---: | ---: |
| 0 | 794 | 3,921 |
| 1 | 3,016 | 1,623 |
| 2 | 2,699 | 1,073 |
| 3 | 1,797 | 535 |
| 4 | 1,057 | 273 |
| 5 이상 | 1,143 | 281 |

### 대상 4종 외 클래스

CRDDC 2022는 여러 클래스가 들어 있는 공개 데이터에서 D00·D10·D20·D40을 평가 대상으로 지정했습니다. 현재 검사에서 D01·D11·D43·D44·D50은 이전 RDD 분류에 있는 코드로 집계했습니다. `D0w0` 한 건은 알 수 없는 클래스로 기록했습니다. [CRDDC 2022 데이터 안내](https://crddc2022.sekilab.global/data/) · [이전 RDD 분류 자료](https://www.mlit.go.jp/road/ir/ir-council/road_maintenance/pdf/05iji2.pdf)

| 클래스 | Japan 객체 / 등장 이미지 | India 객체 / 등장 이미지 |
| --- | ---: | ---: |
| D01 | 0 / 0 | 179 / 118 |
| D11 | 0 / 0 | 45 / 36 |
| D43 | 736 / 696 | 57 / 57 |
| D44 | 3,995 / 3,210 | 1,062 / 869 |
| D50 | 3,553 / 2,610 | 28 / 28 |
| `D0w0` | 0 / 0 | 1 / 1 |

대상 4종이 없고 기타 클래스만 기록된 이미지가 Japan 1,812장, India 562장입니다. India 수치에는 `D0w0` 한 장이 포함됩니다. 대상 외 객체만 있는 이미지를 배경으로 사용해도 되는지는 클래스 정의와 시각 검증을 바탕으로 결정합니다.

## 활용 적합성과 잠정 추천

- **Japan을 D10·D40 동시 보강 후보로 우선 검토합니다.** Train D10 3,979개가 2,240장에, D40 2,243개가 1,390장에 분포합니다. 기존 Czech의 D00 집중은 대상 객체 중 56.6%이고, Japan의 최다 클래스는 D20으로 37.6%입니다. Japan을 검토할 때 D20의 많은 물량과 기타 클래스만 포함된 이미지도 함께 고려해야 합니다.
- **India는 D40 중심 보강 후보입니다.** D40 3,187개가 1,530장에 있고 대상 객체의 46.7%를 차지합니다. India Train의 D10은 68개로 Czech v2 Train의 321개보다 적습니다. 동일한 조건에서 D10과 D40을 함께 보강하려면 Japan에 더 많은 후보가 있습니다.
- 공개 논문에 따르면 세 국가는 차량에 장착한 스마트폰으로 촬영했습니다. Japan의 여러 지자체와 India의 지방도로·주 고속도로·국도는 Czech에 더해 노면, 차선, 주변 배경, 조명 사례를 넓힐 가능성이 있습니다. 실제 블랙박스 실험에서는 낮은 태양, 앞유리 반사와 큰 차내 영역이 관찰됐습니다. 후보의 촬영 조건과 실제 블랙박스 영상의 일치 정도는 Part 5.2-2에서 확인하며, 성능 개선 여부는 정답 라벨이 있는 실제 주행 영상으로 평가해야 합니다. [RDD2022 데이터 논문](https://doi.org/10.1002/gdj3.260) · [Part 5.1 해상도·Crop 진단](part5_resolution_crop_diagnostic.md)

## Part 5.2-2 샘플과 확인 사항

ZIP 내부 경로를 정렬한 뒤 국가별로 seed `42`를 사용했습니다. 각 나라에서 유효 XML의 D00·D10·D20·D40 이미지 각 10장과 객체 없는 이미지 5장, 오류 의심 이미지 1장을 골랐습니다. 총 **92장**으로 Japan·India 각 46장이며, 클래스 추출 과정에서 같은 경로가 중복 선정된 경우는 0장입니다. CSV에는 선택 클래스와 객체 수, 전체 클래스별 객체 수, 오류 유형, 중복 여부를 기록했습니다. [샘플 후보 CSV](../../data/processed/rdd2022_japan_india_inspection/sample_candidates.csv)

1. D10·D40의 박스 정렬, 분류 일관성, 작은 파손과 화면 가장자리의 누락을 확인합니다. 너비 0인 Japan D20과 India `D0w0`는 원본 이미지를 보고 처리 방침을 정합니다.
2. 객체 없는 샘플에서 미라벨 파손을 찾아보고, 기타 클래스와 대상 4종이 비슷해 보이는 사례를 확인합니다. 특히 시공 이음부, 보수 흔적, 차선, 맨홀의 라벨 기준을 맞춥니다.
3. 박스 오버레이로 이미지 내용을 검토하고, 실제 블랙박스 프레임과 카메라 높이·각도, 노면 점유율, 파손의 픽셀 크기, 역광·반사를 비교합니다. Part 5.2-1의 JPEG 디코딩은 파일 판독과 픽셀 크기 검사에 사용했습니다.
4. 국가 내·국가 간 원본 이미지 중복과 유사 주행 장면을 확인합니다. 후속 사용 시 같은 영상·주행 구간이나 유사 프레임이 학습과 평가에 걸치지 않도록 자료를 정리합니다.

## 재현과 검증

프로젝트의 기존 Python `3.14.5`, OpenCV `5.0.0`, NumPy `2.5.4`를 사용했습니다. `zipfile`로 CRC와 ZIP 구조를 읽고 `ElementTree`로 XML을 파싱했습니다. 제한 셸에서 `.venv`가 참조하는 기본 Python에 접근할 수 없어 검사와 테스트는 해당 Python에 접근 가능한 실행으로 진행했습니다. 다시 검사할 때는 `--output-dir`에 새 경로를 지정합니다. [검사 스크립트](../../scripts/inspect_rdd2022_japan_india.py) · [테스트 코드](../../tests/test_rdd2022_japan_india.py)

```powershell
$rddArchiveFolder = 'C:\Projects\dashcam-road-anomaly 데이터&가이드라인'
.\.venv\Scripts\python.exe -B -X utf8 scripts\inspect_rdd2022_japan_india.py `
    --japan-zip (Join-Path $rddArchiveFolder 'Japan.zip') `
    --india-zip (Join-Path $rddArchiveFolder 'India.zip')
.\.venv\Scripts\python.exe -B -X utf8 -m unittest -v tests.test_rdd2022_japan_india
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -v
```

실제 ZIP 검사는 종료 코드 0으로 결과를 저장했습니다. 신규 테스트 **2개**, 전체 회귀 테스트 **48개**가 통과했습니다. 작업 범위는 읽기 전용 검사와 신규 보고서·샘플 목록 작성입니다.
