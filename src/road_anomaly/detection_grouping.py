import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


DEFAULT_MAX_GAP = 1.5


@dataclass(frozen=True)
class FrameDetection:
    frame_index: int
    estimated_time_sec: float
    class_id: int
    class_name: str
    confidence: float
    xyxy: tuple[float, float, float, float]
    image_path: Path


@dataclass(frozen=True)
class SuspiciousEvent:
    start_time_sec: float
    last_detection_time_sec: float
    detection_count: int
    detected_frame_count: int
    representative: FrameDetection


def validate_max_gap(max_gap: float) -> None:
    if not math.isfinite(max_gap) or max_gap < 0:
        raise ValueError("통합 간격은 0 이상의 유한한 숫자(초)여야 합니다.")


def validate_max_event_duration(max_event_duration: float | None) -> None:
    if max_event_duration is not None and (not math.isfinite(max_event_duration) or max_event_duration <= 0):
        raise ValueError("최대 구간 길이는 0보다 큰 유한한 숫자(초) 또는 None이어야 합니다.")


def _summarize(detections: list[FrameDetection]) -> SuspiciousEvent:
    return SuspiciousEvent(
        start_time_sec=detections[0].estimated_time_sec,
        last_detection_time_sec=detections[-1].estimated_time_sec,
        detection_count=len(detections),
        detected_frame_count=len({item.frame_index for item in detections}),
        representative=max(detections, key=lambda item: item.confidence),
    )


def group_detections(
    detections: Iterable[FrameDetection], max_gap: float = DEFAULT_MAX_GAP,
    *, max_event_duration: float | None = None,
) -> list[SuspiciousEvent]:
    """같은 클래스의 인접 탐지를 묶고, 지정된 경우 시작부터의 길이도 제한한다."""
    validate_max_gap(max_gap)
    validate_max_event_duration(max_event_duration)
    ordered = sorted(detections, key=lambda item: (item.class_id, item.estimated_time_sec, item.frame_index))
    events, group = [], []
    rounding_steps = int(max_gap > 0)
    for detection in ordered:
        if group:
            previous = group[-1]
            # 소수 간격의 경계는 부동소수점 반올림 오차 한 단위까지 포함한다.
            limit = math.nextafter(previous.estimated_time_sec + max_gap, math.inf, steps=rounding_steps)
            duration_limit = (math.inf if max_event_duration is None else
                              math.nextafter(group[0].estimated_time_sec + max_event_duration, math.inf))
            if (detection.class_id != previous.class_id or detection.estimated_time_sec > limit
                    or detection.estimated_time_sec > duration_limit):
                events.append(_summarize(group))
                group = []
        group.append(detection)
    if group:
        events.append(_summarize(group))
    return sorted(events, key=lambda event: (event.start_time_sec, event.representative.class_id))
