"""Spots for many copies of one thing across an area: random, never in rows, never closer than a gap, never
through another thing."""

import math
import random

from . import geometry as geo
from .grid import Grid

TRIES_PER_COPY = 30


def spots(area, count, radius, obstacles, gap_m=None, size=(0.8, 1.2), turn=True, seed=0, valid=None):
    """Up to ``count`` ``(x, y, turn, scale)`` inside ``area`` for a thing about ``radius`` metres across its middle.
    ``obstacles``: a Grid of what stands already (copies are added to it as they are placed)."""
    rng = random.Random(seed)
    gap = gap_m if gap_m is not None else radius * 0.5
    own = Grid(max(2.0, radius * 2 + gap))
    out = []
    for _ in range(count * TRIES_PER_COPY):
        if len(out) >= count:
            break
        x, y = area.sample(rng)
        scale = rng.uniform(size[0], size[1])
        r = radius * scale
        box = geo.box_around(x, y, r, r)
        if not area.contains_box(box, r * 0.5):
            continue
        if own.hit(box, gap) or obstacles.hit(box, 0.0):
            continue
        if valid is not None and valid(x, y) is not True:
            continue
        own.add(box)
        obstacles.add(box, "copy")
        out.append((x, y, rng.uniform(0, 2 * math.pi) if turn else 0.0, scale))
    return out
