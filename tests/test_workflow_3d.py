import json
import os
import tempfile
import unittest

from eachlabs import workflow_3d
from eachlabs.api_client import EachlabsClient

from .fake_server import FakeServer


class WorkflowApi:
    """The workflow endpoints of the fake server, with workflows kept in memory."""

    def __init__(self, server):
        self.server = server
        self.workflows = {}  # id -> workflow, versions newest first
        self.deleted = set()
        self.triggers = []
        self.fail_trigger = []  # statuses the next triggers answer with
        self.count = 0
        server.route("GET", "/v1/workflows", lambda r: (200, {}, {"workflows": [
            {"workflow_id": w["workflow_id"], "name": w["name"], "created_at": w["created_at"]}
            for w in self.workflows.values()]}))
        server.route("POST", "/v1/workflows", self._create)

    def add(self, name, definition, versions=("v1",), status="active"):
        self.count += 1
        wid = "wf-%d" % self.count
        self.workflows[wid] = {"workflow_id": wid, "name": name, "status": status,
                               "created_at": "2026-10-30T10:%02d:00Z" % self.count,
                               "versions": [{"version_id": v, "definition": definition} for v in reversed(versions)]}
        self._routes(wid)
        return wid

    def _routes(self, wid):
        self.server.route("GET", "/v1/workflows/" + wid, lambda r: self._get(wid))
        self.server.route("POST", "/v1/workflows/trigger/%s/v1" % wid, lambda r: self._trigger(wid, "v1", r))
        for n in range(2, 6):
            self.server.route("PUT", "/v1/workflows/%s/versions/v%d" % (wid, n),
                              lambda r, n=n: self._put(wid, "v%d" % n, r))
            self.server.route("POST", "/v1/workflows/trigger/%s/v%d" % (wid, n),
                              lambda r, n=n: self._trigger(wid, "v%d" % n, r))

    def _get(self, wid):
        if wid in self.deleted:
            return 404, {}, {"error": "workflow not found"}
        return 200, {}, self.workflows[wid]

    def _create(self, request):
        body = request.json()
        wid = self.add(body["name"], body["definition"])
        return 201, {}, self.workflows[wid]

    def _put(self, wid, version, request):
        entry = {"version_id": version, "published": request.json()["published"],
                 "definition": request.json()["definition"]}
        self.workflows[wid]["versions"].insert(0, entry)
        return 200, {}, entry

    def _trigger(self, wid, version, request):
        if self.fail_trigger:
            return self.fail_trigger.pop(0), {}, {"error": "workflow not found"}
        if wid in self.deleted:
            return 404, {}, {"error": "workflow not found"}
        self.triggers.append((wid, version, request.json()["inputs"]))
        return 202, {}, {"execution_id": "ex-%d" % len(self.triggers)}


class EnsureTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer().__enter__()
        self.api = WorkflowApi(self.server)
        self.client = EachlabsClient("fake-key", base_url=self.server.url)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "config", "workflow-3d.json")
        self.store = workflow_3d.Store(self.path, self.server.url)

    def tearDown(self):
        self.server.__exit__()
        self.tmp.cleanup()

    def test_first_use_creates_the_workflow_and_stores_it(self):
        wid, version = workflow_3d.ensure(self.client, self.store)
        self.assertEqual((wid, version), ("wf-1", "v1"))
        created = self.server.find("POST", "/v1/workflows")[0].json()
        self.assertEqual(created["name"], workflow_3d.NAME)
        self.assertEqual(created["definition"]["metadata"]["addon"], workflow_3d.ADDON)
        self.assertEqual(created["definition"]["metadata"]["def"], workflow_3d.DEF)
        self.assertEqual(self.store.load(), {"workflow_id": "wf-1", "version": "v1", "def": workflow_3d.DEF})
        with open(self.path) as fh:
            self.assertNotIn("fake-key", fh.read())
        # The second run only reads the stored workflow.
        self.assertEqual(workflow_3d.ensure(self.client, self.store), ("wf-1", "v1"))
        self.assertEqual(len(self.server.find("POST", "/v1/workflows")), 1)
        self.assertEqual(len(self.server.find("GET", "/v1/workflows")), 1)

    def test_first_use_finds_its_own_workflow_by_name_and_marker(self):
        self.api.add(workflow_3d.NAME, {"metadata": {}})  # same name, someone else's
        self.api.add("Other", workflow_3d.definition())
        mine = self.api.add(workflow_3d.NAME, workflow_3d.definition())
        self.assertEqual(workflow_3d.ensure(self.client, self.store), (mine, "v1"))
        self.assertEqual(self.server.find("POST", "/v1/workflows"), [])

    def test_a_deleted_workflow_is_made_again(self):
        workflow_3d.ensure(self.client, self.store)
        self.api.deleted.add("wf-1")
        wid, version = workflow_3d.ensure(self.client, self.store)
        self.assertEqual((wid, version), ("wf-2", "v1"))
        self.assertEqual(self.store.load()["workflow_id"], "wf-2")

    def test_a_workflow_marked_deleted_is_made_again(self):
        old = self.api.add(workflow_3d.NAME, workflow_3d.definition(), status="deleted")
        self.store.save(old, "v1")
        wid, _version = workflow_3d.ensure(self.client, self.store)
        self.assertNotEqual(wid, old)

    def test_an_outdated_marker_gets_a_new_version(self):
        old = workflow_3d.definition()
        old["metadata"]["def"] = workflow_3d.DEF - 1
        wid = self.api.add(workflow_3d.NAME, old, versions=("v1", "v2"))
        self.store.save(wid, "v2")
        self.assertEqual(workflow_3d.ensure(self.client, self.store), (wid, "v3"))
        put = self.server.find("PUT", "/v1/workflows/%s/versions/v3" % wid)[0].json()
        self.assertTrue(put["published"])
        self.assertEqual(put["definition"]["metadata"]["def"], workflow_3d.DEF)
        self.assertEqual(self.store.load()["version"], "v3")

    def test_an_edited_workflow_gets_our_definition_as_a_new_version_before_it_runs(self):
        edited = workflow_3d.definition()  # the marker says it is ours and current
        edited["steps"][1]["model"] = "some-other-3d-model"
        edited["steps"][1]["params"]["num_inference_steps"] = 80
        wid = self.api.add(workflow_3d.NAME, edited, versions=("v1", "v2"))
        self.store.save(wid, "v2")
        execution, used, version = workflow_3d.trigger(self.client, self.store, workflow_3d.inputs("red car", "large"))
        self.assertEqual((used, version), (wid, "v3"))
        put = self.server.find("PUT", "/v1/workflows/%s/versions/v3" % wid)[0].json()
        self.assertEqual(put["definition"]["steps"], workflow_3d.definition()["steps"])
        self.assertEqual(self.api.triggers[-1][:2], (wid, "v3"))  # the run used our steps
        self.assertEqual(self.store.load()["version"], "v3")
        self.assertEqual(workflow_3d.ensure(self.client, self.store), (wid, "v3"))  # nothing new the next time
        self.assertEqual(len(self.server.find("PUT", "/v1/workflows/%s/versions/v4" % wid)), 0)

    def test_steps_compare_models_and_parameters(self):
        ours = {"definition": workflow_3d.definition()}
        self.assertTrue(workflow_3d.same_steps(ours))
        changed = workflow_3d.definition()
        changed["steps"][0]["params"]["resolution"] = "4K"
        self.assertFalse(workflow_3d.same_steps({"definition": changed}))
        extra = workflow_3d.definition()
        extra["steps"].append({"id": "upscale", "type": "model", "model": "x", "params": {}})
        self.assertFalse(workflow_3d.same_steps({"definition": extra}))
        self.assertFalse(workflow_3d.same_steps({}))

    def test_a_workflow_made_before_the_marker_is_updated(self):
        hand_made = {"metadata": {"created_by": workflow_3d.OLD_CREATED_BY}, "steps": []}
        wid = self.api.add(workflow_3d.NAME, hand_made, versions=("v1", "v2"))
        self.assertEqual(workflow_3d.ensure(self.client, self.store), (wid, "v3"))

    def test_trigger_404_makes_the_workflow_again_and_retries_once(self):
        workflow_3d.ensure(self.client, self.store)
        self.api.fail_trigger = [404]
        execution, wid, version = workflow_3d.trigger(self.client, self.store, {"prompt": "red car"})
        self.assertEqual((execution, wid, version), ("ex-1", "wf-2", "v1"))
        self.assertEqual(self.api.triggers, [("wf-2", "v1", {"prompt": "red car"})])
        self.assertEqual(self.store.load()["workflow_id"], "wf-2")

    def test_trigger_retries_only_once(self):
        workflow_3d.ensure(self.client, self.store)
        self.api.fail_trigger = [404, 404]
        with self.assertRaises(workflow_3d.ApiError):
            workflow_3d.trigger(self.client, self.store, {"prompt": "x"})
        self.assertEqual(len(self.server.find("POST", "/v1/workflows")), 2)

    def test_other_trigger_errors_are_not_retried(self):
        workflow_3d.ensure(self.client, self.store)
        self.api.fail_trigger = [402]
        with self.assertRaises(workflow_3d.ApiError) as caught:
            workflow_3d.trigger(self.client, self.store, {"prompt": "x"})
        self.assertEqual(caught.exception.status, 402)
        self.assertEqual(len(self.server.find("POST", "/v1/workflows")), 1)

    def test_the_store_keeps_one_entry_per_api_url(self):
        other = workflow_3d.Store(self.path, "https://api.example")
        other.save("prod-wf", "v4")
        workflow_3d.ensure(self.client, self.store)
        with open(self.path) as fh:
            data = json.load(fh)
        self.assertEqual(set(data["workflows"]), {"https://api.example", self.server.url})
        self.assertEqual(other.load()["workflow_id"], "prod-wf")

    def test_triggers_send_the_tier_inputs(self):
        workflow_3d.trigger(self.client, self.store, workflow_3d.inputs("red car", "medium"))
        self.assertEqual(self.api.triggers[0][2], {"prompt": "red car", "octree": 256,
                                                   "steps": workflow_3d.TIERS["medium"]["steps"]})

    def test_next_version(self):
        self.assertEqual(workflow_3d.next_version({"versions": [{"version_id": "v9"}, {"version_id": "v10"},
                                                                {"version_id": "draft"}]}), "v11")
        self.assertEqual(workflow_3d.next_version({}), "v1")


class DefinitionTest(unittest.TestCase):
    def test_steps_and_tier_inputs(self):
        d = workflow_3d.definition()
        draw, make = d["steps"]
        self.assertEqual((draw["model"], make["model"]), ("nano-banana-pro", "hunyuan-3d-v2-1"))
        self.assertIn("$.inputs.prompt", draw["params"]["prompt"])
        self.assertTrue(make["params"]["textured_mesh"])
        self.assertEqual(make["params"]["input_image_url"], "$.draw_image.primary")
        # Exactly one reference each, so the numbers keep their type.
        self.assertEqual(make["params"]["octree_resolution"], "$.inputs.octree")
        self.assertEqual(make["params"]["num_inference_steps"], "$.inputs.steps")
        props = d["input_schema"]["properties"]
        self.assertEqual(props["octree"]["type"], "number")
        self.assertEqual(props["steps"]["default_value"], workflow_3d.TIERS["large"]["steps"])
        self.assertEqual(d["metadata"]["output_mapping"], {"model_zip": "$.make_3d.primary",
                                                           "image": "$.draw_image.primary"})

    def test_the_chats_picture_prompt_is_the_input_and_the_workflow_adds_only_the_plain_background(self):
        prompt = workflow_3d.definition()["steps"][0]["params"]["prompt"]
        self.assertEqual(prompt, "$.inputs.prompt, plain white background, no floor, no shadow, no other objects")
        sent = workflow_3d.inputs("a mature oak tree, the whole tree from roots to crown, full size, no pot.", "medium")
        self.assertEqual(sent["prompt"], "a mature oak tree, the whole tree from roots to crown, full size, no pot")
        # What the picture model gets once the workflow puts the input in its sentence.
        self.assertEqual(prompt.replace("$.inputs.prompt", sent["prompt"]),
                         "a mature oak tree, the whole tree from roots to crown, full size, no pot, plain white "
                         "background, no floor, no shadow, no other objects")
        self.assertEqual(workflow_3d.DEF, 2)  # stored workflows get a new version with it
        self.assertEqual(workflow_3d.cache_tier("large"), "large-def2")

    def test_inputs_per_tier(self):
        self.assertEqual(workflow_3d.inputs("  red   car ", "large"),
                         {"prompt": "red car", "octree": 256, "steps": 30})
        self.assertEqual(workflow_3d.inputs("tree", "medium")["steps"], workflow_3d.TIERS["medium"]["steps"])
        self.assertEqual(workflow_3d.inputs("tree", "tiny"), workflow_3d.inputs("tree", "large"))

    def test_outputs(self):
        done = {"workflow_output": {"model_zip": "https://a/m.zip", "image": "https://a/i.png"}}
        self.assertEqual(workflow_3d.outputs(done), ("https://a/m.zip", "https://a/i.png"))
        older = {"workflow_output": {"glb": "https://a/m.zip"}, "step_outputs": {"draw_image": {"primary": "https://i"}}}
        self.assertEqual(workflow_3d.outputs(older), ("https://a/m.zip", "https://i"))
        self.assertEqual(workflow_3d.outputs({"output": "https://a/z.zip"}), ("https://a/z.zip", None))
        self.assertEqual(workflow_3d.outputs({}), (None, None))
