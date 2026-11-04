"""The detail stage's comparison with the reference picture: after a round, a close-up of the object and the
reference go to the quick model, which names what still differs; the list becomes the next round's note. No
``bpy``: the close-up comes through ``execute``."""

from . import chat_loop
from .instructions.detail import COMPARE, COMPARE_MAX, COMPARED


def wanted(target, visual):
    """True when ``target`` has a reference picture and the model accepts pictures."""
    return bool(getattr(target, "reference", "")) and visual is not None and visual.accepted


def differences(text):
    """The judge's reply as at most ``COMPARE_MAX`` short lines, or ``[]`` when it says the object matches."""
    text = (text or "").strip()
    if not text or text.upper().startswith("MATCHES"):
        return []
    lines = [line.strip(" -*•\t") for line in text.splitlines()]
    return [line[:200] for line in lines if line][:COMPARE_MAX]


def compare(target, execute, post, cancel, visual, quick_llm, clean, secrets=()):
    """Worker thread: the next round's note naming what still differs from the reference, or ``None`` (it
    matches, or there is no close-up or reply). Costs one close-up and one quick call."""
    if not wanted(target, visual) or quick_llm is None or cancel.is_set():
        return None
    post({"type": "looking", "state": True})
    try:
        found = execute("detail_look", {"object": target.name})
    except Exception:  # the comparison is extra
        found = {}
    finally:
        post({"type": "looking", "state": False})
    images = found.get("images") if isinstance(found, dict) else None
    if not images:
        return None
    visual.renders += len(images)
    content = [{"type": "text", "text": COMPARE % target.name},
               {"type": "image_url", "image_url": {"url": target.reference}}]
    content += [{"type": "image_url", "image_url": {"url": url}} for url in images]
    try:
        reply = chat_loop.retried(quick_llm, cancel)([{"role": "user", "content": content}], [])
        text = reply["choices"][0]["message"].get("content") or ""
    except Exception as exc:  # no comparison: the round goes on without it
        chat_loop.debug_log({"stage": "detail", "object": target.name, "compare_error": str(exc)}, secrets)
        return None
    found = differences(text)
    chat_loop.debug_log({"stage": "detail", "object": target.name, "compared": found}, secrets)
    if not found:
        return None
    return {"role": "user", "content": COMPARED % clean("\n".join("- " + f for f in found))}
