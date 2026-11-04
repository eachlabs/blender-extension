"""The Eachlabs workflow that turns a text prompt into a textured 3D model. No ``bpy``; worker threads use it.

The add-on owns one workflow per API URL, named ``NAME``. Its id and version are kept in a small JSON file
(``Store``), and every version the add-on writes carries ``ADDON`` and ``DEF`` in ``definition.metadata``. Before
each run ``ensure`` checks the stored workflow: when it was deleted, its definition is older than ``DEF``, or its
steps are not exactly the add-on's (someone edited the models or their settings in the dashboard), the workflow is
made again or gets a new version with the add-on's definition. The marker alone is never trusted. A trigger that
finds the workflow gone makes a new one and tries once more.
"""

import json
import os
import re
import threading

from .api_client import ApiError

NAME = "Blender 3D model"
ADDON = "eachlabs-blender"
DEF = 2  # raise it whenever ``definition`` changes, so stored workflows get the new one
OLD_CREATED_BY = "eachlabs-blender-addon"  # versions made by hand before the marker existed count as ours, def 0
GONE = ("deleted", "archived", "inactive")
DESCRIPTION = ("Made by the each::labs Blender add-on: text prompt to a photo of one object, then to a textured "
               "3D model (GLB).")


# The chat writes how to draw each object (its picture prompt); only this general ending is the add-on's.
IMAGE_PROMPT = "$.inputs.prompt, plain white background, no floor, no shadow, no other objects"
# Hunyuan's mesh settings per tier. Both textured GLBs are remeshed to 40,000 triangles; the steps set how long the
# 3D step takes (30 steps: about 180 s). A tiny object is never generated: the chat builds it in code.
TIERS = {"large": {"octree": 256, "steps": 30}, "medium": {"octree": 256, "steps": 20}}
DEFAULT_TIER = "large"
TIER_SECONDS = {"large": 205, "medium": 170}  # a whole run, for the plan's time estimate
COST = 0.45  # USD per object before the run (picture 0.15, 3D model 0.30); the run's total_cost after


def definition():
    """The workflow definition: a photo of one object from ``prompt``, then a textured 3D model of it with the
    tier's ``octree`` and ``steps``. A parameter that is exactly one reference keeps its type, so both stay numbers.
    The outputs are the model's zip (``model_zip``) and the picture (``image``)."""
    large = TIERS["large"]
    return {
        "input_schema": {"properties": {
            "prompt": {"type": "string", "required": True},
            "octree": {"type": "number", "required": False, "default_value": large["octree"]},
            "steps": {"type": "number", "required": False, "default_value": large["steps"]},
        }},
        "steps": [
            {"id": "draw_image", "type": "model", "model": "nano-banana-pro",
             "params": {"prompt": IMAGE_PROMPT, "aspect_ratio": "1:1", "resolution": "2K", "output_format": "png",
                        "num_images": 1}},
            {"id": "make_3d", "type": "model", "model": "hunyuan-3d-v2-1",
             "params": {"input_image_url": "$.draw_image.primary", "textured_mesh": True,
                        "octree_resolution": "$.inputs.octree", "num_inference_steps": "$.inputs.steps",
                        "guidance_scale": 7.5}},
        ],
        "metadata": {"addon": ADDON, "def": DEF, "created_by": OLD_CREATED_BY, "description": DESCRIPTION,
                     "output_mapping": {"model_zip": "$.make_3d.primary", "image": "$.draw_image.primary"}},
    }


def inputs(picture_prompt, tier):
    """The trigger inputs for one object: the chat's picture prompt for it, and the tier's mesh settings; an unknown
    tier is ``DEFAULT_TIER``. The workflow adds the plain white background to the prompt."""
    settings = TIERS.get(tier) or TIERS[DEFAULT_TIER]
    prompt = " ".join(str(picture_prompt).split()).rstrip(" .,")
    return {"prompt": prompt, "octree": settings["octree"], "steps": settings["steps"]}


def cache_tier(tier):
    """The tier as the cache keeps it: models made with an older definition are not reused."""
    return "%s-def%d" % (tier, DEF)


def outputs(execution):
    """``(zip URL, image URL)`` of a finished execution; either may be ``None``."""
    named = execution.get("workflow_output") if isinstance(execution.get("workflow_output"), dict) else {}
    steps = execution.get("step_outputs") if isinstance(execution.get("step_outputs"), dict) else {}
    model = named.get("model_zip") or named.get("glb") or named.get("model") or (steps.get("make_3d") or {}).get(
        "primary") or execution.get("output")
    image = named.get("image") or (steps.get("draw_image") or {}).get("primary")
    return (model if isinstance(model, str) else None), (image if isinstance(image, str) else None)


class Store:
    """The workflow id and version per API URL, in one JSON file. Holds no key."""

    def __init__(self, path, base_url):
        self.path = path
        self.base_url = base_url

    def _read(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def load(self):
        """``{"workflow_id", "version", "def"}`` for this API URL, or ``None``."""
        entry = (self._read().get("workflows") or {}).get(self.base_url)
        if isinstance(entry, dict) and entry.get("workflow_id") and entry.get("version"):
            return entry
        return None

    def save(self, workflow_id, version):
        data = self._read()
        data.setdefault("workflows", {})[self.base_url] = {"workflow_id": workflow_id, "version": version, "def": DEF}
        self._write(data)

    def clear(self):
        data = self._read()
        if (data.get("workflows") or {}).pop(self.base_url, None) is not None:
            self._write(data)

    def _write(self, data):
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        partial = self.path + ".part"
        with open(partial, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        os.replace(partial, self.path)


def marker(version):
    """The ``DEF`` a workflow version was written with: ``0`` for one made before the marker existed, ``None``
    for a version that is not the add-on's."""
    meta = ((version or {}).get("definition") or {}).get("metadata") or {}
    if meta.get("addon") == ADDON:
        value = meta.get("def")
        return value if isinstance(value, int) and not isinstance(value, bool) else 0
    if meta.get("created_by") == OLD_CREATED_BY:
        return 0
    return None


def _steps(definition):
    """What a definition runs: each step's id, type, model and parameters, in order."""
    steps = (definition or {}).get("steps") if isinstance(definition, dict) else None
    return [(s.get("id"), s.get("type"), s.get("model"), s.get("params")) for s in steps or []
            if isinstance(s, dict)]


def same_steps(version):
    """True when a version runs exactly the add-on's steps: the same models with the same parameters."""
    return _steps((version or {}).get("definition")) == _steps(definition())


def _usable(workflow):
    return isinstance(workflow, dict) and str(workflow.get("status") or "active").lower() not in GONE


def _versions(workflow):
    return [v for v in workflow.get("versions") or [] if isinstance(v, dict) and v.get("version_id")]


def _ours(workflow):
    return _usable(workflow) and any(marker(v) is not None for v in _versions(workflow))


def next_version(workflow):
    """``v<n+1>`` after the highest ``v<n>`` the workflow has."""
    numbers = [int(m.group(1)) for v in _versions(workflow) for m in [re.fullmatch(r"v(\d+)", v["version_id"])] if m]
    return "v%d" % (max(numbers, default=0) + 1)


def _get(client, workflow_id):
    try:
        return client.get_workflow(workflow_id)
    except ApiError as exc:
        if exc.status in (404, 410):
            return None
        raise


def _fit(client, store, workflow):
    """Use the workflow's newest version written with ``DEF`` whose steps are still the add-on's; push one when it
    has none, so an edited workflow never changes what runs or what it costs. Returns (id, version)."""
    workflow_id = workflow["workflow_id"]
    current = next((v for v in _versions(workflow) if marker(v) == DEF and same_steps(v)), None)
    if current is not None:
        version = current["version_id"]
    else:
        version = next_version(workflow)
        client.put_workflow_version(workflow_id, version, definition(), published=True)
    store.save(workflow_id, version)
    return workflow_id, version


def _create(client, store):
    created = client.create_workflow(NAME, definition())
    versions = _versions(created)
    version = versions[0]["version_id"] if versions else "v1"
    store.save(created["workflow_id"], version)
    return created["workflow_id"], version


_lock = threading.Lock()  # several objects start at once; only one of them may make the workflow


def ensure(client, store, recreate=False):
    """``(workflow_id, version)`` of a workflow with the current definition, made or updated when needed.
    ``recreate``: make a new workflow without looking for one."""
    with _lock:
        if recreate:
            store.clear()
            return _create(client, store)
        stored = store.load()
        if stored:
            workflow = _get(client, stored["workflow_id"])
            if _ours(workflow):
                workflow.setdefault("workflow_id", stored["workflow_id"])
                return _fit(client, store, workflow)
            store.clear()
        named = [w for w in client.list_workflows() if isinstance(w, dict) and w.get("name") == NAME
                 and w.get("workflow_id")]
        named.sort(key=lambda w: str(w.get("created_at") or ""), reverse=True)  # newest first
        for row in named:
            workflow = _get(client, row["workflow_id"])
            if _ours(workflow):
                workflow.setdefault("workflow_id", row["workflow_id"])
                return _fit(client, store, workflow)
        return _create(client, store)


def _gone(exc):
    return exc.status in (404, 410)


def trigger(client, store, inputs):
    """Trigger the workflow; when it is gone, make it again and try once more. Returns
    ``(execution_id, workflow_id, version)``."""
    workflow_id, version = ensure(client, store)
    try:
        return client.trigger_workflow(workflow_id, version, inputs), workflow_id, version
    except ApiError as exc:
        if not _gone(exc):
            raise
    workflow_id, version = ensure(client, store, recreate=True)
    return client.trigger_workflow(workflow_id, version, inputs), workflow_id, version
