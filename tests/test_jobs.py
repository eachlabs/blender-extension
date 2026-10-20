import json
import os
import tempfile
import threading
import unittest

from eachlabs import jobs
from eachlabs.api_client import ApiError, Cancelled


class FakeClient:
    """Scripted stand-in for EachlabsClient. ``statuses`` are returned by successive polls."""

    def __init__(self, statuses, kind="prediction", on_poll=None):
        self.statuses = list(statuses)
        self.kind = kind
        self.on_poll = on_poll
        self.calls = []

    def upload_file(self, path, content_type, file_type, cancel_event=None):
        self.calls.append(("upload", os.path.basename(path), content_type, file_type))
        return "https://cdn.example/%s" % os.path.basename(path)

    def create_prediction(self, model, values):
        self.calls.append(("create", model, values))
        return "pred-1"

    def trigger_workflow(self, workflow_id, version_id, values):
        self.calls.append(("trigger", workflow_id, version_id, values))
        return "exec-1"

    def _poll(self, remote_id):
        self.calls.append(("poll", remote_id))
        if self.on_poll:
            self.on_poll(len([c for c in self.calls if c[0] == "poll"]))
        item = self.statuses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    get_prediction = _poll
    get_execution = _poll

    def cancel_prediction(self, remote_id):
        self.calls.append(("cancel", remote_id))
        return {"status": "success"}

    def download(self, url, dest_path, cancel_event=None):
        self.calls.append(("download", url))
        if cancel_event is not None and cancel_event.is_set():
            raise Cancelled()
        with open(dest_path, "wb") as handle:
            handle.write(b"data")
        return "video/mp4" if url.endswith("mp4") else "image/png"


class WorkerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        for name in ("set_first_frame.png", "set_last_frame.png", "set_clip.mp4", "set_still.png"):
            with open(os.path.join(self.dir, name), "wb") as handle:
                handle.write(b"x")
        self.events = []
        self.cancel = threading.Event()

    def tearDown(self):
        self.tmp.cleanup()

    def spec(self, **overrides):
        files = {role: {"path": os.path.join(self.dir, "set_%s.%s" % (role, "mp4" if role == "clip" else "png")),
                        "content_type": "video/mp4" if role == "clip" else "image/png",
                        "media": "video" if role == "clip" else "image"}
                 for role in ("first_frame", "last_frame", "clip", "still")}
        values = dict(
            job_id="job-1", action="VIDEO", target_kind="model", target_key="demo-first-last",
            target_label="Demo", output_dir=self.dir, base_input={"prompt": "orbit", "duration": 8},
            url_fields={"first_frame_url": ("first_frame", False), "refs": ("last_frame", True)},
            files=files, api_key="k", base_url="https://api.example", input_set_id="set")
        values.update(overrides)
        return jobs.JobSpec(**values)

    def run_job(self, spec, client):
        jobs.run(spec, self.cancel, self.events.append, client=client, sleep=lambda s: self.cancel.is_set())
        return self.events[-1]

    def states(self):
        return [e["state"] for e in self.events if "state" in e]


class SuccessTest(WorkerTestCase):
    def test_prediction_end_to_end(self):
        client = FakeClient([{"status": "starting"}, {"status": "processing"},
                             {"status": "success", "output": "https://cdn.example/out.mp4", "metrics": {"cost": 0.42}}])
        final = self.run_job(self.spec(), client)
        self.assertEqual(self.states(), ["UPLOADING", "SUBMITTING", "QUEUED", "RUNNING", "DOWNLOADING", "IMPORTING"])
        uploads = [c[1] for c in client.calls if c[0] == "upload"]
        self.assertEqual(uploads, ["set_first_frame.png", "set_last_frame.png"])  # Only bound roles.
        create = next(c for c in client.calls if c[0] == "create")
        self.assertEqual(create[2], {"prompt": "orbit", "duration": 8,
                                     "first_frame_url": "https://cdn.example/set_first_frame.png",
                                     "refs": ["https://cdn.example/set_last_frame.png"]})
        result = os.path.join(self.dir, "job-1_result_1.mp4")
        self.assertEqual(final["outputs"], [(result, "video")])
        self.assertEqual(final["cost"], 0.42)
        self.assertTrue(os.path.isfile(result))
        with open(os.path.join(self.dir, "job-1.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["remote_id"], "pred-1")
        self.assertEqual(manifest["status"], "succeeded")
        self.assertNotIn("k", json.dumps(manifest["input"]))
        self.assertTrue(all(e.get("uploaded") is None or set(e["uploaded"]) <= {"first_frame", "last_frame"}
                            for e in self.events))

    def test_keeps_draft_id_from_object_output(self):
        client = FakeClient([{"status": "success", "output": {
            "video_url": "https://cdn.example/draft.mp4", "draft_id": "draft-123"}, "metrics": {"cost": 0.7}}])
        final = self.run_job(self.spec(), client)
        self.assertEqual(final["extras"], {"draft_id": "draft-123"})
        with open(os.path.join(self.dir, "job-1.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["extras"], {"draft_id": "draft-123"})

    def test_reuses_uploaded_urls(self):
        client = FakeClient([{"status": "success", "output": ["https://cdn.example/a.png"]}])
        spec = self.spec(uploaded={"first_frame": "https://cdn.example/old1.png", "last_frame": "https://cdn.example/old2.png"})
        self.run_job(spec, client)
        self.assertFalse([c for c in client.calls if c[0] == "upload"])
        self.assertNotIn("UPLOADING", self.states())

    def test_workflow_uses_workflow_output_when_output_is_empty(self):
        client = FakeClient([{"status": "running"},
                             {"status": "completed", "output": None,
                              "workflow_output": {"video": "https://cdn.example/w.mp4"}, "total_cost": 1.5}])
        final = self.run_job(self.spec(target_kind="workflow", target_key="wf", version_id="v2"), client)
        trigger = next(c for c in client.calls if c[0] == "trigger")
        self.assertEqual(trigger[1:3], ("wf", "v2"))
        self.assertEqual(final["state"], "IMPORTING")
        self.assertEqual(final["cost"], 1.5)

    def test_transient_poll_errors_are_retried(self):
        client = FakeClient([ApiError("Network error: reset"), ApiError("busy", status=503),
                             {"status": "success", "output": "https://cdn.example/o.png"}])
        final = self.run_job(self.spec(), client)
        self.assertEqual(final["state"], "IMPORTING")
        self.assertTrue(any("Retrying" in e.get("message", "") for e in self.events))


class FailureTest(WorkerTestCase):
    def test_prediction_error_text_from_output(self):
        client = FakeClient([{"status": "error", "logs": None, "output": {
            "success": False, "error": "Execution failed", "error_message": "Input image is too small (min 300px)"}}])
        final = self.run_job(self.spec(), client)
        self.assertEqual(final, {"state": "FAILED", "error": "Input image is too small (min 300px)"})

    def test_prediction_error_text_as_bare_output(self):
        refusal = "The generated audio may be restricted by copyright. Adjust the input and retry."
        client = FakeClient([{"status": "error", "logs": None, "output": refusal, "metrics": {"cost": 0}}])
        final = self.run_job(self.spec(), client)
        self.assertEqual(final["error"], refusal)

    def test_workflow_error_cause(self):
        client = FakeClient([{"status": "failed", "error": "step_failed", "error_cause": "step2: provider timeout"}])
        final = self.run_job(self.spec(target_kind="workflow", target_key="wf", version_id="v1"), client)
        self.assertEqual(final["error"], "step2: provider timeout")

    def test_non_transient_poll_error_fails(self):
        client = FakeClient([ApiError("execution not found (HTTP 404)", status=404)])
        final = self.run_job(self.spec(), client)
        self.assertEqual(final, {"state": "FAILED", "error": "execution not found (HTTP 404)"})

    def test_success_without_files(self):
        client = FakeClient([{"status": "success", "output": {"text": "no url"}}])
        final = self.run_job(self.spec(), client)
        self.assertEqual(final["state"], "FAILED")
        self.assertIn("no downloadable file", final["error"])

    def test_missing_input_file(self):
        os.remove(os.path.join(self.dir, "set_first_frame.png"))
        final = self.run_job(self.spec(), FakeClient([]))
        self.assertEqual(final["state"], "FAILED")
        self.assertIn("first_frame is missing", final["error"])

    def test_remote_cancel(self):
        final = self.run_job(self.spec(), FakeClient([{"status": "cancelled"}]))
        self.assertEqual(final["state"], "CANCELLED")

    def test_timeout(self):
        clock = iter([0, 100, 4000]).__next__
        jobs.run(self.spec(timeout_seconds=60), self.cancel, self.events.append,
                 client=FakeClient([{"status": "processing"}] * 3), sleep=lambda s: False, clock=clock)
        self.assertEqual(self.events[-1]["state"], "FAILED")
        self.assertIn("Timed out", self.events[-1]["error"])

    def test_unexpected_exception_is_reported(self):
        client = FakeClient([])
        client.create_prediction = lambda *a: (_ for _ in ()).throw(KeyError("boom"))
        final = self.run_job(self.spec(), client)
        self.assertEqual(final["state"], "FAILED")
        self.assertIn("KeyError", final["error"])


class CancelTest(WorkerTestCase):
    def test_cancel_while_polling_cancels_prediction(self):
        client = FakeClient([{"status": "processing"}] * 5, on_poll=lambda n: n == 2 and self.cancel.set())
        final = self.run_job(self.spec(), client)
        self.assertEqual(final, {"state": "CANCELLED", "message": jobs.PREDICTION_CANCEL_NOTE})
        self.assertIn(("cancel", "pred-1"), client.calls)
        self.assertEqual(len([c for c in client.calls if c[0] == "poll"]), 2)  # Polling stopped.

    def test_cancel_workflow_only_stops_polling(self):
        client = FakeClient([{"status": "running"}] * 5, on_poll=lambda n: self.cancel.set())
        final = self.run_job(self.spec(target_kind="workflow", target_key="wf", version_id="v1"), client)
        self.assertEqual(final["message"], jobs.WORKFLOW_CANCEL_NOTE)
        self.assertFalse([c for c in client.calls if c[0] == "cancel"])

    def test_cancel_before_submit_sends_nothing(self):
        self.cancel.set()
        client = FakeClient([])
        final = self.run_job(self.spec(uploaded={"first_frame": "u1", "last_frame": "u2"}), client)
        self.assertEqual(final, {"state": "CANCELLED", "message": "Cancelled"})
        self.assertEqual(client.calls, [])

    def test_cancel_during_download(self):
        def cancel_then_download(url, dest, cancel_event=None):
            self.cancel.set()
            raise Cancelled()
        client = FakeClient([{"status": "success", "output": "https://cdn.example/o.mp4"}])
        client.download = cancel_then_download
        final = self.run_job(self.spec(), client)
        self.assertEqual(final["state"], "CANCELLED")


class RegistryTest(unittest.TestCase):
    def test_drain_applies_updates_and_returns_ready_jobs(self):
        registry = jobs.Registry()
        job = registry.add(jobs.Job("j1", "IMAGE", "Demo", "model"))
        emit = registry.emitter("j1")
        emit({"state": jobs.UPLOADING})
        emit({"uploaded": {"still": ("https://cdn/a.png", 1.0)}})
        emit({"state": jobs.IMPORTING, "outputs": [("/x.png", "image")]})
        ready = registry.drain()
        self.assertEqual(ready, [job])
        self.assertEqual(job.state, jobs.IMPORTING)
        self.assertEqual(job.uploaded, {"still": ("https://cdn/a.png", 1.0)})
        self.assertTrue(job.active)

    def test_cancel_marks_rendering_job_immediately(self):
        registry = jobs.Registry()
        job = registry.add(jobs.Job("j1", "VIDEO", "Demo", "model"))
        self.assertTrue(registry.cancel("j1", "Render cancelled"))
        self.assertEqual(job.state, jobs.CANCELLED)
        self.assertTrue(job.cancel_event.is_set())
        self.assertIsNotNone(job.finished)
        # Late worker updates for a finished job are ignored.
        registry.emitter("j1")({"state": jobs.UPLOADING})
        registry.drain()
        self.assertEqual(job.state, jobs.CANCELLED)
        self.assertFalse(registry.cancel("j1"))

    def test_cancel_running_job_waits_for_worker(self):
        registry = jobs.Registry()
        job = registry.add(jobs.Job("j1", "VIDEO", "Demo", "model", state=jobs.RUNNING))
        registry.cancel("j1")
        self.assertEqual(job.state, jobs.RUNNING)
        self.assertEqual(job.message, "Cancelling…")

    def test_prunes_old_finished_jobs(self):
        registry = jobs.Registry(keep=3)
        for i in range(5):
            registry.add(jobs.Job("j%d" % i, "IMAGE", "x", "model", state=jobs.DONE))
        self.assertEqual(list(registry.jobs), ["j2", "j3", "j4"])

    def test_threaded_start_reaches_importing(self):
        registry = jobs.Registry()
        job = registry.add(jobs.Job("j1", "IMAGE", "x", "model", state=jobs.UPLOADING))
        with tempfile.TemporaryDirectory() as folder:
            still = os.path.join(folder, "s_still.png")
            with open(still, "wb") as handle:
                handle.write(b"x")
            spec = jobs.JobSpec(job_id="j1", action="IMAGE", target_kind="model", target_key="m", target_label="x",
                                output_dir=folder, base_input={}, url_fields={"image_url": ("still", False)},
                                files={"still": {"path": still, "content_type": "image/png", "media": "image"}},
                                api_key="k", base_url="https://api.example", poll_interval=0.01)
            worker = registry.start(job, spec, client=FakeClient([{"status": "success", "output": "https://cdn/o.png"}]))
            worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(registry.drain(), [job])
            self.assertEqual(job.outputs[0][1], "image")

    def test_format_elapsed(self):
        self.assertEqual(jobs.format_elapsed(5), "0:05")
        self.assertEqual(jobs.format_elapsed(125), "2:05")
        self.assertEqual(jobs.format_elapsed(3725), "1:02:05")


if __name__ == "__main__":
    unittest.main()
