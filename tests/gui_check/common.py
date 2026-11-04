"""What every GUI scenario shares: checks, windows, parked threads, screenshots, the scene file and waits."""

import contextlib
import importlib
import os
import threading
import time

import bpy

from eachlabs import chat_run, jobs, pipeline
from tests.gui_check.args import OUT


RESULTS = []
STATE = {"gaps": [], "last": None}


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition)))
    print("%s  %s%s" % ("PASS" if condition else "FAIL", name, ("  (%s)" % detail) if detail else ""), flush=True)


def window():
    return bpy.context.window_manager.windows[0]


def area_of(kind):
    return next((a for a in window().screen.areas if a.type == kind), None)


# -- parking -----------------------------------------------------------------------------------
# On Blender 4.2 (Python 3.11) an operator under temp_override can run without the GIL while another
# thread runs Python, and Blender crashes (see "Blender 4.2 and threads" in docs/architecture.md). So the
# harness calls such operators only inside ``parked()``, while every add-on thread waits:
# - the chat worker and the job workers hold RUN while they run Python. They let go of it only in waits
#   that the main thread ends: ``hold`` (the fake model's pause, the job poll) and the executor's wait for
#   Blender. Once the harness holds RUN, nothing can wake them until it lets go;
# - the short-lived add-on threads are joined first.

RUN = threading.Lock()
SHORT_THREADS = ("eachlabs-catalog", "eachlabs-cost", "eachlabs-test", "eachlabs-mcp-check", "eachlabs-step-limit")
_parked_ids = set()  # threads that hold RUN while they run Python
_finished = []  # parked threads whose work is over; ``parked()`` joins them
_holds = []  # [due, gate, cancel] for each ``hold`` the main thread has not ended yet
_holds_lock = threading.Lock()


@contextlib.contextmanager
def _released():
    """On a parked thread, let go of RUN around a wait."""
    if threading.get_ident() not in _parked_ids:
        yield
        return
    RUN.release()
    try:
        yield
    finally:
        RUN.acquire()


def hold(seconds, cancel=None):
    """A sleep that only the main thread ends, after ``seconds`` or once ``cancel`` is set: an untimed wait,
    so the thread cannot wake while the harness runs an operator. Returns whether ``cancel`` is set."""
    gate = threading.Event()
    with _holds_lock:
        _holds.append((time.monotonic() + seconds, gate, cancel))
    with _released():
        gate.wait()
    return cancel is not None and cancel.is_set()


def _end_holds():
    now = time.monotonic()
    with _holds_lock:
        due = [h for h in _holds if h[0] <= now or (h[2] is not None and h[2].is_set())]
        for h in due:
            _holds.remove(h)
    for _due, gate, _cancel in due:
        gate.set()
    return 0.02


class _ParkedEvent(threading.Event):
    def wait(self, timeout=None):  # the executor's wait for Blender; the main thread sets it
        with _released():
            return super().wait(timeout)


def _parked(func):
    def body(*args, **kwargs):
        _parked_ids.add(threading.get_ident())
        with RUN:
            try:
                return func(*args, **kwargs)
            finally:  # still holding RUN, so ``parked()`` sees the thread as finished and joins it
                _parked_ids.discard(threading.get_ident())
                _finished.append(threading.current_thread())
    return body


def install_parking():
    from eachlabs import chat_loop

    chat_run._work = _parked(chat_run._work)
    real_job = jobs.run
    jobs.run = _parked(lambda spec, cancel, emit, client=None: real_job(
        spec, cancel, emit, client, sleep=lambda seconds: hold(seconds, cancel)))
    chat_loop.threading = type("T", (), {"Event": _ParkedEvent})
    from eachlabs.chat import run_types
    run_types.threading = chat_loop.threading  # the executor's waits live there
    bpy.app.timers.register(_end_holds, persistent=True)


@contextlib.contextmanager
def parked():
    """Every add-on thread waits while the block runs."""
    got = RUN.acquire(timeout=15)
    if not got:
        print("WARN parked: an add-on thread kept running for 15 s", flush=True)
        check("parked: every add-on thread waits before an operator under temp_override", False,
              "RUN was held for 15 s")
    try:
        joining = [t for t in threading.enumerate() if t.name in SHORT_THREADS] + _finished
        del _finished[:]
        for thread in joining:
            thread.join(5)
            if thread.is_alive():
                print("WARN parked: %s still runs after 5 s" % thread.name, flush=True)
                check("parked: every add-on thread waits before an operator under temp_override", False,
                      "%s still runs" % thread.name)
        time.sleep(0.01)  # a parked thread the main thread just woke reaches its wait for RUN
        yield
    finally:
        if got:
            RUN.release()


@contextlib.contextmanager
def override(kind="VIEW_3D"):
    area = area_of(kind)
    region = next(r for r in area.regions if r.type == "WINDOW")
    with parked(), bpy.context.temp_override(window=window(), area=area, region=region):
        yield


def scroll_sidebar(pages):
    """Scroll the 3D Viewport sidebar so panels further down (Jobs) show in screenshots."""
    area = area_of("VIEW_3D")
    region = next(r for r in area.regions if r.type == "UI")
    with parked(), bpy.context.temp_override(window=window(), area=area, region=region):
        for _ in range(pages):
            bpy.ops.view2d.scroll_down(page=True)


def screenshot(name):
    path = os.path.join(OUT, name)
    with parked(), bpy.context.temp_override(window=window()):
        bpy.ops.screen.screenshot(filepath=path)
    print("SHOT", path, flush=True)


def show_sidebar(area):
    area.spaces.active.show_region_ui = True
    area.tag_redraw()


def panels_in_active_tabs():
    """Scripts cannot pick a sidebar tab (Region.active_panel_category is read-only), so for the
    screenshots the Eachlabs panels join the tab each sidebar opens on. Draw code is unchanged."""
    from eachlabs import panels

    panels.unregister()
    for cls in panels.CLASSES:
        if not getattr(cls, "bl_parent_id", None):
            cls.bl_category = "Item" if cls.bl_space_type == "VIEW_3D" else "Strip"
            cls.bl_order = -1
    panels.register()


def build_scene():
    """Background step: a 48-frame camera orbit, saved so the GUI opens it without the splash."""
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x, scene.render.resolution_y = 640, 360
    scene.render.fps = 24
    scene.frame_start, scene.frame_end = 10, 57
    pivot = bpy.data.objects.new("Orbit", None)
    scene.collection.objects.link(pivot)
    scene.camera.parent = pivot
    scene.camera.constraints.new("TRACK_TO").target = bpy.data.objects["Cube"]
    pivot.keyframe_insert("rotation_euler", index=2, frame=10)
    pivot.rotation_euler[2] = 6.283185
    pivot.keyframe_insert("rotation_euler", index=2, frame=58)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "gui_check.blend"))


def setup():
    show_sidebar(area_of("VIEW_3D"))
    timeline = area_of("DOPESHEET_EDITOR") or area_of("TIMELINE")
    timeline.type = "SEQUENCE_EDITOR"
    timeline.spaces.active.view_type = "SEQUENCER"
    show_sidebar(timeline)


def wait_for(predicate, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        yield 0.1
    return False


def watch_ticks():
    """Our own timer: if the UI thread blocked, the gap between ticks would grow."""
    now = time.perf_counter()
    if STATE["last"] is not None and STATE.get("measure"):
        STATE["gaps"].append(now - STATE["last"])
    STATE["last"] = now
    return 0.05


def latest_job():
    return list(pipeline.REGISTRY.jobs.values())[-1]


SKIPPED = []  # flow modules not in this checkout


def optional(module, name):
    """``tests.gui_check.<module>.<name>``, or a step that does nothing when that module is not in this checkout."""
    full = "tests.gui_check." + module
    try:
        return getattr(importlib.import_module(full), name)
    except ModuleNotFoundError as exc:
        if exc.name != full:
            raise
    if module not in SKIPPED:
        SKIPPED.append(module)

    def skipped(*args, **kwargs):
        return None
        yield

    return skipped
