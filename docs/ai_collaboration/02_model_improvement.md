# 02. 모델 개선 — Czech의 약한 클래스와 실제 블랙박스 사이의 차이

## 작업 배경과 기존 방식의 문제

Czech v2 Baseline의 공식 Val에서 D10 Recall은 0.0462, D40은 0.1500이었습니다. 고정 confidence 0.25에서는 두 클래스 모두 정탐이 0개였습니다. 클래스 가중치를 조정한 선행 실험에서는 전체 mAP50–95가 0.0640에서 0.0450으로 하락했습니다. 이 결과를 보고 분류 가중치 조정보다 실제 D10·D40 학습 사례를 추가하는 가설을 시험했습니다. [Baseline](../experiments/yolo11n_baseline.md) · [클래스 가중치 실험과 미채택 이유](../experiments/yolo11n_improvement_01.md)

## 해결 가설과 기술 선택

Japan은 D10과 D40을 함께 보강할 수 있었고, 시각 검토한 표본에서 박스가 파손 의심 위치를 감쌌습니다. Czech Train 2,263장을 유지하고 Japan Train 2,263장을 추가했습니다. 두 모델은 같은 COCO 사전학습 가중치에서 각각 시작했고, 같은 Czech Val로 best를 선택했습니다. 학습이 끝난 뒤 동일한 Czech Val 283장과 Japan Val 869장에서 각각 비교했습니다. [학습 설계와 설정](../experiments/part5_multicountry_model_training.md)

## 프롬프트 목적과 제약 — 사후 요약

Part 5.2-4 원문은 미확보입니다. 실행 기록에서 확인되는 비교 조건은 YOLO11n, 입력 640, batch 4, seed 42, 최대 30 epoch, RTX 3060 Ti였습니다. 두 나라의 Test는 보존했고 나라별 Val은 두 모델이 공유했습니다. 클래스별 지표와 같은 정답 객체의 오류 변화, 실제 영상의 예측 위치까지 확인한 설계였습니다.

## AI 수행과 사용자 판단

Codex는 입력·가중치 해시 대조, 학습과 평가 사본 분리, 스모크 학습의 실제 갱신 확인, 국가별 결과 및 객체별 사례 비교를 구현했습니다. 사용자는 Japan 검토 표본의 박스 정렬에 의견을 주었습니다. 이후 새 모델이 운전대에 낸 박스 5개를 다음 진단의 문제로 지정했습니다. 각 학습 파라미터를 누가 제안했는지는 당시 원문이 없어 특정하지 않습니다. [사용자 검토 근거](../experiments/part5_multicountry_dataset_build.md) · [후속 ROI 진단 요청](prompts/part5_3_1_roi_diagnostic.md)

## 검증·수정과 측정 결과

동일 평가 코드로 기존 체크포인트의 지표를 재현한 뒤 혼합 모델을 비교했습니다. 아래 수치는 당시 저장된 결과이며 Recall은 Ultralytics의 평균 F1 기준 confidence에서 읽었습니다. [국가별 전체 지표와 재현 조건](../experiments/part5_multicountry_model_training.md)

| Validation | mAP50–95 기존 → 혼합 | D10 Recall 기존 → 혼합 | D40 Recall 기존 → 혼합 |
| --- | --- | --- | --- |
| Czech 283장 | 0.0640 → 0.1292 | 0.0462 → 0.2051 | 0.1500 → 0.2211 |
| Japan 869장 | 0.0106 → 0.1824 | 0.0050 → 0.2882 | 0.0446 → 0.4464 |

Czech에서 D10 Precision은 0.3700에서 0.2070, D40은 0.4268에서 0.3058로 떨어졌습니다. 고정 confidence 0.25에서는 두 모델 모두 Czech D40 정답 20개를 놓쳤습니다. 실제 `road_sample_04`의 동일한 59프레임(0.5초 간격, confidence 0.05)에서 기존 모델은 0개, 혼합 모델은 D40 5개를 표시했고 모두 운전대에 있었습니다.

## 한계와 후속 작업

두 실험 모두 30 epoch였지만 총 배치는 16,980에서 33,960으로 늘었습니다. Japan 데이터 구성과 총 학습량이 함께 바뀌었으므로 향상분을 국가 추가 효과만으로 분리할 수 없습니다. 이를 구분하려면 총 배치·샘플 노출을 맞춘 대조 실험이 필요합니다. 실제 블랙박스 성능은 사용자 승인 GT와 불확실 영역 처리 방법을 갖춘 뒤 검증할 과제로 남았습니다.

[학습 코드](../../scripts/train_yolo_czech_japan.py) · [국가별 비교 코드](../../scripts/evaluate_yolo_czech_japan.py) · [Baseline·가중치 실험 커밋 e83365e](https://github.com/jongyeol-lee/dashcam-road-anomaly/commit/e83365efbee90f4041a3ea6d6dd72a40f3cbe41c) · [혼합 학습 커밋 c214113](https://github.com/jongyeol-lee/dashcam-road-anomaly/commit/c214113fa39298b1fcdc7ee15511620791871067)
