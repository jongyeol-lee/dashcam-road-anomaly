import csv
import json
import logging
import os
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from queue import Queue
from stat import S_ISREG
from tempfile import NamedTemporaryFile
from threading import Event, RLock, Thread
from uuid import UUID

import cv2
import numpy as np
from pydantic import ValidationError

from ..rdd2022 import CLASSES
from ..video import open_video_capture
from ..video_analysis import MVP_SHA256, PROJECT_ROOT, analyze_video
from .schemas import (
    AnalysisResults, ApiError, JobAnalysisSummary, JobHistory, JobHistoryItem, JobHistoryQuery, JobHistoryWarning,
    JobReviews, ReviewState, ReviewSummary, Scene, SceneReview, StoredJob, VideoInfo,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApiSettings:
    project_root: Path = PROJECT_ROOT
    max_upload_bytes: int = 200 * 1024 * 1024
    upload_chunk_bytes: int = 1024 * 1024
    max_event_duration: float = 5.0
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    def __post_init__(self):
        from ..detection_grouping import validate_max_event_duration

        if self.max_upload_bytes <= 0 or self.upload_chunk_bytes <= 0:
            raise ValueError("업로드 크기와 청크 크기는 양수여야 합니다.")
        validate_max_event_duration(self.max_event_duration)

    @property
    def uploads_root(self) -> Path:
        return self.project_root / "data/raw/uploads"

    @property
    def jobs_root(self) -> Path:
        return self.project_root / "outputs/jobs"

    @property
    def analysis_root(self) -> Path:
        return self.project_root / "outputs/video_analysis/jobs"

    @property
    def frames_root(self) -> Path:
        return self.project_root / "data/processed/frames/jobs"


class JobError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.error = ApiError(code=code, message=message)


def contained_path(root: Path, *parts: str) -> Path:
    """사용자 입력뿐 아니라 심볼릭 링크로 작업 폴더를 벗어나는 접근도 막는다."""
    root = root.resolve()
    expected = root.joinpath(*parts)
    path = expected.resolve()
    if path != expected or not path.is_relative_to(root) or path == root:
        raise JobError(404, "not_found", "파일 또는 작업을 찾을 수 없습니다.")
    return path


def write_json_atomic(path: Path, data: dict) -> None:
    """같은 파일시스템의 임시 파일을 교체해 독자가 미완성 JSON을 읽지 않게 한다."""
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def history_warning(job_id: UUID, code: str, message: str) -> JobHistoryWarning:
    logger.warning("분석 이력 조회 경고 (%s): %s", code, job_id)
    return JobHistoryWarning(job_id=job_id, error=ApiError(code=code, message=message))


def validate_upload(path: Path) -> None:
    """표준 MP4 컨테이너와 전체 프레임 디코딩을 검사한다. 모델 추론은 하지 않는다."""
    try:
        with path.open("rb") as handle:
            header = handle.read(12)
        if len(header) < 12 or header[4:8] != b"ftyp" or header[8:12] == b"qt  ":
            raise ValueError("MP4 container required")
        with open_video_capture(path) as (capture, metadata):
            if metadata.width <= 0 or metadata.height <= 0:
                raise ValueError("Invalid dimensions")
            decoded_count = 0
            while True:
                decoded, frame = capture.read()
                if not decoded:
                    break
                if frame is None or frame.size == 0:
                    raise ValueError("Empty decoded frame")
                decoded_count += 1
            if decoded_count == 0 or (metadata.frame_count > 0 and decoded_count != metadata.frame_count):
                raise ValueError("Incomplete video decoding")
    except (OSError, RuntimeError, ValueError, cv2.error) as error:
        raise JobError(422, "invalid_video", "MP4 영상을 정상적으로 디코딩할 수 없습니다.") from error


class JobManager:
    """파일 저장소와 단일 GPU 워커를 관리한다. 같은 저장소의 중복 서버는 잠금으로 막는다."""

    def __init__(self, settings: ApiSettings, analyzer: Callable = analyze_video):
        self.settings = settings
        self.analyzer = analyzer
        self._lock = RLock()
        self._queue = Queue()
        self._stopping = Event()
        self._thread = None
        self._process_lock = None

    def start(self) -> None:
        self.settings.jobs_root.mkdir(parents=True, exist_ok=True)
        handle = (self.settings.jobs_root / ".worker.lock").open("a+b")
        try:
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            raise RuntimeError("이 작업 저장소를 사용하는 API 워커가 이미 실행 중입니다.") from error
        self._process_lock = handle
        try:
            self._recover_interrupted()
            self._thread = Thread(target=self._work, name="road-anomaly-gpu", daemon=True)
            self._thread.start()
        except BaseException:
            self._release_process_lock()
            raise

    def _release_process_lock(self) -> None:
        if self._process_lock is not None:
            self._process_lock.close()
            self._process_lock = None

    def begin_shutdown(self) -> None:
        # 등록·실행 시작·종료 신호를 같은 잠금으로 묶는다.
        with self._lock:
            if not self._stopping.is_set():
                self._stopping.set()
                self._queue.put(None)

    def stop(self) -> None:
        self.begin_shutdown()
        if self._thread is not None:
            # 이미 실행 중인 동기 추론이 끝난 뒤 설정과 잠금을 해제한다.
            self._thread.join()
        self._release_process_lock()

    def _job_path(self, job_id: UUID) -> Path:
        return contained_path(self.settings.jobs_root, str(job_id), "job.json")

    def get(self, job_id: UUID) -> StoredJob:
        with self._lock:
            path = self._job_path(job_id)
            if not path.is_file():
                raise JobError(404, "not_found", "작업을 찾을 수 없습니다.")
            return StoredJob.model_validate_json(path.read_text(encoding="utf-8"))

    def submit(self, job_id: UUID, *, original_filename: str | None = None,
               file_size_bytes: int | None = None) -> StoredJob:
        with self._lock:
            if self._stopping.is_set():
                raise JobError(503, "shutting_down", "서버가 종료 중입니다.")
            job = StoredJob(job_id=job_id, status="queued", created_at=datetime.now(UTC),
                            original_filename=original_filename, file_size_bytes=file_size_bytes)
            path = self._job_path(job_id)
            path.parent.mkdir(parents=True)
            try:
                write_json_atomic(path, job.to_storage())
            except Exception:
                path.unlink(missing_ok=True)
                path.parent.rmdir()
                raise
            self._queue.put(job_id)
            return job

    def list_history(self, query: JobHistoryQuery) -> JobHistory:
        matches = []
        warnings = []
        search = (query.search or "").strip().casefold()
        for directory in self.settings.jobs_root.iterdir():
            try:
                job_id = UUID(directory.name)
            except ValueError:
                continue
            if directory.name != str(job_id):
                continue
            try:
                job = self.get(job_id)
                if job.job_id != job_id:
                    raise ValueError("Inconsistent stored job ID")
            except (OSError, ValueError, JobError):
                warnings.append(history_warning(job_id, "job_data_unavailable", "저장된 작업 정보를 확인할 수 없습니다."))
                continue
            if query.status is not None and job.status != query.status:
                continue
            if search and search not in (job.original_filename or "").casefold():
                continue
            matches.append(job)

        # 오래된 타임스탬프에 시간대가 없으면 기존 서버 저장 기준인 UTC로 비교한다.
        matches.sort(key=lambda job: (job.created_at if job.created_at.tzinfo else job.created_at.replace(tzinfo=UTC),
                                      job.job_id), reverse=query.sort == "newest")
        items = [self._history_item(job, warnings) for job in matches[query.offset:query.offset + query.limit]]
        return JobHistory(items=items, total=len(matches), count=len(items), limit=query.limit, offset=query.offset,
                          warnings=warnings)

    def _history_item(self, job: StoredJob, warnings: list[JobHistoryWarning]) -> JobHistoryItem:
        item = JobHistoryItem(**job.model_dump())
        job_id = job.job_id
        if item.file_size_bytes is None:
            try:
                upload = self.video_path(job_id).stat()
                if not S_ISREG(upload.st_mode):
                    raise ValueError("Stored upload is not a regular file")
                item.file_size_bytes = upload.st_size
            except FileNotFoundError:
                pass
            except (JobError, OSError, ValueError):
                warnings.append(history_warning(job_id, "upload_size_unavailable", "업로드 파일 크기를 확인할 수 없습니다."))
        if job.status != "completed":
            return item

        # 완료 상태를 저장하기 전에 results.json을 게시한다. 완료된 결과는 바뀌지 않는다.
        try:
            results = self._read_results(job_id)
            event_ids = {scene.event_id for scene in results.events}
            if results.job_id != job_id or results.event_count != len(results.events) or len(event_ids) != len(results.events):
                raise ValueError("Inconsistent stored results")
        except (OSError, ValueError, JobError):
            warnings.append(history_warning(job_id, "results_unavailable", "저장된 분석 결과를 확인할 수 없습니다."))
            return item
        item.analysis = JobAnalysisSummary(video=results.video, event_count=results.event_count,
                                           analysis_seconds=results.analysis_seconds)

        # Windows에서 검토 파일 읽기와 원자적 교체가 충돌하지 않도록 한 작업씩 잠근다.
        try:
            with self._lock:
                path = self._reviews_path(job_id)
                reviews = self._read_reviews(path, job_id, event_ids)
        except JobError as error:
            code = "review_read_failed" if error.error.code == "review_read_failed" else "review_data_invalid"
            warnings.append(history_warning(job_id, code, "저장된 검토 데이터를 확인할 수 없습니다."))
            return item
        except (OSError, ValueError):
            warnings.append(history_warning(job_id, "review_read_failed", "검토 데이터를 읽을 수 없습니다."))
            return item
        counts = Counter(entry.review for entry in reviews.reviews)
        reviewed = counts["suspected"] + counts["false_positive"] + counts["deferred"]
        item.reviews = ReviewSummary(unreviewed=len(event_ids) - reviewed, suspected=counts["suspected"],
                                     false_positive=counts["false_positive"], deferred=counts["deferred"],
                                     reviewed_count=reviewed)
        return item

    def _update(self, job_id: UUID, **changes) -> None:
        with self._lock:
            job = self.get(job_id).model_copy(update=changes)
            write_json_atomic(self._job_path(job_id), job.to_storage())

    def _recover_interrupted(self) -> None:
        for directory in self.settings.jobs_root.iterdir():
            if not directory.is_dir():
                continue
            try:
                job_id = UUID(directory.name)
                job = self.get(job_id)
            except (ValueError, OSError, ValidationError, JobError):
                logger.warning("읽을 수 없는 작업 메타데이터를 건너뜁니다.")
                continue
            if job.status in ("queued", "running"):
                self._update(job_id, status="failed", finished_at=datetime.now(UTC),
                             error=ApiError(code="interrupted", message="서버 종료로 작업이 중단됐습니다. 새로 업로드해 주세요."))

    def _work(self) -> None:
        while (job_id := self._queue.get()) is not None:
            try:
                with self._lock:
                    if self._stopping.is_set():
                        self._update(job_id, status="failed", finished_at=datetime.now(UTC),
                                     error=ApiError(code="interrupted", message="서버 종료로 대기 작업이 중단됐습니다."))
                        continue
                    self._update(job_id, status="running", started_at=datetime.now(UTC))
                self.analyzer(
                    self.video_path(job_id), profile="mvp", run_name=str(job_id),
                    max_event_duration=self.settings.max_event_duration,
                    frames_root=self.settings.frames_root, analysis_root=self.settings.analysis_root,
                )
                # 반환값만 신뢰하지 않고 디스크의 요약·탐지·구간·JPEG를 확인한다.
                results = self._load_results(job_id, verify_files=True)
                write_json_atomic(self._results_path(job_id), results.model_dump(mode="json"))
                self._update(job_id, status="completed", finished_at=datetime.now(UTC))
            except Exception:
                # 상세 traceback은 로컬 서버 로그에만 남긴다. API에는 경로나 모델 오류를 노출하지 않는다.
                logger.exception("분석 작업 실패: %s", job_id)
                try:
                    self._update(job_id, status="failed", finished_at=datetime.now(UTC),
                                 error=ApiError(code="analysis_failed", message="영상 분석에 실패했습니다. 서버 로그를 확인해 주세요."))
                except Exception:
                    logger.exception("작업 실패 상태 저장 실패: %s", job_id)
            finally:
                self._queue.task_done()

    def video_path(self, job_id: UUID) -> Path:
        return contained_path(self.settings.uploads_root, str(job_id), "input.mp4")

    def _results_path(self, job_id: UUID) -> Path:
        return contained_path(self.settings.jobs_root, str(job_id), "results.json")

    def _read_results(self, job_id: UUID) -> AnalysisResults:
        return AnalysisResults.model_validate_json(self._results_path(job_id).read_text(encoding="utf-8"))

    def results(self, job_id: UUID) -> AnalysisResults:
        if self.get(job_id).status != "completed":
            raise JobError(409, "results_not_ready", "완료된 작업의 결과만 조회할 수 있습니다.")
        return self._read_results(job_id)

    def scene_path(self, job_id: UUID, event_id: str) -> Path:
        results = self.results(job_id)
        if not any(event.event_id == event_id for event in results.events):
            raise JobError(404, "not_found", "대표 이미지를 찾을 수 없습니다.")
        # JSON에 있는 임의 경로를 제공하지 않고 검증한 ID로 경로를 구성한다.
        return contained_path(self.settings.analysis_root, str(job_id), "scenes", f"{event_id}.jpg")

    def _reviews_path(self, job_id: UUID) -> Path:
        return contained_path(self.settings.jobs_root, str(job_id), "reviews.json")

    def _read_reviews(self, path: Path, job_id: UUID, event_ids: set[str]) -> JobReviews:
        try:
            stored = JobReviews.model_validate_json(path.read_bytes())
            reviewed_ids = {entry.event_id for entry in stored.reviews}
            if stored.job_id != job_id or len(reviewed_ids) != len(stored.reviews) or not reviewed_ids <= event_ids:
                raise ValueError("Inconsistent review data")
        except FileNotFoundError:
            # 이전 완료 작업은 첫 저장 요청 전까지 검토 파일이 없다.
            return JobReviews(job_id=job_id, reviews=[])
        except ValueError as error:
            raise JobError(500, "review_data_invalid", "저장된 검토 데이터를 확인할 수 없습니다.") from error
        except OSError as error:
            logger.exception("검토 파일 읽기 실패: %s", job_id)
            raise JobError(500, "review_read_failed", "검토 데이터를 읽을 수 없습니다.") from error
        return stored

    def _review_event_ids(self, job_id: UUID) -> set[str]:
        results = self.results(job_id)
        if results.job_id != job_id:
            raise JobError(500, "internal_error", "작업의 분석 결과를 확인할 수 없습니다.")
        return {event.event_id for event in results.events}

    def reviews(self, job_id: UUID) -> JobReviews:
        with self._lock:
            event_ids = self._review_event_ids(job_id)
            path = self._reviews_path(job_id)
            return self._read_reviews(path, job_id, event_ids)

    def set_review(self, job_id: UUID, event_id: str, review: ReviewState) -> SceneReview:
        # 한 잠금 안에서 읽기부터 파일 교체까지 마쳐 다른 장면의 변경을 보존한다.
        with self._lock:
            event_ids = self._review_event_ids(job_id)
            if event_id not in event_ids:
                raise JobError(404, "not_found", "검토할 장면을 찾을 수 없습니다.")
            path = self._reviews_path(job_id)
            stored = self._read_reviews(path, job_id, event_ids)
            entry = SceneReview(event_id=event_id, review=review, updated_at=datetime.now(UTC))
            by_event = {item.event_id: item for item in stored.reviews}
            by_event[event_id] = entry
            stored.reviews = sorted(by_event.values(), key=lambda item: item.event_id)
            try:
                write_json_atomic(path, stored.model_dump(mode="json"))
            except OSError as error:
                logger.exception("검토 파일 저장 실패: %s", job_id)
                raise JobError(500, "review_save_failed", "검토 결과를 저장할 수 없습니다.") from error
            return entry

    def _load_results(self, job_id: UUID, *, verify_files: bool) -> AnalysisResults:
        directory = contained_path(self.settings.analysis_root, str(job_id))
        summary = json.loads(contained_path(directory, "summary.json").read_text(encoding="utf-8"))
        events = json.loads(contained_path(directory, "events.json").read_text(encoding="utf-8"))
        public_events = []
        for event in events:
            scene = Scene(**{key: event[key] for key in Scene.model_fields if key != "image_url"},
                          image_url=f"/api/jobs/{job_id}/scenes/{event['event_id']}")
            if (scene.class_name != CLASSES[scene.class_id]
                    or not scene.start_time_sec <= scene.representative_time_sec <= scene.last_detection_time_sec
                    or scene.last_detection_time_sec - scene.start_time_sec > self.settings.max_event_duration + 1e-9
                    or scene.detected_frame_count > scene.detection_count
                    or event["representative_image"] != f"scenes/{scene.event_id}.jpg"):
                raise ValueError("Invalid event metadata")
            if verify_files:
                path = contained_path(directory, "scenes", f"{scene.event_id}.jpg")
                image = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
                if image is None:
                    raise ValueError("Invalid scene JPEG")
            public_events.append(scene)
        video = summary["video"]
        # 클라이언트용 설정에는 경로를 담을 수 있는 임의 키를 전달하지 않는다.
        setting_keys = ("interval_sec", "max_gap_sec", "max_event_duration_sec", "imgsz", "iou", "rect", "max_det",
                        "batch", "quantize", "classes", "agnostic_nms", "augment", "tile", "nms", "conf", "device")
        settings = {key: summary["settings"][key] for key in setting_keys}
        results = AnalysisResults(
            job_id=job_id, video=VideoInfo(**{key: video[key] for key in ("fps", "width", "height", "frame_count")},
                                         duration_sec=summary["video_duration_sec"]),
            video_url=f"/api/jobs/{job_id}/video", extracted_frame_count=video["extracted_frame_count"],
            inferred_frame_count=summary["inferred_frame_count"], detected_frame_count=summary["detected_frame_count"],
            detection_count=summary["detection_count"], event_count=summary["event_count"],
            analysis_seconds=summary["analysis_seconds"], profile=summary["profile"], model_sha256=summary["model"]["sha256"],
            settings=settings, timestamp_basis=summary["timestamp_basis"], events=public_events,
        )
        if (summary["run_name"] != str(job_id) or results.model_sha256 != MVP_SHA256
                or results.event_count != len(events)
                or len({event.event_id for event in public_events}) != len(events)
                or results.detection_count != sum(event.detection_count for event in public_events)
                or results.extracted_frame_count != results.inferred_frame_count
                or results.detected_frame_count > results.inferred_frame_count
                or settings["max_event_duration_sec"] != self.settings.max_event_duration):
            raise ValueError("Inconsistent analysis results")
        if verify_files:
            with contained_path(directory, "detections.csv").open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames or "frame_index" not in reader.fieldnames:
                    raise ValueError("Invalid detections CSV")
                rows = list(reader)
            if len(rows) != results.detection_count or len({row["frame_index"] for row in rows}) != results.detected_frame_count:
                raise ValueError("Incomplete detections CSV")
        return results
