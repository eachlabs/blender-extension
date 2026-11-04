"""The prompt bar in the 3D Viewport: one textured quad per view, input, redraws.

Registered only when ``ui.bar.available()``; otherwise the sidebar shows a plain prompt field.
A press on the unfocused bar arrives through an invisible gizmo that covers the bar: a region's
gizmo handler runs before the active tool's keymap (3D Cursor, Annotate, sculpt and paint brushes),
which a keymap item cannot do. A LEFTMOUSE item in the 3D View keymap is the fallback for a press
the gizmo did not see; it passes the click through unless it hits the bar. A modal operator runs
only while the bar has focus or a press on it is held: Blender postpones autosave while any modal
operator runs, so one that always ran would turn autosave off. While it runs it passes every event
through except clicks on the bar and the keys the text field owns. Any error in drawing or input is
printed and passed through, so the viewport stays usable.
"""

import os
import sys
import time
import traceback

import bpy
import gpu
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader

from . import chat_run, compat, main_thread, preferences
from .ui import bar, bar_state
from .ui.text_field import TextField

SPIN_INTERVAL = 1 / 12  # redraws per second while a run is going
BLINK = 0.5  # caret on/off, seconds
SPIN_STEPS = 12
# Blender's own fonts, tried in this order for characters Inter lacks; the rest of the folder follows.
FALLBACK_FIRST = ("NotoSansSymbols2-Regular.woff2", "NotoSansSymbols-VariableFont_wght.woff2",
                  "NotoEmoji-VariableFont_wght.woff2", "Noto Sans CJK Regular.woff2")
FALLBACK_SKIP = ("Inter", "DejaVu", "lastresort")

_MAC = sys.platform == "darwin"
_MOUSE = {"LEFTMOUSE", "RIGHTMOUSE", "MIDDLEMOUSE"}
_FIELD_KEYS = {"RET", "NUMPAD_ENTER", "ESC", "TAB", "LEFT_ARROW", "RIGHT_ARROW", "UP_ARROW", "DOWN_ARROW", "HOME",
               "END", "BACK_SPACE", "DEL"}
_COMMAND_KEYS = {"A", "C", "X", "V", "Z", "Y"}
_FLOATING = {"UI", "TOOLS", "HUD", "ASSET_SHELF", "ASSET_SHELF_HEADER"}  # regions that can overlap the view
_SHELF = {"ASSET_SHELF", "ASSET_SHELF_HEADER"}  # along the bottom in sculpt and paint modes (5.x)
GIZMO_KEYMAP = "Eachlabs Prompt Bar"
FORCED_FAILURE = "EACHLABS-FORCED-DRAW-FAILURE"  # printed instead of a traceback by the GUI check's forced error
FOCUS_KEY = dict(type="SPACE", value="PRESS", shift=True, alt=True)  # unbound in Blender's default keymaps
CLICK_KEY = dict(type="LEFTMOUSE", value="PRESS", any=True)
_ACTIONS = {"retry": "chat_retry_stage", "undo": "chat_undo_stage", "frame": "chat_frame_result", "play": "chat_play",
            "prefs": "open_preferences", "network": "open_preferences", "new": "chat_new_scene",
            "code": "chat_show_code", "final": "chat_final_render"}
_ACTION_ARGS = {"network": {"section": "SYSTEM"}}  # System holds Network > Allow Online Access

FIELD = TextField()
UI = {"focused": False, "blink_from": 0.0, "mcp_checked": False, "key_seen": None, "pressed": False,
      "fail_draw": False, "draw_errors": 0, "consent": False,  # consent: the consent card is open
      "quality_menu": False,  # the quality menu is open
      "camera_menu": False,  # the Play button's camera menu is open
      "drag": None,  # the region of a press that started in the prompt field: a drag selects
      "last_click": None,  # (time, caret index) of the last press in the field, for a double click
      "asked_open": False,  # the bar shows the whole prompt of the run, not one line
      "hover": None,  # (region pointer, hit id) of the control under the mouse
      "tip": False,  # its tooltip shows (after TIP_DELAY)
      "tip_quiet": None}  # (region pointer, hit id) a click hid the tooltip of, until another control is hovered
_handle = None
_keymaps = []  # (keymap, item)
_placed = {}  # region pointer -> (origin, frame, width, scale, state) as last drawn
_cache = {}  # region pointer -> (key, frame, texture)
_tip_cache = {}  # (text, scale) -> (card, texture)
_tip_placed = {}  # region pointer -> (x, y, w, h) px of the tooltip card drawn there


def active():
    return _handle is not None


# -- state ----------------------------------------------------------------------------------------


# -- drawing --------------------------------------------------------------------------------------


# -- focus and actions ----------------------------------------------------------------------------


# -- input ----------------------------------------------------------------------------------------


class EACHLABS_OT_bar_input(bpy.types.Operator):
    """Runs while the bar has focus or a press on it is held, then ends."""
    bl_idname = "eachlabs.bar_input"
    bl_label = "Prompt bar input"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if _handle is None:
            return {"FINISHED", "PASS_THROUGH"}
        if _done(context):
            # Ending on a press or release of the click that blurred the bar would mark it handled,
            # and Blender then sends no CLICK: click-select would not select. End on the next event.
            return {"PASS_THROUGH"} if event.type in _MOUSE else {"FINISHED", "PASS_THROUGH"}
        try:
            result = on_event(context, event)
        except Exception:  # Input must never get stuck in the bar.
            traceback.print_exc()
            UI["focused"] = UI["pressed"] = False
            tag_redraw()
            return {"FINISHED", "PASS_THROUGH"}
        if _done(context) and (event.type not in _MOUSE or "PASS_THROUGH" not in result):
            return {"FINISHED"} | (result & {"PASS_THROUGH"})
        return result


class EACHLABS_OT_bar_click(bpy.types.Operator):
    """A press in the 3D view: acts when it is on the bar, else passes through to Blender."""
    bl_idname = "eachlabs.bar_click"
    bl_label = "Prompt bar click"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        try:
            target = _target(context, event)
            if target is None:
                return {"CANCELLED", "PASS_THROUGH"}
            UI["pressed"] = True  # the input operator takes the release and any drag
            start_input(context)
            _click(context, event, target)
        except Exception:  # A click must never be stuck in the bar.
            traceback.print_exc()
            UI["pressed"] = False
            return {"CANCELLED", "PASS_THROUGH"}
        return {"FINISHED"}


class EACHLABS_GT_bar(bpy.types.Gizmo):
    """Invisible; covers the drawn bar so a press on it reaches the bar before the active tool."""
    bl_idname = "EACHLABS_GT_bar"
    __slots__ = ("button",)

    def draw(self, context):
        pass

    def test_select(self, context, location):
        try:
            area, region = context.area, context.region
            if area is None or region is None:
                return -1
            hit = _target_at(area, region, region.x + int(location[0]), region.y + int(location[1]))
            hover.track(region, hit[0] if hit else None)  # Blender asks on every mouse move over the view
            if UI["focused"]:
                return -1  # the input operator takes presses while the bar has focus
            return 0 if hit is not None else -1
        except Exception:  # Hit testing must never take a press from Blender by mistake.
            traceback.print_exc()
            return -1

    def invoke(self, context, event):
        self.button = event.type
        UI["pressed"] = True  # until the release
        try:
            target = _target(context, event)
            if target is not None and event.type == "LEFTMOUSE":
                _click(context, event, target)
        except Exception:  # A click must never be stuck in the bar.
            traceback.print_exc()
        return {"RUNNING_MODAL"}  # anything else would pass the press on to the tool

    def modal(self, context, event, tweak):
        if event.type == getattr(self, "button", "LEFTMOUSE") and event.value == "RELEASE":
            return {"FINISHED"}
        try:
            _drag(context, event)
        except Exception:  # A drag must never be stuck in the bar.
            traceback.print_exc()
        return {"RUNNING_MODAL"}

    def exit(self, context, cancel):
        UI["pressed"] = False
        UI["drag"] = None


class EACHLABS_GGT_bar(bpy.types.GizmoGroup):
    bl_idname = "EACHLABS_GGT_bar"
    bl_label = "Prompt bar"
    bl_space_type = "VIEW_3D"
    bl_region_type = "WINDOW"
    bl_options = {"PERSISTENT"}

    @classmethod
    def poll(cls, context):
        return active()

    @classmethod
    def setup_keymap(cls, keyconfig):
        """Left, right and middle presses on the bar all go to the bar."""
        km = keyconfig.keymaps.new(name=GIZMO_KEYMAP, space_type="VIEW_3D", region_type="WINDOW")
        if not km.keymap_items:
            for button in ("LEFTMOUSE", "RIGHTMOUSE", "MIDDLEMOUSE"):
                km.keymap_items.new("gizmogroup.gizmo_tweak", button, "PRESS", any=True)
        return km

    def setup(self, context):
        self.gizmos.new(EACHLABS_GT_bar.bl_idname)

    def draw_prepare(self, context):
        try:
            if self.gizmos and context.region is not None:
                hover.left(context.region, self.gizmos[0].is_highlight)
        except Exception:  # A tooltip must never break the view.
            traceback.print_exc()


class EACHLABS_OT_bar_focus(bpy.types.Operator):
    bl_idname = "eachlabs.bar_focus"
    bl_label = "Focus prompt bar"
    bl_description = "Type a scene prompt in the bar at the bottom of the 3D view"

    @classmethod
    def poll(cls, context):
        return active()

    def execute(self, context):
        focus(context)
        return {"FINISHED"}


CLASSES = (EACHLABS_OT_bar_input, EACHLABS_OT_bar_click, EACHLABS_OT_bar_focus, EACHLABS_GT_bar, EACHLABS_GGT_bar)


# -- input operator and timer ---------------------------------------------------------------------

def _running_in(window):
    return any(op.bl_idname in ("EACHLABS_OT_bar_input", "eachlabs.bar_input") for op in window.modal_operators)


def start_input(context):
    """Start the input operator in the context's window unless it already runs there."""
    window = getattr(context, "window", None)
    if window is None or _running_in(window):
        return
    bpy.ops.eachlabs.bar_input("INVOKE_DEFAULT")


def _tick():
    """Redraws for the caret blink and the run's spinner; ends when the bar is neither focused nor running."""
    try:
        now = time.monotonic()
        if chat_run.STATE.running:
            tag_redraw()
            return SPIN_INTERVAL
        if UI["focused"]:
            tag_redraw()
            return BLINK - (now - UI["blink_from"]) % BLINK + 0.01
        tag_redraw()  # the last frame after a run ends or the bar loses focus
    except Exception:
        traceback.print_exc()
    return None


def _schedule():
    """Tick soon, so a focus or a run start redraws at its own rate."""
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    bpy.app.timers.register(_tick, first_interval=0.01, persistent=True)


def _hook():
    """A main-thread hook: a run started from the sidebar also gets the bar's spinner."""
    if chat_run.STATE.running:
        UI["consent"] = UI["quality_menu"] = UI["camera_menu"] = False
        if not bpy.app.timers.is_registered(_tick):
            _schedule()
    return False


@persistent
def _on_load(_dummy):
    _placed.clear()
    _cache.clear()
    UI["focused"] = UI["pressed"] = UI["consent"] = UI["quality_menu"] = UI["camera_menu"] = False
    hover.stop()


# -- registration ---------------------------------------------------------------------------------

def blender_fonts():
    folder = bpy.utils.system_resource("DATAFILES", path="fonts")
    names = sorted(os.listdir(folder)) if folder and os.path.isdir(folder) else []
    first = [n for n in FALLBACK_FIRST if n in names]
    rest = [n for n in names if n not in first and n.lower().endswith((".woff2", ".ttf", ".otf"))
            and not n.startswith(FALLBACK_SKIP)]
    return [os.path.join(folder, n) for n in first + rest]


def register():
    global _handle
    if not bar.available() or _handle is not None:
        return
    bar.set_fallback_fonts(blender_fonts())
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    FIELD.set_history(chat_run.STATE.history)
    chat_run.ask_consent = open_consent
    chat_run.restore_prompt = restore_prompt
    _handle =bpy.types.SpaceView3D.draw_handler_add(_draw, (), "WINDOW", "POST_PIXEL")
    kc = bpy.context.window_manager.keyconfigs.addon if bpy.context.window_manager else None
    if kc is not None:
        km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
        _keymaps.append((km, km.keymap_items.new("eachlabs.bar_focus", **FOCUS_KEY)))
        _keymaps.append((km, km.keymap_items.new("eachlabs.bar_click", **CLICK_KEY)))
    bpy.app.handlers.load_post.append(_on_load)
    main_thread.add_hook(_hook)


def unregister():
    global _handle
    if _handle is None:
        return
    bpy.types.SpaceView3D.draw_handler_remove(_handle, "WINDOW")
    _handle = None
    if chat_run.ask_consent is open_consent:
        chat_run.ask_consent = None
    if chat_run.restore_prompt is restore_prompt:
        chat_run.restore_prompt = None
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    hover.stop()
    for km, item in _keymaps:
        km.keymap_items.remove(item)
    _keymaps.clear()
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    if _hook in main_thread._hooks:
        main_thread._hooks.remove(_hook)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)  # also ends the running input operator
    _placed.clear()
    _cache.clear()
    _tip_cache.clear()
    _tip_placed.clear()
    UI["focused"] = UI["pressed"] = False
    tag_redraw()


# Imported last: these modules read this one's state through it.
from .viewport.draw import _draw, bottom_inset, current_state, insets, tag_redraw  # noqa: F401


# Imported last: these modules read this one's state through it.
from .viewport.input import _click, _done, _drag, _target, _target_at, on_event  # noqa: F401


# Imported last: these modules read this one's state through it.
from .viewport.actions import _act, _stop, blur, consent, focus, open_consent, restore_prompt, submit  # noqa: F401


# Imported last: these modules read this one's state through it.
from .viewport import hover  # noqa: E402
