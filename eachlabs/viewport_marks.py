"""Live feedback in the 3D view: new objects flash with an orange outline, the camera move is a dashed line.

The state and timing are plain Python (no ``bpy`` at import) so they are unit-testable. Drawing and the
redraw timer import Blender lazily and exist only between ``register()`` and ``unregister()``.
"""

import math
import time
import traceback

FLASH_SECONDS = 1.2
ORANGE = (1.0, 60 / 255, 21 / 255)  # #ff3c15
LINE_WIDTH = 2.5
PATH_WIDTH = 2.0
DASH = 0.6  # drawn share of each dash period
DASHES = 24  # dash periods along the path
IDLE_INTERVAL = 0.5
FRAME_INTERVAL = 1 / 30
BOX_EDGES = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))

_flashes = {}  # object name -> start time
_path = {"points": [], "look_at": None, "alive": None}
_state = {"handle": None, "load": None, "errors": 0}


# -- state (pure) ---------------------------------------------------------------------------------

def flash(names, now):
    for name in names:
        _flashes[name] = now


def active_flashes(now):
    """``(name, alpha)`` for every flash still showing; alpha falls linearly from 1 to 0."""
    live = []
    for name, start in list(_flashes.items()):
        age = now - start
        if age >= FLASH_SECONDS:
            del _flashes[name]
        elif age >= 0:
            live.append((name, 1.0 - age / FLASH_SECONDS))
    return live


def has_flashes():
    return bool(_flashes)


def set_camera_path(points, look_at=None, alive=None):
    """Remember the camera move. ``alive``: a callable that says whether the run's objects still exist."""
    _path["points"] = [tuple(p) for p in points]
    _path["look_at"] = tuple(look_at) if look_at is not None else None
    _path["alive"] = alive


def camera_path():
    return list(_path["points"])


def camera_target():
    """The point the camera path's ring marks, or ``None``."""
    return _path["look_at"]


def clear():
    _flashes.clear()
    set_camera_path([])


def needs_redraw(running):
    return has_flashes() or (running and len(_path["points"]) >= 2)


# -- geometry -------------------------------------------------------------------------------------

def dashed(start, end, dashes=DASHES, share=DASH):
    """Line segment pairs along start -> end: ``dashes`` pieces, each drawn for ``share`` of its period."""
    points = []
    for i in range(dashes):
        for t in (i / dashes, (i + share) / dashes):
            points.append(tuple(s + (e - s) * t for s, e in zip(start, end)))
    return points


def circle(centre, right, up, radius, steps=24):
    """Segment pairs of a circle spanned by the ``right`` and ``up`` directions."""
    ring = [tuple(centre[k] + radius * (math.cos(2 * math.pi * i / steps) * right[k]
                                        + math.sin(2 * math.pi * i / steps) * up[k]) for k in range(3))
            for i in range(steps + 1)]
    return [p for i in range(steps) for p in (ring[i], ring[i + 1])]


# -- drawing --------------------------------------------------------------------------------------

def _colour(alpha):
    from . import compat

    rgb = ORANGE
    if compat.overlay_is_linear():  # the 4.x viewport encodes to sRGB on write
        rgb = tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb)
    return rgb + (alpha,)


def _lines(points, colour, width):
    import gpu
    from gpu_extras.batch import batch_for_shader

    shader = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    shader.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    shader.uniform_float("lineWidth", width)
    shader.uniform_float("color", colour)
    batch_for_shader(shader, "LINES", {"pos": points}).draw(shader)


def _box_segments(obj):
    from mathutils import Vector

    local = [tuple(c) for c in obj.bound_box]
    if len(local) != 8 or all(max(c[k] for c in local) - min(c[k] for c in local) <= 1e-9 for k in range(3)):
        return []  # an empty, a lamp or a camera has no box to outline
    corners = [tuple(obj.matrix_world @ Vector(c)) for c in local]
    return [corners[i] for edge in BOX_EDGES for i in edge]


def path_visible(context):
    """The path shows while the scene is not playing and the run's objects still exist."""
    if len(_path["points"]) < 2:
        return False
    screen = getattr(context, "screen", None)
    if screen is not None and screen.is_animation_playing:
        return False
    alive = _path["alive"]
    return alive is None or bool(alive())


def _draw():
    try:
        _draw_marks()
    except Exception:  # Drawing must never break the viewport.
        _state["errors"] += 1
        if _state["errors"] == 1:
            traceback.print_exc()


def _draw_marks():
    import bpy
    import gpu

    context = bpy.context
    shown = path_visible(context)
    flashes = active_flashes(time.monotonic())
    if not shown and not flashes:
        return
    blend, depth = gpu.state.blend_get(), gpu.state.depth_test_get()
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set("NONE")
    try:
        for name, alpha in flashes:
            try:
                obj = bpy.data.objects.get(name)
                segments = _box_segments(obj) if obj is not None else []
                if segments:
                    _lines(segments, _colour(alpha), LINE_WIDTH)
            except Exception:  # One bad object must not blank the other marks.
                _state["errors"] += 1
                if _state["errors"] == 1:
                    traceback.print_exc()
        if shown:
            start, end = _path["points"][0], _path["points"][-1]
            colour = _colour(1.0)
            _lines(dashed(start, end), colour, PATH_WIDTH)
            span = math.dist(start, end) or 1.0
            rv3d = context.region_data
            if rv3d is not None:
                inverse = rv3d.view_matrix.inverted()
                right, up = tuple(inverse.col[0][:3]), tuple(inverse.col[1][:3])
            else:
                right, up = (1, 0, 0), (0, 0, 1)
            _lines(circle(start, right, up, span * 0.012, 12), colour, 6.0)  # the dot at the start
            if _path["look_at"] is not None:
                _lines(circle(_path["look_at"], right, up, span * 0.03), colour, PATH_WIDTH)  # the ring
    finally:
        gpu.state.blend_set(blend)
        gpu.state.depth_test_set(depth)


# -- redraw timer and registration ----------------------------------------------------------------

def _redraw():
    import bpy

    wm = bpy.context.window_manager
    for window in wm.windows if wm else ():
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "WINDOW":
                        region.tag_redraw()


def _tick():
    try:
        from . import chat_run

        if needs_redraw(chat_run.STATE.running):
            _redraw()
            return FRAME_INTERVAL
    except Exception:  # The timer must keep re-arming.
        traceback.print_exc()
    return IDLE_INTERVAL


def kick():
    """Redraw soon and at frame rate while a flash runs, instead of waiting out the idle interval."""
    import bpy

    if _state["handle"] is None:
        return
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    bpy.app.timers.register(_tick, first_interval=0.01, persistent=True)


def active():
    return _state["handle"] is not None


def register():
    import bpy

    if bpy.app.background or _state["handle"] is not None:
        return
    _state["handle"] = bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_VIEW")
    _state["load"] = bpy.app.handlers.persistent(lambda _dummy: clear())
    bpy.app.handlers.load_post.append(_state["load"])
    kick()


def unregister():
    import bpy

    clear()
    if _state["handle"] is None:
        return
    bpy.types.SpaceView3D.draw_handler_remove(_state["handle"], "WINDOW")
    _state["handle"] = None
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    if _state["load"] in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_state["load"])
    _state["load"] = None
    _redraw()
