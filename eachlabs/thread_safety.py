"""When Blender operators may run inside ``context.temp_override``. Pure, no ``bpy``.

On Python before 3.12 (Blender 4.2), ``bpy.ops`` inside ``temp_override`` can read Python data without the
GIL while another thread runs Python, and Blender crashes. See "Blender 4.2 and threads" in
docs/architecture.md.
"""

import sys
import threading

WAIT_FOR_CHAT = "Wait for the scene chat and its 3D objects to finish, then try again."

_lock = threading.Lock()
_chat_threads = 0  # chat worker threads that are running; chat_run counts them in and out
_gen_threads = 0  # generation workers (3D objects, textures); generation.Registry counts them in and out


def override_races():
    """True when this Python has the bug: before 3.12."""
    return sys.version_info < (3, 12)


def chat_thread_started():
    """Called by chat_run on the main thread just before a chat worker starts."""
    global _chat_threads
    with _lock:
        _chat_threads += 1


def chat_thread_ended():
    """Called by the chat worker as its last step. An abandoned worker can end after the next run started,
    so this is a count, not a flag."""
    global _chat_threads
    with _lock:
        _chat_threads = max(0, _chat_threads - 1)


def gen_thread_started():
    """Called by generation.Registry on the main thread just before a generation worker starts. Such a worker can
    outlive the chat run that ordered it, so it is counted on its own."""
    global _gen_threads
    with _lock:
        _gen_threads += 1


def gen_thread_ended():
    """Called by the generation worker as its last step."""
    global _gen_threads
    with _lock:
        _gen_threads = max(0, _gen_threads - 1)


def ops_override_unsafe():
    """True while ``bpy.ops`` inside ``temp_override`` can crash Blender: a chat or generation worker runs on Python
    before 3.12."""
    return (_chat_threads > 0 or _gen_threads > 0) and override_races()

