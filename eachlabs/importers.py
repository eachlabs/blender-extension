"""Bring results into Blender: images, Image Editor, camera background and sequencer strips."""

import bpy

from . import compat, timing

TAG = "eachlabs_job"


def load_image(path, job_id):
    image = bpy.data.images.load(path, check_existing=True)
    image[TAG] = job_id
    return image


def _image_editors():
    wm = bpy.context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            if area.type == "IMAGE_EDITOR":
                yield window, area


def show_in_image_editor(image):
    """Show ``image`` in an Image Editor: an open one, else Blender's render view, else a new window."""
    if bpy.app.background:
        return False
    editors = list(_image_editors())
    if not editors:
        wm = bpy.context.window_manager
        window = wm.windows[0]
        area = max(window.screen.areas, key=lambda a: a.width * a.height)
        with bpy.context.temp_override(window=window, area=area):
            try:
                bpy.ops.render.view_show("INVOKE_DEFAULT")
            except RuntimeError:
                pass
        editors = list(_image_editors())
        if not editors:
            with bpy.context.temp_override(window=window, area=area):
                bpy.ops.wm.window_new()
            new_window = wm.windows[-1]
            target = max(new_window.screen.areas, key=lambda a: a.width * a.height)
            target.type = "IMAGE_EDITOR"
            editors = [(new_window, target)]
    # Prefer an editor already showing an Eachlabs result or the render, so layouts stay put.
    editors.sort(key=lambda pair: 0 if _shows_result(pair[1]) else 1)
    _window, area = editors[0]
    area.spaces.active.image = image
    area.tag_redraw()
    return True


def _shows_result(area):
    current = area.spaces.active.image
    return current is not None and (TAG in current or current.type == "RENDER_RESULT")


def set_camera_background(scene, image, alpha=0.5):
    """Put ``image`` in the active camera's background, reusing the slot an earlier result used."""
    camera = scene.camera
    if camera is None or camera.type != "CAMERA":
        return "The scene has no active camera for the background image."
    data = camera.data
    slot = next((bg for bg in data.background_images if bg.image is not None and TAG in bg.image), None)
    if slot is None:
        slot = data.background_images.new()
    slot.source = "IMAGE"
    slot.image = image
    slot.alpha = alpha
    slot.display_depth = "FRONT"
    slot.frame_method = "FIT"
    slot.show_background_image = True
    data.show_background_images = True
    return None


def show_in_sequencer(workspace_name, scene):
    """On 5.x the Video Sequencer shows the workspace's sequencer scene; with none set, a new strip
    would be invisible, so point the workspace at the scene that received it."""
    workspace = bpy.data.workspaces.get(workspace_name or "")
    if workspace is not None and hasattr(workspace, "sequencer_scene") and workspace.sequencer_scene is None:
        workspace.sequencer_scene = scene


def _add_sound(scene, sequence_editor, collection, path, frame_start, length, name, retimed):
    channel = timing.first_free_channel(_occupied(sequence_editor), frame_start, length)
    sound = collection.new_sound(name, path, channel, frame_start)
    if compat.strip_length(sound) <= 1:
        # Blender makes a one-frame strip for a file without an audio stream.
        collection.remove(sound)
        return "none", None
    if compat.strip_length(sound) > length:
        compat.set_strip_length(sound, length)
    if retimed:
        sound.mute = True
        return "muted", channel
    if scene.sync_mode == "NONE":
        scene.sync_mode = "AUDIO_SYNC"  # Play Every Frame drifts from sound; this keeps playback live.
    return "synced", channel


def _occupied(sequence_editor):
    for strip in compat.all_strips(sequence_editor):
        yield strip.channel, compat.strip_start(strip), compat.strip_end(strip)


def probe_movie(path):
    """``(frame_count, fps)`` of a movie file, read by Blender."""
    clip = bpy.data.movieclips.load(path, check_existing=False)
    try:
        return clip.frame_duration, clip.fps
    finally:
        bpy.data.movieclips.remove(clip)


def add_movie_strip(scene, path, frame_start, rendered_frames, mode, name, with_audio=False):
    """Add ``path`` at ``frame_start`` on the first free channel and reconcile its timing.

    With ``with_audio``, the clip's sound goes on the next free channel. Sound strips cannot be
    retimed safely from Python, so when the picture is stretched the sound is added muted.
    """
    source_frames, source_fps = probe_movie(path)
    if source_frames <= 0 or source_fps <= 0:
        raise RuntimeError("Blender could not read frames from %s" % path)
    timeline_fps = timing.scene_fps(scene.render.fps, scene.render.fps_base)
    length = timing.target_length(source_frames, source_fps, timeline_fps, rendered_frames, mode)
    sequence_editor = scene.sequence_editor or scene.sequence_editor_create()
    collection = compat.strips(sequence_editor)
    channel = timing.first_free_channel(_occupied(sequence_editor), frame_start, length)
    strip = collection.new_movie(name, path, channel, frame_start, fit_method="FIT")
    source_frames = compat.content_frames(strip)
    top = strip
    if source_frames != length:
        compat.set_strip_length(strip, length)
    if timing.needs_retime(source_frames, length):
        # The strip now spans the target; a Stretch speed effect plays all of its source frames across it.
        effect_channel = timing.first_free_channel(_occupied(sequence_editor), frame_start, length)
        top = compat.new_speed_effect(collection, name + " speed", effect_channel, frame_start, strip)
        top.speed_control = "STRETCH"
    audio, audio_channel = "none", None
    if with_audio:
        audio, audio_channel = _add_sound(scene, sequence_editor, collection, path, frame_start, length,
                                          name + " audio", retimed=top is not strip)
    for item in compat.all_strips(sequence_editor):
        item.select = False
    strip.select = top.select = True
    sequence_editor.active_strip = top
    return {
        "audio": audio,
        "audio_channel": audio_channel,
        "strip": strip.name,
        "channel": strip.channel,
        "speed_strip": top.name if top is not strip else None,
        "frame_start": compat.strip_start(top),
        "frame_end": compat.strip_end(top),
        "length": compat.strip_end(top) - compat.strip_start(top),
        "source_frames": source_frames,
        "source_fps": source_fps,
        "speed": timing.speed_factor(source_frames, length) if top is not strip else 1.0,
        "method": "speed_effect" if top is not strip else "trim" if source_frames != length else "none",
    }
