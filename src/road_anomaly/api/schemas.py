import re
import unicodedata
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, JsonValue, field_validator


JobState = Literal["queued", "running", "completed", "failed"]
ReviewState = Literal["unreviewed", "suspected", "false_positive", "deferred"]
EVENT_ID_PATTERN = r"^event_[0-9]{4,}$"
MAX_FILENAME_LENGTH = 255


def normalize_upload_filename(filename: str) -> str:
    """Windows와 POSIX 경로를 제거하고 화면에 표시할 이름만 남긴다."""
    leaf = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(char for char in leaf if unicodedata.category(char) not in {"Cc", "Cf", "Cs"}).strip()
    name = re.sub(r"^(?:[A-Za-z]:\s*)+", "", name)
    if len(name) > MAX_FILENAME_LENGTH:
        # 유효한 MP4 파일명의 확장자를 보존한다.
        name = name[:MAX_FILENAME_LENGTH - 4] + name[-4:]
    return name


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ApiError(ResponseModel):
    code: str
    message: str


class ErrorResponse(ResponseModel):
    error: ApiError


class JobStatus(ResponseModel):
    job_id: UUID
    status: JobState
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: ApiError | None = None


class JobDetail(JobStatus):
    original_filename: str | None = Field(default=None, max_length=MAX_FILENAME_LENGTH)

    @field_validator("original_filename")
    @classmethod
    def validate_original_filename(cls, value: str | None) -> str | None:
        if value is not None and (not value or value != normalize_upload_filename(value)):
            raise ValueError("Invalid stored upload filename")
        return value


class StoredJob(JobDetail):
    file_size_bytes: int | None = Field(default=None, ge=0)

    def to_storage(self) -> dict:
        # 파일 정보 없이 생성된 작업은 상태를 갱신해도 기존 키 구성을 유지한다.
        absent = {name for name in ("original_filename", "file_size_bytes") if getattr(self, name) is None}
        return self.model_dump(mode="json", exclude=absent)


class VideoInfo(ResponseModel):
    fps: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    frame_count: int = Field(ge=0)
    duration_sec: float | None = Field(default=None, ge=0)


class Scene(ResponseModel):
    event_id: str = Field(pattern=EVENT_ID_PATTERN)
    class_id: int = Field(ge=0, le=3)
    class_name: Literal["D00", "D10", "D20", "D40"]
    start_time_sec: float = Field(ge=0)
    last_detection_time_sec: float = Field(ge=0)
    representative_time_sec: float = Field(ge=0)
    representative_frame_index: int = Field(ge=0)
    representative_xyxy: tuple[float, float, float, float]
    max_confidence: float = Field(ge=0, le=1)
    detection_count: int = Field(gt=0)
    detected_frame_count: int = Field(gt=0)
    image_url: str


class AnalysisResults(ResponseModel):
    job_id: UUID
    status: Literal["completed"] = "completed"
    video: VideoInfo
    video_url: str
    extracted_frame_count: int = Field(gt=0)
    inferred_frame_count: int = Field(gt=0)
    detected_frame_count: int = Field(ge=0)
    detection_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    analysis_seconds: float = Field(ge=0)
    profile: Literal["mvp"]
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    settings: dict[str, JsonValue]
    timestamp_basis: str
    events: list[Scene]


class ResultDetail(AnalysisResults):
    original_filename: str | None = Field(default=None, max_length=MAX_FILENAME_LENGTH)


class ReviewUpdate(ResponseModel):
    review: ReviewState


class SceneReview(ReviewUpdate):
    event_id: str = Field(pattern=EVENT_ID_PATTERN)
    updated_at: AwareDatetime


class JobReviews(ResponseModel):
    job_id: UUID
    reviews: list[SceneReview]


class JobHistoryQuery(ResponseModel):
    status: JobState | None = None
    search: str | None = Field(default=None, max_length=MAX_FILENAME_LENGTH)
    sort: Literal["newest", "oldest"] = "newest"
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class JobAnalysisSummary(ResponseModel):
    video: VideoInfo
    event_count: int = Field(ge=0)
    analysis_seconds: float = Field(ge=0)


class ReviewSummary(ResponseModel):
    unreviewed: int = Field(ge=0)
    suspected: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    deferred: int = Field(ge=0)
    reviewed_count: int = Field(ge=0)


REPORT_SETTING_FIELDS = ("imgsz", "conf", "iou", "interval_sec", "max_gap_sec", "max_event_duration_sec")


class JobReport(ResponseModel):
    job: StoredJob
    results: AnalysisResults
    reviews: JobReviews
    review_summary: ReviewSummary
    exported_at: AwareDatetime


class JobHistoryItem(StoredJob):
    analysis: JobAnalysisSummary | None = None
    reviews: ReviewSummary | None = None


class JobHistoryWarning(ResponseModel):
    job_id: UUID
    error: ApiError


class JobHistory(ResponseModel):
    items: list[JobHistoryItem]
    total: int = Field(ge=0)
    count: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)
    warnings: list[JobHistoryWarning]
