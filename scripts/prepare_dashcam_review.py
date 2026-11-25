import argparse
import csv
import json
import math
import sys
from collections.abc import Iterable
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from fractions import Fraction
from hashlib import file_digest, sha256
from pathlib import Path

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.diagnose_video_detection import render_panel, write_jpg
from scripts.diagnose_video_roi import ROIS, shade_excluded
from scripts.train_yolo_baseline import checked_name
from road_anomaly.roi import NormalizedRoi
from road_anomaly.video import VideoMetadata, iter_decoded_frames, open_video_capture
from road_anomaly.video_analysis import _remove_run_directory, _write_json


INPUT_ROOT = PROJECT_ROOT / "data/raw/dashcam_validation"
OUTPUT_ROOT = PROJECT_ROOT / "data/processed/dashcam_validation"
ROI_SNAPSHOT = PROJECT_ROOT / "outputs/roi_diagnostics/part531_road04/roi_config.json"
RUN_NAME = "part532_candidate_review"
VIDEOS = {"front": "Dashcam-Front.mp4", "rear": "Dashcam-Rear.mp4"}
INTERVAL_SEC = 0.25
DRIVE_GROUP = "dashcam_validation_front_rear"
DECISIONS = ("균열 확인", "파손 없음", "판단 보류", "라벨링 제외")
FRAME_FIELDS = (
    "image_id", "camera", "source_video", "frame_index", "estimated_time_sec", "decoder_time_ms", "fps", "width",
    "height", "image_path", "image_sha256", "roi_preview_path", "candidate_group_ids", "requested_times_sec",
    "exact_duplicate_of",
)
REVIEW_FIELDS = (
    "image_id", "source_video", "frame_index", "estimated_time_sec", "candidate_group_ids", "review_priority",
    "image_path", "roi_preview_path", "similar_frame_group_ids", "source_drive_group_id", "exact_duplicate_of",
    "review_status", "user_decision", "user_class", "user_notes",
)


@dataclass(frozen=True)
class ReviewGroup:
    name: str
    camera: str
    kind: str
    target_times: tuple[float, ...]
    priority_times: tuple[float, ...]


def quarter_seconds(start: int, end: int) -> tuple[float, ...]:
    steps = int((end - start) / INTERVAL_SEC)
    return tuple(start + tick * INTERVAL_SEC for tick in range(steps + 1))


# 원본 구도를 확인해 노면이 보이는 위치와 거리가 달라지는 프레임을 우선 검토에 배치한다.
FRONT_BACKGROUND = (2.5, 7.0, 11.5, 23.0)
REAR_BACKGROUND = (1.0, 8.5, 13.5, 23.0)
GROUPS = (
    ReviewGroup("front_14_18", "front", "suspect_window", quarter_seconds(14, 18), (14.25, 15.25, 15.75, 16.25, 17.0, 17.75)),
    ReviewGroup("rear_03_05", "rear", "suspect_window", quarter_seconds(3, 5), (3.5, 4.0, 4.5, 5.0)),
    ReviewGroup("rear_17_19", "rear", "suspect_window", quarter_seconds(17, 19), (17.0, 17.5, 18.5, 19.0)),
    ReviewGroup("front_background", "front", "background_candidate", FRONT_BACKGROUND, FRONT_BACKGROUND),
    ReviewGroup("rear_background", "rear", "background_candidate", REAR_BACKGROUND, REAR_BACKGROUND),
)


def plan_frames(groups: Iterable[ReviewGroup], metadata: VideoMetadata) -> dict[int, list[tuple[ReviewGroup, float]]]:
    """목표 시각 이상의 첫 프레임을 고르고 같은 원본 인덱스에 대응하는 요청을 모은다."""
    if min(metadata.width, metadata.height, metadata.frame_count) <= 0:
        raise ValueError("영상 해상도와 전체 프레임 수가 양수여야 합니다.")
    fps = Fraction(str(metadata.fps))
    requests = {}
    for group in groups:
        for target_time in dict.fromkeys(group.target_times):
            # 30 fps에서는 0.25초가 7.5프레임이다. 부동소수점 반올림 대신 올림을 정확히 계산한다.
            index = math.ceil(Fraction(str(target_time)) * fps)
            if target_time < 0 or index >= metadata.frame_count:
                raise ValueError(f"영상 범위를 벗어난 목표 시각입니다. {group.name} / {target_time:g}초")
            requests.setdefault(index, []).append((group, target_time))
    return requests


def sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return file_digest(handle, "sha256").hexdigest()


def write_frame(path: Path, image: np.ndarray) -> str:
    encoded, png = cv2.imencode(".png", image)
    if not encoded:
        raise RuntimeError(f"프레임을 PNG로 저장할 수 없습니다. {path}")
    with path.open("xb") as handle:
        handle.write(png)
    return sha256(png).hexdigest()


def frame_title(row: dict) -> str:
    return f"{row['source_video']} | Frame {row['frame_index']:06d} | {row['estimated_time_sec']:.4f} s"


def roi_comparison(image: np.ndarray, title: str, roi: NormalizedRoi) -> np.ndarray:
    """원본 픽셀 크기의 프레임 옆에 ROI를 칠한 사본을 나란히 배치한다."""
    panels = []
    for frame, label in ((image, "Original"), (shade_excluded(image, roi), "ROI B | Cyan: boundary | Shaded: excluded")):
        panel = cv2.copyMakeBorder(frame, 68, 0, 0, 0, cv2.BORDER_CONSTANT, value=(26, 27, 31))
        for text, y, scale in ((title, 27, 0.80), (label, 54, 0.72)):
            cv2.putText(panel, text, (16, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (245, 245, 245), 2, cv2.LINE_AA)
        panels.append(panel)
    return np.hstack(panels)


def extract_camera(path: Path, camera: str, output: Path, roi: NormalizedRoi) -> tuple[list[dict], dict]:
    rows, first_by_hash = [], {}
    decoded_count, last_ms = 0, None
    with open_video_capture(path) as (capture, metadata):
        requests = plan_frames((group for group in GROUPS if group.camera == camera), metadata)
        backend = capture.getBackendName()
        for index, image in iter_decoded_frames(capture):
            decoded_count += 1
            if image.shape[:2] != (metadata.height, metadata.width):
                raise ValueError(f"디코딩 해상도가 영상 메타데이터와 다릅니다. {path.name} / {index}")
            ms = capture.get(cv2.CAP_PROP_POS_MSEC)
            last_ms = ms if math.isfinite(ms) and (ms > 0 or (index == 0 and ms == 0)) else None
            if index not in requests:
                continue

            image_id = f"{camera}_{index:06d}"
            image_path = Path("frames") / camera / f"{image_id}.png"
            roi_path = Path("roi_previews") / camera / f"{image_id}.jpg"
            planned = requests[index]
            group_ids = tuple(dict.fromkeys(group.name for group, _ in planned))
            digest = write_frame(output / image_path, image)
            row = {
                "image_id": image_id, "camera": camera, "source_video": path.name, "frame_index": index,
                "estimated_time_sec": index / metadata.fps, "decoder_time_ms": last_ms,
                "fps": metadata.fps, "width": metadata.width, "height": metadata.height,
                "image_path": image_path.as_posix(), "image_sha256": digest, "roi_preview_path": roi_path.as_posix(),
                "candidate_group_ids": "|".join(group_ids),
                "requested_times_sec": "|".join(str(time) for time in sorted({time for _, time in planned})),
                "exact_duplicate_of": first_by_hash.get(digest, ""),
                "similar_frame_group_ids": "|".join(dict.fromkeys(
                    group.name for group, _ in planned if group.kind == "suspect_window"
                )),
                "group_ids": group_ids,
                "priority_groups": frozenset(group.name for group, time in planned if time in group.priority_times),
            }
            first_by_hash.setdefault(digest, image_id)
            write_jpg(output / roi_path, roi_comparison(image, frame_title(row), roi))
            rows.append(row)

    if decoded_count != metadata.frame_count or len(rows) != len(requests):
        raise RuntimeError(f"원본 프레임을 모두 디코딩하거나 필요한 프레임을 추출하지 못했습니다. {path.name}")
    settings = {
        **asdict(metadata), "source_video": path.name, "source_path": str(path), "source_bytes": path.stat().st_size,
        "duration_sec": decoded_count / metadata.fps, "decoded_frame_count": decoded_count, "backend": backend,
        "last_decoder_time_ms": last_ms, "extracted_frame_count": len(rows),
        "roi_b_vertices_px": roi.pixel_vertices(metadata.width, metadata.height),
    }
    return rows, settings


def export_contact_sheet(output: Path, group: ReviewGroup, rows: list[dict]) -> str:
    first, last = min(group.target_times), max(group.target_times)
    caption = f"{VIDEOS[group.camera]} | Targets {first:g}-{last:g} s" if group.kind == "suspect_window" else (
        f"{VIDEOS[group.camera]} | Background review candidates"
    )
    priority_count = sum(group.name in row["priority_groups"] for row in rows)
    tiles = []
    for row in rows:
        data = (output / row["image_path"]).read_bytes()
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError(f"Contact Sheet용 프레임을 읽을 수 없습니다. {row['image_path']}")
        note = "Priority review" if group.name in row["priority_groups"] else "Additional frame"
        tiles.append(render_panel(image, frame_title(row), f"{row['image_id']} | {note}"))

    height, width = tiles[0].shape[:2]
    columns = min(3, len(tiles))
    gap, header = 10, 58
    sheet = np.full((header + math.ceil(len(tiles) / columns) * (height + gap),
                     gap + columns * (width + gap), 3), (29, 30, 34), dtype=np.uint8)
    cv2.putText(sheet, f"{caption} | {len(tiles)} frames | {priority_count} priority", (gap, 36),
                cv2.FONT_HERSHEY_SIMPLEX, 0.80, (245, 245, 245), 2, cv2.LINE_AA)
    for index, tile in enumerate(tiles):
        y = header + (index // columns) * (height + gap)
        x = gap + (index % columns) * (width + gap)
        sheet[y:y + height, x:x + width] = tile
    path = Path("contact_sheets") / f"{group.name}.jpg"
    write_jpg(output / path, sheet)
    return path.as_posix()


def write_csv(path: Path, fields: tuple[str, ...], rows: Iterable[dict]) -> None:
    # Windows Excel에서 한글 검토 상태와 사용자 메모를 읽을 수 있게 BOM을 기록한다.
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def prepare_review(run_name: str) -> dict:
    output = OUTPUT_ROOT.resolve() / checked_name(run_name)
    if output.is_relative_to(INPUT_ROOT.resolve()) or output.is_relative_to((PROJECT_ROOT / "data/raw").resolve()):
        raise ValueError(f"원본 영상 폴더에 결과를 저장할 수 없습니다. {output}")
    if output.exists(follow_symlinks=False):
        raise FileExistsError(f"이미 사용 중인 실행 이름입니다. {output}")
    inputs = {camera: (INPUT_ROOT / filename).resolve() for camera, filename in VIDEOS.items()}
    before = {camera: sha256_file(path) for camera, path in inputs.items()}
    roi = ROIS["B"]
    roi_info = {
        "use": "visual_review_only", "code_definition": "scripts/diagnose_video_roi.py::ROIS['B']",
        "vertices_normalized": roi.vertices,
    }
    if ROI_SNAPSHOT.is_file():
        saved = json.loads(ROI_SNAPSHOT.read_text(encoding="utf-8"))["conditions"]["B"]["vertices_normalized"]
        roi_info["matches_part531_snapshot"] = roi.vertices == tuple(tuple(point) for point in saved)

    output.mkdir(parents=True)
    with ExitStack() as cleanup:
        cleanup.callback(_remove_run_directory, output)
        (output / "contact_sheets").mkdir()
        rows, sources = [], {}
        for camera, path in inputs.items():
            for folder in ("frames", "roi_previews"):
                (output / folder / camera).mkdir(parents=True)
            captured, sources[camera] = extract_camera(path, camera, output, roi)
            rows.extend(captured)

        group_summaries = {}
        for group in GROUPS:
            selected = [row for row in rows if group.name in row["group_ids"]]
            representatives = [row for row in selected if group.name in row["priority_groups"]]
            group_summaries[group.name] = {
                "camera": group.camera, "kind": group.kind, "requested_times_sec": group.target_times,
                "extracted_frame_count": len(selected), "contact_sheet": export_contact_sheet(output, group, selected),
                "representatives": [{key: row[key] for key in (
                    "image_id", "frame_index", "estimated_time_sec", "image_path", "roi_preview_path",
                )} for row in representatives],
            }

        write_csv(output / "frame_metadata.csv", FRAME_FIELDS, rows)
        ordered = sorted(rows, key=lambda row: not row["priority_groups"])
        write_csv(output / "review_manifest.csv", REVIEW_FIELDS, ({
            **row, "review_priority": "우선" if row["priority_groups"] else "추가", "source_drive_group_id": DRIVE_GROUP,
            "review_status": "미검토", "user_decision": "", "user_class": "", "user_notes": "",
        } for row in ordered))

        for camera, path in inputs.items():
            after = sha256_file(path)
            if before[camera] != after:
                raise RuntimeError(f"후보 프레임을 만드는 중 원본 MP4가 변경됐습니다. {path}")
            sources[camera].update(sha256_before=before[camera], sha256_after=after)

        summary = {
            "run_name": run_name, "output_dir": str(output), "opencv_version": cv2.__version__,
            "sources": sources, "source_drive_group_id": DRIVE_GROUP, "interval_sec": INTERVAL_SEC,
            "sampling_rule": "first frame at or after target by frame_index / fps; one file per source and frame index",
            "groups": group_summaries, "extracted_frame_count": len(rows),
            "priority_review_count": sum(bool(row["priority_groups"]) for row in rows), "roi_b": roi_info,
            "review_decisions": DECISIONS, "ground_truth_status": "pending_manual_review",
            "csv_encoding": "UTF-8 with BOM", "paths_relative_to": "output_dir",
        }
        _write_json(output / "extraction_summary.json", summary)
        cleanup.pop_all()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="전·후방 블랙박스 MP4의 수동 균열 검토 자료를 준비합니다.")
    parser.add_argument("--run-name", default=RUN_NAME, help="data/processed/dashcam_validation 아래 새 폴더 이름")
    args = parser.parse_args()
    try:
        summary = prepare_review(args.run_name)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, cv2.error) as error:
        parser.exit(1, f"{error}\n")

    for group, result in summary["groups"].items():
        print(f"{group} | 추출 {result['extracted_frame_count']}장 | 우선 검토 {len(result['representatives'])}장")
    print(f"출력 {summary['output_dir']}")


if __name__ == "__main__":
    main()
