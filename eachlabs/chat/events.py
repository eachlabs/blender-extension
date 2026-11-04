"""Events a run's worker posts, applied on Blender's main thread: step results, stage ends, and the run's finish."""

import time
import traceback

import bpy

from .. import chat_loop, code_check, code_runner, edit_guard, main_thread, viewport_marks
from ..things import after_step as things_after
from .live import chat_run
from . import budget, edits, library_use, object_jobs, plan_flow, stage_log, undo_watch, viewport


def _fingerprint(build):
    """``code_runner.fingerprint`` of ``build``, or ``None`` when its scene cannot be read."""
    try:
        return code_runner.fingerprint(build)
    except Exception:  # the scene is gone or half-edited; the bar then reads as an ordinary finish
        traceback.print_exc()
        return None



def _live(run):
    return run is chat_run._run and not run.cancel.is_set()



def _apply(run, event):
    """Main thread: one worker event into ``STATE``."""
    if not _live(run):
        return
    kind = event.get("type")
    if chat_run.STATE.code_check_state == "refused" and chat_loop.refusal_ends(event):
        chat_run.STATE.code_check_state, chat_run.STATE.code_check_reason = "", ""
    if kind == "stage":
        chat_run.STATE.stages[event["stage"]] = event["state"]
        if event["state"] in ("done", "partial") and run.build.end_stage(event["stage"]):
            chat_run.STATE.changed.append(event["stage"])
        if event["state"] == "done" and event["stage"] == "layout" and not run.framed:
            run.framed = True
            try:
                viewport.frame_build(run.build, viewport._area(run.view), keep_camera_view=True)
            except Exception:  # Framing is a convenience; the run goes on.
                traceback.print_exc()
        if event["state"] == "done" and event["stage"] == "light" and not run.shaded:
            run.shaded = True
            try:
                viewport.material_preview(run.window, run.view)
            except Exception:  # Shading is a convenience; the run goes on.
                traceback.print_exc()
    elif kind == "thinking":
        chat_run.STATE.thinking_since = event["since"]
    elif kind == "round":
        chat_run.STATE.round, chat_run.STATE.total = event["n"], event["total"]
    elif kind == "tool":
        for step in chat_run.STATE.code_steps:
            if step["id"] == event.get("id"):
                step["state"], step["detail"] = event.get("state"), event.get("detail") or ""
        row = {k: event.get(k) for k in ("id", "name", "summary", "state", "detail")}
        for index, old in enumerate(chat_run.STATE.tools):
            if old["id"] == row["id"]:
                chat_run.STATE.tools[index] = row
                break
        else:
            chat_run.STATE.tools.append(row)
            del chat_run.STATE.tools[:-chat_run.MAX_TOOLS]
    elif kind == "reply":
        chat_run.STATE.reply = event["text"]
    elif kind == "code":
        chat_run.STATE.code_steps.append({"id": event.get("id"), "stage": event.get("stage", ""), "state": "running",
                                 "detail": "", "code": code_check.redact(event.get("code") or "", run.secrets)})
    elif kind == "code_check":
        state = event["state"]
        chat_run.STATE.code_check_state = state if state in ("checking", "refused") else ""
        chat_run.STATE.code_check_reason = event.get("reason", "") if state == "refused" else ""
    elif kind == "objects_wait":
        chat_run.STATE.objects_wait = event["state"] == "on"
    elif kind == "planning":
        chat_run.STATE.planning = bool(event["state"])
    elif kind == "concept":
        chat_run.STATE.concept = event["state"]
        if event["state"] == "done" and run.build.code_runs:
            run.build.code_runs[-1]["concept"] = event.get("url") or ""
            chat_run.STATE.concept_path = event.get("path") or ""
    elif kind == "looking":
        chat_run.STATE.looking = bool(event["state"])
    elif kind == "stages":  # an edit runs its own stages, not the five
        chat_run.STATE.stages = {stage: "todo" for stage in event["stages"]}
    elif kind == "plan":
        chat_run.STATE.plan, chat_run.STATE.plan_waiting, chat_run.STATE.planning = event["plan"], True, False
        chat_run.STATE.plan_since = time.monotonic()



def _finish(run, result, cost):
    if not _live(run):
        return
    edits._end_edit(run.build)  # before the fingerprint: the guard's copies are not the run's change
    chat_run.STATE.running, chat_run.STATE.thinking_since, chat_run.STATE.status = False, None, result.status
    chat_run.STATE.code_check_state, chat_run.STATE.objects_wait, chat_run.STATE.looking = "", False, False
    chat_run.STATE.planning, chat_run.STATE.plan, chat_run.STATE.plan_waiting = False, None, False
    started = getattr(chat_run.STATE, "started_at", 0.0)
    seconds = time.monotonic() - started - chat_run.STATE.plan_waited if started else None
    chat_run.STATE.cost, chat_run.STATE.cost_text = cost, budget.cost_text(result.rounds, cost, seconds)
    object_jobs._cancel_objects(run)  # nothing is left running; every code version without its model stays
    chat_run.STATE.billed = object_jobs._billed(run)
    chat_run.STATE.free_assets = tuple(run.free_assets)
    undo_watch._settle()
    if result.status == "found":  # the bar already says what was found; nothing was built
        chat_run.STATE.error, chat_run.STATE.stages, chat_run.STATE.failed_stage, chat_run.STATE.unchanged = "", {}, None, False
        return
    chat_run.STATE.missing = []
    # Objects only: a world put back on a follow-up not about light is never offered (ask for the light instead).
    blocked = run.put_back - set(run.targets) - {edit_guard.WorldGuard.PUT_BACK}
    chat_run.STATE.blocked = sorted(blocked)[:8] if result.status == "done" else []
    chat_run.STATE.removal = bool(run.removal) and bool(chat_run.STATE.blocked)
    chat_run.STATE.last_targets = list(run.targets)
    stage_log.finished(chat_run.log_folder(), chat_run.STATE.prompt, result.status, chat_run.STATE.stages)
    if result.status == "done":
        library_use.keep(run, chat_run.STATE.code_steps)
        chat_run.STATE.reply, chat_run.STATE.error = result.message or chat_run.STATE.reply, ""
        chat_run.STATE.reply = "\n".join([chat_run.STATE.reply] + plan_flow.outcome_lines(run)).strip()  # whatever the model wrote
        try:  # what the plan asked for and the run did not build: the bar offers to build it
            chat_run.STATE.missing = [item.name for item in plan_flow._missing(run)] if run.plan is not None else []
        except (RuntimeError, ReferenceError):
            chat_run.STATE.missing = []
        chat_run.STATE.unchanged = run.before is not None and _fingerprint(run.build) == run.before
        if not chat_run.STATE.unchanged and things_after.finish(run.build) and not bpy.app.background:
            bpy.ops.ed.undo_push(message="Eachlabs: names")  # one scheme for every thing and part
        # A stage left partly done can be run again from the done bar: Retry runs it and the ones after it.
        chat_run.STATE.failed_stage = next((st for st in chat_loop.ORDER if chat_run.STATE.stages.get(st) == "partial"), None)
    else:
        chat_run.STATE.error = result.message
        chat_run.STATE.failed_stage = result.failed_stage
    main_thread.tag_redraw()


def _execute_marked(build, name, args, limit_s=None):
    """Main thread: apply one tool call, then flash what it created and show the camera path."""
    mark = build.mark()
    result = build.execute(name, args, limit_s)
    try:
        viewport_marks.flash(build.created_since(mark), time.monotonic())
        if name == "run_python":
            viewport._show_camera_path(build)
        if viewport_marks.active():
            viewport_marks.kick()
    except Exception:  # Highlights are decoration; the tool call already succeeded.
        traceback.print_exc()
    return result
