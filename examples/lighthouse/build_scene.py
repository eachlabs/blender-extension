"""Build the gray-box previsualization for "The Last Light" and save it as lighthouse.blend.

    blender --background --factory-startup --python examples/lighthouse/build_scene.py -- --out <dir>

Primitives with flat colors give Seedance the layout and the camera move; the prompts supply the look.
One camera per shot is bound to a timeline marker, so a frame-range render switches cameras itself.
"""

import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shots  # noqa: E402


def colored(obj, rgb):
    obj.color = (*rgb, 1.0)
    return obj


def primitive(kind, location, scale=(1, 1, 1), rgb=(0.8, 0.8, 0.8), name=None, **kwargs):
    getattr(bpy.ops.mesh, "primitive_%s_add" % kind)(location=location, **kwargs)
    obj = bpy.context.active_object
    obj.scale = scale
    if name:
        obj.name = name
    return colored(obj, rgb)


def build_world(scene):
    for obj in list(scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    primitive("plane", (0, 0, 0), (200, 200, 1), (0.08, 0.16, 0.22), "Sea")
    primitive("uv_sphere", (0, 0, 0), (5.5, 5.0, 1.3), (0.25, 0.27, 0.22), "Island", segments=48, ring_count=24)
    for i, (x, y, r) in enumerate([(5.2, -2.0, 1.0), (-1.5, -5.4, 0.8), (3.0, 4.6, 0.9), (-5.8, -1.2, 0.7),
                                   (1.2, 5.6, 0.6), (5.8, 2.5, 0.5)]):
        primitive("ico_sphere", (x, y, 0.2), (r, r * 0.9, r * 0.7), (0.18, 0.18, 0.18), "Rock.%d" % i, subdivisions=1)
    primitive("cylinder", (0, 0, 4.0), (0.6, 0.6, 3.0), (0.92, 0.92, 0.9), "Tower", vertices=32)
    primitive("cylinder", (0, 0, 4.6), (0.62, 0.62, 0.35), (0.65, 0.08, 0.08), "Tower band", vertices=32)
    primitive("cylinder", (0, 0, 7.5), (0.7, 0.7, 0.5), (1.0, 0.85, 0.45), "Lantern", vertices=32)
    primitive("cone", (0, 0, 8.4), (0.85, 0.85, 0.45), (0.4, 0.05, 0.05), "Lantern roof", vertices=32)
    primitive("cube", (-3.2, 2.6, 1.5), (0.8, 0.6, 0.5), (0.55, 0.52, 0.48), "Cottage")
    roof = primitive("cone", (-3.2, 2.6, 2.3), (1.05, 0.85, 0.35), (0.3, 0.12, 0.1), "Cottage roof", vertices=4)
    roof.rotation_euler[2] = math.pi / 4
    dock = primitive("cube", (-7.0, 4.9, 0.35), (2.6, 0.35, 0.08), (0.45, 0.32, 0.2), "Dock")
    dock.rotation_euler[2] = math.atan2(6.2 - 3.6, -9.6 + 4.4)
    boat = primitive("cube", (0, 0, 0.35), (0.9, 0.35, 0.22), (0.75, 0.08, 0.06), "Boat")
    cabin = primitive("cube", (-0.15, 0, 0.75), (0.3, 0.25, 0.2), (0.95, 0.95, 0.95), "Boat cabin")
    cabin.parent = boat
    cabin.location = (-0.15, 0, 0.9)
    cabin.scale = (0.35, 0.7, 0.9)
    animate_boat(boat)


def animate_boat(boat):
    path = shots.BOAT_PATH
    for index, (frame, x, y) in enumerate(path):
        nxt = path[min(index + 1, len(path) - 1)]
        prev = path[max(index - 1, 0)]
        dx, dy = (nxt[1] - prev[1]), (nxt[2] - prev[2])
        boat.location = (x, y, 0.35)
        boat.rotation_euler = (0, 0, math.atan2(dy, dx) if (dx or dy) else boat.rotation_euler[2])
        boat.keyframe_insert("location", frame=frame)
        boat.keyframe_insert("rotation_euler", index=2, frame=frame)
    linear(boat)


def linear(obj):
    action = obj.animation_data.action if obj.animation_data else None
    curves = getattr(action, "fcurves", None) if action else None
    if curves is None and action is not None:
        # Blender 5.x layered actions keep curves in channelbags.
        curves = [c for layer in action.layers for strip in layer.strips for bag in strip.channelbags for c in bag.fcurves]
    for curve in curves or ():
        for point in curve.keyframe_points:
            point.interpolation = "LINEAR"


def look_target(name, a, b, start, end):
    target = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(target)
    for frame, location in ((start, a), (end + 1, b)):
        target.location = location
        target.keyframe_insert("location", frame=frame)
    linear(target)
    return target


def camera(name, lens=32):
    data = bpy.data.cameras.new(name)
    data.lens = lens
    data.clip_end = 1000
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def build_shots(scene):
    for index, shot in enumerate(shots.SHOTS):
        start, end = shots.frame_range(index)
        cam = camera("Cam %s" % shot["name"])
        target = look_target("Target %s" % shot["name"], shot["target"][0], shot["target"][1], start, end)
        track = cam.constraints.new("TRACK_TO")
        track.target, track.track_axis, track.up_axis = target, "TRACK_NEGATIVE_Z", "UP_Y"
        if shot["move"] == "line":
            for frame, location in ((start, shot["camera"][0]), (end + 1, shot["camera"][1])):
                cam.location = location
                cam.keyframe_insert("location", frame=frame)
        else:
            (cx0, cy0), (cx1, cy1) = shot["center"]
            a0, a1 = shot["angles"]
            for step in range(0, shots.SHOT_FRAMES + 1, 12):
                t = step / shots.SHOT_FRAMES
                angle = math.radians(a0 + (a1 - a0) * t)
                cx, cy = cx0 + (cx1 - cx0) * t, cy0 + (cy1 - cy0) * t
                cam.location = (cx + shot["radius"] * math.cos(angle), cy + shot["radius"] * math.sin(angle), shot["height"])
                cam.keyframe_insert("location", frame=start + step)
        linear(cam)
        marker = scene.timeline_markers.new(shot["name"], frame=start)
        marker.camera = cam
    style = camera("Cam style", lens=35)
    style.location = shots.STYLE_CAMERA["location"]
    direction = Vector(shots.STYLE_CAMERA["target"]) - Vector(style.location)
    style.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def configure(scene):
    scene.render.engine = "BLENDER_WORKBENCH"
    shading = scene.display.shading
    shading.light, shading.color_type = "STUDIO", "OBJECT"
    shading.show_shadows, shading.show_cavity = True, True
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.32, 0.38, 0.48)
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 1920, 1080, 100
    scene.render.fps, scene.render.fps_base = shots.FPS, 1.0
    scene.frame_start, scene.frame_end = 1, len(shots.SHOTS) * shots.SHOT_FRAMES
    scene.frame_set(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    os.makedirs(args.out, exist_ok=True)
    scene = bpy.context.scene
    build_world(scene)
    build_shots(scene)
    configure(scene)
    scene.camera = bpy.data.objects["Cam %s" % shots.SHOTS[0]["name"]]
    path = os.path.join(os.path.abspath(args.out), "lighthouse.blend")
    bpy.ops.wm.save_as_mainfile(filepath=path)
    print("SAVED", path, "frames", scene.frame_start, scene.frame_end, "shots", len(shots.SHOTS))


main()
