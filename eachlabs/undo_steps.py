"""The name of Blender's active undo step, for the chat's *Undo stage* pill. Main thread only.

Python has no reader for the undo stack. ``WindowManager.print_undo_steps()`` prints it to the
process's standard output (C ``printf``) in 4.2 and 5.x alike, one line per step with ``*`` on the
active one, so the output is caught by pointing file descriptor 1 at a temporary file for the call.
Anything that fails (no standard output, an unknown C library, a changed format) reads as ``None``:
"unknown", never as a step name.
"""

import ctypes
import os
import re
import sys
import tempfile

# [* M ]   3 {0x...} type='Global Undo', name='Eachlabs: light'
_LINE = re.compile(r"^\[(?P<flags>[^\]]*)\]\s+\d+\s.*name='(?P<name>.*)'\s*$")
_libc = []


def _flush_c():
    if not _libc:
        name = "ucrtbase" if sys.platform == "win32" else None
        _libc.append(ctypes.CDLL(name))
    _libc[0].fflush(None)


def parse(text):
    """The active step's name in ``print_undo_steps`` output, or ``None``."""
    for line in (text or "").splitlines():
        match = _LINE.match(line.strip())
        if match and match.group("flags").startswith("*"):
            return match.group("name")
    return None


def _printed():
    import bpy

    wm = bpy.context.window_manager
    if wm is None or not hasattr(wm, "print_undo_steps"):
        return None
    sys.stdout.flush()
    _flush_c()
    saved = os.dup(1)
    try:
        with tempfile.TemporaryFile() as tmp:
            os.dup2(tmp.fileno(), 1)
            try:
                wm.print_undo_steps()
                _flush_c()
            finally:
                os.dup2(saved, 1)
            tmp.seek(0)
            return tmp.read().decode("utf-8", "replace")
    finally:
        os.close(saved)


def active_name():
    """The active undo step's name, or ``None`` when it cannot be read (always in background mode,
    where the chat pushes no undo steps)."""
    import bpy

    if bpy.app.background:
        return None
    try:
        return parse(_printed())
    except Exception:  # Unknown means the caller falls back to its own tracking.
        return None
