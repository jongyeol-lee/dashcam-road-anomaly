# Part 5.2-3 — Czech + Japan Pilot 데이터셋 구축

확인일 **2026-11-23 (KST)** · 기준 브랜치 `main`, 커밋 `dc0e49b`

## 데이터 선정과 원본 검사

Japan을 첫 비교 대상으로 선정했습니다. Part 5.2-1에서 Japan 원본 Train의 D10은 3,979개, D40은 2,243개로 집계됐습니다. Czech v2 Train의 D10 321개와 D40 158개를 함께 보강할 수 있는 분포입니다. Part 5.2-2에서 Japan 46장의 미리보기를 만들었고, 원본 크기로 본 일부 샘플에서 박스가 파손 의심 영역을 감싸는 것을 확인했습니다. 사용자도 검토한 샘플의 박스가 대체로 잘 맞는다는 의견을 남겼습니다. [데이터 검사](part5_multicountry_data_inspection.md) · [시각 검토](part5_multicountry_visual_review.md)

입력은 Czech v2의 2,829개 이미지·라벨 쌍과 기존 분할 매니페스트, Japan 원본 `Japan.zip`, Part 5.2-2 시각 검토 매니페스트입니다. Japan JPG와 XML은 ZIP에서 직접 읽어 파일명, 디코딩 크기, 클래스명, 박스 좌표를 검사했습니다. 공식 Test 2,627장은 정답 XML이 0개여서 평가 분할에 넣지 않았습니다. [Czech v2 설정](../../data/yolo/rdd2022_czech_v2/data.yaml) · [Czech v2 분할](../../data/processed/rdd2022_czech_v2/split_manifest.csv)

| Japan 원본 Train 검사 | 이미지 수 | 처리 |
| --- | ---: | --- |
| JPG·XML 매칭 | 10,506 | JPG 전체 디코딩 성공 |
| 유효 JPG·XML | 10,505 | 대상 객체 D00 4,048개, D10 3,979개, D20 6,196개, D40 2,243개 |
| 좌표 오류 | 1 | `Japan_001265.xml`의 4번째 D20 박스 `(198, 474, 198, 475)`의 너비가 0이어서 이미지 전체를 격리 |
| 기존 시각 검토의 오류·누락 의심 | 6 | 자동 검사를 통과한 `000712`, `004921`, `004978`, `008266`, `009522`, `010284`를 추가 격리 |
| 기타 클래스만 포함 | 1,812 | 배경과 구분해 분할에서 제외 |
| **분할 적격 / 제외** | **8,687 / 1,819** | 유효 XML 중 객체가 없는 794장에서 누락 의심 4장을 격리해 배경 후보 790장 확보 |

`001265`는 기존 시각 검토에도 오류 의심으로 기록돼 제외 보고서에 사유 두 개가 남습니다. 대상과 기타 클래스가 같은 이미지에 있는 경우 대상 박스만 변환했습니다. Japan Pilot에서 해당하는 기타 객체는 D43 60개, D44 658개, D50 721개입니다. [제외 보고서](../../data/processed/rdd2022_czech_japan_pilot_v1/exclusion_report.csv)

## 중복과 유사 장면

Japan Train 10,506장과 Czech v2 2,829장을 해싱했습니다. JPG 바이트 SHA-256, 디코딩된 원본 픽셀과 크기의 SHA-256, 수평·수직 128비트 dHash를 사용했습니다. dHash를 아홉 구간으로 나눠 구간이 하나라도 같거나 SHA-256이 같은 4,232,243쌍의 해밍 거리를 확인했습니다. 거리 8 이하인 쌍은 아홉 구간 중 적어도 하나가 같으며, 별도의 NumPy 청크 비교로 후보 67쌍이 모두 일치함을 확인했습니다.

| 비교 범위 | JPG SHA-256 일치 | 픽셀 SHA-256 일치 | dHash 거리 ≤ 8 | 파일 번호 근접 검사 후보 |
| --- | ---: | ---: | ---: | ---: |
| Japan Train 내부 | 0 | 0 | 67 | 0 |
| Japan Train ↔ Czech Train | 0 | 0 | 0 | — |
| Japan Train ↔ Czech Val | 0 | 0 | 0 | — |
| Japan Train ↔ Czech Test | 0 | 0 | 0 | — |

Japan 파일 번호 차이가 1~3인 25,218쌍에는 dHash 거리 ≤ 24와 32×32 BGR 썸네일의 채널 평균 절대 차이 ≤ 18을 함께 적용했습니다. 이 조건에 해당하는 쌍은 없었습니다. dHash 후보는 56개 연결 그룹에 117장이었고, 최대 그룹은 4장이었습니다. 시각 비교에서 `001658`과 `002156`은 횡단보도와 신호등, 주변 건물 배치가 유사했습니다. dHash 거리는 3, 파일 번호 차이는 498입니다. 파일 번호로 촬영 순서를 추정하기 어렵고, 이 비교로 동일 파손이나 같은 주행을 확정할 수 없습니다. [유사 장면 비교](../../data/processed/rdd2022_czech_japan_pilot_v1/duplicate_previews/japan_dhash.png) · [후보 쌍과 그룹](../../data/processed/rdd2022_czech_japan_pilot_v1/duplicate_groups.csv)

유사 후보를 연결한 그룹을 분할 단위로 사용했습니다. Czech 어느 분할에든 연결된 Japan 그룹 전체를 격리하도록 했으며, 이번 검사에서 해당하는 그룹은 0개였습니다. Japan의 배정된 그룹 중 Train·Val·Test를 가로지르는 그룹도 0개였습니다. ZIP의 Train XML에는 영상·주행 구간 ID가 없습니다. dHash와 썸네일 기준을 벗어나는 유사 배경이나 같은 주행 구간은 여러 분할에 남을 수 있습니다.

## 분할과 Pilot 선정

Seed `42`로 80%·10%·10%를 목표로 Japan 평가 분할을 먼저 확정했습니다. 기존 Czech 분할 함수에 유사 그룹, 이미지 수, 클래스별 등장 이미지 수와 객체 수, XML에 객체가 없는 이미지 수를 적용했습니다. 한 이미지에 여러 클래스가 있으면 해당 클래스에 모두 집계했습니다.

| Japan 분할 | 이미지 | 비율 | 그룹 | XML에 객체 없음 |
| --- | ---: | ---: | ---: | ---: |
| Train | 6,949 | 80.0% | 6,915 | 632 |
| Val | 869 | 10.0% | 864 | 79 |
| Test | 869 | 10.0% | 861 | 79 |

Japan Train에서만 유사 그룹당 최대 한 장을 골랐습니다. 클래스별 등장 이미지와 객체의 목표 수에 D00·D10·D20·D40 순으로 `1.0 / 1.25 / 1.0 / 1.50`을 곱했습니다. 배경 비율, 해상도, 파일 번호대, 썸네일 평균 밝기 구간도 함께 고려했습니다. Pilot은 Train의 네 해상도를 모두 포함하며 600×600 비율은 96.40%에서 96.38%로 비슷했습니다. 가장 큰 1,000번 단위 파일 번호대의 비중은 두 집합에서 약 7.87%였습니다. 실제 장소와 조명 조건은 확인하지 못했습니다.

Pilot은 상한인 **2,263장**을 확보했습니다. Japan 분할 Train의 32.57%, 원본 Train의 21.54%입니다. 같은 그룹에서 다른 이미지가 뽑힌 15장과 규모·분포 기준으로 뽑히지 않은 4,671장은 Japan Train 분할에만 기록했습니다. [선정 매니페스트](../../data/processed/rdd2022_czech_japan_pilot_v1/selection_manifest.csv) · [전체 분할과 파일 매핑](../../data/processed/rdd2022_czech_japan_pilot_v1/split_manifest.csv)

## 클래스별 분포

각 클래스 열은 **객체 수 / 등장 이미지 수**입니다. 빈 라벨 비율은 전체 이미지 중 대상 객체가 없는 이미지 비율이며, 발행한 Japan 데이터의 빈 라벨은 XML에 객체가 없는 경우에 해당합니다.

| 분할 | 이미지 | D00 | D10 | D20 | D40 | 빈 라벨 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Czech v2 Train | 2,263 | 791 / 610 | 321 / 238 | 128 / 103 | 158 / 122 | 1,410 (62.31%) |
| Japan 전체 분할 Train | 6,949 | 3,238 / 2,237 | 3,181 / 1,791 | 4,960 / 3,775 | 1,793 / 1,112 | 632 (9.09%) |
| Japan Pilot Train | 2,263 | 1,282 / 817 | 1,523 / 840 | 2,063 / 1,512 | 1,011 / 598 | 218 (9.63%) |
| **Czech + Japan Train** | **4,526** | **2,073 / 1,427** | **1,844 / 1,078** | **2,191 / 1,615** | **1,169 / 720** | **1,628 (35.97%)** |
| Czech Val | 283 | 98 / 77 | 39 / 31 | 17 / 13 | 20 / 16 | 174 (61.48%) |
| Czech Test | 283 | 99 / 77 | 39 / 31 | 16 / 13 | 19 / 16 | 173 (61.13%) |
| Japan Holdout Val | 869 | 404 / 280 | 399 / 224 | 620 / 471 | 224 / 139 | 79 (9.09%) |
| Japan Holdout Test | 869 | 406 / 279 | 398 / 224 | 615 / 466 | 226 / 139 | 79 (9.09%) |

## 산출물과 검증

| 데이터셋 | Train | Val | Test |
| --- | ---: | ---: | ---: |
| [Czech + Japan Pilot](../../data/yolo/rdd2022_czech_japan_pilot_v1/data.yaml) | Czech 2,263 + Japan 2,263 | Czech 283 | Czech 283 |
| [Japan Holdout](../../data/yolo/rdd2022_japan_holdout_v1/data.yaml) | — | Japan 869 | Japan 869 |

- JPG는 기존 `Czech_`·`Japan_` 파일명과 바이트를 그대로 복사했습니다. 두 데이터셋의 이미지와 라벨 **6,830쌍**을 파일 목록과 SHA-256으로 대조했습니다. Czech v2 **2,829쌍**의 원본·복사본 해시와 원래 분할이 모두 일치했습니다. Czech v2 YAML, 분할 CSV, 시각 검토 매니페스트, Japan ZIP도 작업 전후 해시가 일치했습니다. [검사 요약](../../data/processed/rdd2022_czech_japan_pilot_v1/inspection_summary.json)
- Japan **4,001개 라벨**, **9,171개 박스**의 클래스, 행 수와 역변환 좌표를 원본 XML과 비교했습니다. 디코딩한 실제 가로·세로 픽셀 크기로 정규화했고, 클래스 ID는 `0=D00, 1=D10, 2=D20, 3=D40`입니다. 좌표는 0~1, 박스 너비와 높이는 양수였으며, 최대 역변환 오차는 **7.61 × 10⁻⁸px 미만**이었습니다. `bbox_previews`의 Train 5장·Val 5장에서 원본 XML 박스와 변환 후 박스의 표시 픽셀이 일치했습니다. [Train D40 비교](../../data/processed/rdd2022_czech_japan_pilot_v1/bbox_previews/train_D40_Japan_000081.png) · [Val D20 비교](../../data/processed/rdd2022_czech_japan_pilot_v1/bbox_previews/val_D20_Japan_000012.png)
- Ultralytics `8.4.215`로 두 YAML의 클래스 매핑과 모든 분할 경로를 확인했습니다. `YOLODataset`에 임시 사본을 전달해 혼합 Train 4,526장·Czech Val 283장·Japan Val 869장과 클래스별 객체 수, 빈 라벨 수가 일치했습니다. Test는 경로, 파일 대응, 해시와 좌표를 검증했습니다. 학습과 Test 성능 평가는 이번 작업 범위 밖입니다.
- 구축 전 C: 여유 공간은 약 259 GiB였습니다. 발행 이미지·라벨 **529,004,731바이트**, 임시 검증 사본 **437,755,117바이트**와 여유분을 합쳐 **1,100,977,576바이트**를 확보한 뒤 생성했습니다. Ultralytics 라벨 캐시는 임시 사본에 생성됐습니다.

## Part 5.2-4 비교 조건

혼합 Train은 Czech v2 Train에 Japan 2,263장을 추가해 이미지 수가 100% 늘었습니다. 마지막 불완전 배치를 포함하는 `batch=4` 조건이면 Czech Baseline은 epoch당 **566 배치**, 혼합은 **1,132 배치**입니다. 같은 30 epochs에서는 각각 **16,980**과 **33,960** 배치입니다. 옵티마이저 갱신 횟수는 gradient accumulation과 warmup에 따라 별도로 집계합니다.

1. 동일한 YOLO11n 초기 가중치, `imgsz=640`, `batch=4`, `seed=42`, AMP, 증강 및 평가 옵션으로 비교합니다. 실제 옵티마이저, 학습률 일정, 완료 epoch, 처리한 배치 수와 갱신 횟수를 실험에 기록합니다. [Czech Baseline 설정](yolo11n_baseline.md)
2. 전체 혼합 데이터 비교와 별도로, Czech만 2,263장인 대조군과 Czech·Japan을 합해 2,263장인 실험군을 같은 업데이트 예산으로 비교합니다. 고정 이미지 수의 비교는 국가 구성 변화의 영향을 볼 수 있습니다. 전체 혼합 비교에는 이미지 수와 학습 노출량 증가도 반영됩니다.
3. 고정 Czech Val 283장에서 Baseline과 비교하고 Japan Val 869장에서 국가별 일반화 성능을 확인합니다. 두 Test의 매니페스트는 고정하고 설정 확정 뒤 최종 평가에 사용합니다. Japan 전체의 수동 라벨 검토는 남아 있으며, 혼합 이미지에서 생략한 기타 라벨과 빈 XML의 누락 가능성도 결과 해석에 고려합니다. 실제 블랙박스 성능은 정답을 확보한 주행 영상에서 별도로 확인합니다.

데이터셋은 Part 5.2-4에서 사용할 수 있습니다. 기존 학습 CLI는 Czech v2 경로와 수량을 검사하므로 혼합 데이터용 실행 경로는 Part 5.2-4에서 구성합니다. [기존 학습 CLI](../../scripts/train_yolo_baseline.py)

## 재현과 회귀 테스트

기존 Python, OpenCV, NumPy, Pillow, Ultralytics를 사용했습니다. 다른 폴더에서 같은 입력으로 다시 생성하려면 `--data-dir`에 새 경로를 지정합니다. 목표 출력 경로가 이미 있으면 스크립트가 중단됩니다. 디스크가 부족하면 분할·선정·중복·제외 기록을 남기고 YOLO 파일 생성을 중단합니다. [구축 스크립트](../../scripts/prepare_rdd2022_czech_japan.py) · [구축 및 분할 테스트](../../tests/test_rdd2022_czech_japan.py)

```powershell
$rddSource = 'C:\Projects\dashcam-road-anomaly 데이터&가이드라인'
.\.venv\Scripts\python.exe -B -X utf8 scripts\prepare_rdd2022_czech_japan.py --japan-zip (Join-Path $rddSource 'Japan.zip')
.\.venv\Scripts\python.exe -B -X utf8 -m unittest -v tests.test_rdd2022_czech_japan
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -v
```

실제 ZIP으로 구축 및 로딩을 완료했고, 신규 테스트 **5개**와 전체 회귀 테스트 **56개**가 통과했습니다. 새 임시 경로에 실제 데이터로 재구축했을 때 분할·선정·중복·제외 CSV 네 개가 바이트 단위로 일치했습니다. 이번 비교의 분할과 선정 목록은 다음 SHA-256으로 식별합니다.

```text
split_manifest.csv      cee2def5a99aa96493c6f50919109ef2378e94ac8d95236ceef854adf29dd077
selection_manifest.csv  bfa002a17ab8b6f40e80f1870c0679694dc7ddd44b9c3970421973033556c102
```
