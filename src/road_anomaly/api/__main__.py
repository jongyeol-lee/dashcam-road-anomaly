"""프로젝트의 로컬 단일 워커 API 서버를 시작한다."""

import sys

import uvicorn
from fastapi import FastAPI

from .jobs import JobManager
from .main import app as default_app


WINDOWS_HTTP_SHUTDOWN_TIMEOUT = 3


class _WindowsServer(uvicorn.Server):
    def __init__(self, config: uvicorn.Config, jobs: JobManager):
        super().__init__(config)
        self.jobs = jobs

    async def shutdown(self, sockets=None) -> None:
        # HTTP 응답을 기다리는 동안 대기 작업이 시작되지 않도록 먼저 큐를 닫는다.
        self.jobs.begin_shutdown()
        await super().shutdown(sockets=sockets)


def create_server(app: FastAPI = default_app, *, port: int = 8000) -> uvicorn.Server:
    windows = sys.platform == "win32"
    # Windows에서는 연결 정리에 문제가 재현된 Proactor 대신 서버 전용 Selector를 사용한다.
    # HTTP 제한은 Uvicorn의 연결과 요청에 적용되며 FastAPI의 GPU 워커 종료 대기는 포함하지 않는다.
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        workers=1,
        loop="asyncio:SelectorEventLoop" if windows else "auto",
        timeout_graceful_shutdown=WINDOWS_HTTP_SHUTDOWN_TIMEOUT if windows else None,
    )
    return _WindowsServer(config, app.state.jobs) if windows else uvicorn.Server(config)


if __name__ == "__main__":
    create_server().run()
