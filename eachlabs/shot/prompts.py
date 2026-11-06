"""The prompts for a shot video and its photos. No ``bpy``."""

CLIP = (
    "@Video1 is a grey clay 3D preview of the scene. Use it only for the camera move and the layout: follow its "
    "camera path, speed, framing and timing exactly, and keep every object where it is in @Video1. Ignore how "
    "@Video1 looks: its materials, colours and lighting are placeholders."
)
ONE_PHOTO = (
    "@Image1 is a real photograph of the same scene at the first frame. The video starts exactly as @Image1, and "
    "the whole scene keeps the look of @Image1 for the whole shot: the same objects, colours and real materials."
)
MANY_PHOTOS = (
    "@Image1 to @Image%d are real photographs of the same scene from this shot: %s. The video starts exactly as "
    "@Image1 and passes through the view of each photo. Every object keeps the look it has in the photo that shows "
    "it: the same colours and real materials."
)
STILL_CLIP = (
    "@Video1 is a grey clay 3D preview of the scene. Use it only for the framing and the layout: the camera stays "
    "still for the whole shot, so keep its framing exactly, and keep every object where it is in @Video1. Ignore how "
    "@Video1 looks: its materials, colours and lighting are placeholders."
)
LOOK = "Photorealistic live-action footage from a real cinema camera, natural light, slight film grain."
PHOTO = (
    "Turn this 3D render into a real photograph of the same scene, taken with a full-frame camera. Keep the exact "
    "framing and every object in the same place, at the same size and outline, with the same colours."
)
PHOTO_REAL = "Make every material and every light real; anything stylised or simplified must look like the real thing."


def _seconds(value):
    return "%g second%s" % (value, "" if value == 1 else "s")


def _photos(times):
    if len(times) == 1:
        return ONE_PHOTO
    when = ["@Image1 at the first frame"]
    when += ["@Image%d at about %s" % (i + 1, _seconds(t)) for i, t in enumerate(times) if i > 0]
    return MANY_PHOTOS % (len(times), ", ".join(when))


def _keep(person):
    return "Add nothing and remove nothing" + (" except what the person asks for below" if person else "") + "."


def _person(text):
    text = (text or "").strip()
    return text[:-1] if text.endswith(".") else text


def video_prompt(times, person="", still=False):
    """The video prompt. ``times[i]`` is the second of photo ``i + 1`` in the clip; ``still``: the camera does not
    move, so the prompt asks for a still camera, not a camera path."""
    person = _person(person)
    parts = [STILL_CLIP if still else CLIP, _photos(times), _keep(person), LOOK]
    if person:
        parts.append("The person's direction: %s." % person)
    return " ".join(parts)


def photo_prompt(person=""):
    """The prompt that turns one 3D render into a photograph."""
    person = _person(person)
    parts = [PHOTO, _keep(person), PHOTO_REAL]
    if person:
        parts.append("The person's direction: %s." % person)
    return " ".join(parts)
