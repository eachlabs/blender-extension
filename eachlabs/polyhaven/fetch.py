"""Downloading Poly Haven assets into the cache folder. Worker thread; no Blender.

Every file is fetched over https with the add-on's download helper (no API key is sent), checked against the md5
Poly Haven lists and against its file signature, and kept under ``<cache>/polyhaven/<asset id>/``.
"""

import hashlib
import json
import os
import time

from .. import glb
from . import catalog

LIST_MAX_AGE_S = 7 * 24 * 3600  # the asset lists change rarely
LIST_MAX_BYTES = 16 * 1024 * 1024
FILE_MAX_BYTES = 40 * 1024 * 1024
WAIT_S = 90
SKY_SIGNATURES = (b"#?RADIANCE", b"#?RGBE")


class HavenError(RuntimeError):
    """Poly Haven could not give an asset; the message is written for the model to act on."""


class Haven:
    def __init__(self, client, folder, cancel=None):
        self._client = client  # api_client.EachlabsClient: only its download helper is used
        self._root = os.path.join(folder, "polyhaven")
        self._cancel = cancel
        self._lists = {}

    def _download(self, url, dest, max_bytes):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            self._client.download(url, dest, self._cancel, max_bytes=max_bytes, wait_seconds=WAIT_S)
        except Exception as exc:  # offline, refused or too large: the model builds the look itself
            raise HavenError("Poly Haven could not be reached (%s); build this look with procedural nodes"
                             % (str(exc) or type(exc).__name__)) from exc

    def _json(self, url, dest, max_age):
        fresh = os.path.exists(dest) and time.time() - os.path.getmtime(dest) < max_age
        if not fresh:
            self._download(url, dest, LIST_MAX_BYTES)
        try:
            with open(dest, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as exc:
            raise HavenError("Poly Haven sent something unreadable; build this look with procedural nodes") from exc
        if not isinstance(data, dict):
            raise HavenError("Poly Haven sent something unreadable; build this look with procedural nodes")
        return data

    def assets(self, kind):
        if kind not in self._lists:
            self._lists[kind] = self._json(catalog.list_url(kind), os.path.join(self._root, "list-%s.json" % kind),
                                           LIST_MAX_AGE_S)
        return self._lists[kind]

    def _pick(self, kind, description):
        found = catalog.best(self.assets(kind), description, names_describe=kind == "texture")
        if found is None:
            raise HavenError("Poly Haven has no %s that matches %r; describe it in other words or build it with "
                             "procedural nodes" % ("sky" if kind == "sky" else "texture", description))
        asset_id, asset = found
        files = self._json(catalog.files_url(asset_id), os.path.join(self._root, asset_id, "files.json"),
                           LIST_MAX_AGE_S)
        return asset_id, asset, files

    def _file(self, asset_id, entry, signature_ok):
        name = os.path.basename(entry["url"].split("?")[0])
        if not name or name.startswith("."):
            raise HavenError("Poly Haven listed a file without a name")
        dest = os.path.join(self._root, asset_id, name)
        if not (os.path.exists(dest) and _md5(dest) == entry["md5"]):
            if entry.get("size", 0) > FILE_MAX_BYTES:
                raise HavenError("that Poly Haven file is too large; build this look with procedural nodes")
            self._download(entry["url"], dest, FILE_MAX_BYTES)
            if entry["md5"] and _md5(dest) != entry["md5"]:
                os.remove(dest)
                raise HavenError("a Poly Haven download arrived damaged; try again or use procedural nodes")
        with open(dest, "rb") as handle:
            head = handle.read(16)
        if not signature_ok(head):
            os.remove(dest)
            raise HavenError("a Poly Haven download was not the picture it should be")
        return dest

    def sky(self, description):
        """``{"id", "name", "path"}`` of the sky matching ``description``."""
        asset_id, asset, files = self._pick("sky", description)
        entry = catalog.sky_file(files)
        if entry is None:
            raise HavenError("that Poly Haven sky has no file to use; pick another description")
        path = self._file(asset_id, entry, lambda head: head.startswith(SKY_SIGNATURES))
        return {"id": asset_id, "name": asset.get("name") or asset_id, "path": path}

    def texture(self, description):
        """``{"id", "name", "maps": {role: path}, "tile_m"}`` of the texture matching ``description``."""
        asset_id, asset, files = self._pick("texture", description)
        entries = catalog.texture_files(files)
        if not entries:
            raise HavenError("that Poly Haven texture has no picture to use; pick another description")
        maps = {role: self._file(asset_id, entry, lambda head: glb.image_type(head) is not None)
                for role, entry in entries.items()}
        return {"id": asset_id, "name": asset.get("name") or asset_id, "maps": maps, "tile_m": catalog.tile_m(asset)}


def _md5(path):
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
