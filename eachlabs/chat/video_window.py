"""Open Sequencer: a window with the finished shot video on top, the scene seen through the video's camera below it
and the Sequencer timeline at the bottom, played together from the video's first frame. Main thread only.

The strip sits in the camera's own scene, so one playhead drives the preview and the 3D view. On 5.x a Sequencer
shows its workspace's sequencer scene, so the window gets a workspace of its own (``WORKSPACE``) pointing at that
scene: the person's workspaces keep theirs. The 3D view looks through the camera with its own local camera, so the
scene camera is not changed. Playback stops at the strip's end, or at the scene's last frame when the strip runs
past it (the person's frame range is never changed), or when it wraps back to the start.

Every operator here runs with a checked window, area and region: a Sequencer operator run from a timer without its
timeline region crashes Blender 5.2."""

import bpy
from bpy.app.handlers import persistent

from .. import compat
from . import video_track

WORKSPACE = "Video Preview"
TAG = "eachlabs_video_preview"  # on the window's workspace: only tagged workspaces are ever removed
STEP = 0.15  # seconds between the steps that build the window; each waits for Blender to apply the last
WAIT_STEPS = 20  # steps to wait for the new workspace to show before giving up
TOP, BOTTOM = 0.55, 0.45  # the first split's lower share (3D view and timeline), then the timeline's share of it

_WATCH = {}  # while the window plays: scene name, window pointer, the frame to stop at, the last frame seen
_OPEN = {}  # the window opened last: its pointer, and the token of the build laying it out
_BUILDS = [0]  # counter for builds and plays: a build whose token left ``_OPEN`` stops, a stale stop does nothing


def find_strip(scene, name):
    editor = scene.sequence_editor
    return next((s for s in compat.all_strips(editor) if s.name == name), None) if editor else None


def open_window(context, scene, strip_name, camera):
    """Open the window for strip ``strip_name`` of ``scene`` looking through ``camera``, or play again in the one
    already open. Raises ``RuntimeError`` when the strip is gone."""
    strip = find_strip(scene, strip_name)
    if strip is None:
        raise RuntimeError("The video is no longer in the Sequencer of %s." % scene.name)
    win = _window(_OPEN.get("window"))
    if win is not None and _areas(win):
        _play(win, scene, strip)
        return win
    wm = context.window_manager
    before = {w.as_pointer() for w in wm.windows}
    with context.temp_override(window=context.window):
        bpy.ops.wm.window_new()
    win = next((w for w in wm.windows if w.as_pointer() not in before), None)
    if win is None:
        raise RuntimeError("Blender did not open a new window.")
    _BUILDS[0] += 1
    _OPEN.update(window=win.as_pointer(), build=_BUILDS[0])
    steps = _build(win.as_pointer(), _BUILDS[0], scene.name, strip_name, camera.name if camera else "")

    def step():
        try:
            return next(steps)
        except StopIteration:
            return None

    bpy.app.timers.register(step, first_interval=STEP)
    return win


def shows(window):
    """True for the video's window: the prompt bar stays out of its 3D view."""
    return window is not None and bool(_OPEN) and window.as_pointer() == _OPEN.get("window")


def _window(pointer):
    """The window with ``pointer`` while it is open, else ``None``."""
    wm = bpy.context.window_manager
    return next((w for w in wm.windows if w.as_pointer() == pointer), None) if wm and pointer else None


def _region(area):
    return next((r for r in area.regions if r.type == "WINDOW"), None) if area is not None else None


def _areas(win):
    """``(preview, view, timeline)`` of a finished window, top to bottom, else ``None``."""
    areas = sorted(win.screen.areas, key=lambda a: -a.y)
    if len(areas) != 3:
        return None
    preview, view, timeline = areas
    if (preview.type != "SEQUENCE_EDITOR" or preview.spaces.active.view_type != "PREVIEW" or view.type != "VIEW_3D"
            or timeline.type != "SEQUENCE_EDITOR" or timeline.spaces.active.view_type != "SEQUENCER"):
        return None
    return preview, view, timeline


def _run(win, area, op, **kwargs):
    """Run ``op`` in ``area`` of ``win`` when the window, the area and its main region all still exist."""
    if win is None or _window(win.as_pointer()) is None or area not in list(win.screen.areas):
        return False
    region = _region(area)
    if region is None:
        return False
    with bpy.context.temp_override(window=win, area=area, region=region):
        op(**kwargs)
    return True


def _build(pointer, token, scene_name, strip_name, camera_name):
    """Timer steps that lay the new window out. A step whose window was closed, or whose build was cancelled (a
    file load, the add-on turned off, another window opened), ends the build."""

    def alive():
        return _window(pointer) if _OPEN.get("build") == token else None

    win = alive()
    if win is None:
        return
    _drop_unused_workspaces()
    first = win.workspace
    with bpy.context.temp_override(window=win):
        bpy.ops.workspace.duplicate()
    for _ in range(WAIT_STEPS):  # the workspace changes once Blender handles the operator's notifier
        yield STEP
        win = alive()
        if win is None:
            return
        if win.workspace != first:
            break
    else:
        return
    scene = bpy.data.scenes.get(scene_name)
    if scene is None:
        return
    workspace = win.workspace
    workspace.name = WORKSPACE
    workspace[TAG] = True
    if hasattr(workspace, "sequencer_scene"):
        workspace.sequencer_scene = scene
    if win.scene != scene:
        win.scene = scene
    while len(win.screen.areas) > 1:  # one area to split into three
        smallest = min(win.screen.areas, key=lambda a: a.width * a.height)
        if not _run(win, smallest, bpy.ops.screen.area_close):
            return
        yield STEP
        win = alive()
        if win is None:
            return
    for factor in (TOP, BOTTOM):
        lowest = min(win.screen.areas, key=lambda a: a.y)
        if not _run(win, lowest, bpy.ops.screen.area_split, direction="HORIZONTAL", factor=factor):
            return
        yield STEP
        win = alive()
        if win is None:
            return
    preview, view, timeline = sorted(win.screen.areas, key=lambda a: -a.y)
    for area, view_type in ((preview, "PREVIEW"), (timeline, "SEQUENCER")):
        area.type = "SEQUENCE_EDITOR"
        area.spaces.active.view_type = view_type
    view.type = "VIEW_3D"
    yield STEP  # the areas get their regions on the next redraw
    win = alive()
    scene = bpy.data.scenes.get(scene_name)
    areas = _areas(win) if win is not None else None
    strip = find_strip(scene, strip_name) if scene is not None else None
    if areas is None or strip is None:
        return
    _configure(win, areas, scene.objects.get(camera_name))
    yield STEP
    win = alive()
    if win is not None and _areas(win):
        _play(win, scene, strip)


def _configure(win, areas, camera):
    preview, view, timeline = areas
    space = preview.spaces.active
    space.show_region_toolbar = space.show_region_footer = False
    space.use_zoom_to_fit = True
    space = view.spaces.active
    space.show_region_toolbar = space.show_region_tool_header = False
    if camera is not None:
        space.use_local_camera, space.camera = True, camera
        space.region_3d.view_perspective = "CAMERA"
        _run(win, view, bpy.ops.view3d.view_center_camera)
    _run(win, timeline, bpy.ops.sequencer.view_all)


def _play(win, scene, strip):
    """Play from the strip's first frame; ``_on_frame`` stops at its last."""
    areas = _areas(win)
    if areas is None:
        return
    _WATCH.clear()  # the jump back to the first frame below is no wrap of this playback
    if win.screen.is_animation_playing:
        _run(win, areas[1], bpy.ops.screen.animation_cancel, restore_frame=False)
    first = compat.strip_start(strip)
    scene.frame_set(first)
    _BUILDS[0] += 1
    end = video_track.stop_frame(compat.strip_end(strip), scene.frame_end)
    _WATCH.update(scene=scene.name, window=win.as_pointer(), end=end, last=first, id=_BUILDS[0])
    if not _run(win, areas[1], bpy.ops.screen.animation_play):
        stop()


def stop():
    """Stop the window's playback and forget it; nothing when it does not play."""
    win = _window(_WATCH.get("window"))
    _WATCH.clear()
    if win is not None and win.screen.is_animation_playing:
        areas = _areas(win)
        if areas is not None:
            _run(win, areas[1], bpy.ops.screen.animation_cancel, restore_frame=False)


def _cancel_anywhere():
    """Stop the playback the closed window started, from whichever window still plays."""
    for win in bpy.context.window_manager.windows:
        area = next((a for a in win.screen.areas if a.type in ("VIEW_3D", "SEQUENCE_EDITOR", "DOPESHEET_EDITOR")),
                    None)
        if win.screen.is_animation_playing and area is not None:
            _run(win, area, bpy.ops.screen.animation_cancel, restore_frame=False)
            return


def close():
    """Stop playback and close the window, when it is open, and remove its workspace."""
    stop()
    win = _window(_OPEN.pop("window", None))
    _OPEN.pop("build", None)
    if win is not None:
        with bpy.context.temp_override(window=win):
            bpy.ops.wm.window_close()
    bpy.app.timers.register(lambda: _drop_unused_workspaces() or None, first_interval=0.0)


def _drop_unused_workspaces():
    """Remove the workspaces this add-on made for earlier windows (tagged), unless a window still shows one."""
    shown = {w.workspace for w in bpy.context.window_manager.windows}
    old = [ws for ws in bpy.data.workspaces if ws.get(TAG) and ws not in shown]
    if old:
        bpy.data.batch_remove(old)


# The handlers stay registered while the add-on is on and do nothing while ``_WATCH`` is empty: removing a handler
# from inside a handler makes Blender skip the next one in the list, possibly another add-on's.

@persistent
def _on_frame(scene, *_args):
    if not _WATCH or scene.name != _WATCH["scene"]:
        return
    if _window(_WATCH["window"]) is None:  # closed while it played; on 5.x playback can go on in another window
        _WATCH.clear()
        bpy.app.timers.register(lambda: _cancel_anywhere() or None, first_interval=0.0)
        return
    frame = scene.frame_current
    if video_track.ends(frame, _WATCH["last"], _WATCH["end"]):
        playing = _WATCH["id"]  # a stop that runs after a new Play leaves the new one alone
        bpy.app.timers.register(lambda: (_WATCH.get("id") == playing and stop()) or None, first_interval=0.0)
    _WATCH["last"] = frame


@persistent
def _on_stop(*_args):
    _WATCH.clear()


@persistent
def _on_load(*_args):
    _WATCH.clear()
    _OPEN.clear()  # also cancels a build under way


@persistent
def _on_save(*_args):
    try:
        _drop_unused_workspaces()  # a closed window's workspace is not saved into the person's file
    except (RuntimeError, ReferenceError):
        pass


_HANDLERS = (("frame_change_post", _on_frame), ("animation_playback_post", _on_stop), ("load_pre", _on_load),
             ("save_pre", _on_save))


def register():
    for name, func in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if func not in handlers:
            handlers.append(func)


def unregister():
    stop()
    _OPEN.clear()
    for name, func in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if func in handlers:
            handlers.remove(func)
