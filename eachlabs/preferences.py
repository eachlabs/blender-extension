"""Add-on preferences: API key, API URL and polling, plus Test connection."""

import json
import os

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty

from . import api_client, asset_cache, chat_loop, compat, detail, generation

ENV_KEY = "EACHLABS_API_KEY"
ENV_URL = "EACHLABS_BASE_URL"

# The video model most generations use. Editable in the preferences; bindings and parameters that
# the selected model does not have are skipped (dev's copy of this model has no "draft" input).
DEFAULT_VIDEO_MODEL = "bytedance-seedance-2-5-reference-to-video"
DEFAULT_VIDEO_BINDINGS = {"video_urls": "clip"}
DEFAULT_VIDEO_PARAMS = {"resolution": "480p", "draft": True}

# Shown under Test connection; written by the operator, read by draw().
connection_status = {"text": "", "ok": None}

DEFAULT_CHAT_MODEL = "openai/gpt-6-sol"
DEFAULT_LIGHT_MODEL = "anthropic/claude-sonnet-5.5"  # answers the light and materials stages
SAME_MODEL = "SAME"  # the light and materials stages use the scene's model
LIGHT_MODELS = (
    (DEFAULT_LIGHT_MODEL, "Sonnet 5.5", "Richer light and materials; costs a little more per scene"),
    (SAME_MODEL, "The scene's model", "One model answers every stage"),
    ("openai/gpt-6-sol", "GPT-6 Sol", "GPT-6 Sol answers the light and materials stages"),
    ("anthropic/claude-opus-5.5", "Opus 5.5", "Best light, about four times the cost"),
)
DEFAULT_DETAIL_MODEL = "openai/gpt-6-astra"  # details the main objects (animals, the scene's subjects)
DETAIL_MODELS = (
    (DEFAULT_DETAIL_MODEL, "GPT-6 Astra", "Best main objects; adds about $1-3 a scene"),
    (SAME_MODEL, "The scene's model", "The scene's model details every object"),
)
STEP_SECONDS = 20  # time limit of one step of the chat's Blender Python
DEFAULT_QUALITY = "PROTOTYPE"  # quick drafts; Final is for the version you keep
QUALITIES = (("PROTOTYPE", "Prototype", "Quick drafts with a plainer look: GPT-6.1 Terra for every stage (unless "
                                        "you set your own model), fewer material and light rounds, a quick concept "
                                        "picture, no generated textures or reference pictures"),
             ("ADVANCED", "Final (experimental)", "Full detail: the rounds, models, detail and reference pictures set below"))
ROUNDS_CAP = 90  # most model replies a run may use, the detail stage included

CODE_CHECK_TEXT = ("Reads every piece of Blender Python the chat writes before it runs, and tries to block any "
                   "step that reads or changes your files, goes online, or touches anything outside the scene "
                   "it builds. It can be wrong. A blocked step does not run; the chat is told why and writes it "
                   "again. Adds a few seconds per step. Off by default.")

CONSENT_UNSET_TEXT = "The chat will ask before it first runs code."

OBJECTS_3D_LIMIT = 2  # 3D objects the chat suggests per scene; the person may move more to 3D
OBJECTS_3D_MINUTES = 20  # from its trigger; a 3D object not back by then stays built in code
TEXTURES_LIMIT = 6  # generated textures per scene
# seconds: texture, concept picture, model reply, result download; used when preferences are unavailable
WAIT_DEFAULTS = (generation.TEXTURE_TIMEOUT_S, generation.CONCEPT_TIMEOUT_S, api_client.CHAT_TIMEOUT,
                 float(api_client.DOWNLOAD_TIMEOUT))

# MCP connection line in the sidebar; written by eachlabs.check_mcp, read by the panel.
mcp_status = {"ok": None, "text": ""}


class EachlabsPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    api_key: StringProperty(
        name="API key",
        subtype="PASSWORD",
        description="Create one at eachlabs.ai under Settings > API Keys. Stored unencrypted in "
                    "Blender's preferences; leave empty to use the EACHLABS_API_KEY environment variable",
    )
    base_url: StringProperty(name="API URL", default=api_client.DEFAULT_BASE_URL)
    poll_interval: FloatProperty(name="Poll every (s)", default=2.0, min=1.0, max=30.0)
    timeout_minutes: IntProperty(name="Give up after (min)", default=60, min=1, max=720)
    default_video_model: StringProperty(
        name="Default video model", default=DEFAULT_VIDEO_MODEL,
        description="Model slug selected for Generate Video when nothing else is chosen; empty to disable")
    default_video_bindings: StringProperty(
        name="Inputs", default=json.dumps(DEFAULT_VIDEO_BINDINGS),
        description='JSON: model input -> render output, e.g. {"video_urls": "clip", "image_urls": "first_frame"}')
    default_video_params: StringProperty(
        name="Parameters", default=json.dumps(DEFAULT_VIDEO_PARAMS),
        description='JSON: parameter overrides, e.g. {"resolution": "480p", "draft": true}')
    chat_quality: EnumProperty(
        name="Quality mode", default=DEFAULT_QUALITY,
        items=QUALITIES,
        description="How much each run builds; the prompt bar's quality menu sets it too")
    chat_model: StringProperty(
        name="Model", default=DEFAULT_CHAT_MODEL,
        description="Language model id the scene chat uses")
    chat_light_model: EnumProperty(
        name="Light and materials model",
        items=LIGHT_MODELS,
        default=DEFAULT_LIGHT_MODEL,
        description="The model that answers the light and materials stages; every other stage uses the model the "
                    "prompt bar shows")
    chat_detail_model: EnumProperty(
        name="Main objects' detail model",
        items=DETAIL_MODELS,
        default=DEFAULT_DETAIL_MODEL,
        description="The model that details the main objects (animals and the scene's subjects); other objects and "
                    "the other stages use the model the prompt bar shows")
    chat_total_rounds: IntProperty(
        name="Total rounds", default=chat_loop.TOTAL_ROUNDS, min=5, max=chat_loop.TOTAL_ROUNDS + 1,
        description="Most model replies one chat message may use. Lower it to make runs shorter; each stage "
                    "also has its own share, so more than the default adds at most the extra light round")
    chat_rounds_cap: IntProperty(
        name="Rounds for big requests", default=ROUNDS_CAP, min=5, max=200,
        description="Most model replies one run may use, the detail stage and its compared versions included: a "
                    "request that lists many things gets more rounds than Total rounds, two for each thing past the "
                    "first six. When a request needs more, the plan asks before it starts")
    chat_step_seconds: IntProperty(
        name="Seconds per step", default=STEP_SECONDS, min=5, max=120,
        description="Longest one step of the chat's Blender Python may run before it is stopped")
    chat_max_failures: IntProperty(
        name="Failures allowed", default=3, min=1, max=10,
        description="Failed steps in a row before the chat stops")
    show_advanced_tools: BoolProperty(
        name="Show advanced tools", default=False,
        description="Show code, Final render and New scene on the prompt bar")
    chat_code_check: BoolProperty(
        name="Code check", default=False,
        description=CODE_CHECK_TEXT)
    chat_code_consent: EnumProperty(
        name="Running the chat's code", default="UNSET",
        items=(("UNSET", "Not asked yet", "The bar asks before the chat's first run"),
               ("ALLOWED", "Allowed", "The person agreed that the chat runs Blender Python")),
        description="Whether the person agreed that the chat runs the Blender Python it writes")
    objects_3d: EnumProperty(
        name="3D objects", default="AUTO",
        items=(("AUTO", "Auto", "The chat chooses which objects are generated as real 3D models"),
               ("ASK", "Always ask", "The same as Auto"),
               ("OFF", "Off", "Everything is built in code")),
        description="Whether the chat may generate real 3D models of objects through Eachlabs")
    objects_3d_limit: IntProperty(
        name="3D limit per scene", default=OBJECTS_3D_LIMIT, min=1, max=12,
        description="Most 3D objects the chat suggests in one scene's plans. Objects you move to 3D on the plan are "
                    "always allowed")
    concept_picture: BoolProperty(
        name="Concept picture", default=True,
        description="At the start of a new scene, draw a picture of it from the prompt and show it to the chat as a "
                    "reference for layout, colours and mood. The plan shows its price")
    visual_check: BoolProperty(
        name="Visual check", default=True,
        description="After the layout, the light and the camera, and in the check, render a small frame from the "
                    "scene camera and show it to the chat, so it can fix what it sees. The picture shows everything "
                    "in the frame, your own objects too. A frame takes a few seconds")
    scene_review: BoolProperty(
        name="Scene review", default=True,
        description="After the build, look at the whole scene from four sides and fix what makes no sense: a ladder "
                    "that leads nowhere, parts lost inside others. About 2 rounds")
    free_assets: BoolProperty(
        name="Free skies and textures", default=True,
        description="Let the chat use free skies and photo textures from Poly Haven (CC0). They are "
                    "downloaded from polyhaven.com and kept in the cache folder. Off: the chat builds every "
                    "look with procedural nodes")
    helper_library: BoolProperty(
        name="Reuse helpers that worked", default=True,
        description="Keep the helper functions the chat wrote in steps that worked, on this computer only, and "
                    "offer the fitting ones to later scenes by name. They pass the same code filter again before "
                    "they run. Off: every scene starts without them")
    settle_props: BoolProperty(
        name="Settle small props", default=True,
        description="After the layout, the detail stage and a fix, bring the chat's small loose things (a cup, a "
                    "crate, a lantern) down onto what is under them, so nothing floats. Takes a fraction of a "
                    "second")
    textures_limit: IntProperty(
        name="Textures per scene", default=TEXTURES_LIMIT, min=0, max=24,
        description="Most generated photo textures the chat may order for one scene; 0 turns them off. The plan "
                    "shows what they may cost")
    objects_3d_wait_minutes: IntProperty(
        name="3D wait limit (min)", default=OBJECTS_3D_MINUTES, min=3, max=60,
        description="Longest one 3D object may take, counted from when its run starts; after it the object stays "
                    "built in code")
    texture_wait_seconds: IntProperty(
        name="Texture wait (s)", default=int(generation.TEXTURE_TIMEOUT_S), min=30, max=900,
        description="Longest one texture may take; after it the material keeps its colour")
    concept_wait_seconds: IntProperty(
        name="Concept picture wait (s)", default=int(generation.CONCEPT_TIMEOUT_S), min=30, max=600,
        description="Longest the concept picture may take; after it the scene is built without it")
    model_reply_wait_seconds: IntProperty(
        name="Model reply wait (s)", default=int(api_client.CHAT_TIMEOUT), min=30, max=600,
        description="Longest one model reply may take; after it the stage counts it as a failed round")
    download_wait_seconds: IntProperty(
        name="Download wait (s)", default=api_client.DOWNLOAD_TIMEOUT, min=30, max=600,
        description="Longest one result download may take; after it the result is skipped")
    detail_rounds: IntProperty(
        name="Detail rounds", default=detail.ROUNDS, min=0, max=8,
        description="After the layout, the model rounds each main object gets to add detail (one less for a "
                    "medium one, one more for its close-up). 0 turns the detail stage off")
    detail_light_rounds: IntProperty(
        name="Secondary detail rounds", default=detail.LIGHT_ROUNDS, min=0, max=4,
        description="Model rounds each secondary object (a tree, a bench, a rock) gets to add detail, after the main "
                    "objects. Copies of an object are rebuilt from it. 0 leaves secondary objects as the layout "
                    "built them")
    detail_parallel: IntProperty(
        name="Objects at once", default=detail.PARALLEL, min=1, max=6,
        description="Main objects the detail stage works on at the same time. Their Blender steps still run one "
                    "at a time")
    reference_pictures: BoolProperty(
        name="Reference pictures", default=True,
        description="Draw a picture of each main object for the chat to build it to, at about $0.15 each; the "
                    "detail stage compares the object with it after each round. The plan shows their price before "
                    "Build")
    detail_candidates: IntProperty(
        name="Versions to compare", default=2, min=1, max=3,
        description="For the first two main objects, the detail stage builds this many versions from the same "
                    "start, renders them, and the chat keeps the better one. Each extra version costs the object's "
                    "detail rounds again and one comparison. 1 builds each object once")
    detail_thinking: EnumProperty(
        name="Detail thinking", default="NORMAL",
        items=(("NORMAL", "Normal", "The model's usual thinking"),
               ("MORE", "More", "The model thinks longer on each detail step: slower, and a step may be cut off "
                                "more often")),
        description="How long the model thinks on each step of the detail stage")
    show_advanced: BoolProperty(name="Advanced")

    def draw(self, context):
        layout = self.layout
        problem = compat.online_problem()
        if problem:
            box = layout.box()
            box.alert = True
            box.label(text=problem, icon="ERROR")
        layout.prop(self, "api_key")
        if not self.api_key and os.environ.get(ENV_KEY):
            layout.label(text="Using the key from %s." % ENV_KEY, icon="INFO")
        row = layout.row()
        row.operator("eachlabs.test_connection", icon="URL")
        if connection_status["text"]:
            icon = "CHECKMARK" if connection_status["ok"] else "ERROR"
            row.label(text=connection_status["text"], icon=icon)
        box = layout.box()
        box.label(text="Default video model", icon="FILE_MOVIE")
        box.prop(self, "default_video_model", text="Model")
        box.prop(self, "default_video_bindings")
        box.prop(self, "default_video_params")
        box = layout.box()
        box.label(text="Chat", icon="OUTLINER_OB_FONT")
        box.prop(self, "chat_quality")
        row = box.row(align=True)
        row.prop(self, "chat_model")
        row.operator("eachlabs.best_quality", text="Best quality")
        box.prop(self, "chat_light_model")
        box.prop(self, "chat_detail_model")
        box.prop(self, "chat_total_rounds")
        box.prop(self, "chat_rounds_cap")
        box.prop(self, "show_advanced_tools")
        from .ui import tokens

        if tokens.CODE_CHECK_AVAILABLE:
            box.prop(self, "chat_code_check")
            from .panels import _wrap

            _wrap(box, context, CODE_CHECK_TEXT)
        if getattr(self, "chat_code_consent", "UNSET") == "ALLOWED":
            box.operator("eachlabs.ask_consent_again")
        else:
            box.label(text=CONSENT_UNSET_TEXT)
        box.prop(self, "visual_check")
        box.prop(self, "scene_review")
        box.prop(self, "chat_step_seconds")
        box.prop(self, "chat_max_failures")
        box = layout.box()
        box.label(text="Detail", icon="MOD_SUBSURF")
        box.prop(self, "detail_rounds")
        box.prop(self, "detail_light_rounds")
        box.prop(self, "detail_parallel")
        box.prop(self, "reference_pictures")
        box.prop(self, "detail_candidates")
        box.prop(self, "detail_thinking")
        box = layout.box()
        box.label(text="3D objects", icon="MESH_MONKEY")
        box.prop(self, "objects_3d")
        box.prop(self, "objects_3d_limit")
        box.prop(self, "objects_3d_wait_minutes")
        box.prop(self, "texture_wait_seconds")
        box.prop(self, "concept_wait_seconds")
        box.prop(self, "model_reply_wait_seconds")
        box.prop(self, "download_wait_seconds")
        box.prop(self, "textures_limit")
        box.prop(self, "free_assets")
        box.prop(self, "settle_props")
        box.prop(self, "helper_library")
        box.prop(self, "concept_picture")
        row = box.row()
        row.operator("eachlabs.clear_3d_cache", icon="TRASH")
        row.label(text=cache_text())
        layout.prop(self, "show_advanced", icon="TRIA_DOWN" if self.show_advanced else "TRIA_RIGHT", emboss=False)
        if self.show_advanced:
            col = layout.column()
            col.prop(self, "base_url")
            col.prop(self, "poll_interval")
            col.prop(self, "timeout_minutes")


def get_preferences(context=None):
    context = context or bpy.context
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon is not None else None


def settings(context=None):
    """API settings for a job, falling back to environment variables when running unregistered."""
    prefs = get_preferences(context)
    key = (prefs.api_key if prefs is not None else "") or os.environ.get(ENV_KEY, "")
    base_url = prefs.base_url if prefs is not None else os.environ.get(ENV_URL, api_client.DEFAULT_BASE_URL)
    return {
        "api_key": key.strip(),
        "base_url": base_url,
        "poll_interval": prefs.poll_interval if prefs is not None else 2.0,
        "timeout_seconds": (prefs.timeout_minutes if prefs is not None else 60) * 60.0,
    }


NOT_SETTINGS = ("rna_type", "bl_idname")


def setting_names(prefs):
    """The name of every setting the add-on's preferences hold."""
    return [p.identifier for p in prefs.bl_rna.properties if p.identifier not in NOT_SETTINGS and not p.is_readonly]


def secrets(context=None):
    """Every credential the add-on holds, for ``code_check.redact`` before a result goes to the model."""
    prefs = get_preferences(context)
    values = [prefs.api_key if prefs is not None else "", os.environ.get(ENV_KEY, "")]
    return [v.strip() for v in values if v and v.strip()]


USER_DIR_ENV = "EACHLABS_USER_DIR"  # overrides where the add-on keeps its own files (tests)


def user_folder(*parts):
    """A folder of the add-on's own files (made when missing): the extension's user folder, else Blender's config
    folder. It holds the 3D workflow's id and the downloaded 3D models, never a key."""
    root = os.environ.get(USER_DIR_ENV, "").strip()
    if not root:
        try:
            root = bpy.utils.extension_path_user(__package__, create=True)
        except (AttributeError, ValueError, RuntimeError):  # not installed as an extension
            root = os.path.join(bpy.utils.user_resource("CONFIG"), "eachlabs")
    path = os.path.join(root, *parts)
    os.makedirs(path, exist_ok=True)
    return path


def user_agent():
    from . import VERSION

    return "eachlabs-blender/%s (Blender %s)" % (VERSION, bpy.app.version_string)


def client(context=None):
    """A client for the current settings. Raises ``ValueError`` for an invalid API URL."""
    values = settings(context)
    return api_client.EachlabsClient(values["api_key"], values["base_url"], user_agent())


class EACHLABS_OT_ask_consent_again(bpy.types.Operator):
    bl_idname = "eachlabs.ask_consent_again"
    bl_label = "Ask before building again"
    bl_description = "Show the card that asks before the chat runs code, on the next run"

    def execute(self, context):
        ask_consent_again(context)
        return {"FINISHED"}


BEST_MODEL = "openai/gpt-6-astra"  # the "Best quality" choice; light and materials keep their own model


class EACHLABS_OT_best_quality(bpy.types.Operator):
    bl_idname = "eachlabs.best_quality"
    bl_label = "Best quality"
    bl_description = ("GPT-6 Astra builds every stage except light and materials, about $10 or more a scene; "
                      "slower and several times the cost of GPT-6 Sol")

    def execute(self, context):
        set_chat_model(context, BEST_MODEL)
        set_quality(context, "ADVANCED")  # Prototype would take the light, detail and rounds back
        return {"FINISHED"}


GENERATED_FOLDERS = ("3d-cache", "concepts")  # 3D models and textures; concept pictures


def cache_text():
    """What the generated files use on disk, for the preferences, such as ``Generated files: 14 MB``."""
    try:
        size = sum(asset_cache.Cache(user_folder(name)).size() for name in GENERATED_FOLDERS)
    except OSError:
        return ""
    return "Generated files: %s" % ("none" if size == 0 else "%.0f MB" % max(1, size / 1048576.0))


class EACHLABS_OT_clear_3d_cache(bpy.types.Operator):
    bl_idname = "eachlabs.clear_3d_cache"
    bl_label = "Clear generated files"
    bl_description = ("Delete the 3D models, textures and concept pictures kept on this computer. Objects already "
                      "in your scenes stay; the next request for one generates it again")

    @classmethod
    def poll(cls, context):
        from . import chat_run

        return not chat_run.STATE.running

    def invoke(self, context, event):
        from . import confirm
        from .ui import tokens

        return confirm.ask(self, context, event, *tokens.CONFIRM_CLEAR_FILES)

    def execute(self, context):
        freed = sum(asset_cache.Cache(user_folder(name)).clear() for name in GENERATED_FOLDERS)
        self.report({"INFO"}, "Cleared the generated files (%.0f MB)." % (freed / 1048576.0))
        return {"FINISHED"}


CLASSES = (EachlabsPreferences, EACHLABS_OT_ask_consent_again, EACHLABS_OT_best_quality, EACHLABS_OT_clear_3d_cache)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


# Imported last: these modules read this one's state through it.
from .prefs.chat_settings import (  # noqa: F401
    advanced_tools,
    allow_code,
    ask_consent_again,
    chat_limits,
    chat_model,
    code_allowed,
    code_check,
    concept_model,
    concept_picture,
    detail_candidates,
    detail_light_rounds,
    detail_model,
    detail_settings,
    free_assets,
    helper_library,
    light_model,
    objects_3d,
    objects_3d_limits,
    quality,
    rounds_cap,
    scene_review,
    set_chat_model,
    set_quality,
    settle_props,
    step_seconds,
    textures_limit,
    video_defaults,
    visual_check,
    wait_limits,
)
