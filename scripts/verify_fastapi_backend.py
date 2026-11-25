"""실행 중인 로컬 API에 실제 MP4를 업로드하고 결과·Range·JPEG를 검증한다."""
import argparse
import json
from pathlib import Path
from time import monotonic, perf_counter, sleep
from urllib.parse import urlparse

import cv2
import httpx
import numpy as np


def verify(base_url: str, video: Path, *, timeout: float = 300) -> dict:
    if urlparse(base_url).hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("검증 대상은 로컬 API 주소여야 합니다.")
    started = perf_counter()
    with httpx.Client(base_url=base_url, timeout=timeout, trust_env=False) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/docs").status_code == 200
        assert "/api/jobs" in client.get("/openapi.json").json()["paths"]
        with video.open("rb") as handle:
            response = client.post("/api/jobs", files={"file": (video.name, handle, "video/mp4")})
        assert response.status_code == 202, response.text
        created = response.json()
        assert created["status"] == "queued", created
        upload_seconds = perf_counter() - started
        job_id = created["job_id"]
        states = ["queued"]
        deadline = monotonic() + timeout
        running_queries = 0
        while monotonic() < deadline:
            status = client.get(f"/api/jobs/{job_id}")
            status.raise_for_status()
            job = status.json()
            if states[-1] != job["status"]:
                states.append(job["status"])
            if job["status"] == "running":
                running_queries += 1
                assert client.get("/api/health").json() == {"status": "ok"}
                assert client.get(f"/api/jobs/{job_id}/results").status_code == 409
            if job["status"] == "failed":
                raise RuntimeError(f"Analysis failed: {job}")
            if job["status"] == "completed":
                break
            sleep(0.1)
        else:
            raise TimeoutError(f"Job timed out: {job_id}")
        assert running_queries > 0, "Did not observe running state"
        response = client.get(f"/api/jobs/{job_id}/results")
        response.raise_for_status()
        results = response.json()
        assert results["event_count"] == len(results["events"])
        assert results["detection_count"] == sum(event["detection_count"] for event in results["events"])
        assert results["extracted_frame_count"] == results["inferred_frame_count"]
        assert results["settings"]["device"] == "cuda:0"
        assert results["settings"]["max_event_duration_sec"] == 5
        for event in results["events"]:
            assert 0 <= event["last_detection_time_sec"] - event["start_time_sec"] <= 5 + 1e-9
            response = client.get(event["image_url"])
            response.raise_for_status()
            assert response.headers["content-type"] == "image/jpeg"
            image = cv2.imdecode(np.frombuffer(response.content, dtype=np.uint8), cv2.IMREAD_COLOR)
            assert image is not None
            assert image.shape[:2] == (results["video"]["height"], results["video"]["width"])
        video_url = results["video_url"]
        head = client.head(video_url)
        assert head.status_code == 200
        size = video.stat().st_size
        assert int(head.headers["content-length"]) == size
        assert head.headers["content-type"] == "video/mp4"
        ranges = []
        with video.open("rb") as handle:
            for start, end in ((0, 1023), (size // 2, size // 2 + 1023), (size - 1024, size - 1)):
                response = client.get(video_url, headers={"Range": f"bytes={start}-{end}"})
                assert response.status_code == 206
                assert response.headers["accept-ranges"] == "bytes"
                assert response.headers["content-range"] == f"bytes {start}-{end}/{size}"
                handle.seek(start)
                assert response.content == handle.read(end - start + 1)
                ranges.append(response.headers["content-range"])
        return {"job": job, "states": states, "running_status_queries": running_queries,
                "upload_and_validation_seconds": upload_seconds, "total_verification_seconds": perf_counter() - started,
                "results": results, "verified_jpegs": len(results["events"]), "verified_ranges": ranges,
                "note": "HTTP/MP4 Range 검증. 브라우저 코덱 재생 및 React 통합은 별도 검증 대상."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--video", type=Path, default=Path("data/raw/dashcam_validation/Dashcam-Front.mp4"))
    parser.add_argument("--output", type=Path, required=True, help="새 검증 JSON 경로. 기존 파일은 덮어쓰지 않음")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("검증 결과 파일이 이미 있습니다. 새로운 --output 경로를 지정해 주세요.")
    result = verify(args.base_url, args.video)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({"job_id": result["job"]["job_id"], "states": result["states"],
                      "detections": result["results"]["detection_count"], "events": result["verified_jpegs"],
                      "analysis_seconds": result["results"]["analysis_seconds"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
