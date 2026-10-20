"""Add-on preferences: API key, API URL and polling, plus Test connection."""

import json
import os

import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty, StringProperty

from . import api_client, compat

ENV_KEY = "EACHLABS_API_KEY"
ENV_URL = "EACHLABS_BASE_URL"

# The video model most generations use. Editable in the preferences; bindings and parameters that
# the selected model does not have are skipped (dev's copy of this model has no "draft" input).
DEFAULT_VIDEO_MODEL = "bytedance-seedance-2-5-reference-to-video"
DEFAULT_VIDEO_BINDINGS = {"video_urls": "clip"}
DEFAULT_VIDEO_PARAMS = {"resolution": "480p", "draft": True}

# Shown under Test connection; written by the operator, read by draw().
connection_status = {"text": "", "ok": None}


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


def video_defaults(context=None):
    """``{"model", "bindings", "params"}`` for the default video model, or ``None`` when unset."""
    prefs = get_preferences(context)
    if prefs is None:
        return {"model": DEFAULT_VIDEO_MODEL, "bindings": dict(DEFAULT_VIDEO_BINDINGS),
                "params": dict(DEFAULT_VIDEO_PARAMS)}
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


def user_agent():
    from . import VERSION

    return "eachlabs-blender/%s (Blender %s)" % (VERSION, bpy.app.version_string)


def client(context=None):
    """A client for the current settings. Raises ``ValueError`` for an invalid API URL."""
    values = settings(context)
    return api_client.EachlabsClient(values["api_key"], values["base_url"], user_agent())


CLASSES = (EachlabsPreferences,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
