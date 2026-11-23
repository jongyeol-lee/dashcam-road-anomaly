import math
from dataclasses import dataclass


Point = tuple[float, float]
EPSILON = 1e-12


def _cross(start: Point, end: Point, point: Point) -> float:
    return (end[0] - start[0]) * (point[1] - start[1]) - (end[1] - start[1]) * (point[0] - start[0])


@dataclass(frozen=True)
class BoxPosition:
    keep: bool
    touches_boundary: bool


@dataclass(frozen=True)
class NormalizedRoi:
    """원본 프레임에 대한 0~1 상대 좌표로 정의한 볼록 다각형."""

    vertices: tuple[Point, ...]

    def __post_init__(self) -> None:
        try:
            vertices = tuple((x, y) for x, y in self.vertices)
            valid = len(vertices) >= 3 and all(
                math.isfinite(value) and 0 <= value <= 1 for point in vertices for value in point
            )
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("ROI 좌표는 0~1 범위의 유한한 (x, y) 꼭짓점 3개 이상이어야 합니다.")

        # 모든 변에 대해 나머지 꼭짓점이 같은 안쪽에 있어야 한다.
        direction = 1 if _cross(*vertices[:3]) > 0 else -1
        for index, start in enumerate(vertices):
            next_index = (index + 1) % len(vertices)
            end = vertices[next_index]
            if any(direction * _cross(start, end, point) <= EPSILON
                   for i, point in enumerate(vertices) if i not in (index, next_index)):
                raise ValueError("ROI 꼭짓점은 중복 없이 볼록 다각형의 둘레 순서여야 합니다.")
        object.__setattr__(self, "vertices", vertices if direction == 1 else vertices[::-1])

    def pixel_vertices(self, width: int, height: int) -> tuple[Point, ...]:
        """좌표 1은 프레임 오른쪽 또는 아래쪽 끝인 width 또는 height에 대응한다."""
        if width <= 0 or height <= 0:
            raise ValueError("프레임 너비와 높이는 양수여야 합니다.")
        return tuple((x * width, y * height) for x, y in self.vertices)

    def classify(self, box: tuple[float, float, float, float], width: int, height: int) -> BoxPosition:
        """박스 중심으로 통과 여부를 정하고 박스의 경계 교차 또는 접촉을 함께 반환한다."""
        if width <= 0 or height <= 0:
            raise ValueError("프레임 너비와 높이는 양수여야 합니다.")
        x1, y1, x2, y2 = box
        if not (0 <= x1 <= x2 <= width and 0 <= y1 <= y2 <= height):
            raise ValueError(f"프레임 범위를 벗어나거나 순서가 잘못된 박스입니다. {box}")
        x1, y1, x2, y2 = x1 / width, y1 / height, x2 / width, y2 / height
        center = ((x1 + x2) / 2, (y1 + y2) / 2)
        corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        xs, ys = zip(*self.vertices, strict=True)
        disjoint = (x2 < min(xs) - EPSILON or x1 > max(xs) + EPSILON
                    or y2 < min(ys) - EPSILON or y1 > max(ys) + EPSILON)
        keep, strictly_inside = True, True
        for start, end in zip(self.vertices, (*self.vertices[1:], self.vertices[0]), strict=True):
            sides = [_cross(start, end, point) for point in corners]
            keep = keep and _cross(start, end, center) >= -EPSILON
            strictly_inside = strictly_inside and min(sides) > EPSILON
            # 분리 축은 ROI 각 변의 법선과 위에서 확인한 박스의 x/y 축이다.
            disjoint = disjoint or max(sides) < -EPSILON
        return BoxPosition(keep, not disjoint and not strictly_inside)
