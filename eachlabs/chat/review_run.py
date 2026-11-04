"""The scene review in Blender: its four pictures and undoing its fix stage. Main thread only; ``review.py`` decides.

The pictures are the visual check's camera frame and three ``look_around`` views fitted to the request's main
things, with everything else still shown. The undo is Blender's own: the fix stage is one undo step, and
``bpy.ops.ed.undo`` takes the scene back to the step before it, the way *Undo stage* does.
"""

import bpy

from .. import look_around, thread_safety, undo_steps, visual_check
from ..scene_build import SceneBuild
from ..things import ids, registry
from .live import chat_run
from .stages import FIX
from . import undo_watch

AROUND = ((35.0, 25.0), (155.0, 25.0), (275.0, 25.0))  # three sides, a third of a turn apart


def _main_roots(build, entries, subjects):
    """The roots of the things the request is about: each subject word's things by name, kind or label."""
    out = []
    for word in subjects or ():
        for entry in entries:
            if ids.matches(entry, word) and entry["name"] not in out:
                out.append(entry["name"])
    return out


def views(build, subjects=()):
    """``{"images", "names", "things"}``: the camera's view and three views around ``subjects`` (plan names; all
    the chat built when none match), the things' names and their inventory lines. ``images`` empty with a
    ``reason`` when nothing could be rendered."""
    entries = registry.inventory(build._objects())
    if not entries:
        return {"images": [], "reason": "no things to review"}
    camera = visual_check.render(build, False)
    around = look_around.render_view(build, None, (), "solid", _main_roots(build, entries, subjects), AROUND)
    images = (camera.get("images") or [])[:1] + list(around.get("images") or [])
    return {"images": images, "names": [e["name"] for e in entries],
            "things": [ids.inventory_line(e) for e in entries],
            "reason": camera.get("reason") or around.get("reason") or ""}


def mark(run):
    """Before the review's fix stage: the undo steps the run pushed so far."""
    run.review_pushes = run.build.pushes
    return {}


def _window(pointer):
    windows = list(bpy.context.window_manager.windows)
    return next((w for w in windows if w.as_pointer() == pointer), windows[0] if windows else None)


def undo_fix(run):
    """Undo the review's fix stage: ``{"undone": True}``, or ``undone`` False with a ``reason``. Only when the fix
    stage is the one undo step pushed since ``mark`` and the active one, so nothing else is undone."""
    if bpy.app.background:
        return {"undone": False, "reason": "background mode has no undo steps"}
    since = getattr(run, "review_pushes", None)
    if since is None or run.build.pushes != since + 1:
        return {"undone": False, "reason": "the fix stage is not the last undo step"}
    if undo_steps.active_name() != SceneBuild.undo_name(FIX):
        return {"undone": False, "reason": "the active undo step is not the fix stage"}
    # Blender 4.2: an operator under temp_override races any Python thread, and the waiting chat worker still wakes
    # to check for Stop. Never risk the crash during a run: the person takes the stage back with Undo stage.
    if thread_safety.override_races():
        return {"undone": False, "ask": True, "reason": "Blender 4.2 cannot undo while the chat runs"}
    window = _window(run.window)
    if window is None:
        return {"undone": False, "reason": "no window"}
    chat_run._undo["own"] = True
    try:
        with bpy.context.temp_override(window=window, screen=window.screen):
            bpy.ops.ed.undo()
    except RuntimeError as exc:
        return {"undone": False, "reason": str(exc)}
    finally:
        chat_run._undo["own"] = False
        undo_watch._settle()
    if FIX in chat_run.STATE.changed:
        changed = chat_run.STATE.changed
        del changed[len(changed) - 1 - changed[::-1].index(FIX)]
    run.build.pushes -= 1
    return {"undone": True}
