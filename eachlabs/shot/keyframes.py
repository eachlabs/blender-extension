"""Key frames: the frames of a camera move that show each object best. No ``bpy``."""

COVERED = 0.9


def pick(views, first, limit=9):
    """Sorted frames to photograph, always with ``first``.

    ``views`` maps a frame to {thing name: share of the thing in view, 0 to 1}. A thing in view at every frame needs
    no frame of its own: ``first`` shows it. Any other thing needs one unless a picked frame already shows it at 0.9
    or more; its frame is the one that shows it most (earliest on a tie).
    """
    picked = [first]
    always = set.intersection(*(set(shown) for shown in views.values())) if views else set()

    def covered(name):
        return any(views.get(f, {}).get(name, 0.0) >= COVERED for f in picked)

    best = {}
    for frame in sorted(views):
        for name, share in views[frame].items():
            if name in always:
                continue
            if name not in best or share > views[best[name]][name]:
                best[name] = frame
    for name in sorted(best, key=lambda n: (best[n], n)):
        if len(picked) >= limit:
            break
        if not covered(name):
            picked.append(best[name])
    return sorted(set(picked))


def share(boxes):
    """How well a frame shows a thing, 0 to 1, from its parts' projected boxes ``(x0, x1, y0, y1)`` in view
    coordinates, where the frame is 0..1 and boxes may reach past it.

    The part of the thing's box inside the frame, as a share of the whole box; or, when more, the share of the frame
    that part fills, so a close-up that fills or overflows the frame counts as showing the thing."""
    if not boxes:
        return 0.0
    x0, x1 = min(b[0] for b in boxes), max(b[1] for b in boxes)
    y0, y1 = min(b[2] for b in boxes), max(b[3] for b in boxes)
    full = (x1 - x0) * (y1 - y0)
    seen = max(0.0, min(x1, 1.0) - max(x0, 0.0)) * max(0.0, min(y1, 1.0) - max(y0, 0.0))
    if seen <= 0.0:
        return 0.0
    whole = seen / full if full > 0.0 else 1.0
    return round(min(1.0, max(whole, seen)), 3)


def surrounds(corners, point):
    """True when ``point`` lies inside the axis-aligned box around ``corners`` (x, y, z points): the thing is around
    it."""
    if not corners:
        return False
    return all(min(c[i] for c in corners) <= point[i] <= max(c[i] for c in corners) for i in range(3))


def pick_until(views, first, last, limit=9):
    """``pick`` within the frames ``first`` to ``last`` of a move measured further: a shorter video picks from the
    same measure."""
    return pick({frame: shown for frame, shown in views.items() if first <= frame <= last}, first, limit)
