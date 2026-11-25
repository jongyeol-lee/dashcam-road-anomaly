# Part 5.3-3 — 실제 블랙박스 GT v1 모델·ROI B 비교

작업일 **2026-11-25 (KST)** · 시작 커밋 `f2bece7` · CUDA 추론 `part533_gt_v1` · 최종 비교 자료 `part533_gt_v1_review`

Confidence 0.05에서 Czech Baseline은 예측 0개였고, Czech + Japan 혼합 모델은 34개 중 D20 2개를 정탐했습니다. 혼합 모델에 ROI B를 적용하면 정상 배경 FP 4개가 모두 제거되고 `rear_000555`의 정탐이 미탐으로 바뀝니다. Confidence 0.25에서도 ROI B가 이 프레임의 유일한 정탐을 제거했습니다. [평가 요약](../../outputs/dashcam_evaluation/part533_gt_v1_review/summary.json) · [후방 18.5초 비교](../../outputs/dashcam_evaluation/part533_gt_v1_review/comparisons/conf_0.05/rear_000555.jpg)

## 평가 대상과 사전 확정 조건

발행 매니페스트 순서대로 원본 PNG 11장을 두 모델에 각각 한 번씩 입력했습니다. 승인 매니페스트의 `positive` 5장에 D20 GT 각 1개, `normal_background` 3장, `uncertain_regions_only` 3장이 있습니다. 나머지 3장은 전체 제외입니다. 보류 영역 8개는 이미지 ID와 revision으로 연결했습니다. `rear_000120` v0002 #2의 저장 클래스 D40은 보류 영역의 출처입니다. 확정 GT는 다섯 D20 박스입니다. [발행 및 승인 기록](part5_dashcam_manual_box_drafts.md#평가용-gt-v1-발행)

| 입력 | 검증한 SHA-256 |
| --- | --- |
| 평가 GT `release_manifest.json` | `2b9ac000c986d1c93aa5d2267e757fdf1264b32b4f4ae1dab23dbf56d849f789` |
| 평가 GT `uncertain_regions.json` | `5767e737f881b039ee1eadd632f37296f0c9b1bd12aa7bc6b7cd14cdf9b7b78b` |
| Czech Baseline `best.pt` | `40f0b6af12b8a33d83119138251ae345ee2ac50df5a3ae0ec81137d781b63342` |
| Czech + Japan `best.pt` | `3d770f1515ef2baf2fbe25d4c9ba241d289254b2002894d7cc02ff56009b2afb` |

기존 `--verify`로 발행본을 재검증했습니다. 실행 시 두 JSON과 11장 PNG의 SHA-256, 1920×1080 디코딩, 승인 범위와 D20 좌표를 확인했습니다. 두 로컬 체크포인트는 기존 학습 기록의 해시와 일치했고, 둘 다 `0=D00`, `1=D10`, `2=D20`, `3=D40`인 YOLO11n 탐지 모델로 로드됐습니다. [발행 검증기](../../scripts/publish_dashcam_gt.py) · [Baseline 학습](yolo11n_baseline.md) · [혼합 모델 학습](part5_multicountry_model_training.md) · [이미지별 경로 및 해시](../../outputs/dashcam_evaluation/part533_gt_v1_review/inputs.json)

추론은 CUDA 0, 배치 1, FP32 입출력 설정으로 실행했습니다. 입력은 1920×1080 전체 프레임에 640×640 letterbox를 적용했고 `rect=False`, NMS IoU 0.7, confidence 0.05, `max_det=300`, 클래스별 NMS를 사용했습니다. 증강·클래스 필터·타일링은 껐습니다. A와 B는 Czech Baseline, C와 D는 Czech + Japan이며 B와 D에만 ROI B를 적용합니다. 두 confidence 조건 `>= 0.05`, `>= 0.25`는 모델마다 저장한 같은 NMS 결과에서 필터링했습니다. [실제 모델별 옵션과 시간](../../outputs/dashcam_evaluation/part533_gt_v1_review/summary.json)

GT와 예측은 동일 클래스, IoU 0.50 이상에서 IoU, confidence, GT·예측 ID 순으로 일대일 매칭했습니다. 그 뒤 미매칭 예측의 보류 영역 교차 면적을 영역 합집합 기준으로 계산했습니다. 예측 면적의 50% 이상이면 보류, 그 미만이면 승인된 정상 배경에서만 확정 FP로 판정하고 나머지는 추가 검토로 남겼습니다. 다른 클래스의 IoU 0.50 이상 겹침은 혼동 진단에 기록합니다. ROI B는 중심이 정규화 좌표 `((0, 0), (1, 0), (1, 0.60), (0, 0.60))` 안이나 경계에 있는 박스를 통과시킵니다. 1080px 프레임에서는 `y ≤ 648`입니다. GT 좌표와 분모 5개는 전 조건에 공통입니다. [평가 로직](../../src/road_anomaly/dashcam_evaluation.py) · [기존 ROI 판정](../../src/road_anomaly/roi.py)

## 두 모델과 confidence 비교

각 조건의 평가 범위는 11장, D20 GT 5개, 정상 배경 3장입니다. FP 이미지 수와 이미지당 FP는 승인 정상 배경 3장을 기준으로 계산했습니다.

| 조건 | Confidence | 예측 | D00 / D10 / D20 / D40 | D20 TP / FN | D20 Recall | 배경 FP | FP 이미지 | 배경 장당 FP | 보류 | 추가 검토 | 클래스 혼동 |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A | 0.05 | 0 | 0 / 0 / 0 / 0 | 0 / 5 | 0% | 0 | 0 | 0 | 0 | 0 | 0 |
| B | 0.05 | 0 | 0 / 0 / 0 / 0 | 0 / 5 | 0% | 0 | 0 | 0 | 0 | 0 | 0 |
| C | 0.05 | 34 | 20 / 0 / 13 / 1 | 2 / 3 | 40% | 4 | 2 | 1.33 | 0 | 28 | 0 |
| D | 0.05 | 8 | 0 / 0 / 7 / 1 | 1 / 4 | 20% | 0 | 0 | 0 | 0 | 7 | 0 |
| A | 0.25 | 0 | 0 / 0 / 0 / 0 | 0 / 5 | 0% | 0 | 0 | 0 | 0 | 0 | 0 |
| B | 0.25 | 0 | 0 / 0 / 0 / 0 | 0 / 5 | 0% | 0 | 0 | 0 | 0 | 0 | 0 |
| C | 0.25 | 1 | 0 / 0 / 1 / 0 | 1 / 4 | 20% | 0 | 0 | 0 | 0 | 0 | 0 |
| D | 0.25 | 0 | 0 / 0 / 0 / 0 | 0 / 5 | 0% | 0 | 0 | 0 | 0 | 0 | 0 |

확정 GT가 0개인 D40의 Recall은 JSON에서 `null`, CSV에서 `N/A`입니다. 이 표의 성능 지표는 확정 D20 프레임 Recall과 승인 배경 FP입니다. 파손·부분 보류 프레임의 라벨 완전성과 클래스별 표본 규모는 전체 Precision, F1, mAP를 산출할 근거가 부족합니다. [비교 CSV](../../outputs/dashcam_evaluation/part533_gt_v1_review/comparison.csv)

## 확정 GT별 결과

정탐 셀의 괄호는 `IoU / confidence`입니다. GT 좌표는 오른쪽·아래 끝 미포함 원본 픽셀입니다.

| 이미지 / 시각 | D20 GT xyxy | A·B 두 기준 | C 0.05 | D 0.05 | C 0.25 | D 0.25 |
| --- | --- | --- | --- | --- | --- | --- |
| [rear_000525 · 17.5초](../../outputs/dashcam_evaluation/part533_gt_v1_review/comparisons/conf_0.05/rear_000525.jpg) | (455,565,1032,760) | FN | TP (0.7149 / 0.0629) | TP (0.7149 / 0.0629) | FN | FN |
| [rear_000540 · 18.0초](../../outputs/dashcam_evaluation/part533_gt_v1_review/comparisons/conf_0.05/rear_000540.jpg) | (556,520,959,788) | FN | FN | FN | FN | FN |
| [rear_000555 · 18.5초](../../outputs/dashcam_evaluation/part533_gt_v1_review/comparisons/conf_0.05/rear_000555.jpg) | (386,602,1131,786) | FN | TP (0.6383 / 0.0804) | FN | TP (0.5411 / 0.3743) | FN |
| [front_000510 · 17.0초](../../outputs/dashcam_evaluation/part533_gt_v1_review/comparisons/conf_0.05/front_000510.jpg) | (788,700,1505,882) | FN | FN | FN | FN | FN |
| [rear_000120 · 4.0초](../../outputs/dashcam_evaluation/part533_gt_v1_review/comparisons/conf_0.05/rear_000120.jpg) | (264,552,430,705) | FN | FN | FN | FN | FN |

`rear_000525`의 GT 중심은 y=662.5이고, 정탐 예측 `p006`의 중심은 y=646.09입니다. 이 예측은 ROI B를 통과합니다. `rear_000555`는 0.05에서 IoU가 더 높은 `p003`이 매칭됐고, 0.25에서는 score 0.3743의 `p001`이 매칭됐습니다. 두 중심은 각각 y=681.80과 y=680.22입니다. 두 confidence 조건 모두 ROI 적용 후 이 프레임에 재매칭할 예측이 남지 않았습니다. [GT별 매칭과 최선 동일 클래스 후보](../../outputs/dashcam_evaluation/part533_gt_v1_review/gt_matches.json) · [후방 18.5초 confidence 0.25](../../outputs/dashcam_evaluation/part533_gt_v1_review/comparisons/conf_0.25/rear_000555.jpg)

## ROI 효과와 주요 오차 사례

| 모델 / Confidence | 전체 → 통과 | 제거 | 제거된 TP 예측 | TP→FN GT | 다른 박스 재매칭 | 제거된 배경 FP | 제거된 보류 / 추가 검토 | 경계 접촉·교차 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| Baseline / 0.05 | 0 → 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 0 |
| 혼합 / 0.05 | 34 → 8 | 26 | 1 | 1 | 0 | 4 | 0 / 21 | 14 |
| Baseline / 0.25 | 0 → 0 | 0 | 0 | 0 | 0 | 0 | 0 / 0 | 0 |
| 혼합 / 0.25 | 1 → 0 | 1 | 1 | 1 | 0 | 0 | 0 / 0 | 1 |

경계 접촉·교차는 ROI 적용 전 예측을 기준으로 셌습니다. 혼합 모델 0.05의 경계 박스 14개 중 8개는 중심이 경계 안이고 6개는 밖입니다. 확정 GT 중심은 5개 중 4개가 경계 밖에 있지만, ROI 적용에 따른 미탐 증가는 실제 예측을 다시 매칭했을 때의 1개입니다. [제거된 예측 및 GT ID](../../outputs/dashcam_evaluation/part533_gt_v1_review/summary.json) · [예측별 ROI 판정](../../outputs/dashcam_evaluation/part533_gt_v1_review/prediction_diagnostics.json)

| 정상 배경 | 혼합 모델 D00 FP confidence | 중심 y | ROI B |
| --- | --- | --- | --- |
| [front_000210 · 7.0초](../../outputs/dashcam_evaluation/part533_gt_v1_review/comparisons/conf_0.05/front_000210.jpg) | 0.0759 / 0.0678 | 824.87 / 812.89 | 2개 제거 |
| [front_000690 · 23.0초](../../outputs/dashcam_evaluation/part533_gt_v1_review/comparisons/conf_0.05/front_000690.jpg) | 0.1460 / 0.0656 | 825.16 / 806.19 | 2개 제거 |
| [rear_000690 · 23.0초](../../outputs/dashcam_evaluation/part533_gt_v1_review/comparisons/conf_0.05/rear_000690.jpg) | 예측 0개 | — | 0개 제거 |

두 전방 정상 배경에서 D00 박스는 화면 하단의 비슷한 위치에 모였습니다. 해당 위치와 주변에는 전방 유리에 반사된 것으로 보이는 무늬가 있어, 다른 시각의 프레임에서도 같은 카메라 좌표에서 탐지가 반복되는지 확인할 가치가 있습니다. 네 박스는 모두 confidence 0.25 미만입니다.

- `rear_000540`은 혼합 모델이 D20을 3개 예측했으나 최고 IoU가 0.4041(0.0777)이어서 미탐입니다. 같은 후방 구간에서 `rear_000525`, `rear_000555`는 정탐했으므로 연속 프레임에서도 박스 범위가 달라졌습니다. [후방 18.0초 비교](../../outputs/dashcam_evaluation/part533_gt_v1_review/comparisons/conf_0.05/rear_000540.jpg)
- `front_000510`의 혼합 모델 D00 13개는 추가 검토입니다. D20 GT와의 최대 IoU는 0.1866이어서 IoU 0.50 기준의 클래스 혼동은 0건입니다. `front_000345`의 D00 3개도 부분 보류 프레임에서 추가 검토로 남겼습니다. [전방 17.0초 비교](../../outputs/dashcam_evaluation/part533_gt_v1_review/comparisons/conf_0.05/front_000510.jpg) · [전방 11.5초 비교](../../outputs/dashcam_evaluation/part533_gt_v1_review/comparisons/conf_0.05/front_000345.jpg)
- 보류 영역 포함 비율이 50% 이상인 예측은 전 조건에서 0개입니다. `rear_000120`의 D40 1개(confidence 0.0552)는 보류 합집합과 예측 면적의 24.2%가 겹쳐 추가 검토로 분류됐습니다. 중심 y=643.26이므로 ROI B에서도 남습니다. [후방 4.0초 비교](../../outputs/dashcam_evaluation/part533_gt_v1_review/comparisons/conf_0.05/rear_000120.jpg) · [보류·추가 검토 목록](../../outputs/dashcam_evaluation/part533_gt_v1_review/review_predictions.json)

## 전방·후방 비교

전방 4장에는 D20 GT 1개와 정상 배경 2장, 후방 7장에는 D20 GT 4개와 정상 배경 1장이 있습니다. Baseline은 전·후방 모두 두 confidence 기준에서 예측 0개와 정탐 0개였습니다. 혼합 모델의 조건별 결과는 다음과 같습니다. [카메라별 집계](../../outputs/dashcam_evaluation/part533_gt_v1_review/summary.json)

| 조건 / Confidence | 전방 예측 | 전방 D20 TP / GT | 전방 배경 FP | 후방 예측 | 후방 D20 TP / GT | 후방 배경 FP |
| --- | ---: | --- | ---: | ---: | --- | ---: |
| C / 0.05 | 20 | 0 / 1 | 4 | 14 | 2 / 4 | 0 |
| D / 0.05 | 0 | 0 / 1 | 0 | 8 | 1 / 4 | 0 |
| C / 0.25 | 0 | 0 / 1 | 0 | 1 | 1 / 4 | 0 |
| D / 0.25 | 0 | 0 / 1 | 0 | 0 | 0 / 4 | 0 |

후방 525·540·555 프레임은 `rear_17_19` 유사 프레임 그룹의 연속 관찰입니다. 전방과 후방에서 같은 파손을 관찰했을 가능성도 남아 있습니다. 이 결과의 집계 단위는 프레임이며, 독립 파손 사례 수와 사례 단위 성능은 미확정입니다. [후보 추출과 주행 그룹](part5_dashcam_ground_truth_preparation.md#세-의심-구간과-배경-검토-후보)

## 실행 환경과 시간

Windows 11 `10.0.26300`, 프로젝트 `.venv` Python 3.14.5, PyTorch 2.14.1+cu130, torchvision 0.29.1+cu130, Ultralytics 8.4.215, OpenCV 5.0.0을 사용했습니다. RTX 3060 Ti 8 GiB의 CUDA 0에서 텐서 계산을 확인했습니다. NVIDIA 드라이버 581.15의 지원 CUDA와 PyTorch 빌드 CUDA는 모두 13.0입니다. 두 모델의 입력 텐서와 백엔드 가중치는 FP32였고 CUDA matmul의 TF32는 꺼졌으며 cuDNN TF32는 허용됐습니다. [환경과 설정 기록](../../outputs/dashcam_evaluation/part533_gt_v1_review/inputs.json) · [환경 버전 관리](../ENVIRONMENT.md)

| 모델 | 체크포인트 로드·해시 | CUDA 백엔드 준비 | 합성 텐서 워밍업 | 전처리 평균 | 추론 평균 / 11장 합계 | NMS·좌표 복원 평균 | 11장 추론 호출 벽시계 |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| Baseline | 117.56 ms | 71.75 ms | 1,651.00 ms | 1.71 ms | 13.07 / 143.75 ms | 0.58 ms | 172.39 ms |
| 혼합 | 58.78 ms | 66.50 ms | 14.33 ms | 1.61 ms | 11.29 / 124.19 ms | 2.15 ms | 168.87 ms |

평균의 분모는 모델마다 11장입니다. Ultralytics 프로파일링은 전처리, 모델 forward, NMS·원본 좌표 복원 구간을 CUDA 동기화해 측정합니다. 벽시계는 디코딩한 PNG 배열에서 예측 호출이 반환될 때까지이며, 체크포인트 로드, 워밍업, 박스 내보내기와 그림 저장 시간은 별도입니다. Baseline이 프로세스 내 첫 모델이었으므로 워밍업과 평균 시간 표는 이 실행의 관측값으로 해석합니다. [Baseline 프레임별 시간](../../outputs/dashcam_evaluation/part533_gt_v1_review/raw_baseline_predictions.json) · [혼합 모델 프레임별 시간](../../outputs/dashcam_evaluation/part533_gt_v1_review/raw_mixed_predictions.json)

CPU에서 11장에 대해 ROI 중심·경계 판정과 박스 선택을 수행한 시간은 B에서 0.0067 / 0.0060 ms, D에서 0.4054 / 0.0311 ms였습니다(각각 confidence 0.05 / 0.25). 최종 비교 자료를 생성할 때 저장 예측에서 측정한 값이며 점수 필터, GT 매칭, 파일 입출력 시간은 별도입니다. [ROI 처리 시간 비교](../../outputs/dashcam_evaluation/part533_gt_v1_review/comparison.csv)

## 재현과 보존 검사

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts\publish_dashcam_gt.py --verify
.\.venv\Scripts\python.exe -B -X utf8 scripts\evaluate_dashcam_gt.py --run-name part533_gt_v1
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests
```

제한 셸에서 `.venv`가 참조하는 사용자 영역 Python 실행 경로 접근이 거부됐습니다. 위 세 명령은 해당 Python에 접근할 수 있는 실행 권한으로 완료했습니다. 재현할 때는 새 실행 이름을 지정합니다. 첫 실행 이후 겹친 박스의 confidence 라벨 가림을 발견해, 저장 예측 두 파일을 SHA-256으로 대조한 뒤 `write_evaluation()`으로 `part533_gt_v1_review`에 번호와 점수 범례를 다시 생성했습니다. 최종 자료에서 재추론 호출은 0회였으며 두 원본 예측 JSON의 바이트가 첫 실행과 일치합니다.

신규 테스트 20개를 포함한 전체 회귀 테스트 122개가 통과했습니다. 별도 결과 검사에서 원본 예측과 매니페스트로 8개 조건의 집계, GT 판정 40개, ROI 효과 4개를 다시 계산했고 저장값과 일치했습니다. JPEG는 2개 confidence 조건마다 11장씩 모두 디코딩했습니다. 원본 영상·추출 프레임·사용자 초안·승인 기록·발행본·두 모델·기존 실험 산출물 등 1,152개 파일의 전후 경로와 SHA-256이 일치했습니다. 공개 Test는 이번 검사와 평가 범위에서 제외했습니다. [테스트](../../tests/test_dashcam_evaluation.py) · [보존 검사 목록과 해시](../../outputs/dashcam_evaluation/part533_gt_v1_review/preservation.json)

| 로컬 산출물 | 포함 정보 |
| --- | --- |
| [Baseline 원본 예측](../../outputs/dashcam_evaluation/part533_gt_v1_review/raw_baseline_predictions.json) · [혼합 모델 원본 예측](../../outputs/dashcam_evaluation/part533_gt_v1_review/raw_mixed_predictions.json) | 모델별 11개 행, 박스 없는 이미지 포함, 원본 xyxy·score·예측 ID·프레임별 시간 |
| [평가 요약](../../outputs/dashcam_evaluation/part533_gt_v1_review/summary.json) · [비교 CSV](../../outputs/dashcam_evaluation/part533_gt_v1_review/comparison.csv) | 8개 조건의 비교, 카메라별 결과, ROI 제거·유지·GT 변화 및 시간 |
| [GT 매칭](../../outputs/dashcam_evaluation/part533_gt_v1_review/gt_matches.json) · [예측별 판정](../../outputs/dashcam_evaluation/part533_gt_v1_review/prediction_diagnostics.json) · [검토 목록](../../outputs/dashcam_evaluation/part533_gt_v1_review/review_predictions.json) | GT별 TP·FN, 예측별 ROI 위치, 중복 없이 분류한 보류 및 추가 검토 ID |
| [0.05 비교 이미지](../../outputs/dashcam_evaluation/part533_gt_v1_review/comparisons/conf_0.05) · [0.25 비교 이미지](../../outputs/dashcam_evaluation/part533_gt_v1_review/comparisons/conf_0.25) | 이미지당 원본, GT·보류, A~D 패널, y=648 경계와 판정·점수 범례 |

비교 영상의 출처는 Jihad Dib, Konstantinos Sirlantzis, Gareth Howells의 *An Annotated Water-Filled, and Dry Potholes Dataset for Deep Learning Applications* v1(CC BY 4.0)입니다. 위 JPEG는 원본 영상에서 추출한 프레임에 평가 박스와 ROI를 표시한 자료입니다. [영상 출처와 이용 조건](part5_dashcam_ground_truth_preparation.md#영상-출처와-이용-조건)

## 서비스 적용 판단에 필요한 다음 검증

혼합 모델의 전체 프레임 추론(C)을 다음 블랙박스 검증의 비교 후보로 둘 근거는 D20 정탐 2개입니다. 0.25에서는 정상 배경 FP가 0개이고 정탐이 1개로 줄어듭니다. ROI B는 전방 오탐을 줄였지만, 두 confidence 모두 후방 정탐을 제거했습니다. 고정 경계를 기본 필터로 적용하려면 카메라·주행 조건별로 노면 하단의 파손이 얼마나 손실되는지 더 확인해야 합니다. 이번 실험 범위에서 서비스 채택은 사용자 검토 대기입니다.

다음 진단은 주행과 카메라를 늘려 독립 주행별 D20, 확정 D40, 정상 배경을 확보하는 단계입니다. 전방의 유리 반사·차선·포장 보수와 후방의 노면 높이 분포를 함께 라벨링하면, 동일한 score 기준에서 전체 프레임과 카메라별 ROI를 비교할 수 있습니다. 전방 510번처럼 D00만 조밀하게 나오는 장면과 후방 540번처럼 D20 박스 범위가 부족한 장면은 따로 검토하고, 전체 MP4를 분석할 때는 시간 통합 전후의 실제 사례와 총소요 시간을 측정합니다. [실험 의사결정과 사용자 검토 상태](../ai_collaboration/05_dashcam_model_roi_evaluation.md)
