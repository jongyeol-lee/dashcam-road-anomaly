"""사용자가 승인한 Part 5.3-2 v3 스냅샷을 평가 전용 GT로 발행·검증한다."""

import argparse
import json
import shutil
import sys
from hashlib import sha256
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts import annotate_dashcam_drafts as drafts
from road_anomaly.video_analysis import _write_json

APPROVAL = Path("outputs/annotation_review/part532_approval_preparation_v3/approval_manifest.json")
APPROVED_SHA = "da088ba526af7ff274862465f20128606ad801805a2c3e72f103667dfedcb3df"
RELEASE = drafts.REVIEW.parent / "part532_evaluation_gt_v1"
SCOPES = {
    "damage_gt_candidate": "positive",
    "normal_background_candidate": "normal_background",
    "uncertain_regions_only": "uncertain_regions_only",
    "whole_image_hold": "excluded",
}


def approved_snapshot():
    data = (PROJECT / APPROVAL).read_bytes()
    if sha256(data).hexdigest() != APPROVED_SHA:
        raise ValueError("사용자가 승인한 v3 매니페스트 SHA-256 불일치")
    return json.loads(data)


def release_documents(snapshot):
    """승인 원문에서 정답, 보류 영역과 이미지별 평가 범위를 투영한다."""
    frames, regions = [], []
    for entry in snapshot["images"]:
        scope = SCOPES[entry["image_disposition"]]
        image_id = entry["image_id"]
        row = {key: entry[key] for key in (
            "image_id", "revision", "source_video", "frame_index", "estimated_time_sec", "width", "height",
            "image_sha256", "source_draft", "latest_draft_sha256", "source_drive_group_id",
            "similar_frame_group_ids", "possible_same_damage_group", "confirmed_damage_case_id", "exclusion_reason",
        )}
        row.update(scope=scope, source_image=entry["image_path"],
                   image_path=None if scope == "excluded" else f"images/{scope}/{image_id}.png",
                   ground_truth=[])
        for box in entry["candidate_boxes"]:
            if box["candidate_class"] != "D20" or scope != "positive":
                raise ValueError(f"{image_id} 승인 대상 클래스·범위 불일치")
            row["ground_truth"].append({"box_id": box["box_id"], "class": "D20", "xyxy": box["xyxy"]})
        for box in entry["uncertain_regions"]:
            regions.append({"image_id": image_id, "revision": entry["revision"], "box_id": box["box_id"],
                            "xyxy": box["xyxy"], "stored_class": box["candidate_class"], "reason": box["reason"]})
        frames.append(row)
    return {
        "release_manifest.json": {
            "release": RELEASE.name, "purpose": "diagnostic_evaluation_only", "training_allowed": False,
            "approval_status": "approved", "approval_date_kst": "2026-11-25",
            "approval_manifest_project_path": APPROVAL.as_posix(), "approval_manifest_sha256": APPROVED_SHA,
            "source_root_project_path": drafts.REVIEW.relative_to(PROJECT).as_posix(),
            "coordinates": "original pixel xyxy, right and bottom exclusive",
            "uncertain_regions_file": "uncertain_regions.json", "images": frames,
        },
        "uncertain_regions.json": regions,
    }


def check_sources(snapshot):
    for entry in snapshot["images"]:
        label = drafts.REVIEW / entry["source_draft"]
        root = drafts.REVIEW / Path(entry["source_draft"]).parts[0]
        image = drafts.REVIEW / entry["image_path"]
        if (drafts.latest_revision(root, entry["image_id"]) != entry["revision"]
                or drafts.sha256_file(label) != entry["latest_draft_sha256"]
                or drafts.sha256_file(image) != entry["image_sha256"]):
            raise ValueError(f"{entry['image_id']} 최신 버전 또는 원본·초안 해시 불일치")
        saved = json.loads(label.read_bytes())
        for box in entry["candidate_boxes"] + entry["uncertain_regions"]:
            if saved["boxes"][box["box_id"] - 1] != drafts.make_box(box["candidate_class"], box["xyxy"]):
                raise ValueError(f"{entry['image_id']} #{box['box_id']} 저장 좌표·클래스 불일치")


def verify(directory, documents):
    expected_files = set(documents)
    for name, expected in documents.items():
        if json.loads((directory / name).read_bytes()) != expected:
            raise ValueError(f"{name} 승인 내용 불일치")
    for frame in documents["release_manifest.json"]["images"]:
        if frame["image_path"] is None:
            continue
        path = directory / frame["image_path"]
        drafts.read_image(path)
        if drafts.sha256_file(path) != frame["image_sha256"]:
            raise ValueError(f"{path} 원본 이미지 해시 불일치")
        expected_files.add(frame["image_path"])
    if {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()} != expected_files:
        raise ValueError("발행 파일 목록 불일치")


def publish():
    if RELEASE.exists():
        raise FileExistsError(f"기존 발행본이 있습니다. --verify로 확인하세요. {RELEASE}")
    snapshot = approved_snapshot()
    documents = release_documents(snapshot)
    check_sources(snapshot)
    with drafts.staging_directory(RELEASE.parent) as staging:
        for frame in documents["release_manifest.json"]["images"]:
            if frame["image_path"]:
                target = staging / frame["image_path"]
                target.parent.mkdir(exist_ok=True, parents=True)
                shutil.copyfile(drafts.REVIEW / frame["source_image"], target)
        for name, data in documents.items():
            _write_json(staging / name, data)
        verify(staging, documents)
        check_sources(approved_snapshot())
        staging.rename(RELEASE)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="기존 발행본을 읽기 전용으로 재검증")
    if parser.parse_args().verify:
        verify(RELEASE, release_documents(approved_snapshot()))
    else:
        publish()
    print(RELEASE)
