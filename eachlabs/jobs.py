"""Job records and the worker thread that uploads, submits, polls and downloads. No ``bpy``.

Workers never mutate a ``Job``. They emit field updates into a queue that the main thread drains
(``Registry.drain``) from a ``bpy.app.timers`` callback.
"""

import collections
import json
import os
import queue
import threading
import time
from dataclasses import dataclass, field

from . import api_client, naming

RENDERING = "RENDERING"
UPLOADING = "UPLOADING"
SUBMITTING = "SUBMITTING"
QUEUED = "QUEUED"
RUNNING = "RUNNING"
DOWNLOADING = "DOWNLOADING"
IMPORTING = "IMPORTING"
DONE = "DONE"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

FINISHED = frozenset((DONE, FAILED, CANCELLED))

LABELS = {
    RENDERING: "Rendering",
    UPLOADING: "Uploading",
    SUBMITTING: "Submitting",
    QUEUED: "Queued",
    RUNNING: "Running",
    DOWNLOADING: "Downloading",
    IMPORTING: "Importing",
    DONE: "Done",
    FAILED: "Failed",
    CANCELLED: "Cancelled",
}

WORKFLOW_CANCEL_NOTE = ("Stopped polling. Eachlabs has no cancel endpoint for workflow runs, "
                        "so the run may still finish and be billed.")
# Prediction cancel only marks the record; provider work already in flight is not stopped.
PREDICTION_CANCEL_NOTE = "Cancelled on Eachlabs. Work already running at the provider may still finish."

MAX_TRANSIENT_ERRORS = 5
# Output fields kept beside the files: a Seedance 2.5 draft_id upgrades the draft to 1080p within 7 days.
KEEP_OUTPUT_FIELDS = ("draft_id",)


@dataclass(frozen=True)
class JobSpec:
    """Everything a worker needs, captured on the main thread before it starts."""

    job_id: str
    action: str
    target_kind: str
    target_key: str
    target_label: str
    output_dir: str
    base_input: dict
    url_fields: dict  # field name -> (role, is_array)
    files: dict  # role -> {"path", "content_type", "media"}
    api_key: str
    base_url: str
    user_agent: str = "eachlabs-blender"
    version_id: str = None
    uploaded: dict = field(default_factory=dict)  # role -> public URL already uploaded
    input_set_id: str = ""
    poll_interval: float = 2.0
    max_poll_interval: float = 5.0
    timeout_seconds: float = 3600.0


@dataclass
class Job:
    job_id: str
    action: str
    label: str
    target_kind: str
    state: str = RENDERING
    error: str = ""
    message: str = ""
    remote_id: str = ""
    outputs: list = field(default_factory=list)  # [(path, media kind)]
    cost: float = None
    extras: dict = field(default_factory=dict)  # Result fields worth keeping, such as a Seedance draft_id.
    uploaded: dict = field(default_factory=dict)  # role -> (url, unix time)
    started: float = field(default_factory=time.monotonic)
    finished: float = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    context: dict = field(default_factory=dict)  # Main-thread data for importing (scene, frames, flags).

    @property
    def active(self):
        return self.state not in FINISHED

    @property
    def elapsed(self):
        return (self.finished or time.monotonic()) - self.started

    def apply(self, fields):
        uploaded = fields.pop("uploaded", None)
        if uploaded:
            self.uploaded.update(uploaded)
        for key, value in fields.items():
            setattr(self, key, value)
        if self.state in FINISHED and self.finished is None:
            self.finished = time.monotonic()


def format_elapsed(seconds):
    seconds = int(max(0, seconds))
    return "%d:%02d" % divmod(seconds, 60) if seconds < 3600 else "%d:%02d:%02d" % (
        seconds // 3600, seconds % 3600 // 60, seconds % 60)


class Registry:
    """Main-thread job list plus the queue workers write to."""

    def __init__(self, keep=8):
        self.jobs = collections.OrderedDict()
        self.keep = keep
        self.updated = 0
        self._updates = queue.SimpleQueue()

    def add(self, job):
        self.jobs[job.job_id] = job
        self._prune()
        return job

    def get(self, job_id):
        return self.jobs.get(job_id)

    def active(self):
        return [job for job in self.jobs.values() if job.active]

    def emitter(self, job_id):
        def emit(fields):
            self._updates.put((job_id, dict(fields)))
        return emit

    def start(self, job, spec, client=None):
        """Run the worker for ``job`` on a daemon thread."""
        emit = self.emitter(job.job_id)
        worker = threading.Thread(target=run, args=(spec, job.cancel_event, emit, client),
                                  name="eachlabs-%s" % job.job_id, daemon=True)
        worker.start()
        return worker

    def drain(self):
        """Apply queued updates; return jobs that just reached ``IMPORTING``.

        ``self.updated`` counts the updates applied, so callers know to redraw.
        """
        ready = []
        self.updated = 0
        while True:
            try:
                job_id, fields = self._updates.get_nowait()
            except queue.Empty:
                break
            job = self.jobs.get(job_id)
            if job is None or (job.state in FINISHED and fields.get("state") != job.state):
                continue
            job.apply(fields)
            self.updated += 1
            if fields.get("state") == IMPORTING:
                ready.append(job)
        return ready

    def cancel(self, job_id, message=""):
        job = self.jobs.get(job_id)
        if job is None or not job.active:
            return False
        job.cancel_event.set()
        if job.state == RENDERING or job.state == IMPORTING:
            job.apply({"state": CANCELLED, "message": message or "Cancelled"})
        else:
            job.message = "Cancelling…"
        return True

    def cancel_all(self, message=""):
        for job in list(self.jobs.values()):
            self.cancel(job.job_id, message)

    def clear_finished(self):
        for job_id in [j.job_id for j in self.jobs.values() if not j.active]:
            del self.jobs[job_id]

    def _prune(self):
        finished = [j.job_id for j in self.jobs.values() if not j.active]
        while len(self.jobs) > self.keep and finished:
            del self.jobs[finished.pop(0)]


# -- worker ----------------------------------------------------------------------------------


def run(spec, cancel, emit, client=None, sleep=None, clock=time.monotonic):
    """Upload, submit, poll and download for one job. Reports only through ``emit``."""
    client = client or api_client.EachlabsClient(spec.api_key, spec.base_url, spec.user_agent)
    wait = sleep or cancel.wait
    remote_id = None
    try:
        urls = _upload(spec, client, cancel, emit)
        request_input = dict(spec.base_input)
        for name, (role, is_array) in spec.url_fields.items():
            request_input[name] = [urls[role]] if is_array else urls[role]
        _check(cancel)
        emit({"state": SUBMITTING, "message": ""})
        if spec.target_kind == "workflow":
            remote_id = client.trigger_workflow(spec.target_key, spec.version_id, request_input)
        else:
            remote_id = client.create_prediction(spec.target_key, request_input)
        emit({"state": QUEUED, "remote_id": remote_id})
        _write_manifest(spec, request_input, remote_id, "submitted")
        result = _poll(spec, client, remote_id, cancel, emit, wait, clock)
        if result is None:
            return
        outputs = _download(spec, client, result["urls"], cancel, emit)
        _write_manifest(spec, request_input, remote_id, "succeeded", outputs, result.get("cost"), result["extras"])
        emit({"state": IMPORTING, "outputs": outputs, "cost": result.get("cost"), "extras": result["extras"],
              "message": ""})
    except (api_client.Cancelled, _CancelledHere):
        _cancel_remote(spec, client, remote_id, emit)
    except api_client.ApiError as exc:
        if cancel.is_set():
            _cancel_remote(spec, client, remote_id, emit)
        else:
            emit({"state": FAILED, "error": exc.message})
    except Exception as exc:  # Report anything unexpected in the panel instead of losing the thread.
        emit({"state": FAILED, "error": "%s: %s" % (type(exc).__name__, exc)})


class _CancelledHere(Exception):
    pass


def _check(cancel):
    if cancel.is_set():
        raise _CancelledHere()


def _upload(spec, client, cancel, emit):
    urls = dict(spec.uploaded)
    needed = sorted({role for role, _ in spec.url_fields.values()} - set(urls))
    if needed:
        emit({"state": UPLOADING, "message": "Uploading %d file(s)" % len(needed)})
    for role in needed:
        _check(cancel)
        info = spec.files.get(role)
        if not info or not os.path.isfile(info["path"]):
            raise api_client.ApiError("Input file for %s is missing; render again." % role)
        url = client.upload_file(info["path"], info["content_type"], info["media"], cancel_event=cancel)
        urls[role] = url
        emit({"uploaded": {role: (url, time.time())}})
    return urls


def _poll(spec, client, remote_id, cancel, emit, wait, clock):
    is_workflow = spec.target_kind == "workflow"
    interval = spec.poll_interval
    deadline = clock() + spec.timeout_seconds
    failures = 0
    last_state = QUEUED
    while True:
        if wait(interval):
            raise _CancelledHere()
        if clock() > deadline:
            raise api_client.ApiError("Timed out after %d minutes waiting for Eachlabs" % (spec.timeout_seconds // 60))
        try:
            data = client.get_execution(remote_id) if is_workflow else client.get_prediction(remote_id)
            failures = 0
        except api_client.ApiError as exc:
            failures += 1
            if not exc.transient or failures >= MAX_TRANSIENT_ERRORS:
                raise
            emit({"message": "Retrying status check (%s)" % exc.message})
            continue
        status = api_client.normalize_status(data.get("status"))
        if status == api_client.SUCCEEDED:
            output = data.get("output")
            if output in (None, "", [], {}) and is_workflow:
                output = data.get("workflow_output")
            urls = api_client.output_urls(output)
            if not urls:
                raise api_client.ApiError("Finished, but the result has no downloadable file")
            extras = {k: output[k] for k in KEEP_OUTPUT_FIELDS if isinstance(output, dict) and output.get(k)}
            return {"urls": urls, "cost": _cost(data), "extras": extras}
        if status == api_client.FAILED:
            raise api_client.ApiError(_failure_text(data))
        if status == api_client.CANCELLED:
            emit({"state": CANCELLED, "message": "Cancelled on Eachlabs"})
            return None
        state = RUNNING if status == api_client.RUNNING else QUEUED
        if state != last_state:
            emit({"state": state, "message": ""})
            last_state = state
        interval = min(spec.max_poll_interval, interval * 1.25)


def _download(spec, client, urls, cancel, emit):
    emit({"state": DOWNLOADING, "message": "Downloading %d file(s)" % len(urls)})
    os.makedirs(spec.output_dir, exist_ok=True)
    outputs = []
    for index, url in enumerate(urls, start=1):
        _check(cancel)
        staging = naming.result_path(spec.output_dir, spec.job_id, index, "download")
        content_type = client.download(url, staging, cancel_event=cancel)
        path = naming.result_path(spec.output_dir, spec.job_id, index, naming.extension_for(url, content_type))
        os.replace(staging, path)
        outputs.append((path, naming.media_kind(path, content_type)))
    return outputs


def _cancel_remote(spec, client, remote_id, emit):
    note = "Cancelled"
    if remote_id and spec.target_kind == "workflow":
        note = WORKFLOW_CANCEL_NOTE
    elif remote_id:
        try:
            client.cancel_prediction(remote_id)
            note = PREDICTION_CANCEL_NOTE
        except api_client.ApiError as exc:
            note = "Stopped polling; Eachlabs cancel failed: %s" % exc.message
    emit({"state": CANCELLED, "message": note})


def _failure_text(data):
    """Failure reason. Predictions carry it inside ``output`` (an object, or the bare message for provider
    refusals); workflow executions at the top level."""
    output = data.get("output")
    if isinstance(output, str) and output.strip():
        return output.strip()[:500]
    sources = [output] if isinstance(output, dict) else []
    sources.append(data)
    for source in sources:
        for key in ("error_message", "error_cause", "error", "message", "logs"):
            value = source.get(key)
            if isinstance(value, str) and value.strip() and value.strip().lower() != "execution failed":
                return value.strip()[:500]
    return "The run failed without an error message"


def _cost(data):
    """Settled USD cost: ``metrics.cost`` on predictions, ``total_cost`` on workflow executions."""
    metrics = data.get("metrics") if isinstance(data.get("metrics"), dict) else {}
    for value in (metrics.get("cost"), data.get("total_cost"), data.get("cost")):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def _write_manifest(spec, request_input, remote_id, status, outputs=None, cost=None, extras=None):
    record = {
        "job_id": spec.job_id,
        "input_set_id": spec.input_set_id,
        "action": spec.action,
        "target": {"kind": spec.target_kind, "key": spec.target_key, "version_id": spec.version_id,
                   "label": spec.target_label},
        "remote_id": remote_id,
        "status": status,
        "input": request_input,
        "outputs": [path for path, _ in outputs or ()],
        "cost_usd": cost,
        "extras": extras or {},
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    try:
        os.makedirs(spec.output_dir, exist_ok=True)
        with open(naming.manifest_path(spec.output_dir, spec.job_id), "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
    except OSError:
        pass  # The manifest is a convenience; never fail a run over it.
