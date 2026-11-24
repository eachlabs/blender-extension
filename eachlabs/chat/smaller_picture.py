"""A picture made smaller before it goes to each::sense: the concept and reference pictures as ``data:`` URLs.

Main thread only (``bpy.data.images``). A tool answer is at most 2 MiB and each model call carries its pictures
again, so a picture is sent at most ``SIDE`` pixels on its longer side, as a JPEG. Anything that cannot be read or
written comes back unchanged: the caller decides what still fits.
"""

import base64
import os
import tempfile

import bpy

SIDE = 1024
QUALITY = 85
_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def smaller(url, side=SIDE):
    """``url`` (a ``data:image/...;base64,`` URL) at most ``side`` pixels on its longer side, as a JPEG."""
    head, _, data = str(url or "").partition(",")
    kind = head[len("data:"):].split(";")[0] if head.startswith("data:") else ""
    if kind not in _TYPES or ";base64" not in head:
        return url
    with tempfile.TemporaryDirectory(prefix="eachlabs-picture-") as folder:
        source = os.path.join(folder, "in" + _TYPES[kind])
        target = os.path.join(folder, "out.jpg")
        try:
            with open(source, "wb") as handle:
                handle.write(base64.b64decode(data))
            image = bpy.data.images.load(source, check_existing=False)
        except (OSError, RuntimeError, ValueError):
            return url
        try:
            width, height = image.size
            if not width or not height or max(width, height) <= side and kind == "image/jpeg":
                return url
            scale = min(1.0, float(side) / max(width, height))
            image.scale(max(1, round(width * scale)), max(1, round(height * scale)))
            image.file_format = "JPEG"
            try:
                image.save(filepath=target, quality=QUALITY)
            except TypeError:  # a Blender whose Image.save takes no arguments
                image.filepath_raw = target
                image.save()
            with open(target, "rb") as handle:
                out = handle.read()
        except (OSError, RuntimeError, ValueError):
            return url
        finally:
            bpy.data.images.remove(image)
    return "data:image/jpeg;base64," + base64.b64encode(out).decode("ascii")
