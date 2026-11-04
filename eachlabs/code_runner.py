"""Runs one step of Blender Python written by the chat model. Main thread only.

The code is checked by ``code_check`` first, then executed in a fresh namespace under a time limit. This is
not a sandbox: the check refuses the obvious ways out of the scene, but code that passes it runs with
Blender's full access. The namespace gets ``bpy``, ``bmesh`` and ``mathutils`` as they are, and ``math`` and
``random`` as copies holding only their public functions and constants, and ``scene``, the build's scene.
Everything the step creates joins
the build: objects move into its collection and carry its tags, other new datablocks carry its run tag.
The result is a short summary for the model, passed through ``code_check.redact``. Redaction replaces exact
copies of the add-on's credentials only; the filter's ``credentials`` and ``private`` rules are the main guard.
While the code runs, the API key is emptied in the add-on preferences; a step that changes a setting stops the
run (``settings_guard``).
"""

import builtins
import ctypes
import io
import linecache
import math
import random
import sys
import threading
import traceback
import types

import bmesh
import bpy
import mathutils

from . import chat_loop, code_check, edit_guard, error_hints, preferences, settings_guard
from .library import helpers as library_helpers
from .placement import apply as placement_apply
from .things import after_step as things_after
from .ui import tokens
from .scene.snapshot import (  # noqa: F401
    DATA_KINDS,
    _camera_state,
    _data_snapshot,
    _mesh_counts,
    _object_state,
    _others_snapshot,
    _r,
    _repair_meshes,
    _update,
    _world_state,
    fingerprint,
)
from .scene.step_namespace import _namespace  # noqa: F401

LIMIT_S = 20.0  # seconds per step when the caller passes none; the chat passes its chat_step_seconds preference
FILENAME = "<step>"
TRACEBACK_LINES = 20
OUTPUT_CHARS = 2000
OUTPUT_CUT = "\n[%d more characters cut. read_scene lists every object you built; print less.]"
LIST_MAX = 40  # entries per summary list; the summary goes back to the model every step
PUT_BACK = ("This step changed objects that are not the target (put_back lists them); they were put back as they "
            "were. Change only the target: %s.")
WORLD_KEPT = ("This step changed the world (the sky or the background light); it was put back, because the request "
              "is not about the light, the sky or the time of day. Light new things with lights of their own.")
LEFT_MODE = ("Your step left Blender in %s mode; the add-on put it back in Object Mode. End every step in Object "
             "Mode: bmesh.from_edit_mesh and mode_set are not needed, use bmesh.new() and bm.to_mesh(mesh).")
TAGGED_KINDS = ("meshes", "materials", "lights", "cameras", "curves", "node_groups", "images", "worlds")
REPAIRED = ("These meshes had broken data (faces pointing at vertices or corners that do not exist) and Blender "
            "repaired them, so some of their faces may be gone: %s. Build them again with bmesh or "
            "from_pydata, using only indices of vertices that exist.")


def _cap(items):
    if len(items) <= LIST_MAX:
        return list(items)
    return list(items[:LIST_MAX]) + ["+%d more" % (len(items) - LIST_MAX)]


class StepTimeout(BaseException):
    """Stops a step at its time limit. Not an ``Exception``, so the step's ``except Exception`` cannot keep it."""


def _set_async(thread_id, exc):
    """Raise ``exc`` in that thread at its next check between bytecodes; ``None`` drops a pending one."""
    ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(thread_id),
                                               ctypes.py_object(exc) if exc is not None else None)


class _Watchdog:
    """Stops the calling thread's step once ``limit_s`` has passed, and again every 0.1 s until ``stop``.

    A helper thread raises ``StepTimeout`` in the step as an asynchronous exception. Not ``sys.settrace``:
    Python switches off a trace function that raises, and in Python 3.11 the next step then ran untraced."""

    def __init__(self, limit_s):
        self.thread_id = threading.get_ident()
        self.lock = threading.Lock()
        self.active = True
        self.hit = False
        self.done = threading.Event()
        threading.Thread(target=self._watch, args=(limit_s,), name="eachlabs-step-limit", daemon=True).start()

    def _watch(self, limit_s):
        if self.done.wait(limit_s):
            return
        while True:
            with self.lock:
                if not self.active:
                    return
                self.hit = True
                _set_async(self.thread_id, StepTimeout)
            if self.done.wait(0.1):
                return

    def stop(self):
        with self.lock:
            self.active = False
            _set_async(self.thread_id, None)
        self.done.set()


def _execute(code, limit_s, out, scene=None, requests=None, prelude=""):
    """Run ``code``; return the trimmed traceback text, or ``None`` when it finished. ``requests`` collects what
    the code asked zone(), place() and scatter() for."""
    namespace = _namespace(scene, requests)
    linecache.cache[FILENAME] = (len(code), None, code.splitlines(True), FILENAME)
    failure, watchdog, stdout = None, None, sys.stdout
    try:
        try:
            compiled = compile(code, FILENAME, "exec")
            sys.stdout = out
            watchdog = _Watchdog(limit_s)
            if prelude:  # stored helpers the step calls by name, defined first in its namespace
                exec(compile(prelude, "<helpers>", "exec"), namespace)
            exec(compiled, namespace)
        except BaseException as exc:  # noqa: BLE001 - sorted out below, once the watchdog is off
            failure = exc
    except StepTimeout as exc:  # a stop that landed in the handler above
        failure = failure or exc
    finally:
        # Until the watchdog is off a stop can land anywhere, so this retries until it is off. stdout is
        # restored here by hand: a stop inside a context manager's exit would leave it redirected.
        # A stop can also land in another add-on's Python handler that Blender runs during the step (accepted).
        while True:
            try:
                if watchdog is not None:
                    watchdog.stop()
                sys.stdout = stdout
                break
            except StepTimeout:
                continue
    if failure is not None and not isinstance(failure, (Exception, SystemExit, StepTimeout)):
        linecache.cache.pop(FILENAME, None)
        raise failure  # KeyboardInterrupt and the like are not the step's to report
    text = _trimmed(failure) if failure is not None else None
    linecache.cache.pop(FILENAME, None)
    if isinstance(failure, StepTimeout) or (watchdog is not None and watchdog.hit and failure is None):
        stopped = "TimeoutError: The step ran longer than %g s and was stopped" % limit_s
        return "\n".join(text.splitlines()[:-1] + [stopped]) if text else stopped
    return text


def _trimmed(exc):
    tb = traceback.TracebackException.from_exception(exc)
    own = [frame for frame in tb.stack if frame.filename == FILENAME]
    if own:
        tb.stack = traceback.StackSummary.from_list(own)
    lines = "".join(tb.format()).rstrip("\n").splitlines()
    return "\n".join(lines[-TRACEBACK_LINES:])


def _adopt(build, before):
    """Bring what the step created into the build; returns ``(new objects, new materials)``."""
    new = {kind: [b for b in getattr(bpy.data, kind) if b.session_uid not in before[kind]] for kind in DATA_KINDS}
    objects = sorted(new["objects"], key=lambda o: o.session_uid)
    for obj in objects:
        build.adopt(obj)
    for kind in TAGGED_KINDS:
        for block in new[kind]:
            build.tag(block)
    collections = list(new["collections"])
    while True:  # collections the step made and left empty once their objects moved
        empty = [c for c in collections if not c.objects and not c.children]
        if not empty:
            break
        for coll in empty:
            collections.remove(coll)
            bpy.data.collections.remove(coll)
    return objects, sorted(new["materials"], key=lambda m: m.session_uid)


def _summary(build, scene, names, others, sampled, world, camera, objects, materials):
    alive = {o.session_uid for o in bpy.data.objects}
    removed = [name for uid, name in names.items() if uid not in alive]
    lights = [o for o in objects if o.type == "LIGHT"]
    touched = 0  # the person's objects the step changed or deleted; counted, never named
    by_uid = {o.session_uid: o for o in scene.objects}
    cache = {}
    for uid, state in others.items():
        obj = by_uid.get(uid)
        if obj is None or (not build.owns(obj) and _object_state(obj, cache) != state):
            touched += 1
    from . import scene_build  # it imports this module

    made = {o.session_uid for o in objects}
    roots = [o for o in objects if o.parent is None or o.parent.session_uid not in made]
    placed = []  # where each new thing's geometry really is; its origin is often 0 or an empty's offset
    for root in roots:
        where = scene_build.extent(root)
        if where is not None:
            placed.append(dict(name=root.name, **where))
        elif root.type not in ("LIGHT", "CAMERA"):
            placed.append({"name": root.name, "location": _r(root.matrix_world.translation)})
    summary = {
        "new_objects": _cap([{"name": o.name, "type": o.type} for o in objects]),
        "placed": _cap(placed),
        "removed_objects": _cap(removed),
        "new_materials": _cap([m.name for m in materials]),
        "new_lights": _cap([{"name": o.name, "type": o.data.type, "energy": round(o.data.energy, 1)}
                            for o in lights]),
        "touched_other": touched,
    }
    if sampled:
        summary["touched_other_sampled"] = True
    world_after = _world_state(scene, build)
    if world_after != world:
        summary["world"] = world_after
    camera_after = _camera_state(scene, build)
    if camera_after != camera:
        summary.update(camera_after)
    return summary


def run(code, build, limit_s=LIMIT_S, secrets=None):
    """Check and run one step in ``build``'s scene; ``{"ok": True, "summary": ...}`` or ``{"ok": False, ...}``.

    Every text in the result has ``secrets`` (by default the add-on's credentials) replaced by ``[redacted]``."""
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("code_runner.run must be called on Blender's main thread.")
    if secrets is None:
        secrets = preferences.secrets()
    return code_check.redact(_run(code, build, limit_s), secrets)


def _execute_guarded(code, limit_s, out, scene, requests=None, prelude=""):
    """``_execute`` with the add-on's secrets emptied in its preferences while the code runs; returns
    ``(error, changed)``, where ``changed`` means the step changed a setting and every setting was put back.

    This runs on the main thread, so Blender handles no UI event, timer or preferences save until it
    returns, and the filter refuses ``bpy.ops.eachlabs`` and file loading. A step that changes the scene's
    model choice still makes the add-on fetch a price; that read sees the emptied key."""
    prefs = preferences.get_preferences()
    if prefs is None:  # unregistered (scripts, tests): there are no settings to protect
        return _execute(code, limit_s, out, scene, requests, prelude), False
    return settings_guard.run_hidden(prefs, preferences.setting_names(prefs), preferences.secrets(),
                                     lambda: _execute(code, limit_s, out, scene, requests, prelude))


def _prelude(code, build):
    """The stored helpers ``code`` calls by name, when they pass the filter as a whole; ``""`` otherwise."""
    entries = getattr(build, "library", None)
    text = library_helpers.prelude(code, entries) if entries else ""
    if not text:
        return ""
    try:
        code_check.check(text)
    except code_check.Refused:
        return ""
    return text


def _run(code, build, limit_s):
    try:
        code_check.check(code)
    except code_check.Refused as exc:
        return {"ok": False, "error": str(exc)}
    try:
        scene = build.scene
    except RuntimeError as exc:
        return {"ok": False, "error": str(exc)}
    mode = build.busy_mode()
    if mode is not None:  # Changing data under Edit Mode would be lost or clash with the person's edit.
        return {"ok": False, "error": "Blender is busy in %s mode; try again in a moment." % mode}

    _update(scene)
    guard = getattr(build, "guard", None)  # a targeted edit: the chat's other objects are put back after the step
    if guard is not None:
        guard.begin()
    world_guard = getattr(build, "world_guard", None)  # a follow-up not about the light keeps the world
    if world_guard is not None:
        world_guard.begin()
    before = _data_snapshot()
    counts = _mesh_counts()
    names = {o.session_uid: o.name for o in bpy.data.objects if build.owns(o)}  # the build's, for removed_objects
    others, sampled = _others_snapshot(scene, build)
    world, camera = _world_state(scene, build), _camera_state(scene, build)
    things_before = things_after.before(build)

    out = io.StringIO()
    build.note_change()
    requests = []
    error, changed = _execute_guarded(code, limit_s, out, scene, requests, _prelude(code, build))
    left = build.leave_modes()  # before the mesh repair: an Edit Mode mesh is written back only on leaving it
    repaired = _repair_meshes(build, counts)  # before _adopt and _update: nothing may evaluate a broken mesh
    placed, things = None, {}
    placing = [r for r in requests if r[0] in ("zone", "place", "scatter")]
    if placing and not changed:  # before _adopt: the areas and copies it makes join the build there
        try:
            placed = placement_apply.run(scene, placing, lambda o: build.owns(o)
                                         or o.session_uid not in before["objects"],
                                         getattr(build, "area_rules", ()))
        except Exception as exc:  # noqa: BLE001 - the step's own result still goes back
            placed = {"error": "placing failed: %s: %s" % (type(exc).__name__, exc)}
    try:
        objects, materials = _adopt(build, before)
        if not changed:  # what belongs to which thing, before the guard: a removed thing's rest goes with it
            things = things_after.apply(build, scene, requests, things_before, objects)
        restored = guard.check() if guard is not None else []
        if world_guard is not None:
            restored += world_guard.check()
        _update(scene)
        summary = _summary(build, scene, names, others, sampled, world, camera, objects, materials)
    except Exception as exc:  # noqa: BLE001 - the step may leave data the summary cannot read
        if changed:
            raise chat_loop.StopRun(tokens.SETTINGS_CHANGED) from None
        return {"ok": False, "error": "%sThe step ran, but its summary could not be built: %s: %s. Call read_scene "
                "to see the scene instead of running the step again." % (
                    error + "\n" if error else "", type(exc).__name__, exc)}
    if changed:  # what the step made stays in the build; the model is not told anything
        raise chat_loop.StopRun(tokens.SETTINGS_CHANGED)
    result = {"ok": error is None, "summary": summary}
    if error is not None:
        result["error"] = error
        try:
            answer = error_hints.hint(error, code)
        except Exception:  # noqa: BLE001 - a hint is extra; the error goes back without it
            answer = ""
        if answer:
            result["hint"] = answer
    if left is not None:
        result["mode"] = LEFT_MODE % left
    if placed:
        result["placement"] = placed
    result.update(things)
    if things.get("orphans"):
        result["orphans_note"] = things_after.ORPHANS_NOTE % ", ".join(things["orphans"])
    if repaired:
        result["repaired_meshes"] = _cap(repaired)
        result["repair_note"] = REPAIRED % ", ".join(_cap(repaired))
    if restored:
        result["put_back"] = _cap(restored)
        objects_back = [r for r in restored if r != edit_guard.WorldGuard.PUT_BACK]
        result["note"] = (PUT_BACK % ", ".join(getattr(build, "focus_names", None) or ["the target"])
                          if objects_back else WORLD_KEPT)
    printed = out.getvalue()
    if len(printed) > OUTPUT_CHARS:  # the start is kept: a cut-off head made the model print the same list again
        printed = printed[:OUTPUT_CHARS] + OUTPUT_CUT % (len(printed) - OUTPUT_CHARS)
    if printed:
        result["output"] = printed
    return result
