"""Blender 4.2's rule for operators while another Python thread runs."""

import os
import sys
import threading
import time
import types

from eachlabs import main_thread, render_export
from tests.smoke.common import WORK, check


def test_thread_guard(scene):
    """Blender 4.2: nothing of the add-on calls bpy.ops under temp_override while a chat run is going."""
    from eachlabs import code_check, thread_safety

    old = sys.version_info < (3, 12)
    for name, step in (("temp_override", "with bpy.context.temp_override():\n    pass"),
                       ("bpy.ops.object.quick_smoke()", "bpy.ops.object.quick_smoke()")):
        try:
            code_check.check(step)
            refused = False
        except code_check.Refused as exc:
            refused = exc.rule == "context-override"
        check("thread guard: the filter refuses %s on Python before 3.12 only" % name, refused == old,
              "%s %s" % (sys.version.split()[0], refused))
    deadline = time.monotonic() + 10  # earlier chat workers end on their own; wait for them, bounded
    while time.monotonic() < deadline:
        workers = [t for t in threading.enumerate() if t.name == "eachlabs-chat"]
        if not workers:
            break
        main_thread.tick()  # a worker may wait for the main thread before it can end
        for worker in workers:
            worker.join(0.05)
    real_races, real_threads = thread_safety.override_races, thread_safety._chat_threads
    view = types.SimpleNamespace(type="VIEW_3D", regions=[types.SimpleNamespace(type="WINDOW")])
    context = types.SimpleNamespace(area=view, window=None)
    path = os.path.join(WORK, "guard", "still.png")
    calls = []
    try:
        alive = [t for t in threading.enumerate() if t.name == "eachlabs-chat"]
        check("thread guard: no chat worker counted once the chat runs are over", real_threads == 0 and not alive,
              "%s %d alive" % (real_threads, len(alive)))
        thread_safety.override_races = lambda: True
        thread_safety.chat_thread_started()
        unsafe = thread_safety.ops_override_unsafe()
        error = render_export.render_still(context, scene, path, render_export.VIEWPORT,
                                           lambda: calls.append("done"), calls.append)
        check("thread guard: a viewport snapshot during a chat run on Python before 3.12 is refused",
              unsafe and error == thread_safety.WAIT_FOR_CHAT and not calls and not os.path.exists(path)
              and not render_export.busy(), "%s %r %s" % (unsafe, error, calls))
        thread_safety.override_races = lambda: False
        check("thread guard: from Python 3.12 nothing is held back", not thread_safety.ops_override_unsafe())
        thread_safety.override_races = lambda: True
        thread_safety.chat_thread_ended()
        check("thread guard: with no chat run nothing is held back", not thread_safety.ops_override_unsafe())
    finally:
        thread_safety.override_races, thread_safety._chat_threads = real_races, real_threads
