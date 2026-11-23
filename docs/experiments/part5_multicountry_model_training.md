# Part 5.2-4 — Czech + Japan YOLO11n 학습과 국가별 Validation 비교

실험일 **2026-11-23 (KST)** · 실험 이름 `czech_japan_pilot_v1_yolo11n_640_b4_s42_e30`

혼합 모델의 mAP50–95는 Czech에서 **0.0640 → 0.1292**, Japan에서 **0.0106 → 0.1824**로 올랐습니다. 실제 블랙박스에서는 새 D40 탐지 5건 모두 운전대에 박스를 그렸습니다. 두 나라의 Validation에서는 개선을 확인했고, 이 영상에서 노면 파손을 찾아낸 사례는 없었습니다.

## 실험 설계

Japan의 D10·D40 학습 사례를 추가하면 Czech에서 약했던 두 클래스의 Recall과 AP가 올라가는지, Japan 도로와 실제 블랙박스 영상에서도 변화가 나타나는지 확인합니다. 기존 모델은 Czech v2 Baseline의 epoch 26 체크포인트입니다. 신규 모델과 Baseline은 SHA-256이 같은 공식 COCO 사전학습 `yolo11n.pt`에서 각각 시작했습니다. [Czech Baseline](yolo11n_baseline.md) · [데이터 선정과 분할](part5_multicountry_dataset_build.md)

| 용도 | Czech 이미지 | Japan 이미지 | 사용 방법 |
| --- | ---: | ---: | --- |
| Baseline Train | 2,263 | 0 | 기존 학습 기록과 가중치 사용 |
| 혼합 Train | 2,263 | 2,263 | 고정 매니페스트의 4,526장으로 학습 |
| Czech Val | 283 | 0 | 두 학습의 epoch별 검증·best 선정 기준, 두 모델 비교 |
| Japan Val | 0 | 869 | 학습 완료 후 두 모델 비교 |

두 나라의 Test는 최종 평가용으로 보관했습니다. 원본 매니페스트의 그룹과 분할을 확인하고 Train·Val의 이미지 및 라벨 해시를 대조했습니다. 학습용 임시 사본에는 혼합 Train과 Czech Val만, 국가별 평가 사본에는 해당 Val만 복사했습니다. 혼합 Train에 들어간 Japan 객체 수는 D00 1,282개, D10 1,523개, D20 2,063개, D40 1,011개입니다.

스테이징할 Train·Val 데이터는 366,805,505바이트였고 시작 시 디스크 여유 공간은 258.41 GiB였습니다. 같은 나라를 평가할 때는 두 모델이 하나의 Val 임시 사본을 공유합니다. [시작 시점 파일 해시와 장비 기록](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/preflight.json)

## 학습 조건

두 실험에서 YOLO11n, 입력 640, 배치 4, seed 42, CUDA 0, workers 2, AMP, deterministic, `cache=False`, 최대 30 epochs, patience 10, `optimizer=auto`, `cls_pw=0.0`을 사용했습니다. 장비는 RTX 3060 Ti 8 GiB, 환경은 Python 3.14.5, PyTorch 2.14.1+cu130, Ultralytics 8.4.215입니다. [환경 기록](../ENVIRONMENT.md) · [신규 실행 설정](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/args.yaml)

스모크 테스트는 Czech 65장과 Japan 48장으로 1 epoch를 완료했습니다. 29배치에서 옵티마이저 갱신 1회를 확인했습니다. Train box/cls/dfl loss는 3.09322 / 16.2258 / 2.61499였고, 36.07초가 걸렸습니다. CUDA 역전파, AMP, best·last 가중치 저장, 원본 해시 일치를 확인한 뒤 본 학습을 시작했습니다. [스모크 학습 기록](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/smoke/training_summary.json) · [실제 갱신 수](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/smoke/training_checks.json)

| 본 학습 | Czech Baseline | Czech + Japan |
| --- | ---: | ---: |
| 완료 epoch / best epoch | 30 / 26 | 30 / 29 |
| 배치/epoch × 완료 epoch | 566 × 30 = 16,980 | 1,132 × 30 = 33,960 |
| 실제 옵티마이저 갱신 | 기존 기록에 없음 | 2,555회 |
| 기본 샘플 노출 Czech / Japan | 67,890 / 0 | 67,890 / 67,890 |
| 학습 시간 (내부 최종 검증 포함) | 25분 22.77초 | 49분 0.69초 |
| CUDA 최대 할당 / 예약 | 673.88 / 896 MiB | 678.10 / 886 MiB |
| 마지막 Train box / cls / dfl loss | 1.70752 / 2.22462 / 1.52010 | 1.78352 / 2.00768 / 1.68441 |
| 마지막 Czech Val box / cls / dfl loss | 2.16534 / 2.55004 / 1.86442 | 2.00552 / 2.30249 / 1.77942 |
| best.pt 크기 | 5,504,986바이트 | 5,505,050바이트 |

두 실행 모두 설정한 30 epoch까지 진행했습니다. `auto`는 양쪽에서 **AdamW, 초기 학습률 0.00125, momentum 0.9**를 선택했습니다. 신규 실행에서 확인한 betas는 (0.9, 0.999)입니다. 두 로그 모두 weight decay 0인 weight 81개, 0.0005인 weight 88개, 0인 bias 87개로 파라미터 그룹을 구성했습니다. warmup 3 epochs와 선형 학습률 일정을 적용했고, 마지막 epoch의 세 그룹 학습률은 양쪽 모두 0.00005375였습니다. 신규 모델은 Czech Val의 mAP50-95를 기준으로 epoch 29에 best를 저장했습니다. [학습 요약](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/training_summary.json) · [갱신 수·best 해시](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/training_checks.json) · [epoch별 손실·학습률](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/results.csv) · [신규 best.pt](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/weights/best.pt)

## 평가 방법

두 모델을 동일한 코드로 국가별 Val 전체에서 평가합니다. 정량 평가는 `imgsz=640`, `batch=4`, `conf=0.001`, NMS IoU 0.7, `rect=False`, `max_det=300`입니다. Precision과 Recall은 Ultralytics가 평균 F1을 기준으로 고른 confidence에서 읽고, AP는 confidence를 변화시킨 정밀도–재현율 곡선으로 계산합니다. 전체 행의 AP 열은 네 클래스의 평균입니다.

오류 사례는 양쪽 모델 모두 `conf=0.25`에서 집계합니다. GT와의 IoU가 0.5 이상인 같은 클래스 박스를 일대일로 우선 매칭하고, 남은 위치 일치를 클래스 혼동으로 분류합니다. 모델 간 정탐 변화는 같은 GT 객체에 대해 계산합니다. 공통 오탐은 두 모델 각각에서 오탐인 박스가 같은 클래스이고 서로의 IoU도 0.5 이상인 경우입니다. XML에 없는 실제 파손은 이 기준에서 오탐으로 집계될 수 있습니다.

## Czech Validation 결과

283장에 정답 객체가 174개 있습니다. 각 칸은 **기존 → 혼합 (혼합 − 기존)** 순서입니다. 차이는 반올림 전 값으로 계산한 절대 점수 차이이며, 전체 행의 AP는 mAP입니다.

| 클래스 | 정답 객체 | Precision | Recall | AP50 | AP50–95 |
| --- | ---: | --- | --- | --- | --- |
| 전체 | 174 | 0.2893 → 0.2853 (-0.0040) | 0.2860 → 0.3512 (+0.0652) | 0.1756 → 0.3410 (+0.1654) | 0.0640 → 0.1292 (+0.0653) |
| D00 | 98 | 0.2378 → 0.3577 (+0.1199) | 0.4184 → 0.4490 (+0.0306) | 0.2565 → 0.3423 (+0.0858) | 0.0966 → 0.1395 (+0.0429) |
| D10 | 39 | 0.3700 → 0.2070 (-0.1630) | 0.0462 → 0.2051 (+0.1590) | 0.1455 → 0.2060 (+0.0605) | 0.0432 → 0.0653 (+0.0221) |
| D20 | 17 | 0.1225 → 0.2707 (+0.1482) | 0.5294 → 0.5294 (0.0000) | 0.0921 → 0.5169 (+0.4248) | 0.0295 → 0.2165 (+0.1870) |
| D40 | 20 | 0.4268 → 0.3058 (-0.1210) | 0.1500 → 0.2211 (+0.0711) | 0.2083 → 0.2989 (+0.0906) | 0.0867 → 0.0957 (+0.0090) |

기존 모델을 다시 평가한 결과는 저장된 전체·클래스별 지표와 일치했습니다. 혼합 모델에서 네 클래스 모두 AP50과 AP50–95가 올랐습니다. D10과 D40은 Recall이 각각 0.1590, 0.0711 올랐지만 Precision이 0.1630, 0.1210 낮아졌습니다. D00은 네 지표가 함께 올랐고, D20은 Recall이 같아도 AP50이 0.4248 올랐습니다. D20과 D40은 각각 17개와 20개 정답을 바탕으로 한 결과입니다. [네 조합의 비교 원본](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/validation/comparison.json)

## Japan Validation 결과

869장에 정답 객체가 1,647개 있습니다. 표의 단위와 순서는 Czech 표와 같습니다.

| 클래스 | 정답 객체 | Precision | Recall | AP50 | AP50–95 |
| --- | ---: | --- | --- | --- | --- |
| 전체 | 1,647 | 0.1057 → 0.4704 (+0.3647) | 0.1513 → 0.4190 (+0.2677) | 0.0397 → 0.4061 (+0.3664) | 0.0106 → 0.1824 (+0.1718) |
| D00 | 404 | 0.0309 → 0.4450 (+0.4140) | 0.3540 → 0.3493 (-0.0047) | 0.0344 → 0.3500 (+0.3156) | 0.0107 → 0.1485 (+0.1377) |
| D10 | 399 | 0.1716 → 0.3890 (+0.2174) | 0.0050 → 0.2882 (+0.2832) | 0.0491 → 0.2759 (+0.2269) | 0.0116 → 0.1046 (+0.0930) |
| D20 | 620 | 0.0752 → 0.5266 (+0.4514) | 0.2016 → 0.5919 (+0.3903) | 0.0440 → 0.5546 (+0.5106) | 0.0103 → 0.2732 (+0.2629) |
| D40 | 224 | 0.1450 → 0.5210 (+0.3760) | 0.0446 → 0.4464 (+0.4018) | 0.0313 → 0.4439 (+0.4126) | 0.0098 → 0.2034 (+0.1936) |

Japan에서는 D10과 D40 모두 Precision과 Recall이 함께 올랐습니다. D40 Recall은 0.0446에서 0.4464로 올랐고, D20은 혼합 모델의 AP50–95가 가장 높았습니다. D00은 두 AP와 Precision이 올랐지만 Recall은 0.3540에서 0.3493으로 소폭 낮아졌습니다. 혼합 학습에 Japan 이미지가 포함되어 있으므로 이 결과는 해당 국가의 분리된 Val 표본에 적용됩니다. [Japan 평가 표본·가중치 기록](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/validation/japan/mixed/provenance.json)

평가 호출 시간은 Czech에서 기존 10.43초·혼합 7.84초, Japan에서 기존 12.83초·혼합 12.43초였습니다. 네 평가와 스테이징, 오류 사례 생성 및 보존 검사에 66.43초가 걸렸습니다. 학습 설정 파일은 데이터와 실행 경로·이름을 제외한 인자가 모두 일치했습니다. [평가 및 설정 대조 결과](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/validation/comparison.json)

검증 시 Ultralytics가 기록한 순수 모델 추론 시간은 이미지당 Czech 3.29 → 3.79 ms, Japan 3.22 → 3.12 ms였습니다(RTX 3060 Ti, 입력 640, 배치 4). 아래 MP4 시간에는 프레임 추출·결과 저장도 포함됩니다.

## 같은 정답 객체에서 달라진 오류

아래 네 정탐·미탐 열을 더하면 해당 국가의 전체 정답 수가 됩니다. 마지막 열은 예측 박스 쌍을 세므로 정답 객체 수와 별개입니다. 정탐은 클래스 일치, confidence ≥ 0.25, GT IoU ≥ 0.5를 모두 충족해야 합니다.

| Val | 기존 미탐 → 혼합 정탐 | 기존 정탐 → 혼합 미탐 | 양쪽 정탐 | 양쪽 미탐 | 공통 오탐 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Czech | 23 | 1 | 9 | 141 | 5 |
| Japan | 537 | 17 | 65 | 1,028 | 27 |

- **회복한 객체**는 Czech에서 D10 4개, D00 14개, D20 5개였습니다. Japan에서는 D10 84개와 D40 87개를 새로 찾았습니다. Czech의 교량 아래 가로 방향 D10과 Japan의 D40 사례를 GT·기존·혼합 순서로 비교할 수 있습니다. [Czech D10](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/validation/czech/paired_cases/gained_tp_Czech_001611.png) · [Japan D40](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/validation/japan/paired_cases/gained_tp_Japan_000117.png)
- **놓치게 된 객체**는 Czech에서 D00 1개, Japan에서 D00 14개·D20 3개였습니다. Czech 사례에서는 기존 D00 박스가 있던 위치를 혼합 모델이 D20으로 분류했습니다. [Czech D00](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/validation/czech/paired_cases/lost_tp_Czech_001946.png) · [Japan D20](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/validation/japan/paired_cases/lost_tp_Japan_001546.png)
- **남은 미탐**에는 Czech D10 35개와 D40 20개, Japan D10 315개와 D40 137개가 포함됩니다. Czech D40은 AP가 올랐어도 고정 기준에서 양쪽 모두 20개 전체를 놓쳤습니다. [Czech D40](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/validation/czech/paired_cases/both_missed_Czech_000064.png) · [Japan D40](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/validation/japan/paired_cases/both_missed_Japan_000073.png)
- **D20·D40 혼동**은 Czech 기존 모델에서 GT D40을 D20으로 분류한 1건이었습니다. 같은 사진에 혼합 모델도 D20을 표시했지만 해당 D40과의 IoU가 매칭 기준에 미달했습니다. Czech 혼합 및 Japan 양쪽에서 기준을 충족한 D20↔D40 혼동은 0건이었습니다. Japan의 GT D20→D00 혼동은 16건에서 2건으로 줄었습니다. [Czech D40→D20](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/validation/czech/paired_cases/confusion_Czech_003570.png) · [Japan 오류 집계](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/validation/japan/paired_summary.json)
- **차선·노면 경계의 오탐**도 남았습니다. Czech 공통 오탐 5개 중 4개가 D00이었고, 점선 바로 옆의 길쭉한 노면 흔적에 두 모델이 박스를 그린 사례가 있었습니다. Japan에서는 정답이 없는 이미지에서 흰 차선 옆의 어두운 세로 흔적을 혼합 모델이 D00으로, 직사각형 포장 경계로 보이는 선을 D10으로 예측했습니다. 라벨에는 보수 공사 이력이 없어 이 흔적이 실제 보수 자국인지는 확인할 수 없습니다. [Czech 공통 D00](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/validation/czech/paired_cases/common_fp_Czech_000161.png) · [Japan 차선 옆 D00](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/validation/japan/paired_cases/background_fp_Japan_001745.png) · [Japan 포장 경계 D10](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/validation/japan/paired_cases/background_fp_Japan_009849.png)

클래스별 집계와 예시 이미지 목록, 이미지별 전체 판정을 함께 저장했습니다. [Czech 집계](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/validation/czech/paired_summary.json) · [Czech 객체별 판정](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/validation/czech/paired_events.json) · [Japan 집계](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/validation/japan/paired_summary.json) · [Japan 객체별 판정](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/validation/japan/paired_events.json)

## 실제 블랙박스 영상

기존 MP4 CLI로 `road_sample_04.mp4`를 두 번 분석했습니다. 원본은 1920×1080, 29.97 fps, 875프레임입니다. 두 실행 모두 0.5초 간격, 입력 640, confidence 0.05, NMS IoU 0.7, `rect=False`, `max_det=300`, 동일 클래스 통합 간격 1.5초, CUDA 0을 사용했습니다. 두 실행이 추출한 59개 JPEG의 SHA-256과 프레임 시각 CSV가 일치했습니다.

| 모델 | 분석 프레임 | 박스 | D00 / D10 / D20 / D40 | 통합 구간 | 영상 분석 시간 |
| --- | ---: | ---: | --- | ---: | ---: |
| Czech Baseline | 59 | 0 | 0 / 0 / 0 / 0 | 0 | 8.15초 |
| Czech + Japan | 59 | 5 | 0 / 0 / 0 / 5 | 3 | 8.20초 |

| 원본 기준 구간 | 박스 수 | 최고 confidence | 대표 프레임과 위치 |
| --- | ---: | ---: | --- |
| 1.5015–2.5025초 | 3 | 0.0872 | [프레임 45 · 운전대 중앙 하단](../../outputs/video_analysis/part524_road04_mixed/scenes/event_0001.jpg) |
| 18.0180초 | 1 | 0.0744 | [프레임 540 · 운전대 왼쪽 하단](../../outputs/video_analysis/part524_road04_mixed/scenes/event_0002.jpg) |
| 26.5265초 | 1 | 0.0507 | [프레임 795 · 운전대 왼쪽 하단](../../outputs/video_analysis/part524_road04_mixed/scenes/event_0003.jpg) |

다섯 박스를 각각 원본 프레임에서 대조했습니다. 모두 화면 하단 운전대의 엠블럼이나 왼쪽 부품을 가리켰습니다. 첫 구간은 처음 두 프레임의 엠블럼과 다음 프레임의 왼쪽 부품까지 하나로 묶였습니다. 이 영상에서 확인된 노면 파손 탐지는 0건입니다. 원본 영상에 정답 라벨이 없어 도로 파손의 미탐 수 및 영상 Recall은 산출할 수 없습니다. [기존 결과](../../outputs/video_analysis/part524_road04_baseline/summary.json) · [혼합 결과](../../outputs/video_analysis/part524_road04_mixed/summary.json) · [다섯 박스와 좌표](../../outputs/video_analysis/part524_road04_mixed/detections.csv) · [구간 통합 기록](../../outputs/video_analysis/part524_road04_mixed/events.json)

## 해석과 다음 실험

같은 Czech·Japan Validation에서 새 모델은 두 국가의 mAP와 D10·D40 Recall을 개선했습니다. 고정 confidence에서는 Czech D40 정탐이 여전히 없고, 실제 영상에서도 실내 부품만 검출했습니다. 혼합 모델을 다음 검증 후보로 남기되, 이 자료만으로 실사용 성능 향상이나 Japan 데이터만의 기여도를 확정하기는 어렵습니다. seed는 42 하나이고, 혼합 모델의 배치 수는 기존의 두 배입니다. 중복·유사 그룹으로 분할했지만 원본 주행 구간 식별자가 없어, 개별 주행 단위의 독립성도 추가 확인 대상입니다.

다음 단계에서는 아래 15 epoch 설계로 학습량의 영향을 점검하고, 다른 경로·조명의 블랙박스 영상에 노면 파손과 실내 배경을 표시해 확인합니다. 같은 영상 표본에서 노면 영역 제한 전후의 정탐·미탐과 실내 오탐을 비교하면 이번 영상에서 발견한 문제를 직접 검증할 수 있습니다. 두 Test는 최종 모델과 조건을 확정한 뒤 평가합니다.

## 학습량을 맞춘 보조 실험 설계

혼합 데이터 15 epochs와 Czech 30 epochs는 마지막 불완전 배치를 포함해 각각 16,980배치이며, 기본 샘플 기준 이미지 처리량도 67,890장으로 같습니다. 혼합 15 epochs에서는 Czech 33,945장과 Japan 33,945장에 해당하고, Czech 30 epochs에서는 Czech 67,890장에 해당합니다. Mosaic 등 증강에서 참조하는 추가 이미지는 이 수에 포함하지 않습니다.

보조 실험은 `scripts/train_yolo_czech_japan.py --name czech_japan_pilot_v1_yolo11n_640_b4_s42_e15 --epochs 15`로 별도 실행할 수 있습니다. 15 epoch 일정은 warmup 이후 학습률 감소 속도와 Mosaic 종료 시점이 30 epoch 일정과 달라집니다. 실제 옵티마이저와 갱신 횟수, 최종 학습률을 함께 확인해야 합니다. 이번 실행은 30 epoch 주 실험 한 건입니다.

## 재현

프로젝트 루트에서 실행합니다. 아래 예시는 기존 결과와 구분되는 이름을 사용합니다. 학습 CLI는 스모크 검증 후 공식 COCO 가중치를 다시 불러오고, 평가 CLI는 학습 때 기록한 원본 및 체크포인트 해시를 확인합니다.

```powershell
$runName = 'czech_japan_pilot_v1_yolo11n_640_b4_s42_e30_repeat'
.\.venv\Scripts\python.exe -B -X utf8 scripts\train_yolo_czech_japan.py --name $runName
.\.venv\Scripts\python.exe -B -X utf8 scripts\evaluate_yolo_czech_japan.py --name $runName
$roadClip = 'data/raw/road_sample_04.mp4'
$oldBest = 'outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/weights/best.pt'
$newBest = "outputs/yolo_multicountry/$runName/weights/best.pt"
.\.venv\Scripts\python.exe -B -X utf8 scripts\analyze_video.py $roadClip --model $oldBest --run-name road04_baseline_repeat --interval 0.5 --confidence 0.05 --max-gap 1.5 --device cuda:0
.\.venv\Scripts\python.exe -B -X utf8 scripts\analyze_video.py $roadClip --model $newBest --run-name road04_mixed_repeat --interval 0.5 --confidence 0.05 --max-gap 1.5 --device cuda:0
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -v
```

신규 테스트 7개와 이를 포함한 전체 회귀 테스트 63개가 통과했습니다. 고정 경로·매핑, Czech Val 원본 불일치, Train과 Val·Test 사이의 그룹 교차, 스모크 실패 후 중단, 기존 결과 폴더 보호, 실제 배치·옵티마이저 갱신 확인, 두 모델의 GT와 객체별 오류 매칭을 검사했습니다. [학습 CLI](../../scripts/train_yolo_czech_japan.py) · [평가 CLI](../../scripts/evaluate_yolo_czech_japan.py) · [신규 테스트](../../tests/test_yolo_czech_japan_training.py)

## 보존 확인

영상 분석 뒤 학습 전 기록과 대조한 Train·Val 이미지·라벨, 매니페스트, YAML, COCO 및 기존 모델 가중치 등 **16,461개 파일의 SHA-256이 모두 일치**했습니다. Czech v2·혼합 Pilot·Japan Holdout의 파일 수도 각각 5,659개·10,185개·3,477개였고, 시작 후 새로 생겼거나 수정 시각이 바뀐 파일은 0개였습니다. Test 영역은 파일 목록·시각 등 메타데이터만 확인했습니다. 신규 best 가중치의 SHA-256은 `3d770f1515ef2baf2fbe25d4c9ba241d289254b2002894d7cc02ff56009b2afb`입니다. [사후 보존 검사](../../outputs/yolo_multicountry/czech_japan_pilot_v1_yolo11n_640_b4_s42_e30/validation/preservation.json)
