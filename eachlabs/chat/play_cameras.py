"""Which cameras Play can look through, in what order, and the line under each name in the menu. No ``bpy``.

A camera is given as its name and its transform keys: one list of ``(frame, value)`` per animated channel, its
parents' channels included, read on the Blender side (``playback.py``).
"""

CHAT_MOVE = "the chat's camera move · %s"
MOVE = "camera move · %s"
STILL = "still"


def moves(curves, frame_range):
    """True when one of the channels changes between two keys whose span overlaps the frame range."""
    start, end = frame_range
    for keys in curves:
        keys = sorted(keys)
        for (f0, v0), (f1, v1) in zip(keys, keys[1:]):
            if abs(v1 - v0) > 1e-6 and f0 < end and f1 > start:
                return True
    return False


def seconds_text(frame_range, fps):
    """The frame range as playback time: ``5 s``, ``2.5 s``."""
    frames = frame_range[1] - frame_range[0] + 1
    seconds = frames / fps if fps > 0 else 0.0
    return "%g s" % round(max(seconds, 0.0), 1)


def order(names, chat_camera="", scene_camera=""):
    """The chat's own camera first, else the scene camera, then the others by name."""
    first = chat_camera if chat_camera in names else scene_camera if scene_camera in names else ""
    rest = sorted((n for n in names if n != first), key=lambda n: (n.lower(), n))
    return ([first] if first else []) + rest


def chosen(names, wanted, chat_camera="", scene_camera=""):
    """The camera Play looks through: the one the person chose while it exists, else the first of ``order``;
    ``""`` when the scene has no camera."""
    if wanted in names:
        return wanted
    listed = order(names, chat_camera, scene_camera)
    return listed[0] if listed else ""


def hint(curves, frame_range, fps, chat_own):
    if not moves(curves, frame_range):
        return STILL
    return (CHAT_MOVE if chat_own else MOVE) % seconds_text(frame_range, fps)


def menu(cameras, wanted, chat_camera, scene_camera, frame_range, fps):
    """``(name, hint, chosen)`` per camera in ``order``; ``cameras``: ``{name: curves}``."""
    names = list(cameras)
    pick = chosen(names, wanted, chat_camera, scene_camera)
    return [(name, hint(cameras[name], frame_range, fps, name == chat_camera), name == pick)
            for name in order(names, chat_camera, scene_camera)]
