"""Blender's render window stays closed while a shot renders: the clay clip and the key frames render in the
background of the person's work. Main thread only.

The person's choice (Preferences > Interface > Temporary Editors > Render In) is kept and put back once the job's
renders are over: finished, failed or stopped, and Blender's own render has let go."""

import bpy

from .. import jobs, main_thread, render_export

_saved = []  # the person's render_display_type while a shot hides it


def _view():
    return bpy.context.preferences.view


def hide():
    if not _saved:
        _saved.append(_view().render_display_type)
    _view().render_display_type = "NONE"


def restore():
    if _saved:
        _view().render_display_type = _saved.pop()


def _rendering(job):
    return (job.state == jobs.RENDERING and job.active) or render_export.busy()


def hide_while(job):
    """Hide the render window until ``job`` leaves its renders, then put the person's choice back."""
    hide()
    main_thread.add_task(lambda: _rendering(job) or restore() or False)
