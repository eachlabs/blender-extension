"""The chat's main-thread timer and what a run leaves behind: applying queued work, a lost run, reset and dismiss."""

import queue
import time
import traceback

from .live import chat_run
from .. import main_thread, viewport_marks
from . import object_jobs, undo_watch


def reset_view():
    """Forget what the bar shows about the last run (status, chips, reply, error, pills, tools, cost);
    the prompt history stays. Does nothing while a run is going."""
    if chat_run.STATE.running:
        return
    chat_run.STATE.status, chat_run.STATE.stages, chat_run.STATE.reply, chat_run.STATE.error, chat_run.STATE.changed = "idle", {}, "", "", []
    chat_run.STATE.tools, chat_run.STATE.cost, chat_run.STATE.cost_text, chat_run.STATE.failed_stage = [], None, "", None
    chat_run.STATE.missing, chat_run.STATE.blocked, chat_run.STATE.free_assets = [], [], ()
    chat_run.STATE.round, chat_run.STATE.thinking_since, chat_run.STATE.code_steps, chat_run.STATE.attempt = 0, None, [], ""
    chat_run.STATE.unchanged, chat_run.STATE.objects, chat_run.STATE.objects_wait = False, [], False
    chat_run.STATE.planning, chat_run.STATE.plan, chat_run.STATE.plan_waiting, chat_run.STATE.billed = False, None, False, False
    main_thread.tag_redraw()



def dismiss():
    """Keep the scene after a stop: the bar goes back to idle; what was built stays."""
    reset_view()



def _lost(run):
    """True when the running run's scene is gone, or its collection was deleted after it made one."""
    try:
        run.build.scene
        name = run.build.collection_name
    except (RuntimeError, ReferenceError):
        return True
    if name is not None:
        run.had_collection = True
        return False
    return run.had_collection



def _check_lost():
    """A run whose scene or collection the person deleted ends, and the bar goes back to idle."""
    run = chat_run._run
    now = time.monotonic()
    if run is None or not chat_run.STATE.running or now - run.checked_at < chat_run.LOST_READ_EVERY:
        return
    run.checked_at = now
    if _lost(run):
        chat_run.cancel(drop_build=True)
        viewport_marks.clear()
        reset_view()



def tick():
    """Apply queued chat work for at most ``TICK_BUDGET`` seconds; True while a run is busy."""
    _check_lost()
    try:
        objects_busy = object_jobs._objects_tick()
    except Exception:  # the 3D objects must not stop the chat's queue
        traceback.print_exc()
        objects_busy = False
    deadline = time.perf_counter() + chat_run.TICK_BUDGET
    while time.perf_counter() < deadline:
        try:
            func = chat_run._calls.get_nowait()
        except queue.Empty:
            break
        try:
            func()
        except Exception:  # One failed call must not stop the rest of the queue.
            traceback.print_exc()
        undo_watch._quiet()
    thread = chat_run.worker()
    return chat_run.STATE.running or objects_busy or not chat_run._calls.empty() or (thread is not None and thread.is_alive())



def hook():
    return "busy" if tick() else False
