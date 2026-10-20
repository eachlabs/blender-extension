"""Shims for API differences between Blender 4.2 and 5.x (see docs/architecture.md)."""

import bpy

# Strip speed is set with a Speed Control effect on every version. RetimingKeys from Python crash
# Blender 4.2 on add(), and on 5.2 they resolve to the wrong strip whenever the sequencer holds
# more than one strip, then crash on write (verified with probe scripts, see docs/architecture.md).


def strip_start(strip):
    """First timeline frame. 5.x calls it ``left_handle``; ``frame_final_start`` goes away in 6.0."""
    return strip.left_handle if hasattr(strip, "left_handle") else strip.frame_final_start


def strip_end(strip):
    """First timeline frame after the strip (exclusive end)."""
    return strip.right_handle if hasattr(strip, "right_handle") else strip.frame_final_end


def strip_length(strip):
    return strip.duration if hasattr(strip, "left_handle") else strip.frame_final_duration


def set_strip_length(strip, length):
    """Trim or extend the strip's right handle so it spans ``length`` timeline frames."""
    if hasattr(strip, "left_handle"):
        strip.duration = length
    else:
        strip.frame_final_duration = length


def content_frames(strip):
    """Frames in the strip's source, ignoring handles."""
    return strip.content_duration if hasattr(strip, "content_duration") else strip.frame_duration


def strips(sequence_editor):
    """Top-level strip collection: ``strips`` in 4.4+ / 5.x, ``sequences`` in 4.2."""
    if hasattr(sequence_editor, "strips"):
        return sequence_editor.strips
    return sequence_editor.sequences


def all_strips(sequence_editor):
    if hasattr(sequence_editor, "strips_all"):
        return sequence_editor.strips_all
    return sequence_editor.sequences_all


def new_speed_effect(collection, name, channel, frame_start, source):
    try:
        return collection.new_effect(name, "SPEED", channel, frame_start, seq1=source)
    except TypeError:
        return collection.new_effect(name, "SPEED", channel, frame_start,
                                     length=strip_length(source), input1=source)


def set_image_output(image_settings, file_format="PNG"):
    if hasattr(image_settings, "media_type"):
        image_settings.media_type = "IMAGE"
    image_settings.file_format = file_format


def set_video_output(image_settings):
    if hasattr(image_settings, "media_type"):
        image_settings.media_type = "VIDEO"
    image_settings.file_format = "FFMPEG"


def sequencer_scene(context, fallback):
    """The scene the Video Sequencer shows: 5.x workspaces may point at a separate one."""
    workspace = getattr(context, "workspace", None)
    scene = getattr(workspace, "sequencer_scene", None) if workspace else None
    return scene or fallback


def online_problem():
    """``None`` when network access is allowed, else a message telling the user how to enable it."""
    if bpy.app.online_access:
        return None
    if getattr(bpy.app, "online_access_override", False):
        return "Blender was started with --offline-mode. Restart without it to use Eachlabs."
    return "Online access is off. Enable it in Preferences > System > Network > Allow Online Access."
