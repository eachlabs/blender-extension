"""The local cache of generated 3D models: one GLB per description and tier. No ``bpy``; workers use it.

An object asked for again with the same description (lowercase, spaces collapsed) and tier is brought in from the
cache, with no new run and no cost. The cache lives in the add-on's user folder, holds nothing secret, and is kept
under ``LIMIT_BYTES`` by removing the least recently used models, never one a job is about to bring in
(``hold``). Preferences offer *Clear generated files*.
"""

import json
import os
import re
import threading
import time
import uuid

LIMIT_BYTES = 2 * 1024 ** 3
INDEX = "index.json"
_lock = threading.Lock()  # several workers add models at once
_in_use = set()  # cache files a job holds until it brought them into the scene; eviction skips them


def hold(path):
    """Keep the cache file at ``path`` until ``release``: a job is about to import it."""
    with _lock:
        _in_use.add(os.path.normpath(path))


def release(path):
    with _lock:
        _in_use.discard(os.path.normpath(path))


def held():
    with _lock:
        return set(_in_use)


def key(description):
    """The cache key of a description: lowercase, trimmed, spaces collapsed."""
    return " ".join(str(description or "").lower().split())


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text)[:40].strip("-") or "model"


class Cache:
    def __init__(self, folder, limit_bytes=LIMIT_BYTES):
        self.folder = folder
        self.limit = limit_bytes

    def _index_path(self):
        return os.path.join(self.folder, INDEX)

    def _read(self):
        try:
            with open(self._index_path(), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return []
        entries = data.get("entries") if isinstance(data, dict) else None
        return [e for e in entries or [] if isinstance(e, dict) and e.get("key") and e.get("file")]

    def _write(self, entries):
        os.makedirs(self.folder, exist_ok=True)
        partial = self._index_path() + ".part"
        with open(partial, "w", encoding="utf-8") as fh:
            json.dump({"entries": entries}, fh, indent=1)
        os.replace(partial, self._index_path())

    def _file(self, entry):
        return os.path.join(self.folder, os.path.basename(entry["file"]))

    def get(self, description, tier, hold=False):
        """The entry for ``description`` and ``tier`` with its ``path``, or ``None``; marks it used. ``hold``: keep
        the file until ``release``."""
        wanted = key(description)
        with _lock:
            entries = self._read()
            for entry in entries:
                if entry["key"] == wanted and entry.get("tier") == tier and os.path.isfile(self._file(entry)):
                    entry["used"] = time.time()
                    self._write(entries)
                    if hold:
                        _in_use.add(os.path.normpath(self._file(entry)))
                    return dict(entry, path=self._file(entry))
        return None

    def has(self, description, tier):
        wanted = key(description)
        return any(e["key"] == wanted and e.get("tier") == tier and os.path.isfile(self._file(e))
                   for e in self._read())

    def put(self, description, tier, source, version="", cost=None, hold=False):
        """Move the file at ``source`` (a GLB, or a texture picture) into the cache and return its path there; the
        oldest entries go when the cache is over its limit, except files a job holds. ``hold``: keep the new file
        until ``release``."""
        wanted = key(description)
        name = "%s-%s-%s%s" % (_slug(wanted), tier, uuid.uuid4().hex[:6], os.path.splitext(source)[1] or ".glb")
        os.makedirs(self.folder, exist_ok=True)
        target = os.path.join(self.folder, name)
        os.replace(source, target)
        now = time.time()
        with _lock:
            if hold:
                _in_use.add(os.path.normpath(target))
            entries = []
            for entry in self._read():
                if entry["key"] == wanted and entry.get("tier") == tier:
                    if not self._held(entry):
                        self._remove_files(entry)  # replaced by the new model; a held file stays until cleared
                else:
                    entries.append(entry)
            entries.append({"key": wanted, "tier": tier, "file": name, "prompt": " ".join(str(description).split()),
                            "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "used": now,
                            "workflow_version": version, "cost": cost, "bytes": os.path.getsize(target)})
            entries = self._evict(entries, keep=name)
            self._write(entries)
        return target

    def _sidecars(self, entry):
        """The model's file and the texture files written beside it (``<name>_tex<n>.<ext>``)."""
        stem = os.path.splitext(os.path.basename(entry["file"]))[0]
        try:
            names = os.listdir(self.folder)
        except OSError:
            return []
        return [os.path.join(self.folder, n) for n in names if n == entry["file"] or n.startswith(stem + "_tex")]

    def _remove_files(self, entry):
        for path in self._sidecars(entry):
            try:
                os.remove(path)
            except OSError:
                pass

    def _bytes(self, entry):
        total = 0
        for path in self._sidecars(entry):
            try:
                total += os.path.getsize(path)
            except OSError:
                pass
        return total

    def _held(self, entry):
        return os.path.normpath(self._file(entry)) in _in_use

    def _evict(self, entries, keep=None):
        sizes = {e["file"]: self._bytes(e) for e in entries}
        total = sum(sizes.values())
        for entry in sorted(entries, key=lambda e: e.get("used") or 0):
            if total <= self.limit:
                break
            if entry["file"] == keep or self._held(entry):
                continue
            self._remove_files(entry)
            total -= sizes[entry["file"]]
            entries = [e for e in entries if e is not entry]
        return entries

    def size(self):
        """Bytes the cache uses on disk."""
        total = 0
        try:
            names = os.listdir(self.folder)
        except OSError:
            return 0
        for name in names:
            try:
                total += os.path.getsize(os.path.join(self.folder, name))
            except OSError:
                pass
        return total

    def clear(self):
        """Remove every cached model; returns the bytes freed."""
        with _lock:
            freed = self.size()
            try:
                names = os.listdir(self.folder)
            except OSError:
                return 0
            for name in names:
                try:
                    os.remove(os.path.join(self.folder, name))
                except OSError:
                    pass
            return freed
