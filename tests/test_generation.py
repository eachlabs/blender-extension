import math
import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from eachlabs import api_client, asset_cache, generation, glb, thread_safety, workflow_3d

from . import glb_fixture


class GlbTest(unittest.TestCase):
    def test_reads_a_box_in_blender_axes(self):
        model = glb.read(glb_fixture.box_glb((2.0, 1.0, 0.5)))
        self.assertEqual(len(model.parts), 1)
        self.assertEqual(model.triangle_count, 12)
        low, high = model.bounds
        # glTF y (1.0, up) becomes Blender z; glTF z (0.5) becomes -y.
        self.assertEqual([round(high[i] - low[i], 4) for i in range(3)], [2.0, 0.5, 1.0])
        part = model.parts[0]
        self.assertEqual(len(part.uvs), 16)
        self.assertEqual(part.uvs[:2], [0.0, 1.0])  # v flipped
        self.assertEqual(model.materials[0].base_texture, 0)
        self.assertEqual(model.materials[0].mr_texture, 1)
        self.assertEqual(model.textures[0].mime, "image/png")

    def test_data_uri_images_and_their_real_type(self):
        model = glb.read(glb_fixture.box_glb(data_uri=True))
        self.assertTrue(all(t is not None and t.data.startswith(b"\x89PNG") for t in model.textures))
        self.assertEqual(glb.image_type(b"\xff\xd8\xff\xe0rest"), "image/jpeg")

    def test_only_png_and_jpeg_images_are_kept(self):
        self.assertEqual(glb.image_type(glb_fixture.png()), "image/png")
        for data in (b"GIF89a....", b"<svg xmlns=", b"\x89PNG fake", b"", None):
            self.assertIsNone(glb.image_type(data))
        good = glb_fixture.box_glb()
        model = glb.read(good)
        self.assertTrue(all(t is not None for t in model.textures))
        bad = good.replace(glb_fixture.png()[:8], b"GIF89a\0\0")  # every embedded PNG now reads as a GIF
        self.assertNotEqual(bad, good)
        model = glb.read(bad)
        self.assertTrue(model.textures and all(t is None for t in model.textures))  # dropped, the mesh stays
        self.assertEqual(model.triangle_count, 12)

    def test_root_node_transform(self):
        # Turned 90 degrees about glTF y and moved 3 along x.
        half = math.sqrt(0.5)
        model = glb.read(glb_fixture.box_glb((2.0, 1.0, 0.5), root={"rotation": [0, half, 0, half],
                                                                    "translation": [3, 0, 0]}))
        low, high = model.bounds
        self.assertEqual([round(high[i] - low[i], 4) for i in range(3)], [0.5, 2.0, 1.0])
        self.assertAlmostEqual((low[0] + high[0]) / 2, 3.0, places=4)

    def test_prefers_the_pbr_glb_in_a_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.zip")
            with open(path, "wb") as fh:
                fh.write(glb_fixture.model_zip((3.0, 1.0, 1.0)))
            model = glb.read(glb.glb_from_zip(path))
            low, high = model.bounds
            self.assertAlmostEqual(high[0] - low[0], 3.0, places=4)
            with open(path, "wb") as fh:
                fh.write(b"not a zip")
            with self.assertRaises(glb.GlbError):
                glb.glb_from_zip(path)

    def test_scale_to_the_chats_size_along_its_measure(self):
        bounds = ((-1.0, -0.25, 0.0), (1.0, 0.25, 1.5))  # 2 long, 0.5 deep, 1.5 tall
        self.assertAlmostEqual(glb.scale_for(bounds, 9.0, "height"), 6.0)  # 1.5 tall -> 9 m tall
        self.assertAlmostEqual(glb.scale_for(bounds, 4.5, "length"), 2.25)  # 2 long -> 4.5 m long
        self.assertAlmostEqual(glb.scale_for(bounds, 4.0), 2.0)  # no measure: the longest side
        self.assertEqual(glb.scale_for(((0, 0, 0), (0, 0, 0)), 3, "height"), 1.0)

    def test_the_base_ignores_stray_points_below_the_model(self):
        floor = [0.0] * 300 + [1.0] * 700  # wheels at 0, body above
        stray = [-0.3] * 3  # a smear under the car
        positions = [v for z in floor + stray for v in (0.0, 0.0, z)]
        model = glb.Model(parts=[glb.Part(positions, [0, 1, 2])])
        self.assertEqual(glb.base_height(model), 0.0)  # not -0.3
        self.assertEqual(glb.base_height(glb.Model(parts=[glb.Part([0, 0, 2.0, 0, 0, 3.0], [])])), 2.0)
        self.assertEqual(glb.base_height(glb.Model()), 0.0)

    def test_an_accessor_larger_than_its_data_is_refused(self):
        doc = {"bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 24, "byteStride": 12}],
               "accessors": [{"componentType": 5126, "type": "VEC3", "count": 2, "bufferView": 0},
                             {"componentType": 5126, "type": "VEC3", "count": 3, "bufferView": 0},
                             {"componentType": 5126, "type": "VEC3", "count": 10 ** 9},
                             {"componentType": 5126, "type": "VEC3", "count": 2},
                             {"componentType": 5126, "type": "VEC3", "count": "many", "bufferView": 0},
                             {"componentType": 5126, "type": "VEC3", "count": -1, "bufferView": 0}]}
        binary = bytes(24)
        self.assertEqual(glb.accessor(doc, binary, 0), [0.0] * 6)  # strided, fits
        self.assertEqual(glb.accessor(doc, binary, 3), [0] * 6)  # no buffer view, no larger than the data
        for index in (1, 2, 4, 5):  # past its view; a count the data cannot hold; not a count
            with self.subTest(index=index), self.assertRaises(glb.GlbError):
                glb.accessor(doc, binary, index)

    def test_a_zip_glb_over_the_cap_is_refused(self):
        self.assertEqual(glb.MAX_ZIP_GLB, 64 * 1024 * 1024)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "m.zip")
            with open(path, "wb") as fh:
                fh.write(glb_fixture.model_zip())
            with mock.patch.object(glb, "MAX_ZIP_GLB", 100), self.assertRaises(glb.GlbError):
                glb.glb_from_zip(path)

    def test_errors(self):
        for data in (b"", b"PK\x03\x04" + b"0" * 30, b"glTF" + (1).to_bytes(4, "little") + b"\0" * 12):
            with self.assertRaises(glb.GlbError):
                glb.read(data)


class FakeClient:
    """The workflow calls of the API client, scripted."""

    def __init__(self, polls, payload=None):
        self.polls = list(polls)
        self.payload = payload if payload is not None else glb_fixture.model_zip()
        self.triggered = []
        self.downloads = []
        self.lock = threading.Lock()

    def list_workflows(self):
        return [{"workflow_id": "wf", "name": workflow_3d.NAME}]

    def get_workflow(self, workflow_id):
        return {"workflow_id": "wf", "versions": [{"version_id": "v4", "definition": workflow_3d.definition()}]}

    def trigger_workflow(self, workflow_id, version, inputs):
        self.triggered.append((workflow_id, version, inputs))
        return "ex-1"

    def get_execution(self, execution_id, timeout=None):
        self.timeouts = getattr(self, "timeouts", []) + [timeout]
        item = self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]
        if isinstance(item, Exception):
            raise item
        return item

    def download(self, url, dest, cancel_event=None, max_bytes=None, wait_seconds=None):
        self.max_bytes = max_bytes
        self.wait_seconds = wait_seconds
        self.downloads.append(url)
        with open(dest, "wb") as fh:
            fh.write(self.payload)
        return "application/zip"


DONE = {"status": "completed", "total_cost": 0.45,
        "workflow_output": {"model_zip": "https://files.invalid/m.zip", "image": "https://files.invalid/i.png"}}


class WithoutPathsTest(unittest.TestCase):
    def test_home_and_temp_folders_are_not_sent(self):
        home = os.path.expanduser("~")
        text = generation.without_paths("OSError: [Errno 28] No space left: '%s/Library/eachlabs/3d-cache/x.glb'" % home)
        self.assertNotIn(home, text)
        self.assertIn("'~/Library/eachlabs/3d-cache/x.glb'", text)
        temp = os.path.join(tempfile.gettempdir(), "eachlabs-1", "m.zip")
        self.assertEqual(generation.without_paths("the model file could not be read (%s)" % temp),
                         "the model file could not be read (%s)" % os.path.join("<temp>", "eachlabs-1", "m.zip"))
        self.assertEqual(generation.without_paths("the provider refused it"), "the provider refused it")
        self.assertEqual(generation.without_paths(None), "")


class CountedWorkerTest(unittest.TestCase):
    def tearDown(self):
        thread_safety._gen_threads = 0

    def job(self):
        return generation.Job("3d-1", "object", "car", "red car", "large")

    def test_a_worker_is_counted_from_before_it_starts_until_it_returns(self):
        registry, inside, release = generation.Registry(), [], threading.Event()

        def worker(spec, cancel, emit, client):
            inside.append(thread_safety._gen_threads)
            release.wait(5)

        with mock.patch.object(thread_safety, "override_races", return_value=True):
            thread = registry.start(self.job(), None, worker)
            for _ in range(200):
                if inside:
                    break
                time.sleep(0.005)
            self.assertEqual(inside, [1])
            self.assertTrue(thread_safety.ops_override_unsafe())  # Blender 4.2's guard sees it
            release.set()
            thread.join(5)
            self.assertEqual(thread_safety._gen_threads, 0)
            self.assertFalse(thread_safety.ops_override_unsafe())

    def test_a_worker_that_raises_is_still_counted_out(self):
        def worker(spec, cancel, emit, client):
            raise RuntimeError("boom")

        with mock.patch.object(threading, "excepthook", lambda args: None):
            thread = generation.Registry().start(self.job(), None, worker)
            thread.join(5)
        self.assertEqual(thread_safety._gen_threads, 0)

    def test_a_thread_that_cannot_start_is_not_counted(self):
        with mock.patch.object(threading.Thread, "start", side_effect=RuntimeError("no thread")):
            with self.assertRaises(RuntimeError):
                generation.Registry().start(self.job(), None, lambda *a: None)
        self.assertEqual(thread_safety._gen_threads, 0)


class RunObjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.events = []
        self.cancel = threading.Event()
        self.now = [0.0]

    def tearDown(self):
        self.tmp.cleanup()

    def spec(self, **kw):
        values = dict(job_id="3d-1", kind="object", description="red car", tier="medium", api_key="k",
                      base_url="https://api.invalid", folder=os.path.join(self.tmp.name, "models"),
                      store_path=os.path.join(self.tmp.name, "store.json"), poll_s=4.0)
        values.update(kw)
        return generation.Spec(**values)

    def sleep(self, seconds):
        self.now[0] += seconds
        return self.cancel.is_set()

    def run_job(self, client, **kw):
        generation.run_object(self.spec(**kw), self.cancel, self.events.append, client, sleep=self.sleep,
                              clock=lambda: self.now[0])
        return self.events[-1]

    def test_the_model_download_uses_its_specs_wait_limit(self):
        client = FakeClient([DONE])
        self.run_job(client, download_s=45.0)
        self.assertEqual(client.wait_seconds, 45.0)

    def test_success_writes_the_pbr_glb_and_reports_the_cost(self):
        client = FakeClient([{"status": "running"}, {"status": "running"}, DONE])
        last = self.run_job(client)
        self.assertEqual(last["state"], generation.READY)
        self.assertEqual(last["cost"], 0.45)
        self.assertTrue(last["path"].endswith("3d-1.glb"))
        with open(last["path"], "rb") as fh:
            low, high = glb.read(fh.read()).bounds
        self.assertAlmostEqual(high[0] - low[0], 2.0, places=4)  # the PBR box, not the 1 m one
        self.assertEqual(client.triggered, [("wf", "v4", workflow_3d.inputs("red car", "medium"))])
        self.assertEqual(client.downloads, ["https://files.invalid/m.zip"])
        self.assertEqual(self.now[0], 12.0)  # three polls, 4 s apart
        self.assertEqual(client.timeouts, [generation.POLL_HTTP_S] * 3)  # short reads: Stop is seen soon
        self.assertEqual(client.max_bytes, 64 * 1024 * 1024)  # a model download is capped
        self.assertEqual([e["state"] for e in self.events], ["running", "downloading", "ready"])
        self.assertEqual(os.listdir(os.path.join(self.tmp.name, "models")), ["3d-1.glb"])

    def test_a_bare_glb_download(self):
        client = FakeClient([DONE], payload=glb_fixture.box_glb())
        self.assertEqual(self.run_job(client)["state"], generation.READY)

    def test_timeout(self):
        last = self.run_job(FakeClient([{"status": "running"}]), timeout_s=20)
        self.assertEqual(last["state"], generation.FAILED)
        self.assertIn("longer than", last["error"])
        self.assertTrue(last["left_running"])  # the run itself goes on at Eachlabs and may bill
        job = generation.Job("3d-1", "object", "car", "red car", "large")
        job.apply(last)
        self.assertTrue(job.left_running)
        failed = self.run_job(FakeClient([{"status": "failed", "error": "refused"}]))
        self.assertNotIn("left_running", failed)  # a run that failed is over

    def test_the_limit_counts_from_the_trigger(self):
        client = FakeClient([{"status": "running"}, {"status": "running"}, DONE])
        real = client.trigger_workflow

        def slow_trigger(*args):  # making or updating the workflow took long; it does not count
            self.now[0] += 500
            return real(*args)
        client.trigger_workflow = slow_trigger
        self.assertEqual(self.run_job(client, timeout_s=20)["state"], generation.READY)
        self.assertEqual(generation.TIMEOUT_S, 1200.0)

    def test_failed_run(self):
        failed = {"status": "failed", "step_outputs": {"make_3d": {"error": "provider refused the image"}}}
        last = self.run_job(FakeClient([failed]))
        self.assertEqual((last["state"], last["error"]), (generation.FAILED, "provider refused the image"))

    def test_transient_poll_errors_are_retried(self):
        client = FakeClient([api_client.ApiError("busy", status=503), DONE])
        self.assertEqual(self.run_job(client)["state"], generation.READY)

    def test_a_broken_zip_fails(self):
        last = self.run_job(FakeClient([DONE], payload=b"PK not really"))
        self.assertEqual(last["state"], generation.FAILED)
        self.assertEqual(os.listdir(os.path.join(self.tmp.name, "models")), [])

    def test_stop_while_polling(self):
        self.cancel.set()
        last = self.run_job(FakeClient([{"status": "running"}]))
        self.assertEqual(last["state"], generation.CANCELLED)


class QueueTest(unittest.TestCase):
    def job(self, name, tier, place, state=generation.QUEUED):
        return generation.Job(name, "object", name, name, tier, state=state,
                              priority=generation.priority(tier, place))

    def test_large_first_then_the_plans_order(self):
        jobs = [self.job("house", "medium", 1), self.job("garage", "medium", 2), self.job("car", "large", 3),
                self.job("tree", "large", 4)]
        order = []
        while True:
            job = generation.next_queued(jobs)
            if job is None:
                break
            order.append(job.name)
            job.state = generation.DONE
        self.assertEqual(order, ["car", "tree", "house", "garage"])

    def test_one_at_a_time(self):
        jobs = [self.job("car", "large", 0, generation.RUNNING), self.job("house", "large", 1)]
        self.assertIsNone(generation.next_queued(jobs))
        jobs[0].state = generation.DOWNLOADING
        self.assertIsNone(generation.next_queued(jobs))
        jobs[0].state = generation.READY  # being brought in: the next run may start
        self.assertIs(generation.next_queued(jobs), jobs[1])
        jobs[1].state = generation.CANCELLED
        self.assertIsNone(generation.next_queued(jobs))

    def test_a_texture_never_waits_behind_a_3d_object(self):
        texture = generation.Job("tex", "texture", "Wall", "brick", generation.TEXTURE_TIER)
        texture.state = generation.QUEUED
        jobs = [self.job("car", "large", 0, generation.RUNNING), texture]
        self.assertIs(generation.next_queued(jobs), texture)
        texture.state = generation.RUNNING
        jobs.append(self.job("house", "large", 1))
        self.assertIsNone(generation.next_queued(jobs))

    def test_time_counts_from_the_trigger(self):
        job = self.job("car", "large", 0)
        self.assertEqual(job.running_for, 0.0)
        job.apply({"state": generation.STARTING})
        self.assertEqual(job.running_for, 0.0)
        job.apply({"state": generation.RUNNING})
        self.assertIsNotNone(job.triggered)
        self.assertGreaterEqual(job.running_for, 0.0)


class RegistryTest(unittest.TestCase):
    def test_updates_apply_on_drain_and_ready_jobs_are_returned(self):
        registry = generation.Registry()
        job = registry.add(generation.Job("a", "object", "car", "red car", "large"))
        emit = registry.emitter("a")
        emit({"state": generation.RUNNING})
        self.assertEqual(job.state, generation.STARTING)
        self.assertEqual(registry.drain(), [])
        self.assertEqual(job.state, generation.RUNNING)
        emit({"state": generation.READY, "path": "/x.glb"})
        self.assertEqual(registry.drain(), [job])
        self.assertTrue(job.active)

    def test_cancel_ignores_later_updates(self):
        registry = generation.Registry()
        job = registry.add(generation.Job("a", "object", "car", "red car", "large"))
        self.assertTrue(registry.cancel("a"))
        self.assertTrue(job.cancel_event.is_set())
        registry.emitter("a")({"state": generation.READY, "path": "/x.glb"})
        self.assertEqual(registry.drain(), [])
        self.assertEqual(job.state, generation.CANCELLED)
        self.assertFalse(registry.cancel("a"))


class PictureClient:
    """A fake client for one prediction: polls in order, then a download of ``payload``."""

    def __init__(self, polls, payload=glb_fixture.png()):
        self.polls, self.payload = list(polls), payload
        self.created, self.downloads = [], []

    def create_prediction(self, model, values):
        self.created.append((model, values))
        return "pr-1"

    def get_prediction(self, prediction_id, timeout=None):
        item = self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]
        if isinstance(item, Exception):
            raise item
        return item

    def download(self, url, dest, cancel_event=None, max_bytes=None, wait_seconds=None):
        self.max_bytes = max_bytes
        self.wait_seconds = wait_seconds
        self.downloads.append(url)
        with open(dest, "wb") as fh:
            fh.write(self.payload)
        return "image/png"


class RunTextureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.events, self.cancel, self.now = [], threading.Event(), [0.0]

    def tearDown(self):
        self.tmp.cleanup()

    def run_job(self, client, **kw):
        values = dict(job_id="tex-1", kind="texture", description="weathered red brick",
                      tier=generation.TEXTURE_TIER, api_key="k", base_url="https://api.invalid",
                      folder=os.path.join(self.tmp.name, "tex"), store_path="", poll_s=2.0,
                      cache_folder=os.path.join(self.tmp.name, "cache"))
        values.update(kw)

        def sleep(seconds):
            self.now[0] += seconds
            return self.cancel.is_set()
        generation.run_texture(generation.Spec(**values), self.cancel, self.events.append, client, sleep=sleep,
                               clock=lambda: self.now[0])
        return self.events[-1]

    def test_a_texture_download_uses_its_specs_wait_limit(self):
        client = PictureClient([{"status": "success", "output": ["https://files.invalid/t.png"]}])
        self.run_job(client, download_s=33.0)
        self.assertEqual(client.wait_seconds, 33.0)

    def test_a_texture_download_waits_120_seconds_by_default(self):
        client = PictureClient([{"status": "success", "output": ["https://files.invalid/t.png"]}])
        self.run_job(client)
        self.assertEqual(client.wait_seconds, 120)

    def test_a_texture_not_done_by_its_wait_limit_fails(self):
        client = PictureClient([{"status": "running"}])
        last = self.run_job(client, timeout_s=30.0)
        self.assertEqual(last["state"], generation.FAILED)
        self.assertIn("longer than", last["error"])
        self.assertGreaterEqual(self.now[0], 30.0)
        self.assertLess(self.now[0], 40.0)

    def test_a_picture_that_is_not_png_or_jpeg_fails_and_leaves_no_file(self):
        client = PictureClient([{"status": "success", "output": ["https://files.invalid/t.png"]}],
                               payload=b"<html>not a picture</html>")
        last = self.run_job(client)
        self.assertEqual((last["state"], last["error"]), (generation.FAILED, "The picture is not a PNG or JPEG file"))
        self.assertEqual(os.listdir(os.path.join(self.tmp.name, "tex")), [])

    def test_a_texture_is_drawn_tileable_and_kept_in_the_cache(self):
        client = PictureClient([{"status": "processing"}, {"status": "success", "output": [
            "https://files.invalid/t.png"], "metrics": {"cost": 0.15}}])
        last = self.run_job(client)
        self.assertEqual((last["state"], last["cost"]), (generation.READY, 0.15))
        model, values = client.created[0]
        self.assertEqual(model, "nano-banana-pro")
        self.assertEqual((values["aspect_ratio"], values["resolution"], values["output_format"]), ("1:1", "1K", "png"))
        self.assertIn("seamless tileable texture of weathered red brick", values["prompt"])
        self.assertTrue(last["path"].startswith(os.path.join(self.tmp.name, "cache")) and last["path"].endswith(".png"))
        self.assertTrue(asset_cache.Cache(os.path.join(self.tmp.name, "cache")).has("weathered red brick",
                                                                                     generation.TEXTURE_TIER))
        self.assertEqual([e["state"] for e in self.events], [generation.RUNNING, generation.READY])
        self.assertEqual(client.max_bytes, 20 * 1024 * 1024)  # a picture download is capped

    def test_a_size_model_gets_an_image_size_instead_of_an_aspect_ratio(self):
        import threading

        client = PictureClient([{"status": "success", "output": ["https://files.invalid/c.png"]}])
        generation.draw(client, "a cozy room", self.tmp.name, "concept", threading.Event(), aspect="16:9",
                        sleep=lambda s: False, model="z-image-turbo-text-to-image")
        model, values = client.created[0]
        self.assertEqual(model, "z-image-turbo-text-to-image")
        self.assertEqual(values, {"prompt": "a cozy room", "image_size": "landscape_16_9", "num_images": 1,
                                  "output_format": "png"})

    def test_the_concept_prompt_carries_the_request(self):
        text = generation.concept_prompt("a street at  dusk")
        self.assertIn("A concept picture of this 3D scene", text)
        self.assertIn(": a street at dusk.", text)

    def test_a_failed_or_slow_picture(self):
        self.assertEqual(self.run_job(PictureClient([{"status": "failed", "error": "refused"}]))["error"], "refused")
        self.assertEqual(self.run_job(PictureClient([{"status": "processing"}]), timeout_s=10)["state"],
                         generation.FAILED)
