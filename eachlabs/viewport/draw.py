"""Drawing the prompt bar in the 3D viewport: its scale, insets around side panels, the Skia frame as a GPU texture."""

import bpy
import gpu
import time
import traceback
from gpu_extras.batch import batch_for_shader

from .. import chat_run, compat, preferences
from ..chat import playback, selection, video_window
from . import hover, live
from ..ui import bar, bar_state


def scale(context):
    """Image pixels per logical pixel: Blender's UI scale, which already includes Retina's pixel size."""
    return max(0.5, context.preferences.system.ui_scale)



def _api_key():
    try:
        return preferences.settings(bpy.context)["api_key"]
    except Exception:  # A broken setting only matters for the key message.
        return ""



def current_state(now=None):
    now = time.monotonic() if now is None else now
    chat = chat_run.STATE
    if chat.error and bar_state._error_text(chat.error) in bar_state.KEY_ERRORS:
        if live.overlay.UI["key_seen"] is None:
            live.overlay.UI["key_seen"] = _api_key()
    else:
        live.overlay.UI["key_seen"] = None
    changed = live.overlay.UI["key_seen"] is not None and _api_key() != live.overlay.UI["key_seen"]
    caret_on = int((now - live.overlay.UI["blink_from"]) / live.overlay.BLINK) % 2 == 0
    phase = (int(now * live.overlay.SPIN_STEPS) % live.overlay.SPIN_STEPS) / live.overlay.SPIN_STEPS if chat.running else 0.0
    finished = chat.status in ("done", "stopped", "cancelled") and not chat.running
    undoable = chat_run.undoable_stages() if finished else None
    asking = bar_state.consent_shown(live.overlay.UI["consent"], preferences.code_allowed(bpy.context))
    if chat.running:
        live.overlay.UI["quality_menu"] = live.overlay.UI["camera_menu"] = False  # no menus while a run is going
    playing = playback.is_playing()
    cameras = playback.menu(bpy.context.scene) if finished and chat.status == "done" and not playing else []
    thing = ""
    if chat.target in ("asset", "character") and not chat.running:
        thing = bar_state.thing_label(selection.selected_things(bpy.context))
    state = bar_state.from_chat(chat, live.overlay.FIELD, live.overlay.UI["focused"], now, caret_on, phase, changed, chat_run.has_scene(),
                                undoable, consent=asking,
                                quality=preferences.quality(bpy.context), menu=live.overlay.UI["quality_menu"],
                                asked_open=live.overlay.UI["asked_open"],
                                advanced=preferences.advanced_tools(bpy.context), tab=chat.target,
                                cameras=cameras, camera_menu=live.overlay.UI["camera_menu"], playing=playing,
                                thing=thing)
    state.thinking_seconds = float(int(state.thinking_seconds))
    from . import fold  # it calls this module's redraw

    state.folded = fold.folded(state, now)
    return state



def _key(state, width, s):
    f = state.field
    values = sorted((k, v) for k, v in vars(state).items() if k != "field")
    return repr((values, f.text, f.caret, f.anchor, width, s))



def _texture(frame):
    import numpy

    pixels = numpy.frombuffer(frame.rgba, dtype=numpy.uint8).reshape(frame.height, frame.width, 4)[::-1]
    data = pixels.astype(numpy.float32) / 255.0
    if compat.overlay_is_linear():
        rgb, alpha = data[..., :3], data[..., 3:]
        straight = numpy.divide(rgb, alpha, out=numpy.zeros_like(rgb), where=alpha > 0)
        linear = numpy.where(straight <= 0.04045, straight / 12.92, ((straight + 0.055) / 1.055) ** 2.4)
        data[..., :3] = linear * alpha
    data = data.ravel()
    buffer = gpu.types.Buffer("FLOAT", data.size, data)
    return gpu.types.GPUTexture((frame.width, frame.height), format="RGBA8", data=buffer)



def _draw():
    try:
        live.overlay._placed.pop(bpy.context.region.as_pointer(), None)  # no hit area unless this draw succeeds
        if video_window.shows(bpy.context.window):  # the video's window shows the scene, not the chat
            return
        if live.overlay.UI["fail_draw"]:
            raise RuntimeError(live.overlay.FORCED_FAILURE)
        _draw_bar(bpy.context)
    except Exception as exc:  # Drawing must never break the viewport.
        live.overlay.UI["draw_errors"] += 1
        if str(exc) == live.overlay.FORCED_FAILURE:
            print(live.overlay.FORCED_FAILURE, flush=True)
        elif live.overlay.UI["draw_errors"] <= 3:
            traceback.print_exc()



def insets(area, region):
    """Px of ``region`` covered on the left and right by an overlapping toolbar or sidebar."""
    left = right = 0
    for r in area.regions:
        if r.type not in ("TOOLS", "UI") or r.width <= 1 or r.x < region.x or r.x + r.width > region.x + region.width:
            continue
        if r.x + r.width / 2 < region.x + region.width / 2:
            left = max(left, r.x + r.width - region.x)
        else:
            right = max(right, region.x + region.width - r.x)
    return left, right



def bottom_inset(area, region):
    """Px of ``region`` covered along the bottom by an overlapping asset shelf and its header."""
    bottom = 0
    for r in area.regions:
        if r.type in live.overlay._SHELF and r.width > 1 and r.height > 1 and region.y <= r.y < region.y + region.height:
            bottom = max(bottom, r.y + r.height - region.y)
    return bottom



def _draw_bar(context):
    region = context.region
    s = scale(context)
    left, right = insets(context.area, region)
    width = bar_state.bar_width((region.width - left - right) / s)
    state = current_state()
    key = _key(state, width, s)
    ptr = region.as_pointer()
    cached = live.overlay._cache.get(ptr)
    if cached is None or cached[0] != key:
        frame = bar.render(state, width, s)
        cached = live.overlay._cache[ptr] = (key, frame, _texture(frame))
    _, frame, texture = cached
    origin = bar_state.image_origin((frame.width, frame.height), frame.bar_rect, region.width, s, left, right,
                                    bottom_inset(context.area, region))
    live.overlay._placed[ptr] = (origin, frame, width, s, state)
    _quad(texture, origin[0], origin[1], frame.width, frame.height)
    hover.draw_tip(region, origin, frame, s, left, right)


def _quad(texture, x, y, w, h):
    """``texture`` on a rectangle of the region, bottom-left at (x, y) px, premultiplied."""
    shader = gpu.shader.from_builtin("IMAGE")
    batch = batch_for_shader(shader, "TRI_FAN", {"pos": ((x, y), (x + w, y), (x + w, y + h), (x, y + h)),
                                                 "texCoord": ((0, 0), (1, 0), (1, 1), (0, 1))})
    blend = gpu.state.blend_get()
    gpu.state.blend_set("ALPHA_PREMULT")
    try:
        shader.bind()
        shader.uniform_sampler("image", texture)
        batch.draw(shader)
    finally:
        gpu.state.blend_set(blend)



def tag_redraw():
    wm = bpy.context.window_manager
    for window in wm.windows if wm else ():
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "WINDOW":
                        region.tag_redraw()
