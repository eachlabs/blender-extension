"""Pictures the chat draws for itself: the scene's concept picture and a reference picture per main object."""

import base64
import threading
import time
import uuid

from .. import chat_loop, generation, plan3d, thread_safety


def _concept(run, prompt, post):
    """Worker thread: draw the concept picture; its ``data:`` URL, or ``None`` when it could not be made (the run
    goes on without it)."""
    post({"type": "concept", "state": "drawing"})
    try:
        path, url, _cost = generation.draw(
            run.client, generation.concept_prompt(run.request or prompt), run.concept_folder,
            "concept-%s" % uuid.uuid4().hex[:6], run.cancel, aspect="16:9", image_format="jpeg",
            timeout_s=run.concept_seconds, download_s=run.download_seconds,
            model=getattr(run, "concept_model", generation.IMAGE_MODEL))
        with open(path, "rb") as handle:
            data = "data:image/jpeg;base64," + base64.b64encode(handle.read()).decode("ascii")
    except Exception as exc:  # the picture is a reference; the run builds without it
        chat_loop.debug_log({"stage": "concept", "error": str(exc)}, run.secrets)
        post({"type": "concept", "state": "failed"})
        return None
    post({"type": "concept", "state": "done", "url": url, "path": path})
    return data



def _draw_references(run, items):
    """Worker thread, after Build: draw a reference picture of each item, side by side, while the layout is built.
    Each picture runs on a thread of its own; the detail stage waits for the ones it needs."""
    for item in items:
        entry = {"state": "drawing", "data": "", "event": threading.Event()}
        run.references[item.name] = entry
        prompt = generation.reference_prompt(item.picture_prompt or item.description or item.name)

        def draw(entry=entry, prompt=prompt, name=item.name):
            try:
                path, _url, _cost = generation.draw(
                    run.client, prompt, run.concept_folder, "reference-%s" % uuid.uuid4().hex[:6], run.cancel,
                    aspect="4:3", image_format="jpeg", timeout_s=run.concept_seconds,
                    download_s=run.download_seconds, model=generation.REFERENCE_MODEL)
                with open(path, "rb") as handle:
                    entry["data"] = "data:image/jpeg;base64," + base64.b64encode(handle.read()).decode("ascii")
                entry["state"] = "done"
            except Exception as exc:  # the object is built without it
                chat_loop.debug_log({"stage": "reference", "object": name, "error": str(exc)}, run.secrets)
                entry["state"] = "failed"
            finally:
                entry["event"].set()
                thread_safety.gen_thread_ended()

        thread = threading.Thread(target=draw, name="eachlabs-reference", daemon=True)
        thread_safety.gen_thread_started()
        try:
            thread.start()
        except RuntimeError:
            thread_safety.gen_thread_ended()
            entry["state"] = "failed"
            entry["event"].set()



def _reference_for(run, name):
    """Worker thread: the reference picture drawn for the plan item that ``name`` is named after, waiting for it
    while it is still drawing; ``""`` when there is none."""
    words = set(plan3d.name_words(name))
    for item_name, entry in run.references.items():
        item_words = set(plan3d.name_words(item_name))
        if not item_words or not item_words <= words:
            continue
        deadline = time.monotonic() + run.concept_seconds
        while not entry["event"].wait(0.25):
            if run.cancel.is_set() or time.monotonic() > deadline:
                return ""
        return entry["data"]
    return ""
