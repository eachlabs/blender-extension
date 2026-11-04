"""Whether the next prompt continues the current scene, and dropping Blender's startup Cube for a new one."""

import bpy
import traceback

from .live import chat_run
from .. import scene_build


def continues(scene):
    """True when a prompt in ``scene`` changes the current scene instead of starting a new one: the
    chat built something here, the person did not start a new scene, and its collection still exists."""
    if chat_run._build is None or not chat_run._build.prompts:
        return False
    try:
        return chat_run._build.scene == scene and chat_run._build.collection_name is not None
    except RuntimeError:  # the build's scene is gone
        return False



def has_scene():
    """For the bar's placeholder: is there a scene the next prompt changes?"""
    try:
        scene = bpy.context.scene
        return continues(scene) or (not chat_run._no_resume and _built_in(scene))
    except Exception:  # no scene in this context
        return False



def _built_in(scene):
    """Whether ``scene`` holds a collection the chat built, from this session or the opened file."""
    return any(c.get(scene_build.RUN) for c in scene.collection.children_recursive)



def _drop_cube(run):
    """Main thread, when a new scene's stages start (after the plan): delete Blender's untouched startup Cube. It is
    part of the layout stage's undo step."""
    if run is not chat_run._run or run.cancel.is_set():
        return
    try:
        run.build.drop_startup_cube()
    except Exception:  # a convenience; the run goes on
        traceback.print_exc()
