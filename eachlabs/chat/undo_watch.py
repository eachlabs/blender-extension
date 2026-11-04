"""Watching Blender's undo and the person's own edits, so Undo stage and the bar know what the chat changed."""

import bpy
import time
from bpy.app.handlers import persistent

from .live import chat_run
from .. import main_thread, scene_build, undo_steps


def _top_step():
    """Blender's active undo step, read again after a change or every ``UNDO_READ_EVERY`` seconds."""
    now = time.monotonic()
    if chat_run._undo["dirty"] or now - chat_run._undo["read_at"] >= chat_run.UNDO_READ_EVERY:
        chat_run._undo["top"], chat_run._undo["read_at"], chat_run._undo["dirty"] = undo_steps.active_name(), now, False
        chat_run._undo["readable"] = chat_run._undo["top"] is not None
    return chat_run._undo["top"]



def _tracking():
    """True when the undo stack cannot be read, so the handlers below decide when the pill hides."""
    if chat_run._undo["readable"] is None:
        _top_step()
    return not chat_run._undo["readable"]



def undoable_stages(fresh=False):
    """The stages *Undo stage* may undo, oldest first: none unless the last one is the active undo step
    (when that can be read). ``fresh``: read the undo stack now."""
    stages = chat_run._undoable_stages()
    if not stages or chat_run.STATE.running:
        return stages
    if fresh:
        chat_run._undo["dirty"] = True
    top = _top_step()
    if top is not None and top != scene_build.SceneBuild.undo_name(stages[-1]):
        return []
    return stages



def _changed():
    chat_run._undo["dirty"] = True



def _quiet():
    chat_run._undo["quiet_until"] = time.monotonic() + chat_run.QUIET



def _settle():
    """After the chat's own change outside a run: quiet, and take the selection as it is now."""
    _quiet()
    _changed()
    try:
        chat_run._undo["signature"] = _signature(bpy.context.scene)
    except Exception:  # No scene in this context; the next quiet update takes it.
        chat_run._undo["signature"] = None



def _undone_past_run():
    if chat_run._build is None or chat_run.STATE.running:
        return False
    try:
        return chat_run._build.collection_name is None
    except RuntimeError:  # the scene itself was undone away
        return True



@persistent
def on_undo(*_args):
    _changed()
    if chat_run._undo["own"]:
        return
    if _tracking():
        chat_run.STATE.changed = []
    if _undone_past_run():
        chat_run.reset_view()  # nothing the bar says about the run is true any more
    main_thread.tag_redraw()



def _signature(scene):
    """What an edit without a moved object changes: the object count, the selection, the active object."""
    layer = bpy.context.view_layer
    active = layer.objects.active if layer is not None else None
    selected = []
    for obj in scene.objects:
        try:
            if obj.select_get():
                selected.append(obj.name)
        except RuntimeError:  # not in this view layer
            pass
    return len(scene.objects), tuple(sorted(selected)), active.name if active else None



def _person_edit(scene, depsgraph):
    """True when this update is the person's edit, not the chat's own or a frame change.

    During a run, the person's edit is a moved or reshaped object the run did not make. After it, any
    moved or reshaped object, or a change to the object count, selection or active object, counts.
    Updates that only redraw shading (Blender sends them on its own) never count.
    """
    frame = scene.frame_current
    screen = getattr(bpy.context, "screen", None)
    if chat_run._undo["frame"] != frame or (screen is not None and screen.is_animation_playing):
        chat_run._undo["frame"] = frame
        _quiet()  # a frame change is followed by more updates of the same frame
    if time.monotonic() < chat_run._undo["quiet_until"]:
        if not chat_run.STATE.running:
            chat_run._undo["signature"] = _signature(scene)
        return False
    run_id = chat_run._build.run_id if chat_run._build is not None else None
    for update in depsgraph.updates:
        obj = update.id.original if isinstance(update.id, bpy.types.Object) else None
        if obj is not None and (update.is_updated_transform or update.is_updated_geometry) and (
                not chat_run.STATE.running or obj.get(scene_build.RUN) != run_id):
            return True
    if chat_run.STATE.running:
        return False
    return chat_run._undo["signature"] is not None and _signature(scene) != chat_run._undo["signature"]



@persistent
def on_depsgraph(scene, depsgraph):
    _changed()
    if chat_run.STATE.changed and _tracking() and _person_edit(scene, depsgraph):
        chat_run.STATE.changed = []
        main_thread.tag_redraw()



_HANDLERS = (("undo_post", on_undo), ("redo_post", on_undo), ("depsgraph_update_post", on_depsgraph))



def register_handlers():
    for name, func in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if func not in handlers:
            handlers.append(func)
    try:  # the add-on turned on with a file open
        chat_run.file_opened()
    except AttributeError:  # Blender is still starting: no file data yet; on_load_post comes
        pass



def unregister_handlers():
    for name, func in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if func in handlers:
            handlers.remove(func)
