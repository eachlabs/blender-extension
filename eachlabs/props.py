"""Scene settings (saved with the .blend) and session lists (window manager, not saved)."""

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty,
                       PointerProperty, StringProperty)

from . import capabilities as caps, catalog, timing

NONE = "NONE"

_SOURCE_ITEMS = {
    action: [(NONE, "None", "Do not send anything to this input")]
    + [(role, caps.SOURCES[role]["label"], "") for role in caps.sources_for(action)]
    for action in (caps.IMAGE, caps.VIDEO)
}


def _source_items(self, _context):
    return _SOURCE_ITEMS.get(self.action, _SOURCE_ITEMS[caps.IMAGE])


def _param_items(self, _context):
    return catalog.enum_items(self.target_key, self.name)


def _target_update(self, context):
    from . import pipeline

    pipeline.on_target_changed(context, self)


def _show_all_update(_self, context):
    catalog.populate(context)


class EachlabsBinding(bpy.types.PropertyGroup):
    """One URI input of the selected target and the render output sent to it."""

    title: StringProperty()
    action: StringProperty()
    media: StringProperty()
    is_array: BoolProperty()
    required: BoolProperty()
    description: StringProperty()
    source: EnumProperty(name="Source", items=_source_items,
                         description="Which render output Eachlabs receives in this input")
    filepath: StringProperty(name="File", subtype="FILE_PATH",
                             description="Image, video or audio file sent to this input (style frame, character sheet, music)")


class EachlabsParam(bpy.types.PropertyGroup):
    """One scalar model or workflow input, sent only when overridden."""

    title: StringProperty()
    kind: StringProperty()
    target_key: StringProperty()
    required: BoolProperty()
    description: StringProperty()
    enabled: BoolProperty(name="Override", description="Send this value instead of the model default")
    value_enum: EnumProperty(name="Value", items=_param_items)
    value_int: IntProperty(name="Value")
    value_float: FloatProperty(name="Value")
    value_bool: BoolProperty(name="Value")
    value_string: StringProperty(name="Value")


class EachlabsAction(bpy.types.PropertyGroup):
    target: StringProperty(name="Model or workflow", update=_target_update,
                           description="Eachlabs model or workflow that receives the render")
    prompt: StringProperty(name="Prompt", description="Sent as the target's prompt input")
    use_seed: BoolProperty(name="Seed", description="Send a fixed seed for repeatable results")
    seed: IntProperty(name="Seed", min=0, max=2147483647)
    show_all: BoolProperty(name="All URL-input models", update=_show_all_update,
                           description="Also list models whose category does not declare this input kind")
    bindings: CollectionProperty(type=EachlabsBinding)
    params: CollectionProperty(type=EachlabsParam)
    bound_key: StringProperty()
    show_params: BoolProperty(name="Parameters")
    extra_json: StringProperty(name="Extra inputs", description='JSON object merged into the request, e.g. {"num_images": 2}')
    last_inputs: StringProperty(description="Rendered inputs kept for re-run (JSON)")


class EachlabsSceneSettings(bpy.types.PropertyGroup):
    image: PointerProperty(type=EachlabsAction)
    video: PointerProperty(type=EachlabsAction)
    still_source: EnumProperty(
        name="Source",
        items=[("RENDER", "Render", "Render the current frame at the scene resolution"),
               ("VIEWPORT", "Viewport", "Fast snapshot of the 3D Viewport")],
        default="RENDER")
    open_in_editor: BoolProperty(name="Open in Image Editor", default=True)
    camera_background: BoolProperty(name="Camera background", default=True,
                                    description="Show the result as the active camera's background for A/B comparison")
    use_scene_range: BoolProperty(name="Scene range", default=True)
    frame_start: IntProperty(name="Start", default=1, min=0)
    frame_end: IntProperty(name="End", default=48, min=0)
    preview_height: EnumProperty(
        name="Preview",
        items=[("480", "480p", "Render about 480 pixels tall"),
               ("720", "720p", "Render about 720 pixels tall"),
               ("1080", "1080p", "Render about 1080 pixels tall"),
               ("0", "Scene", "Full scene resolution")],
        default="720")
    video_source: EnumProperty(
        name="Source",
        items=[("RENDER", "Render", "Render the frame range"),
               ("VIEWPORT", "Viewport", "Fast viewport playblast of the frame range")],
        default="RENDER")
    match_duration: BoolProperty(
        name="Match duration", default=True,
        description="Ask the model for the rendered length (its duration input), so results need no retiming")
    import_audio: BoolProperty(name="Import audio", default=True,
                               description="Add the clip's sound as a sequencer strip")
    timing_mode: EnumProperty(
        name="Timing",
        items=[(timing.FIT_RANGE, "Fit to range", "Stretch the result to the rendered frame range"),
               (timing.KEEP_TIMING, "Keep timing", "Play the result in real time at the scene frame rate")],
        default=timing.FIT_RANGE)


class EachlabsTargetItem(bpy.types.PropertyGroup):
    key: StringProperty()
    kind: StringProperty()


class EachlabsSession(bpy.types.PropertyGroup):
    image_targets: CollectionProperty(type=EachlabsTargetItem)
    video_targets: CollectionProperty(type=EachlabsTargetItem)


CLASSES = (EachlabsBinding, EachlabsParam, EachlabsAction, EachlabsSceneSettings,
           EachlabsTargetItem, EachlabsSession)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.eachlabs = PointerProperty(type=EachlabsSceneSettings)
    bpy.types.WindowManager.eachlabs = PointerProperty(type=EachlabsSession)


def unregister():
    del bpy.types.WindowManager.eachlabs
    del bpy.types.Scene.eachlabs
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
