"""Plain 2D geometry for placement: boxes ``(x0, y0, x1, y1)``, areas (a box or a ring) and turned footprints."""

import math
from dataclasses import dataclass

TURNS = (0.0, math.pi / 2, math.pi, 3 * math.pi / 2)


def box_around(x, y, half_w, half_d):
    return (x - half_w, y - half_d, x + half_w, y + half_d)


def box_size(box):
    return box[2] - box[0], box[3] - box[1]


def box_centre(box):
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def boxes_overlap(a, b, margin=0.0):
    return a[0] - margin < b[2] and b[0] < a[2] + margin and a[1] - margin < b[3] and b[1] < a[3] + margin


def box_inside(inner, outer, slack=0.0):
    return (inner[0] >= outer[0] - slack and inner[1] >= outer[1] - slack and inner[2] <= outer[2] + slack
            and inner[3] <= outer[3] + slack)


def box_gap(a, b):
    """The open distance between two boxes along the axis where they are furthest apart; negative when they overlap
    on both axes."""
    return max(b[0] - a[2], a[0] - b[2], b[1] - a[3], a[1] - b[3])


def union(boxes):
    boxes = list(boxes)
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def turned_box(x, y, size, offset, turn):
    """The axis-aligned box of a footprint of ``size`` (width along local X, depth along local Y) whose centre sits
    ``offset`` from its origin, with the origin at ``(x, y)`` turned ``turn`` radians about Z."""
    c, s = math.cos(turn), math.sin(turn)
    cx = x + offset[0] * c - offset[1] * s
    cy = y + offset[0] * s + offset[1] * c
    half_w = (abs(size[0] * c) + abs(size[1] * s)) / 2
    half_d = (abs(size[0] * s) + abs(size[1] * c)) / 2
    return box_around(cx, cy, half_w, half_d)


def facing_turn(x, y, tx, ty):
    """The turn that points a thing's front (its local -Y) from ``(x, y)`` toward ``(tx, ty)``."""
    return math.atan2(tx - x, -(ty - y))


def angle_off(a, b):
    """How far apart two angles are, 0..pi."""
    d = (a - b) % (2 * math.pi)
    return min(d, 2 * math.pi - d)


@dataclass
class Area:
    """Where things may stand: a box, or a ring (``inner``..``outer`` metres around ``centre``)."""

    name: str
    box: tuple = None
    centre: tuple = None
    inner: float = 0.0
    outer: float = 0.0

    @property
    def is_ring(self):
        return self.box is None

    @property
    def bounds(self):
        if self.box is not None:
            return self.box
        return box_around(self.centre[0], self.centre[1], self.outer, self.outer)

    def contains_point(self, x, y, slack=0.0):
        if self.box is not None:
            return box_inside((x, y, x, y), self.box, slack)
        r = math.hypot(x - self.centre[0], y - self.centre[1])
        return self.inner - slack <= r <= self.outer + slack

    def contains_box(self, box, slack=0.0):
        if self.box is not None:
            return box_inside(box, self.box, slack)
        corners = ((box[0], box[1]), (box[0], box[3]), (box[2], box[1]), (box[2], box[3]))
        if not all(math.hypot(x - self.centre[0], y - self.centre[1]) <= self.outer + slack for x, y in corners):
            return False
        return _box_circle_gap(box, self.centre) >= self.inner - slack

    def overlaps_box(self, box):
        if self.box is not None:
            return boxes_overlap(box, self.box)
        if _box_circle_gap(box, self.centre) > self.outer:
            return False
        corners = ((box[0], box[1]), (box[0], box[3]), (box[2], box[1]), (box[2], box[3]))
        return not all(math.hypot(x - self.centre[0], y - self.centre[1]) < self.inner for x, y in corners)

    def overlaps(self, other):
        if other.is_ring and not self.is_ring:
            return other.overlaps(self)
        if not other.is_ring:
            return self.overlaps_box(other.box)
        d = math.hypot(self.centre[0] - other.centre[0], self.centre[1] - other.centre[1])
        if d >= self.outer + other.outer:
            return False
        return not (d + other.outer <= self.inner or d + self.outer <= other.inner)

    def sample(self, rng):
        """A random point inside the area, even across a ring's area."""
        if self.box is not None:
            return rng.uniform(self.box[0], self.box[2]), rng.uniform(self.box[1], self.box[3])
        angle = rng.uniform(0, 2 * math.pi)
        r = math.sqrt(rng.uniform(self.inner ** 2, self.outer ** 2))
        return self.centre[0] + r * math.cos(angle), self.centre[1] + r * math.sin(angle)

    def size_m2(self):
        if self.box is not None:
            w, d = box_size(self.box)
            return w * d
        return math.pi * (self.outer ** 2 - self.inner ** 2)


def _box_circle_gap(box, centre):
    """Distance from ``centre`` to the nearest point of ``box`` (0 when it lies inside)."""
    dx = max(box[0] - centre[0], 0.0, centre[0] - box[2])
    dy = max(box[1] - centre[1], 0.0, centre[1] - box[3])
    return math.hypot(dx, dy)


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


GROW_MARGIN = 1.3  # a zone grown for a thing too big for it gets this much room around the thing


def grown_for(area, size):
    """``area`` grown so a thing ``size`` (width, depth) fits inside it, or ``None`` when it fits already. A box
    zone keeps its centre and grows each side that is too short; a ring widens outward."""
    need = max(size) * GROW_MARGIN
    if area.is_ring:
        if area.outer - area.inner >= max(size):
            return None
        return Area(area.name, centre=area.centre, inner=area.inner, outer=area.inner + need)
    width, depth = area.box[2] - area.box[0], area.box[3] - area.box[1]
    if width >= size[0] and depth >= size[1]:
        return None
    cx, cy = (area.box[0] + area.box[2]) / 2, (area.box[1] + area.box[3]) / 2
    w = width if width >= size[0] else size[0] * GROW_MARGIN  # a side long enough keeps its size
    d = depth if depth >= size[1] else size[1] * GROW_MARGIN
    return Area(area.name, box=box_around(cx, cy, w / 2, d / 2))
