"""The Eachlabs sidebar tab, identical in the 3D Viewport and the Video Sequencer."""

import textwrap

import bpy

from . import capabilities as caps, catalog, compat, jobs, pipeline, preferences

STATE_ICONS = {
    jobs.RENDERING: "RENDER_STILL",
    jobs.UPLOADING: "EXPORT",
    jobs.SUBMITTING: "EXPORT",
    jobs.QUEUED: "SORTTIME",
    jobs.RUNNING: "PLAY",
    jobs.DOWNLOADING: "IMPORT",
    jobs.IMPORTING: "IMPORT",
    jobs.DONE: "CHECKMARK",
    jobs.FAILED: "ERROR",
    jobs.CANCELLED: "CANCEL",
}

ACTION_LABELS = {caps.IMAGE: "Image", caps.VIDEO: "Video", pipeline.EXPORT: "Movie"}

PARAM_ATTR = {"enum": "value_enum", "int": "value_int", "float": "value_float", "bool": "value_bool"}


def _wrap(layout, context, text, icon="NONE", alert=False):
    # Region width is in pixels; ui_scale folds in display scale and Retina pixel size.
    scale = context.preferences.system.ui_scale if context.preferences else 1.0
    width = max(20, int((context.region.width if context.region else 300) / (6.5 * scale)) - 4)
    column = layout.column(align=True)
    column.alert = alert
    for index, line in enumerate(textwrap.wrap(text, width) or [""]):
        column.label(text=line, icon=icon if index == 0 else "BLANK1" if icon != "NONE" else "NONE")


def draw_status(layout, context):
    problem = compat.online_problem()
    if problem:
        box = layout.box()
        _wrap(box, context, problem, icon="ERROR", alert=True)
        box.operator("eachlabs.open_preferences", text="Open System preferences", icon="PREFERENCES").section = "SYSTEM"
    if not preferences.settings(context)["api_key"]:
        box = layout.box()
        _wrap(box, context, "Add your Eachlabs API key to start.", icon="KEYINGSET")
        box.operator("eachlabs.open_preferences", text="Set API key", icon="PREFERENCES")
    row = layout.row(align=True)
    state = catalog.STATUS["state"]
    text = {"": "Models not loaded", "LOADING": "Loading models…"}.get(state, catalog.STATUS["message"])
    row.label(text=text, icon="ERROR" if state == "ERROR" else "WORLD")
    row.operator("eachlabs.refresh_catalog", text="", icon="FILE_REFRESH")
    if state == "ERROR":
        _wrap(layout, context, catalog.STATUS["message"], alert=True)
    if not bpy.data.filepath:
        _wrap(layout, context, "Unsaved file: inputs and results go to a temp folder. Save to keep them next to the .blend.",
              icon="INFO")


def _draw_target(layout, context, settings, collection_name, icon, default_button=False):
    row = layout.row(align=True)
    row.prop_search(settings, "target", context.window_manager.eachlabs, collection_name, text="", icon=icon)
    if default_button:
        row.operator("eachlabs.use_default_video", text="", icon="SOLO_ON")
    layout.prop(settings, "show_all")
    target = catalog.resolve(settings.target)
    if settings.target and target is None:
        _wrap(layout, context, "Refresh the list to use this target.", icon="INFO")
    return target


def _draw_inputs(layout, context, settings, target):
    if target.has_prompt:
        layout.prop(settings, "prompt")
    if target.has_seed:
        row = layout.row(align=True)
        row.prop(settings, "use_seed", text="Seed")
        sub = row.row(align=True)
        sub.active = settings.use_seed
        sub.prop(settings, "seed", text="")
    box = layout.box()
    box.label(text="Send render to", icon="LINKED")
    for binding in settings.bindings:
        row = box.row()
        row.label(text=("%s *" if binding.required else "%s") % binding.name)
        row.prop(binding, "source", text="")
        if binding.source == caps.FILE:
            box.prop(binding, "filepath", text="")
    if settings.bindings and all(b.source == "NONE" for b in settings.bindings):
        _wrap(box, context, "Eachlabs does not say which input takes which media yet; pick one.", alert=True)
    header = layout.row()
    header.prop(settings, "show_params", icon="TRIA_DOWN" if settings.show_params else "TRIA_RIGHT", emboss=False)
    if settings.show_params:
        column = layout.column()
        for param in settings.params:
            row = column.row(align=True)
            row.prop(param, "enabled", text=("%s *" if param.required else "%s") % param.name)
            sub = row.row(align=True)
            sub.active = param.enabled
            sub.prop(param, PARAM_ATTR.get(param.kind, "value_string"), text="")
        column.prop(settings, "extra_json", text="JSON")


def _draw_price(layout, target):
    text = catalog.price_text(target)
    if text:
        layout.label(text=text)


def draw_image(layout, context):
    scene_settings = context.scene.eachlabs
    settings = scene_settings.image
    target = _draw_target(layout, context, settings, "image_targets", "IMAGE_DATA")
    if target is not None:
        _draw_price(layout, target)
        _draw_inputs(layout, context, settings, target)
    layout.row().prop(scene_settings, "still_source", expand=True)
    row = layout.row()
    row.prop(scene_settings, "open_in_editor", text="Image Editor")
    row.prop(scene_settings, "camera_background")
    row = layout.row(align=True)
    row.scale_y = 1.3
    row.operator("eachlabs.generate_image", icon="RENDER_STILL")
    sub = row.row(align=True)
    sub.enabled = pipeline.last_inputs(settings) is not None
    sub.operator("eachlabs.rerun", text="", icon="RECOVER_LAST").action = caps.IMAGE


def draw_video(layout, context):
    scene = context.scene
    scene_settings = scene.eachlabs
    settings = scene_settings.video
    target = _draw_target(layout, context, settings, "video_targets", "FILE_MOVIE", default_button=True)
    if target is not None:
        _draw_price(layout, target)
        _draw_inputs(layout, context, settings, target)
    column = layout.column(align=True)
    column.prop(scene_settings, "use_scene_range")
    row = column.row(align=True)
    if scene_settings.use_scene_range:
        row.enabled = False
        row.prop(scene, "frame_start", text="Start")
        row.prop(scene, "frame_end", text="End")
    else:
        row.prop(scene_settings, "frame_start")
        row.prop(scene_settings, "frame_end")
    layout.prop(scene_settings, "preview_height")
    layout.row().prop(scene_settings, "video_source", expand=True)
    row = layout.row()
    row.prop(scene_settings, "match_duration")
    row.prop(scene_settings, "import_audio")
    layout.prop(scene_settings, "timing_mode")
    row = layout.row(align=True)
    row.scale_y = 1.3
    row.operator("eachlabs.generate_video", icon="RENDER_ANIMATION")
    sub = row.row(align=True)
    sub.enabled = pipeline.last_inputs(settings) is not None
    sub.operator("eachlabs.rerun", text="", icon="RECOVER_LAST").action = caps.VIDEO
    layout.operator("eachlabs.export_movie", icon="SEQUENCE")


def draw_jobs(layout, context):
    registry = pipeline.REGISTRY
    if not registry.jobs:
        layout.label(text="No jobs yet")
    for job in reversed(list(registry.jobs.values())):
        box = layout.box()
        row = box.row()
        row.label(text="%s · %s" % (ACTION_LABELS.get(job.action, job.action), job.label),
                  icon=STATE_ICONS.get(job.state, "DOT"))
        if job.active:
            row.operator("eachlabs.cancel_job", text="", icon="X").job_id = job.job_id
        elif job.state == jobs.DONE and job.outputs:
            row.operator("eachlabs.open_file", text="", icon="PLAY").filepath = job.outputs[0][0]
        detail = "%s · %s" % (jobs.LABELS.get(job.state, job.state), jobs.format_elapsed(job.elapsed))
        if job.cost is not None:
            detail += " · $%.2f" % job.cost
        box.label(text=detail)
        if job.error:
            _wrap(box, context, job.error, alert=True)
        elif job.message:
            _wrap(box, context, job.message)
    row = layout.row(align=True)
    row.operator("eachlabs.open_folder", icon="FILE_FOLDER")
    if any(not j.active for j in registry.jobs.values()):
        row.operator("eachlabs.clear_jobs", icon="TRASH")


SPACES = (("VIEW_3D", "view3d"), ("SEQUENCE_EDITOR", "sequencer"))


def _panel(space, suffix, name, label, draw, parent=None, closed=False):
    attrs = {
        "bl_space_type": space,
        "bl_region_type": "UI",
        "bl_category": "Eachlabs",
        "bl_label": label,
        "draw": lambda self, context: draw(self.layout, context),
    }
    if parent:
        attrs["bl_parent_id"] = parent
    if closed:
        attrs["bl_options"] = {"DEFAULT_CLOSED"}
    return type("EACHLABS_PT_%s_%s" % (suffix, name), (bpy.types.Panel,), attrs)


def _classes():
    classes = []
    for space, suffix in SPACES:
        main = _panel(space, suffix, "main", "Eachlabs", draw_status)
        parent = main.__name__
        classes += [
            main,
            _panel(space, suffix, "image", "Generate Image from View", draw_image, parent),
            _panel(space, suffix, "video", "Generate Video from Camera Move", draw_video, parent),
            _panel(space, suffix, "jobs", "Jobs", draw_jobs, parent),
        ]
    return classes


CLASSES = _classes()


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
