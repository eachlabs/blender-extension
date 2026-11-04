"""The render judge: the vision model compares two versions of one object and names the better one. No Blender."""

import re

SYSTEM = ("You judge two versions of one 3D object built in Blender for a scene. Pick the version that is better "
          "made: more real detail that reads from a few metres away, real proportions, every part attached to the "
          "rest, nothing floating, sunk in or poking through, smooth shapes where the real thing is smooth, and "
          "closer to what the request asks for. Judge the shapes and the build, not the plain shading.")
ASK = ("The request: %s\nThe object: \"%s\". Version A and version B follow, each from the same sides. Answer with "
       "the letter of the better version, A or B, then a short reason in one sentence.")
_VERDICT = re.compile(r"\b([AB])\b")


def messages(prompt, name, images_a, images_b):
    """The judge call: the request, then both versions' pictures, labelled."""
    parts = [{"type": "text", "text": ASK % (" ".join(str(prompt or "").split())[:600], name)},
             {"type": "text", "text": "Version A:"}]
    parts += [{"type": "image_url", "image_url": {"url": url}} for url in images_a]
    parts.append({"type": "text", "text": "Version B:"})
    parts += [{"type": "image_url", "image_url": {"url": url}} for url in images_b]
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": parts}]


def verdict(text):
    """``("A" or "B", reason)`` from the judge's reply, or ``(None, "")`` when it names neither."""
    text = str(text or "").strip()
    found = _VERDICT.search(text[:40])
    if not found:
        return None, ""
    reason = text[found.end():].strip(" .:-—\n")
    return found.group(1), reason[:200]
