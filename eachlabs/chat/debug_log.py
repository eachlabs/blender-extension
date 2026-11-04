"""The chat's debug log: every model call written to the file EACHLABS_CHAT_LOG names, with secrets and pictures removed."""

import json
import os

from .. import code_check


LOG_ENV = "EACHLABS_CHAT_LOG"  # a file path: every model call's messages and reply are appended to it as JSON lines



def _without_images(value):
    """A record with each ``data:`` image replaced by a short mark, so the log stays readable."""
    if isinstance(value, str):
        return "[image, %d characters]" % len(value) if value.startswith("data:image/") else value
    if isinstance(value, dict):
        return {k: _without_images(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_without_images(v) for v in value]
    return value



def debug_log(record, secrets=()):
    """Append ``record`` to the file ``EACHLABS_CHAT_LOG`` names, with ``secrets`` redacted; off when unset.
    The request's headers, which carry the key, are never part of a record."""
    path = os.environ.get(LOG_ENV, "").strip()
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(_without_images(code_check.redact(record, secrets)), default=str) + "\n")
    except OSError:  # a debug aid must never stop the run
        pass
