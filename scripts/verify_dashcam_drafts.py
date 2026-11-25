"""Part 5.3-2 사용자 초안을 읽어 버전이 고정된 승인 검토 자료를 만든다."""

import argparse
import csv
import json
import os
import sys
from hashlib import sha256
from itertools import combinations
from pathlib import Path

import cv2


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import annotate_dashcam_drafts as drafts
from scripts.train_yolo_baseline import checked_name
from road_anomaly.video_analysis import _write_json
from road_anomaly.yolo_evaluation import Detection, box_iou


OUTPUT = PROJECT / "outputs/annotation_review"
RUN = "part532_approval_preparation_v2"
FINAL_RUN = "part532_approval_preparation_v3"
# 자유 서술 메모와 클래스의 의미를 대조한 정확한 저장본에만 수작업 해석을 적용한다.
REVIEWED_SHA = {
    "rear_000525": "1e99199bed2e9b6ce9304ced6ea2b469f585a61e961aff80be118924544053b0",
    "rear_000540": "24d982623fd379bb45337ab65ce9c21aaa90b746c46099df218cb72625076aa7",
    "rear_000555": "dcaed06a986c195e8feff62649461374b7c7da68ec59c7c93fb4907d32812496",
    "front_000510": "bf913a01d6ede5162374387cb27429d67cab5baf69470b9d6c4826e0be45d72a",
    "rear_000120": "4e43a3c81669efc67a63c1ac0ca9cc20a5156643237965e59f301eb70f0d9bcc",
    "rear_000135": "411153d72411ec889d84570525f39d1e0ec89b37ca007f3295e82a309e50cc97",
}


REVISED_SHA = {
    "rear_000540": "af81865f6b45cdd1776f2fe9e107d9deb60100048f4f4c0fbbddc412aaffbaf9",
    "rear_000120": "d80f2197186ba9c9bf8d00a446239b55c46cc14b52dd03593dd08e3538371198",
}

# 8장의 상태·박스와 자유 서술 메모를 직접 대조한 저장본. 다른 버전에 이 판단을 승계하지 않는다.
BACKGROUND_REVIEWED_SHA = {
    "front_000075": "0c207afaaca98251a3ed19289103d71744622ec0749f19c9de744eeddc845c69",
    "front_000210": "e01731da396f7767b33c05142b49f8b92191ee47ad290eeea5d24e679a941323",
    "front_000345": "ee12cb6a2960fa7fac886a8f9526af2ed10cf4f5902a5c039b7dee29b8124bd6",
    "front_000690": "1230e3b93430cfd9a35c1340598fff1953be512e449d7767ecb9cfbd5ffe9b74",
    "rear_000030": "ff55c6891249465647a7ed22dcb4506836dba2455f709da2da75cc9aca279c20",
    "rear_000255": "8b01d401a56eaba6a23d7139782f23643395cfff0d2d85a1aab34fc3465cab3d",
    "rear_000405": "1c3327bf2d41e998783cb0a802aefd06a26130643b126df0869019c479fa788f",
    "rear_000690": "b35b971dfa24400323e208646f7ec3b5d402c471e5463d585ce211ebf9230c95",
}


def by_id(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    indexed = {row["image_id"]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"중복 이미지 ID가 있습니다. {path}")
    return indexed


def duplicates(boxes):
    pairs = []
    for (i, a), (j, b) in combinations(enumerate(boxes, 1), 2):
        overlap = box_iou(Detection(0, tuple(a["xyxy"])), Detection(0, tuple(b["xyxy"])))
        if overlap >= 0.80:
            pairs.append({"box_ids": [i, j], "iou": overlap, "exact": a["xyxy"] == b["xyxy"]})
    return pairs


def validate(record, expected, *, background=False):
    for key, value in expected.items():
        if record[key] != value:
            raise ValueError(f"{record['image_id']} v{record['revision']}의 {key} 불일치")
    boxes, status = record["boxes"], record["review_status"]
    statuses = (*drafts.STATUSES, drafts.NO_DAMAGE) if background else drafts.STATUSES
    if not isinstance(boxes, list) or status not in statuses or not isinstance(record["user_notes"], str):
        raise ValueError("박스 목록, 상태 또는 메모 형식이 잘못됐습니다.")
    if (status in ("미검토", drafts.NO_DAMAGE) and boxes) or (record["revision"] == 0 and (status != "미검토" or record["user_notes"])):
        raise ValueError(f"{record['image_id']} v{record['revision']:04d}의 검토 상태와 입력 내용이 맞지 않습니다.")
    for box in boxes:
        recalculated = drafts.make_box(box["candidate_class"], box["xyxy"])
        if recalculated != box:
            raise ValueError(f"{record['image_id']} 저장 ROI B와 재계산 결과가 다릅니다.")


def reconcile(record, digest):
    """저장 필드는 보존하고 승인 대기·추가 확인·좌표가 없는 보류를 별도로 표시한다."""
    image_id = record["image_id"]
    original = digest == REVIEWED_SHA.get(image_id)
    revised = digest == REVISED_SHA.get(image_id)
    known = original or revised
    candidates, holds, unresolved_notes = [], [], []
    for number, box in enumerate(record["boxes"], 1):
        item = {"box_id": number, **box}
        if not known:
            holds.append(dict(item, reason="새 버전 메모와 클래스 대조 필요"))
        elif image_id == "rear_000120" and ((original and number in (3, 4)) or (revised and number == 2)):
            holds.append(dict(item, reason="저장 D40과 사용자 메모의 판단 보류 불일치"))
        elif box["candidate_class"] == drafts.PENDING:
            holds.append(dict(item, reason="사용자 지정 판단 보류"))
        else:
            candidates.append(dict(item, requires_additional_D40_confirmation=box["candidate_class"] == "D40"))
    if original and image_id == "rear_000540":
        unresolved_notes.append("상단의 별도 파손 의심 자국. 메모에만 있고 좌표 없음.")
    whole_hold = record["review_status"] == drafts.PENDING and not record["boxes"]
    return {
        "reviewed_snapshot": known, "candidate_boxes": candidates, "uncertain_regions": holds,
        "uncertain_without_coordinates": unresolved_notes, "whole_image_hold": whole_hold,
        "image_disposition": "exclude_pending_confirmation" if whole_hold else "await_user_review",
    }


def audit_image(review, row, metadata):
    image_id = row["image_id"]
    background = image_id in drafts.BACKGROUND_IDS
    root = review / (drafts.BACKGROUND_DIR if background else drafts.DRAFT_DIR)
    record, image = drafts.load_latest(root, image_id)
    index = int(row["frame_index"])
    expected = {k: row[k] for k in ("image_id", "source_video", "image_path", "similar_frame_group_ids", "source_drive_group_id")}
    for key in ("image_id", "source_video", "frame_index", "estimated_time_sec", "image_path", "candidate_group_ids"):
        if metadata[key] != row[key]:
            raise ValueError(f"매니페스트와 프레임 메타데이터의 {key} 불일치. {image_id}")
    if (image_id != f"{metadata['camera']}_{index:06d}"
            or float(row["estimated_time_sec"]) != index / float(metadata["fps"])
            or (int(metadata["width"]), int(metadata["height"])) != drafts.SIZE
            or drafts.sha256_file(review / row["image_path"]) != metadata["image_sha256"]):
        raise ValueError(f"원본 프레임 연결이 잘못됐습니다. {image_id}")
    expected.update(kind="manual_annotation_draft", frame_index=index, estimated_time_sec=float(row["estimated_time_sec"]),
                    width=drafts.SIZE[0], height=drafts.SIZE[1], image_sha256=metadata["image_sha256"],
                    detail_crop_xyxy=list(drafts.BACKGROUND_CROP if background else drafts.DETAIL_CROPS[image_id]),
                    roi_b_vertices_normalized=[list(v) for v in drafts.ROI_B.vertices])
    history = []
    for revision in range(record["revision"] + 1):
        directory = drafts.revision_dir(root, image_id, revision)
        data = (directory / "draft.json").read_bytes()
        version = json.loads(data)
        validate(version, dict(expected, revision=revision), background=background)
        ok, encoded = cv2.imencode(".jpg", drafts.box_comparison(image, version))
        if not ok or sha256(encoded).hexdigest() != drafts.sha256_file(directory / "roi_comparison.jpg"):
            raise ValueError(f"원본 좌표로 다시 그린 박스와 저장된 미리보기가 다릅니다. {directory}")
        history.append({"revision": revision, "sha256": sha256(data).hexdigest(), "box_count": len(version["boxes"]),
                        "review_status": version["review_status"], "duplicate_pairs": duplicates(version["boxes"])})
    if version != record:
        raise ValueError(f"검증 중 최신 초안 내용이 바뀌었습니다. {image_id}")
    return {
        **record, "history": history, "latest_draft_sha256": history[-1]["sha256"],
        "source_draft": (directory / "draft.json").relative_to(review).as_posix(),
        "saved_roi_preview": (directory / "roi_comparison.jpg").relative_to(review).as_posix(),
        "duplicate_pairs": history[-1]["duplicate_pairs"],
        **({} if background else reconcile(record, history[-1]["sha256"])),
    }, image


def write_preview(path, record, image):
    display = cv2.copyMakeBorder(image, 86, 0, 0, 0, cv2.BORDER_CONSTANT, value=(28, 28, 28))
    title = f"{record['image_id']}  |  {record['estimated_time_sec']:.1f} s  |  draft v{record['revision']:04d}"
    note = "Awaiting approval   |   Yellow: candidate   |   Orange: D40 needs confirmation   |   Magenta: hold"
    if record["whole_image_hold"]:
        note = "Entire image on hold - planned exclusion"
    elif record["uncertain_without_coordinates"]:
        note += "   |   Upper mark: note only"
    for label, y in ((title, 30), (note, 65)):
        cv2.putText(display, label, (16, y), cv2.FONT_HERSHEY_SIMPLEX, 0.77, (244, 244, 244), 2, cv2.LINE_AA)
    panel = display[86:]
    for key in ("candidate_boxes", "uncertain_regions"):
        for box in record[key]:
            hold = key == "uncertain_regions"
            color = (210, 66, 240) if hold else (0, 215, 255)
            if box.get("requires_additional_D40_confirmation"):
                color = (0, 132, 255)
            candidate = box["candidate_class"]
            label = f"#{box['box_id']} {candidate if candidate != drafts.PENDING else '?'}" + (" HOLD" if hold else "")
            x1, y1, x2, y2 = box["xyxy"]
            cv2.rectangle(panel, (x1, y1), (x2 - 1, y2 - 1), color, 2)
            for ink, weight in (((15, 15, 15), 4), (color, 2)):
                cv2.putText(panel, label, (x1, max(24, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.71, ink, weight, cv2.LINE_AA)
    drafts.write_jpg(path, display)


def final_entry(entry, previous):
    """서명 대상은 검토한 버전에 고정하고, 좌표가 있는 보류와 이미지 전체 제외를 구분한다."""
    image_id, digest = entry["image_id"], entry["latest_draft_sha256"]
    boxes, status = entry["boxes"], entry["review_status"]
    if entry["duplicate_pairs"]:
        raise ValueError(f"{image_id} 중복 의심 박스 확인 필요: {entry['duplicate_pairs']}")
    if image_id in drafts.BACKGROUND_IDS:
        if digest != BACKGROUND_REVIEWED_SHA[image_id]:
            raise ValueError(f"{image_id} 배경 저장본이 변경됐습니다. 최신 메모와 판정을 대조하세요.")
        if status == drafts.NO_DAMAGE and not boxes:
            disposition = "normal_background_candidate"
        elif status == drafts.PENDING and all(b["candidate_class"] == drafts.PENDING for b in boxes):
            disposition = "uncertain_regions_only" if boxes else "whole_image_hold"
        else:
            raise ValueError(f"{image_id} 배경 판정·박스 확인 필요")
        entry = dict(entry, candidate_boxes=[], uncertain_without_coordinates=[],
                     uncertain_regions=[dict(box, box_id=i, reason="사용자 지정 판단 보류")
                                        for i, box in enumerate(boxes, 1)])
    else:
        prior = previous[image_id]
        expected_digest = REVISED_SHA.get(image_id, REVIEWED_SHA[image_id])
        if (digest != expected_digest or entry["revision"] != prior["revision"]
                or digest != prior["latest_draft_sha256"]):
            raise ValueError(f"{image_id} 승인 검토 v2와 최신 저장본이 다릅니다.")
        disposition = "whole_image_hold" if entry["whole_image_hold"] else "damage_gt_candidate"

    # 사례 동일성은 사용자가 확정하지 않았다. 연속 관찰의 가설은 실제 사례 ID와 분리한다.
    possible_group = entry["similar_frame_group_ids"]
    excluded = disposition == "whole_image_hold"
    confirmation = []
    if image_id == "rear_000120":
        box = next(b for b in entry["uncertain_regions"] if b["box_id"] == 2)
        confirmation.append({"box_id": 2, "xyxy": box["xyxy"], "stored_class": box["candidate_class"],
                             "proposed_disposition": "uncertain_region", "approval_status": "pending",
                             "reason": "중앙 세 자국을 모두 보류한 메모에 따라 2번을 D40 GT에서 제외"})
    return dict(entry, image_disposition=disposition, approval_status="pending",
                whole_image_hold=excluded, exclude_from_evaluation=excluded,
                exclusion_reason=entry["user_notes"] if excluded else None,
                normal_background_candidate=disposition == "normal_background_candidate",
                confirmed_damage_case_id=None,
                possible_same_damage_group=possible_group if possible_group in ("rear_17_19", "rear_03_05") else None,
                additional_confirmation=confirmation)


def prepare(review=drafts.REVIEW, output=OUTPUT, run=None, *, final_review=False):
    target = output / checked_name(run if run is not None else (FINAL_RUN if final_review else RUN))
    if target.exists():
        raise FileExistsError(f"기존 승인 검토 자료가 있습니다. {target}")
    rows = by_id(review / "review_manifest.csv")
    metadata = by_id(review / "frame_metadata.csv")
    if len(rows) != 43 or rows.keys() != metadata.keys():
        raise ValueError("Part 5.3-2 두 매니페스트의 43개 프레임 ID를 확인하세요.")
    background = [row for row in rows.values()
                  if set(row["candidate_group_ids"].split("|")) & {"front_background", "rear_background"}]
    if {r["image_id"] for r in background} != set(drafts.BACKGROUND_IDS):
        raise ValueError("배경 검토 목록과 수동 박스 검토 목록을 확인하세요.")
    ids = list(drafts.DETAIL_CROPS)
    if final_review:
        prior_path = output / RUN / "approval_manifest.json"
        prior_data = prior_path.read_bytes()
        prior = json.loads(prior_data)
        previous = {entry["image_id"]: entry for entry in prior["images"]}
        if set(previous) != set(ids) or len(prior["images"]) != len(ids):
            raise ValueError("승인 검토 v2의 파손 후보 목록 불일치")
        ids.extend(drafts.BACKGROUND_IDS)
    output.mkdir(parents=True, exist_ok=True)
    with drafts.staging_directory(output) as staging:
        images = []
        for image_id in ids:
            entry, image = audit_image(review, rows[image_id], metadata[image_id])
            if final_review:
                entry = final_entry(entry, previous)
            else:
                entry["preview"] = f"{image_id}.jpg"
                write_preview(staging / entry["preview"], entry, image)
            images.append(entry)
        manifest = {"kind": "approval_review_only", "approved_versions": [], "training_allowed": False,
                    "source_root": review.name, "images": images,
                    "proposed_image_exclusions": [r["image_id"] for r in images if r["whole_image_hold"]]}
        if final_review:
            manifest.update(
                approval_status="pending", purpose="evaluation_only", gt_published=False,
                source_root=Path(os.path.relpath(review, target)).as_posix(),
                previous_manifest=f"../{RUN}/approval_manifest.json", previous_manifest_sha256=sha256(prior_data).hexdigest(),
                normal_background_candidates=[r["image_id"] for r in images if r["normal_background_candidate"]],
                summary={
                    "reviewed_images": len(images),
                    "candidate_boxes_by_class": {c: sum(b["candidate_class"] == c for r in images for b in r["candidate_boxes"])
                                                 for c in ("D20", "D40")},
                    "uncertain_regions": sum(len(r["uncertain_regions"]) for r in images),
                    "normal_background_candidates": sum(r["normal_background_candidate"] for r in images),
                    "excluded_images": len(manifest["proposed_image_exclusions"]),
                },
            )
        else:
            manifest["background_review_queue"] = background
        _write_json(staging / "approval_manifest.json", manifest)
        for entry in images:
            root = review / (drafts.BACKGROUND_DIR if entry["image_id"] in drafts.BACKGROUND_IDS else drafts.DRAFT_DIR)
            if (drafts.latest_revision(root, entry["image_id"]) != entry["revision"]
                    or drafts.sha256_file(review / entry["source_draft"]) != entry["latest_draft_sha256"]):
                raise ValueError("검증 중 새 버전이 저장됐습니다. 최신 버전을 다시 확인하세요.")
        staging.rename(target)
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name")
    parser.add_argument("--final-review", action="store_true", help="파손·배경 14장의 평가용 GT 승인 후보 검증")
    args = parser.parse_args()
    print(prepare(run=args.run_name, final_review=args.final_review))
