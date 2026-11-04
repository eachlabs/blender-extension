"""Pictures in the model's messages: the visual check's frames, and sending a call again without them when a model refuses images."""

from dataclasses import dataclass

from ..api_client import ApiError
from ..instructions.notes import LOOK, LOOK_AROUND, LOOK_FRAME, LOOK_NOTES, LOOK_OVERVIEW, NO_PICTURE


@dataclass
class Visual:
    """The visual check of a run. ``accepted`` turns False when the model refused a picture with HTTP 400; the
    caller keeps that for the model's later runs."""

    accepted: bool = True
    renders: int = 0  # frames rendered in this run
    # Seconds between the bar's "Looking at the frame…" and the render, so the bar is drawn before the render
    # holds the main thread.
    pause: float = 0.3



def _pictured(message):
    return isinstance(message.get("content"), list) and any(
        isinstance(part, dict) and part.get("type") == "image_url" for part in message["content"])



def without_pictures(messages):
    """``messages`` with every picture taken out: a visual check becomes ``NO_PICTURE``, the concept picture goes."""
    out = []
    for message in messages:
        if not _pictured(message):
            out.append(message)
        elif message.get("look"):
            out.append({"role": "user", "content": NO_PICTURE})
    return out



def look_message(found, stage=None):
    """The user message that shows a ``render_frames`` result to the model."""
    notes = [LOOK_NOTES[stage]] if stage in LOOK_NOTES else []
    measured = [n for n in found.get("notes") or () if isinstance(n, str)]
    text = "\n".join([LOOK] + notes + ([LOOK_OVERVIEW] if found.get("overview") else []) + measured)
    parts = [{"type": "text", "text": text}]
    frames = found.get("frames") or []
    for index, url in enumerate(found["images"]):
        if len(found["images"]) > 1 and index < len(frames):
            parts.append({"type": "text", "text": LOOK_FRAME % frames[index]})
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return {"role": "user", "content": parts, "look": True}



def around_message(images, views=None):
    """The user message that shows a ``look_at`` result: its four sides, each labelled."""
    parts = [{"type": "text", "text": LOOK_AROUND}]
    for index, url in enumerate(images):
        if views and index < len(views):
            parts.append({"type": "text", "text": "%s:" % views[index]})
        parts.append({"type": "image_url", "image_url": {"url": url}})
    return {"role": "user", "content": parts, "look": True}


def _for_model(messages):
    """The messages as sent: without the add-on's own marks."""
    return [{k: v for k, v in m.items() if k != "look"} if "look" in m else m for m in messages]



def with_pictures_fallback(ask, visual):
    """``ask(messages, tools)`` that, when the model refuses a call with pictures with HTTP 400, sends it once more
    without them and turns the visual check off. The messages are changed in place, so later rounds go without."""
    def call(messages, tools):
        try:
            return ask(_for_model(messages), tools)
        except ApiError as exc:
            if visual is None or exc.status != 400 or exc.rate_limited or not any(_pictured(m) for m in messages):
                raise
        visual.accepted = False
        messages[:] = without_pictures(messages)
        return ask(_for_model(messages), tools)
    return call
