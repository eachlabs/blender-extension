"""What the bar shows about the chat (ChatState) and what one run carries from start to finish (_Run)."""

import bpy
import threading
from dataclasses import dataclass, field

from .. import chat_loop, generation, preferences


@dataclass
class ChatState:
    prompt: str = ""
    target: str = "scene"  # the bar's tab: what the next prompt builds (``instructions.targets``)
    run_target: str = "scene"  # the tab the last run started with; Retry keeps it
    stages: dict = field(default_factory=dict)  # stage -> todo | active | done | failed | cancelled
    status: str = "idle"  # idle | running | done | stopped | cancelled
    thinking_since: object = None  # time.monotonic() while waiting for the model, else None
    started_at: float = 0.0  # time.monotonic() when the run started; 0 before any run
    plan_since: object = None  # time.monotonic() while the plan waits for Build, else None
    plan_waited: float = 0.0  # seconds the plan waited for Build in this run; not the run's own time
    round: int = 0
    total: int = 0
    tools: list = field(default_factory=list)  # last tool events: id, name, summary, state, detail
    reply: str = ""
    error: str = ""
    cost: object = None  # float | None
    cost_text: str = ""
    code_check_on: bool = False  # Code check was on for this run
    code_check_state: str = ""  # "" | checking | refused
    code_check_reason: str = ""  # why the last step was refused
    running: bool = False
    failed_stage: object = None  # str | None
    missing: list = field(default_factory=list)  # planned things the last run did not build; the bar offers them
    blocked: list = field(default_factory=list)  # objects the last edit was kept from changing; the bar offers them
    removal: bool = False  # blocked holds objects that still match what the last edit removed
    last_targets: list = field(default_factory=list)  # what the last run edited
    history: list = field(default_factory=list)  # prompts, newest first
    attempt: str = ""  # the prompt of the last start, also when it was refused; Retry sends it again
    code_steps: list = field(default_factory=list)  # this run's run_python steps: id, stage, code, state, detail
    changed: list = field(default_factory=list)  # stages that changed the scene, in order; each is one undo step
    unchanged: bool = False  # the run ended done, and its steps changed nothing in the scene
    objects: list = field(default_factory=list)  # this run's 3D objects: name, state, seconds, cost, cached, error
    found: list = field(default_factory=list)  # names a find selected; Frame result frames them
    objects_wait: bool = False  # the check stage waits for 3D objects to arrive
    concept: str = ""  # the concept picture: drawing | done | failed, or "" when the run has none
    concept_path: str = ""  # its file once drawn
    looking: bool = False  # the visual check renders a frame for the model
    final_render: str = ""  # the Final render: "" | rendering | saved | cancelled | failed
    final_path: str = ""  # its saved picture
    final_error: str = ""
    final_seconds: float = 0.0
    planning: bool = False  # the model is choosing which objects are generated in 3D
    plan: object = None  # plan3d.Plan shown in the bar, or None
    plan_waiting: bool = False  # the plan waits for Build or Cancel
    free_assets: tuple = ()  # names of the Poly Haven skies and textures the last run used
    billed: bool = False  # a 3D run was already going when the add-on stopped waiting for it: it may still bill
    play_camera: str = ""  # the camera the person chose for Play; "": the chat's camera, else the scene camera
    video: str = ""  # the shot video: "" | rendering | photos | generating | done | failed | stopped | too_long
    video_job: str = ""  # its job on ``pipeline.REGISTRY``
    video_message: str = ""  # "2 of 3" while the photos are made; the reason when it failed
    video_seconds: int = 0  # seconds the video model has been making it
    video_progress: int = 0  # percent of the renders written while it records the camera move
    video_since: float = 0.0  # time.monotonic() when the video model started
    video_stage: str = ""  # the stage it is at, failed or stopped at: camera | keys | look | video | sequencer
    video_info: dict = field(default_factory=dict)  # the video made last: seconds, photos, price, started, ended



class _Run:
    def __init__(self, build, client, model, limits, view=None, earlier=(), window=None):
        self.build, self.client, self.model, self.limits = build, client, model, limits
        self.light_model = ""  # the model for the light and materials stages; "": the scene's model
        self.detail_model = ""  # the model for the main objects' detail; "": the scene's model
        self.view = view  # pointer of the 3D view area the run was started from, or None
        self.window = window  # pointer of the window the run was started from, or None
        self.shaded = False  # Material Preview was switched on after the light stage
        self.earlier = tuple(earlier)  # earlier prompts of this scene, newest first; set for a follow-up
        self.code_check = False  # review each step before it runs
        self.rounds_cap = preferences.ROUNDS_CAP  # most rounds a request that lists many things may use
        self.put_back = set()  # objects outside an edit's targets its steps changed and the add-on put back
        self.removal = False  # an edit removed things, and others of the chat's still match the request
        self.secrets = ()  # credentials kept out of every tool result the model sees
        self.step_seconds = preferences.STEP_SECONDS  # time limit of one run_python step
        self.blender = tuple(bpy.app.version)  # read here: the worker never touches bpy
        self.framed = bool(earlier)  # a follow-up keeps the view the person has
        self.fresh = False  # a new scene: Blender's untouched startup Cube goes when its stages start
        self.had_collection = False  # the run's collection existed at some point of the run
        self.checked_at = -1e9  # when ``_lost`` last looked
        self.before = None  # code_runner.fingerprint at the start, or None when it could not be read
        self.objects_3d = False  # the model may generate 3D objects
        self.objects_limit = preferences.OBJECTS_3D_LIMIT  # 3D objects per scene
        self.objects_timeout = generation.TIMEOUT_S
        self.texture_seconds, self.concept_seconds, self.reply_seconds, self.download_seconds = (
            preferences.WAIT_DEFAULTS)  # until start() reads the preferences
        self.textures_limit = 0  # generated textures per scene; 0: no texture tool
        self.free_assets_on = False  # the stages may use Poly Haven's free skies and textures
        self.settle_on = False  # small loose props come down onto what is under them after a build stage
        self.free_assets = []  # names of the ones this run used, main thread
        self.concept = False  # the run starts with a concept picture of the scene
        self.concept_allowed = False  # a follow-up may draw one when the quick call says the person asked for it
        self.visual = None  # chat_loop.Visual when the visual check is on
        self.scene_review = False  # after the check stage, a separate call judges the scene (``chat/review.py``)
        self.review_pushes = None  # the build's undo steps before the review's fix stage, main thread
        self.jobs = []  # ids of this run's generation jobs, in order
        self.told = set()  # failed jobs the model was told to build in code; the worker thread writes it
        self.plan_step = False  # the run starts with a plan of its 3D objects
        self.plan = None  # the plan the person approved; the add-on queues its 3D items
        self.plan_event = chat_loop.threading.Event()  # set when the person answered the plan; like the executor's
        self.plan_answer = None  # "build" | "cancel"
        self.cache_folder = ""  # read on the main thread, so the worker can check the cache
        self.concept_folder = ""  # the same, for the concept picture's file
        self.final = False  # the stages are over: a 3D model with no code version to replace fails
        self.detail = None  # detail.Settings when the run has a detail stage
        self.detail_more = False  # the detail stage asks the model to think longer
        self.references_on = False  # the plan may order a reference picture of each main object
        self.references = {}  # item name -> {"state": drawing | done | failed, "data": data URL, "event": Event}
        self.planned = []  # (item name, detail) of the plan's code items, for the detail stage's pick
        self.names = []  # the chat's things (root names), for the quick call that reads the prompt
        self.things = []  # one inventory line per thing (name, kind, labels, parent), sent with those names
        self.selected = []  # session_uid of each selected object when the run started
        self.selected_names = []  # their names: sent only when the prompt points at them
        self.targets = []  # names of the existing objects the prompt changes (the selection, or found by name)
        self.whole = False  # every stage was asked for, before Assets or Characters left out the light and camera
        self.edit_roots = []  # an edit's target root objects, set on the main thread when the edit starts
        self.request = ""  # the prompt as the person wrote it
        self.cancel = threading.Event()
        self.thread = None
        self.name_key, self.name_index = None, {}  # ``_name_index``
