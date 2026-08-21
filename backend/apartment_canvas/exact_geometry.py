"""Small exact 2-D kernel used by Apartment Canvas derived topology.

Coordinates enter through canonical JSON numeric tokens parsed as ``Decimal``
values and are thereafter only ``Fraction`` values.  This module deliberately
has no tolerance or float fallbacks.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Any, Iterable


class ExactGeometryError(ValueError):
    """Input is not a finite canonical numeric value or valid exact geometry."""


def rational(value: Any) -> Fraction:
    """Convert an intentionally exact value, never a binary float.

    Decimal values are the only source-geometry numeric ingress.  Rational
    strings are retained solely for parsing this module's own derived-output
    tokens back into exact points.
    """
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal, Fraction)):
        raise ExactGeometryError("coordinate must be a finite numeric token")
    if isinstance(value, Fraction):
        return value
    if isinstance(value, str) and value.count("/") == 1:
        numerator, denominator = value.split("/")
        try:
            denominator_value = int(denominator)
            if denominator_value <= 0:
                raise ValueError("denominator must be positive")
            parsed = Fraction(int(numerator), denominator_value)
        except (ValueError, ZeroDivisionError) as exc:
            raise ExactGeometryError("invalid rational token") from exc
        if value != f"{parsed.numerator}/{parsed.denominator}":
            raise ExactGeometryError("coordinate strings must be canonical reduced rational tokens")
        return parsed
    if isinstance(value, str):
        raise ExactGeometryError("coordinate strings must be reduced rational tokens")
    decimal = Decimal(value)
    if not decimal.is_finite():
        raise ExactGeometryError("coordinate must be finite")
    return Fraction(decimal)


def rational_text(value: Fraction) -> str:
    """The one schema-wide representation: reduced numerator/positive denominator."""
    if not isinstance(value, Fraction):
        raise TypeError("rational_text requires Fraction")
    return f"{value.numerator}/{value.denominator}"


@dataclass(frozen=True, order=True)
class Point:
    x: Fraction
    y: Fraction

    @classmethod
    def from_value(cls, value: Any) -> "Point":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ExactGeometryError("point must be a two-coordinate sequence")
        return cls(rational(value[0]), rational(value[1]))

    def to_tokens(self) -> list[str]:
        return [rational_text(self.x), rational_text(self.y)]


def vector(a: Point, b: Point) -> Point:
    return Point(b.x - a.x, b.y - a.y)


def cross(a: Point, b: Point) -> Fraction:
    return a.x * b.y - a.y * b.x


def orientation(a: Point, b: Point, c: Point) -> Fraction:
    return cross(vector(a, b), vector(a, c))


def on_segment(point: Point, start: Point, end: Point) -> bool:
    return (
        orientation(start, end, point) == 0
        and min(start.x, end.x) <= point.x <= max(start.x, end.x)
        and min(start.y, end.y) <= point.y <= max(start.y, end.y)
    )


@dataclass(frozen=True)
class SegmentRelation:
    kind: str
    point: Point | None = None


def classify_segments(a: Point, b: Point, c: Point, d: Point) -> SegmentRelation:
    """Classify exact segment interaction (proper/contact/overlap/disjoint)."""
    ab_c, ab_d = orientation(a, b, c), orientation(a, b, d)
    cd_a, cd_b = orientation(c, d, a), orientation(c, d, b)
    if ab_c * ab_d < 0 and cd_a * cd_b < 0:
        return SegmentRelation("proper", proper_intersection(a, b, c, d))
    contacts = sorted({p for p in (a, b, c, d) if on_segment(p, a, b) and on_segment(p, c, d)})
    if len(contacts) > 1:
        return SegmentRelation("overlap")
    if contacts:
        return SegmentRelation("contact", contacts[0])
    return SegmentRelation("disjoint")


def proper_intersection(a: Point, b: Point, c: Point, d: Point) -> Point:
    """Return the exact line intersection, rejecting non-proper segment pairs."""
    r, s = vector(a, b), vector(c, d)
    denominator = cross(r, s)
    if denominator == 0:
        raise ExactGeometryError("parallel segments have no proper intersection")
    t = cross(vector(a, c), s) / denominator
    point = Point(a.x + t * r.x, a.y + t * r.y)
    if not (0 < t < 1 and on_segment(point, c, d)):
        raise ExactGeometryError("segments do not intersect properly")
    return point


def segment_parameter(point: Point, start: Point, end: Point) -> Fraction:
    if not on_segment(point, start, end) or start == end:
        raise ExactGeometryError("point is not on a non-zero segment")
    delta = vector(start, end)
    return (point.x - start.x) / delta.x if delta.x != 0 else (point.y - start.y) / delta.y


def shoelace(ring: Iterable[Point]) -> Fraction:
    points = tuple(ring)
    if len(points) < 3:
        return Fraction(0)
    return sum((a.x * b.y - b.x * a.y for a, b in zip(points, points[1:] + points[:1])), Fraction(0)) / 2


def point_in_ring(point: Point, ring: Iterable[Point]) -> bool:
    """Strict even/odd point membership; a boundary witness is a programming error."""
    points = tuple(ring)
    if any(on_segment(point, a, b) for a, b in zip(points, points[1:] + points[:1])):
        raise ExactGeometryError("point-on-boundary is not a parity witness")
    inside = False
    for a, b in zip(points, points[1:] + points[:1]):
        if (a.y > point.y) != (b.y > point.y):
            crossing_x = a.x + (point.y - a.y) * (b.x - a.x) / (b.y - a.y)
            if crossing_x > point.x:
                inside = not inside
    return inside


def point_in_contours_parity(point: Point, contours: Iterable[Iterable[Point]]) -> bool:
    return sum(point_in_ring(point, contour) for contour in contours) % 2 == 1


def interior_witness(ring: Iterable[Point]) -> Point:
    """Find an exact inside point by scanning non-vertex horizontal slabs.

    The scan lines are midpoints of adjacent distinct vertex ordinates.  Every
    intersection and interval midpoint is rational; no offset is introduced.
    """
    points = tuple(ring)
    if len(points) < 3 or shoelace(points) == 0:
        raise ExactGeometryError("non-zero ring required for an interior witness")
    ys = sorted({point.y for point in points})
    for low, high in zip(ys, ys[1:]):
        y = (low + high) / 2
        xs = sorted(
            a.x + (y - a.y) * (b.x - a.x) / (b.y - a.y)
            for a, b in zip(points, points[1:] + points[:1])
            if (a.y > y) != (b.y > y)
        )
        for left, right in zip(xs[::2], xs[1::2]):
            candidate = Point((left + right) / 2, y)
            if point_in_ring(candidate, points):
                return candidate
    raise ExactGeometryError("could not construct exact interior witness")
