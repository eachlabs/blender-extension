import os
import tempfile
import threading
import unittest

from eachlabs import jobs
from eachlabs.api_client import ApiError, Cancelled
from eachlabs.shot import models, prompts, worker


def _done(url, cost):
    return {"status": "success", "output": url, "metrics": {"cost": cost}}


class FakeClient:
    """Scripted stand-in for EachlabsClient, modelled on ``tests/test_jobs.py``. Each prediction id has its own
    list of statuses: ``photo-1``, ``photo-2``… for the photos in creation order, ``video-1`` for the video."""

    def __init__(self, results, on_poll=None):
        self.results = {key: list(value) for key, value in results.items()}
        self.on_poll = on_poll
        self.calls = []
        self.created = 0

    def upload_file(self, path, content_type, file_type, cancel_event=None):
        self.calls.append(("upload", os.path.basename(path), content_type, file_type))
        return "https://cdn.example/%s" % os.path.basename(path)

    def create_prediction(self, model, values):
        self.calls.append(("create", model, values))
        kind = "video" if model == models.VIDEO["slug"] else "photo"
        count = len([c for c in self.calls if c[0] == "create" and (c[1] == models.VIDEO["slug"]) == (kind == "video")])
        return "%s-%d" % (kind, count)

    def get_prediction(self, remote_id, timeout=None):
        self.calls.append(("poll", remote_id))
        if self.on_poll:
            self.on_poll(remote_id)
        item = self.results[remote_id].pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def cancel_prediction(self, remote_id):
        self.calls.append(("cancel", remote_id))
        return {"status": "success"}

    def download(self, url, dest_path, cancel_event=None):
        self.calls.append(("download", url))
        if cancel_event is not None and cancel_event.is_set():
            raise Cancelled()
        with open(dest_path, "wb") as handle:
            handle.write(b"data")
        return "video/mp4"


class ShotWorkerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        for name in ("clip.mp4", "render1.png", "render2.png"):
            with open(os.path.join(self.dir, name), "wb") as handle:
                handle.write(b"x")
        self.events = []
        self.cancel = threading.Event()

    def tearDown(self):
        self.tmp.cleanup()

    def spec(self, **overrides):
        values = dict(
            job_id="shot-1", output_dir=self.dir, clip_path=os.path.join(self.dir, "clip.mp4"),
            render_paths=[os.path.join(self.dir, "render1.png"), os.path.join(self.dir, "render2.png")],
            times=[0.0, 6.0], person="sunset", aspect="16:9", resolution="720p", seconds=10,
            api_key="k", base_url="https://api.example", user_agent="test")
        values.update(overrides)
        return worker.ShotSpec(**values)

    def happy(self):
        return {"photo-1": [{"status": "processing"}, _done("https://out/p1.jpg", 0.045)],
                "photo-2": [_done("https://out/p2.jpg", 0.045)],
                "video-1": [{"status": "processing"}, _done("https://out/v.mp4", 3.05)]}

    def run_worker(self, client, spec=None):
        worker.run(spec or self.spec(), self.cancel, self.events.append, client=client,
                   sleep=lambda s: self.cancel.is_set())

    def creates(self, client):
        return [c for c in client.calls if c[0] == "create"]

    def test_happy_path_order(self):
        client = FakeClient(self.happy())
        self.run_worker(client)
        self.assertEqual([c[0] for c in client.calls if c[0] in ("upload", "create")], ["upload"] * 3 + ["create"] * 3)
        self.assertEqual([c[1] for c in client.calls if c[0] == "upload"], ["clip.mp4", "render1.png", "render2.png"])
        self.assertEqual([c[1] for c in self.creates(client)], [models.PHOTO["slug"]] * 2 + [models.VIDEO["slug"]])
        self.assertEqual([c for c in client.calls if c[0] == "download"], [("download", "https://out/v.mp4")])
        last = self.events[-1]
        self.assertEqual(last["state"], jobs.IMPORTING)
        self.assertEqual(len(last["outputs"]), 1)
        path, kind = last["outputs"][0]
        self.assertEqual(kind, "video")
        self.assertTrue(os.path.isfile(path))

    def test_emits_progress_and_uploads(self):
        client = FakeClient(self.happy())
        self.run_worker(client)
        self.assertEqual(self.events[0]["state"], jobs.UPLOADING)
        uploaded = {}
        for event in self.events:
            uploaded.update(event.get("uploaded", {}))
        self.assertEqual({key: url for key, (url, _stamp) in uploaded.items()},
                         {"clip": "https://cdn.example/clip.mp4", "render1": "https://cdn.example/render1.png",
                          "render2": "https://cdn.example/render2.png"})
        messages = [e["message"] for e in self.events if e.get("state") == jobs.RUNNING and "message" in e]
        self.assertEqual(messages, ["Making the look (1 of 2)", "Making the look (2 of 2)", "Seedance 2.5 is making it"])
        self.assertIn({"remote_id": "video-1"}, self.events)

    def test_photo_input(self):
        client = FakeClient(self.happy())
        self.run_worker(client)
        photos = [c[2] for c in self.creates(client)[:2]]
        self.assertEqual(photos[0], {"prompt": prompts.photo_prompt("sunset"), "image": ["https://cdn.example/render1.png"],
                                     "aspect_ratio": "16:9", "resolution": "1.5K", "output_format": "jpeg"})
        self.assertEqual(photos[1]["image"], ["https://cdn.example/render2.png"])

    def test_video_input(self):
        client = FakeClient(self.happy())
        self.run_worker(client)
        video_input = self.creates(client)[-1][2]
        self.assertEqual(video_input, {
            "prompt": prompts.video_prompt([0.0, 6.0], "sunset"), "video_urls": ["https://cdn.example/clip.mp4"],
            "image_urls": ["https://out/p1.jpg", "https://out/p2.jpg"], "resolution": "720p", "duration": "10",
            "aspect_ratio": "16:9", "generate_audio": True})

    def test_reuses_uploaded(self):
        client = FakeClient(self.happy())
        self.run_worker(client, self.spec(uploaded={"clip": "https://cdn.example/old-clip.mp4"}))
        self.assertEqual([c[1] for c in client.calls if c[0] == "upload"], ["render1.png", "render2.png"])
        self.assertEqual(self.creates(client)[-1][2]["video_urls"], ["https://cdn.example/old-clip.mp4"])

    def test_photo_failure_stops_before_video(self):
        client = FakeClient({"photo-1": [{"status": "processing"}, {"status": "failed", "output": "Blocked by filter"}],
                             "photo-2": [{"status": "processing"}] * 3})
        self.run_worker(client)
        self.assertEqual(self.events[-1], {"state": jobs.FAILED, "error": "Photo 1 failed: Blocked by filter"})
        self.assertNotIn(models.VIDEO["slug"], [c[1] for c in self.creates(client)])
        self.assertIn(("cancel", "photo-2"), client.calls)

    def test_stop_during_photos(self):
        def on_poll(remote_id):
            self.cancel.set()

        client = FakeClient({"photo-1": [{"status": "processing"}], "photo-2": [{"status": "processing"}]},
                            on_poll=on_poll)
        self.run_worker(client)
        self.assertEqual([c for c in client.calls if c[0] == "cancel"], [("cancel", "photo-1"), ("cancel", "photo-2")])
        self.assertEqual(self.events[-1], {"state": jobs.CANCELLED, "message": jobs.PREDICTION_CANCEL_NOTE})
        self.assertNotIn(models.VIDEO["slug"], [c[1] for c in self.creates(client)])

    def test_stop_during_video_cancels_it(self):
        def on_poll(remote_id):
            if remote_id == "video-1":
                self.cancel.set()

        results = self.happy()
        results["video-1"] = [{"status": "processing"}]
        client = FakeClient(results, on_poll=on_poll)
        self.run_worker(client)
        self.assertEqual([c for c in client.calls if c[0] == "cancel"], [("cancel", "video-1")])
        self.assertEqual(self.events[-1], {"state": jobs.CANCELLED, "message": jobs.PREDICTION_CANCEL_NOTE})

    def test_cost_sums_photos_and_video(self):
        client = FakeClient(self.happy())
        self.run_worker(client)
        self.assertAlmostEqual(self.events[-1]["cost"], 3.14)

    def test_missing_render_fails(self):
        os.remove(os.path.join(self.dir, "render2.png"))
        client = FakeClient(self.happy())
        self.run_worker(client)
        self.assertEqual(self.events[-1]["state"], jobs.FAILED)
        self.assertEqual(self.creates(client), [])

    def test_transient_poll_error_retries(self):
        results = self.happy()
        results["photo-1"].insert(0, ApiError("busy", status=503))
        client = FakeClient(results)
        self.run_worker(client)
        self.assertEqual(self.events[-1]["state"], jobs.IMPORTING)

    def test_video_without_file_fails(self):
        results = self.happy()
        results["video-1"] = [{"status": "success", "output": None, "metrics": {"cost": 3.05}}]
        client = FakeClient(results)
        self.run_worker(client)
        self.assertEqual(self.events[-1], {"state": jobs.FAILED, "error": "The video finished without a file"})
        self.assertEqual([c for c in client.calls if c[0] == "download"], [])
        self.assertNotIn(jobs.IMPORTING, [e.get("state") for e in self.events])

    def test_unexpected_error_cancels_running_photos(self):
        def on_poll(remote_id):
            raise ValueError("bad reply")

        client = FakeClient({"photo-1": [{"status": "processing"}], "photo-2": [{"status": "processing"}]},
                            on_poll=on_poll)
        self.run_worker(client)
        self.assertEqual([c for c in client.calls if c[0] == "cancel"], [("cancel", "photo-1"), ("cancel", "photo-2")])
        self.assertEqual(self.events[-1], {"state": jobs.FAILED, "error": "ValueError: bad reply"})
        self.assertNotIn(models.VIDEO["slug"], [c[1] for c in self.creates(client)])

    def test_second_photo_failure_names_it(self):
        client = FakeClient({"photo-1": [{"status": "processing"}] * 3,
                             "photo-2": [{"status": "failed", "output": "Blocked by filter"}]})
        self.run_worker(client)
        self.assertEqual(self.events[-1], {"state": jobs.FAILED, "error": "Photo 2 failed: Blocked by filter"})
        self.assertIn(("cancel", "photo-1"), client.calls)

    def test_video_failure_text_unchanged(self):
        results = self.happy()
        results["video-1"] = [{"status": "failed", "output": "Too many people"}]
        client = FakeClient(results)
        self.run_worker(client)
        self.assertEqual(self.events[-1], {"state": jobs.FAILED, "error": "Too many people"})


if __name__ == "__main__":
    unittest.main()
