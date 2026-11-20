import unittest
from pathlib import Path

from src.road_anomaly.detection_grouping import FrameDetection, group_detections


def detection(frame_index: int, time_sec: float, *, class_id: int = 3, confidence: float = 0.5) -> FrameDetection:
    return FrameDetection(
        frame_index, time_sec, class_id, f"D{class_id}", confidence,
        (10.0, 20.0, 30.0, 40.0), Path(f"frame_{frame_index:06d}.jpg"),
    )


class DetectionGroupingTest(unittest.TestCase):
    def test_merges_consecutive_detections_at_the_boundary_and_splits_larger_gaps(self) -> None:
        first = detection(0, 0.0)
        second = detection(15, 1.5)
        third = detection(30, 3.0)
        fourth = detection(46, 4.6)

        events = group_detections([fourth, first, third, second])

        self.assertEqual([(event.start_time_sec, event.last_detection_time_sec) for event in events],
                         [(0.0, 3.0), (4.6, 4.6)])
        self.assertEqual([event.detection_count for event in events], [3, 1])
        self.assertEqual(events[0].representative, first)

    def test_groups_each_class_independently(self) -> None:
        events = group_detections([
            detection(0, 0.0, class_id=3), detection(8, 0.8, class_id=0),
            detection(16, 1.6, class_id=3), detection(20, 2.0, class_id=0),
        ])

        self.assertEqual([(event.representative.class_id, event.detection_count) for event in events],
                         [(3, 1), (0, 2), (3, 1)])
        self.assertEqual(events[1].last_detection_time_sec, 2.0)

    def test_counts_boxes_and_frames_and_selects_the_highest_confidence(self) -> None:
        best = detection(10, 1.0, confidence=0.92)
        items = [detection(0, 0.0), best, detection(10, 1.0, confidence=0.78)]

        event, = group_detections(items)

        self.assertEqual(event.representative, best)
        self.assertEqual(event.detection_count, 3)
        self.assertEqual(event.detected_frame_count, 2)
        self.assertEqual(len(items), 3)

    def test_configurable_gap_includes_decimal_boundaries(self) -> None:
        items = [detection(7, 0.7), detection(8, 0.8)]
        self.assertEqual(len(group_detections(items, max_gap=0.1)), 1)
        self.assertEqual(len(group_detections(items, max_gap=0.09)), 2)
        self.assertEqual(len(group_detections(items, max_gap=0.0)), 2)

    def test_empty_detections_and_invalid_gaps(self) -> None:
        self.assertEqual(group_detections([]), [])
        for gap in (-1.0, float("inf"), float("nan")):
            with self.subTest(gap=gap), self.assertRaisesRegex(ValueError, "통합 간격"):
                group_detections([], max_gap=gap)
