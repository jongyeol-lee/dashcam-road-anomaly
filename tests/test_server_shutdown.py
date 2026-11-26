import http.client
import re
import socket
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent
from time import monotonic, sleep
from uuid import uuid4

from src.road_anomaly.api.jobs import ApiSettings, write_json_atomic
from src.road_anomaly.api.schemas import JobStatus


@unittest.skipUnless(sys.platform == "win32", "Windows 서버 종료 설정 검증")
class ServerShutdownTest(unittest.TestCase):
    def test_shutdown_bounds_open_range_without_starting_queued_work(self):
        script = dedent("""
            import sys
            from pathlib import Path
            from threading import Thread
            from time import monotonic, sleep
            from uuid import UUID
            from src.road_anomaly.api.__main__ import create_server
            from src.road_anomaly.api.jobs import ApiSettings
            from src.road_anomaly.api.main import create_app
            from src.road_anomaly.api.schemas import AnalysisResults, VideoInfo

            root, active, pending = Path(sys.argv[1]), UUID(sys.argv[2]), UUID(sys.argv[3])
            def analyzer(video, *, run_name, **options):
                (root / ("started-" + run_name)).touch()
                if run_name == str(active):
                    deadline = monotonic() + 15
                    while not (root / "release").exists() and monotonic() < deadline:
                        sleep(0.02)

            app = create_app(ApiSettings(project_root=root), analyzer=analyzer)
            manager = app.state.jobs
            # 분석 산출물 검사만 대역으로 두고 상태 파일·워커·종료 처리는 실제 경로를 사용한다.
            manager._load_results = lambda job_id, **options: AnalysisResults(
                job_id=job_id, video=VideoInfo(fps=30, width=320, height=180, frame_count=30, duration_sec=1),
                video_url=f"/api/jobs/{job_id}/video", extracted_frame_count=2, inferred_frame_count=2,
                detected_frame_count=0, detection_count=0, event_count=0, analysis_seconds=0.1,
                profile="mvp", model_sha256="0" * 64, settings={}, timestamp_basis="frame_index / fps", events=[],
            )
            server = create_server(app, port=0)

            def request_shutdown():
                sys.stdin.readline()
                manager.submit(active)
                manager.submit(pending)
                sys.stdin.readline()
                server.should_exit = True

            Thread(target=request_shutdown, daemon=True).start()
            server.run()
        """)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = ApiSettings(project_root=root)
            now = datetime.now(UTC)
            job = JobStatus(job_id=uuid4(), status="completed", created_at=now, started_at=now, finished_at=now)
            metadata = settings.jobs_root / str(job.job_id) / "job.json"
            metadata.parent.mkdir(parents=True)
            # 과거 완료 작업의 디스크 구조를 재현해 영상 응답만 검증한다.
            write_json_atomic(metadata, job.model_dump(mode="json"))
            video = settings.uploads_root / str(job.job_id) / "input.mp4"
            video.parent.mkdir(parents=True)
            # 수신을 멈췄을 때 소켓 버퍼만으로 응답이 완료되지 않는 크기를 사용한다.
            with video.open("wb") as handle:
                handle.truncate(32 * 1024 * 1024)

            active, pending = uuid4(), uuid4()
            log = root / "server.log"
            with log.open("wb") as output, subprocess.Popen(
                [sys.executable, "-B", "-X", "utf8", "-c", script, str(root), str(active), str(pending)],
                cwd=Path(__file__).resolve().parents[1],
                stdin=subprocess.PIPE,
                stdout=output,
                stderr=subprocess.STDOUT,
                text=True,
            ) as process:
                try:
                    deadline = monotonic() + 20
                    while monotonic() < deadline and process.poll() is None:
                        match = re.search(r"Uvicorn running on http://127\.0\.0\.1:(\d+)", log.read_text(encoding="utf-8"))
                        if match:
                            break
                        sleep(0.05)
                    else:
                        self.fail(log.read_text(encoding="utf-8"))

                    process.stdin.write("queue\n")
                    process.stdin.flush()
                    self.wait_for(lambda: (root / f"started-{active}").exists())

                    port = int(match[1])
                    with socket.socket() as client:
                        client.settimeout(5)
                        client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
                        client.connect(("127.0.0.1", port))
                        client.sendall(
                            f"GET /api/jobs/{job.job_id}/video HTTP/1.1\r\n"
                            "Host: localhost\r\nRange: bytes=0-\r\n\r\n".encode("ascii")
                        )
                        with http.client.HTTPResponse(client) as response:
                            response.begin()
                            self.assertEqual(response.status, 206)
                            process.stdin.write("stop\n")
                            process.stdin.flush()
                            self.wait_for(lambda: not self.listening(port))
                            (root / "release").touch()
                            self.assertEqual(process.wait(timeout=9), 0)
                finally:
                    if process.poll() is None:
                        process.kill()

            shutdown_log = log.read_text(encoding="utf-8")
            self.assertIn("timeout graceful shutdown exceeded", shutdown_log)
            self.assertIn("Application shutdown complete.", shutdown_log)
            self.assertNotIn("WinError 10054", shutdown_log)
            active_status = JobStatus.model_validate_json((settings.jobs_root / str(active) / "job.json").read_bytes())
            self.assertEqual(active_status.status, "completed")
            pending_status = JobStatus.model_validate_json((settings.jobs_root / str(pending) / "job.json").read_bytes())
            self.assertEqual(pending_status.status, "failed")
            self.assertEqual(pending_status.error.code, "interrupted")
            self.assertFalse((root / f"started-{pending}").exists())

    @staticmethod
    def listening(port):
        with socket.socket() as client:
            client.settimeout(0.25)
            return client.connect_ex(("127.0.0.1", port)) == 0

    def wait_for(self, condition):
        deadline = monotonic() + 5
        while monotonic() < deadline:
            if condition():
                return
            sleep(0.025)
        self.fail("서버 검증 조건의 대기 시간이 초과됐습니다.")
