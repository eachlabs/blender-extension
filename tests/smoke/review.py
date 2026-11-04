"""The visual check, the scene review and the camera candidates."""

import json
import math
import re
import threading
import types

import bpy

from eachlabs import chat_loop, preferences
from tests import blender_fakes
from tests.blender_fakes import CAMERA, CHECK, FakeLLM, STREET, code_reply, offline_api, text_reply, tool_reply
from tests.smoke.chat_common import _ScriptLLM, _chat_drive
from tests.smoke.common import _step, check


CANDIDATE_CODE = '''
root = bpy.data.objects.new("Cand Hut", None)
scene.collection.objects.link(root)
for name, x in (("Cand Hut wall", 0.0), ("Cand Hut door", 0.6)):
    m = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(m)
    bm.free()
    o = bpy.data.objects.new(name, m)
    scene.collection.objects.link(o)
    o.location = (x, 0, 0.5)
    attach(o, root)
'''


def test_candidates():
    """A stashed version of an object comes back in place, under its names, as the chat's own; stashes leave no
    trace."""
    from eachlabs import scene_build
    from eachlabs.chat import candidates

    scene = bpy.data.scenes.new("eachlabs_candidates_test")
    build = scene_build.SceneBuild(scene, "cand-run")
    try:
        check("candidates: the hut is built", _step(build, CANDIDATE_CODE).get("ok"))
        key = candidates.stash(build, "Cand Hut")
        door = scene.objects["Cand Hut door"]
        door.location.x = 5.0
        _step(build, 'm = bpy.data.meshes.new("x")\no = bpy.data.objects.new("Cand Hut roof", m)\n'
                     'scene.collection.objects.link(o)\nattach(o, bpy.data.objects["Cand Hut"])\n')
        candidates.restore(build, "Cand Hut", key)
        hut = scene.objects.get("Cand Hut")
        names = sorted(o.name for o in [hut] + list(hut.children_recursive)) if hut else []
        check("candidates: the stashed version is back under its names, parts in place, the chat's own",
              names == ["Cand Hut", "Cand Hut door", "Cand Hut wall"]
              and abs(scene.objects["Cand Hut door"].matrix_world.translation.x - 0.6) < 1e-4
              and all(build.owns(scene.objects[n]) for n in names), str(names))
        key2 = candidates.stash(build, "Cand Hut")
        _step(build, 'for o in list(bpy.data.objects):\n    if o.name.startswith("Cand Hut door"):\n'
                     '        bpy.data.objects.remove(o)\n')
        try:
            candidates.restore(build, "Cand Hut", key2)
            back = scene.objects.get("Cand Hut door") is not None
        except ValueError as exc:
            back = str(exc)
        check("candidates: a step that removes things by name prefix leaves the stashed copies alone", back is True,
              str(back))
        candidates.drop([key, key2])
        check("candidates: dropping the stash removes its scene and copies",
              bpy.data.scenes.get(candidates.STORE) is None
              and not [o for o in bpy.data.objects if o.name.startswith("Cand Hut") and not o.users_scene])
    finally:
        bpy.data.scenes.remove(scene)


def _png_size(url):
    """``(width, height)`` of a PNG ``data:`` URL, or ``None``."""
    import base64
    import struct

    prefix = "data:image/png;base64,"
    if not url.startswith(prefix):
        return None
    data = base64.b64decode(url[len(prefix):])
    return struct.unpack(">II", data[16:24]) if data[:8] == b"\x89PNG\r\n\x1a\n" else None


VISUAL_SETTINGS = (("render", "engine"), ("render", "resolution_x"), ("render", "resolution_y"),
                   ("render", "resolution_percentage"), ("render", "filepath"), ("render", "use_motion_blur"),
                   ("render", "film_transparent"), ("render", "use_compositing"), ("render.image_settings",
                   "file_format"), ("eevee", "taa_render_samples"), ("", "camera"), ("", "frame_current"))


def _visual_settings(scene):
    out = []
    for path, attr in VISUAL_SETTINGS:
        owner = scene
        for part in filter(None, path.split(".")):
            owner = getattr(owner, part)
        out.append(getattr(owner, attr))
    return tuple(out)


def test_visual_check():
    """The visual check renders small frames on the main thread, puts the scene's settings back, and the model sees
    each frame as a picture: after the layout, the light and the camera, and in the check."""
    from eachlabs import chat_run, scene_build, thread_safety, visual_check

    scene = bpy.data.scenes.new("eachlabs_visual")
    scene.render.engine = "CYCLES"
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1920, 1080, 50
    scene.render.filepath, scene.render.use_motion_blur, scene.render.film_transparent = "//keep/me", True, True
    scene.frame_current = 7
    build = scene_build.SceneBuild(scene, "visualcheck")
    mesh = bpy.data.meshes.new("Visual box")
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    bm.to_mesh(mesh)
    bm.free()
    box = bpy.data.objects.new("Visual box", mesh)
    scene.collection.objects.link(box)
    build.adopt(box)
    before = _visual_settings(scene)
    cameras = len(bpy.data.cameras)
    try:
        found = visual_check.render(build)
        check("visual: with no camera of the chat's, one overview frame of about 640 x 360",
              found.get("overview") is True and len(found["images"]) == 1
              and _png_size(found["images"][0]) == (640, 360), str({k: v for k, v in found.items() if k != "images"}))
        check("visual: the scene's render settings, camera and frame are put back, and the overview camera is gone",
              _visual_settings(scene) == before and len(bpy.data.cameras) == cameras
              and visual_check.OVERVIEW not in bpy.data.objects, "%s != %s" % (_visual_settings(scene), before))
        cam = bpy.data.objects.new("Visual cam", bpy.data.cameras.new("Visual cam"))
        scene.collection.objects.link(cam)
        build.adopt(cam)
        cam.location = (0, -12, 2)
        cam.rotation_euler = (math.radians(85), 0, 0)
        cam.keyframe_insert("location", frame=1)
        cam.location = (0, -8, 2)
        cam.keyframe_insert("location", frame=48)
        scene.frame_start, scene.frame_end, scene.camera = 1, 48, cam
        before = _visual_settings(scene)
        still = visual_check.render(build)
        moving = visual_check.render(build, moves=True)
        check("visual: the chat's camera, frame 1, and the middle and last frames too for a camera move",
              still["frames"] == [1] and not still["overview"] and moving["frames"] == [1, 24, 48]
              and all(_png_size(u) == (640, 360) for u in moving["images"]) and _visual_settings(scene) == before,
              "%s %s" % (still.get("frames"), moving.get("frames")))
        seconds = still["seconds"] + moving["seconds"]
        print("visual: render seconds %s" % seconds, flush=True)
        check("visual: a small frame renders in under 3 s", max(seconds) < 3.0, str(seconds))
        failing = visual_check.render(types.SimpleNamespace(scene=scene, owns=lambda _x: False,
                                                            frame_targets=lambda: []))
        check("visual: with nothing built yet there is no frame", failing["images"] == [] and failing["reason"])
    finally:
        bpy.data.scenes.remove(scene)

    # A chat run: the renders run on the main thread while the chat worker waits, and the model sees them.
    calls = []
    real_render, real_pref = visual_check.render, preferences.visual_check

    def watched(build, moves=False):
        calls.append({"main": threading.current_thread() is threading.main_thread(),
                      "worker": any(t.name == "eachlabs-chat" and t.is_alive() for t in threading.enumerate()),
                      "guarded": thread_safety.ops_override_unsafe() == thread_safety.override_races(),
                      "settings": _visual_settings(build.scene)})
        found = real_render(build, moves)
        calls[-1]["after"] = _visual_settings(build.scene)
        calls[-1]["frames"] = found.get("frames")
        return found

    visual_check.render = chat_run.visual_check.render = watched
    preferences.visual_check = lambda context=None: True
    scene = bpy.data.scenes.new("eachlabs_visual_run")
    context = types.SimpleNamespace(scene=scene, preferences=bpy.context.preferences)
    script = [code_reply(blender_fakes.LAYOUT_CODE), text_reply("Ground and two buildings."), text_reply("Fine."),
              code_reply(blender_fakes.MATERIALS_CODE), text_reply("Painted."),
              code_reply(blender_fakes.LIGHT_CODE), text_reply("Lit."), text_reply("Fine."),
              code_reply(blender_fakes.CAMERA_CODE), text_reply("A dolly."), text_reply("Fine."),
              tool_reply(("read_scene", {})), text_reply("A street at dusk.")]
    try:
        with offline_api() as client:
            llm = _ScriptLLM(script)
            client.chat_llm, client.balances = llm, [5.0, 4.9]
            chat_run.new_scene()
            chat_run.start(context, "a street at dusk")
            _chat_drive(60)
            pictures = [m for ms in llm.messages for m in ms if isinstance(m["content"], list)]
            sizes = [_png_size(p["image_url"]["url"]) for m in pictures for p in m["content"]
                     if p.get("type") == "image_url"]
            check("visual: four renders in a run, each on the main thread while the chat worker waits",
                  len(calls) == 4 and all(c["main"] and c["worker"] and c["guarded"] for c in calls),
                  str([{k: v for k, v in c.items() if k not in ("settings", "after")} for c in calls]))
            check("visual: every render puts the settings back", all(c["settings"] == c["after"] for c in calls))
            check("visual: the camera and the check stages see both ends and the middle of the dolly",
                  [c["frames"] for c in calls][2:] == [[1, 60, 120], [1, 60, 120]], str([c["frames"] for c in calls]))
            check("visual: the model gets each render as a PNG picture with the line",
                  len(sizes) >= 6 and all(s is not None for s in sizes)
                  and all(m["content"][0]["text"].startswith(chat_loop.LOOK) for m in pictures)
                  and chat_run.STATE.status == "done", "%s %s" % (sizes, chat_run.STATE.error))
            check("visual: the bar line is off after the run", chat_run.STATE.looking is False)
            check("visual: its rounds come on top of the round limit",
                  chat_run.STATE.total == preferences.chat_limits(context).total_rounds + chat_loop.LOOK_ROUNDS,
                  str(chat_run.STATE.total))
    finally:
        visual_check.render = chat_run.visual_check.render = real_render
        preferences.visual_check = real_pref
        chat_run.cancel(drop_build=True)
        chat_run.new_scene()
        bpy.data.scenes.remove(scene)
    import inspect
    check("visual: the render never uses temp_override (safe on Blender 4.2 during a chat run)",
          "temp_override" not in inspect.getsource(visual_check).split('"""', 2)[2])


REVIEW_FIX_CODE = '''# Bring Building A up to the street
for obj in scene.objects:
    if obj.name.startswith("Building A"):
        obj.location.x = -7.0
'''


def _review_reply(thing=None, fix="Move it one metre toward the street.", named=None):
    """A review answer on Building A (by its name in the list, which earlier tests may have numbered), or ``thing``."""
    def answer(messages):
        listed = re.search(r"^(Building A(?:\.\d+)?) \|", messages[1]["content"][0]["text"], re.MULTILINE)
        name = thing or (listed.group(1) if listed else "?")
        if named is not None:
            named.append(name)
        return json.dumps({"matches": False, "missing": ["a bus stop"], "problems": [
            {"thing": name, "what": "%s stands apart from the street." % name, "fix": fix}]})
    return answer


def test_scene_review():
    """After the check stage, the scene review judges the finished scene from four pictures; a problem it keeps gets
    one more fix stage whose request carries it, then a second look; nothing else changes the run."""
    from eachlabs import chat_run
    from eachlabs.chat import review_run

    real_pref, real_undo = preferences.scene_review, review_run.undo_fix
    undos = []

    def run(review, again=None, on=True, extra=()):
        preferences.scene_review = lambda context=None: on
        scene = bpy.data.scenes.new("eachlabs_review")
        scene.render.fps, scene.render.fps_base = 24, 1.0
        context = types.SimpleNamespace(scene=scene, preferences=bpy.context.preferences)
        with offline_api() as client:
            llm = FakeLLM(STREET + CAMERA + CHECK + [text_reply("A street at sunset.")] + list(extra))
            llm.review = review
            if again is not None:
                llm.again = again
            client.chat_llm, client.balances = llm, [5.0, 5.0]
            chat_run.new_scene()
            chat_run.start(context, "A street at sunset")
            ended = _chat_drive(90)
        fix_system = "This stage: fix what the add-on measured."  # the fix stage's system text, on any Blender
        fixes = [ms for ms in llm.messages if len(ms) == 2 and fix_system in ms[0]["content"]]
        building = next((o for o in scene.objects if o.name.startswith("Building A")), None)
        out = {"ended": ended, "llm": llm, "fixes": fixes, "x": building.location.x if building else None,
               "stages": dict(chat_run.STATE.stages), "reply": chat_run.STATE.reply, "cost": chat_run.STATE.cost_text}
        chat_run.new_scene()
        bpy.data.scenes.remove(scene)
        return out

    def watched_undo(run_):
        undos.append(1)
        return real_undo(run_)

    review_run.undo_fix = watched_undo
    try:
        named = []
        found = run(_review_reply(named=named), '{"solved": [true], "worse": false}',
                    extra=[code_reply(REVIEW_FIX_CODE), text_reply("Moved Building A.")])
        name = named[0] if named else "?"
        reviews = found["llm"].reviews
        pictures = [sum(p.get("type") == "image_url" for p in ms[1]["content"]) for ms in reviews]
        check("review: one review call with four pictures, then a second look with them before and after",
              found["ended"] and pictures == [4, 8], "%s %s %r" % (pictures, found["stages"], found["reply"]))
        asked = reviews[0][1]["content"][0]["text"] if reviews else ""
        check("review: the review call carries the request and the things by name",
              "A street at sunset" in asked and name.startswith("Building A"), asked[:300])
        request = found["fixes"][0][1]["content"] if found["fixes"] else ""
        check("review: a kept problem gets one extra fix stage whose request carries it",
              len(found["fixes"]) == 1 and "%s: %s stands apart from the street. Fix: Move it" % (name, name)
              in request and found["stages"].get("fix") == "done" and found["x"] == -7.0,
              "%d %s %s" % (len(found["fixes"]), found["stages"], request[-400:]))
        check("review: the check's reply stays, with the review's line after it",
              found["reply"].startswith("A street at sunset.")
              and "Review: %s stands apart from the street — fixed." % name in found["reply"]
              and "Moved Building A" not in found["reply"], found["reply"])
        check("review: its fix stage's rounds are counted", found["cost"].startswith("12 ROUNDS"), found["cost"])

        found = run(_review_reply("Building Z"), extra=[code_reply(REVIEW_FIX_CODE)])
        check("review: a problem on a name that is not a thing gets no fix stage and no line",
              found["ended"] and len(found["llm"].reviews) == 1 and not found["fixes"]
              and "fix" not in found["stages"] and "Review:" not in found["reply"] and found["x"] != -7.0,
              "%s %r" % (found["stages"], found["reply"]))
        found = run(_review_reply(fix="Remove it."), extra=[code_reply(REVIEW_FIX_CODE)])
        check("review: a fix that removes something is dropped", found["ended"] and not found["fixes"]
              and "Review:" not in found["reply"], found["reply"])

        found = run(_review_reply(), on=False, extra=[code_reply(REVIEW_FIX_CODE)])
        check("review: off, no review call is made and the run is as before",
              found["ended"] and found["llm"].reviews == [] and not found["fixes"]
              and found["cost"].startswith("10 ROUNDS"), "%d %s" % (len(found["llm"].reviews), found["cost"]))

        undos.clear()
        named = []
        found = run(_review_reply(named=named), '{"solved": [false], "worse": true}',
                    extra=[code_reply(REVIEW_FIX_CODE), text_reply("Moved Building A.")])
        name = named[0] if named else "?"
        check("review: worse after the fix asks to undo the fix stage, and says so (background mode has no undo)",
              len(found["fixes"]) == 1 and undos == [1]
              and "Review: %s stands apart from the street (not fixed). The fix made the scene worse and could "
              "not be undone." % name in found["reply"], found["reply"])
    finally:
        preferences.scene_review, review_run.undo_fix = real_pref, real_undo
    check("review: undo refuses in background mode, which has no undo steps",
          review_run.undo_fix(types.SimpleNamespace(build=types.SimpleNamespace(pushes=3), review_pushes=None))
          == {"undone": False, "reason": "background mode has no undo steps"})
