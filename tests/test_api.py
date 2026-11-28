import csv
import io
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event, Lock, Thread
from time import monotonic, sleep
from unittest.mock import patch
from uuid import UUID, uuid4

import cv2
import numpy as np
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from starlette.datastructures import UploadFile

from scripts.make_test_video import make_test_video
from src.road_anomaly.api.jobs import ApiSettings, JobManager, write_json_atomic
from src.road_anomaly.api.main import create_app
from src.road_anomaly.api.reports import CSV_COLUMNS, spreadsheet_text
from src.road_anomaly.api.schemas import JobStatus, normalize_upload_filename
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
        self.multiple_events = False
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
        if events and self.multiple_events:
            events.append({**events[0], "event_id": "event_0002", "representative_image": "scenes/event_0002.jpg"})
        summary = {
            "run_name": job_id, "profile": "mvp", "video": {"path": str(video), "fps": 10, "width": 320,
            "height": 180, "frame_count": 30, "extracted_frame_count": 6},
            "video_duration_sec": 3, "inferred_frame_count": 6, "detected_frame_count": 0 if self.empty else 3,
            "detection_count": 3 * len(events), "event_count": len(events), "analysis_seconds": 0.2,
            "model": {"path": str(self.root / "secret/best.pt"), "sha256": MVP_SHA256},
            "settings": settings, "timestamp_basis": "frame_index / fps",
        }
        (directory / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (directory / "events.json").write_text(json.dumps(events), encoding="utf-8")
        with (directory / "detections.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(DETECTION_COLUMNS)
            for _ in events:
                writer.writerows((index, index / 10, 2, "D20", 0.7, 10, 20, 50, 60, "private.jpg") for index in (5, 10, 15))
        if events:
            success, jpeg = cv2.imencode(".jpg", np.zeros((180, 320, 3), np.uint8))
            self.assertTrue(success)
            for event in events:
                (directory / event["representative_image"]).write_bytes(jpeg.tobytes())
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

    def export_rows(self, client, job_id):
        response = client.get(f"/api/jobs/{job_id}/exports/csv")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        self.assertEqual(response.headers["content-disposition"], f'attachment; filename="road-anomaly-{job_id}.csv"')
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertTrue(response.content.startswith(b"\xef\xbb\xbf"))
        reader = csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"), newline=""))
        self.assertEqual(tuple(reader.fieldnames), CSV_COLUMNS)
        return list(reader)

    def export_sheet(self, client, job_id):
        response = client.get(f"/api/jobs/{job_id}/exports/xlsx")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["content-type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertEqual(response.headers["content-disposition"], f'attachment; filename="road-anomaly-{job_id}.xlsx"')
        self.assertEqual(response.headers["cache-control"], "no-store")
        workbook = load_workbook(io.BytesIO(response.content))
        self.addCleanup(workbook.close)
        return workbook.active

    def test_xlsx_preserves_all_scenes_and_saved_reviews_in_readable_cell_types(self):
        self.multiple_events = True
        with self.client() as client:
            job_id = self.upload(client, filename="한글 전방.mp4")
            self.wait(client, job_id)
            client.put(f"/api/jobs/{job_id}/reviews/event_0001", json={"review": "deferred"})
            directory = self.settings.jobs_root / job_id
            path = directory / "results.json"
            results = json.loads(path.read_bytes())
            results["events"][0].update(max_confidence=0.7012345678912, representative_time_sec=1.012345678912,
                                        representative_xyxy=[-0.012345678912, 20.567891234, 51.2, 66.7])
            write_json_atomic(path, results)
            kept = {file: file.read_bytes() for file in directory.glob("*.json")}

            csv_rows = self.export_rows(client, job_id)
            sheet = self.export_sheet(client, job_id)
            self.assertEqual(tuple(cell.value for cell in sheet[1]), CSV_COLUMNS)
            self.assertEqual((sheet.max_row, sheet.max_column), (3, 31))
            self.assertEqual(sheet.freeze_panes, "A2")
            self.assertEqual(sheet.auto_filter.ref, "A1:AE3")
            self.assertTrue(sheet["A1"].alignment.wrap_text)
            self.assertEqual(sheet["A1"].fill.fgColor.rgb, "00244C70")
            self.assertGreater(sheet.column_dimensions["C"].width, sheet.column_dimensions["A"].width)
            self.assertGreater(sheet.column_dimensions["I"].width, sheet.column_dimensions["H"].width)
            self.assertLess(sheet.column_dimensions["X"].width, 32)
            self.assertEqual(sheet["V2"].value, "판단 보류")
            self.assertEqual(sheet["V3"].value, "미검토")
            self.assertIsNone(sheet["W3"].value)
            for cells, csv_row in zip(sheet.iter_rows(min_row=2), csv_rows, strict=True):
                for field, cell in zip(CSV_COLUMNS, cells, strict=True):
                    raw = csv_row[field]
                    if field in {"created_at", "finished_at", "exported_at", "review_updated_at"} and raw:
                        self.assertIsInstance(cell.value, datetime)
                        self.assertIn("KST", cell.number_format)
                        expected = datetime.fromisoformat(raw).replace(tzinfo=None) + timedelta(hours=9)
                        tolerance = 5 if field == "exported_at" else 0.001
                        self.assertLess(abs((cell.value - expected).total_seconds()), tolerance)
                    elif type(cell.value) in {int, float}:
                        self.assertEqual(cell.data_type, "n")
                        self.assertAlmostEqual(cell.value, float(raw), places=12)
                    else:
                        self.assertEqual(cell.value, raw or None)
            self.assertEqual({file: file.read_bytes() for file in kept}, kept)
            self.assertEqual(len(self.calls), 1)

    def test_xlsx_serializes_long_untrusted_filenames_as_text(self):
        with self.client() as client:
            job_id = self.upload(client, filename='=1+2,' + '전방영상' * 48 + '.mp4')
            self.wait(client, job_id)
            saved_name = client.get(f"/api/jobs/{job_id}/report").json()["job"]["original_filename"]
            sheet = self.export_sheet(client, job_id)
            self.assertEqual((sheet["B2"].data_type, sheet["B2"].value), ("s", saved_name))
            self.assertLess(sheet.column_dimensions["B"].width, len(saved_name))
            self.assertEqual(self.export_rows(client, job_id)[0]["original_filename"], "'" + saved_name)

    def test_xlsx_keeps_styled_headers_for_zero_events_and_supports_legacy_metadata(self):
        with self.client() as client:
            job_id = self.upload(client)
            self.wait(client, job_id)
            path = self.settings.jobs_root / job_id / "job.json"
            job = json.loads(path.read_bytes())
            del job["original_filename"], job["file_size_bytes"]
            write_json_atomic(path, dict(job, created_at="2026-11-27T03:46:14.123", finished_at=None))
            sheet = self.export_sheet(client, job_id)
            self.assertIsNone(sheet["B2"].value)
            self.assertEqual(sheet["C2"].value, datetime(2026, 11, 27, 12, 46, 14, 123000))
            self.assertIsNone(sheet["D2"].value)

            self.empty = True
            empty_id = self.upload(client)
            self.wait(client, empty_id)
            empty = self.export_sheet(client, empty_id)
            self.assertEqual(tuple(cell.value for cell in empty[1]), CSV_COLUMNS)
            self.assertEqual((empty.max_row, empty.freeze_panes, empty.auto_filter.ref), (1, "A2", "A1:AE1"))
            self.assertIn("KST", empty["C1"].comment.text)

    def test_job_report_and_csv_use_the_same_data_without_mutating_files(self):
        self.multiple_events = True
        weights = self.root / "model.pt"
        weights.write_bytes(b"model-weight-sentinel")
        with self.client() as client:
            job_id = self.upload(client, filename="한글,전방.mp4")
            status = self.wait(client, job_id)
            result_path = self.settings.jobs_root / job_id / "results.json"
            results = json.loads(result_path.read_text(encoding="utf-8"))
            results["events"][0].update(max_confidence=0.700012345, representative_time_sec=1.023456789,
                                        representative_xyxy=[-0.0001234, 20.56789, 50.123456, 60.789012])
            write_json_atomic(result_path, results)
            kept = {path: path.read_bytes() for path in self.root.rglob("*") if path.suffix in {".json", ".mp4", ".jpg", ".pt"}}

            response = client.get(f"/api/jobs/{job_id}/report")
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers["cache-control"], "no-store")
            report = response.json()
            self.assertEqual(report["results"], results)
            self.assertEqual(report["job"], dict(status, original_filename="한글,전방.mp4", file_size_bytes=len(self.mp4)))
            self.assertEqual(report["reviews"], {"job_id": job_id, "reviews": []})
            self.assertEqual(report["review_summary"], dict(unreviewed=2, suspected=0, false_positive=0, deferred=0, reviewed_count=0))
            rows = self.export_rows(client, job_id)
            self.assertEqual(len(rows), results["event_count"])
            for row, event in zip(rows, results["events"], strict=True):
                self.assertEqual(row["event_id"], event["event_id"])
                self.assertEqual(row["original_filename"], "한글,전방.mp4")
                self.assertEqual(row["class_label"], "거북등 균열")
                self.assertEqual(row["review_label"], "미검토")
                self.assertEqual(row["review_updated_at"], "")
                self.assertEqual(row["model_sha256"], results["model_sha256"])
                for field in ("max_confidence", "start_time_sec", "last_detection_time_sec", "representative_time_sec"):
                    self.assertEqual(float(row[field]), event[field])
                self.assertEqual([float(row[key]) for key in ("x1", "y1", "x2", "y2")], event["representative_xyxy"])
                self.assertEqual(int(row["representative_frame_index"]), event["representative_frame_index"])
                self.assertEqual(datetime.fromisoformat(row["exported_at"]).tzinfo, UTC)
                for key in ("imgsz", "conf", "iou", "interval_sec", "max_gap_sec", "max_event_duration_sec"):
                    self.assertEqual(float(row[key]), results["settings"][key])
            self.assertEqual({path: path.read_bytes() for path in kept}, kept)
            self.assertFalse((result_path.parent / "reviews.json").exists())
            self.assertEqual(len(self.calls), 1)

    def test_report_reflects_each_saved_state_and_isolates_jobs(self):
        self.multiple_events = True
        with self.client() as client:
            job_id = self.upload(client)
            other_id = self.upload(client)
            self.wait(client, job_id)
            self.wait(client, other_id)
            for state, label in (("suspected", "파손 의심"), ("false_positive", "오탐"),
                                 ("deferred", "판단 보류"), ("unreviewed", "미검토")):
                saved = client.put(f"/api/jobs/{job_id}/reviews/event_0001", json={"review": state}).json()
                report = client.get(f"/api/jobs/{job_id}/report").json()
                self.assertEqual(report["reviews"]["reviews"], [saved])
                self.assertEqual(report["review_summary"]["reviewed_count"], int(state != "unreviewed"))
                row, untouched = self.export_rows(client, job_id)
                self.assertEqual((row["review_state"], row["review_label"]), (state, label))
                self.assertEqual(datetime.fromisoformat(row["review_updated_at"]), datetime.fromisoformat(saved["updated_at"]))
                self.assertEqual(untouched["review_state"], "unreviewed")
            other_report = client.get(f"/api/jobs/{other_id}/report").json()
            self.assertEqual(other_report["reviews"]["reviews"], [])
            self.assertEqual(other_report["review_summary"]["unreviewed"], 2)
            self.assertTrue(all(row["job_id"] == other_id and row["review_updated_at"] == "" for row in self.export_rows(client, other_id)))

    def test_report_supports_zero_events_and_legacy_filename(self):
        with self.client() as client:
            job_id = self.upload(client)
            self.wait(client, job_id)
            path = self.settings.jobs_root / job_id / "job.json"
            job = json.loads(path.read_text(encoding="utf-8"))
            del job["original_filename"], job["file_size_bytes"]
            write_json_atomic(path, job)
            report = client.get(f"/api/jobs/{job_id}/report").json()
            self.assertIsNone(report["job"]["original_filename"])
            self.assertIsNone(report["job"]["file_size_bytes"])
            self.assertEqual(self.export_rows(client, job_id)[0]["original_filename"], "")
            self.empty = True
            empty_id = self.upload(client)
            self.wait(client, empty_id)
            empty = client.get(f"/api/jobs/{empty_id}/report").json()
            self.assertEqual(empty["results"]["events"], [])
            self.assertTrue(all(count == 0 for count in empty["review_summary"].values()))
            self.assertEqual(self.export_rows(client, empty_id), [])

    def test_csv_preserves_special_characters_and_escapes_formula_prefixes(self):
        with self.client() as client:
            job_id = self.upload(client)
            self.wait(client, job_id)
            path = self.settings.jobs_root / job_id / "job.json"
            job = json.loads(path.read_text(encoding="utf-8"))
            for name in ('한글,"전방".mp4', '=1+1,한글".mp4', '+한글.mp4', '-한글.mp4', '@한글.mp4', '＝한글.mp4'):
                with self.subTest(name=name):
                    write_json_atomic(path, dict(job, original_filename=name))
                    report = client.get(f"/api/jobs/{job_id}/report").json()
                    self.assertEqual(report["job"]["original_filename"], name)
                    row, = self.export_rows(client, job_id)
                    self.assertEqual(row["original_filename"], name if name.startswith("한글") else "'" + name)
                    self.assertIsNone(row.get(None))
            # 업로드 계약에서 제어문자를 제거하고, CSV 문자열 처리도 선두 제어문자를 방어한다.
            self.assertEqual(normalize_upload_filename("한글\r\n전방.mp4"), "한글전방.mp4")
            for prefix in ("\r", "\n", "\t", " \t="):
                self.assertEqual(spreadsheet_text(prefix + "한글.mp4"), "'" + prefix + "한글.mp4")

    def test_report_rejects_unknown_unfinished_and_inconsistent_jobs(self):
        with self.client() as client:
            job_id = self.upload(client)
            self.wait(client, job_id)
            path = self.settings.jobs_root / job_id / "job.json"
            job = json.loads(path.read_text(encoding="utf-8"))
            for suffix in ("report", "exports/csv", "exports/xlsx"):
                self.assert_error(client.get(f"/api/jobs/not-uuid/{suffix}"), 422, "invalid_request")
                self.assert_error(client.get(f"/api/jobs/{uuid4()}/{suffix}"), 404, "not_found")
                for state in ("queued", "running", "failed"):
                    write_json_atomic(path, dict(job, status=state))
                    self.assert_error(client.get(f"/api/jobs/{job_id}/{suffix}"), 409, "results_not_ready")
                write_json_atomic(path, dict(job, job_id=str(uuid4())))
                self.assert_error(client.get(f"/api/jobs/{job_id}/{suffix}"), 500, "job_data_unavailable")

    def test_report_errors_when_results_or_reviews_cannot_be_read(self):
        with self.client() as client:
            job_id = self.upload(client)
            self.wait(client, job_id)
            directory = self.settings.jobs_root / job_id
            path = directory / "results.json"
            original = path.read_bytes()
            results = json.loads(original)
            results["events"][0]["image_url"] = f"/api/jobs/{uuid4()}/scenes/event_0001"
            for suffix in ("report", "exports/csv", "exports/xlsx"):
                endpoint = f"/api/jobs/{job_id}/{suffix}"
                path.write_text("{", encoding="utf-8")
                self.assert_error(client.get(endpoint), 500, "results_unavailable")
                write_json_atomic(path, results)
                self.assert_error(client.get(endpoint), 500, "results_unavailable")
                path.write_bytes(original)
                invalid_review = directory / "reviews.json"
                invalid_review.write_text("{", encoding="utf-8")
                self.assert_error(client.get(endpoint), 500, "review_data_invalid")
                self.assertEqual(invalid_review.read_bytes(), b"{")
                invalid_review.unlink()
                with patch.object(Path, "read_bytes", side_effect=PermissionError("unreadable review")):
                    self.assert_error(client.get(endpoint), 500, "review_read_failed")

    def test_history_empty(self):
        with self.client() as client:
            self.assertEqual(client.get("/api/jobs").json(), {
                "items": [], "total": 0, "count": 0, "limit": 20, "offset": 0, "warnings": [],
            })

    def test_detail_filename_is_sanitized_and_legacy_jobs_remain_readable(self):
        with self.client() as client:
            job_id = self.upload(client, filename="folder/후방 기록.mp4")
            self.assertEqual(self.wait(client, job_id)["original_filename"], "후방 기록.mp4")
            self.assertEqual(client.get(f"/api/jobs/{job_id}/results").json()["original_filename"], "후방 기록.mp4")
            path = self.settings.jobs_root / job_id / "job.json"
            stored = json.loads(path.read_bytes())
            del stored["original_filename"]
            write_json_atomic(path, stored)
            self.assertIsNone(client.get(f"/api/jobs/{job_id}").json()["original_filename"])
            self.assertEqual(client.get(f"/api/jobs/{job_id}/results").status_code, 200)
            self.assertIsNone(client.get(f"/api/jobs/{job_id}/results").json()["original_filename"])
            self.assertNotIn("original_filename", json.loads(path.read_bytes()))

    def test_history_invalid_queries(self):
        with self.client() as client:
            for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}, {"offset": "x"},
                           {"sort": "latest"}, {"status": "pending"}, {"search": "x" * 256}, {"extra": "x"}):
                with self.subTest(params=params):
                    self.assert_error(client.get("/api/jobs", params=params), 422, "invalid_request")

    def test_history_upload_metadata_and_existing_status_contract(self):
        filename = "전방 영상 (아침)+1.MP4"
        with self.client() as client:
            upload = client.post("/api/jobs", files={"file": (
                f"C:\\개인폴더\\내부/{filename}", self.mp4, "video/mp4",
            )})
            self.assertEqual(upload.status_code, 202, upload.text)
            self.assertEqual(set(upload.json()), set(JobStatus.model_fields))
            job_id = upload.json()["job_id"]
            self.assertEqual(set(self.wait(client, job_id)), set(JobStatus.model_fields) | {"original_filename"})
            path = self.settings.jobs_root / job_id / "job.json"
            disk = json.loads(path.read_bytes())
            row = client.get("/api/jobs", params={"search": "전방 영상"}).json()["items"][0]
            for data in (disk, row):
                self.assertEqual(data["original_filename"], filename)
                self.assertEqual(data["file_size_bytes"], len(self.mp4))
            stored = self.settings.uploads_root / job_id / "input.mp4"
            self.assertEqual(stored.stat().st_size, len(self.mp4))
            self.assertEqual([file.name for file in stored.parent.iterdir()], ["input.mp4"])
            self.assertNotIn("개인폴더", path.read_text(encoding="utf-8"))

    def test_history_filename_controls_drive_and_long_name(self):
        self.assertEqual(normalize_upload_filename("C:\\folder/ C:\x00전방\r\n\t\u202e 한글.mp4"), "전방 한글.mp4")
        name = "가" * 280 + ".MP4"
        expected = "가" * 251 + ".MP4"
        with self.client() as client:
            job_id = self.upload(client, filename=name)
            self.wait(client, job_id)
            row = client.get("/api/jobs").json()["items"][0]
            self.assertEqual(row["original_filename"], expected)
            self.assertEqual(row["file_size_bytes"], len(self.mp4))

    def test_job_metadata_save_failure_cleans_upload_and_job_before_queue(self):
        with self.client(raise_server_exceptions=False) as client:
            with self.assertLogs("src.road_anomaly.api.main", level="ERROR"):
                with patch("src.road_anomaly.api.jobs.write_json_atomic", side_effect=OSError("disk write failed")):
                    response = client.post("/api/jobs", files={"file": ("front.mp4", self.mp4, "video/mp4")})
            self.assert_error(response, 500, "internal_error")
            self.assertEqual(list(self.settings.uploads_root.iterdir()), [])
            self.assertEqual(list(self.settings.jobs_root.iterdir()), [self.settings.jobs_root / ".worker.lock"])
            self.assertEqual(self.calls, [])

    def test_history_legacy_metadata_restart_and_read_only_access(self):
        with self.client() as client:
            first, second = self.upload(client), self.upload(client)
            for job_id in (first, second):
                self.wait(client, job_id)
                path = self.settings.jobs_root / job_id / "job.json"
                job = json.loads(path.read_bytes())
                del job["original_filename"], job["file_size_bytes"]
                write_json_atomic(path, job)
            saved = client.put(f"/api/jobs/{first}/reviews/event_0001", json={"review": "deferred"})
            self.assertEqual(saved.status_code, 200)
            (self.settings.uploads_root / second / "input.mp4").unlink()
            paths = list(self.settings.jobs_root.glob("*/*.json"))
            original = {path: path.read_bytes() for path in paths}
            previous = client.get("/api/jobs").json()
            rows = {item["job_id"]: item for item in previous["items"]}
            self.assertEqual(previous["warnings"], [])
            self.assertIsNone(rows[first]["original_filename"])
            self.assertEqual(rows[first]["file_size_bytes"], len(self.mp4))
            self.assertIsNone(rows[second]["original_filename"])
            self.assertIsNone(rows[second]["file_size_bytes"])
            self.assertEqual(rows[first]["reviews"]["deferred"], 1)
            self.assertEqual(rows[second]["reviews"]["unreviewed"], 1)
            self.assertEqual(client.get("/api/jobs", params={"search": "sample"}).json()["items"], [])
        with self.client() as client:
            self.assertEqual(client.get("/api/jobs").json(), previous)
            self.assertEqual({path: path.read_bytes() for path in self.settings.jobs_root.glob("*/*.json")}, original)
            self.assertEqual(len(self.calls), 2)

    def test_history_states_and_zero_completed_events(self):
        attempted = Event()
        entered = Event()
        release = Event()
        self.empty = True

        def analyzer(video, **options):
            if not attempted.is_set():
                attempted.set()
                raise RuntimeError(f"Internal filename: {video}")
            entered.set()
            if not release.wait(8):
                raise TimeoutError
            return self.analyze(video, **options)

        with self.client(analyzer=analyzer) as client:
            try:
                with self.assertLogs("src.road_anomaly.api.jobs", level="ERROR"):
                    failed = self.upload(client)
                    self.wait(client, failed, "failed")
                running = self.upload(client)
                self.assertTrue(entered.wait(5))
                queued = self.upload(client)
                response = client.get("/api/jobs")
                self.assertNotIn(str(self.root), response.text)
                rows = {item["job_id"]: item for item in response.json()["items"]}
                for job_id, status in ((failed, "failed"), (running, "running"), (queued, "queued")):
                    self.assertEqual(rows[job_id]["status"], status)
                    self.assertIsNone(rows[job_id]["analysis"])
                    self.assertIsNone(rows[job_id]["reviews"])
                self.assertEqual(rows[failed]["error"]["code"], "analysis_failed")
            finally:
                release.set()
            self.wait(client, running)
            self.wait(client, queued)
            completed = client.get("/api/jobs", params={"status": "completed"}).json()
            self.assertEqual(completed["total"], 2)
            for row in completed["items"]:
                self.assertEqual(row["analysis"]["event_count"], 0)
                self.assertEqual(row["analysis"]["video"]["duration_sec"], 3)
                self.assertEqual(row["analysis"]["analysis_seconds"], 0.2)
                self.assertTrue(all(value == 0 for value in row["reviews"].values()))
                self.assertNotIn("events", row["analysis"])
                self.assertNotIn("settings", row["analysis"])

    def test_history_filters_sort_ties_and_pagination(self):
        with self.client() as client:
            for i, status, filename, created in (
                (1, "failed", "Dashcam-Rear.mp4", "2026-11-01T00:00:00Z"),
                (2, "queued", "OTHER.mp4", "2026-11-02T00:00:00Z"),
                (3, "failed", "DASHCAM-Front.mp4", "2026-11-03T01:00:00+01:00"),
                (4, "failed", "dashcam 전방.mp4", "2026-11-03T00:00:00"),
            ):
                directory = self.settings.jobs_root / str(UUID(int=i))
                directory.mkdir()
                write_json_atomic(directory / "job.json", {"job_id": directory.name, "status": status,
                                  "original_filename": filename, "created_at": created})
            directory = self.settings.jobs_root / "ignore_this_directory"
            directory.mkdir()
            request = {"status": "failed", "search": "  DaShCam  ", "limit": 1}
            first = client.get("/api/jobs", params=request).json()
            next_page = client.get("/api/jobs", params={**request, "offset": 1}).json()
            oldest = client.get("/api/jobs", params={**request, "sort": "oldest", "limit": 3}).json()
            out = client.get("/api/jobs", params={**request, "offset": 3}).json()
            self.assertEqual((first["total"], first["count"], first["items"][0]["job_id"]), (3, 1, str(UUID(int=4))))
            self.assertEqual(next_page["items"][0]["job_id"], str(UUID(int=3)))
            self.assertEqual([row["job_id"] for row in oldest["items"]], [str(UUID(int=i)) for i in (1, 3, 4)])
            self.assertEqual((out["total"], out["count"], out["items"], out["warnings"]), (3, 0, [], []))

    def test_history_review_summary_matches_explicit_updates(self):
        self.multiple_events = True
        with self.client() as client:
            job_id = self.upload(client)
            self.wait(client, job_id)
            endpoint = f"/api/jobs/{job_id}/reviews"
            for updates, expected in (
                ((), (2, 0, 0, 0, 0)),
                (((1, "suspected"), (2, "deferred")), (0, 1, 0, 1, 2)),
                (((1, "false_positive"), (2, "unreviewed")), (1, 0, 1, 0, 1)),
            ):
                for index, review in updates:
                    self.assertEqual(client.put(f"{endpoint}/event_{index:04}", json={"review": review}).status_code, 200)
                row = client.get("/api/jobs").json()["items"][0]
                self.assertEqual(row["analysis"]["event_count"], 2)
                keys = ("unreviewed", "suspected", "false_positive", "deferred", "reviewed_count")
                self.assertEqual(row["reviews"], dict(zip(keys, expected, strict=True)))
            self.assertEqual([row["review"] for row in client.get(endpoint).json()["reviews"]],
                             ["false_positive", "unreviewed"])

    def test_history_damage_is_reported_and_off_page_results_are_not_read(self):
        with self.client() as client:
            bad_results, bad_reviews, valid = [self.upload(client) for _ in range(3)]
            for job_id in (bad_results, bad_reviews, valid):
                self.wait(client, job_id)
            incomplete = str(uuid4())
            (self.settings.jobs_root / incomplete).mkdir()
            corrupt_job = str(uuid4())
            corrupt_directory = self.settings.jobs_root / corrupt_job
            corrupt_directory.mkdir()
            (corrupt_directory / "job.json").write_bytes(b"{")
            invalid_result_path = self.settings.jobs_root / bad_results / "results.json"
            original_result = json.loads(invalid_result_path.read_bytes())
            write_json_atomic(invalid_result_path, {**original_result, "event_count": 100})
            review_path = self.settings.jobs_root / bad_reviews / "reviews.json"
            entry = {"event_id": "event_9999", "review": "suspected", "updated_at": "2026-11-26T00:00:00Z"}
            write_json_atomic(review_path, {"job_id": bad_reviews, "reviews": [entry]})
            with self.assertLogs("src.road_anomaly.api.jobs", level="WARNING") as logs:
                page = client.get("/api/jobs", params={"limit": 1}).json()
                body = client.get("/api/jobs").json()
            self.assertEqual(page["items"][0]["job_id"], valid)
            self.assertEqual(page["total"], 3)
            self.assertEqual({warning["job_id"] for warning in page["warnings"]}, {incomplete, corrupt_job})
            self.assertEqual({warning["job_id"]: warning["error"]["code"] for warning in body["warnings"]}, {
                incomplete: "job_data_unavailable", corrupt_job: "job_data_unavailable",
                bad_results: "results_unavailable", bad_reviews: "review_data_invalid",
            })
            by_id = {row["job_id"]: row for row in body["items"]}
            self.assertIsNone(by_id[bad_results]["analysis"])
            self.assertIsNone(by_id[bad_results]["reviews"])
            self.assertEqual(by_id[bad_reviews]["analysis"]["event_count"], 1)
            self.assertIsNone(by_id[bad_reviews]["reviews"])
            self.assertEqual(by_id[valid]["reviews"]["unreviewed"], 1)
            self.assertTrue(any(bad_reviews in row for row in logs.output))

    def test_history_review_read_failure_is_distinct_from_missing_file(self):
        with self.client() as client:
            job_id = self.upload(client)
            self.wait(client, job_id)
            review_path = self.settings.jobs_root / job_id / "reviews.json"
            read = Path.read_bytes

            def denied(path):
                if path == review_path:
                    raise PermissionError("private location")
                return read(path)

            with self.assertLogs("src.road_anomaly.api.jobs", level="WARNING"):
                with patch.object(Path, "read_bytes", denied):
                    response = client.get("/api/jobs")
            self.assertNotIn("private location", response.text)
            body = response.json()
            self.assertIsNone(body["items"][0]["reviews"])
            self.assertEqual(body["warnings"][0]["error"]["code"], "review_read_failed")

    def test_history_redirected_paths_do_not_read_other_jobs(self):
        with self.client() as client:
            first, another = self.upload(client), self.upload(client)
            self.wait(client, first)
            self.wait(client, another)
            directory = self.settings.jobs_root / first
            path = directory / "job.json"
            disk = json.loads(path.read_bytes())
            del disk["file_size_bytes"]
            write_json_atomic(path, disk)
            upload = self.settings.uploads_root / first / "input.mp4"
            other_directory = self.settings.jobs_root / another
            other_upload = self.settings.uploads_root / another / "input.mp4"
            resolve = Path.resolve
            for source, target, code in (
                (path, other_directory / "job.json", "job_data_unavailable"),
                (directory / "results.json", other_directory / "results.json", "results_unavailable"),
                (directory / "reviews.json", other_directory / "reviews.json", "review_data_invalid"),
                (upload, other_upload, "upload_size_unavailable"),
            ):
                with self.subTest(code=code):
                    def redirected(path_arg, *args, **kwargs):
                        return target if path_arg == source else resolve(path_arg, *args, **kwargs)

                    with self.assertLogs("src.road_anomaly.api.jobs", level="WARNING"):
                        with patch.object(Path, "resolve", redirected):
                            response = client.get("/api/jobs")
                    self.assertEqual(response.status_code, 200)
                    self.assertNotIn(str(self.root), response.text)
                    body = response.json()
                    self.assertEqual(body["warnings"][0]["job_id"], first)
                    self.assertEqual(body["warnings"][0]["error"]["code"], code)
                    row = next((item for item in body["items"] if item["job_id"] == first), None)
                    if code == "job_data_unavailable":
                        self.assertIsNone(row)
                    else:
                        self.assertIsNone(row[{"results_unavailable": "analysis", "review_data_invalid": "reviews",
                                               "upload_size_unavailable": "file_size_bytes"}[code]])

    def test_history_reads_during_review_updates_return_consistent_counts(self):
        self.multiple_events = True
        with self.client() as client:
            job_id = self.upload(client)
            self.wait(client, job_id)
            started = Barrier(3, timeout=5)

            def save(index, review):
                started.wait()
                return client.put(f"/api/jobs/{job_id}/reviews/event_{index:04}", json={"review": review})

            def read():
                started.wait()
                return [client.get("/api/jobs").json() for _ in range(8)]

            with ThreadPoolExecutor(max_workers=3) as workers:
                reader = workers.submit(read)
                saves = [workers.submit(save, i, review) for i, review in ((1, "suspected"), (2, "deferred"))]
                self.assertTrue(all(result.result().status_code == 200 for result in saves))
                for body in reader.result():
                    self.assertEqual(body["warnings"], [])
                    reviews = body["items"][0]["reviews"]
                    self.assertEqual(reviews["reviewed_count"], reviews["suspected"] + reviews["deferred"])
                    self.assertEqual(reviews["unreviewed"] + reviews["reviewed_count"], 2)
            final = client.get("/api/jobs").json()["items"][0]["reviews"]
            self.assertEqual(final, {"unreviewed": 0, "suspected": 1, "false_positive": 0, "deferred": 1,
                                     "reviewed_count": 2})

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

    def test_reviews_round_trip_and_original_files_survive_restart(self):
        self.multiple_events = True
        with self.client() as client:
            job_id = self.upload(client)
            self.wait(client, job_id)
            endpoint = f"/api/jobs/{job_id}/reviews"
            job_dir = self.settings.jobs_root / job_id
            analysis_dir = self.settings.analysis_root / job_id
            originals = (job_dir / "job.json", job_dir / "results.json", analysis_dir / "detections.csv",
                         analysis_dir / "scenes/event_0001.jpg", self.settings.uploads_root / job_id / "input.mp4")
            snapshots = {path: path.read_bytes() for path in originals}
            self.assertEqual(client.get(endpoint).json(), {"job_id": job_id, "reviews": []})
            self.assertFalse((job_dir / "reviews.json").exists())

            for state in ("suspected", "false_positive", "unreviewed"):
                response = client.put(f"{endpoint}/event_0001", json={"review": state})
                self.assertEqual(response.status_code, 200, response.text)
                first = response.json()
                self.assertEqual((first["event_id"], first["review"]), ("event_0001", state))
                self.assertTrue(first["updated_at"].endswith("Z"))
            second = client.put(f"{endpoint}/event_0002", json={"review": "deferred"}).json()
            expected = {"job_id": job_id, "reviews": [first, second]}
            self.assertEqual(second["review"], "deferred")
            self.assertEqual(client.get(endpoint).json(), expected)
            self.assertEqual(json.loads((job_dir / "reviews.json").read_bytes()), expected)

            other = self.upload(client)
            self.wait(client, other)
            self.assertEqual(client.get(f"/api/jobs/{other}/reviews").json(), {"job_id": other, "reviews": []})
        with self.client() as client:
            self.assertEqual(client.get(endpoint).json(), expected)
        self.assertEqual({path: path.read_bytes() for path in originals}, snapshots)
        self.assertEqual(len(self.calls), 2)

    def test_reviews_validate_ids_request_and_cors(self):
        with self.client() as client:
            job_id = self.upload(client)
            self.wait(client, job_id)
            endpoint = f"/api/jobs/{job_id}/reviews"
            for ident, status, code in (("invalid-uuid", 422, "invalid_request"), (uuid4(), 404, "not_found")):
                missing = f"/api/jobs/{ident}/reviews"
                self.assert_error(client.get(missing), status, code)
                self.assert_error(client.put(f"{missing}/event_0001", json={"review": "suspected"}), status, code)
            for event_id in ("invalid", "event_0001.jpg", "%2e%2e%5cjob.json"):
                self.assert_error(client.put(f"{endpoint}/{event_id}", json={"review": "suspected"}), 422, "invalid_request")
            self.assert_error(client.put(f"{endpoint}/event_9999", json={"review": "suspected"}), 404, "not_found")
            for payload in ({}, {"review": "damaged"}, {"review": None}, {"review": "suspected", "path": "../job.json"}):
                self.assert_error(client.put(f"{endpoint}/event_0001", json=payload), 422, "invalid_request")
            malformed = client.put(f"{endpoint}/event_0001", content=b"{", headers={"Content-Type": "application/json"})
            self.assert_error(malformed, 422, "invalid_request")
            for origin, status in (("http://127.0.0.1:5173", 200), ("https://example.org", 400)):
                response = client.options(f"{endpoint}/event_0001", headers={
                    "Origin": origin, "Access-Control-Request-Method": "PUT", "Access-Control-Request-Headers": "Content-Type",
                })
                self.assertEqual(response.status_code, status)
                self.assertEqual("access-control-allow-origin" in response.headers, status == 200)
            self.assertFalse((self.settings.jobs_root / job_id / "reviews.json").exists())

    def test_reviews_reject_queued_running_and_failed_jobs(self):
        entered, release = Event(), Event()

        def fail(video, **options):
            entered.set()
            release.wait(5)
            raise RuntimeError("analysis failed")

        with self.client(fail) as client:
            def assert_unavailable(job_id):
                endpoint = f"/api/jobs/{job_id}/reviews"
                self.assert_error(client.get(endpoint), 409, "results_not_ready")
                self.assert_error(client.put(f"{endpoint}/event_0001", json={"review": "deferred"}), 409, "results_not_ready")

            with self.assertLogs("src.road_anomaly.api.jobs", level="ERROR"):
                running = self.upload(client)
                try:
                    self.assertTrue(entered.wait(5))
                    queued = self.upload(client)
                    self.assertEqual(client.get(f"/api/jobs/{queued}").json()["status"], "queued")
                    assert_unavailable(running)
                    assert_unavailable(queued)
                finally:
                    release.set()
                self.wait(client, running, "failed")
                self.wait(client, queued, "failed")
            assert_unavailable(running)

    def test_corrupt_reviews_cannot_be_overwritten(self):
        with self.client() as client:
            job_id = self.upload(client)
            self.wait(client, job_id)
            endpoint = f"/api/jobs/{job_id}/reviews"
            path = self.settings.jobs_root / job_id / "reviews.json"
            entry = {"event_id": "event_0001", "review": "suspected", "updated_at": "2026-11-26T00:00:00Z"}
            for corrupt in (
                b'{"reviews":', b"\xff",
                json.dumps({"job_id": str(uuid4()), "reviews": []}).encode(),
                json.dumps({"job_id": job_id, "reviews": [entry, entry]}).encode(),
                json.dumps({"job_id": job_id, "reviews": [{**entry, "event_id": "event_9999"}]}).encode(),
                json.dumps({"job_id": job_id, "reviews": [{**entry, "updated_at": "invalid"}]}).encode(),
            ):
                with self.subTest(corrupt=corrupt):
                    path.write_bytes(corrupt)
                    self.assert_error(client.get(endpoint), 500, "review_data_invalid")
                    self.assert_error(client.put(f"{endpoint}/event_0001", json={"review": "deferred"}), 500, "review_data_invalid")
                    self.assertEqual(path.read_bytes(), corrupt)

    def test_review_read_and_atomic_replace_failures_preserve_file(self):
        with self.client() as client:
            job_id = self.upload(client)
            self.wait(client, job_id)
            endpoint = f"/api/jobs/{job_id}/reviews"
            event_endpoint = f"{endpoint}/event_0001"
            before = client.put(event_endpoint, json={"review": "suspected"}).json()
            path = self.settings.jobs_root / job_id / "reviews.json"
            original = path.read_bytes()
            with self.assertLogs("src.road_anomaly.api.jobs", level="ERROR"):
                with patch.object(Path, "read_bytes", side_effect=PermissionError):
                    self.assert_error(client.get(endpoint), 500, "review_read_failed")
                    self.assert_error(client.put(event_endpoint, json={"review": "deferred"}), 500, "review_read_failed")
                with patch.object(Path, "replace", side_effect=PermissionError):
                    self.assert_error(client.put(event_endpoint, json={"review": "deferred"}), 500, "review_save_failed")
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])
            self.assertEqual(client.get(endpoint).json()["reviews"], [before])

    def test_review_file_redirect_is_rejected(self):
        with self.client() as client:
            job_id = self.upload(client)
            self.wait(client, job_id)
            endpoint = f"/api/jobs/{job_id}/reviews"
            directory = self.settings.jobs_root / job_id
            path, target = directory / "reviews.json", directory / "results.json"
            original = target.read_bytes()
            resolve = Path.resolve
            with patch.object(Path, "resolve", lambda path_arg: target if path_arg == path else resolve(path_arg)):
                self.assert_error(client.get(endpoint), 404, "not_found")
                self.assert_error(client.put(f"{endpoint}/event_0001", json={"review": "deferred"}), 404, "not_found")
            self.assertEqual(target.read_bytes(), original)
            self.assertFalse(path.exists())

    def test_concurrent_reviews_preserve_distinct_events(self):
        self.multiple_events = True
        with self.client() as client:
            job_id = self.upload(client)
            self.wait(client, job_id)
            endpoint = f"/api/jobs/{job_id}/reviews"
            started = Barrier(2, timeout=5)

            def store(event_id, review):
                started.wait()
                return client.put(f"{endpoint}/{event_id}", json={"review": review})

            with ThreadPoolExecutor(max_workers=2) as workers:
                first = workers.submit(store, "event_0001", "suspected")
                second = workers.submit(store, "event_0002", "deferred")
                for response in (first.result(), second.result()):
                    self.assertEqual(response.status_code, 200, response.text)
            reviews = client.get(endpoint).json()["reviews"]
            self.assertEqual({row["event_id"]: row["review"] for row in reviews},
                             {"event_0001": "suspected", "event_0002": "deferred"})

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
