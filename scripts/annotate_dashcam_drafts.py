"""Part 5.3-2의 여섯 프레임에 대한 수동 박스 초안과 비교 이미지."""

import argparse
import csv
import json
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.prepare_dashcam_review import (
    OUTPUT_ROOT, ROIS, RUN_NAME, frame_title, roi_comparison, sha256_file, write_frame, write_jpg,
)
from road_anomaly.rdd2022 import CLASSES
from road_anomaly.video_analysis import _write_json


REVIEW = OUTPUT_ROOT / RUN_NAME
DRAFT_DIR = "annotation_drafts"
SIZE = (1920, 1080)
PENDING = "판단 보류"
CANDIDATES = (*CLASSES, PENDING)
STATUSES = ("미검토", "검토 중", PENDING, "초안 작성")
NO_DAMAGE = "파손 없음"
BACKGROUND_DIR = "background_drafts"
BACKGROUND_CROP = (320, 360, 1600, 1080)
BACKGROUND_IDS = ("front_000075", "front_000210", "front_000345", "front_000690",
                  "rear_000030", "rear_000255", "rear_000405", "rear_000690")
ROI_B = ROIS["B"]
# 주변 노면과 유리 무늬도 볼 수 있도록 넉넉히 잡은 열람 구역이다. 박스 목록과 별도로 보관한다.
DETAIL_CROPS = {
    "rear_000525": (320, 400, 1120, 850),
    "rear_000540": (330, 395, 1130, 845),
    "rear_000555": (340, 425, 1140, 875),
    "front_000510": (845, 495, 1645, 945),
    "rear_000120": (255, 395, 1055, 845),
    "rear_000135": (110, 326, 1070, 866),
}
BOX_COLOR = (40, 195, 255)


@contextmanager
def staging_directory(parent: Path):
    # Windows의 임시 폴더 전용 ACL이 최종 산출물에 남지 않도록 작업 폴더 권한을 상속한다.
    staging = parent / f".annotation-{uuid4().hex}"
    staging.mkdir()
    try:
        yield staging
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def make_box(candidate: str, xyxy: list[int] | tuple[int, ...]) -> dict:
    """원본 픽셀 경계와 클래스 후보를 검증하고 기존 ROI 필터의 판단·면적을 기록한다."""
    if candidate not in CANDIDATES:
        raise ValueError("클래스 후보를 목록에서 선택하세요.")
    if len(xyxy) != 4 or any(type(value) is not int for value in xyxy):
        raise ValueError("좌표 네 개를 정수로 입력하세요.")
    x1, y1, x2, y2 = xyxy
    width, height = SIZE
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError(f"0 ≤ x1 < x2 ≤ {width}, 0 ≤ y1 < y2 ≤ {height} 범위로 입력하세요.")
    decision = ROI_B.classify((x1, y1, x2, y2), width, height)
    vertices = np.asarray(ROI_B.pixel_vertices(width, height), dtype=np.float32)
    box = np.float32([(x1, y1), (x2, y1), (x2, y2), (x1, y2)])
    overlap, _ = cv2.intersectConvexConvex(vertices, box)
    outside = 1 - overlap / ((x2 - x1) * (y2 - y1))
    return {
        "candidate_class": candidate, "xyxy": list(xyxy),
        "roi_b": {"center_inside": decision.keep, "touches_boundary": decision.touches_boundary,
                  "outside_area_fraction": max(0.0, min(1.0, outside))},
    }


def read_image(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape[:2] != SIZE[::-1]:
        raise ValueError(f"1920×1080 원본 PNG를 읽을 수 없습니다. {path}")
    return image


def paint_boxes(image: np.ndarray, boxes: list[dict]) -> None:
    for index, box in enumerate(boxes, 1):
        x1, y1, x2, y2 = box["xyxy"]
        # 오른쪽·아래쪽 끝은 미포함이다. 저장한 영역의 마지막 픽셀에 테두리를 그린다.
        cv2.rectangle(image, (x1, y1), (x2 - 1, y2 - 1), BOX_COLOR, 1)
        if min(x2 - x1, y2 - y1) >= 4:
            cv2.rectangle(image, (x1 + 1, y1 + 1), (x2 - 2, y2 - 2), BOX_COLOR, 1)
        candidate = box["candidate_class"]
        label = f"{index} {candidate if candidate != PENDING else '?'}"
        cv2.putText(image, label, (min(x1, image.shape[1] - 98), max(19, y1 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, BOX_COLOR, 2, cv2.LINE_AA)


def box_comparison(image: np.ndarray, draft: dict) -> np.ndarray:
    comparison = roi_comparison(image, frame_title(draft), ROI_B)
    height, width = image.shape[:2]
    for left in (0, width):
        paint_boxes(comparison[-height:, left:left + width], draft["boxes"])
    return comparison


def revision_dir(root: Path, image_id: str, revision: int) -> Path:
    ids = BACKGROUND_IDS if root.name == BACKGROUND_DIR else DETAIL_CROPS
    if image_id not in ids:
        raise ValueError(f"현재 검토 세션의 이미지를 선택하세요. {image_id}")
    return root / "labels" / image_id / f"{revision:04d}"


def latest_revision(root: Path, image_id: str) -> int:
    parent = revision_dir(root, image_id, 0).parent
    return max((int(p.name) for p in parent.iterdir() if p.is_dir() and p.name.isascii() and p.name.isdecimal()),
               default=-1)


def save_revision(root: Path, image: np.ndarray, draft: dict) -> dict:
    """편집을 시작한 버전 다음에 JSON과 비교 JPG를 함께 게시한다. 기존 버전은 보존한다."""
    statuses = (*STATUSES, NO_DAMAGE) if root.name == BACKGROUND_DIR else STATUSES
    if draft["review_status"] not in statuses or not isinstance(draft["user_notes"], str):
        raise ValueError("검토 상태와 메모를 확인하세요.")
    boxes = [make_box(box["candidate_class"], box["xyxy"]) for box in draft["boxes"]]
    if boxes and draft["review_status"] == "미검토":
        raise ValueError("박스를 기록하려면 이미지 검토 상태를 선택하세요.")
    if boxes and draft["review_status"] == NO_DAMAGE:
        raise ValueError("박스가 있는 이미지는 파손 없음으로 저장할 수 없습니다.")
    image_id, previous = draft["image_id"], draft["revision"]
    revision = previous + 1
    target = revision_dir(root, image_id, revision)
    target.parent.mkdir(parents=True, exist_ok=True)
    conflict = "다른 창에서 새 초안을 저장했습니다. 최신 버전을 다시 열어 확인하세요."
    if latest_revision(root, image_id) != previous:
        raise FileExistsError(conflict)
    updated = {**draft, "revision": revision, "boxes": boxes}
    with staging_directory(target.parent) as staging:
        _write_json(staging / "draft.json", updated)
        write_jpg(staging / "roi_comparison.jpg", box_comparison(image, updated))
        # 비어 있지 않은 기존 버전 폴더는 rename으로 교체할 수 없다. 동시 저장도 같은 규칙을 따른다.
        try:
            staging.rename(target)
        except OSError as exc:
            if target.exists():
                raise FileExistsError(conflict) from exc
            raise
    return updated


def load_latest(root: Path, image_id: str) -> tuple[dict, np.ndarray]:
    revision = latest_revision(root, image_id)
    draft = json.loads((revision_dir(root, image_id, revision) / "draft.json").read_text(encoding="utf-8"))
    path = root / "originals" / f"{image_id}.png"
    if (draft["image_id"] != image_id or draft["revision"] != revision or
            sha256_file(path) != draft["image_sha256"]):
        raise ValueError(f"초안 버전 또는 원본 이미지 해시가 일치하지 않습니다. {image_id}")
    return draft, read_image(path)


def write_detail(root: Path, image: np.ndarray, draft: dict) -> None:
    image_id = draft["image_id"]
    x1, y1, x2, y2 = draft["detail_crop_xyxy"]
    crop = image[y1:y2, x1:x2]
    write_frame(root / "zoom" / f"{image_id}.png",
                cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
    marked = image.copy()
    cv2.rectangle(marked, (x1, y1), (x2 - 1, y2 - 1), (250, 205, 115), 3)
    panels = []
    for frame, caption in ((marked, "Original | Blue outline: detail view"),
                           (crop, f"Road detail | x [{x1}, {x2})   y [{y1}, {y2})")):
        display = cv2.resize(frame, (960, 540), interpolation=cv2.INTER_NEAREST if frame is crop else cv2.INTER_AREA)
        display = cv2.copyMakeBorder(display, 66, 0, 0, 0, cv2.BORDER_CONSTANT, value=(26, 27, 31))
        for line, y in ((frame_title(draft), 26), (caption, 52)):
            cv2.putText(display, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.68, (245, 245, 245), 1, cv2.LINE_AA)
        panels.append(display)
    write_jpg(root / "comparisons" / f"{image_id}.jpg", np.hstack(panels))


def prepare(review: Path = REVIEW, *, background: bool = False) -> Path:
    root = review / (BACKGROUND_DIR if background else DRAFT_DIR)
    if root.exists():
        raise FileExistsError(f"기존 초안이 있습니다. edit 명령으로 여세요. {root}")
    with (review / "review_manifest.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = {row["image_id"]: row for row in csv.DictReader(handle)}
    with (review / "frame_metadata.csv").open(encoding="utf-8-sig", newline="") as handle:
        digests = {row["image_id"]: row["image_sha256"] for row in csv.DictReader(handle)}
    crops = DETAIL_CROPS
    if background:
        crops = dict.fromkeys(BACKGROUND_IDS, BACKGROUND_CROP)
        for image_id in crops:
            camera = image_id.split("_")[0]
            if rows[image_id]["candidate_group_ids"] != f"{camera}_background":
                raise ValueError(f"배경 검토 그룹이 일치하지 않습니다. {image_id}")
    with staging_directory(review) as temporary:
        staging = temporary / root.name
        staging.mkdir()
        for name in ("originals", "zoom", "comparisons"):
            (staging / name).mkdir()
        for image_id, crop in crops.items():
            row = rows[image_id]
            source = review / row["image_path"]
            copy = staging / "originals" / f"{image_id}.png"
            copy.write_bytes(source.read_bytes())
            if sha256_file(copy) != digests[image_id]:
                raise ValueError(f"추출 당시 PNG 해시와 다릅니다. {source}")
            image = read_image(copy)
            draft = {
                "kind": "manual_annotation_draft", "revision": -1, "image_id": image_id,
                "source_video": row["source_video"], "image_path": row["image_path"], "image_sha256": digests[image_id],
                "frame_index": int(row["frame_index"]), "estimated_time_sec": float(row["estimated_time_sec"]),
                "similar_frame_group_ids": row["similar_frame_group_ids"], "source_drive_group_id": row["source_drive_group_id"],
                "width": SIZE[0], "height": SIZE[1], "detail_crop_xyxy": list(crop),
                "roi_b_vertices_normalized": ROI_B.vertices,
                "review_status": "미검토", "user_notes": "", "boxes": [],
            }
            write_detail(staging, image, draft)
            save_revision(staging, image, draft)
        staging.rename(root)
    return root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "edit"), default="edit", nargs="?")
    parser.add_argument("--background", action="store_true", help="배경 후보 8장의 별도 세션")
    args = parser.parse_args()
    if args.action == "prepare":
        print(prepare(background=args.background))
        return
    directory = REVIEW / (BACKGROUND_DIR if args.background else DRAFT_DIR)
    if not directory.is_dir():
        parser.error("먼저 prepare 명령으로 검토 자료를 생성하세요.")
    from scripts.dashcam_box_editor import run_editor
    run_editor(directory)


if __name__ == "__main__":
    main()
