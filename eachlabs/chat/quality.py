"""The two quality modes: Prototype (a plainer look, one model, for quick drafts) and Final (the preferences as
set, for final scenes). Prototype trims only what changes the look: materials, light, detail and generated pictures.
The layout, the camera, the check, the visual check and the fixes keep their rounds, so nothing is left broken.
Each reader takes the preference's value and gives what the mode allows. No Blender here."""

from dataclasses import replace

PROTOTYPE = "PROTOTYPE"
ADVANCED = "ADVANCED"
MODES = (PROTOTYPE, ADVANCED)

# The camera keeps three rounds: build the move, measure it, fix it (see ``stages.STAGE_ROUNDS``).
STAGE_ROUNDS = {"layout": 3, "materials": 1, "light": 1, "camera": 3, "check": 2}
DETAIL_ROUNDS = 1  # per main object, plus its close-up; secondary objects get none
ROUNDS_CAP = 40
# Builds a whole scene for about a ninth of Final's routing and misses nothing from the prompt, but details animals
# poorly, so Final keeps its own models.
MODEL = "openai/gpt-6.1-terra"
# A clean, simple 3D picture in about 3 s; Final keeps ``generation.IMAGE_MODEL``.
CONCEPT_MODEL = "z-image-turbo-text-to-image"
CONCEPT_PRICE = 0.005


def mode_of(value):
    """``value`` as a mode; anything unknown is Prototype, the default."""
    return value if value in MODES else PROTOTYPE


def prototype(mode):
    return mode_of(mode) == PROTOTYPE


def limits(mode, limits):
    """``limits`` (a ``run_types.Limits``) for ``mode``: Prototype's stage rounds and their total, never more than
    the person's own total."""
    if not prototype(mode):
        return limits
    stage_rounds = dict(limits.stage_rounds)
    stage_rounds.update(STAGE_ROUNDS)
    return replace(limits, stage_rounds=stage_rounds, total_rounds=min(limits.total_rounds, sum(STAGE_ROUNDS.values())))


def rounds_cap(mode, cap):
    return min(cap, ROUNDS_CAP) if prototype(mode) else cap


def detail_rounds(mode, rounds):
    return min(rounds, DETAIL_ROUNDS) if prototype(mode) else rounds


def secondary_rounds(mode, rounds):
    return 0 if prototype(mode) else rounds


def candidates(mode, count):
    return 1 if prototype(mode) else count


def references(mode, on):
    return False if prototype(mode) else on


def scene_model(mode, model, default):
    """The scene's model: GPT-6.1 Terra in Prototype while the preference holds the ``default``; a model the person
    chose themselves is kept."""
    return MODEL if prototype(mode) and model == default else model


def concept(mode, model, price):
    """``(model, price)`` of the concept picture: Z-Image Turbo in Prototype, else ``model`` at ``price``."""
    return (CONCEPT_MODEL, CONCEPT_PRICE) if prototype(mode) else (model, price)


def textures(mode, limit):
    """Generated textures a scene may order: none in Prototype (free textures and node materials instead)."""
    return 0 if prototype(mode) else limit


def stage_model(mode, model):
    """The light and materials model, or the main objects' detail model: ``""`` (the scene's model) in Prototype."""
    return "" if prototype(mode) else model
