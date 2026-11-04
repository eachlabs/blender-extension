"""What the person points at: the selection and names a prompt reads, Find, and asking for a selection when none is made."""

import bpy
import traceback

from .. import chat_loop, intent, main_thread, startup_cube
from ..scene import new_scene
from ..things import ids, registry
from .live import chat_run


def _on_tab(obj, layer, scene):
    """A selected object that Assets and Characters change: shown, not a light or a camera, and not Blender's
    untouched startup Cube (selected in every new file, it would turn the first added object into a change)."""
    if obj.type in registry.SKIP_TYPES:
        return False
    try:
        if not obj.visible_get(view_layer=layer):
            return False
    except RuntimeError:  # not in this view layer
        return False
    return not (obj.name == "Cube" and startup_cube.matches(new_scene.cube_facts(obj, scene)))


def _top(obj):
    while obj.parent is not None:
        obj = obj.parent
    return obj


def selected_things(context):
    """Main thread, for the bar: the names of the selected things that Assets and Characters change, a selected part
    as its whole thing."""
    layer, scene = getattr(context, "view_layer", None), getattr(context, "scene", None)
    if layer is None or scene is None:
        return []
    names = []
    for obj in layer.objects.selected:
        if not _on_tab(obj, layer, scene):
            continue
        name = (registry.root_of(obj) or _top(obj)).name
        if name not in names:
            names.append(name)
    return names


def clear(context):
    """Main thread: the tab chip's cross. Nothing is selected afterwards, so the next prompt adds."""
    layer = getattr(context, "view_layer", None)
    for obj in list(layer.objects.selected) if layer is not None else ():
        obj.select_set(False)


def _scene_names(build, context, things_only=False):
    """Main thread, when a run starts: the chat's things (root names), and what is selected (session_uid of each
    selected thing with all its parts and child things, and the things' names). A selected part means its thing.
    ``things_only``: the selection as Assets and Characters read it (``_on_tab``)."""
    try:
        mine = build._objects()
        roots = [e["name"] for e in registry.inventory(mine)]
        layer = getattr(context, "view_layer", None) or build.scene.view_layers[0]
        selected = []
        for obj in build.scene.objects:
            if not _selected(obj, layer) or things_only and not _on_tab(obj, layer, build.scene):
                continue
            root = registry.root_of(obj) if build.owns(obj) else None
            if root is None:  # the person's object, or one from before things: its top object
                root = _top(obj)
            if root not in selected:
                selected.append(root)
    except (RuntimeError, ReferenceError, AttributeError):
        return [], [], []
    names = [o.name for o in selected]
    whole = registry.subtree_objects(mine, names)
    with_parts = list(dict.fromkeys([o.session_uid for o in whole] + [
        o.session_uid for root in selected if not registry.is_root(root)
        for o in [root] + list(root.children_recursive)]))
    return roots[:intent.NAMES_MAX], with_parts, names


def _inventory(build):
    """Main thread: one line per thing of the chat's, for the intent call."""
    try:
        return [ids.inventory_line(e) for e in registry.inventory(build._objects())][:intent.NAMES_MAX]
    except (RuntimeError, ReferenceError):
        return []



def _selected(obj, layer):
    try:
        return obj.select_get(view_layer=layer)
    except RuntimeError:  # not in this view layer
        return False



def _read_prompt(run, prompt, llm, note=""):
    """Worker thread: one quick call that reads what the prompt asks for. Only the chat's own names and the number
    of selected objects are sent. ``None`` when the call fails: the run builds as usual. ``note``: the tab's line
    (``targets.KIND_NOTE``)."""
    messages = [{"role": "system", "content": intent.INSTRUCTIONS},
                {"role": "user", "content": intent.request(prompt, run.names, len(run.selected),
                                                           getattr(run, "things", None), note)}]
    try:
        reply = llm(messages, [])
        text = reply["choices"][0]["message"].get("content") or ""
    except Exception as exc:  # the run builds as usual
        chat_loop.debug_log({"stage": "intent", "error": str(exc)}, run.secrets)
        return None
    chat_loop.debug_log({"stage": "intent", "messages": messages, "reply": text}, run.secrets)
    return intent.parse(text, run.names)



def _found(run, asked):
    """Main thread: select and frame what a find asked for, or list the main things; the bar says it."""
    if run is not chat_run._run:
        return
    if run.build.prompts and run.build.prompts[0] == chat_run.STATE.prompt:
        del run.build.prompts[:1]  # a question is not a change to the scene
    if asked["intent"] == intent.LIST:
        chat_run.STATE.reply, chat_run.STATE.found = intent.list_text(asked["names"]), []
        return
    found = select_objects(run.build, asked["names"])
    chat_run.STATE.found = [o.name for o in found]
    if not found:
        chat_run.STATE.reply = intent.nothing_text(asked["label"])
        return
    chat_run.STATE.reply = intent.found_text(asked["label"] or found[0].name, len(found))
    try:
        chat_run.frame_objects(found, chat_run._area(run.view))
    except Exception:  # framing is a convenience
        traceback.print_exc()



def select_objects(build, names):
    """Main thread: select the things with these names, with all their parts and child things; returns them."""
    objects = list(registry.subtree_objects(build._objects(), names))
    for name in names:  # an object from before things: it and everything under it
        root = build.scene.objects.get(name)
        if root is None or not build.owns(root) or registry.is_root(root):
            continue
        for obj in [root] + list(root.children_recursive):
            if obj not in objects:
                objects.append(obj)
    if not objects:
        return []
    layer = bpy.context.view_layer if bpy.context.scene == build.scene else build.scene.view_layers[0]
    for obj in build.scene.objects:
        if _selected(obj, layer):
            obj.select_set(False, view_layer=layer)
    for obj in objects:
        try:
            obj.select_set(True, view_layer=layer)
        except RuntimeError:
            pass
    layer.objects.active = objects[0]
    chat_run._settle()
    return objects



def _needs_selection(run):
    """Main thread: the prompt points at the selection and nothing is selected; nothing ran."""
    if run is not chat_run._run:
        return
    chat_run.STATE.running, chat_run.STATE.status, chat_run.STATE.stages = False, "idle", {}
    chat_run.STATE.error = intent.NEEDS_SELECTION
    if run.build.prompts and run.build.prompts[0] == chat_run.STATE.prompt:
        del run.build.prompts[:1]
    if chat_run.restore_prompt is not None:
        try:
            chat_run.restore_prompt(chat_run.STATE.prompt)
        except Exception:
            traceback.print_exc()
    main_thread.tag_redraw()
