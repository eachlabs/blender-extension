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
    mcp = preferences.mcp_status
    row = layout.row(align=True)
    row.label(text=mcp["text"] or "MCP not checked",
              icon="CHECKMARK" if mcp["ok"] else "ERROR" if mcp["ok"] is False else "PLUGIN")
    row.operator("eachlabs.check_mcp", text="", icon="FILE_REFRESH")
    prefs = preferences.get_preferences(context)
    from .ui import tokens

    if prefs is not None and tokens.CODE_CHECK_AVAILABLE:
        layout.prop(prefs, "chat_code_check")
        _wrap(layout, context, "Checks the chat's Blender Python before it runs.")
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


STAGE_ICONS = {"done": "CHECKMARK", "active": "SORTTIME", "failed": "ERROR", "cancelled": "CANCEL", "partial": "INFO"}
CHAT_ACTIONS = {"retry": ("eachlabs.chat_retry_stage", "FILE_REFRESH"), "undo": ("eachlabs.chat_undo_stage", "LOOP_BACK"),
                "frame": ("eachlabs.chat_frame_result", "ZOOM_SELECTED"), "play": ("eachlabs.chat_play", "PLAY"),
                "prefs": ("eachlabs.open_preferences", "PREFERENCES"),
                "network": ("eachlabs.open_preferences", "PREFERENCES"), "new": ("eachlabs.chat_new_scene", "ADD"),
                "code": ("eachlabs.chat_show_code", "TEXT"), "final": ("eachlabs.chat_final_render", "RENDER_STILL"),
                "video_stop": ("eachlabs.chat_video_stop", "CANCEL"),
                "video_retry": ("eachlabs.chat_video_retry", "FILE_REFRESH"),
                "video_open": ("eachlabs.chat_video_open", "SEQUENCE"), "video_file": ("eachlabs.chat_video_file", "FILEBROWSER")}


def draw_chat(layout, context):
    """The scene chat without the prompt bar (Skia unavailable): a prompt, Build, and the run's state."""
    import time

    from . import chat_run, overlay
    from .chat import playback
    from .ui import bar, bar_state, tokens

    chat = chat_run.STATE
    finished = chat.status in ("done", "stopped", "cancelled") and not chat.running
    undoable = chat_run.undoable_stages() if finished else None
    playing = playback.is_playing(context)
    cameras = playback.menu(context.scene) if finished and chat.status == "done" and not playing else []
    state = bar_state.from_chat(chat, overlay.FIELD, False, time.monotonic(), has_scene=chat_run.has_scene(),
                                undoable=undoable, advanced=preferences.advanced_tools(), cameras=cameras,
                                playing=playing)
    session = context.window_manager.eachlabs
    layout.prop(session, "chat_prompt", text="")
    row = layout.row(align=True)
    row.scale_y = 1.3
    if chat_run.STATE.running:
        row.operator("eachlabs.chat_cancel", text="Stop", icon="CANCEL")
    else:
        row.enabled = state.send_enabled
        row.operator("eachlabs.chat_send", text="Build", icon="PLAY").prompt = session.chat_prompt
    if state.mode == "plan":  # the plan waits for Build; Stop above is its Cancel
        for text, chips in ((state.plan_3d, [c for c in state.plan_chips if c[2] == "3d"]),
                            (state.plan_code, [c for c in state.plan_chips if c[2] == "code"])):
            if text:
                _wrap(layout, context, text)
            col = layout.column(align=True)
            for index, label, mode, cached in chips:
                text = "%s · %s" % (label, tokens.PLAN_CACHED) if cached and mode == "3d" else label
                col.operator("eachlabs.chat_plan_toggle", text=text,
                             icon="MESH_MONKEY" if mode == "3d" else "SCRIPT").index = index
        _wrap(layout, context, state.plan_note or tokens.PLAN_HINT)
        layout.operator("eachlabs.chat_plan", text="Build", icon="PLAY").answer = "build"
    if state.stages:
        row = layout.row(align=True)
        for stage, value in state.stages.items():
            row.label(text=stage.capitalize(), icon=STAGE_ICONS.get(value, "DOT"))
    if state.mode == "waiting":
        layout.label(text="%s · %d s" % (tokens.THINKING, state.thinking_seconds), icon="SORTTIME")
        if state.thinking_seconds >= tokens.SLOW_AFTER:
            _wrap(layout, context, tokens.SLOW_TEXT)
    for text, alert in ((state.status, False), (state.reply, False), (state.error, True)):
        if text:
            _wrap(layout, context, text, alert=alert)
    if state.cost_text:
        layout.label(text=state.cost_text)
    if state.actions:
        row = layout.row(align=True)
        for action in state.actions:
            if action not in CHAT_ACTIONS:  # Keep, and Stop while running: the Build row has them
                continue
            idname, icon = CHAT_ACTIONS[action]
            if action == "play":  # Play as the chosen camera and its camera menu, or Pause while it plays
                sub = row.row(align=True)
                sub.operator(idname, text=bar.play_label(state), icon="PAUSE" if state.playing else icon)
                if state.play_camera and not state.playing:
                    sub.operator_menu_enum("eachlabs.chat_play_camera", "camera", text="", icon="CAMERA_DATA")
                continue
            props = row.operator(idname, text=bar.action_label(action, state.stages, state.undo_stage),
                                 icon=icon)
            if action == "network":
                props.section = "SYSTEM"


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


def _chat_fallback():
    from . import overlay

    return not overlay.active()


SPACES = (("VIEW_3D", "view3d"), ("SEQUENCE_EDITOR", "sequencer"))


def _panel(space, suffix, name, label, draw, parent=None, closed=False, poll=None):
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
    if poll:
        attrs["poll"] = classmethod(lambda cls, context: poll())
    return type("EACHLABS_PT_%s_%s" % (suffix, name), (bpy.types.Panel,), attrs)


def _classes():
    classes = []
    for space, suffix in SPACES:
        main = _panel(space, suffix, "main", "Eachlabs", draw_status)
        parent = main.__name__
        classes.append(main)
        if space == "VIEW_3D":
            classes.append(_panel(space, suffix, "chat", "Scene Chat", draw_chat, parent, poll=_chat_fallback))
        classes += [
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
