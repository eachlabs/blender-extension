"""The helper library's file: one JSON file in the add-on's own folder on this computer, capped in size.

Nothing here is sent anywhere; the helpers reach only the model's own messages and the step's namespace.
"""

import json
import os

FILE = "helpers.json"
ENTRIES_MAX = 150
BYTES_MAX = 400_000


def load(folder):
    """The stored entries, newest last; ``[]`` when there is no file or it cannot be read."""
    try:
        with open(os.path.join(folder, FILE), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    entries = data.get("helpers") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    keep = ("name", "args", "source", "description", "hash")
    return [e for e in entries if isinstance(e, dict) and all(isinstance(e.get(k), str) for k in keep)]


def merged(entries, new):
    """``entries`` with ``new`` added: one entry per name, the newest version, oldest dropped past the caps."""
    by_name = {e["name"]: e for e in entries}
    for entry in new:
        by_name.pop(entry["name"], None)
        by_name[entry["name"]] = entry
    out = list(by_name.values())[-ENTRIES_MAX:]
    while out and len(json.dumps({"helpers": out})) > BYTES_MAX:
        out.pop(0)
    return out


def save(folder, entries):
    """Write ``entries`` through a temporary file, so a crash never leaves half a file."""
    path = os.path.join(folder, FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"helpers": entries}, fh)
    os.replace(tmp, path)
