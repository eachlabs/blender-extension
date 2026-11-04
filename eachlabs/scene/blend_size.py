"""How finely blend() remeshes and how much it smooths, which parts stay out of it, and how its colours meet, from
sizes and distances alone (no bpy, so unit tests cover it)."""

VOXELS_THINNEST = (12, 6)  # voxels across the thinnest part at softness 0 and at softness 1
VOXELS_WIDEST = 120  # at most this many voxels across the whole result, so its mesh stays small
SMOOTH_STEPS = (2, 20)  # smoothing steps at softness 0 and at softness 1
VOXEL_MIN_M = 0.001
LONG_THIN = 0.2  # thinnest side under this share of the longest: a tail, a whisker, a thin limb
FLAT = 0.3  # thinnest side under this share of the middle one: an ear, a fin, a wing
EDGE_VOXELS = (2.0, 6.0)  # how many voxels two colours take to meet, at softness 0 and at softness 1


def settings(sizes, extent, softness):
    """``(voxel size in metres, smoothing steps)`` for parts of world ``sizes`` (x, y, z each) whose union spans
    ``extent`` metres at its widest. Softness 0 keeps the shapes close, 1 fuses them into a softer blob; a thin
    part (a leg, a tail) stays several voxels across unless that would make the mesh too large."""
    soft = min(1.0, max(0.0, float(softness)))
    thinnest = min(min(s) for s in sizes)
    across = VOXELS_THINNEST[0] + (VOXELS_THINNEST[1] - VOXELS_THINNEST[0]) * soft
    voxel = max(thinnest / across, extent / VOXELS_WIDEST, VOXEL_MIN_M)
    steps = round(SMOOTH_STEPS[0] + (SMOOTH_STEPS[1] - SMOOTH_STEPS[0]) * soft)
    return voxel, steps


def thin(size):
    """True when a part of world ``size`` (x, y, z) is long and thin or flat: the remesh frays such a part, so
    blend() leaves it out and attaches it to the result instead."""
    low, mid, high = sorted(float(v) for v in size)
    return high <= 0 or low < LONG_THIN * high or low < FLAT * mid


def edge_width(voxel, softness):
    """Metres over which two parts' colours meet on the blended surface."""
    soft = min(1.0, max(0.0, float(softness)))
    return voxel * (EDGE_VOXELS[0] + (EDGE_VOXELS[1] - EDGE_VOXELS[0]) * soft)


def weights(distances, width):
    """Each colour's share at a point ``distances`` (one per colour, ``None`` when farther than ``width``) from the
    parts of that colour: 1 on a part, falling to 0 at ``width`` away, normalised to sum to 1."""
    raw = [0.0 if d is None else max(0.0, 1.0 - float(d) / width) for d in distances]
    total = sum(raw)
    if total <= 0:
        return [0.0] * len(raw)
    return [r / total for r in raw]


def other_colour(shares, colours, own):
    """``(r, g, b, mix)`` for a face of colour ``own``: the other colours' mean by share, and how much of it shows
    (``1 - own share``), so a face shows ``own * (1 - mix) + other * mix``, the same on both sides of an edge."""
    mix = 1.0 - shares[own]
    if mix <= 1e-6:
        return (0.0, 0.0, 0.0, 0.0)
    rgb = [sum(shares[m] * colours[m][c] for m in range(len(shares)) if m != own) / mix for c in range(3)]
    return (rgb[0], rgb[1], rgb[2], mix)
