"""Frame-rate and frame-range math for placing generated clips on the timeline."""

FIT_RANGE = "FIT_RANGE"
KEEP_TIMING = "KEEP_TIMING"


def scene_fps(fps, fps_base=1.0):
    """Blender's effective frame rate: ``render.fps / render.fps_base``."""
    if fps <= 0 or fps_base <= 0:
        raise ValueError("fps and fps_base must be positive")
    return fps / fps_base


def range_length(frame_start, frame_end):
    """Number of frames in an inclusive range."""
    if frame_end < frame_start:
        raise ValueError("frame_end must not be before frame_start")
    return frame_end - frame_start + 1


def target_length(source_frames, source_fps, timeline_fps, rendered_frames, mode=FIT_RANGE):
    """Timeline frames the imported strip should span.

    ``FIT_RANGE`` matches the rendered range. ``KEEP_TIMING`` keeps the clip's real duration at the
    timeline's frame rate.
    """
    if source_frames <= 0:
        raise ValueError("source clip has no frames")
    if mode == FIT_RANGE:
        if rendered_frames <= 0:
            raise ValueError("rendered range has no frames")
        return rendered_frames
    if mode == KEEP_TIMING:
        if source_fps <= 0 or timeline_fps <= 0:
            raise ValueError("frame rates must be positive")
        return max(1, int(round(source_frames * timeline_fps / source_fps)))
    raise ValueError("unknown timing mode: %r" % (mode,))


def speed_factor(source_frames, timeline_frames):
    """Source frames advanced per timeline frame for a strip spanning ``timeline_frames``."""
    if source_frames <= 0 or timeline_frames <= 0:
        raise ValueError("frame counts must be positive")
    return source_frames / timeline_frames


# Generators often return a frame or two past the requested length; trimming that tail keeps the clip's
# sound playable, where stretching it would mute the sound.
TAIL_TOLERANCE = 2


def needs_retime(source_frames, timeline_frames, tolerance=TAIL_TOLERANCE):
    """Whether the clip must be stretched to span ``timeline_frames``. A surplus tail of up to
    ``tolerance`` frames is trimmed instead."""
    return not 0 <= source_frames - timeline_frames <= tolerance


def frame_end_exclusive(frame_start, length):
    return frame_start + length


def first_free_channel(occupied, frame_start, length, max_channel=128):
    """Lowest channel with no strip overlapping ``[frame_start, frame_start + length)``.

    ``occupied`` is an iterable of ``(channel, start, end_exclusive)`` tuples.
    """
    end = frame_start + length
    busy = set()
    for channel, start, stop in occupied:
        if start < end and frame_start < stop:
            busy.add(channel)
    for channel in range(1, max_channel + 1):
        if channel not in busy:
            return channel
    raise ValueError("no free sequencer channel between 1 and %d" % max_channel)


def preview_percentage(resolution_y, target_height):
    """Resolution percentage that brings the scene height closest to ``target_height``.

    ``target_height`` of 0 means full scene resolution. Never upscales above 100%.
    """
    if resolution_y <= 0:
        raise ValueError("resolution_y must be positive")
    if not target_height or target_height >= resolution_y:
        return 100
    return max(1, min(100, int(round(target_height * 100.0 / resolution_y))))


def even_dimensions(width, height):
    """H.264 needs even frame sizes; round each dimension down to an even number (minimum 2)."""
    return max(2, width - width % 2), max(2, height - height % 2)
