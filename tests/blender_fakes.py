"""Offline stand-ins shared by the Blender smoke test and the GUI check."""

import contextlib
import os
import shutil

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

    def get_prediction(self, prediction_id):
        status = FakeClient.statuses.get("next", "success")
        if status == "success":
            url = "https://fake.invalid/" + os.path.basename(FakeClient.results["next"])
            output = {"video_url": url, "draft_id": FakeClient.draft_id} if FakeClient.draft_id else url
            return {"status": "success", "output": output, "metrics": {"cost": 0.1}}
        return {"status": status}

    def cancel_prediction(self, prediction_id):
        FakeClient.log.append(("cancel", prediction_id))
        return {"status": "success"}

    def download(self, url, dest_path, cancel_event=None):
        shutil.copyfile(FakeClient.results["next"], dest_path)
        return "video/mp4" if FakeClient.results["next"].endswith(".mp4") else "image/png"


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
