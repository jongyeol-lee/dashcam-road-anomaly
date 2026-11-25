from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue


JobState = Literal["queued", "running", "completed", "failed"]


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


class VideoInfo(ResponseModel):
    fps: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    frame_count: int = Field(ge=0)
    duration_sec: float | None = Field(default=None, ge=0)


class Scene(ResponseModel):
    event_id: str = Field(pattern=r"^event_[0-9]{4,}$")
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
