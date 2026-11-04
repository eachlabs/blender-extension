"""Offline stand-ins shared by the Blender smoke test and the GUI check."""

import contextlib
import itertools
import json
import glob
import os
import shutil
import sys
import tempfile
import threading
import zipfile

from eachlabs import api_client, catalog, compat, preferences

ENTRIES = [
    {"slug": "smoke-edit", "title": "Smoke Edit", "output_type": "image", "category": {"Slug": "image-to-image"},
     "request_schema": {"required": ["prompt", "image_url"], "properties": {
         "prompt": {"type": "string"}, "image_url": {"type": "string", "format": "uri"}}}},
    {"slug": "smoke-first-last", "title": "Smoke First Last", "output_type": "video",
     "category": {"Slug": "image-to-video"}, "request_schema": {"required": ["prompt", "duration"], "properties": {
         "prompt": {"type": "string"}, "first_frame_url": {"type": "string", "format": "uri"},
         "last_frame_url": {"type": "string", "format": "uri"}, "seed": {"type": "integer"},
         "duration": {"type": "integer", "enum": [5, 10], "default": 5},
         "aspect_ratio": {"type": "string", "enum": ["16:9", "9:16"]}}}},
]
# Shaped like the production bytedance-seedance-2-5-reference-to-video schema (synthetic copy).
REFERENCE_MODEL = {
    "slug": "bytedance-seedance-2-5-reference-to-video", "title": "Reference Video (fake)", "output_type": "video",
    "category": {"Slug": "reference-to-video"}, "request_schema": {"required": ["prompt"], "properties": {
        "prompt": {"type": "string"},
        "image_urls": {"type": ["array", "string", "null"], "items": {"type": ["string", "null"], "format": "uri-reference"}},
        "video_urls": {"type": ["array", "string", "null"], "items": {"type": ["string", "null"], "format": "uri-reference"}},
        "audio_urls": {"type": ["array", "string", "null"], "items": {"type": ["string", "null"], "format": "uri-reference"}},
        "duration": {"type": "string", "enum": ["auto"] + [str(n) for n in range(4, 31)], "default": "auto"},
        "resolution": {"type": "string", "enum": ["480p", "720p", "1080p"], "default": "720p"},
        "draft": {"type": "boolean", "default": False},
        "generate_audio": {"type": "boolean", "default": True}}},
}
ENTRIES.append(REFERENCE_MODEL)
IMAGE_LABEL = "Smoke Edit [smoke-edit]"
VIDEO_LABEL = "Smoke First Last [smoke-first-last]"
REFERENCE_LABEL = "Reference Video (fake) [bytedance-seedance-2-5-reference-to-video]"


class FakeClient:
    """Stands in for EachlabsClient: uploads are recorded, results are local files.

    Set ``FakeClient.results["next"]`` to the file to "download" and ``FakeClient.statuses["next"]``
    to the status polls return; ``FakeClient.fail_create`` makes submission fail with that error.
    """

    log = []
    statuses = {}
    results = {}
    fail_create = None
    draft_id = None  # When set, outputs come back as {"video_url", "draft_id"} like a Seedance draft.

    def __init__(self, api_key, base_url, user_agent="", timeout=30):
        self.api_key = api_key

    def get_model(self, slug):
        return {"cost": {"estimate": "$0.10 per execution", "unit": "execution", "type": "fixed", "amount": 0.1}}

    def upload_file(self, path, content_type, file_type, cancel_event=None):
        FakeClient.log.append(("upload", os.path.basename(path)))
        return "https://fake.invalid/" + os.path.basename(path)

    def create_prediction(self, model, values):
        if FakeClient.fail_create:
            raise api_client.ApiError(FakeClient.fail_create, status=401)
        FakeClient.log.append(("create", model, values))
        return "pred-%d" % len(FakeClient.log)

    def get_prediction(self, prediction_id, timeout=None):
        status = FakeClient.statuses.get("next", "success")
        if status == "success":
            url = "https://fake.invalid/" + os.path.basename(FakeClient.results["next"])
            output = {"video_url": url, "draft_id": FakeClient.draft_id} if FakeClient.draft_id else url
            return {"status": "success", "output": output, "metrics": {"cost": 0.1}}
        return {"status": status}

    def cancel_prediction(self, prediction_id):
        FakeClient.log.append(("cancel", prediction_id))
        return {"status": "success"}

    def download(self, url, dest_path, cancel_event=None, max_bytes=None, wait_seconds=None):
        shutil.copyfile(FakeClient.results["next"], dest_path)
        return "video/mp4" if FakeClient.results["next"].endswith(".mp4") else "image/png"

    # Chat: ``FakeClient.chat_llm`` answers each round; ``FakeClient.balances`` is read in order.
    chat_llm = None
    balances = []
    chat_sent = []  # max_tokens and reasoning of each chat call

    def chat_completion(self, model, messages, tools, timeout=120.0, max_tokens=None, reasoning=True, effort=None):
        FakeClient.log.append(("chat", model))
        FakeClient.chat_sent.append({"max_tokens": max_tokens, "reasoning": reasoning, "timeout": timeout,
                                     "effort": effort})
        return FakeClient.chat_llm(messages, tools)

    def get_balance(self):
        if not FakeClient.balances:
            raise api_client.ApiError("no balance scripted")
        return {"balance_usd": FakeClient.balances.pop(0)}


_call_ids = itertools.count(1)


def tool_reply(*calls):
    """A chat completion asking for ``(name, args)`` tool calls."""
    return {"choices": [{"message": {"content": None, "tool_calls": [
        {"id": "call_%d" % next(_call_ids), "type": "function",
         "function": {"name": name, "arguments": json.dumps(args)}} for name, args in calls]}}]}


def is_intent_call(messages):
    from eachlabs import intent

    return bool(messages) and messages[0].get("content") == intent.INSTRUCTIONS


def is_review_call(messages):
    """The scene review's call or its second look, which a scripted run answers apart from its rounds."""
    from eachlabs.instructions import review

    return bool(messages) and messages[0].get("content") in (review.SYSTEM, review.AGAIN_SYSTEM)


def text_reply(text):
    return {"choices": [{"message": {"content": text}}]}


NO_FINDINGS = '{"matches": true, "missing": [], "problems": []}'


class FakeLLM:
    """Answers chat rounds from a script; ``text_reply("Done.")`` once the script runs out.

    With ``gate`` set, each round waits for the event; it returns an empty text reply as soon as
    ``cancel()`` is true, the way a stopped request ends the round.
    """

    def __init__(self, replies, gate=None, cancel=None):
        self.replies = list(replies)
        self.gate = gate
        self.cancel = cancel or (lambda: False)
        self.calls = 0
        self.messages = []  # the messages of every call
        self.waiting = threading.Event()
        # The scene review's answers (text, or ``messages -> text``) and the messages of each review call.
        self.review, self.again, self.reviews = NO_FINDINGS, '{"solved": [], "worse": false}', []

    def __call__(self, messages, tools):
        if is_intent_call(messages):  # the quick call that reads a follow-up: a build unless a test scripts it
            return text_reply('{"intent": "build"}')
        if is_review_call(messages):  # not a round of the run's script
            self.reviews.append(messages)
            from eachlabs.instructions import review

            answer = self.review if messages[0]["content"] == review.SYSTEM else self.again
            return text_reply(answer(messages) if callable(answer) else answer)
        self.calls += 1
        self.messages.append([dict(m) for m in messages])
        if self.gate is not None:
            self.waiting.set()
            while not self.gate.wait(0.02):
                if self.cancel():
                    return text_reply("")
        return self.replies.pop(0) if self.replies else text_reply("Done.")


# Model-written steps for a street at sunset: real Blender Python, one run_python per stage.
LAYOUT_CODE = '''# Ground and two buildings
def block(name, size, location):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    bmesh.ops.translate(bm, vec=(0, 0, size[2] / 2), verts=bm.verts)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    scene.collection.objects.link(obj)
    return obj

block("Ground", (60, 20, 0.02), (0, 0, -0.02))
block("Building A", (7, 6, 12), (-8, 6, 0))
block("Building B", (7, 6, 18), (8, 6, 0))
'''

MATERIALS_CODE = '''# Materials for the ground and the buildings
def material(name, color, roughness):
    mat = bpy.data.materials.new(name)
    if mat.node_tree is None:
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = roughness
    mat.diffuse_color = color
    return mat

colors = {"Ground": (0.04, 0.04, 0.05, 1.0), "Building": (0.45, 0.36, 0.28, 1.0)}
for obj in scene.objects:
    for prefix, color in colors.items():
        if obj.name.startswith(prefix) and obj.type == "MESH" and not obj.data.materials:
            obj.data.materials.append(material(obj.name + " material", color, 0.8))
'''

LIGHT_CODE = '''# Low sun, a warm street lamp and an evening sky
sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
sun.data.energy = 2.0
sun.rotation_euler = (math.radians(80), 0, math.radians(30))
scene.collection.objects.link(sun)
lamp = bpy.data.objects.new("Street lamp", bpy.data.lights.new("Street lamp", "POINT"))
lamp.data.energy = 300.0
lamp.data.color = (1.0, 0.7, 0.4)
lamp.location = (0, -2, 4.5)
scene.collection.objects.link(lamp)
world = bpy.data.worlds.new("Evening sky")
if world.node_tree is None:
    world.use_nodes = True
background = world.node_tree.nodes.get("Background")
background.inputs["Color"].default_value = (0.9, 0.5, 0.3, 1.0)
background.inputs["Strength"].default_value = 0.4
scene.world = world
'''

CAMERA_CODE = '''# A five second dolly along the street
target = bpy.data.objects.new("Camera target", None)
target.location = (0, 6, 6)
scene.collection.objects.link(target)
cam = bpy.data.objects.new("Street camera", bpy.data.cameras.new("Street camera"))
cam.data.lens = 35
scene.collection.objects.link(cam)
track = cam.constraints.new("TRACK_TO")
track.target = target
track.track_axis = "TRACK_NEGATIVE_Z"
track.up_axis = "UP_Y"
first = scene.frame_start
last = first + int(round(5 * scene.render.fps / scene.render.fps_base)) - 1
cam.location = (-20, -14, 3)
cam.keyframe_insert("location", frame=first)
cam.location = (20, -14, 3)
cam.keyframe_insert("location", frame=last)
scene.frame_end = last
scene.camera = cam
'''

KIOSK_CODE = '''# A kiosk in front of the buildings
mesh = bpy.data.meshes.new("Kiosk")
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=2.0)
bm.to_mesh(mesh)
bm.free()
kiosk = bpy.data.objects.new("Kiosk", mesh)
kiosk.location = (0, 12, 1)
scene.collection.objects.link(kiosk)
'''


def code_reply(code):
    return tool_reply(("run_python", {"code": code}))


STREET = [code_reply(LAYOUT_CODE), text_reply("Ground and two buildings."),
          code_reply(MATERIALS_CODE), text_reply("Asphalt and brick materials."),
          code_reply(LIGHT_CODE), text_reply("A low sun, a street lamp and an evening sky.")]
CAMERA = [code_reply(CAMERA_CODE), text_reply("A five second dolly along the street.")]
CHECK = [tool_reply(("read_scene", {}), ("camera_view", {}))]  # the final text reply follows
BAD_CAMERA = code_reply("# Camera\ncam = bpy.data.objects['No such camera']")


@contextlib.contextmanager
def offline_api(online=True):
    """Route all API calls to FakeClient with a fake key and fast polling."""
    real = api_client.EachlabsClient, compat.online_problem, preferences.settings
    api_client.EachlabsClient = FakeClient
    if online:
        compat.online_problem = lambda: None
    preferences.settings = lambda context=None: dict(real[2](context), api_key="fake-key", poll_interval=0.05)
    try:
        yield FakeClient
    finally:
        api_client.EachlabsClient, compat.online_problem, preferences.settings = real


def load_catalog():
    catalog._loaded(ENTRIES, [], [])


def ensure_skia():
    """Make ``import skia`` work in Blender from this checkout: unpack this Python's wheel from
    eachlabs/wheels (scripts/build.sh downloads them). Returns an error text, or None when it works."""
    try:
        import skia  # noqa: F401
        return None
    except ImportError:
        pass
    tag = "cp%d%d" % sys.version_info[:2]
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eachlabs", "wheels")
    machine = "arm64" if os.uname().machine == "arm64" else "x86_64" if sys.platform != "win32" else "amd64"
    wheels = [w for w in glob.glob(os.path.join(root, "skia_python-*-%s-%s-*.whl" % (tag, tag))) if machine in w
              and ("macosx" in w) == (sys.platform == "darwin") and ("linux" in w) == sys.platform.startswith("linux")]
    if not wheels:
        return "no Skia wheel for %s %s in %s; run scripts/build.sh first" % (tag, machine, root)
    target = os.path.join(tempfile.gettempdir(), "eachlabs-skia-" + os.path.basename(wheels[0])[:-4])
    if not glob.glob(os.path.join(target, "skia.*")):
        with zipfile.ZipFile(wheels[0]) as wheel:
            wheel.extractall(target)
    sys.path.insert(0, target)
    try:
        import skia  # noqa: F401,F811
    except ImportError as exc:
        return "Skia wheel %s does not import: %s" % (os.path.basename(wheels[0]), exc)
    return None
