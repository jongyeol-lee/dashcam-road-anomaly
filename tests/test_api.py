import csv
import io
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic, sleep
from unittest.mock import patch
from uuid import UUID, uuid4

import cv2
import numpy as np
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from scripts.make_test_video import make_test_video
from src.road_anomaly.api.jobs import ApiSettings, JobManager, write_json_atomic
from src.road_anomaly.api.main import create_app
from src.road_anomaly.api.schemas import JobStatus
from src.road_anomaly.video_analysis import DETECTION_COLUMNS, MVP_SHA256, PROFILES


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.mp4 = make_test_video(Path(temp.name) / "sample.mp4").read_bytes()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.settings = ApiSettings(project_root=self.root)
        self.empty = False
        self.calls = []

    def analyze(self, video, **options):
        self.calls.append((video, options))
        job_id = options["run_name"]
        directory = options["analysis_root"] / job_id
        directory.mkdir(parents=True)
        (directory / "scenes").mkdir()
        settings = dict(PROFILES["mvp"]["predict"], interval_sec=0.5, max_gap_sec=1.5,
                        max_event_duration_sec=options["max_event_duration"], conf=0.05, device="cuda:0")
        events = [] if self.empty else [{
            "event_id": "event_0001", "class_id": 2, "class_name": "D20", "start_time_sec": 0.5,
            "last_detection_time_sec": 1.5, "representative_time_sec": 1.0, "representative_frame_index": 10,
            "representative_xyxy": [10, 20, 50, 60], "max_confidence": 0.7,
            "detection_count": 3, "detected_frame_count": 3, "representative_image": "scenes/event_0001.jpg",
        }]
        summary = {
            "run_name": job_id, "profile": "mvp", "video": {"path": str(video), "fps": 10, "width": 320,
            "height": 180, "frame_count": 30, "extracted_frame_count": 6},
            "video_duration_sec": 3, "inferred_frame_count": 6, "detected_frame_count": 0 if self.empty else 3,
            "detection_count": 0 if self.empty else 3, "event_count": len(events), "analysis_seconds": 0.2,
            "model": {"path": str(self.root / "secret/best.pt"), "sha256": MVP_SHA256},
            "settings": settings, "timestamp_basis": "frame_index / fps",
        }
        (directory / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (directory / "events.json").write_text(json.dumps(events), encoding="utf-8")
        with (directory / "detections.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(DETECTION_COLUMNS)
            if not self.empty:
                writer.writerows((index, index / 10, 2, "D20", 0.7, 10, 20, 50, 60, "private.jpg") for index in (5, 10, 15))
        if not self.empty:
            success, jpeg = cv2.imencode(".jpg", np.zeros((180, 320, 3), np.uint8))
            self.assertTrue(success)
            (directory / "scenes/event_0001.jpg").write_bytes(jpeg.tobytes())
        return summary

    def client(self, analyzer=None, settings=None, **options):
        return TestClient(create_app(settings or self.settings, analyzer=analyzer or self.analyze), **options)

    def upload(self, client, data=None, filename="sample.mp4"):
        response = client.post("/api/jobs", files={"file": (filename, self.mp4 if data is None else data, "video/mp4")})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["status"], "queued")
        return response.json()["job_id"]

    def wait(self, client, job_id, status="completed"):
        deadline = monotonic() + 8
        while monotonic() < deadline:
            response = client.get(f"/api/jobs/{job_id}")
            self.assertEqual(response.status_code, 200, response.text)
            job = response.json()
            if job["status"] == status:
                return job
            if job["status"] == "failed" and status != "failed":
                self.fail(str(job))
            sleep(0.01)
        self.fail(f"Timed out waiting for {status}: {job}")

    def assert_error(self, response, status, code):
        self.assertEqual(response.status_code, status, response.text)
        self.assertEqual(response.json()["error"]["code"], code)
        self.assertNotIn(str(self.root), response.text)
        self.assertEqual(set(response.json()), {"error"})

    def test_health_contract_and_local_cors(self):
        with self.client() as client:
            self.assertEqual(client.get("/api/health").json(), {"status": "ok"})
            schema = client.get("/openapi.json").json()
            self.assertIn("/api/jobs/{job_id}/scenes/{event_id}", schema["paths"])
            self.assertIn("202", schema["paths"]["/api/jobs"]["post"]["responses"])
            for origin, allowed in (("http://localhost:5173", True), ("https://example.org", False)):
                response = client.get("/api/health", headers={"Origin": origin})
                self.assertEqual("access-control-allow-origin" in response.headers, allowed)

    def test_completed_results_and_jpeg_do_not_expose_local_paths(self):
        with self.client() as client:
            job_id = self.upload(client, filename="../../unsafe.mp4")
            UUID(job_id)
            job = self.wait(client, job_id)
            self.assertLessEqual(job["created_at"], job["started_at"])
            self.assertLessEqual(job["started_at"], job["finished_at"])
            response = client.get(f"/api/jobs/{job_id}/results")
            self.assertEqual(response.status_code, 200, response.text)
            results = response.json()
            self.assertEqual((results["extracted_frame_count"], results["inferred_frame_count"], results["detection_count"]), (6, 6, 3))
            self.assertEqual(results["settings"]["max_event_duration_sec"], 5)
            self.assertNotIn(str(self.root), response.text)
            self.assertNotIn("best.pt", response.text)
            self.assertNotIn("path", results["video"])
            image = client.get(results["events"][0]["image_url"])
            self.assertEqual(image.headers["content-type"], "image/jpeg")
            self.assertIsNotNone(cv2.imdecode(np.frombuffer(image.content, dtype=np.uint8), cv2.IMREAD_COLOR))
            self.assertEqual(self.calls[0][1]["profile"], "mvp")
            self.assertEqual(self.calls[0][0], self.settings.uploads_root / job_id / "input.mp4")
            self.assertEqual(list((self.settings.uploads_root / job_id).iterdir()), [self.calls[0][0]])

    def test_running_status_is_available_and_jobs_are_serialized(self):
        entered, release, guard = Event(), Event(), Lock()
        active, maximum = 0, 0

        def blocking(video, **options):
            nonlocal active, maximum
            with guard:
                active += 1
                maximum = max(maximum, active)
            entered.set()
            if not release.wait(8):
                raise RuntimeError("Test synchronization timed out")
            try:
                return self.analyze(video, **options)
            finally:
                with guard:
                    active -= 1

        with self.client(blocking) as client:
            try:
                first = self.upload(client)
                self.assertTrue(entered.wait(4))
                second = self.upload(client)
                self.assertEqual(client.get(f"/api/jobs/{first}").json()["status"], "running")
                self.assertEqual(client.get(f"/api/jobs/{second}").json()["status"], "queued")
                self.assert_error(client.get(f"/api/jobs/{second}/results"), 409, "results_not_ready")
                self.assertEqual(client.get("/api/health").status_code, 200)
            finally:
                release.set()
            self.wait(client, first)
            self.wait(client, second)
        self.assertEqual(maximum, 1)
        self.assertEqual(len(self.calls), 2)

    def test_analysis_failure_does_not_stop_next_job_or_leak_details(self):
        attempt = 0

        def fail_once(video, **options):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                raise RuntimeError(f"sensitive model path: {self.root}/secret.pt")
            return self.analyze(video, **options)

        with self.client(fail_once) as client:
            with self.assertLogs("src.road_anomaly.api.jobs", level="ERROR"):
                failed = self.upload(client)
                job = self.wait(client, failed, "failed")
            self.assertEqual(job["error"]["code"], "analysis_failed")
            self.assertNotIn("secret.pt", json.dumps(job))
            self.assertIsNotNone(job["finished_at"])
            self.assert_error(client.get(f"/api/jobs/{failed}/results"), 409, "results_not_ready")
            next_job = self.upload(client)
            self.wait(client, next_job)

    def test_invalid_uploads_leave_no_partial_files(self):
        with self.client() as client:
            for name, data, status, code in (("sample.avi", self.mp4, 415, "unsupported_file_type"),
                                              ("sample.mp4", b"", 422, "empty_file"),
                                              ("sample.mp4", b"broken", 422, "invalid_video"),
                                              ("sample.mp4", self.mp4[:len(self.mp4) // 2], 422, "invalid_video")):
                with self.subTest(name=name, size=len(data)):
                    response = client.post("/api/jobs", files={"file": (name, data, "video/mp4")})
                    self.assert_error(response, status, code)
            self.assertEqual(list(self.settings.uploads_root.glob("*")), [])
            self.assertEqual(list(self.settings.jobs_root.glob("*/job.json")), [])
            self.assertEqual(self.calls, [])

    def test_file_limit_and_total_body_limit_including_chunked_requests(self):
        with self.client(settings=replace(self.settings, max_upload_bytes=64)) as client:
            self.assert_error(client.post("/api/jobs", files={"file": ("x.mp4", b"x" * 65)}), 413, "upload_too_large")
            body = b"x" * (65 * 1024)
            self.assert_error(client.post("/api/jobs", content=body, headers={"Content-Type": "multipart/form-data; boundary=x"}),
                              413, "upload_too_large")
            self.assert_error(client.post("/api/jobs", content=iter([body[:100], body[100:]]),
                                          headers={"Content-Type": "multipart/form-data; boundary=x"}), 413, "upload_too_large")
            self.assertEqual(list(self.settings.uploads_root.glob("*")), [])

    def test_chunk_copy_enforces_limit_and_cleans_partial_file(self):
        # 실제 수신 크기 메타데이터를 신뢰하지 않는 두 번째 제한도 확인한다.
        with self.client(settings=replace(self.settings, max_upload_bytes=7, upload_chunk_bytes=4)) as client:
            endpoint = next(route.endpoint for route in client.app.routes if getattr(route, "path", None) == "/api/jobs")
            upload = UploadFile(file=io.BytesIO(b"12345678"), filename="x.mp4", size=None)
            from src.road_anomaly.api.jobs import JobError
            with self.assertRaises(JobError) as error:
                endpoint(upload)
            self.assertEqual(error.exception.status_code, 413)
            self.assertTrue(upload.file.closed)
            self.assertEqual(list(self.settings.uploads_root.iterdir()), [])

    def test_existing_upload_directory_is_never_cleaned_on_uuid_collision(self):
        with self.client(raise_server_exceptions=False) as client:
            job_id = self.upload(client)
            self.wait(client, job_id)
            with (patch("src.road_anomaly.api.main.uuid4", return_value=UUID(job_id)),
                  self.assertLogs("src.road_anomaly.api.main", level="ERROR")):
                response = client.post("/api/jobs", files={"file": ("x.mp4", b"replacement")})
            self.assert_error(response, 500, "internal_error")
            self.assertEqual(client.get(f"/api/jobs/{job_id}/video").content, self.mp4)
            self.assertEqual(client.get(f"/api/jobs/{job_id}").json()["status"], "completed")

    def test_missing_file_extra_fields_and_multiple_files(self):
        with self.client() as client:
            self.assert_error(client.post("/api/jobs"), 422, "invalid_request")
            self.assert_error(client.post("/api/jobs", files={"file": ("x.mp4", self.mp4)}, data={"model_path": "secret.pt"}),
                              400, "invalid_request")
            self.assert_error(client.post("/api/jobs", files=[("file", ("a.mp4", self.mp4)), ("file", ("b.mp4", self.mp4))]),
                              400, "invalid_request")
            self.assertEqual(self.calls, [])

    def test_video_range_head_suffix_and_unsatisfiable_range(self):
        with self.client() as client:
            job_id = self.upload(client)
            url = f"/api/jobs/{job_id}/video"
            full = client.get(url)
            self.assertEqual(full.content, self.mp4)
            self.assertEqual(full.headers["content-type"], "video/mp4")
            for value, expected in (("bytes=0-15", self.mp4[:16]), ("bytes=-8", self.mp4[-8:]), ("bytes=16-", self.mp4[16:])):
                response = client.get(url, headers={"Range": value})
                self.assertEqual(response.status_code, 206)
                self.assertEqual(response.content, expected)
                self.assertEqual(response.headers["accept-ranges"], "bytes")
                self.assertIn(f"/{len(self.mp4)}", response.headers["content-range"])
            head = client.head(url)
            self.assertEqual(head.content, b"")
            self.assertEqual(int(head.headers["content-length"]), len(self.mp4))
            invalid = client.get(url, headers={"Range": f"bytes={len(self.mp4)}-"})
            self.assert_error(invalid, 416, "invalid_range")
            self.assertEqual(invalid.headers["content-range"], f"bytes */{len(self.mp4)}")
            self.assert_error(client.get(url, headers={"Range": "bytes=garbage"}), 400, "invalid_request")

    def test_empty_detection_results(self):
        self.empty = True
        with self.client() as client:
            job_id = self.upload(client)
            self.wait(client, job_id)
            results = client.get(f"/api/jobs/{job_id}/results").json()
            self.assertEqual((results["events"], results["detection_count"], results["event_count"]), ([], 0, 0))
            self.assert_error(client.get(f"/api/jobs/{job_id}/scenes/event_0001"), 404, "not_found")

    def test_unknown_ids_and_arbitrary_path_requests(self):
        with self.client() as client:
            for suffix in ("", "/results", "/video", "/scenes/event_0001"):
                self.assert_error(client.get(f"/api/jobs/{uuid4()}{suffix}"), 404, "not_found")
                self.assert_error(client.get(f"/api/jobs/not-a-uuid{suffix}"), 422, "invalid_request")
            for path in ("/data/raw/input.mp4", "/outputs/jobs/anything/job.json", "/api/jobs/%2e%2e%5csecret/video"):
                self.assertIn(client.get(path).status_code, (404, 422))
            job_id = self.upload(client)
            self.wait(client, job_id)
            for event_id in ("../summary.json", "%2e%2e%5csummary.json", "event_0001.jpg", "summary"):
                self.assertIn(client.get(f"/api/jobs/{job_id}/scenes/{event_id}").status_code, (404, 422))
            self.assert_error(client.get(f"/api/jobs/{job_id}/scenes/event_9999"), 404, "not_found")

    def test_redirected_paths_cannot_serve_other_jobs(self):
        with self.client() as client:
            first, second = self.upload(client), self.upload(client)
            self.wait(client, first)
            self.wait(client, second)
            original = self.settings.uploads_root / first / "input.mp4"
            target = self.settings.uploads_root / second / "input.mp4"
            resolve = Path.resolve

            def redirected(path, *args, **kwargs):
                # Windows의 링크 생성 권한 없이도 junction/symlink 해석 결과를 검증한다.
                return target if path == original else resolve(path, *args, **kwargs)

            with patch.object(Path, "resolve", redirected):
                self.assert_error(client.get(f"/api/jobs/{first}/video"), 404, "not_found")

    def test_output_validation_fails_before_completed_and_next_job_runs(self):
        attempt = 0

        def missing_jpeg(video, **options):
            nonlocal attempt
            attempt += 1
            result = self.analyze(video, **options)
            if attempt == 1:
                (options["analysis_root"] / options["run_name"] / "scenes/event_0001.jpg").unlink()
            return result

        with self.client(missing_jpeg) as client:
            with self.assertLogs("src.road_anomaly.api.jobs", level="ERROR"):
                first = self.upload(client)
                self.wait(client, first, "failed")
            self.assertFalse((self.settings.jobs_root / first / "results.json").exists())
            second = self.upload(client)
            self.wait(client, second)

    def test_restart_keeps_completed_results_and_fails_interrupted_jobs(self):
        with self.client() as client:
            completed = self.upload(client)
            self.wait(client, completed)
            before = client.get(f"/api/jobs/{completed}/results").json()
        interrupted = []
        for state in ("queued", "running"):
            job_id = uuid4()
            interrupted.append(str(job_id))
            directory = self.settings.jobs_root / str(job_id)
            directory.mkdir()
            job = JobStatus(job_id=job_id, status=state, created_at=datetime.now(UTC))
            write_json_atomic(directory / "job.json", job.model_dump(mode="json"))
        with self.client() as client:
            self.assertEqual(client.get(f"/api/jobs/{completed}/results").json(), before)
            self.assertEqual(client.get(before["events"][0]["image_url"]).status_code, 200)
            for job_id in interrupted:
                job = client.get(f"/api/jobs/{job_id}").json()
                self.assertEqual(job["status"], "failed")
                self.assertEqual(job["error"]["code"], "interrupted")
                self.assertIsNotNone(job["finished_at"])
        self.assertEqual(len(self.calls), 1)

    def test_duplicate_worker_is_rejected_without_recovering_running_jobs(self):
        first = JobManager(self.settings, self.analyze)
        second = JobManager(self.settings, self.analyze)
        first.start()
        try:
            with self.assertRaisesRegex(RuntimeError, "이미 실행 중"):
                second.start()
        finally:
            first.stop()
        second.start()
        second.stop()

    def test_shutdown_finishes_running_job_fails_queue_and_rejects_submission(self):
        entered, release = Event(), Event()

        def blocking(video, **options):
            entered.set()
            if not release.wait(8):
                raise RuntimeError("Test synchronization timed out")
            return self.analyze(video, **options)

        with self.client(blocking) as client:
            first = self.upload(client)
            self.assertTrue(entered.wait(4))
            second = self.upload(client)
            manager = client.app.state.jobs
            shutdown = Thread(target=manager.stop)
            shutdown.start()
            try:
                self.assertTrue(manager._stopping.wait(4))
                self.assert_error(client.post("/api/jobs", files={"file": ("x.mp4", self.mp4)}), 503, "shutting_down")
            finally:
                release.set()
                shutdown.join(8)
            self.assertFalse(shutdown.is_alive())
            self.wait(client, first)
            self.assertEqual(self.wait(client, second, "failed")["error"]["code"], "interrupted")
            self.assertEqual(len(self.calls), 1)
