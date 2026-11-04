"""Framing problems the camera view measures: something right in front of the lens, big things never in frame.

Seen in test renders: a market-stall post filling the middle of the first frame, a bandit's hat filling the frame
from inside a tent, and a harbour shot that showed two of its three boats. No Blender here: the camera view hands
over names, shares of the frame, distances and boxes.
"""

from .. import plan3d

NEAR_M = 4.0  # metres from the lens: closer than this, a thing between the camera and the subject blocks it
NEAR_SHARE_PCT = 8.0  # share of the frame such a thing must cover to count
CENTRE = (0.2, 0.8)  # the middle of the frame, in view coordinates, where a blocker hides the shot
BIG_M = 3.0  # a thing this long or longer is one the shot is likely about
LISTED = 6


def closest_m(origin, corners):
    """Distance from ``origin`` to the axis-aligned box around ``corners`` (0 inside it)."""
    total = 0.0
    for axis in range(3):
        low, high = min(c[axis] for c in corners), max(c[axis] for c in corners)
        d = max(low - origin[axis], 0.0, origin[axis] - high)
        total += d * d
    return total ** 0.5


def in_centre(rect):
    """True when a frame rectangle ``(x0, x1, y0, y1)`` reaches into the middle of the frame."""
    x0, x1, y0, y1 = rect
    return x1 > CENTRE[0] and x0 < CENTRE[1] and y1 > CENTRE[0] and y0 < CENTRE[1]


def near_blockers(entries, subject=None):
    """``entries``: ``[{"name", "root", "coverage_pct", "distance_m", "rect", "ground"}]`` for one frame. The
    things right in front of the lens that hide the middle of the frame, biggest first."""
    found = [e for e in entries
             if e["distance_m"] <= NEAR_M and e["coverage_pct"] >= NEAR_SHARE_PCT and in_centre(e["rect"])
             and not e.get("ground") and e.get("root") != subject]
    found.sort(key=lambda e: -e["coverage_pct"])
    return [{"name": e["root"] or e["name"], "distance_m": round(e["distance_m"], 2),
             "coverage_pct": e["coverage_pct"]} for e in found[:LISTED]]


def about_subjects(root, subjects):
    """Whether the root's name shares a word with one of ``subjects`` (the planned things' names), so a shot is
    about it. Every root counts when there are no subjects."""
    if not subjects:
        return True
    words = set(plan3d.name_words(root))
    return any(words.intersection(plan3d.name_words(s)) for s in subjects)


def never_in_view(views, big_roots, subjects=()):
    """Names in ``big_roots`` (``{root name: [part names]}``) with no part visible at any of ``views``, only those the
    request is about when ``subjects`` names the planned things."""
    seen = set()
    for view in views:
        seen.update(v["name"] for v in view.get("visible") or ())
    return [root for root, parts in big_roots.items()
            if not seen.intersection(parts) and about_subjects(root, subjects)][:LISTED]
