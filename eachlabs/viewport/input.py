"""The bar's input: which region a press lands in, clicks, drags and double clicks in the field, and typing."""

import time

from .. import chat_run
from . import draw, hover, live
from ..ui import bar, bar_state, tokens as T


def _target(context, event):
    """(control id, image point, placed) under the mouse, or None outside every drawn bar."""
    screen = context.window.screen if context.window else None
    for area in screen.areas if screen else ():
        if area.type != "VIEW_3D":
            continue
        for region in area.regions:
            if region.type == "WINDOW" and _inside(region, event.mouse_x, event.mouse_y):
                return _target_at(area, region, event.mouse_x, event.mouse_y)
    return None



def _target_at(area, region, x, y):
    """The bar control at window px (x, y) in this 3D view's main region, as ``_target``."""
    if any(r.type in live.overlay._FLOATING and _inside(r, x, y) for r in area.regions):
        return None  # a sidebar, toolbar, HUD or asset shelf drawn over the view gets its own clicks
    placed = live.overlay._placed.get(region.as_pointer())
    if placed is None or not _inside(region, x, y):
        return None
    origin, frame = placed[0], placed[1]
    point = bar_state.to_image(x - region.x, y - region.y, origin, frame.height)
    name = bar_state.hit(frame.hits, *point)
    return (name, point, placed) if name else None



def _inside(region, x, y):
    return region.width > 1 and region.x <= x < region.x + region.width and region.y <= y < region.y + region.height



def _owns(event):
    if event.type in live.overlay._FIELD_KEYS or event.type == "TEXTINPUT":
        return True
    command = event.oskey if live.overlay._MAC else event.ctrl and not event.alt
    if command:
        return event.type in live.overlay._COMMAND_KEYS
    return bool(event.unicode) and event.unicode.isprintable()



def _double_click_s(context):
    """Blender's double-click time, in seconds, from the person's preferences."""
    try:
        return context.preferences.inputs.mouse_double_click_time / 1000.0
    except AttributeError:
        return 0.35



def _field_index(placed, point):
    """Caret index in the prompt field for an image point, also outside the field while dragging."""
    _, frame, width, s, state = placed
    hx, hy = frame.hits["field"][:2]
    return bar.index_at(state, width, (point[0] - hx) / s, (point[1] - hy) / s)



def _click(context, event, target):
    name, point, placed = target
    hover.clicked()
    if name != "quality" and bar_state.picked(name) is None:
        live.overlay.UI["quality_menu"] = False  # a click anywhere but the menu closes it
    if name != "play_menu" and name not in T.CAMERA_HITS:
        live.overlay.UI["camera_menu"] = False  # the same for the camera menu
    live.overlay.UI["drag"] = None
    if name in ("field", "bar"):
        if name == "field" and "field" in placed[1].hits:
            index = _field_index(placed, point)
            now, last = time.monotonic(), live.overlay.UI.get("last_click")
            double = event.value == "DOUBLE_CLICK" or (
                last is not None and now - last[0] <= _double_click_s(context) and abs(index - last[1]) <= 1)
            live.overlay.UI["last_click"] = None if double else (now, index)
            if double:
                live.overlay.FIELD.select_word(index)
            else:
                live.overlay.FIELD.set_caret(index, extend=event.shift)
                # A drag from here selects; the region is kept, as every redraw places the bar anew.
                live.overlay.UI["drag"] = next((ptr for ptr, p in live.overlay._placed.items() if p is placed), None)
        live.overlay.focus(context)
    else:
        live.overlay._act(context, name)



def _drag(context, event):
    """A mouse move while a press that started in the prompt field is held: select up to the mouse."""
    ptr = live.overlay.UI.get("drag")
    placed = live.overlay._placed.get(ptr) if ptr is not None else None
    if placed is None or "field" not in placed[1].hits or event.type not in ("MOUSEMOVE", "INBETWEEN_MOUSEMOVE"):
        return False
    origin, frame = placed[0], placed[1]
    screen = context.window.screen if context.window else None
    for area in screen.areas if screen else ():
        for region in area.regions:
            if region.as_pointer() == ptr:
                point = bar_state.to_image(event.mouse_x - region.x, event.mouse_y - region.y, origin, frame.height)
                live.overlay.FIELD.drag_to(_field_index(placed, point))
                live.overlay.UI["blink_from"] = time.monotonic()
                draw.tag_redraw()
                return True
    return False



def _type(context, event):
    result = live.overlay.FIELD.handle(event.type, ctrl=event.ctrl, alt=event.alt, shift=event.shift, cmd=event.oskey,
                          char=event.unicode)
    live.overlay.UI["blink_from"] = time.monotonic()
    wm = context.window_manager
    if result == "submit":
        live.overlay.submit(context)
    elif result == "blur" and (live.overlay.UI["quality_menu"] or live.overlay.UI["camera_menu"]):
        live.overlay.UI["quality_menu"] = live.overlay.UI["camera_menu"] = False  # Esc closes a menu first
    elif result == "blur" and live.overlay.UI["consent"]:
        live.overlay.consent(context, "cancel")  # Esc closes the card first; the bar keeps the keys
    elif result == "blur":
        if chat_run.STATE.running:
            live.overlay._stop()  # Esc in the focused bar stops the run; what was built stays
        live.overlay.blur()
    elif result == "copy":
        wm.clipboard = live.overlay.FIELD.copy()
    elif result == "cut":
        wm.clipboard = live.overlay.FIELD.cut()
    elif result == "paste":
        live.overlay.FIELD.paste(wm.clipboard)
    draw.tag_redraw()



def on_event(context, event):
    if event.type == "MOUSEMOVE":
        hover.track_event(context, event)
    if event.type in live.overlay._MOUSE:
        target = _target(context, event)
        if event.value in ("PRESS", "DOUBLE_CLICK"):
            live.overlay.UI["pressed"] = target is not None
            if target is None:
                live.overlay.UI["quality_menu"] = live.overlay.UI["camera_menu"] = False
                if live.overlay.UI["focused"]:
                    live.overlay.blur()
                return {"PASS_THROUGH"}
            if event.type == "LEFTMOUSE":
                _click(context, event, target)
            return {"RUNNING_MODAL"}
        taken = live.overlay.UI["pressed"]  # release, click and drag of a press that started on the bar
        if event.value == "RELEASE":
            live.overlay.UI["pressed"] = False
            live.overlay.UI["drag"] = None
        return {"RUNNING_MODAL"} if taken else {"PASS_THROUGH"}
    if live.overlay.UI["pressed"] and _drag(context, event):
        return {"RUNNING_MODAL"}
    if live.overlay.UI["pressed"] and event.value == "CLICK_DRAG":
        return {"RUNNING_MODAL"}
    if live.overlay.UI["focused"] and event.value == "PRESS" and _owns(event):
        _type(context, event)
        return {"RUNNING_MODAL"}
    return {"PASS_THROUGH"}



def _done(context):
    return not live.overlay.UI["focused"] and not live.overlay.UI["pressed"]
