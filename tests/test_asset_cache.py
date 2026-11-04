import json
import os
import tempfile
import threading
import unittest

from eachlabs import asset_cache, generation, workflow_3d

from . import glb_fixture
from .test_generation import DONE, FakeClient


class CacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = os.path.join(self.tmp.name, "cache")

    def tearDown(self):
        for path in asset_cache.held():
            asset_cache.release(path)
        self.tmp.cleanup()

    def model(self, name="m.glb", size=1000):
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as fh:
            fh.write(b"g" * size)
        return path

    def test_key(self):
        self.assertEqual(asset_cache.key("  Red   1970s MUSCLE car "), "red 1970s muscle car")

    def test_put_then_get_by_key_and_tier(self):
        cache = asset_cache.Cache(self.folder)
        path = cache.put("Red car", "large", self.model(), version="v3", cost=0.45)
        self.assertTrue(os.path.isfile(path) and path.startswith(self.folder))
        hit = cache.get("  red CAR", "large")
        self.assertEqual(hit["path"], path)
        self.assertEqual((hit["prompt"], hit["workflow_version"], hit["cost"]), ("Red car", "v3", 0.45))
        self.assertTrue(hit["date"].endswith("Z"))
        self.assertIsNone(cache.get("red car", "medium"))
        self.assertIsNone(cache.get("blue car", "large"))
        self.assertTrue(cache.has("red car", "large"))
        with open(os.path.join(self.folder, asset_cache.INDEX)) as fh:
            self.assertEqual(len(json.load(fh)["entries"]), 1)

    def test_a_missing_file_is_a_miss(self):
        cache = asset_cache.Cache(self.folder)
        os.remove(cache.put("red car", "large", self.model()))
        self.assertIsNone(cache.get("red car", "large"))

    def test_the_same_key_replaces_the_old_model(self):
        cache = asset_cache.Cache(self.folder)
        first = cache.put("red car", "large", self.model("a.glb"))
        second = cache.put("red car", "large", self.model("b.glb"))
        self.assertFalse(os.path.exists(first))
        self.assertEqual(cache.get("red car", "large")["path"], second)

    def test_the_least_recently_used_go_over_the_limit(self):
        cache = asset_cache.Cache(self.folder, limit_bytes=2500)
        a = cache.put("a", "large", self.model("a.glb"))
        with open(os.path.splitext(a)[0] + "_tex0.png", "wb") as fh:  # a texture written beside it counts too
            fh.write(b"t" * 200)
        b = cache.put("b", "large", self.model("b.glb"))
        cache.get("a", "large")  # a is used again, so b is the oldest
        c = cache.put("c", "large", self.model("c.glb"))
        self.assertTrue(os.path.exists(a) and os.path.exists(c))
        self.assertFalse(os.path.exists(b))
        self.assertIsNone(cache.get("b", "large"))
        self.assertLessEqual(cache.size(), 2500 + 200)

    def test_a_file_a_job_holds_is_never_evicted(self):
        cache = asset_cache.Cache(self.folder, limit_bytes=2500)
        a = cache.put("a", "large", self.model("a.glb"), hold=True)  # a job is about to import it
        b = cache.put("b", "large", self.model("b.glb"))
        c = cache.put("c", "large", self.model("c.glb"))
        self.assertTrue(os.path.exists(a), "the oldest, but held")
        self.assertFalse(os.path.exists(b))
        self.assertTrue(os.path.exists(c))
        asset_cache.release(a)
        cache.put("d", "large", self.model("d.glb"))
        self.assertFalse(os.path.exists(a), "once let go it can go")

    def test_a_cache_hit_can_be_held_and_a_held_file_is_not_replaced_away(self):
        cache = asset_cache.Cache(self.folder)
        first = cache.put("red car", "large", self.model("a.glb"))
        hit = cache.get("red car", "large", hold=True)
        self.assertIn(os.path.normpath(hit["path"]), asset_cache.held())
        second = cache.put("red car", "large", self.model("b.glb"))
        self.assertTrue(os.path.exists(first), "the job holding it still imports it")
        self.assertEqual(cache.get("red car", "large")["path"], second)
        asset_cache.release(first)
        self.assertNotIn(os.path.normpath(first), asset_cache.held())

    def test_clear(self):
        cache = asset_cache.Cache(self.folder)
        cache.put("a", "large", self.model(size=3000))
        self.assertGreaterEqual(cache.clear(), 3000)
        self.assertEqual(cache.size(), 0)
        self.assertIsNone(cache.get("a", "large"))
        self.assertEqual(asset_cache.Cache(os.path.join(self.tmp.name, "none")).clear(), 0)

    def test_parallel_puts_keep_every_entry(self):
        cache = asset_cache.Cache(self.folder)
        paths = [self.model("m%d.glb" % i) for i in range(8)]
        threads = [threading.Thread(target=cache.put, args=("thing %d" % i, "large", p)) for i, p in enumerate(paths)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertTrue(all(cache.has("thing %d" % i, "large") for i in range(8)))


class WorkerCacheTest(unittest.TestCase):
    def test_a_finished_run_goes_into_the_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "cache")
            spec = generation.Spec("3d-1", "object", "Red car", "large", "k", "https://api.invalid", folder,
                                   os.path.join(tmp, "store.json"), poll_s=0.0, cache_folder=folder)
            events = []
            generation.run_object(spec, threading.Event(), events.append, FakeClient([DONE]),
                                  sleep=lambda s: False)
            self.assertEqual(events[-1]["state"], generation.READY)
            hit = asset_cache.Cache(folder).get("red car", workflow_3d.cache_tier("large"))
            self.assertEqual(hit["path"], events[-1]["path"])
            self.assertEqual((hit["cost"], hit["workflow_version"]), (0.45, "v4"))
            self.assertEqual(sorted(n for n in os.listdir(folder) if n.endswith(".glb")), [os.path.basename(hit["path"])])
