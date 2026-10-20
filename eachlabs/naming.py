"""Output folder and file names. Every file carries the ID of the job or input set that made it."""

import datetime
import os
import re
import secrets
import tempfile

FOLDER = "eachlabs"
UNSAVED_FOLDER = os.path.join("eachlabs-blender", "unsaved")

_ID_PATTERN = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def new_id(now=None):
    """Return a sortable, collision-resistant ID such as ``20261019-153012-a1b2``."""
    now = now or datetime.datetime.now()
    return "%s-%s" % (now.strftime("%Y%m%d-%H%M%S"), secrets.token_hex(2))


def is_id(value):
    return bool(_ID_PATTERN.match(value or ""))


def safe_component(text, fallback="untitled"):
    cleaned = _UNSAFE.sub("_", text or "").strip("._")
    return cleaned or fallback


def output_dir(blend_filepath, temp_root=None):
    """Folder for inputs and results: ``<blend dir>/eachlabs/<blend name>/``.

    Unsaved files use the system temp directory rather than Blender's session temp directory,
    which Blender deletes on exit while images and strips still reference it.
    """
    if blend_filepath:
        directory, filename = os.path.split(os.path.abspath(blend_filepath))
        stem = safe_component(os.path.splitext(filename)[0])
        return os.path.join(directory, FOLDER, stem)
    return os.path.join(temp_root or tempfile.gettempdir(), UNSAVED_FOLDER)


def input_path(folder, input_set_id, role, ext):
    return os.path.join(folder, "%s_%s.%s" % (input_set_id, role, ext.lstrip(".")))


def frames_dir(folder, input_set_id):
    return os.path.join(folder, "%s_frames" % input_set_id)


def frame_pattern(folder, input_set_id):
    """Render output prefix; Blender appends the zero-padded frame number and extension."""
    return os.path.join(frames_dir(folder, input_set_id), "frame_")


def result_path(folder, job_id, index, ext):
    return os.path.join(folder, "%s_result_%d.%s" % (job_id, index, ext.lstrip(".")))


def manifest_path(folder, job_id):
    return os.path.join(folder, "%s.json" % job_id)


_CONTENT_TYPE_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/tiff": "tif",
    "image/bmp": "bmp",
    "image/x-exr": "exr",
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
    "video/x-matroska": "mkv",
}

IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif", "tif", "tiff", "bmp", "exr"}
VIDEO_EXTS = {"mp4", "mov", "webm", "mkv", "m4v", "avi"}


def extension_for(url, content_type=None):
    """Pick a file extension from the URL path, falling back to the response content type."""
    path = (url or "").split("?", 1)[0].split("#", 1)[0]
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    if ext in IMAGE_EXTS or ext in VIDEO_EXTS:
        return ext
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    return _CONTENT_TYPE_EXT.get(mime, "bin")


def media_kind(path_or_ext, content_type=None):
    """Return ``"image"``, ``"video"`` or ``None`` from a content type or file extension."""
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    ext = os.path.splitext(path_or_ext)[1] or path_or_ext
    ext = ext.lstrip(".").lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    return None


CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "tif": "image/tiff",
    "tiff": "image/tiff",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
}
AUDIO_EXTS = {"wav", "mp3"}


def upload_kind(path):
    """Storage ``file_type`` for an upload: ``image``, ``video``, ``audio`` or ``other``."""
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    if ext in AUDIO_EXTS:
        return "audio"
    return media_kind(path) or "other"


def content_type_for(path):
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    return CONTENT_TYPES.get(ext, "application/octet-stream")
