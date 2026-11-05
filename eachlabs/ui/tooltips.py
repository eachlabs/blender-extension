"""What each control of the prompt bar says on hover: what it does and how to use it, keyed by hit id
(``bar_state._HIT_ORDER``). The sidebar's buttons use the same texts as their Blender tooltips. No Blender code."""

from . import tokens as T

TEXTS = {
    "tab_scene": "Scene: build a whole scene with its camera move, or change anything in it. Start here with a "
                 "description of the place you imagine.",
    "tab_asset": "Assets: add one object to your scene, like a lamp or a barrel. Select an object first to change "
                 "it instead.",
    "tab_character": "Characters: add a person or an animal, built at full detail. Select one first to change it.",
    T.TAB_CLEAR: "Clear the selection. The next prompt then adds a new thing instead of changing this one.",
    "quality": "Prototype builds a quick draft for about $0.5. Final builds full detail with the models set in "
               "Preferences, for about $5–10. Click to choose.",
    "settings": "Open the add-on's preferences: your API key, the models, rounds and checks.",
    "send": "Send the prompt (Enter). Shift+Enter starts a new line.",
    "stop": "Stop the run (Esc). What was built stays.",
    "field": "Type what to build or change. Enter sends it; the Up arrow brings back earlier prompts.",
    "play": "Play the camera move through this camera. The 3D view looks through it; Pause puts your view back.",
    "play_menu": "Choose which camera to play through.",
    "frame": "Zoom the 3D view to everything the chat built. Your selection stays.",
    "final": "Render this scene once at full quality with Cycles, in its own window. It takes minutes; Esc there "
             "stops it. The picture is saved next to the .blend file.",
    "undo": "Undo the last stage the chat ran, as one step. It asks first.",
    "code": "Show the Blender Python the chat wrote for this scene, every prompt, in a Text Editor.",
    "new": "Build the next prompt in a new, empty scene. This one stays in Blender's scene list. It asks first.",
    "retry": "Run the stopped stage again, keeping what the others built.",
    "keep": "Keep what was built and clear this message. The next prompt changes the same scene.",
    "prefs": "Open the add-on's preferences to add or change your Eachlabs API key.",
    "network": "Open Blender's System preferences. Turn on Network > Allow Online Access there, then try again.",
    "halt": "Stop the run instead of waiting for the rewritten step. What was built stays.",
    "consent_check": "Let the chat run Blender code, with Code check reading each step before it runs. It can be "
                     "wrong; it is not a sandbox.",
    "consent_plain": "Let the chat run Blender code without Code check. Every step is still one undo.",
    "consent_cancel": "Run nothing. Your prompt stays in the field.",
    "plan_build": "Start the run with this plan. The 3D objects are generated and paid for; the rest is built in "
                  "code.",
    "plan_cancel": "Run nothing and pay nothing. Your prompt goes back into the field.",
    "plan_limit": "Build within your round limit. The scene may be left unfinished.",
    "plan_raise": "Raise the round limit for this run only, so the whole plan gets built. It costs more.",
    "missing": "Build the planned things that are not in the scene yet.",
    "widen": "Run the change again, this time also allowed to change the named objects.",
    "asked": "The prompt this run was sent. Click to show all of it; click again to fold it.",
}
PLAN_ITEM = "Click to move this object between a generated 3D model and code. Nothing is paid for before Build."
QUALITY_ITEMS = ("Choose Prototype: a quick draft for about $0.5.",
                 "Choose Final: full detail with the models set in Preferences, for about $5–10.")
CAMERA_ITEM = "Play through this camera."


def text(hit_id):
    """The tooltip of a control, or ``""`` for the bar itself and anything unknown."""
    if hit_id == "consent_plain" and not T.CODE_CHECK_AVAILABLE:
        return "Let the chat run the Blender code it writes. Every step is one undo, and you can see the code it ran."
    if hit_id in TEXTS:
        return TEXTS[hit_id]
    if hit_id in T.PLAN_HITS:
        return PLAN_ITEM
    if hit_id in T.QUALITY_HITS:
        return QUALITY_ITEMS[T.QUALITY_HITS.index(hit_id)]
    if hit_id in T.CAMERA_HITS:
        return CAMERA_ITEM
    return ""
