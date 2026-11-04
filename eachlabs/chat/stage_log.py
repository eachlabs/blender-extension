"""A local log of what the person did with the chat's stages: finished runs, Undo stage, Retry, and a follow-up
right after. Read later to tune the instructions; nothing here is shown in the bar or sent anywhere.

One JSON line per event in the add-on's own folder on this computer. A prompt is kept only as a short hash, unless
the chat log is on (the person set ``EACHLABS_CHAT_LOG``), so the file never holds what the person typed by default.
"""

import hashlib
import json
import os
import time

FILE = "stages.jsonl"
BYTES_MAX = 1_000_000  # past this the file starts again; the newest half is kept
FOLLOW_UP_S = 600  # a new prompt this soon after a finished run counts as an edit right after it
_last = {"finished": 0.0, "prompt": ""}


def prompt_hash(prompt):
    return hashlib.sha1(str(prompt or "").encode()).hexdigest()[:10]


def entry(action, prompt, **fields):
    """The line for one event: its action, the time, the prompt's hash, and the prompt itself with the chat log on."""
    row = {"action": action, "time": int(time.time()), "prompt": prompt_hash(prompt)}
    if os.environ.get("EACHLABS_CHAT_LOG", "").strip():
        row["text"] = str(prompt or "")[:500]
    row.update({k: v for k, v in fields.items() if v is not None})
    return row


def write(folder, row):
    """Append ``row``; past ``BYTES_MAX`` keep the newest half. A full disk never stops the chat."""
    if not folder:
        return
    path = os.path.join(folder, FILE)
    try:
        if os.path.exists(path) and os.path.getsize(path) > BYTES_MAX:
            with open(path, encoding="utf-8") as fh:
                lines = fh.readlines()
            with open(path, "w", encoding="utf-8") as fh:
                fh.writelines(lines[len(lines) // 2:])
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass


def finished(folder, prompt, status, stages):
    """A run ended: its status and each stage's state."""
    _last["finished"], _last["prompt"] = time.monotonic(), prompt
    write(folder, entry("finished", prompt, status=status, stages=dict(stages)))


def started(folder, prompt, follow_up):
    """A run started; a follow-up soon after a finished one is the person editing what it built."""
    if follow_up and _last["finished"] and time.monotonic() - _last["finished"] < FOLLOW_UP_S:
        write(folder, entry("edited_after", _last["prompt"], next=prompt_hash(prompt)))


def undone(folder, prompt, stage):
    write(folder, entry("undo_stage", prompt, stage=stage))


def retried(folder, prompt, stage):
    write(folder, entry("retry", prompt, stage=stage))
