"""The worker for a shot video: upload the clip and the renders, turn each render into a photo, then make the video
from the clip and the photos, and download it. No ``bpy``.

It runs as ``run(spec, cancel, emit, client)`` on a job registry's thread and reports only through ``emit``, with the
states, cancel note and download of ``jobs``.
"""

import os
import time
from dataclasses import dataclass, field

from .. import api_client, jobs
from . import models, prompts

PHOTO_RESOLUTION = "1.5K"
PHOTO_FORMAT = "jpeg"


@dataclass(frozen=True)
class ShotSpec:
    """Everything the worker needs, captured on the main thread."""

    job_id: str
    output_dir: str
    clip_path: str
    render_paths: list  # in frame order; render ``i`` becomes photo ``i``
    times: list  # the second of each photo in the clip
    person: str
    aspect: str
    resolution: str
    seconds: int
    api_key: str
    base_url: str
    user_agent: str = "eachlabs-blender"
    still: bool = False  # the camera does not move: the prompt says so
    uploaded: dict = field(default_factory=dict)  # key ("clip", "render1"…) -> public URL already uploaded
    poll_interval: float = 2.0
    max_poll_interval: float = 5.0
    timeout_seconds: float = 3600.0


class _Failed(Exception):
    """A prediction failed or was cancelled on Eachlabs; ``event`` is the final update to emit."""

    def __init__(self, event):
        super().__init__(event)
        self.event = event


def run(spec, cancel, emit, client=None, sleep=None, clock=time.monotonic):
    """Upload, make the photos, make the video and download it. Reports only through ``emit``."""
    client = client or api_client.EachlabsClient(spec.api_key, spec.base_url, spec.user_agent)
    wait = sleep or cancel.wait
    running = []  # prediction ids to cancel on Eachlabs when the job stops
    try:
        urls = _upload(spec, client, cancel, emit)
        photos, photo_cost = _photos(spec, client, urls, cancel, emit, wait, clock, running)
        jobs._check(cancel)
        video_input = {
            "prompt": prompts.video_prompt(spec.times, spec.person, still=spec.still),
            "video_urls": [urls["clip"]],
            "image_urls": photos,
            "resolution": spec.resolution,
            "duration": str(spec.seconds),
            "aspect_ratio": spec.aspect,
            "generate_audio": True,
        }
        emit({"state": jobs.RUNNING, "message": "%s is making it" % models.VIDEO["label"]})
        video_id = client.create_prediction(models.VIDEO["slug"], video_input)
        running.append(video_id)
        emit({"remote_id": video_id})
        video = _poll(spec, client, [video_id], cancel, wait, clock, running)[video_id]
        found = api_client.output_urls(video["output"])
        if not found:
            raise api_client.ApiError("The video finished without a file")
        outputs = jobs._download(spec, client, found[:1], cancel, emit)
        extras = {k: video["output"][k] for k in jobs.KEEP_OUTPUT_FIELDS
                  if isinstance(video["output"], dict) and video["output"].get(k)}
        emit({"state": jobs.IMPORTING, "outputs": outputs, "cost": _total(photo_cost + [video["cost"]]),
              "extras": extras, "message": ""})
    except (api_client.Cancelled, jobs._CancelledHere):
        emit({"state": jobs.CANCELLED, "message": _cancel_remote(client, running)})
    except _Failed as exc:
        _cancel_remote(client, running)
        emit(exc.event)
    except api_client.ApiError as exc:
        if cancel.is_set():
            emit({"state": jobs.CANCELLED, "message": _cancel_remote(client, running)})
        else:
            _cancel_remote(client, running)
            emit({"state": jobs.FAILED, "error": exc.message})
    except Exception as exc:  # Report anything unexpected in the panel instead of losing the thread.
        _cancel_remote(client, running)
        emit({"state": jobs.FAILED, "error": "%s: %s" % (type(exc).__name__, exc)})


def _upload(spec, client, cancel, emit):
    """Upload the clip and the renders not uploaded yet; return every key's URL."""
    files = [("clip", spec.clip_path, "video/mp4", "video")]
    for index, path in enumerate(spec.render_paths, start=1):
        content_type = "image/png" if path.lower().endswith(".png") else "image/jpeg"
        files.append(("render%d" % index, path, content_type, "image"))
    urls = dict(spec.uploaded)
    needed = [item for item in files if item[0] not in urls]
    if needed:
        emit({"state": jobs.UPLOADING, "message": "Uploading %d file(s)" % len(needed)})
    for key, path, content_type, media in needed:
        jobs._check(cancel)
        if not os.path.isfile(path):
            raise api_client.ApiError("The %s file is missing; make the shot again." % key)
        url = client.upload_file(path, content_type, media, cancel_event=cancel)
        urls[key] = url
        emit({"uploaded": {key: (url, time.time())}})
    return urls


def _photos(spec, client, urls, cancel, emit, wait, clock, running):
    """One photo per render, each from its own render only. Returns the photo URLs in render order and their
    costs."""
    ids = []
    for index in range(1, len(spec.render_paths) + 1):
        jobs._check(cancel)
        photo_input = {
            "prompt": prompts.photo_prompt(spec.person),
            "image": [urls["render%d" % index]],
            "aspect_ratio": spec.aspect,
            "resolution": PHOTO_RESOLUTION,
            "output_format": PHOTO_FORMAT,
        }
        remote_id = client.create_prediction(models.PHOTO["slug"], photo_input)
        ids.append(remote_id)
        running.append(remote_id)
    total = len(ids)

    def progress(finished):
        emit({"state": jobs.RUNNING, "message": "Making the look (%d of %d)" % (min(finished + 1, total), total)})

    progress(0)
    names = {remote_id: "Photo %d" % index for index, remote_id in enumerate(ids, start=1)}
    results = _poll(spec, client, ids, cancel, wait, clock, running, progress, names)
    photos = []
    for remote_id in ids:
        found = api_client.output_urls(results[remote_id]["output"])
        if not found:
            raise api_client.ApiError("A photo finished without a file")
        photos.append(found[0])
    return photos, [results[remote_id]["cost"] for remote_id in ids]


def _poll(spec, client, ids, cancel, wait, clock, running, progress=None, names=None):
    """Poll every id until all succeed; each finished id leaves ``running``. Returns id -> output and cost.

    A failed or cancelled prediction ends the job: ``_Failed`` carries the update to emit, its error starting with
    the prediction's name in ``names`` when it has one ("Photo 2 failed: …")."""
    pending = list(ids)
    results = {}
    interval = spec.poll_interval
    deadline = clock() + spec.timeout_seconds
    failures = 0
    while pending:
        if wait(interval):
            raise jobs._CancelledHere()
        if clock() > deadline:
            raise api_client.ApiError("Timed out after %d minutes waiting for Eachlabs" % (spec.timeout_seconds // 60))
        for remote_id in list(pending):
            try:
                data = client.get_prediction(remote_id)
                failures = 0
            except api_client.ApiError as exc:
                failures += 1
                if not exc.transient or failures >= jobs.MAX_TRANSIENT_ERRORS:
                    raise
                continue
            status = api_client.normalize_status(data.get("status"))
            if status == api_client.FAILED:
                running.remove(remote_id)
                reason = jobs._failure_text(data)
                name = (names or {}).get(remote_id)
                raise _Failed({"state": jobs.FAILED, "error": "%s failed: %s" % (name, reason) if name else reason})
            if status == api_client.CANCELLED:
                running.remove(remote_id)
                raise _Failed({"state": jobs.CANCELLED, "message": "Cancelled on Eachlabs"})
            if status == api_client.SUCCEEDED:
                pending.remove(remote_id)
                running.remove(remote_id)
                results[remote_id] = {"output": data.get("output"), "cost": jobs._cost(data)}
                if progress and pending:
                    progress(len(results))
        interval = min(spec.max_poll_interval, interval * 1.25)
    return results


def _cancel_remote(client, running):
    """Cancel every prediction still running on Eachlabs; return the note for the panel."""
    note = jobs.PREDICTION_CANCEL_NOTE if running else "Cancelled"
    for remote_id in list(running):
        try:
            client.cancel_prediction(remote_id)
        except api_client.ApiError as exc:
            note = "Stopped polling; Eachlabs cancel failed: %s" % exc.message
    running.clear()
    return note


def _total(costs):
    known = [cost for cost in costs if cost is not None]
    return round(sum(known), 6) if known else None
