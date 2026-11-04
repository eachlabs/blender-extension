"""Generation jobs the chat starts while it builds: one Eachlabs run each, on its own worker thread. No ``bpy``.

A job runs ``worker(spec, cancel, emit, client)`` and reports only through ``emit``; the main thread applies the
updates (``Registry.drain``) and brings ``READY`` results into the scene. ``run_object`` is the worker for a 3D
object; other kinds (a texture) add their own worker and reuse the registry, the states and the polling.
"""

import collections
import os
import queue
import tempfile
import threading
import time
from dataclasses import dataclass, field

from . import api_client, asset_cache, glb, thread_safety, workflow_3d

QUEUED = "queued"  # waits for the job before it: one 3D run at a time, since parallel runs slow each other down
STARTING = "starting"
RUNNING = "running"
DOWNLOADING = "downloading"
READY = "ready"  # the result is on disk; the main thread brings it into the scene
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"
FINISHED = frozenset((DONE, FAILED, CANCELLED))

TIMEOUT_S = 1200.0  # from its trigger; an object not back by then stays built in code (preference: 3D wait limit)
POLL_S = 4.0
POLL_HTTP_S = 10.0  # one status read; short, so a stopped worker ends soon after Stop
MAX_MODEL_BYTES = 64 * 1024 * 1024  # a downloaded 3D model (zip or GLB); a real one is about 6 MB
MAX_PICTURE_BYTES = 20 * 1024 * 1024  # a downloaded texture or concept picture
MAX_POLL_ERRORS = 5


@dataclass(frozen=True)
class Spec:
    """What a worker needs, captured on the main thread."""

    job_id: str
    kind: str  # "object"
    description: str
    tier: str
    api_key: str
    base_url: str
    folder: str  # where the result file is written
    store_path: str  # the workflow store (``workflow_3d.Store``)
    user_agent: str = "eachlabs-blender"
    timeout_s: float = TIMEOUT_S
    download_s: float = api_client.DOWNLOAD_TIMEOUT  # longest the result download may take
    poll_s: float = POLL_S
    cache_folder: str = ""  # set: the result is kept in the asset cache, and READY points there
    picture_prompt: str = ""  # the chat's words for drawing the object; the description when empty
    aspect: str = "1:1"  # a picture's aspect ratio (textures, the concept picture)
    image_format: str = "png"


@dataclass
class Job:
    job_id: str
    kind: str
    name: str  # what the bar calls it: "car"
    description: str
    tier: str
    state: str = STARTING
    error: str = ""
    path: str = ""  # the result file once READY
    cost: float = None  # the run's total_cost; 0 for a cached result
    cached: bool = False
    remote_id: str = ""
    version: str = ""  # the workflow version the run used
    started: float = field(default_factory=time.monotonic)
    triggered: float = None  # when its run was triggered (time.monotonic); its time limit counts from here
    finished: float = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    left_running: bool = False  # its run was triggered and the add-on stopped waiting: it may still go on and bill
    context: dict = field(default_factory=dict)  # main-thread data: the run, the placements
    priority: tuple = (0, 0)  # the queue runs the lowest first: (tier rank, place in the plan)

    @property
    def active(self):
        return self.state not in FINISHED

    @property
    def elapsed(self):
        return (self.finished or time.monotonic()) - self.started

    @property
    def running_for(self):
        """Seconds since its run was triggered; 0 while it waits in the queue."""
        if self.triggered is None:
            return 0.0
        return (self.finished or time.monotonic()) - self.triggered

    def apply(self, fields):
        if fields.get("state") == RUNNING and self.triggered is None:
            self.triggered = time.monotonic()
        for key, value in fields.items():
            setattr(self, key, value)
        if self.state in FINISHED and self.finished is None:
            self.finished = time.monotonic()


class Registry:
    """Main-thread list of generation jobs, plus the queue their workers write to."""

    def __init__(self, keep=32):
        self.jobs = collections.OrderedDict()
        self.keep = keep
        self._updates = queue.SimpleQueue()

    def add(self, job):
        self.jobs[job.job_id] = job
        finished = [j.job_id for j in self.jobs.values() if not j.active]
        while len(self.jobs) > self.keep and finished:
            del self.jobs[finished.pop(0)]
        return job

    def get(self, job_id):
        return self.jobs.get(job_id)

    def emitter(self, job_id):
        def emit(fields):
            self._updates.put((job_id, dict(fields)))
        return emit

    def start(self, job, spec, worker, client=None):
        """Start ``worker`` on its own thread. It is counted for ``thread_safety`` from just before it starts until
        it returns, so Blender 4.2's guard sees it even after the chat run ended."""
        emit = self.emitter(job.job_id)

        def work():
            try:
                worker(spec, job.cancel_event, emit, client)
            finally:
                thread_safety.gen_thread_ended()

        thread = threading.Thread(target=work, name="eachlabs-gen-%s" % job.job_id, daemon=True)
        thread_safety.gen_thread_started()
        try:
            thread.start()
        except Exception:
            thread_safety.gen_thread_ended()
            raise
        return thread

    def drain(self):
        """Apply queued updates; return the jobs that just became ``READY``."""
        ready = []
        while True:
            try:
                job_id, fields = self._updates.get_nowait()
            except queue.Empty:
                break
            job = self.jobs.get(job_id)
            if job is None or not job.active:
                continue
            job.apply(fields)
            if fields.get("state") == READY:
                ready.append(job)
        return ready

    def cancel(self, job_id, message="Stopped"):
        job = self.jobs.get(job_id)
        if job is None or not job.active:
            return False
        job.cancel_event.set()
        job.apply({"state": CANCELLED, "error": message})
        return True


BUSY = frozenset((STARTING, RUNNING, DOWNLOADING))
TIER_RANK = {"large": 0, "medium": 1}


def priority(tier, place):
    """A job's place in the queue: large before medium, then the plan's order (the subject first)."""
    return (TIER_RANK.get(tier, 2), place)


def next_queued(jobs):
    """The queued job to start now, or ``None``: one run at a time of each kind, so a texture never waits behind a
    3D object."""
    jobs = list(jobs)
    busy = {job.kind for job in jobs if job.state in BUSY}
    queued = [job for job in jobs if job.state == QUEUED and job.kind not in busy]
    return min(queued, key=lambda job: job.priority) if queued else None


def without_paths(text):
    """An error for the model: this computer's home and temp folders become ``~`` and ``<temp>``, so no local path
    or user name is sent."""
    text = str(text or "")
    for folder, short in ((tempfile.gettempdir(), "<temp>"), (os.path.expanduser("~"), "~")):
        for form in {folder, os.path.realpath(folder)}:
            if len(form) > 1:
                text = text.replace(form, short)
    return text


class _Stopped(Exception):
    pass


def run_object(spec, cancel, emit, client=None, sleep=None, clock=time.monotonic):
    """Trigger the 3D workflow, poll it, download the zip and write its GLB to ``spec.folder``. Emits ``READY``
    with the GLB path and the run's cost, or ``FAILED`` with a reason the person can read."""
    client = client or api_client.EachlabsClient(spec.api_key, spec.base_url, spec.user_agent)
    wait = sleep or cancel.wait
    try:
        store = workflow_3d.Store(spec.store_path, spec.base_url)
        execution_id, _workflow_id, version = workflow_3d.trigger(
            client, store, workflow_3d.inputs(spec.picture_prompt or spec.description, spec.tier))
        deadline = clock() + spec.timeout_s  # counted from the trigger, never from when the job was queued
        emit({"state": RUNNING, "remote_id": execution_id, "version": version})
        try:
            execution = _poll(spec, client, execution_id, cancel, wait, clock, deadline)
        except TimeoutError as exc:
            emit({"state": FAILED, "error": str(exc), "left_running": True})
            return
        model_url, _image_url = workflow_3d.outputs(execution)
        if not model_url:
            raise api_client.ApiError("The 3D run finished without a model")
        cost = execution.get("total_cost")
        cost = float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None
        emit({"state": DOWNLOADING, "cost": cost})
        path = _download_glb(spec, client, model_url, cancel)
        if spec.cache_folder:
            path = asset_cache.Cache(spec.cache_folder).put(spec.description, workflow_3d.cache_tier(spec.tier),
                                                            path, version, cost, hold=True)
        emit({"state": READY, "path": path, "cost": cost})
    except (_Stopped, api_client.Cancelled):
        emit({"state": CANCELLED, "error": "Stopped"})
    except TimeoutError as exc:
        emit({"state": FAILED, "error": str(exc)})
    except (api_client.ApiError, glb.GlbError) as exc:
        emit({"state": CANCELLED if cancel.is_set() else FAILED, "error": getattr(exc, "message", None) or str(exc)})
    except Exception as exc:  # a worker always reports back
        emit({"state": FAILED, "error": "%s: %s" % (type(exc).__name__, exc)})


def _poll(spec, client, execution_id, cancel, wait, clock, deadline):
    errors = 0
    while True:
        if wait(spec.poll_s):
            raise _Stopped()
        if clock() > deadline:
            raise TimeoutError("it took longer than %d minutes" % round(spec.timeout_s / 60))
        try:
            execution = client.get_execution(execution_id, timeout=POLL_HTTP_S)
            errors = 0
        except api_client.ApiError as exc:
            errors += 1
            if not exc.transient or errors >= MAX_POLL_ERRORS:
                raise
            continue
        status = api_client.normalize_status(execution.get("status"))
        if status == api_client.SUCCEEDED:
            return execution
        if status in (api_client.FAILED, api_client.CANCELLED):
            raise api_client.ApiError(_failure(execution))


def _failure(execution):
    for source in [execution] + [s for s in (execution.get("step_outputs") or {}).values() if isinstance(s, dict)]:
        for key in ("error_message", "error", "message"):
            value = source.get(key)
            if isinstance(value, str) and value.strip() and value.strip().lower() != "execution failed":
                return value.strip()[:300]
    return "the 3D run failed"


def _download_glb(spec, client, url, cancel):
    """The model zip (or a bare GLB) at ``url``, as ``<folder>/<job id>.glb``. The provider's link may expire soon
    after the run, so this runs right away."""
    os.makedirs(spec.folder, exist_ok=True)
    staging = os.path.join(spec.folder, spec.job_id + ".download")
    target = os.path.join(spec.folder, spec.job_id + ".glb")
    try:
        client.download(url, staging, cancel_event=cancel, max_bytes=MAX_MODEL_BYTES, wait_seconds=spec.download_s)
        with open(staging, "rb") as handle:
            head = handle.read(4)
        if head == glb.MAGIC:
            os.replace(staging, target)
        else:
            data = glb.glb_from_zip(staging)
            glb.split(data)  # a readable GLB, or GlbError now rather than at import
            with open(target + ".part", "wb") as out:
                out.write(data)
            os.replace(target + ".part", target)
    finally:
        for leftover in (staging, target + ".part"):
            if os.path.exists(leftover):
                os.remove(leftover)
    return target


# Pictures: a tileable texture, or the concept picture of a new scene. One ``nano-banana-pro`` prediction each.
IMAGE_MODEL = "nano-banana-pro"
IMAGE_PRICE = 0.15  # USD per picture, as the runs bill it; the bar shows the settled cost
TEXTURE_TIER = "texture-1k"  # the cache key's tier for textures
TEXTURE_TIMEOUT_S = 240.0
TEXTURE_PROMPT = ("A seamless tileable texture of %s. Seen straight on and filling the whole square, flat and evenly "
                  "lit, with no shadows, no perspective, no objects and no border; its edges wrap.")


CONCEPT_PROMPT = ("A concept picture of this 3D scene, as its camera would see it, in one wide frame: %s. "
                  "Realistic light and materials, with no text, no labels and no frame.")
CONCEPT_TIMEOUT_S = 120.0
# A reference picture of one main object for the detail stage, which builds to it: the same picture model as
# the concept picture, since a weak picture's wrong proportions are copied into the object.
# Models that take an image size preset instead of an aspect ratio, and the preset for each ratio.
SIZE_MODELS = ("z-image-turbo-text-to-image", "flux-2-flash-text-to-image")
SIZES = {"16:9": "landscape_16_9", "4:3": "landscape_4_3", "1:1": "square_hd"}
REFERENCE_MODEL = IMAGE_MODEL
REFERENCE_PRICE = IMAGE_PRICE
REFERENCE_PROMPT = ("A reference photo of %s, alone: the whole object fully in view at its real proportions, from the "
                    "view that shows its shape best, on a plain light background, with no text, no shadow clutter "
                    "and no other objects.")


def reference_prompt(description):
    return REFERENCE_PROMPT % " ".join(str(description).split())[:400]


def concept_prompt(prompt):
    return CONCEPT_PROMPT % " ".join(str(prompt).split())[:600]


def texture_prompt(description):
    return TEXTURE_PROMPT % " ".join(str(description).split())[:200]


def draw(client, prompt, folder, name, cancel, aspect="1:1", image_format="png", timeout_s=TEXTURE_TIMEOUT_S,
         poll_s=POLL_S, sleep=None, clock=time.monotonic, started=None, download_s=api_client.DOWNLOAD_TIMEOUT,
         model=IMAGE_MODEL):
    """One picture: run the prediction, wait for it, download it to ``<folder>/<name>.<format>``. Returns
    ``(path, url, cost)``. ``started(prediction_id)`` is called once it runs."""
    wait = sleep or cancel.wait
    inputs = {"prompt": prompt, "aspect_ratio": aspect, "output_format": image_format, "num_images": 1}
    if model == IMAGE_MODEL:
        inputs["resolution"] = "1K"
    if model in SIZE_MODELS:
        inputs = {"prompt": prompt, "image_size": SIZES.get(aspect, "landscape_16_9"), "num_images": 1,
                  "output_format": image_format}
    prediction_id = client.create_prediction(model, inputs)
    if started is not None:
        started(prediction_id)
    deadline = clock() + timeout_s
    errors = 0
    while True:
        if wait(poll_s):
            raise _Stopped()
        if clock() > deadline:
            raise TimeoutError("it took longer than %d minutes" % max(1, round(timeout_s / 60)))
        try:
            data = client.get_prediction(prediction_id, timeout=POLL_HTTP_S)
            errors = 0
        except api_client.ApiError as exc:
            errors += 1
            if not exc.transient or errors >= MAX_POLL_ERRORS:
                raise
            continue
        status = api_client.normalize_status(data.get("status"))
        if status in (api_client.FAILED, api_client.CANCELLED):
            raise api_client.ApiError(_failure(data).replace("the 3D run", "the picture"))
        if status == api_client.SUCCEEDED:
            break
    urls = api_client.output_urls(data.get("output"))
    if not urls:
        raise api_client.ApiError("The picture finished without a file")
    metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
    cost = next((float(v) for v in (metrics.get("cost"), data.get("cost"))
                 if isinstance(v, (int, float)) and not isinstance(v, bool)), None)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "%s.%s" % (name, "jpg" if image_format == "jpeg" else image_format))
    client.download(urls[0], path + ".part", cancel_event=cancel, max_bytes=MAX_PICTURE_BYTES,
                    wait_seconds=download_s)
    try:
        with open(path + ".part", "rb") as handle:
            head = handle.read(8)
        if glb.image_type(head) is None:  # only PNG and JPEG reach Blender's image loader
            raise api_client.ApiError("The picture is not a PNG or JPEG file")
        os.replace(path + ".part", path)
    finally:
        if os.path.exists(path + ".part"):
            os.remove(path + ".part")
    return path, urls[0], cost


def run_texture(spec, cancel, emit, client=None, sleep=None, clock=time.monotonic):
    """The worker for a texture: draw it, keep it in the cache, and emit ``READY`` with its file."""
    client = client or api_client.EachlabsClient(spec.api_key, spec.base_url, spec.user_agent)
    try:
        path, _url, cost = draw(client, texture_prompt(spec.picture_prompt or spec.description), spec.folder,
                                spec.job_id, cancel, spec.aspect, spec.image_format, spec.timeout_s, spec.poll_s,
                                sleep, clock, started=lambda pid: emit({"state": RUNNING, "remote_id": pid}),
                                download_s=spec.download_s)
        if spec.cache_folder:
            path = asset_cache.Cache(spec.cache_folder).put(spec.description, TEXTURE_TIER, path, IMAGE_MODEL, cost,
                                                            hold=True)
        emit({"state": READY, "path": path, "cost": cost})
    except (_Stopped, api_client.Cancelled):
        emit({"state": CANCELLED, "error": "Stopped"})
    except TimeoutError as exc:
        emit({"state": FAILED, "error": str(exc)})
    except api_client.ApiError as exc:
        emit({"state": CANCELLED if cancel.is_set() else FAILED, "error": getattr(exc, "message", None) or str(exc)})
    except Exception as exc:  # a worker always reports back
        emit({"state": FAILED, "error": "%s: %s" % (type(exc).__name__, exc)})
