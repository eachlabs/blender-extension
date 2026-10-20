"""Capability filtering and binding, on synthetic catalog entries shaped like GET /v1/models rows."""

import unittest

from eachlabs import capabilities as caps


def model(slug, category, output_type, props, required=()):
    return {
        "slug": slug,
        "title": slug.replace("-", " ").title(),
        "output_type": output_type,
        "category": {"Slug": category, "Name": category},
        "request_schema": {"type": "object", "required": list(required), "properties": props},
    }


URI = {"type": "string", "format": "uri"}
URI_LIST = {"type": "array", "items": {"type": "string", "format": "uri"}}

EDIT = model("demo-image-edit", "image-to-image", "image",
             {"prompt": {"type": "string"}, "image_url": URI, "seed": {"type": "integer"},
              "strength": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.8}},
             required=("prompt", "image_url"))
TEXT_TO_IMAGE = model("demo-text-to-image", "text-to-image", "array",
                      {"prompt": {"type": "string"}, "image_prompt": URI})
FIRST_LAST = model("demo-first-last", "image-to-video", "video",
                   {"prompt": {"type": "string"}, "first_frame_url": URI, "last_frame_url": URI,
                    "duration": {"enum": [4, 6, 8, None], "type": "integer", "default": 8},
                    "generate_audio": {"type": ["boolean", "null"], "default": True}},
                   required=("prompt", "first_frame_url", "last_frame_url", "duration"))
SINGLE_I2V = model("demo-i2v", "image-to-video", "video",
                   {"prompt": {"type": ["string", "null"]}, "image_url": URI,
                    "aspect_ratio": {"type": "string", "enum": ["16:9", "9:16"]}})
V2V = model("demo-v2v", "video-to-video", "video", {"video_url": URI, "prompt": {"type": "string"}})
REFS = model("demo-refs", "reference-to-video", "video", {"prompt": {"type": "string"}, "reference_image_urls": URI_LIST})
NO_MEDIA = model("demo-t2v", "text-to-video", "video", {"prompt": {"type": "string"}})
UPSCALE = model("demo-upscale", "image-to-image", "object", {"image": URI})


class ModelTargetTest(unittest.TestCase):
    def test_parses_fields_params_prompt_and_seed(self):
        target = caps.model_target(EDIT)
        self.assertEqual(target.kind, caps.MODEL)
        self.assertEqual(target.output_kind, "image")
        self.assertEqual(target.input_kinds, frozenset({"image"}))
        self.assertEqual([f.name for f in target.fields], ["image_url"])
        self.assertTrue(target.fields[0].required)
        self.assertTrue(target.has_prompt and target.has_seed)
        self.assertEqual([(p.name, p.type) for p in target.params], [("strength", "float")])
        self.assertEqual(target.label, "Demo Image Edit [demo-image-edit]")

    def test_output_kind_falls_back_to_category(self):
        self.assertEqual(caps.model_target(TEXT_TO_IMAGE).output_kind, "image")
        self.assertEqual(caps.model_target(UPSCALE).output_kind, "image")

    def test_enum_drops_null_and_keeps_types(self):
        target = caps.model_target(FIRST_LAST)
        params = {p.name: p for p in target.params}
        self.assertEqual(params["duration"].type, "enum")
        self.assertEqual(params["duration"].choices, (4, 6, 8))
        self.assertEqual(params["generate_audio"].type, "bool")

    def test_nullable_prompt_is_still_a_prompt(self):
        self.assertTrue(caps.model_target(SINGLE_I2V).has_prompt)

    def test_array_uri_field(self):
        target = caps.model_target(REFS)
        self.assertTrue(target.fields[0].is_array)

    def test_string_category_and_missing_schema(self):
        target = caps.model_target({"slug": "x", "output_type": "video", "category": "image-to-video"})
        self.assertEqual(target.input_kinds, frozenset({"image"}))
        self.assertEqual(target.fields, [])


class OffersTest(unittest.TestCase):
    def offered(self, action, entries, show_all=False):
        return [e["slug"] for e in entries if caps.offers(caps.model_target(e), action, show_all)]

    def test_image_action(self):
        everything = [EDIT, TEXT_TO_IMAGE, FIRST_LAST, SINGLE_I2V, V2V, REFS, NO_MEDIA, UPSCALE]
        self.assertEqual(self.offered(caps.IMAGE, everything), ["demo-image-edit", "demo-upscale"])
        # Show-all admits image outputs with any URI input, whatever the category says.
        self.assertEqual(self.offered(caps.IMAGE, everything, show_all=True),
                         ["demo-image-edit", "demo-text-to-image", "demo-upscale"])

    def test_video_action(self):
        everything = [EDIT, FIRST_LAST, SINGLE_I2V, V2V, REFS, NO_MEDIA]
        self.assertEqual(self.offered(caps.VIDEO, everything),
                         ["demo-first-last", "demo-i2v", "demo-v2v", "demo-refs"])


class BindingTest(unittest.TestCase):
    def test_single_field_gets_the_primary_source(self):
        self.assertEqual(caps.default_bindings(caps.model_target(EDIT), caps.IMAGE), {"image_url": "still"})
        self.assertEqual(caps.default_bindings(caps.model_target(SINGLE_I2V), caps.VIDEO), {"image_url": "first_frame"})
        self.assertEqual(caps.default_bindings(caps.model_target(V2V), caps.VIDEO), {"video_url": "clip"})

    def test_ambiguous_targets_are_left_to_the_user(self):
        # Two URI fields: which is the last frame is not declared, so nothing is pre-selected.
        self.assertEqual(caps.default_bindings(caps.model_target(FIRST_LAST), caps.VIDEO), {})
        # "reference" does not say image or video.
        self.assertEqual(caps.default_bindings(caps.model_target(REFS), caps.VIDEO), {})

    def test_sources_per_action(self):
        self.assertEqual(caps.sources_for(caps.IMAGE), ["still", "file"])
        self.assertEqual(caps.sources_for(caps.VIDEO), ["clip", "first_frame", "last_frame", "file"])


class BuildInputTest(unittest.TestCase):
    def test_builds_request_with_urls_prompt_seed_and_defaults(self):
        target = caps.model_target(FIRST_LAST)
        values = caps.build_input(
            target,
            {"first_frame_url": "first_frame", "last_frame_url": "last_frame"},
            {"first_frame": "https://cdn/a.png", "last_frame": "https://cdn/b.png"},
            prompt="  orbit the cube  ", seed=7, params={"generate_audio": False})
        self.assertEqual(values, {
            "first_frame_url": "https://cdn/a.png",
            "last_frame_url": "https://cdn/b.png",
            "prompt": "orbit the cube",
            "generate_audio": False,
            "duration": 8,  # Required with a declared default.
        })  # No seed: the model has no seed field.
        self.assertEqual(caps.missing_required(target, values), [])

    def test_array_fields_wrap_urls_and_missing_required_is_reported(self):
        target = caps.model_target(REFS)
        values = caps.build_input(target, {"reference_image_urls": "first_frame"}, {"first_frame": "https://cdn/a.png"})
        self.assertEqual(values["reference_image_urls"], ["https://cdn/a.png"])
        target = caps.model_target(EDIT)
        values = caps.build_input(target, {}, {}, prompt="")
        self.assertEqual(caps.missing_required(target, values), ["image_url", "prompt"])

    def test_extra_inputs_override(self):
        target = caps.model_target(EDIT)
        values = caps.build_input(target, {"image_url": "still"}, {"still": "u"}, prompt="p",
                                  extra={"prompt": "from json", "custom": [1, 2]})
        self.assertEqual(values["prompt"], "from json")
        self.assertEqual(values["custom"], [1, 2])

    def test_bound_roles(self):
        self.assertEqual(caps.bound_roles({"a": "clip", "b": "", "c": "clip", "d": "last_frame"}), ["clip", "last_frame"])


WORKFLOW = {
    "workflow_id": "wf-1",
    "name": "Restyle shot",
    "categories": ["video"],
    "versions": [
        {"version_id": "v1", "status": "active", "published": True, "updated_at": "2026-01-01T00:00:00Z",
         "definition": {"input_schema": {"properties": {"old": {"type": "image"}}}}},
        {"version_id": "v2", "status": "active", "production": True, "updated_at": "2025-12-01T00:00:00Z",
         "definition": {"input_schema": {"properties": {
             "shot": {"type": "video", "required": True},
             "style": {"type": "image"},
             "prompt": {"type": "string", "required": True},
             "strength": {"type": "number", "default_value": 0.5}}}}},
        {"version_id": "v3", "status": "archived", "production": False, "updated_at": "2026-06-01T00:00:00Z"},
    ],
}


class WorkflowTest(unittest.TestCase):
    def test_production_version_wins(self):
        target = caps.workflow_target(WORKFLOW)
        self.assertEqual(target.version_id, "v2")
        self.assertEqual(target.kind, caps.WORKFLOW)
        self.assertEqual({f.name: f.media for f in target.fields}, {"shot": "video", "style": "image"})
        self.assertTrue(target.has_prompt)
        self.assertEqual(target.required, frozenset({"shot", "prompt"}))
        self.assertEqual(target.label, "Restyle shot [workflow]")

    def test_offers_and_bindings_use_declared_types(self):
        target = caps.workflow_target(WORKFLOW)
        self.assertTrue(caps.offers(target, caps.VIDEO))
        self.assertTrue(caps.offers(target, caps.IMAGE))
        self.assertEqual(caps.default_bindings(target, caps.VIDEO), {"shot": "clip", "style": "first_frame"})
        self.assertEqual(caps.default_bindings(target, caps.IMAGE), {"style": "still"})

    def test_latest_active_when_no_production(self):
        versions = [dict(v, production=False) for v in WORKFLOW["versions"]]
        self.assertEqual(caps.pick_version(versions)["version_id"], "v1")

    def test_no_definition(self):
        self.assertIsNone(caps.workflow_target({"workflow_id": "x", "versions": [{"version_id": "v1"}]}))

    def test_untyped_workflow_is_not_offered(self):
        detail = {"workflow_id": "w", "name": "n", "versions": [
            {"version_id": "v1", "production": True, "definition": {"input_schema": {"properties": {"url": {"type": "string"}}}}}]}
        self.assertFalse(caps.offers(caps.workflow_target(detail), caps.VIDEO))


SEEDANCE_LIKE = model("demo-reference", "reference-to-video", "video", {
    "prompt": {"type": "string"},
    "image_urls": {"type": ["array", "string", "null"], "items": {"type": ["string", "null"], "format": "uri-reference"}},
    "video_urls": {"type": ["array", "string", "null"], "items": {"type": ["string", "null"], "format": "uri-reference"}},
    "duration": {"type": "string", "enum": ["auto"] + [str(n) for n in range(4, 31)], "default": "auto"},
    "draft": {"type": "boolean", "default": False},
}, required=("prompt",))


class ReferenceModelTest(unittest.TestCase):
    def test_nullable_array_reference_fields_are_bindable(self):
        target = caps.model_target(SEEDANCE_LIKE)
        self.assertEqual({f.name: f.is_array for f in target.fields}, {"image_urls": True, "video_urls": True})
        self.assertTrue(caps.offers(target, caps.VIDEO))
        self.assertEqual(caps.default_bindings(target, caps.VIDEO), {})

    def test_file_sources_get_their_own_role(self):
        target = caps.model_target(SEEDANCE_LIKE)
        role = caps.file_role("image_urls")
        values = caps.build_input(target, {"video_urls": "clip", "image_urls": role},
                                  {"clip": "https://cdn/c.mp4", role: "https://cdn/style.png"}, prompt="p")
        self.assertEqual(values["image_urls"], ["https://cdn/style.png"])
        self.assertEqual(values["video_urls"], ["https://cdn/c.mp4"])
        self.assertIn(caps.FILE, caps.sources_for(caps.IMAGE))


class MatchDurationTest(unittest.TestCase):
    def test_string_enum_picks_covering_value(self):
        target = caps.model_target(SEEDANCE_LIKE)
        self.assertEqual(caps.match_duration(target, 10.0), ("duration", "10"))
        self.assertEqual(caps.match_duration(target, 9.2), ("duration", "10"))
        self.assertEqual(caps.match_duration(target, 2.0), ("duration", "4"))
        self.assertEqual(caps.match_duration(target, 45.0), ("duration", "30"))
        self.assertEqual(caps.match_duration(target, 10.04), ("duration", "10"))

    def test_integer_enum_and_numeric(self):
        self.assertEqual(caps.match_duration(caps.model_target(FIRST_LAST), 5.5), ("duration", 6))
        self.assertEqual(caps.match_duration(caps.model_target(FIRST_LAST), 6.5), ("duration", 8))
        numeric = model("n", "image-to-video", "video", {"image_url": URI, "duration": {"type": "integer", "minimum": 3, "maximum": 12}})
        self.assertEqual(caps.match_duration(caps.model_target(numeric), 2.2), ("duration", 3))
        self.assertEqual(caps.match_duration(caps.model_target(numeric), 7.6), ("duration", 8))

    def test_no_duration_input(self):
        self.assertIsNone(caps.match_duration(caps.model_target(V2V), 10))


if __name__ == "__main__":
    unittest.main()
