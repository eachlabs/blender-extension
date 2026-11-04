"""What a prompt builds, by the bar's tab: a whole scene, one asset, or one character. The request text the model
gets for an asset or a character, and the stages such a run goes through. No Blender here."""

SCENE = "scene"
ASSET = "asset"
CHARACTER = "character"
TARGETS = (SCENE, ASSET, CHARACTER)

_ADD = {
    ASSET: ("Add exactly one new thing to the scene: %s\n"
            "Place it where it fits among what is already there. Build only this thing and its own parts. Change "
            "nothing that exists, and leave the light, the sky and the camera as they are."),
    CHARACTER: ("Add exactly one new character to the scene: %s\n"
                "It is the main object: build it with full detail and pose it where it fits among what is already "
                "there. Change nothing that exists, and leave the light, the sky and the camera as they are."),
}
_ALONE = {
    ASSET: ("Build one thing on its own: %s\n"
            "Show it on a plain ground under soft light, with a slow camera move around it. Build nothing else."),
    CHARACTER: ("Build one character on its own: %s\n"
                "It is the main object: build it with full detail. Show it on a plain ground under soft light, with "
                "a slow camera move around it. Build nothing else."),
}
# Added to the quick call on Assets and Characters with nothing selected: a thing the prompt names is changed only when
# it is of the tab's kind; anything else it mentions is the new thing, or where it goes.
KIND_NOTE = {
    ASSET: ("This request was sent on the Assets tab: it adds one object, or changes objects the person names. "
            "Count a thing in names only when it is an object, never a person or an animal."),
    CHARACTER: ("This request was sent on the Characters tab: it adds one person or animal, or changes characters "
                "the person names. Count a thing in names only when it is a person or an animal."),
}
SKIPPED = ("light", "camera")  # an asset or a character added to a scene keeps its light and camera


def target_of(value):
    """``value`` as a target; anything unknown builds a scene."""
    return value if value in TARGETS else SCENE


def request(target, prompt, fresh):
    """The request the model gets: the person's words for a scene, else the asset or character framing.
    ``fresh``: there is no scene yet, so the thing is shown on its own."""
    target = target_of(target)
    if target == SCENE:
        return prompt
    return (_ALONE if fresh else _ADD)[target] % prompt.strip()


def stages(target, fresh, stages):
    """``stages`` for the run: an asset or a character added to a scene skips the light and the camera."""
    if target_of(target) == SCENE or fresh:
        return tuple(stages)
    return tuple(s for s in stages if s not in SKIPPED)
