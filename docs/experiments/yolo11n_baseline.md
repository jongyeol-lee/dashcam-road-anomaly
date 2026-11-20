# YOLO11n Baseline 학습 및 Validation 평가

실험일 **2026-11-19 (KST)** · RDD2022 Czech v2 · `20261119_yolo11n_640_b4_s42`

## 데이터와 사전학습 모델

Part 2의 [Czech v2 데이터 설정](../../data/yolo/rdd2022_czech_v2/data.yaml)과 분할을 사용했습니다. 원본 JPG는 `600×600`이며, 클래스 ID는 0부터 `D00`, `D10`, `D20`, `D40` 순서입니다.

| 분할 | 이미지 | 라벨 파일 | 이번 실험에서의 용도 |
| --- | ---: | ---: | --- |
| Train | 2,263 | 2,263 | 모델 학습 |
| Validation | 283 | 283 | 학습 중 검증과 `best.pt` 평가 및 오류 분석 |
| Test | 283 | 283 | 향후 최종 평가용으로 보존 |

학습 프로세스에는 Train과 Validation의 임시 사본을 제공했습니다. Ultralytics가 생성한 라벨 스캔 캐시는 임시 사본에 위치합니다. `cache=False`는 이미지 캐시를 끕니다. `args.yaml`의 `data`는 당시 임시 YAML 경로이며, 재실행에는 `training_summary.json`에 기록된 원본 Czech v2 경로를 사용합니다.

초기 가중치 `outputs/yolo11n.pt`는 Ultralytics 공식 `v8.3.0` 릴리스의 COCO 사전학습 탐지 모델입니다. 이번 작업에서 5,613,764바이트를 다운로드했으며, SHA-256은 `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1`입니다. [Ultralytics YOLO11 모델 설명](https://docs.ultralytics.com/models/yolo11) · [공식 가중치 릴리스](https://github.com/ultralytics/assets/releases/tag/v8.3.0)

RDD2022의 Figshare 배포 메타데이터에는 CC BY 4.0, CRDDC 대회 규칙에는 이미지 기준 CC BY-SA 4.0이 표기되어 있습니다. 로컬 Czech 폴더의 원본 ZIP과 다운로드 경로는 Part 2에서 확인되지 않아 로컬 사본의 배포 출처가 미확인입니다. [Figshare 배포 정보](https://api.figshare.com/v2/articles/21431547) · [CRDDC 대회 규칙](https://crddc2022.sekilab.global/rules/)

## 환경과 학습 설정

| 항목 | 확인 결과 |
| --- | --- |
| 실행 환경 | Windows 11 x64, 프로젝트 `.venv`, Python `3.14.5` |
| GPU | NVIDIA GeForce RTX 3060 Ti 8 GiB, CUDA `0`, 드라이버 `581.15` |
| 라이브러리 | PyTorch `2.14.1+cu130`, CUDA 빌드 `13.0`, Ultralytics `8.4.215` |
| Baseline | 최대 30 epochs, `imgsz=640`, `batch=4`, `seed=42`, `workers=2`, `deterministic=True` |
| 학습 옵션 | AMP·Validation·Plots 활성화, 이미지 캐시 비활성화, `patience=10`, `optimizer=auto` |

CUDA 텐서 연산과 역전파, 데이터 경로와 클래스 매핑, 공식 모델의 Train 이미지 로딩을 확인했습니다. 스모크 테스트는 seed 42로 선택한 Train 113장과 Validation 283장에서 1 epoch를 완료했습니다. AMP와 batch 4를 확인했고 `best.pt`, `last.pt`, `results.csv`를 저장했습니다. 36.15초는 학습 호출과 학습 종료 시 내부 검증을 포함한 시간입니다. [스모크 기록](../../outputs/yolo_smoke/20261119_smoke/training_summary.json)

## 본 학습 결과

Train 2,263장으로 **30/30 epoch**를 완료했습니다. AMP와 batch 4로 실행했고, Ultralytics의 자동 옵티마이저는 `AdamW`를 선택했습니다. 학습 호출부터 내부 최종 검증까지 **25분 23초**가 걸렸습니다. 이 구간의 PyTorch CUDA 메모리 최댓값은 할당량 673.88 MiB, 예약량 896 MiB입니다.

| Epoch | Train box loss | Train cls loss | Train DFL loss | 학습 중 Val mAP50 | 학습 중 Val mAP50–95 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2.65348 | 9.35849 | 2.07824 | 0.01920 | 0.00564 |
| 26 | 1.77396 | 2.32392 | 1.56488 | 0.17476 | 0.05789 |
| 30 | 1.70752 | 2.22462 | 1.52010 | 0.16062 | 0.05373 |

학습 중 Validation mAP50–95가 가장 높았던 26 epoch 체크포인트가 `best.pt`입니다. 모델 SHA-256은 `40f0b6af12b8a33d83119138251ae345ee2ac50df5a3ae0ec81137d781b63342`입니다. [best.pt](../../outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/weights/best.pt) · [last.pt](../../outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/weights/last.pt) · [results.csv](../../outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/results.csv) · [학습 그래프](../../outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/results.png) · [args.yaml](../../outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/args.yaml) · [학습 기록](../../outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/training_summary.json)

## `best.pt` Validation 평가

Validation **283장, 정답 객체 174개**를 GPU 0에서 평가했습니다. 입력은 `imgsz=640`, `rect=False`, batch 4였고, 예측 최소 confidence는 `0.001`, NMS IoU는 `0.7`입니다. 표의 Precision과 Recall은 Ultralytics가 평균 F1이 최대인 confidence에서 산출한 값입니다. [Ultralytics 평가 기준](https://docs.ultralytics.com/modes/val)

| 클래스 | 이미지 | 정답 객체 | Precision | Recall | AP50 | AP50–95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| **전체** | **283** | **174** | **0.2893** | **0.2860** | **0.1756** | **0.0640** |
| D00 종방향 균열 | 77 | 98 | 0.2378 | 0.4184 | 0.2565 | 0.0966 |
| D10 횡방향 균열 | 31 | 39 | 0.3700 | 0.0462 | 0.1455 | 0.0432 |
| D20 거북등 균열 | 13 | 17 | 0.1225 | 0.5294 | 0.0921 | 0.0295 |
| D40 포트홀 | 16 | 20 | 0.4268 | 0.1500 | 0.2083 | 0.0867 |

전체 행의 AP50과 AP50–95는 클래스 평균인 mAP입니다. 독립 평가 호출에 10.39초가 걸렸습니다. 이 조건에서 Ultralytics가 기록한 이미지당 평균 시간은 전처리 0.77 ms, 모델 추론 3.98 ms, 후처리 1.21 ms입니다. [정량 결과 JSON](../../outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/validation/metrics.json) · [PR 곡선](../../outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/validation/BoxPR_curve.png) · [혼동 행렬](../../outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/validation/confusion_matrix.png) · [정규화 혼동 행렬](../../outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/validation/confusion_matrix_normalized.png)

## 정성적 오류 분석

Validation 전체에서 confidence `0.25`, NMS IoU `0.7`로 예측했습니다. GT와 예측은 IoU `0.5` 이상에서 1:1로 연결했습니다. 같은 클래스를 먼저 연결하고 남은 매칭은 클래스 혼동으로 기록했습니다. 이 조건에서 정탐 10건, 대응 예측이 없는 정답 163건, 클래스 혼동 1건, 대응 정답이 없는 예측 25건이었습니다. 대응 정답이 없는 예측 중 3건은 빈 GT 이미지에서 나왔습니다. 대표 이미지 10장의 왼쪽에는 GT, 오른쪽에는 예측과 confidence가 표시됩니다. [사례 폴더](../../outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/validation/cases) · [사례와 클래스별 집계](../../outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/validation/qualitative.json)

| 유형 | 관찰 내용 | 이미지 |
| --- | --- | --- |
| 정탐 | 갓길 차선 옆 D00을 감지했습니다. confidence 0.560, GT IoU 0.728입니다. | [Czech_000370](../../outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/validation/cases/true_positive_Czech_000370.png) |
| 미탐 | GT의 D40 2개와 D20 2개에 대해 confidence 0.25 이상 예측이 없었습니다. | [Czech_000982](../../outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/validation/cases/false_negative_Czech_000982.png) |
| 배경 오탐 | GT가 비어 있으며, 모델의 D00 박스 2개가 같은 길쭉한 노면 자국에 겹쳤습니다. | [Czech_000161](../../outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/validation/cases/background_false_positive_Czech_000161.png) |
| 클래스 혼동 | 우측 노면의 D40 정답을 D20으로 분류했습니다. confidence 0.447, GT IoU 0.628입니다. | [Czech_003570](../../outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/validation/cases/class_confusion_Czech_003570.png) |
| 상대적으로 작은 정탐 | 이 조건에서 검출한 정답 중 가장 작은 D00 박스는 2,006 px²였습니다. confidence 0.270, GT IoU 0.713입니다. | [Czech_001518](../../outputs/yolo_baseline/20261119_yolo11n_640_b4_s42/validation/cases/small_detection_Czech_001518.png) |

D40 학습 객체는 158개이고 Validation에는 16장에 20개가 있습니다. 정성 분석 조건에서 D40으로 예측한 박스는 0개였습니다. D40 정답 19개에 대응 예측이 없었고 1개는 D20으로 분류됐습니다. D20과 D40의 Validation 표본이 각각 17개와 20개여서 한두 객체의 결과가 클래스별 지표에 큰 영향을 줄 수 있습니다.

## 검증 범위와 다음 확인 사항

프로젝트 `.venv`에서 기존 MP4·Czech 데이터 준비 테스트 17개와 새 Baseline 테스트 4개가 모두 통과했습니다. Part 2의 매니페스트와 원본 XML로 Train·Validation JPG 2,546장의 해시와 YOLO 라벨 좌표를 확인했습니다. 원본 데이터 경로의 Ultralytics 캐시 파일은 0개였습니다. 실제 블랙박스 MP4에서의 탐지 성능과 영상 분석 시간은 미검증입니다.

Part 2에서는 dHash 유사 후보가 분할을 넘지 않도록 배정했습니다. 원본 영상과 주행 구간 ID를 확인할 수 없어 검출 범위 밖의 유사 장면이 분할에 섞였을 가능성이 남습니다. 이후에는 주행 구간 단위로 분리한 블랙박스 영상에서 재현성을 확인하고, D10·D40의 미탐과 D20·D40 사이의 라벨 일관성을 먼저 점검할 수 있습니다. [Part 2 검사 보고서](../../data/processed/rdd2022_czech_v2/inspection_summary.json)

## 실행 명령어

프로젝트 루트에서 실행했습니다. 새 실험에는 새 `--name`을 사용합니다. 완료된 모델을 다시 평가할 때는 새 `--evaluation-name`으로 결과를 저장할 수 있습니다.

```powershell
$projectPython = '.\.venv\Scripts\python.exe'
& $projectPython -B -X utf8 scripts\train_yolo_baseline.py check
& $projectPython -u -B -X utf8 scripts\train_yolo_baseline.py smoke --name 20261119_smoke
& $projectPython -u -B -X utf8 scripts\train_yolo_baseline.py train `
  --name 20261119_yolo11n_640_b4_s42 --smoke-name 20261119_smoke
& $projectPython -u -B -X utf8 scripts\train_yolo_baseline.py evaluate --name 20261119_yolo11n_640_b4_s42
& $projectPython -B -X utf8 -m unittest discover -s tests -v
```
