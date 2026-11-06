"""The bar's Video tab in Blender: the ``Shot`` the bar draws from (the scene's cameras, the chosen settings, the
photos from the camera's measured view), when that view is measured, and what the tab's chips and buttons do. Main
thread only.

Nothing heavy runs while the bar draws or after an edit: ``shot`` only reads the last measure. The view is measured
when the tab opens and when its camera or aspect changes (on a timer, so the click draws first), and afresh on Send,
so the confirm card's price is what the scene shows now. Make video carries that pick into the start, which refuses
and asks again when the scene changed since. A duration only picks again from the measure."""

import math

import bpy

from .. import main_thread, render_export
from .. import timing as scene_timing
from ..shot import models, start, timing, view_cache
from ..ui import video_tab as view, video_texts as V
from . import make_video, play_cameras, playback
from .live import chat_run

MEASURE_AFTER = 0.05  # seconds after a click before its measure, so the click draws first
WAIT = 0.5  # seconds between tries while the animation plays, Blender renders or a tool runs
_wanted = []  # [(scene name, camera name, aspect, ui or None)]: the timer's measure; ui: open the confirm card after


def _fps(scene):
    return scene_timing.scene_fps(scene.render.fps, scene.render.fps_base)


def _cameras(scene):
    """``(name, hint, moves)`` per camera, in the Play menu's order."""
    return [(name, hint, hint != play_cameras.STILL) for name, hint, _chosen in playback.menu(scene)]


def _shown(state):
    return state.video_job, state.video


def shot(context, ui, prompt=""):
    """The Video tab's ``Shot`` for the scene as it is now. Reads only: the photos come from the last measure."""
    scene, state = context.scene, chat_run.STATE
    cameras = _cameras(scene) if scene is not None else []
    names = [name for name, _hint, _moves in cameras]
    camera = state.video_camera if state.video_camera in names else (playback.chosen(scene) if names else "")
    s = view.Shot(cameras=cameras, camera=camera, aspect=state.video_aspect, resolution=state.video_resolution,
                  menu=ui["video_menu"], confirm=ui["video_confirm"], stop_ask=ui["video_stop_ask"],
                  card=ui["video_hidden"] != _shown(state), prompt=prompt, changed=ui["video_changed"])
    if not camera:
        return s
    fps, moves = _fps(scene), view.moves(s)
    s.longest = timing.longest(scene.frame_start, scene.frame_end, fps, moves)
    default = timing.default_seconds(scene.frame_start, scene.frame_end, fps, moves)
    s.seconds = max(models.VIDEO["min_seconds"], min(state.video_length or default, s.longest))
    s.move_seconds = math.ceil((scene.frame_end - scene.frame_start + 1) / fps - 1e-9)
    cam = scene.objects[camera]
    if view_cache.measured(scene, cam, s.aspect):
        s.photos = {d: view_cache.photos(scene, cam, s.aspect, d) for d in set(view.durations(s)) | {s.seconds}}
    return s


def _free():
    """True when measuring may step through the frames now: nothing plays, renders or holds a modal tool."""
    return not playback.is_playing() and not render_export.busy() and view_cache.can_measure()


def measure_soon(context, ui, then_confirm=False):
    """Measure the tab's view on a timer: when the tab opens, the camera or aspect changes, or Send has to wait for
    a tool. ``then_confirm``: open the confirm card once measured."""
    s = shot(context, ui)
    if not s.camera:
        return
    _wanted[:] = [(context.scene.name, s.camera, s.aspect, ui if then_confirm else None)]
    if bpy.app.timers.is_registered(_measure):
        bpy.app.timers.unregister(_measure)
    bpy.app.timers.register(_measure, first_interval=MEASURE_AFTER)


def _measure():
    """The timer: measure what was asked for if its scene and camera are still there, once Blender is free."""
    if not _wanted:
        return None
    if not _free():
        return WAIT
    scene_name, camera_name, aspect, ui = _wanted.pop()
    scene = bpy.data.scenes.get(scene_name)
    cam = scene.objects.get(camera_name) if scene is not None else None
    if cam is not None and cam.type == "CAMERA":
        try:
            view_cache.measure(scene, cam, aspect)
        except (RuntimeError, ReferenceError) as exc:
            print("Eachlabs: measuring the camera's view: %s" % exc)
            ui = None
        if ui is not None and bpy.context.scene == scene:
            _confirm(bpy.context, ui)
    main_thread.tag_redraw()
    return None


def forget():
    """Another file opens: no measure is waiting."""
    _wanted.clear()
    if bpy.app.timers.is_registered(_measure):
        bpy.app.timers.unregister(_measure)


def opened(context, ui):
    """The tab was chosen: measure its camera's view."""
    measure_soon(context, ui)


def _set(context, ui, setting, value):
    state = chat_run.STATE
    if setting == "camera":
        state.video_camera = value
    elif setting == "aspect":
        state.video_aspect = value
    elif setting == "resolution":
        state.video_resolution = value
    elif setting == "seconds":
        state.video_length = value
    if setting in ("camera", "aspect"):
        measure_soon(context, ui)


def _confirm(context, ui, changed=False):
    """Open the confirm card on the last measure, keeping the key frames it priced for Make video."""
    s = shot(context, ui)
    cam = context.scene.objects.get(s.camera)
    if cam is None or not view_cache.measured(context.scene, cam, s.aspect):
        return False
    frames = view_cache.frames(context.scene, cam, s.aspect, view_cache.plan_for(context.scene, s.seconds))
    ui["video_priced"] = (context.scene.name, s.camera, s.aspect, s.seconds, tuple(frames))
    ui["video_confirm"], ui["video_menu"], ui["video_changed"] = True, "", changed
    return True


def ask(context, ui, field):
    """Send on the Video tab: measure the scene afresh, then open the confirm card with that price. Nothing starts
    here. While a tool or playback holds Blender, the measure and the card wait for it."""
    s = shot(context, ui, field.text)
    if view.send_block(s, chat_run.STATE.video in make_video.RUNNING):
        return False
    ui["video_menu"] = ""
    if not _free():
        measure_soon(context, ui, then_confirm=True)
        return False
    view_cache.measure(context.scene, context.scene.objects[s.camera], s.aspect)
    return _confirm(context, ui)


def make(context, ui, field):
    """Make video on the confirm card: the only button that starts one, with the key frames the card priced."""
    s = shot(context, ui, field.text)
    priced = ui.get("video_priced") or ()
    ui["video_confirm"] = ui["video_stop_ask"] = ui["video_changed"] = False
    if view.send_block(s, chat_run.STATE.video in make_video.RUNNING):
        return
    if tuple(priced[:4]) != (context.scene.name, s.camera, s.aspect, s.seconds):
        ask(context, ui, field)  # the settings moved under the card: price them again
        return
    request = start.Request(prompt=field.text.strip(), camera=s.camera, aspect=s.aspect, resolution=s.resolution,
                            seconds=s.seconds, frames=priced[4])
    try:
        started = make_video.video_start(context, request)
    except start.SceneChanged:
        _confirm(context, ui, changed=True)  # the start measured afresh: the card shows the new price
        return
    ui["video_hidden"] = None
    if started is not None:
        field.clear()


def _load(request, field):
    """The settings and direction of an earlier video back on the tab."""
    state = chat_run.STATE
    state.video_camera, state.video_aspect = request["camera"], request["aspect"]
    state.video_resolution, state.video_length = request["resolution"], request["seconds"] or 0
    field.clear()
    field.paste(request.get("prompt") or "")


def _request():
    job = make_video.job_of(("failed", "stopped"))
    return (job.context.get("shot") or {}).get("request") if job else None


def retry(context, ui, field):
    """Retry video: the failed video's settings and direction on the tab, then the confirm card with its price for
    the scene as it is now. A camera the open scene lacks falls back to its Play camera, which the card names."""
    request = _request()
    if request is None:
        return
    _load(request, field)
    ask(context, ui, field)


def act(context, name, ui, field):
    """A click on the Video tab's chips, menu items or buttons. Returns True when the bar should take the keys."""
    if name in V.CHIP_HITS:
        which = V.CHIPS[V.CHIP_HITS.index(name)]
        ui["video_menu"] = "" if ui["video_menu"] == which else which
        ui["video_confirm"] = False  # a setting may change: Send prices it again
        return bool(ui["video_menu"])
    if name in V.MENU_HITS:
        got = view.picked(shot(context, ui), name)
        ui["video_menu"] = ""
        if got is not None:
            _set(context, ui, *got)
        return False
    if name == "video_make":
        make(context, ui, field)
    elif name == "video_cancel":
        ui["video_confirm"] = ui["video_changed"] = False
    elif name == "video_stop":
        ui["video_stop_ask"] = True
    elif name in ("video_stop_yes", "video_stop_no"):
        ui["video_stop_ask"] = False
        if name == "video_stop_yes":
            make_video.stop()
    elif name == "video_retry":
        retry(context, ui, field)
    elif name in ("video_another", "video_edit"):
        if name == "video_edit":
            request = _request()
            if request is not None:
                _load(request, field)
        ui["video_hidden"], ui["video_confirm"] = _shown(chat_run.STATE), False
        return True
    return False
