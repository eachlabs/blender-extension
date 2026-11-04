"""Play through a camera and Final render."""

import os
import types

import bpy
import mathutils

from tests.smoke.common import WORK, _step, check


def test_final_render():
    """Final render renders the chat's scene with Cycles, saves the picture, and puts the render settings back."""
    from eachlabs import chat_run, preferences, scene_build

    os.environ[preferences.USER_DIR_ENV] = os.path.join(WORK, "user")
    scene = bpy.data.scenes.new("eachlabs_final")
    build = scene_build.SceneBuild(scene, "final-run")
    old_build = chat_run._build
    try:
        _step(build, "import bmesh\nmesh = bpy.data.meshes.new('Dog')\nbm = bmesh.new()\n"
                     "bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=8, radius=0.3)\nbm.to_mesh(mesh)\n"
                     "dog = bpy.data.objects.new('Dog', mesh)\nscene.collection.objects.link(dog)\n"
                     "dog.location = (0, 0, 0.3)\nthing(dog, 'dog', '')\n"
                     "cam = bpy.data.objects.new('Cam', bpy.data.cameras.new('Cam'))\n"
                     "scene.collection.objects.link(cam)\nscene.camera = cam\ncam.location = (0, -3, 0.6)\n"
                     "cam.rotation_euler = (1.45, 0, 0)\n")
        build.subjects = ["dog"]
        scene.render.engine = "BLENDER_EEVEE_NEXT" if bpy.app.version < (5, 0, 0) else "BLENDER_EEVEE"
        scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 64, 48, 100
        chat_run._build = build
        chat_run.STATE.final_render = ""
        result = bpy.ops.eachlabs.chat_final_render()
        state, path = chat_run.STATE.final_render, chat_run.STATE.final_path
        check("final render: saved as untitled-final.png in the add-on's folder, settings put back",
              result == {"FINISHED"} and state == "saved" and os.path.isfile(path)
              and os.path.basename(path).startswith("untitled-final") and scene.render.engine != "CYCLES"
              and not scene.camera.data.dof.use_dof,
              "%s %s %r %s %s" % (result, state, path, scene.render.engine, chat_run.STATE.final_error))
    finally:
        chat_run._build = old_build
        chat_run.STATE.final_render = ""
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)


def test_play_through_camera():
    """Play through a chosen camera: the view looks through it and the scene camera is it while playing; Pause, or
    playback stopping any other way, puts both back. A scene without a camera plays as before."""
    from eachlabs import chat_run, scene_build
    from eachlabs.chat import playback

    check("play: the playback handlers are registered",
          playback._on_play in bpy.app.handlers.animation_playback_pre
          and playback._on_stop in bpy.app.handlers.animation_playback_post)
    scene = bpy.data.scenes.new("eachlabs_play")
    build = scene_build.SceneBuild(scene, "play-run")
    old = chat_run._build, chat_run.STATE.play_camera, playback._play_op, playback._cancel_op
    is_playing = playback.is_playing
    played, cancelled = [], []
    try:
        person = bpy.data.objects.new("Person cam", bpy.data.cameras.new("Person cam"))
        scene.collection.objects.link(person)
        scene.camera = person
        scene.frame_start, scene.frame_end, scene.render.fps = 1, 120, 24
        _step(build, "cam = bpy.data.objects.new('Chat cam', bpy.data.cameras.new('Chat cam'))\n"
                     "scene.collection.objects.link(cam)\nthing(cam, 'camera', '')\n"
                     "cam.location = (0, -10, 2)\ncam.keyframe_insert('location', frame=1)\n"
                     "cam.location = (0, -4, 2)\ncam.keyframe_insert('location', frame=120)\n")
        chat_run._build, chat_run.STATE.play_camera = build, ""
        playback._play_op = lambda context, area: played.append(context.scene.camera.name if context.scene.camera
                                                                else None)
        playback._cancel_op = lambda context: cancelled.append(True)
        items = playback.menu(scene)
        check("play: the chat's camera comes first and is chosen, with its move's length; the other is still",
              items == [("Chat cam", "the chat's camera move · 5 s", True), ("Person cam", "still", False)],
              repr(items))
        view = types.SimpleNamespace(view_perspective="PERSP", view_location=mathutils.Vector((1, 2, 3)),
                                     view_rotation=mathutils.Quaternion((1, 0, 0, 0)), view_distance=9.0,
                                     view_camera_zoom=0.0, view_camera_offset=(0.0, 0.0))
        context = types.SimpleNamespace(scene=scene, area=None, screen=None, window=None)
        playback.play(context, playback.chosen(scene), region_3d=view)
        check("play: Play as the chat's camera looks through it, makes it the scene camera and plays",
              scene.camera.name == "Chat cam" and view.view_perspective == "CAMERA" and played == ["Chat cam"],
              "%s %s %s" % (scene.camera.name, view.view_perspective, played))
        view.view_location = mathutils.Vector((0, 0, 0))  # the camera view moved the view
        for handler in list(bpy.app.handlers.animation_playback_post):
            if handler is playback._on_stop:
                handler(scene, None)  # playback stopped another way: Esc, Space or the timeline
        check("play: playback stopping any other way puts the view and the scene camera back",
              scene.camera.name == "Person cam" and view.view_perspective == "PERSP"
              and tuple(view.view_location) == (1, 2, 3) and view.view_distance == 9.0 and not chat_run._play_saved,
              "%s %s %s" % (scene.camera.name, view.view_perspective, tuple(view.view_location)))
        with bpy.context.temp_override(scene=scene):
            bpy.ops.eachlabs.chat_play_camera(camera="Person cam")
        check("play: choosing a camera in the menu makes it Play's camera",
              chat_run.STATE.play_camera == "Person cam" and playback.chosen(scene) == "Person cam"
              and [c for _n, _h, c in playback.menu(scene)] == [False, True], chat_run.STATE.play_camera)
        scene.camera = None
        playback.play(context, playback.chosen(scene), region_3d=view)
        during = (scene.camera.name if scene.camera else None, view.view_perspective)
        playback.is_playing = lambda context=None: True  # a background Blender has no screen that plays
        try:
            bpy.ops.eachlabs.chat_play()  # Pause while it plays
        finally:
            playback.is_playing = is_playing
        check("play: Pause stops playback and puts back a scene camera that was none and the view",
              during == ("Person cam", "CAMERA") and cancelled == [True] and scene.camera is None
              and view.view_perspective == "PERSP", "%s %s %s %s" % (during, cancelled, scene.camera,
                                                                    view.view_perspective))
        empty = bpy.data.scenes.new("eachlabs_play_empty")
        try:
            plain = types.SimpleNamespace(scene=empty, area=None, screen=None, window=None)
            played.clear()
            playback.play(plain, playback.chosen(empty), region_3d=view)
            check("play: a scene without a camera plays as before: no view switch, nothing to put back",
                  playback.menu(empty) == [] and played == [None] and view.view_perspective == "PERSP"
                  and not chat_run._play_saved and playback.restore() is False, "%s %s" % (played, chat_run._play_saved))
        finally:
            bpy.data.scenes.remove(empty)
    finally:
        chat_run._build, chat_run.STATE.play_camera, playback._play_op, playback._cancel_op = old
        chat_run._play_saved.clear()
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)
