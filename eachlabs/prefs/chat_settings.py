"""The chat's settings as the run reads them: the model, round and wait limits, 3D, textures, detail and consent."""

import bpy
import json

from .. import chat_loop, detail
from ..chat import quality as quality_modes
from . import live


def video_defaults(context=None):
    """``{"model", "bindings", "params"}`` for the default video model, or ``None`` when unset."""
    prefs = live.preferences.get_preferences(context)
    if prefs is None:
        return {"model": live.preferences.DEFAULT_VIDEO_MODEL, "bindings": dict(live.preferences.DEFAULT_VIDEO_BINDINGS),
                "params": dict(live.preferences.DEFAULT_VIDEO_PARAMS)}
    model = prefs.default_video_model.strip()
    if not model:
        return None
    values = {"model": model}
    for key, text in (("bindings", prefs.default_video_bindings), ("params", prefs.default_video_params)):
        try:
            parsed = json.loads(text) if text.strip() else {}
        except ValueError:
            parsed = {}
        values[key] = parsed if isinstance(parsed, dict) else {}
    return values



def quality(context=None):
    """``"PROTOTYPE"`` or ``"ADVANCED"``; Final when preferences are unavailable (scripts and tests that run
    unregistered keep the settings they pass)."""
    prefs = live.preferences.get_preferences(context)
    return quality_modes.mode_of(getattr(prefs, "chat_quality", None)) if prefs is not None else quality_modes.ADVANCED



def chat_limits(context=None):
    """Round and failure limits for a chat run, as the quality mode allows; the defaults when preferences are
    unavailable."""
    prefs = live.preferences.get_preferences(context)
    if prefs is None:
        return chat_loop.Limits()
    return quality_modes.limits(quality(context), chat_loop.Limits(total_rounds=prefs.chat_total_rounds,
                                                                   max_failures=prefs.chat_max_failures))



def rounds_cap(context=None):
    """Most model replies a request that lists many things may use; the default when preferences are unavailable."""
    prefs = live.preferences.get_preferences(context)
    value = getattr(prefs, "chat_rounds_cap", None) if prefs is not None else None
    value = value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else live.preferences.ROUNDS_CAP
    return quality_modes.rounds_cap(quality(context), value)



def step_seconds(context=None):
    """The time limit of one run_python step, in seconds."""
    prefs = live.preferences.get_preferences(context)
    value = getattr(prefs, "chat_step_seconds", None) if prefs is not None else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else live.preferences.STEP_SECONDS



def chat_model(context=None):
    """The chat model id: the preference, or the default when it is empty or preferences are unavailable."""
    prefs = live.preferences.get_preferences(context)
    value = getattr(prefs, "chat_model", "") if prefs is not None else ""
    value = (value.strip() if isinstance(value, str) else "") or live.preferences.DEFAULT_CHAT_MODEL
    return quality_modes.scene_model(quality(context), value, live.preferences.DEFAULT_CHAT_MODEL)



def light_model(context=None):
    """The model for the light and materials stages, or ``""`` when the scene's model answers them too."""
    prefs = live.preferences.get_preferences(context)
    value = getattr(prefs, "chat_light_model", None) if prefs is not None else None
    value = value if isinstance(value, str) and value else live.preferences.DEFAULT_LIGHT_MODEL
    return quality_modes.stage_model(quality(context), "" if value == live.preferences.SAME_MODEL else value)



def detail_model(context=None):
    """The model for the detail stage of the main objects, or ``""`` when the scene's model details them too."""
    prefs = live.preferences.get_preferences(context)
    value = getattr(prefs, "chat_detail_model", None) if prefs is not None else None
    value = value if isinstance(value, str) and value else live.preferences.DEFAULT_DETAIL_MODEL
    return quality_modes.stage_model(quality(context), "" if value == live.preferences.SAME_MODEL else value)



def set_quality(context, mode):
    """Store ``mode`` (``"PROTOTYPE"`` or ``"ADVANCED"``) in the saved preferences, as the bar's quality menu does."""
    _store(context, "chat_quality", quality_modes.mode_of(mode))



def set_chat_model(context, model):
    """Store ``model`` as the chat model in the saved preferences."""
    _store(context, "chat_model", model)



def _store(context, name, value):
    context = context or bpy.context
    prefs = live.preferences.get_preferences(context)
    if prefs is None:
        return
    setattr(prefs, name, value)
    try:
        context.preferences.is_dirty = True  # saved with the preferences, like a change made by hand
    except (AttributeError, TypeError):
        pass



def objects_3d(context=None):
    """``"AUTO"``, ``"ASK"`` or ``"OFF"``; ``"OFF"`` when preferences are unavailable (scripts and tests that run
    unregistered), so nothing is generated that the person did not choose."""
    prefs = live.preferences.get_preferences(context)
    value = getattr(prefs, "objects_3d", "OFF") if prefs is not None else "OFF"
    return value if value in ("AUTO", "ASK", "OFF") else "OFF"



def concept_picture(context=None):
    """True when a new scene starts with a concept picture; False when preferences are unavailable."""
    prefs = live.preferences.get_preferences(context)
    return bool(getattr(prefs, "concept_picture", False)) if prefs is not None else False



def visual_check(context=None):
    """True when the chat looks at small renders of the scene; False when preferences are unavailable."""
    prefs = live.preferences.get_preferences(context)
    return bool(getattr(prefs, "visual_check", False)) if prefs is not None else False



def scene_review(context=None):
    """True when a separate call judges the finished scene and its findings get a fix stage; False when
    preferences are unavailable."""
    prefs = live.preferences.get_preferences(context)
    return bool(getattr(prefs, "scene_review", False)) if prefs is not None else False



def textures_limit(context=None):
    """Generated textures one scene may order; 0 when preferences are unavailable."""
    prefs = live.preferences.get_preferences(context)
    value = getattr(prefs, "textures_limit", 0) if prefs is not None else 0
    return quality_modes.textures(quality(context), value if isinstance(value, int) and value > 0 else 0)



def concept_model(context=None):
    """``(model, price)`` of the concept picture for the quality mode."""
    from .. import generation

    return quality_modes.concept(quality(context), generation.IMAGE_MODEL, generation.IMAGE_PRICE)



def objects_3d_limits(context=None):
    """``(objects per scene, seconds per object)`` for generated 3D objects."""
    prefs = live.preferences.get_preferences(context)
    limit = getattr(prefs, "objects_3d_limit", live.preferences.OBJECTS_3D_LIMIT) if prefs is not None else live.preferences.OBJECTS_3D_LIMIT
    minutes = getattr(prefs, "objects_3d_wait_minutes", live.preferences.OBJECTS_3D_MINUTES) if prefs is not None else live.preferences.OBJECTS_3D_MINUTES
    return (limit if isinstance(limit, int) and limit > 0 else live.preferences.OBJECTS_3D_LIMIT,
            60.0 * (minutes if isinstance(minutes, int) and minutes > 0 else live.preferences.OBJECTS_3D_MINUTES))



def wait_limits(context=None):
    """``(texture, concept picture, model reply, download)`` wait limits in seconds; the module defaults when
    preferences are unavailable."""
    prefs = live.preferences.get_preferences(context)
    out = []
    for name, default in zip(("texture_wait_seconds", "concept_wait_seconds", "model_reply_wait_seconds",
                              "download_wait_seconds"), live.preferences.WAIT_DEFAULTS):
        value = getattr(prefs, name, None) if prefs is not None else None
        out.append(float(value) if isinstance(value, int) and not isinstance(value, bool) and value > 0
                   else float(default))
    return tuple(out)



def detail_settings(context=None):
    """``(rounds per object, objects at once, reference pictures, more thinking)`` for the detail stage; rounds 0
    (the stage is off) when preferences are unavailable."""
    prefs = live.preferences.get_preferences(context)
    if prefs is None:
        return 0, detail.PARALLEL, False, False
    rounds = getattr(prefs, "detail_rounds", 0)  # a preferences object without it, as in tests: off
    parallel = getattr(prefs, "detail_parallel", detail.PARALLEL)
    mode = quality(context)
    return (quality_modes.detail_rounds(mode, rounds if isinstance(rounds, int) and not isinstance(rounds, bool)
                                        and rounds > 0 else 0),
            parallel if isinstance(parallel, int) and not isinstance(parallel, bool) and parallel > 0
            else detail.PARALLEL,
            quality_modes.references(mode, bool(getattr(prefs, "reference_pictures", True))),
            getattr(prefs, "detail_thinking", "NORMAL") == "MORE")



def detail_candidates(context=None):
    """Versions of a main object the detail stage compares; 1 (built once) when preferences are unavailable."""
    prefs = live.preferences.get_preferences(context)
    value = getattr(prefs, "detail_candidates", 1) if prefs is not None else 1
    return quality_modes.candidates(quality(context), value if isinstance(value, int) and not isinstance(value, bool)
                                    and 1 <= value <= 3 else 1)


def detail_light_rounds(context=None):
    """Rounds per secondary object in the detail stage; 0 (none) when preferences are unavailable."""
    prefs = live.preferences.get_preferences(context)
    rounds = getattr(prefs, "detail_light_rounds", 0) if prefs is not None else 0
    return quality_modes.secondary_rounds(quality(context), rounds if isinstance(rounds, int)
                                          and not isinstance(rounds, bool) and rounds > 0 else 0)



def advanced_tools(context=None):
    """True when the bar shows Show code, Final render and New scene; off when preferences are unavailable."""
    prefs = live.preferences.get_preferences(context)
    return bool(getattr(prefs, "show_advanced_tools", False)) if prefs is not None else False



def code_check(context=None):
    """True when the person turned Code check on; off when preferences are unavailable."""
    prefs = live.preferences.get_preferences(context)
    return bool(getattr(prefs, "chat_code_check", False)) if prefs is not None else False



def code_allowed(context=None):
    """True once the person agreed that the chat runs the Blender Python it writes; also when preferences are
    unavailable (scripts and tests that run unregistered start runs directly)."""
    prefs = live.preferences.get_preferences(context)
    return prefs is None or getattr(prefs, "chat_code_consent", "UNSET") == "ALLOWED"



def ask_consent_again(context=None):
    """Forget the consent, so the card shows again before the next run."""
    context = context or bpy.context
    prefs = live.preferences.get_preferences(context)
    if prefs is None:
        return
    prefs.chat_code_consent = "UNSET"
    try:
        context.preferences.is_dirty = True
    except (AttributeError, TypeError):
        pass



def allow_code(context=None, code_check_on=False):
    """Store the consent (and Code check on, when asked) in the saved preferences."""
    context = context or bpy.context
    prefs = live.preferences.get_preferences(context)
    if prefs is None:
        return
    prefs.chat_code_consent = "ALLOWED"
    if code_check_on:
        prefs.chat_code_check = True
    try:
        context.preferences.is_dirty = True  # saved with the preferences, like a change made by hand
    except (AttributeError, TypeError):
        pass



def settle_props(context=None):
    """True when small loose props are settled after the layout, detail and fix stages; off without preferences."""
    prefs = live.preferences.get_preferences(context)
    return bool(getattr(prefs, "settle_props", False)) if prefs is not None else False


def helper_library(context=None):
    """True when helpers that worked are kept and offered; off when preferences are unavailable."""
    prefs = live.preferences.get_preferences(context)
    return bool(getattr(prefs, "helper_library", False)) if prefs is not None else False


def free_assets(context=None):
    """True when the chat may use Poly Haven's free skies and textures; off when preferences are unavailable."""
    prefs = live.preferences.get_preferences(context)
    return bool(getattr(prefs, "free_assets", False)) if prefs is not None else False
