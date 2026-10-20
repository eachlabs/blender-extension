"""Orchestrates each action: validate, render, start the job, import the result."""

import json
import os
import shutil
import time

import bpy

from . import (api_client, capabilities as caps, catalog, compat, importers, jobs, main_thread, naming,
               preferences, render_export, timing)

REGISTRY = jobs.Registry()
EXPORT = "EXPORT"

# Reuse an uploaded file for re-runs until a day before its 7-day retention ends.
UPLOAD_REUSE_SECONDS = api_client.UPLOAD_RETENTION_SECONDS - 24 * 3600


class Problem(Exception):
    """A user-facing reason an action cannot start."""


def action_settings(scene, action):
    return scene.eachlabs.image if action == caps.IMAGE else scene.eachlabs.video


def _action_of(settings):
    return caps.IMAGE if settings.path_from_id().endswith("image") else caps.VIDEO


# -- target selection -------------------------------------------------------------------------


def on_target_changed(context, settings):
    target = catalog.resolve(settings.target)
    if target is None:
        if not settings.target:
            settings.bindings.clear()
            settings.params.clear()
            settings.bound_key = ""
        return
    if settings.bound_key != target.key:
        rebuild_inputs(settings, target, _action_of(settings))
    if target.kind == caps.MODEL:
        catalog.fetch_cost(target.key, context)


def rebuild_inputs(settings, target, action):
    settings.bindings.clear()
    defaults = caps.default_bindings(target, action)
    for field in target.fields:
        item = settings.bindings.add()
        item.name = field.name
        item.title = field.title
        item.action = action
        item.media = field.media or ""
        item.is_array = field.is_array
        item.required = field.required
        item.description = field.description[:500]
        item.source = defaults.get(field.name, "NONE")
    settings.params.clear()
    for param in target.params:
        item = settings.params.add()
        item.name = param.name
        item.title = param.title
        item.kind = param.type
        item.target_key = target.key
        item.required = param.required
        item.description = param.description[:500]
        item.enabled = param.required and param.default is None
        if param.type == "enum":
            catalog.register_enum(target.key, param)
            if param.default is not None and param.default in param.choices:
                item.value_enum = str(param.default)
        elif param.default is not None:
            try:
                setattr(item, "value_" + {"int": "int", "float": "float", "bool": "bool"}.get(param.type, "string"),
                        param.default if param.type != "string" else str(param.default))
            except (TypeError, ValueError, OverflowError):
                pass
    settings.bound_key = target.key


def _param_value(item):
    if item.kind == "enum":
        return catalog.enum_value(item.target_key, item.name, item.value_enum)
    return getattr(item, "value_" + {"int": "int", "float": "float", "bool": "bool"}.get(item.kind, "string"))


# -- validation -------------------------------------------------------------------------------


def _common_checks(context):
    problem = compat.online_problem()
    if problem:
        raise Problem(problem)
    values = preferences.settings(context)
    if not values["api_key"]:
        raise Problem("Add your Eachlabs API key in the add-on preferences.")
    try:
        api_client.validate_base_url(values["base_url"])
    except ValueError as exc:
        raise Problem(str(exc))
    return values


def build_request(settings, action, seconds=None, match_duration=False):
    """Resolve the target and turn the panel into ``(target, base_input, url_fields, files)``.

    ``files`` holds user-picked files bound to inputs; ``seconds`` is the rendered length, used to
    request a matching duration when ``match_duration`` is on and the user set none.
    """
    target = catalog.resolve(settings.target)
    if target is None:
        raise Problem("Choose a model or workflow first (refresh the list if it is empty).")
    if settings.bound_key != target.key:
        rebuild_inputs(settings, target, action)
    bindings, files = {}, {}
    for binding in settings.bindings:
        if binding.source == "NONE":
            continue
        if binding.source != caps.FILE:
            bindings[binding.name] = binding.source
            continue
        path = bpy.path.abspath(binding.filepath) if binding.filepath else ""
        if not os.path.isfile(path):
            raise Problem("Pick the file to send as %s." % binding.name)
        role = caps.file_role(binding.name)
        files[role] = {"path": path, "content_type": naming.content_type_for(path), "media": naming.upload_kind(path)}
        bindings[binding.name] = role
    if not any(role in caps.SOURCES for role in bindings.values()):
        raise Problem("Choose which input of %s receives the render." % target.title)
    extra = {}
    if settings.extra_json.strip():
        try:
            extra = json.loads(settings.extra_json)
        except ValueError as exc:
            raise Problem("Extra inputs is not valid JSON: %s" % exc)
        if not isinstance(extra, dict):
            raise Problem('Extra inputs must be a JSON object such as {"num_images": 2}.')
    params = {p.name: _param_value(p) for p in settings.params if p.enabled}
    if match_duration and seconds:
        matched = caps.match_duration(target, seconds)
        if matched and matched[0] not in params and matched[0] not in extra:
            params[matched[0]] = matched[1]
    placeholders = {role: "https://pending.invalid/" + role for role in caps.bound_roles(bindings)}
    values = caps.build_input(target, bindings, placeholders, settings.prompt,
                              settings.seed if settings.use_seed else None, params, extra)
    missing = caps.missing_required(target, values)
    if missing:
        raise Problem("%s needs: %s." % (target.title, ", ".join(missing)))
    by_name = {f.name: f for f in target.fields}
    url_fields = {name: (role, by_name[name].is_array) for name, role in bindings.items() if name not in extra}
    base_input = {k: v for k, v in values.items() if k not in url_fields}
    return target, base_input, url_fields, files


# -- actions ----------------------------------------------------------------------------------


def start_image(context):
    """Start Generate Image from View. Returns an error message or ``None``."""
    scene = context.scene
    try:
        api = _common_checks(context)
        target, base_input, url_fields, picked = build_request(scene.eachlabs.image, caps.IMAGE)
    except Problem as exc:
        return str(exc)
    folder = naming.output_dir(bpy.data.filepath)
    job_id = naming.new_id()
    still = naming.input_path(folder, job_id, "still", "png")
    files = {"still": {"path": still, "content_type": "image/png", "media": "image"}}
    job = REGISTRY.add(jobs.Job(job_id, caps.IMAGE, target.label, target.kind))
    job.context = {"scene": scene.name, "open_in_editor": scene.eachlabs.open_in_editor,
                   "camera_background": scene.eachlabs.camera_background}

    def rendered():
        if not job.active:
            return
        _remember(scene.eachlabs.image, job_id, files, {})
        _launch(job, target, base_input, url_fields, dict(files, **picked), folder, job_id, {}, api)

    error = render_export.render_still(context, scene, still, scene.eachlabs.still_source, rendered,
                                       lambda message: _render_failed(job, message))
    if error:
        job.apply({"state": jobs.FAILED, "error": error})
    main_thread.start()
    return error


def start_video(context):
    """Start Generate Video from Camera Move. Returns an error message or ``None``."""
    scene = context.scene
    settings = scene.eachlabs
    try:
        api = _common_checks(context)
        start, end = (scene.frame_start, scene.frame_end) if settings.use_scene_range else (
            settings.frame_start, settings.frame_end)
        if end < start:
            raise Problem("The frame range ends before it starts.")
        fps = timing.scene_fps(scene.render.fps, scene.render.fps_base)
        frames = timing.range_length(start, end)
        target, base_input, url_fields, picked = build_request(settings.video, caps.VIDEO, frames / fps,
                                                               settings.match_duration)
    except Problem as exc:
        return str(exc)
    folder = naming.output_dir(bpy.data.filepath)
    job_id = naming.new_id()
    files = {
        "clip": {"path": naming.input_path(folder, job_id, "clip", "mp4"), "content_type": "video/mp4", "media": "video"},
        "first_frame": {"path": naming.input_path(folder, job_id, "first_frame", "png"),
                        "content_type": "image/png", "media": "image"},
        "last_frame": {"path": naming.input_path(folder, job_id, "last_frame", "png"),
                       "content_type": "image/png", "media": "image"},
    }
    percentage = timing.preview_percentage(scene.render.resolution_y, int(settings.preview_height))
    job = REGISTRY.add(jobs.Job(job_id, caps.VIDEO, target.label, target.kind))
    job.context = {"scene": scene.name, "sequencer_scene": compat.sequencer_scene(context, scene).name,
                   "workspace": _workspace_name(context), "frame_start": start, "frames": frames,
                   "timing": settings.timing_mode, "import_audio": settings.import_audio}

    def rendered(frame_paths):
        if not job.active:
            return
        try:
            render_export.package_clip(frame_paths, scene.render.fps, scene.render.fps_base,
                                       files["clip"]["path"], files["first_frame"]["path"], files["last_frame"]["path"])
        except (RuntimeError, OSError) as exc:
            job.apply({"state": jobs.FAILED, "error": "Packaging the clip failed: %s" % exc})
            return
        # The clip and its first and last frames carry everything; a 2 min film's PNGs run to gigabytes.
        shutil.rmtree(naming.frames_dir(folder, job_id), ignore_errors=True)
        _remember(settings.video, job_id, files, {"frame_start": start, "frames": frames, "fps": fps})
        _launch(job, target, base_input, url_fields, dict(files, **picked), folder, job_id, {}, api)

    error = render_export.render_frames(context, scene, naming.frame_pattern(folder, job_id), start, end, percentage,
                                        settings.video_source, rendered, lambda message: _render_failed(job, message))
    if error:
        job.apply({"state": jobs.FAILED, "error": error})
    main_thread.start()
    return error


def rerun(context, action):
    """Submit the last rendered inputs again with the current target, prompt, seed and parameters."""
    scene = context.scene
    settings = action_settings(scene, action)
    try:
        api = _common_checks(context)
        data = last_inputs(settings)
        if data is None:
            raise Problem("Nothing to re-run yet; generate once first.")
        missing = [role for role, info in data["files"].items() if not os.path.isfile(info["path"])]
        if missing:
            raise Problem("The last render's %s file is gone; generate again." % missing[0])
        seconds = data["frames"] / data["fps"] if data.get("frames") and data.get("fps") else None
        target, base_input, url_fields, picked = build_request(
            settings, action, seconds, action == caps.VIDEO and scene.eachlabs.match_duration)
    except Problem as exc:
        return str(exc)
    now = time.time()
    # Picked files may have changed since the last run, so only rendered inputs are reused.
    uploaded = {role: url for role, (url, stamp) in data.get("uploaded", {}).items()
                if now - stamp < UPLOAD_REUSE_SECONDS and role in caps.SOURCES}
    job_id = naming.new_id()
    job = REGISTRY.add(jobs.Job(job_id, action, target.label, target.kind, state=jobs.UPLOADING))
    if action == caps.IMAGE:
        job.context = {"scene": scene.name, "open_in_editor": scene.eachlabs.open_in_editor,
                       "camera_background": scene.eachlabs.camera_background}
    else:
        job.context = {"scene": scene.name, "sequencer_scene": compat.sequencer_scene(context, scene).name,
                       "workspace": _workspace_name(context), "frame_start": data.get("frame_start", scene.frame_start),
                       "frames": data.get("frames"), "timing": scene.eachlabs.timing_mode,
                       "import_audio": scene.eachlabs.import_audio}
    folder = os.path.dirname(next(iter(data["files"].values()))["path"])
    _launch(job, target, base_input, url_fields, dict(data["files"], **picked), folder, data["input_set_id"],
            uploaded, api)
    main_thread.start()
    return None


def apply_default_video(context, force=False):
    """Select the default video model with its bindings and parameters. Returns a message or ``None``."""
    settings = context.scene.eachlabs.video
    defaults = preferences.video_defaults(context)
    if defaults is None:
        return "No default video model is set in the add-on preferences."
    target = catalog.MODELS.get(defaults["model"])
    if target is None:
        return "The default video model %s is not in the loaded catalog." % defaults["model"]
    if settings.target and not force:
        return None
    settings.target = target.label
    if settings.bound_key != target.key:
        rebuild_inputs(settings, target, caps.VIDEO)
    skipped = []
    by_name = {b.name: b for b in settings.bindings}
    for name, role in defaults["bindings"].items():
        if name in by_name and role in caps.sources_for(caps.VIDEO):
            by_name[name].source = role
        else:
            skipped.append(name)
    params = {p.name: p for p in settings.params}
    for name, value in defaults["params"].items():
        if name in params and _set_param(params[name], value):
            params[name].enabled = True
        else:
            skipped.append(name)
    if target.kind == caps.MODEL:
        catalog.fetch_cost(target.key, context)
    return ("Default applied; %s has no %s." % (target.title, ", ".join(skipped))) if skipped else None


def _set_param(item, value):
    try:
        if item.kind == "enum":
            identifiers = {identifier for identifier, _, _ in catalog.enum_items(item.target_key, item.name)}
            if str(value) not in identifiers:
                return False
            item.value_enum = str(value)
        elif item.kind in ("int", "float", "bool"):
            setattr(item, "value_" + item.kind, value)
        else:
            item.value_string = str(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return True


def export_movie(context):
    """Render the sequencer, with sound, to one MP4 next to the .blend. Returns an error or ``None``."""
    scene = compat.sequencer_scene(context, context.scene)
    editor = scene.sequence_editor
    strips = list(compat.all_strips(editor)) if editor else []
    if not strips:
        return "The sequencer is empty; generate a video first."
    start = min(compat.strip_start(s) for s in strips)
    end = max(compat.strip_end(s) for s in strips) - 1
    folder = naming.output_dir(bpy.data.filepath)
    job_id = naming.new_id()
    path = naming.input_path(folder, job_id, "movie", "mp4")
    job = REGISTRY.add(jobs.Job(job_id, EXPORT, "frames %d-%d" % (start, end), "local"))

    def done():
        seconds = timing.range_length(start, end) / timing.scene_fps(scene.render.fps, scene.render.fps_base)
        job.apply({"state": jobs.DONE, "outputs": [(path, "video")],
                   "message": "%s (%d:%02d)" % (os.path.basename(path), seconds // 60, seconds % 60)})

    error = render_export.export_sequencer(context, scene, path, start, end, done,
                                           lambda message: _render_failed(job, message))
    if error:
        job.apply({"state": jobs.FAILED, "error": error})
    main_thread.start()
    return error


def cancel(job_id):
    job = REGISTRY.get(job_id)
    if job is None:
        return
    if job.state == jobs.RENDERING:
        render_export.cancel_pending()
        REGISTRY.cancel(job_id, "Cancelled. Press Esc in the render window to stop the render early.")
    else:
        REGISTRY.cancel(job_id)


def last_inputs(settings):
    if not settings.last_inputs:
        return None
    try:
        data = json.loads(settings.last_inputs)
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("files") else None


def _workspace_name(context):
    workspace = getattr(context, "workspace", None)
    return workspace.name if workspace is not None else ""


def _remember(settings, input_set_id, files, extra):
    record = {"input_set_id": input_set_id, "files": files, "uploaded": {}, "created": time.time()}
    record.update(extra)
    settings.last_inputs = json.dumps(record)


def _render_failed(job, message):
    if job.active:
        state = jobs.CANCELLED if message == "Render cancelled" else jobs.FAILED
        job.apply({"state": state, "error": "" if state == jobs.CANCELLED else message,
                   "message": message if state == jobs.CANCELLED else ""})


def _launch(job, target, base_input, url_fields, files, folder, input_set_id, uploaded, api):
    roles = {role for role, _ in url_fields.values()}
    spec = jobs.JobSpec(
        job_id=job.job_id, action=job.action, target_kind=target.kind, target_key=target.key,
        target_label=target.label, output_dir=folder, base_input=base_input, url_fields=url_fields,
        files={role: files[role] for role in roles}, api_key=api["api_key"], base_url=api["base_url"],
        user_agent=preferences.user_agent(), version_id=target.version_id,
        uploaded={role: url for role, url in uploaded.items() if role in roles}, input_set_id=input_set_id,
        poll_interval=api["poll_interval"], timeout_seconds=api["timeout_seconds"])
    job.context["input_set_id"] = input_set_id
    job.apply({"state": jobs.UPLOADING, "message": ""})
    REGISTRY.start(job, spec)


# -- main-thread reconciliation ---------------------------------------------------------------


def tick_hook():
    ready = REGISTRY.drain()
    changed = bool(REGISTRY.updated)
    for job in ready:
        import_result(job)
    _persist_uploads()
    if REGISTRY.active():
        return "busy"
    return changed


def _persist_uploads():
    for job in REGISTRY.jobs.values():
        saved = job.context.get("uploads_saved", 0)
        if len(job.uploaded) <= saved:
            continue
        job.context["uploads_saved"] = len(job.uploaded)
        scene = bpy.data.scenes.get(job.context.get("scene", ""))
        if scene is None:
            continue
        settings = action_settings(scene, job.action)
        data = last_inputs(settings)
        if data is None or data.get("input_set_id") != job.context.get("input_set_id"):
            continue
        data.setdefault("uploaded", {}).update({role: list(value) for role, value in job.uploaded.items()})
        settings.last_inputs = json.dumps(data)


def import_result(job):
    """Load a finished job's files into Blender (main thread)."""
    try:
        scene = bpy.data.scenes.get(job.context.get("scene", ""))
        if scene is None:
            raise RuntimeError("the scene %r no longer exists" % job.context.get("scene"))
        images = [path for path, kind in job.outputs if kind == "image"]
        videos = [path for path, kind in job.outputs if kind == "video"]
        notes = []
        if images:
            loaded = [importers.load_image(path, job.job_id) for path in images]
            if job.context.get("open_in_editor", True):
                importers.show_in_image_editor(loaded[0])
            if job.context.get("camera_background"):
                note = importers.set_camera_background(scene, loaded[0])
                if note:
                    notes.append(note)
            notes.append("Image %s" % loaded[0].name)
        for path in videos:
            target_scene = bpy.data.scenes.get(job.context.get("sequencer_scene", "")) or scene
            frames = job.context.get("frames")
            mode = job.context.get("timing", timing.FIT_RANGE) if frames else timing.KEEP_TIMING
            info = importers.add_movie_strip(target_scene, path, job.context.get("frame_start", scene.frame_current),
                                             frames or 0, mode, "EL %s" % job.job_id,
                                             with_audio=job.context.get("import_audio", True))
            importers.show_in_sequencer(job.context.get("workspace"), target_scene)
            notes.append("Strip on channel %d, frames %d-%d" % (info["channel"], info["frame_start"], info["frame_end"] - 1))
            if info["audio"] == "synced":
                notes.append("audio on channel %d" % info["audio_channel"])
            elif info["audio"] == "muted":
                notes.append("audio muted on channel %d because the picture was retimed" % info["audio_channel"])
        if job.extras.get("draft_id"):
            notes.append("draft %s" % job.extras["draft_id"])
        if not images and not videos:
            raise RuntimeError("the result is not an image or video Blender can open (%s)"
                               % ", ".join(os.path.basename(p) for p, _ in job.outputs))
        job.apply({"state": jobs.DONE, "message": "; ".join(notes)})
    except Exception as exc:
        job.apply({"state": jobs.FAILED, "error": "Import failed: %s" % exc})


@bpy.app.handlers.persistent
def on_load_pre(*_args):
    render_export.cancel_pending()
    REGISTRY.cancel_all("Cancelled because another file was opened.")


@bpy.app.handlers.persistent
def on_load_post(*_args):
    catalog.populate(bpy.context)


def shutdown():
    render_export.cancel_pending()
    REGISTRY.cancel_all("Cancelled because the add-on was disabled.")
