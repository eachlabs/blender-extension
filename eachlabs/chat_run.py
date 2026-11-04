"""The scene chat inside Blender: run state, the worker thread, and the chat operators.

The worker runs ``chat_loop.run`` and never touches ``bpy``. Its events and its tool calls are
queued here and applied on the main thread by ``tick``, which ``main_thread`` calls as a hook.
"""

import base64
import math
import os
import queue
import re
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field, replace

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

from bpy.app.handlers import persistent
from mathutils import Matrix, Vector

from . import (asset_cache, chat_loop, code_check, code_review, code_runner, compat, confirm, detail, edit_guard,
               generation, intent, main_thread, objects_3d, plan3d, preferences, scene_build, solids, textures,
               thread_safety, undo_steps, viewport_marks, visual_check, workflow_3d)
from .ui import tokens
from .instructions import targets
from .chat.budget import cost_text  # noqa: F401
from .chat.state import ChatState, _Run  # noqa: F401

TICK_BUDGET = 0.010  # seconds of queued chat work applied per tick
QUIET = 0.5  # seconds after the chat's own change in which scene updates are taken as the chat's
MAX_TOOLS = 20
MAX_HISTORY = 20
EXECUTOR_MARGIN = 15.0  # seconds the worker waits past the step limit, so a step that ran is never timed out
UNDO_READ_EVERY = 1.0  # seconds between reads of Blender's active undo step while the pill can show
LOST_READ_EVERY = 0.25  # seconds between checks that the running run's scene and collection still exist
_widen = []  # the targets the next run edits: set by "Also let it change ...", used once
GEN = generation.Registry()
GEN_WORKER = generation.run_object  # tests put a fake worker here
TEX_WORKER = generation.run_texture  # the same, for textures
GEN_CLIENT = None  # tests put a fake client here; None: each worker makes its own
NO_PICTURES = set()  # model ids that refused a picture with HTTP 400 in this session: no visual check, no concept


STATE = ChatState()

_calls = queue.SimpleQueue()
_run = None  # the current _Run
_build = None  # the current scene's SceneBuild: retries and follow-up prompts build into its collection
_no_resume = False  # New scene was pressed: the next prompt starts a new build even where the chat built before
_builds = []  # this session's builds, for picking up a scene's earlier work (``SceneBuild.take``)
_file_runs = frozenset()  # the run tags of the chat's collections when the file was opened
_play_saved = {}  # what Play through a camera changed, to put back when playback stops (``chat/playback.py``)


NO_CONSENT = "Choose how the chat may run code first."
# Set by the prompt bar: opens its consent card with this prompt in the field; False when the bar is not shown.
ask_consent = None


_undo = {"own": False, "quiet_until": 0.0, "frame": None, "signature": None,  # see "Undo tracking" below
         "top": None, "read_at": -1e9, "dirty": True, "readable": None}


def _call_soon(func):
    _calls.put(func)


def worker():
    """The current run's thread, or ``None``."""
    return _run.thread if _run is not None else None


def _refuse(text):
    STATE.error = text
    if STATE.status in ("stopped", "cancelled"):  # the bar shows the refusal, not the last run's stop
        STATE.status, STATE.failed_stage = "idle", None
    return False


def start(context, prompt, stages=None):
    """Start a chat run on a worker thread. ``stages`` set: a retry into the last run's collection."""
    global _run, _build, _no_resume
    if STATE.running:
        return _refuse("A chat is already running.")
    STATE.attempt = (prompt or "").strip()
    problem = compat.online_problem()
    if problem:
        return _refuse(problem)
    prompt = (prompt or "").strip()
    if not prompt:
        return _refuse(tokens.EMPTY_PROMPT)
    try:
        client = preferences.client(context)
    except ValueError as exc:
        return _refuse(str(exc))
    if not client.api_key:
        return _refuse("Add your Eachlabs API key to start.")
    if not preferences.code_allowed(context):  # every start asks first: send, Retry and the sidebar
        if ask_consent is not None and ask_consent(prompt):
            STATE.error = ""
            if STATE.status in ("stopped", "cancelled"):
                STATE.status, STATE.failed_stage = "idle", None
            main_thread.tag_redraw()
            return False
        return _refuse(NO_CONSENT)
    model = preferences.chat_model(context)
    limits = preferences.chat_limits(context)
    visual = preferences.visual_check(context) and model not in NO_PICTURES
    if visual:  # its rounds come on top, so the camera and the check still get theirs
        limits = replace(limits, total_rounds=limits.total_rounds + chat_loop.LOOK_ROUNDS)

    retry = stages is not None and _build is not None
    fresh = False  # a new scene: the first prompt of a scene
    if retry:
        try:
            _build.scene
        except RuntimeError as exc:
            return _refuse(str(exc))
        earlier = _build.prompts[1:]
    elif continues(context.scene):
        earlier = list(_build.prompts)
        _build.take(context.scene, _file_runs, _builds)  # an earlier build in the same scene
    else:
        resumed = None if _no_resume else scene_build.SceneBuild.resume(context.scene, _file_runs, _builds)
        _build = resumed or scene_build.SceneBuild(context.scene, uuid.uuid4().hex[:12])
        earlier = list(_build.prompts)
        fresh = resumed is None
        if _build not in _builds:
            _builds.append(_build)
    _no_resume = False
    if not retry:
        _build.prompts[:] = ([prompt] + _build.prompts)[:MAX_HISTORY]
        _build.since = _build.mark()  # this run's own objects come after it; a retry keeps the run's mark
    earlier = earlier[:chat_loop.EARLIER_MAX]
    detail_rounds, detail_parallel, references_on, detail_more = preferences.detail_settings(context)
    stages = tuple(stages) if stages is not None else chat_loop.ORDER
    if not detail_rounds:
        stages = tuple(s for s in stages if s != chat_loop.DETAIL)
    full = chat_loop.is_full(stages)  # every stage: not a retry of the later ones
    target = targets.target_of(STATE.run_target if retry else STATE.target)  # a retry keeps its run's tab
    STATE.run_target = target
    if full:  # an asset or a character added to a scene keeps its light and camera
        stages = targets.stages(target, fresh, stages)
    if not bpy.app.background:
        bpy.ops.ed.undo_push(message="Eachlabs: before chat")

    viewport_marks.clear()
    if not fresh:
        _show_camera_path(_build)  # the camera this scene already has
    old = dict(STATE.stages) if retry else {}
    STATE.changed = [s for s in STATE.changed if s not in stages] if retry else []
    shown = chat_loop.ORDER if detail_rounds else chat_loop.STAGES
    if full:
        shown = tuple(s for s in shown if s in stages)
    STATE.stages = {s: ("todo" if s in stages else old.get(s, "todo")) for s in shown}
    STATE.prompt, STATE.status, STATE.running = prompt, "running", True
    STATE.thinking_since, STATE.round, STATE.total = None, 0, limits.total_rounds
    STATE.started_at, STATE.plan_since, STATE.plan_waited = time.monotonic(), None, 0.0
    STATE.tools, STATE.reply, STATE.error, STATE.code_steps = [], "", "", []
    STATE.cost, STATE.cost_text, STATE.failed_stage, STATE.unchanged = None, "", None, False
    STATE.objects, STATE.objects_wait, STATE.concept, STATE.concept_path = [], False, "", ""
    STATE.final_render, STATE.final_path, STATE.final_error = "", "", ""  # a new run: its scene is not rendered yet
    STATE.looking, STATE.billed = False, False
    STATE.planning, STATE.plan, STATE.plan_waiting = False, None, False
    STATE.history =([prompt] + [p for p in STATE.history if p != prompt])[:MAX_HISTORY]
    _build.code_runs.append({"prompt": prompt, "retry": retry, "steps": STATE.code_steps})  # the same list
    del _build.code_runs[:-MAX_HISTORY]

    area = getattr(context, "area", None)
    view = area.as_pointer() if area is not None and area.type == "VIEW_3D" else None
    window = getattr(context, "window", None)
    run = _Run(_build, client, model, limits, view, earlier, window.as_pointer() if window is not None else None)
    library_use.prepare(run, prompt, context)
    stage_log.started(log_folder(), prompt, follow_up=not fresh)
    run.secrets = tuple(preferences.secrets(context)) + ((client.api_key,) if client.api_key else ())
    run.step_seconds = preferences.step_seconds(context)
    run.code_check = preferences.code_check(context)
    run.objects_3d = preferences.objects_3d(context) != "OFF"
    run.objects_limit, run.objects_timeout = preferences.objects_3d_limits(context)
    run.rounds_cap, run.light_model = preferences.rounds_cap(context), preferences.light_model(context)
    run.detail_model = preferences.detail_model(context)
    run.texture_seconds, run.concept_seconds, run.reply_seconds, run.download_seconds = preferences.wait_limits(context)
    if detail_rounds and chat_loop.DETAIL in stages:
        run.detail = detail.Settings(rounds=detail_rounds, parallel=detail_parallel, look=visual,
                                     light_rounds=preferences.detail_light_rounds(context),
                                     candidates=preferences.detail_candidates(context))
        run.detail_more = detail_more
        run.references_on = references_on and model not in NO_PICTURES
    run.plan_step = (run.objects_3d or run.references_on) and full  # a retry of later stages adds nothing
    run.fresh = fresh  # set before the worker starts: it reads it
    run.target, run.whole = target, full
    things_after.migrate(_build)  # a scene built before things existed gets them now
    # On Assets and Characters, a light, a camera, a hidden object or the startup Cube is not a thing to change.
    run.names, run.selected, run.selected_names = _scene_names(_build, context, things_only=target != targets.SCENE)
    run.things = _inventory(_build)
    _build.allowed = set()
    _build.world_guard = None  # set again by the worker for a follow-up that keeps the world
    run.textures_limit = preferences.textures_limit(context)
    # A new scene, or a change that asks for one (the quick call decides): retries and the stages after a stopped
    # one never draw again.
    run.concept_allowed = preferences.concept_picture(context) and full and (
        model not in NO_PICTURES)
    run.concept = run.concept_allowed and fresh
    run.concept_model, run.concept_price = preferences.concept_model(context)
    run.visual = chat_loop.Visual() if visual else None
    run.scene_review = preferences.scene_review(context) and full and model not in NO_PICTURES
    run.free_assets_on = preferences.free_assets(context)
    run.settle_on = preferences.settle_props(context)
    if run.objects_3d or run.textures_limit or run.free_assets_on:
        run.cache_folder = cache_folder()
    if run.concept_allowed or run.references_on:
        run.concept_folder = preferences_folder("concepts")
    run.before = _fingerprint(_build)
    try:  # on a change, what existed before it: a new thing may not stand through it
        _build.existing = {o.name for o in _build._objects()} if not fresh and not retry else set()
    except (RuntimeError, ReferenceError):
        _build.existing = set()
    STATE.code_check_on, STATE.code_check_state, STATE.code_check_reason = run.code_check, "", ""
    _run = run
    run.thread = threading.Thread(target=_work, args=(run, prompt, stages), name="eachlabs-chat", daemon=True)
    # Counted before start(): a worker that ends at once must not lower the count before it is raised.
    thread_safety.chat_thread_started()
    try:
        run.thread.start()
    except Exception as exc:  # no thread: nothing runs, and the bar offers Retry
        thread_safety.chat_thread_ended()
        _run, run.thread = None, None
        if not retry:
            del _build.prompts[:1]
        if _build.code_runs and _build.code_runs[-1]["steps"] is STATE.code_steps:
            _build.code_runs.pop()
        STATE.running, STATE.status = False, "idle"
        print("Eachlabs: the chat could not start: %s" % exc)
        return _refuse(tokens.START_FAILED)
    main_thread.start()
    main_thread.tag_redraw()
    return True


def preferences_folder(name):
    return preferences.user_folder(name)


def log_folder():
    """The folder of the stage log, or ``None`` when it cannot be made or the add-on is not installed (scripts and
    tests write nothing)."""
    if preferences.get_preferences() is None:
        return None
    try:
        return preferences.user_folder("logs")
    except OSError:
        return None


# The detail stage ------------------------------------------------------------------------------------------------
# After the layout, ``detail.run`` improves the main objects. Its steps come here on the main thread: each one may
# change only its own object, and the edit guard puts back any other object of the chat's that it changed.


def file_opened():
    """Main thread, after a file is opened or the add-on starts: the chat's collections in it are its earlier
    work. This session's builds are forgotten."""
    global _file_runs
    _file_runs = frozenset(c[scene_build.RUN] for c in bpy.data.collections
                           if isinstance(c.get(scene_build.RUN), str) and c[scene_build.RUN])
    _builds.clear()


def new_scene(context=None):
    """The next prompt builds a new scene; nothing is deleted. With a window whose scene holds the chat's work,
    the window moves to a new, empty Blender scene; the old one stays in Blender's scene list."""
    global _build, _no_resume
    if STATE.running:
        return False
    window = getattr(context, "window", None)
    if window is not None and _built_in(window.scene):
        window.scene = scene_build.blank_scene(window.scene)
    _build, _no_resume = None, True
    viewport_marks.clear()
    reset_view()
    return True


# Generated 3D objects -----------------------------------------------------------------------------
# When Build is pressed the add-on queues a job per approved 3D item; the worker runs the 3D workflow. Its result is
# brought into the scene on the main thread by ``_objects_tick``, between the chat's steps. A job that fails is told
# to the model at the start of the next stage (``_failed_notes``); its code version stays.


def cache_folder():
    return preferences.user_folder("3d-cache")


# Set by the prompt bar: puts a prompt back in its field after Cancel on the plan.
restore_prompt = None


def _objects_rows(run):
    """``STATE.objects`` and the build's ``generated`` entries from the run's jobs. A finished job lets go of its
    cache file."""
    rows = []
    for job in _jobs(run):
        if not job.active and job.path and not job.context.get("let_go"):
            job.context["let_go"] = True
            asset_cache.release(job.path)
        status = "pending" if job.active else "ready" if job.state == generation.DONE else "failed"
        entry = run.build.generated.get(job.job_id)
        if entry is not None:
            entry["status"] = status
        rows.append({"id": job.job_id, "kind": job.kind, "name": job.name, "state": job.state,
                     "seconds": job.running_for,
                     "cost": job.cost, "cached": job.cached, "error": job.error, "priority": job.priority})
    STATE.objects = rows


def cancel(drop_build=False):
    """Stop the current run; what was built stays. ``drop_build``: forget it too (file opened, add-on off)."""
    global _build
    run = _run
    if drop_build:
        _build = None
    if run is None or not STATE.running:
        return False
    if STATE.plan_waiting and not drop_build:  # Stop on the plan is its Cancel: the prompt comes back
        return plan_answer("cancel")
    run.cancel.set()
    _cancel_objects(run)
    STATE.billed = _billed(run)
    STATE.running, STATE.status, STATE.thinking_since = False, "cancelled", None
    STATE.objects_wait, STATE.planning, STATE.plan, STATE.plan_waiting = False, False, None, False
    for stage, state in STATE.stages.items():
        if state == "active":
            STATE.stages[stage] = "cancelled"
    main_thread.tag_redraw()
    return True


# Undo tracking --------------------------------------------------------------------------------
# *Undo stage* runs ``ed.undo`` once, which undoes whatever step is on top. So the pill is offered
# only while the top step is the chat's last stage. That is read from Blender's undo stack
# (``undo_steps``). When it cannot be read (background mode, or no standard output to catch),
# tracking decides instead: any other undo, redo or edit clears ``STATE.changed``. The chat's own changes are told apart by time (``QUIET`` after each), by tag
# during a run, and the pill's own undo by a flag.


# Framing --------------------------------------------------------------------------------------


# Operators -------------------------------------------------------------------------------------


# Imported last: these modules read this one's state through it.
from .chat.detail_steps import _apart, _detail_copies, _detail_roots, _into  # noqa: F401

from .chat.texture_jobs import queue_texture  # noqa: F401

from .chat.selection import _inventory, _scene_names  # noqa: F401
from .things import after_step as things_after  # noqa: E402

from .chat.undo_watch import (  # noqa: F401
    _quiet,
    _settle,
    on_depsgraph,
    on_undo,
    register_handlers,
    undoable_stages,
    unregister_handlers,
)

from .chat.viewport import _area, _show_camera_path, frame_objects, material_preview  # noqa: F401

from .chat.removal import _resting_on  # noqa: F401
from .chat import library_use, stage_log  # noqa: E402

from .chat.plan_flow import _hollow, build_missing, plan_answer, plan_toggle, widen  # noqa: F401

from .chat.object_jobs import (  # noqa: F401
    FAILED_REPLY,
    UPGRADED,
    _billed,
    _cancel_objects,
    _claim,
    _failed_notes,
    _jobs,
)

from .chat.show_code import code_text, show_code  # noqa: F401

from .chat.operators import (  # noqa: F401
    CLASSES,
    EACHLABS_OT_chat_cancel,
    EACHLABS_OT_chat_frame_result,
    EACHLABS_OT_chat_new_scene,
    EACHLABS_OT_chat_retry_stage,
    EACHLABS_OT_chat_send,
    EACHLABS_OT_chat_undo_stage,
    _undoable_stages,
    paid_running,
)

from .chat.edits import _begin_edit, _end_edit  # noqa: F401

from .chat.concepts import _concept, _reference_for  # noqa: F401

from .chat.events import _fingerprint, _finish  # noqa: F401

from .chat.work import _work  # noqa: F401

from .chat.scene_state import _built_in, _drop_cube, continues, has_scene  # noqa: F401

from .chat.events import _execute_marked  # noqa: F401

from .chat.lifecycle import dismiss, hook, reset_view, tick  # noqa: F401
