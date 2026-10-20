"""Session cache of models and workflows, and the window-manager lists the panels search."""

import threading
import time

import bpy

from . import api_client, capabilities as caps, main_thread, preferences

MAX_WORKFLOW_DETAILS = 50

MODELS = {}  # slug -> Target
WORKFLOWS = {}  # workflow_id -> Target
BY_LABEL = {}  # Target.label -> Target
COSTS = {}  # slug -> cost dict, None (no listed price) or "loading"
STATUS = {"state": "", "message": "", "loaded_at": None}
_ENUM_ITEMS = {}  # (target key, param name) -> [(identifier, name, description)]
_ENUM_VALUES = {}  # (target key, param name) -> {identifier: original value}


def loaded():
    return STATUS["state"] == "READY"


def resolve(label):
    return BY_LABEL.get(label) if label else None


def refresh(context=None):
    """Fetch the catalog in the background. The caller has already checked online access."""
    if STATUS["state"] == "LOADING":
        return
    client = preferences.client(context)
    STATUS.update(state="LOADING", message="Loading models…")

    def work():
        models, workflows, notes = [], [], []
        try:
            models = client.list_models()
        except api_client.ApiError as exc:
            main_thread.call_soon(lambda: _failed(exc.message))
            return
        if client.api_key:
            try:
                for row in client.list_workflows():
                    if len(workflows) >= MAX_WORKFLOW_DETAILS:
                        notes.append("first %d workflows only" % MAX_WORKFLOW_DETAILS)
                        break
                    workflows.append(client.get_workflow(row.get("workflow_id") or row.get("slug")))
            except api_client.ApiError as exc:
                notes.append("workflows unavailable: %s" % exc.message)
        else:
            notes.append("add an API key to list your workflows")
        main_thread.call_soon(lambda: _loaded(models, workflows, notes))

    threading.Thread(target=work, name="eachlabs-catalog", daemon=True).start()
    main_thread.start()


def _failed(message):
    STATUS.update(state="ERROR", message=message)


def _loaded(model_rows, workflow_rows, notes):
    MODELS.clear()
    WORKFLOWS.clear()
    for row in model_rows:
        target = caps.model_target(row)
        if target.key:
            MODELS[target.key] = target
    for row in workflow_rows:
        target = caps.workflow_target(row)
        if target is not None and target.key:
            WORKFLOWS[target.key] = target
    BY_LABEL.clear()
    for target in list(MODELS.values()) + list(WORKFLOWS.values()):
        BY_LABEL[target.label] = target
    summary = "%d models, %d workflows" % (len(MODELS), len(WORKFLOWS))
    if notes:
        summary += " (%s)" % "; ".join(notes)
    STATUS.update(state="READY", message=summary, loaded_at=time.time())
    populate(bpy.context)
    scene = getattr(bpy.context, "scene", None)
    if scene is not None and hasattr(scene, "eachlabs") and not scene.eachlabs.video.target:
        from . import pipeline

        pipeline.apply_default_video(bpy.context)


def populate(context):
    """Fill the searchable target lists for both actions from the cache."""
    wm = getattr(context, "window_manager", None)
    scene = getattr(context, "scene", None)
    if wm is None or not hasattr(wm, "eachlabs"):
        return
    for action, collection_name, settings_name in ((caps.IMAGE, "image_targets", "image"),
                                                   (caps.VIDEO, "video_targets", "video")):
        show_all = bool(scene and getattr(scene.eachlabs, settings_name).show_all)
        collection = getattr(wm.eachlabs, collection_name)
        collection.clear()
        offered = [t for t in WORKFLOWS.values() if caps.offers(t, action)]
        offered += sorted((t for t in MODELS.values() if caps.offers(t, action, show_all)),
                          key=lambda t: t.title.lower())
        for target in offered:
            item = collection.add()
            item.name = target.label
            item.key = target.key
            item.kind = target.kind


def fetch_cost(slug, context=None):
    """Fetch a model's listed price in the background (``GET /v1/models/{slug}``)."""
    if slug in COSTS and COSTS[slug] != "error":
        return
    try:
        client = preferences.client(context)
    except ValueError:
        return
    COSTS[slug] = "loading"

    def work():
        try:
            cost = client.get_model(slug).get("cost")
        except api_client.ApiError:
            cost = "error"
        main_thread.call_soon(lambda: COSTS.__setitem__(slug, cost))

    threading.Thread(target=work, name="eachlabs-cost", daemon=True).start()
    main_thread.start()


def price_text(target):
    if target is None:
        return ""
    if target.kind == caps.WORKFLOW:
        return "No listed price for workflows"
    cost = COSTS.get(target.key)
    if cost == "loading":
        return "Loading price…"
    if cost == "error":
        return "Price unavailable"
    if not isinstance(cost, dict):
        return "Price not listed"
    estimate = (cost.get("estimate") or "").strip()
    if not estimate or (estimate == "Usage-based pricing" and cost.get("unit") is None):
        return "Price not listed (usage-based)"
    return estimate


def register_enum(target_key, param):
    key = (target_key, param.name)
    _ENUM_ITEMS[key] = [(str(v), str(v), "") for v in param.choices]
    _ENUM_VALUES[key] = {str(v): v for v in param.choices}


def enum_items(target_key, name):
    return _ENUM_ITEMS.get((target_key, name)) or [("NONE", "(refresh)", "")]


def enum_value(target_key, name, identifier):
    return _ENUM_VALUES.get((target_key, name), {}).get(identifier, identifier)


def clear():
    MODELS.clear()
    WORKFLOWS.clear()
    BY_LABEL.clear()
    COSTS.clear()
    STATUS.update(state="", message="", loaded_at=None)
