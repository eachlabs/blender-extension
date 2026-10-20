"""Shared driver for the example films: run shots through the add-on's pipeline like an agent would.

Used by the example scripts, such as lighthouse/make_movie.py, inside ``blender --background``. Shots run
through Generate Video from Camera Move with the default video model; spending is capped by a budget
calibrated on the first result. ``FakeClient`` makes every call local and free for rehearsals.
"""

import json
import os
import shutil
import stat
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from eachlabs import api_client, capabilities as caps, catalog, jobs, main_thread, naming, pipeline  # noqa: E402

# Listed production prices with a reference video: the same rate per output second and per reference
# second, so a clip of matching length costs twice the rate per second.
LISTED_RATES = {"480p": 0.0708 * 2, "720p": 0.159 * 2, "1080p": 0.3913 * 2}
LISTED_PER_SECOND = LISTED_RATES["480p"]
RETRIES = 1


def log(message):
    print("[run %s] %s" % (time.strftime("%H:%M:%S"), message), flush=True)


class FakeClient:
    """Free stand-in for EachlabsClient: every result is the uploaded input, with a draft id."""

    uploads, requests = {}, []
    IMAGE_MODEL = "p-image-edit"

    def __init__(self, api_key, base_url, user_agent="", timeout=30):
        self.api_key = api_key

    def list_models(self):
        uri_list = {"type": ["array", "string", "null"], "items": {"type": ["string", "null"], "format": "uri-reference"}}
        return [
            {"slug": self.IMAGE_MODEL, "title": "P Image Edit (fake)", "output_type": "image",
             "category": {"Slug": "image-to-image"},
             "request_schema": {"required": ["prompt"], "properties": {"prompt": {"type": "string"}, "images": uri_list}}},
            {"slug": "bytedance-seedance-2-5-reference-to-video", "title": "Seedance 2.5 Reference (fake)",
             "output_type": "video", "category": {"Slug": "reference-to-video"},
             "request_schema": {"required": ["prompt"], "properties": {
                 "prompt": {"type": "string"}, "image_urls": uri_list, "video_urls": uri_list, "audio_urls": uri_list,
                 "duration": {"type": "string", "enum": ["auto"] + [str(n) for n in range(4, 31)]},
                 "resolution": {"type": "string", "enum": ["480p", "720p", "1080p"]},
                 "aspect_ratio": {"type": "string", "enum": ["auto", "16:9", "9:16"]},
                 "draft": {"type": "boolean"}, "generate_audio": {"type": "boolean"}}}},
        ]

    def list_workflows(self):
        return []

    def get_model(self, slug):
        return {"cost": {"estimate": "fake", "unit": "execution", "type": "fixed", "amount": 0}}

    def get_balance(self):
        return {"balance_usd": 0}

    def upload_file(self, path, content_type, file_type, cancel_event=None):
        url = "https://fake.invalid/%s" % os.path.basename(path)
        FakeClient.uploads[url] = path
        return url

    def create_prediction(self, model, values):
        FakeClient.requests.append((model, values))
        return "fake-%d" % len(FakeClient.requests)

    def get_prediction(self, prediction_id):
        _model, values = FakeClient.requests[int(prediction_id.split("-")[1]) - 1]
        source = (values.get("video_urls") or values.get("images") or [None])[0]
        return {"status": "success", "output": {"video_url": source, "draft_id": "draft-" + prediction_id},
                "metrics": {"cost": 0}}

    def cancel_prediction(self, prediction_id):
        return {}

    def download(self, url, dest_path, cancel_event=None):
        shutil.copyfile(FakeClient.uploads[url], dest_path)
        return "video/mp4" if url.endswith(".mp4") else "image/png"


def read_key(path):
    path = os.path.expanduser(path)
    if stat.S_IMODE(os.stat(path).st_mode) & 0o077:
        raise SystemExit("%s must be chmod 600" % path)
    with open(path, encoding="utf-8") as handle:
        key = handle.read().strip()
    if not key:
        raise SystemExit("%s is empty" % path)
    return key


def connect(fake, key_file, base_url):
    """Point the add-on at the fake client or at the API with the key from ``key_file``."""
    if fake:
        api_client.EachlabsClient = FakeClient
        os.environ["EACHLABS_API_KEY"] = "fake"
    else:
        os.environ["EACHLABS_API_KEY"] = read_key(key_file)
    os.environ["EACHLABS_BASE_URL"] = base_url


def drive(until, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline and not until():
        main_thread.tick()
        time.sleep(0.2)
    main_thread.tick()
    return until()


def latest_job():
    return list(pipeline.REGISTRY.jobs.values())[-1]


def load_catalog():
    catalog.refresh()
    drive(lambda: catalog.STATUS["state"] in ("READY", "ERROR"), 180)
    if not catalog.loaded():
        raise SystemExit("catalog: %s" % catalog.STATUS["message"])


def configure_video(bpy, scene, reference_path=None, aspect="16:9", references=(), params=None):
    """Default video model, matched duration, audio on. One reference image is bound as @Image1; several
    ``references`` are uploaded and sent in order through Extra inputs, since a binding holds one file.
    ``params`` overrides model parameters such as resolution or draft."""
    message = pipeline.apply_default_video(bpy.context, force=True)
    if message:
        log(message)
    video = scene.eachlabs.video
    for binding in video.bindings:
        if binding.name == "image_urls":
            if references:
                binding.source = "NONE"
            else:
                binding.source, binding.filepath = caps.FILE, reference_path
    if references:
        client = api_client.EachlabsClient(os.environ["EACHLABS_API_KEY"], os.environ["EACHLABS_BASE_URL"], timeout=120)
        urls = [client.upload_file(p, naming.content_type_for(p), naming.upload_kind(p)) for p in references]
        video.extra_json = json.dumps({"image_urls": urls})
        log("uploaded %d reference images as @Image1-%d" % (len(urls), len(urls)))
    wanted = dict({"aspect_ratio": aspect}, **(params or {}))
    for param in video.params:
        if param.name not in wanted:
            continue
        value = wanted[param.name]
        if param.kind == "enum":
            if value not in {i for i, _, _ in catalog.enum_items(param.target_key, param.name)}:
                raise SystemExit("%s does not offer %s=%s" % (video.target, param.name, value))
            param.value_enum = value
        elif param.kind == "bool":
            param.value_bool = bool(value)
        else:
            param.value_string = str(value)
        param.enabled = True
    settings = scene.eachlabs
    settings.use_scene_range = False
    settings.preview_height = "720"  # The reference clip; the output resolution is the model's 480p.
    settings.match_duration = settings.import_audio = True
    settings.timing_mode = "FIT_RANGE"
    log("video target %s; inputs %s; params %s" % (
        video.target, {b.name: b.source for b in video.bindings if b.source != "NONE"},
        {p.name: getattr(p, "value_" + {"enum": "enum", "bool": "bool"}.get(p.kind, "string"))
         for p in video.params if p.enabled}))


def submit(bpy, scene, name, first, last, prompt):
    scene.eachlabs.frame_start, scene.eachlabs.frame_end = first, last
    scene.eachlabs.video.prompt = prompt
    scene.frame_set(first)
    error = pipeline.start_video(bpy.context)
    if error:
        raise SystemExit("shot %s: %s" % (name, error))
    job = latest_job()
    log("shot %s frames %d-%d rendered, job %s submitted" % (name, first, last, job.job_id))
    return job


def run_shots(bpy, scene, shots, budget, concurrency, spent=0.0, retries=RETRIES, listed_rate=LISTED_PER_SECOND):
    """Generate ``shots`` (dicts with name, first, last, seconds, prompt). Returns (done, entries, spent, stopped)."""
    queue, active, attempts, done, observed, entries, stopped = list(range(len(shots))), {}, {}, {}, [], [], None
    while queue or active:
        main_thread.tick()
        for job_id, index in list(active.items()):
            job = pipeline.REGISTRY.get(job_id)
            if job.active:
                continue
            del active[job_id]
            spent += job.cost or 0.0
            entry = {"shot": shots[index]["name"], "frames": [shots[index]["first"], shots[index]["last"]],
                     "job_id": job.job_id, "remote_id": job.remote_id, "state": job.state, "cost_usd": job.cost,
                     "draft_id": job.extras.get("draft_id"), "outputs": [p for p, _ in job.outputs],
                     "message": job.message, "error": job.error}
            entries.append(entry)
            log("shot %s %s, cost $%s. %s" % (entry["shot"], job.state, job.cost, job.error or job.message))
            if job.state == jobs.DONE:
                done[index] = job
                if job.cost:
                    observed.append(job.cost / shots[index]["seconds"])
            elif attempts[index] <= retries:
                queue.insert(0, index)
        # One shot at a time until one succeeds, so its settled cost replaces the listed rate.
        limit = concurrency if done else 1
        if queue and len(active) < limit:
            rate = max(observed) if observed else listed_rate
            in_flight = sum(shots[i]["seconds"] for i in active.values())
            projected = spent + rate * (in_flight + shots[queue[0]]["seconds"])
            if projected > budget:
                log("stopping: the next shot would bring the estimate to $%.2f, over the $%.2f budget"
                    % (projected, budget))
                stopped = "budget"
                queue.clear()
                continue
            index = queue.pop(0)
            attempts[index] = attempts.get(index, 0) + 1
            shot = shots[index]
            active[submit(bpy, scene, shot["name"], shot["first"], shot["last"], shot["prompt"]).job_id] = index
        time.sleep(0.5)
    return done, entries, spent, stopped
