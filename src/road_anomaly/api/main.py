import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import FastAPI, File, Path as PathParameter, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from .jobs import ApiSettings, JobError, JobManager, contained_path, validate_upload
from .schemas import (
    AnalysisResults, ErrorResponse, EVENT_ID_PATTERN, JobHistory, JobHistoryQuery, JobReviews, JobStatus,
    ReviewUpdate, SceneReview, normalize_upload_filename,
)


logger = logging.getLogger(__name__)


class JsonErrorMiddleware:
    """본문 제한과 FileResponse가 직접 만드는 오류도 API의 JSON 형식으로 통일한다."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        replaced = False

        async def send_json_error(message):
            nonlocal replaced
            if message["type"] == "http.response.start" and message["status"] >= 400:
                headers = dict(message.get("headers", []))
                if b"application/json" not in headers.get(b"content-type", b""):
                    status = message["status"]
                    codes = {400: "invalid_request", 404: "not_found", 413: "upload_too_large", 416: "invalid_range"}
                    response = JSONResponse(status_code=status,
                                            content={"error": {"code": codes.get(status, "http_error"),
                                                               "message": "요청을 처리할 수 없습니다."}},
                                            headers={key.decode(): value.decode() for key, value in headers.items()
                                                     if key in (b"content-range", b"allow")})
                    await response(scope, receive, send)
                    replaced = True
            if not replaced:
                await send(message)

        await self.app(scope, receive, send_json_error)


def create_app(settings: ApiSettings | None = None, *, analyzer=None) -> FastAPI:
    """서버 설정과 테스트용 분석 함수를 주입할 수 있는 로컬 MVP 앱을 생성한다."""
    settings = settings or ApiSettings()
    manager = JobManager(settings) if analyzer is None else JobManager(settings, analyzer)

    @asynccontextmanager
    async def lifespan(app):
        # 설정 디렉터리는 프로세스 수명 동안 유지한다. YOLO import보다 먼저 적용한다.
        with TemporaryDirectory(prefix="road-anomaly-api-") as config:
            values = dict(YOLO_CONFIG_DIR=config, MPLCONFIGDIR=config, YOLO_OFFLINE="true", YOLO_AUTOINSTALL="false")
            previous = {key: os.environ.get(key) for key in values}
            os.environ.update(values)
            try:
                await run_in_threadpool(manager.start)
                try:
                    yield
                finally:
                    await run_in_threadpool(manager.stop)
            finally:
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    app = FastAPI(
        title="Dashcam Road Anomaly API", version="0.1.0", lifespan=lifespan,
        form_limits={"max_files": 1, "max_fields": 0},
        responses={code: {"model": ErrorResponse} for code in (400, 404, 409, 413, 415, 422, 500)},
    )
    app.state.jobs = manager
    app.add_middleware(JsonErrorMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["GET", "POST", "HEAD", "PUT"], allow_headers=["Content-Type", "Range"],
                       expose_headers=["Accept-Ranges", "Content-Range", "Content-Length"])

    @app.exception_handler(JobError)
    async def job_error(request, error):
        return JSONResponse(status_code=error.status_code, content={"error": error.error.model_dump()})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_request", "message": "요청 형식을 확인해 주세요."}})

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        codes = {400: "invalid_request", 404: "not_found", 413: "upload_too_large", 416: "invalid_range"}
        return JSONResponse(status_code=error.status_code, headers=error.headers,
                            content={"error": {"code": codes.get(error.status_code, "http_error"),
                                               "message": "요청을 처리할 수 없습니다."}})

    @app.exception_handler(Exception)
    async def unexpected_error(request, error):
        logger.exception("API 요청 처리 실패")
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "서버 처리 중 오류가 발생했습니다."}})

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    # 경로 단위 제한은 JSON 오류 미들웨어 안에서 실행되어 413 형식도 동일하다.
    @app.post("/api/jobs", status_code=202, response_model=JobStatus,
              max_body_size=settings.max_upload_bytes + 64 * 1024)
    def upload(file: Annotated[UploadFile, File(description="MP4 video, maximum 200 MiB by default")]):
        directory = None
        committed = False
        try:
            filename = normalize_upload_filename(file.filename or "")
            if Path(filename).suffix.lower() != ".mp4":
                raise JobError(415, "unsupported_file_type", "MP4 파일만 업로드할 수 있습니다.")
            if file.size is not None and file.size > settings.max_upload_bytes:
                raise JobError(413, "upload_too_large", "업로드 파일 크기 제한을 초과했습니다.")
            job_id = uuid4()
            destination = contained_path(settings.uploads_root, str(job_id))
            destination.mkdir(parents=True)
            # 독점 생성에 성공한 뒤에만 실패 정리 대상으로 등록한다.
            directory = destination
            partial = directory / "input.part"
            size = 0
            with partial.open("xb") as handle:
                while chunk := file.file.read(settings.upload_chunk_bytes):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise JobError(413, "upload_too_large", "업로드 파일 크기 제한을 초과했습니다.")
                    handle.write(chunk)
            if size == 0:
                raise JobError(422, "empty_file", "빈 파일은 업로드할 수 없습니다.")
            validate_upload(partial)
            stored_size = partial.rename(directory / "input.mp4").stat().st_size
            job = manager.submit(job_id, original_filename=filename, file_size_bytes=stored_size)
            committed = True
            return job
        finally:
            file.file.close()
            if directory is not None and not committed:
                # 이 요청에서 독점 생성한 고정 이름 파일만 정리한다.
                for name in ("input.part", "input.mp4"):
                    (directory / name).unlink(missing_ok=True)
                directory.rmdir()

    @app.get("/api/jobs", response_model=JobHistory)
    def job_history(query: Annotated[JobHistoryQuery, Query()]):
        """저장된 분석 작업과 페이지에 포함된 작업의 검토 요약을 조회한다."""
        return manager.list_history(query)

    @app.get("/api/jobs/{job_id}", response_model=JobStatus)
    def job_status(job_id: UUID):
        return manager.get(job_id)

    @app.get("/api/jobs/{job_id}/results", response_model=AnalysisResults)
    def results(job_id: UUID):
        return manager.results(job_id)

    @app.get("/api/jobs/{job_id}/reviews", response_model=JobReviews)
    def reviews(job_id: UUID):
        return manager.reviews(job_id)

    @app.put("/api/jobs/{job_id}/reviews/{event_id}", response_model=SceneReview)
    def save_review(job_id: UUID, event_id: Annotated[str, PathParameter(pattern=EVENT_ID_PATTERN)], update: ReviewUpdate):
        return manager.set_review(job_id, event_id, update.review)

    @app.head("/api/jobs/{job_id}/video", response_class=FileResponse, include_in_schema=False)
    @app.get("/api/jobs/{job_id}/video", response_class=FileResponse)
    def video(job_id: UUID):
        manager.get(job_id)
        path = manager.video_path(job_id)
        if not path.is_file():
            raise JobError(404, "not_found", "원본 영상을 찾을 수 없습니다.")
        return FileResponse(path, media_type="video/mp4")

    @app.get("/api/jobs/{job_id}/scenes/{event_id}", response_class=FileResponse)
    def scene(job_id: UUID, event_id: str):
        if not re.fullmatch(EVENT_ID_PATTERN, event_id):
            raise JobError(422, "invalid_request", "대표 이미지 ID를 확인해 주세요.")
        path = manager.scene_path(job_id, event_id)
        if not path.is_file():
            raise JobError(404, "not_found", "대표 이미지를 찾을 수 없습니다.")
        return FileResponse(path, media_type="image/jpeg")

    return app


app = create_app()
