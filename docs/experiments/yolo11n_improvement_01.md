# YOLO11n 오류 분석 및 클래스 가중치 실험

실험일 **2026-11-19 (KST)** · RDD2022 Czech v2 · `20261119_cls_pw025_640_b4_s42`

## 분석 범위

Part 3의 `best.pt` SHA-256과 저장된 공식 Validation 지표를 확인했습니다. 분석 대상은 Czech v2 Validation 283장과 정답 객체 174개입니다. 이 중 174장은 라벨이 빈 이미지입니다. [Part 3 보고서](yolo11n_baseline.md) · [Baseline 정량 결과](../../outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/validation/metrics.json)

최소 confidence `0.001`, 입력 `640×640`, batch 4, NMS IoU `0.7`로 추론했습니다. 같은 예측에서 confidence `0.05`, `0.10`, `0.25` 이상인 박스를 남겨 각 조건에서 GT와 1:1로 매칭했습니다. 같은 클래스와 IoU `0.50` 이상을 정탐으로 집계했습니다. 같은 클래스 매칭 후 남은 IoU `0.50` 이상 쌍은 클래스 혼동, 남은 같은 클래스의 IoU `0.10` 이상 `0.50` 미만 쌍은 위치 오류로 기록했습니다. 두 유형 모두 예측 클래스의 FP와 정답 클래스의 FN에 각각 포함했습니다. Precision은 `TP/(TP+FP)`, Recall은 `TP/(TP+FN)`입니다. 예측이 0개인 클래스의 Precision은 미정의입니다.

동일한 설정으로 독립 추론을 두 번 실행해 박스 좌표·confidence, 임계값별 집계와 매칭 결과가 일치함을 확인했습니다. 아래 집계는 임계값별 운영 분석입니다. 공식 AP와 최적 F1 지점의 Precision·Recall은 별도로 비교합니다. [임계값 분석 JSON](../../outputs/error_analysis/yolo11n_czech_v2_20261119/threshold_analysis.json) · [Ultralytics Validation 기준](https://docs.ultralytics.com/modes/val)

## Baseline 임계값별 오류

| Confidence | TP | FP | FN | Precision | Recall | 빈 GT 이미지 FP | D10 TP / FP | D40 TP / FP |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.05 | 71 | 309 | 103 | 0.1868 | 0.4080 | 36 | 8 / 19 | 4 / 9 |
| 0.10 | 38 | 102 | 136 | 0.2714 | 0.2184 | 6 | 0 / 0 | 0 / 0 |
| 0.25 | 10 | 26 | 164 | 0.2778 | 0.0575 | 3 | 0 / 0 | 0 / 0 |

`0.10`에서 `0.05`로 낮추자 맞게 찾은 객체가 33개 늘고 오탐이 207개 늘었습니다. D10과 D40으로 분류된 정탐 12건은 모두 `[0.05, 0.10)` 구간에 있었습니다. `0.05`에서도 D10 정답 39개 중 31개, D40 정답 20개 중 16개가 미탐이었습니다.

| 클래스 | `0.05`에서 확인한 오류 | GT 크기와 형태 |
| --- | --- | --- |
| D10 횡방향 균열 | 미매칭 26건, 위치 오류 4건, D00 혼동 1건 | 박스 짧은 변 중앙값 25 px. 39개 중 30개는 짧은 변이 32 px 미만입니다. |
| D40 포트홀 | 미매칭 15건, D20 혼동 1건 | 면적 중앙값은 전체 영상의 0.47%. 20개 중 17개는 면적이 전체의 1% 미만입니다. |
| D20 거북등 균열 | 정탐 10건과 오탐 78건. 오탐에는 같은 GT 주변의 중복 박스 13건과 빈 GT 이미지 예측 3건이 포함됩니다. | 면적 중앙값은 전체 영상의 3.48%입니다. |

작은 박스를 원본 `600×600` 이미지 면적의 1% 미만으로 정의했습니다. `0.05`에서 작은 박스는 80개 중 29개, 나머지 박스는 94개 중 42개를 맞혔습니다. 클래스 구성과 노면 패턴이 달라 면적만의 영향은 분리할 수 없습니다. D40 정탐 4개는 모두 작은 박스였고, D10 정탐 8개는 모두 짧은 변이 32 px 미만이었습니다. 이미지와 라벨만으로는 촬영 거리를 확인할 수 없습니다.

초기 집계에서 정규화 좌표의 오차로 D00의 짧은 변 32 px 경계 1개가 잘못 분류됐습니다. 원본 정수 픽셀 경계로 보정하고 Validation XML·YOLO 라벨 283쌍을 대조했습니다. 보정 전후 TP·FP·FN과 클래스 혼동 집계는 일치했습니다. 최종 사례는 새 분석 경로에 저장했습니다.

## 대표 이미지와 라벨 점검

GT는 왼쪽, 예측과 confidence는 오른쪽에 표시했습니다. 총 19장으로 D00 4장, D10·D20·D40 각 5장입니다. 이미지에는 confidence를 소수 넷째 자리까지 표시했고, 사례 JSON에는 원래 값을 저장했습니다. [대표 사례 19장](../../outputs/error_analysis/yolo11n_czech_v2_20261119/cases)

| 유형 | 확인한 사실 | 확인이 필요한 해석 |
| --- | --- | --- |
| D40 낮은 confidence 정탐 | `Czech_003477`의 40×27 px 포트홀을 confidence 0.09525, IoU 0.838로 탐지했습니다. [이미지](../../outputs/error_analysis/yolo11n_czech_v2_20261119/cases/true_positive_D40_Czech_003477_conf0.05.png) | 박스가 정답 위치에 겹쳤고 confidence가 0.10 미만이어서 해당 임계값에서 제외됐습니다. |
| D10 위치 오류 | `Czech_002385`의 폭 301 px D10 박스에 예측이 일부만 걸쳐 IoU 0.280이었습니다. [이미지](../../outputs/error_analysis/yolo11n_czech_v2_20261119/cases/localization_D10_Czech_002385_conf0.05.png) | 길게 이어진 균열을 짧게 예측한 사례입니다. 길이를 나눠 주석하는 기준도 함께 확인할 필요가 있습니다. |
| D10 분류 혼동 | `Czech_003488`에서 GT D10을 D00으로 분류했습니다. confidence 0.0825, IoU 0.647입니다. [이미지](../../outputs/error_analysis/yolo11n_czech_v2_20261119/cases/class_confusion_D10_Czech_003488_conf0.05.png) | 서로 교차하는 자국이 보입니다. 가까운 방향의 D10·D00 구분 기준을 재검토할 표본입니다. |
| D40 작은 박스 미탐 | `Czech_000064`의 53×16 px 포트홀에 `0.25` 이상 예측이 없었습니다. [이미지](../../outputs/error_analysis/yolo11n_czech_v2_20261119/cases/small_miss_D40_Czech_000064_conf0.25.png) | 가로로 긴 어두운 자국이 보입니다. 화면 내 크기는 측정했고 실제 거리는 미확인입니다. |
| D40 분류 혼동 | `Czech_003570`에서 GT D40을 D20으로 분류했습니다. confidence 0.447, IoU 0.628입니다. [이미지](../../outputs/error_analysis/yolo11n_czech_v2_20261119/cases/class_confusion_D40_Czech_003570_conf0.25.png) | 포트홀과 주변 균열이 함께 보입니다. D20과 D40의 경계를 재검토할 표본입니다. |
| 빈 GT 이미지 과다 탐지 | `Czech_003155`의 우측 노면 영역을 D20으로 표시했습니다. GT는 비어 있습니다. [이미지](../../outputs/error_analysis/yolo11n_czech_v2_20261119/cases/background_false_positive_D20_Czech_003155_conf0.10.png) | 불균일한 표면과 보수 흔적으로 보이는 부분이 있습니다. 실제 파손 여부나 라벨 누락은 이 이미지로 확정할 수 없습니다. |

## 단일 개선 실험의 근거

Train의 객체 수는 D00 791개, D10 321개, D20 128개, D40 158개입니다. D40은 D00의 약 5분의 1이고, D10·D40 둘 다 IoU가 높은 예측이 confidence `0.10` 미만에 머무는 사례가 있었습니다. 이 결과를 근거로 클래스 빈도의 상대적 영향만 조절하는 가설을 선택했습니다. Ultralytics `cls_pw`를 `0.0`에서 `0.25`로 변경했습니다. Train 객체 수의 역빈도에 0.25 제곱을 적용한 뒤 네 가중치의 평균이 1이 되게 정규화합니다. [Ultralytics 클래스 가중치 설명](https://docs.ultralytics.com/modes/train#how-do-i-train-a-model-on-an-imbalanced-dataset)

공식 COCO `yolo11n.pt`, Train 2,263장, Validation 283장, 최대 30 epoch, seed 42, `imgsz=640`, batch 4, CUDA 0, workers 2, AMP, AdamW 자동 선택과 patience 10을 적용했습니다. Test 283장은 최종 평가용으로 보존했습니다. 모델이 처음부터 좁은 균열이나 복합 파손의 특징을 구분하지 못한 경우 가중치 조정만으로 위치나 라벨 경계 문제가 개선되기 어렵습니다. D20 가중치 상승으로 오탐이 증가하거나 D00 탐지에 손실이 생길 가능성도 있습니다.

## 학습 결과와 비교 조건

**실험 1회에서 30/30 epoch를 완료했습니다.** 실제 학습 가중치는 D00 `0.751117`, D10 `0.941078`, D20 `1.184267`, D40 `1.123538`이었습니다. 두 `args.yaml`을 대조해 실행 경로와 이름을 제외한 설정 차이가 `cls_pw` 하나임을 확인했습니다. 학습 도중 가장 높은 Validation mAP50–95는 29 epoch에서 `0.04615`였으며, 해당 `best.pt`를 별도로 평가했습니다. [실험 설정과 입력 해시](../../outputs/yolo_improvement/20261119_cls_pw025_640_b4_s42/experiment.json) · [학습 기록](../../outputs/yolo_improvement/20261119_cls_pw025_640_b4_s42/training_summary.json) · [results.csv](../../outputs/yolo_improvement/20261119_cls_pw025_640_b4_s42/results.csv) · [args.yaml](../../outputs/yolo_improvement/20261119_cls_pw025_640_b4_s42/args.yaml)

별도 평가는 Baseline과 동일한 Validation 283장, `640×640`, batch 4, CUDA 0, 최소 confidence `0.001`, NMS IoU `0.7` 조건입니다. `best.pt`의 SHA-256은 `02e3c79017105799bf5facb8d912ae5db4b775cec02e739a414558a01c84bebe`입니다. [실험 best.pt](../../outputs/yolo_improvement/20261119_cls_pw025_640_b4_s42/weights/best.pt) · [last.pt](../../outputs/yolo_improvement/20261119_cls_pw025_640_b4_s42/weights/last.pt) · [Validation 결과](../../outputs/yolo_improvement/20261119_cls_pw025_640_b4_s42/validation/metrics.json) · [혼동 행렬](../../outputs/yolo_improvement/20261119_cls_pw025_640_b4_s42/validation/confusion_matrix.png)

| 지표 | Baseline | 클래스 가중치 실험 | 변화 |
| --- | ---: | ---: | ---: |
| Precision | 0.2893 | 0.1725 | −0.1168 |
| Recall | 0.2860 | 0.2558 | −0.0301 |
| mAP50 | 0.1756 | 0.1368 | −0.0388 |
| mAP50–95 | 0.0640 | 0.0450 | −0.0189 |
| D40 Recall | 0.1500 | 0.1500 | 0.0000 |
| D10 Recall | 0.0462 | 0.0762 | +0.0301 |

변화량은 반올림 전 수치에서 계산했습니다. 아래는 `Baseline → 클래스 가중치 실험` 순서입니다. [전체 비교 JSON](../../outputs/yolo_improvement/20261119_cls_pw025_640_b4_s42/validation/comparison.json)

| 클래스 | Precision | Recall | AP50 | AP50–95 |
| --- | ---: | ---: | ---: | ---: |
| D00 | 0.2378 → 0.2077 | 0.4184 → 0.3265 | 0.2565 → 0.2184 | 0.0966 → 0.0799 |
| D10 | 0.3700 → 0.2482 | 0.0462 → 0.0762 | 0.1455 → 0.1258 | 0.0432 → 0.0356 |
| D20 | 0.1225 → 0.0845 | 0.5294 → 0.4706 | 0.0921 → 0.1162 | 0.0295 → 0.0352 |
| D40 | 0.4268 → 0.1496 | 0.1500 → 0.1500 | 0.2083 → 0.0867 | 0.0867 → 0.0294 |

| Confidence | 전체 TP | 전체 FP | 전체 FN | D10 TP / FP | D20 TP / FP | D40 TP / FP |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.05 | 71 → 69 | 309 → 456 | 103 → 105 | 8 / 19 → 11 / 58 | 10 / 78 → 9 / 130 | 4 / 9 → 4 / 35 |
| 0.10 | 38 → 36 | 102 → 153 | 136 → 138 | 0 / 0 → 1 / 4 | 5 / 48 → 8 / 69 | 0 / 0 → 2 / 6 |
| 0.25 | 10 → 16 | 26 → 42 | 164 → 158 | 0 / 0 → 0 / 0 | 3 / 19 → 5 / 33 | 0 / 0 → 0 / 0 |

| 비용 항목 | Baseline | 클래스 가중치 실험 |
| --- | ---: | ---: |
| 학습 호출과 내부 최종 검증 | 1,522.77초 | 1,479.02초 |
| PyTorch CUDA 최대 할당량 | 673.88 MiB | 627.78 MiB |
| PyTorch CUDA 최대 예약량 | 896 MiB | 836 MiB |
| Validation 이미지당 추론 | 3.98 ms | 3.11 ms |

속도와 메모리는 RTX 3060 Ti의 각 실행에서 한 번 측정한 수치입니다. 영상 디코딩과 프레임 추출 시간은 포함되지 않습니다.

## 판단과 Part 5 확인 사항

**이번 설정 변경은 개선에 실패했습니다.** D10 Recall은 올랐지만 Precision과 AP가 떨어졌습니다. D40의 공식 Recall은 그대로였고, `0.05`에서도 정탐 4건으로 같았지만 오탐이 9건에서 35건으로 늘었습니다. D20의 AP50–95는 올랐지만 `0.05`에서 오탐이 78건에서 130건으로 늘었습니다. 세 confidence 기준에서 전체 오탐이 늘었고 전체 mAP50–95는 `0.0640`에서 `0.0450`으로 떨어졌습니다. 드문 클래스에 더 큰 가중치를 주는 것만으로는 이번 실험에서 낮은 confidence와 과다 탐지를 함께 개선할 수 없었습니다.

Part 5에서는 Baseline을 비교 기준으로 사용하고, 주행 구간을 분리한 실제 MP4에서 장면 단위 미탐과 분당 오탐, 연속 프레임 중복을 먼저 확인합니다. 포트홀과 주변 거북등 균열의 경계, 횡방향 균열의 박스 길이, 보수 표면이 보이는 빈 라벨 이미지의 주석을 재검토할 후보로 남겼습니다. 영상 ID가 없어 Czech 분할에 유사 주행 장면이 남아 있을 수 있습니다. 실제 블랙박스 영상 성능은 미검증입니다.

기존 테스트를 포함한 27개 테스트가 통과했습니다. 매칭, confidence 재현성, 크기 경계, 평가 조건 일치, 기존 출력 보호를 확인했습니다. Baseline 산출물과 Train·Validation의 학습 전후 해시가 일치했습니다. 이 실험의 추론과 정량 평가는 Validation으로 제한했습니다.

## 실행 명령어

프로젝트 루트에서 실행합니다. 기존 결과와 구분되는 이름은 `--name`, 기존 분석 결과 위치는 `--analysis-name`으로 지정할 수 있습니다.

```powershell
$py = '.\.venv\Scripts\python.exe'
& $py -u -B -X utf8 scripts\yolo_improvement_01.py analyze
& $py -u -B -X utf8 scripts\yolo_improvement_01.py train --name 20261119_cls_pw025_640_b4_s42
& $py -u -B -X utf8 scripts\yolo_improvement_01.py analyze --name yolo11n_czech_v2_20261119
& $py -u -B -X utf8 scripts\yolo_improvement_01.py evaluate `
  --name 20261119_cls_pw025_640_b4_s42 --analysis-name yolo11n_czech_v2_20261119
& $py -B -X utf8 -m unittest discover -s tests -v
```
