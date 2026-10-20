"""The single ``bpy.app.timers`` dispatcher that reconciles worker results on the main thread."""

import queue
import traceback

import bpy

BUSY_INTERVAL = 0.2
IDLE_INTERVAL = 1.0
REDRAW_SPACES = {"VIEW_3D", "SEQUENCE_EDITOR", "PREFERENCES"}

_tasks = []  # Callables returning True while they still have work (for example a pending render).
_hooks = []  # Callables run every tick; return True to redraw, "busy" to also keep ticking fast.
_calls = queue.SimpleQueue()  # One-shot callables queued from worker threads via ``call_soon``.


def add_task(task):
    _tasks.append(task)
    _ensure_running()


def add_hook(hook):
    if hook not in _hooks:
        _hooks.append(hook)


def call_soon(func):
    """Run ``func`` on the main thread at the next tick. Safe to call from any thread."""
    _calls.put(func)


def tag_redraw():
    wm = getattr(bpy.context, "window_manager", None)
    if wm is None:
        return
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type in REDRAW_SPACES:
                area.tag_redraw()


def tick():
    """One reconciliation step. Also called directly by background scripts and tests."""
    busy = False
    redraw = False
    while True:
        try:
            func = _calls.get_nowait()
        except queue.Empty:
            break
        _safe(func)
        redraw = True
    for task in list(_tasks):
        still_running = _safe(task)
        if still_running:
            busy = True
        else:
            _tasks.remove(task)
            redraw = True
    for hook in _hooks:
        result = _safe(hook)
        if result:
            redraw = True
            busy = busy or result == "busy"
    if redraw or busy:
        tag_redraw()
    return busy


def _safe(func):
    try:
        return func()
    except Exception:
        traceback.print_exc()
        return False


def _timer():
    return BUSY_INTERVAL if tick() else IDLE_INTERVAL


def _ensure_running():
    if not bpy.app.timers.is_registered(_timer):
        bpy.app.timers.register(_timer, first_interval=BUSY_INTERVAL, persistent=True)


def start():
    _ensure_running()


def stop():
    if bpy.app.timers.is_registered(_timer):
        bpy.app.timers.unregister(_timer)
    _tasks.clear()
    _hooks.clear()
    while not _calls.empty():
        _calls.get_nowait()
