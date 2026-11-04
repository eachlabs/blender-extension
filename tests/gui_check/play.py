"""Play through the camera from the bar."""

import os

import bpy

from eachlabs import chat_run
from tests.gui_check.args import OUT
from tests.gui_check.bar_input import bar_point, click, key, move, orange_pixels, placed, viewport_centre
from tests.gui_check.common import area_of, check, override, screenshot, window


def _view_state():
    rv3d = area_of("VIEW_3D").spaces.active.region_3d
    return (rv3d.view_perspective, tuple(round(v, 3) for v in rv3d.view_location),
            tuple(round(v, 4) for v in rv3d.view_rotation), round(rv3d.view_distance, 3),
            bpy.context.scene.camera.name if bpy.context.scene.camera else None)


def play_through(still_orange):
    """The done card's Play: Play as the chat's camera with its camera menu, Pause, and the view put back."""
    from eachlabs import overlay, viewport_marks
    from eachlabs.chat import playback

    scene = bpy.context.scene
    chat_cam = playback.chat_camera(scene)
    check("play: the button reads Play as the chat's camera, with the camera menu part",
          chat_cam and placed()[4].play_camera == chat_cam and {"play", "play_menu"} <= set(placed()[1].hits),
          "%r %r %s" % (chat_cam, placed()[4].play_camera, sorted(placed()[1].hits)))
    click(*bar_point("play_menu"))
    yield 0.4
    menu = placed()[4].camera_menu
    names = [o.name for o in scene.objects if o.type == "CAMERA"]
    check("play: the chevron opens the camera menu with every camera, the chat's first and chosen",
          overlay.UI["camera_menu"] and sorted(n for n, _h, _c in menu) == sorted(names) and len(names) >= 2
          and menu[0][0] == chat_cam and menu[0][2] and "camera_1" in placed()[1].hits,
          "%r %s" % (menu, sorted(placed()[1].hits)))
    screenshot("bar-06-camera-menu.png")
    key("ESC")
    yield 0.4
    check("play: Esc closes the camera menu", not overlay.UI["camera_menu"] and not placed()[4].camera_menu)
    click(*bar_point("play_menu"))
    yield 0.4
    other = menu[1][0]
    click(*bar_point("camera_1"))
    yield 0.4
    check("play: choosing a camera closes the menu and names it on the button",
          not overlay.UI["camera_menu"] and placed()[4].play_camera == other, repr(placed()[4].play_camera))
    click(*bar_point("play_menu"))
    yield 0.4
    # In the status bar below the editors a click selects nothing, so the camera stage stays the undo step.
    view = area_of("VIEW_3D")
    click(view.x + view.width // 2, min(a.y for a in window().screen.areas) // 2)
    yield 0.3
    move(*viewport_centre())
    yield 0.3
    check("play: a click outside the bar closes the camera menu", not overlay.UI["camera_menu"])
    click(*bar_point("play_menu"))
    yield 0.4
    click(*bar_point("camera_0"))
    yield 0.4
    before = _view_state()
    click(*bar_point("play"))
    yield 0.6
    rv3d = area_of("VIEW_3D").spaces.active.region_3d
    check("bar: Play plays the animation through the chat's camera",
          window().screen.is_animation_playing and rv3d.view_perspective == "CAMERA" and scene.camera.name == chat_cam,
          "%s %s %s" % (window().screen.is_animation_playing, rv3d.view_perspective, scene.camera.name))
    overlay.tag_redraw()
    yield 0.3
    screenshot("live-04-playing.png")
    play_orange = orange_pixels(os.path.join(OUT, "live-04-playing.png"))
    check("live: the camera path is hidden while the animation plays",
          window().screen.is_animation_playing and viewport_marks.path_visible(bpy.context) is False
          and play_orange < still_orange - 40, "%d -> %d orange pixels" % (still_orange, play_orange))
    check("play: while it plays the button reads Pause, without the camera menu part",
          placed()[4].playing and "play" in placed()[1].hits and "play_menu" not in placed()[1].hits,
          str(sorted(placed()[1].hits)))
    click(*bar_point("play"))
    yield 0.6
    check("play: Pause stops playback and puts the view and the scene camera back",
          not window().screen.is_animation_playing and _view_state() == before,
          "%s -> %s" % (before, _view_state()))
    click(*bar_point("play_menu"))
    yield 0.4
    click(*bar_point("camera_1"))
    yield 0.4
    click(*bar_point("play"))
    yield 0.6
    through = (rv3d.view_perspective, scene.camera.name)
    with override():
        bpy.ops.screen.animation_cancel(restore_frame=True)  # stopped another way, as Esc in the view does
    yield 0.4
    check("play: playback stopped another way also puts the view back",
          through == ("CAMERA", other) and not window().screen.is_animation_playing and _view_state() == before,
          "%s %s -> %s" % (through, before, _view_state()))
    chat_run.STATE.play_camera = ""
    key("ESC")  # the camera menu gave the bar the keys; give them back to Blender
    yield 0.3
    check("play: Esc gives the keys back after the camera menu", not overlay.UI["focused"])
