"""The prompt bar's registration and the viewport marks."""

import os
import types

import bpy

import eachlabs
from eachlabs import panels
from tests.smoke.common import SKIA_ERROR, _FakeLayout, check


def _bar_keymap_items():
    kc = bpy.context.window_manager.keyconfigs.addon
    km = kc.keymaps.get("3D View") if kc else None
    return [i for i in km.keymap_items if i.idname in ("eachlabs.bar_focus", "eachlabs.bar_click")] if km else []


def _overlay_left_nothing(overlay, label):
    check("overlay: %s leaves no draw handler, timer or keymap item" % label,
          overlay._handle is None and not bpy.app.timers.is_registered(overlay._tick) and not _bar_keymap_items()
          and not hasattr(bpy.types, "EACHLABS_OT_bar_input") and "bl_rna" not in overlay.EACHLABS_GGT_bar.__dict__,
          "%r %r %d" % (overlay._handle, bpy.app.timers.is_registered(overlay._tick), len(_bar_keymap_items())))


def test_overlay():
    from eachlabs import overlay
    from eachlabs.ui import bar, fonts

    check("overlay: Skia imports in Blender", SKIA_ERROR is None, SKIA_ERROR or "")
    check("overlay: registered with Skia, no redraw timer while idle", overlay.active()
          and not bpy.app.timers.is_registered(overlay._tick)
          and hasattr(bpy.types, "EACHLABS_OT_bar_input") and hasattr(bpy.types, "EACHLABS_OT_bar_click"),
          "available %s" % bar.available())
    kc = bpy.context.window_manager.keyconfigs.addon
    items = {i.idname: i for i in _bar_keymap_items()}
    focus, click = items.get("eachlabs.bar_focus"), items.get("eachlabs.bar_click")
    check("overlay: Shift+Alt+Space focuses the bar", kc is None or (
        focus is not None and focus.type == "SPACE" and focus.shift and focus.alt and not focus.ctrl),
        "addon keyconfig %s" % ("missing" if kc is None else "present"))
    check("overlay: a left press in the 3D view goes to the bar's click operator", kc is None or (
        click is not None and click.type == "LEFTMOUSE" and click.value == "PRESS" and click.any))
    wm = bpy.context.window_manager
    probe = wm.keyconfigs.new("eachlabs-smoke")
    try:
        km = overlay.EACHLABS_GGT_bar.setup_keymap(probe)
        overlay.EACHLABS_GGT_bar.setup_keymap(probe)  # a second set-up adds nothing
        tweaks = sorted((i.type, i.value, i.any) for i in km.keymap_items if i.idname == "gizmogroup.gizmo_tweak")
    finally:
        wm.keyconfigs.remove(probe)
    check("overlay: the bar's gizmo group is registered and takes left, right and middle presses",
          "bl_rna" in overlay.EACHLABS_GGT_bar.__dict__ and "bl_rna" in overlay.EACHLABS_GT_bar.__dict__
          and tweaks == [("LEFTMOUSE", "PRESS", True), ("MIDDLEMOUSE", "PRESS", True), ("RIGHTMOUSE", "PRESS", True)],
          str(tweaks))
    names = [os.path.basename(p) for p in fonts._fallback_paths]
    check("overlay: Blender's CJK and emoji fonts are the fallbacks",
          "Noto Sans CJK Regular.woff2" in names and "NotoEmoji-VariableFont_wght.woff2" in names, str(names[:5]))
    check("overlay: CJK and emoji come from the fallback fonts, Latin and Cyrillic from Inter",
          bar._choice("regular", "\u65e5") >= 0 and bar._choice("regular", "\U0001f306") >= 0
          and bar._choice("regular", "a") == -1 and bar._choice("regular", "\u043a") == -1)
    from eachlabs.ui.text_field import TextField
    field = TextField()
    field.paste("\u043a\u0430\u0444\u0435 \u65e5\u672c\u306e\u8857 \U0001f306 street")
    frame = bar.render(bar.BarState(mode="typing", field=field, focused=True), 568, 2)
    check("overlay: mixed scripts render", frame.width == (568 + 72) * 2 and len(frame.rgba) == frame.width * frame.height * 4)
    state = overlay.current_state()
    check("overlay: idle chat gives an idle bar", state.mode == "idle" and not state.focused, state.mode)

    for n in (1, 2):
        eachlabs.unregister()
        _overlay_left_nothing(overlay, "unregister %d" % n)
        eachlabs.register()
        check("overlay: register %d adds one handler and two keymap items" % n, overlay.active()
              and len(_bar_keymap_items()) == (0 if kc is None else 2))

    real = bar.available
    try:
        bar.available = lambda: False
        eachlabs.unregister()
        eachlabs.register()
        _overlay_left_nothing(overlay, "Skia unavailable")
        chat_panel = next(c for c in panels.CLASSES if c.__name__ == "EACHLABS_PT_view3d_chat")
        check("overlay: sidebar chat panel shows without Skia", chat_panel.poll(bpy.context))
        log = []
        panels.draw_chat(_FakeLayout(log), types.SimpleNamespace(
            window_manager=bpy.context.window_manager, region=None,
            preferences=types.SimpleNamespace(system=types.SimpleNamespace(ui_scale=1.0))))
        check("overlay: sidebar chat panel has the Build button", ("operator", "eachlabs.chat_send") in log, repr(log))
    finally:
        bar.available = real
        eachlabs.unregister()
        eachlabs.register()
    check("overlay: back with Skia, the sidebar chat panel hides",
          overlay.active() and not next(c for c in panels.CLASSES if c.__name__ == "EACHLABS_PT_view3d_chat").poll(
              bpy.context))


def test_marks_lifecycle():
    from eachlabs import viewport_marks

    for _ in range(2):
        eachlabs.unregister()
        eachlabs.register()
    # Background Blender has no viewport, so no handler is added; the GUI check covers the draw handler.
    check("marks: register and unregister twice leave no handler in background", not viewport_marks.active())
    viewport_marks.flash(["x"], 0.0)
    viewport_marks.unregister()
    check("marks: unregister clears the state", viewport_marks.camera_path() == [] and not viewport_marks.has_flashes())
