"""The Final render's settings and file name: Cycles samples, depth of field from the subject's size, and where the
picture is saved. No ``bpy``."""

import os

SAMPLES = 256  # most Cycles samples; adaptive sampling stops earlier where the picture is clean
NOISE = 0.02  # adaptive sampling's noise threshold
BOUNCES = 8
FSTOP_PER_METRE = 2.0  # f-number per metre of the subject: a small subject gets a soft background, a house stays sharp
FSTOP = (2.8, 11.0)
SUFFIX = "-final"


def fstop(size_m):
    """The aperture that keeps a subject ``size_m`` across in focus while the background softens."""
    return round(min(FSTOP[1], max(FSTOP[0], float(size_m) * FSTOP_PER_METRE)), 1)


def output_path(blend_path, folder, exists):
    """Where the Final render is saved: next to the saved ``.blend`` as ``<name>-final.png``, else in ``folder``
    as ``untitled-final.png``; ``-2``, ``-3``… when that file ``exists(path)``."""
    if blend_path:
        folder = os.path.dirname(blend_path)
        stem = os.path.splitext(os.path.basename(blend_path))[0] or "untitled"
    else:
        stem = "untitled"
    path = os.path.join(folder, stem + SUFFIX + ".png")
    count = 2
    while exists(path):
        path = os.path.join(folder, "%s%s-%d.png" % (stem, SUFFIX, count))
        count += 1
    return path


def seconds_text(seconds):
    seconds = int(round(seconds))
    return "%d min %d s" % divmod(seconds, 60) if seconds >= 60 else "%d s" % seconds
