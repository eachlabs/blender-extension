"""Render the inputs a job sends: a still, a viewport snapshot, or a frame range packaged as MP4.

The user's render settings are snapshotted before any change and restored afterwards. In the UI,
renders run as Blender's own render job (``INVOKE_DEFAULT``) and finish through a main-thread task;
in background mode they run synchronously.
"""

import os
import shutil

import bpy

from . import compat, main_thread, timing

_SETTINGS = (
    ("render", "filepath"),
    ("render", "use_file_extension"),
    ("render", "resolution_percentage"),
    ("render", "use_sequencer"),
    ("render.image_settings", "media_type"),
    ("render.image_settings", "file_format"),
    ("render.image_settings", "color_mode"),
    ("render.image_settings", "color_depth"),
    ("render.image_settings", "compression"),
    ("render.ffmpeg", "format"),
    ("render.ffmpeg", "codec"),
    ("render.ffmpeg", "constant_rate_factor"),
    ("render.ffmpeg", "ffmpeg_preset"),
    ("render.ffmpeg", "audio_codec"),
    ("render.ffmpeg", "audio_channels"),
    ("render.ffmpeg", "audio_bitrate"),
    ("", "frame_start"),
    ("", "frame_end"),
)

STILL = "RENDER"
VIEWPORT = "VIEWPORT"
MISSING_FILE_GRACE_TICKS = 15


def _owner(scene, path):
    owner = scene
    for part in filter(None, path.split(".")):
        owner = getattr(owner, part)
    return owner


def snapshot(scene):
    saved = []
    for path, attr in _SETTINGS:
        owner = _owner(scene, path)
        if hasattr(owner, attr):
            saved.append((path, attr, getattr(owner, attr)))
    return saved


def restore(scene, saved):
    for path, attr, value in saved:
        try:
            setattr(_owner(scene, path), attr, value)
        except (AttributeError, TypeError, ValueError, ReferenceError):
            pass


def _png(scene):
    settings = scene.render.image_settings
    compat.set_image_output(settings, "PNG")
    settings.color_mode = "RGB"
    settings.color_depth = "8"
    settings.compression = 15
    # Results added to this scene's sequencer must never replace the 3D render of the next input.
    scene.render.use_sequencer = False


class _Pending:
    def __init__(self, scene, saved, expected, on_done, on_fail):
        self.scene_name = scene.name
        self.saved = saved
        self.expected = expected
        self.on_done = on_done
        self.on_fail = on_fail
        self.state = "running"
        self.grace = MISSING_FILE_GRACE_TICKS


_pending = None


def busy():
    return _pending is not None or bpy.app.is_job_running("RENDER")


def _handler_complete(*_args):
    if _pending is not None:
        _pending.state = "done"


def _handler_cancel(*_args):
    if _pending is not None:
        _pending.state = "cancelled"


def _set_handlers(enabled):
    for handlers, func in ((bpy.app.handlers.render_complete, _handler_complete),
                           (bpy.app.handlers.render_cancel, _handler_cancel)):
        if enabled and func not in handlers:
            handlers.append(func)
        elif not enabled and func in handlers:
            handlers.remove(func)


def _watch():
    """Main-thread task: finish the pending render once Blender reports it done or cancelled."""
    global _pending
    pending = _pending
    if pending is None:
        return False
    if pending.state == "running":
        return True
    missing = [p for p in pending.expected if not os.path.isfile(p)]
    if pending.state == "done" and missing and pending.grace > 0:
        pending.grace -= 1
        return True
    _pending = None
    _set_handlers(False)
    scene = bpy.data.scenes.get(pending.scene_name)
    if scene is not None:
        restore(scene, pending.saved)
    if pending.state == "cancelled":
        pending.on_fail("Render cancelled")
    elif missing:
        pending.on_fail("Render finished but %s was not written" % os.path.basename(missing[0]))
    else:
        pending.on_done()
    return False


def _view3d(context):
    areas = []
    if getattr(context, "area", None) is not None and context.area.type == "VIEW_3D":
        areas.append(context.area)
    window = getattr(context, "window", None)
    if window is not None:
        areas += [a for a in window.screen.areas if a.type == "VIEW_3D"]
    for area in areas:
        region = next((r for r in area.regions if r.type == "WINDOW"), None)
        if region is not None:
            return window, area, region
    return None, None, None


def _viewport_render(context, animation):
    window, area, region = _view3d(context)
    if area is not None:
        with context.temp_override(window=window, area=area, region=region):
            bpy.ops.render.opengl(animation=animation, write_still=not animation, view_context=True)
    else:
        bpy.ops.render.opengl(animation=animation, write_still=not animation, view_context=False)


def _run(context, scene, configure, animation, mode, on_done, on_fail):
    """Configure, render and hand control back. Returns an error string if it could not start."""
    global _pending
    if busy():
        return "Another render is running; wait for it to finish."
    saved = snapshot(scene)
    try:
        expected = configure(scene)
    except Exception:
        restore(scene, saved)
        raise
    if mode == VIEWPORT or bpy.app.background:
        try:
            if mode == VIEWPORT:
                _viewport_render(context, animation)
            else:
                bpy.ops.render.render(animation=animation, write_still=not animation, scene=scene.name)
        except RuntimeError as exc:
            restore(scene, saved)
            return "Render failed: %s" % exc
        restore(scene, saved)
        missing = [p for p in expected if not os.path.isfile(p)]
        if missing:
            return "Render finished but %s was not written" % os.path.basename(missing[0])
        on_done()
        return None
    _pending = _Pending(scene, saved, expected, on_done, on_fail)
    _set_handlers(True)
    try:
        result = bpy.ops.render.render("INVOKE_DEFAULT", animation=animation, write_still=not animation,
                                       scene=scene.name)
    except RuntimeError as exc:
        result = {"CANCELLED"}
        print("Eachlabs: render failed to start:", exc)
    if "CANCELLED" in result:
        _pending = None
        _set_handlers(False)
        restore(scene, saved)
        return "Blender could not start the render."
    main_thread.add_task(_watch)
    return None


def render_still(context, scene, path, mode, on_done, on_fail):
    """Render the current frame (or snapshot the viewport) to ``path`` as PNG."""
    os.makedirs(os.path.dirname(path), exist_ok=True)

    def configure(target):
        _png(target)
        target.render.filepath = path
        target.render.use_file_extension = False
        return [path]

    return _run(context, scene, configure, False, mode, on_done, on_fail)


def render_frames(context, scene, prefix, frame_start, frame_end, percentage, mode, on_done, on_fail):
    """Render ``frame_start..frame_end`` as a PNG sequence; ``on_done(paths)`` receives the files."""
    os.makedirs(os.path.dirname(prefix), exist_ok=True)
    paths = []

    def configure(target):
        _png(target)
        target.render.filepath = prefix
        target.render.use_file_extension = True
        target.render.resolution_percentage = percentage
        target.frame_start = frame_start
        target.frame_end = frame_end
        paths[:] = [target.render.frame_path(frame=f) for f in range(frame_start, frame_end + 1)]
        return list(paths)

    return _run(context, scene, configure, True, mode, lambda: on_done(list(paths)), on_fail)


def _h264(ffmpeg, audio):
    ffmpeg.format, ffmpeg.codec = "MPEG4", "H264"
    ffmpeg.constant_rate_factor, ffmpeg.ffmpeg_preset = "HIGH", "GOOD"
    if audio:
        ffmpeg.audio_codec, ffmpeg.audio_channels, ffmpeg.audio_bitrate = "AAC", "STEREO", 192
    else:
        ffmpeg.audio_codec = "NONE"


def export_sequencer(context, scene, path, frame_start, frame_end, on_done, on_fail):
    """Render the sequencer over ``frame_start..frame_end`` to an H.264 MP4 with AAC sound."""
    os.makedirs(os.path.dirname(path), exist_ok=True)

    def configure(target):
        compat.set_video_output(target.render.image_settings)
        _h264(target.render.ffmpeg, audio=True)
        target.render.use_sequencer = True
        target.render.filepath = path
        target.render.use_file_extension = False
        target.render.resolution_percentage = 100
        target.frame_start, target.frame_end = frame_start, frame_end
        return [path]

    return _run(context, scene, configure, True, STILL, on_done, on_fail)


def _window_override():
    wm = getattr(bpy.context, "window_manager", None)
    if bpy.app.background or wm is None or not wm.windows:
        return None
    return bpy.context.temp_override(window=wm.windows[0])


def encode_mp4(frame_paths, fps, fps_base, out_path):
    """Encode a PNG sequence to H.264 MP4 through a temporary, sequencer-only scene."""
    image = bpy.data.images.load(frame_paths[0], check_existing=False)
    try:
        width, height = timing.even_dimensions(*image.size)
    finally:
        bpy.data.images.remove(image)
    scene = bpy.data.scenes.new("eachlabs_encode")
    try:
        scene.render.fps, scene.render.fps_base = fps, fps_base
        scene.render.resolution_x, scene.render.resolution_y = width, height
        scene.render.resolution_percentage = 100
        # Frames are already display-referred; a neutral transform keeps their look in the clip.
        try:
            scene.view_settings.view_transform = "Standard"
        except TypeError:
            pass
        scene.view_settings.exposure, scene.view_settings.gamma = 0.0, 1.0
        collection = compat.strips(scene.sequence_editor_create())
        strip = collection.new_image("frames", frame_paths[0], 1, 1, fit_method="FIT")
        for path in frame_paths[1:]:
            strip.elements.append(os.path.basename(path))
        scene.frame_start, scene.frame_end = 1, len(frame_paths)
        scene.render.use_sequencer = True
        compat.set_video_output(scene.render.image_settings)
        _h264(scene.render.ffmpeg, audio=False)
        scene.render.filepath = out_path
        scene.render.use_file_extension = False
        override = _window_override()
        if override is None:
            bpy.ops.render.render(animation=True, scene=scene.name)
        else:
            with override:
                bpy.ops.render.render(animation=True, scene=scene.name)
    finally:
        bpy.data.scenes.remove(scene)
    if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError("Blender did not write %s" % os.path.basename(out_path))
    return out_path


def package_clip(frame_paths, fps, fps_base, clip_path, first_path, last_path):
    """MP4 plus first and last frames from one rendered sequence."""
    encode_mp4(frame_paths, fps, fps_base, clip_path)
    shutil.copyfile(frame_paths[0], first_path)
    shutil.copyfile(frame_paths[-1], last_path)
    return {"clip": clip_path, "first_frame": first_path, "last_frame": last_path}


def cancel_pending():
    """Forget a pending render's follow-up (the render itself can only be stopped with Esc)."""
    global _pending
    if _pending is not None:
        _pending.on_done = lambda: None
        _pending.on_fail = lambda message: None
