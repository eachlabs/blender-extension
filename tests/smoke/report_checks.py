"""The checks read_scene runs: light, glass, looks, piercing, floating and texture scale."""

import os
import re

import bpy

from tests.smoke.common import WORK, _step, check


CORRECT_ROOM_CODE = '''
import math

def paint(name, rgb):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.diffuse_color = (rgb[0], rgb[1], rgb[2], 1.0)
    return m

def root(name, where=(0, 0, 0)):
    r = bpy.data.objects.new(name, None)
    scene.collection.objects.link(r)
    r.location = where
    return r

def solid(r, part, bm, where, rgb, turn):
    name = "%s / %s" % (r.name, part)
    m = bpy.data.meshes.new(name)
    bm.to_mesh(m)
    bm.free()
    m.materials.append(paint(r.name + " paint", rgb))
    o = bpy.data.objects.new(name, m)
    scene.collection.objects.link(o)
    o.location = where
    o.rotation_euler = turn
    attach(o, r)
    return o

def box(r, part, size, where, rgb=(0.5, 0.4, 0.3), turn=(0, 0, 0)):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    return solid(r, part, bm, where, rgb, turn)

def rod(r, part, radius, depth, where, rgb=(0.4, 0.3, 0.2), turn=(0, 0, 0), tip=None):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=16, radius1=radius,
                          radius2=radius if tip is None else tip, depth=depth)
    return solid(r, part, bm, where, rgb, turn)

ground = root("Yard")
box(ground, "lawn", (30, 30, 0.2), (0, 0, -0.3), (0.2, 0.5, 0.2))
thing(ground, "ground")

room = root("Room")
box(room, "floor", (8, 6, 0.2), (0, 0, -0.1), (0.5, 0.35, 0.2))
box(room, "ceiling", (8, 6, 0.2), (0, 0, 3.1), (0.9, 0.9, 0.85))
for part, size, where in (
        ("back wall left", (2.7, 0.2, 3), (-2.65, 2.9, 1.5)),
        ("back wall under west window", (1.0, 0.2, 1.0), (-0.8, 2.9, 0.5)),
        ("back wall over west window", (1.0, 0.2, 0.8), (-0.8, 2.9, 2.6)),
        ("back wall middle", (0.8, 0.2, 3), (0.1, 2.9, 1.5)),
        ("back wall under east window", (1.2, 0.2, 1.0), (1.1, 2.9, 0.5)),
        ("back wall over east window", (1.2, 0.2, 0.8), (1.1, 2.9, 2.6)),
        ("back wall right", (2.3, 0.2, 3), (2.85, 2.9, 1.5)),
        ("left wall south", (0.2, 1.5, 3), (-3.9, -2.25, 1.5)),
        ("left wall over door", (0.2, 1.0, 0.9), (-3.9, -1.0, 2.55)),
        ("left wall north", (0.2, 3.3, 3), (-3.9, 1.15, 1.5)),
        ("right wall", (0.2, 5.8, 3), (3.9, -0.1, 1.5))):
    box(room, part, size, where, (0.85, 0.8, 0.7))
thing(room, "room", "walls, floor, ceiling")

for name, x0, x1 in (("West window", -1.3, -0.3), ("East window", 0.5, 1.7)):
    w = root(name)
    mid, width = (x0 + x1) / 2, x1 - x0
    box(w, "sill bar", (width, 0.2, 0.08), (mid, 2.9, 1.04), (0.3, 0.2, 0.1))
    box(w, "head bar", (width, 0.2, 0.08), (mid, 2.9, 2.16), (0.3, 0.2, 0.1))
    box(w, "left bar", (0.08, 0.2, 1.04), (x0 + 0.04, 2.9, 1.6), (0.3, 0.2, 0.1))
    box(w, "right bar", (0.08, 0.2, 1.04), (x1 - 0.04, 2.9, 1.6), (0.3, 0.2, 0.1))
    box(w, "pane", (width - 0.16, 0.01, 1.04), (mid, 2.9, 1.6), (0.7, 0.8, 0.9))
    thing(w, "window", "glass, frame", parent=room)

door = root("Door")
box(door, "south jamb", (0.2, 0.06, 2.1), (-3.9, -1.47, 1.05), (0.3, 0.2, 0.1))
box(door, "north jamb", (0.2, 0.06, 2.1), (-3.9, -0.53, 1.05), (0.3, 0.2, 0.1))
box(door, "head", (0.2, 0.88, 0.06), (-3.9, -1.0, 2.07), (0.3, 0.2, 0.1))
box(door, "leaf", (0.04, 0.88, 2.03), (-3.9, -1.0, 1.025), (0.45, 0.3, 0.15))
box(door, "knob", (0.06, 0.04, 0.04), (-3.86, -0.65, 1.0), (0.8, 0.7, 0.2))
thing(door, "door", parent=room)

table = root("Dining table")
box(table, "top", (1.6, 0.9, 0.04), (0, 0, 0.74))
for i, (x, y) in enumerate(((-0.72, -0.37), (0.72, -0.37), (-0.72, 0.37), (0.72, 0.37))):
    box(table, "leg %d" % i, (0.06, 0.06, 0.72), (x, y, 0.36))
thing(table, "table")

books = root("Open books")
box(books, "lower book", (0.3, 0.22, 0.03), (-0.45, 0.15, 0.775), (0.6, 0.1, 0.1))
box(books, "upper book", (0.28, 0.2, 0.03), (-0.45, 0.15, 0.805), (0.1, 0.2, 0.6), (0, 0, 0.2))
thing(books, "books", "open books", parent=table)

tray = root("Tray")
box(tray, "base", (0.4, 0.3, 0.02), (0.4, 0, 0.77), (0.6, 0.6, 0.6))
box(tray, "north rim", (0.4, 0.01, 0.03), (0.4, 0.145, 0.795), (0.6, 0.6, 0.6))
box(tray, "south rim", (0.4, 0.01, 0.03), (0.4, -0.145, 0.795), (0.6, 0.6, 0.6))
box(tray, "east rim", (0.01, 0.28, 0.03), (0.595, 0, 0.795), (0.6, 0.6, 0.6))
box(tray, "west rim", (0.01, 0.28, 0.03), (0.205, 0, 0.795), (0.6, 0.6, 0.6))
thing(tray, "tray", parent=table)

mug = root("Mug")
rod(mug, "body", 0.04, 0.1, (0.4, 0, 0.83), (0.9, 0.9, 0.9))
box(mug, "handle", (0.02, 0.01, 0.06), (0.45, 0, 0.83), (0.9, 0.9, 0.9))
thing(mug, "mug", parent=tray)

lamp = root("Pendant lamp")
box(lamp, "rod", (0.02, 0.02, 1.1), (0, 0, 2.45), (0.1, 0.1, 0.1))
rod(lamp, "shade", 0.25, 0.25, (0, 0, 1.775), (0.8, 0.6, 0.3), tip=0.06)
thing(lamp, "lamp", "pendant")

tucked = root("Tucked chair", (0, -0.4, 0))
box(tucked, "seat", (0.42, 0.42, 0.04), (0, -0.4, 0.45))
for i, (x, y) in enumerate(((-0.19, -0.59), (0.19, -0.59), (-0.19, -0.21), (0.19, -0.21))):
    box(tucked, "leg %d" % i, (0.04, 0.04, 0.43), (x, y, 0.215))
box(tucked, "back", (0.42, 0.04, 0.45), (0, -0.59, 0.695))
thing(tucked, "chair")

shelf = root("Bookshelf")
box(shelf, "west side", (0.03, 0.3, 1.8), (-2.985, 2.65, 0.9))
box(shelf, "east side", (0.03, 0.3, 1.8), (-2.015, 2.65, 0.9))
box(shelf, "back", (0.94, 0.02, 1.8), (-2.5, 2.79, 0.9))
for i, z in enumerate((0.01, 0.6, 1.2)):
    box(shelf, "board %d" % i, (0.94, 0.28, 0.02), (-2.5, 2.64, z))
box(shelf, "top", (1.0, 0.3, 0.02), (-2.5, 2.65, 1.79))
thing(shelf, "bookshelf")

for name, x, z in (("Lower shelf books", -2.9, 0.73), ("Upper shelf books", -2.4, 1.33)):
    standing = root(name)
    for i in range(6):
        box(standing, "book %d" % i, (0.03, 0.18, 0.24), (x + i * 0.04, 2.62, z), (0.2 + i * 0.1, 0.2, 0.3))
    thing(standing, "books", "standing books", parent=shelf)

loose_book = root("Floor book")
box(loose_book, "cover", (0.25, 0.18, 0.04), (1.5, -1.2, 0.02), (0.2, 0.5, 0.3))
thing(loose_book, "book")

rug = root("Rug")
box(rug, "pile", (2.0, 1.4, 0.01), (2.5, 0, 0.005), (0.6, 0.15, 0.15))
thing(rug, "rug")

sofa = root("Sofa")
box(sofa, "base", (1.8, 0.8, 0.4), (-1.5, -2.3, 0.2), (0.3, 0.3, 0.5))
box(sofa, "back", (1.8, 0.2, 0.5), (-1.5, -2.6, 0.65), (0.3, 0.3, 0.5))
box(sofa, "west arm", (0.2, 0.6, 0.25), (-2.3, -2.2, 0.525), (0.3, 0.3, 0.5))
box(sofa, "east arm", (0.2, 0.6, 0.25), (-0.7, -2.2, 0.525), (0.3, 0.3, 0.5))
box(sofa, "seat", (1.4, 0.6, 0.1), (-1.5, -2.2, 0.45), (0.35, 0.35, 0.55))
thing(sofa, "sofa")

cushion = root("Throw cushion")
box(cushion, "pillow", (0.4, 0.4, 0.12), (-1.9, -2.2, 0.555), (0.8, 0.7, 0.2))
thing(cushion, "cushion", parent=sofa)

fireplace = root("Fireplace")
box(fireplace, "hearth", (0.8, 1.8, 0.06), (3.4, 0, 0.03), (0.4, 0.4, 0.4))
box(fireplace, "south cheek", (0.6, 0.3, 1.0), (3.5, -0.65, 0.56), (0.5, 0.45, 0.4))
box(fireplace, "north cheek", (0.6, 0.3, 1.0), (3.5, 0.65, 0.56), (0.5, 0.45, 0.4))
box(fireplace, "firebox back", (0.1, 1.0, 1.0), (3.75, 0, 0.56), (0.2, 0.2, 0.2))
box(fireplace, "lintel", (0.6, 1.6, 0.2), (3.5, 0, 1.16), (0.5, 0.45, 0.4))
box(fireplace, "mantel", (0.7, 1.8, 0.05), (3.45, 0, 1.285), (0.4, 0.25, 0.1))
box(fireplace, "chimney breast", (0.4, 1.0, 1.69), (3.6, 0, 2.155), (0.5, 0.45, 0.4))
thing(fireplace, "fireplace")

fire = root("Fire")
rod(fire, "south log", 0.06, 0.5, (3.42, -0.1, 0.12), (0.3, 0.15, 0.05), (math.pi / 2, 0, 0.3))
rod(fire, "north log", 0.06, 0.5, (3.42, 0.1, 0.12), (0.3, 0.15, 0.05), (math.pi / 2, 0, -0.3))
rod(fire, "top log", 0.05, 0.45, (3.45, 0, 0.23), (0.3, 0.15, 0.05), (0, math.pi / 2, 0))
for i, (y, h) in enumerate(((-0.12, 0.3), (0.0, 0.4), (0.12, 0.28))):
    rod(fire, "flame %d" % i, 0.07, h, (3.45, y, 0.2 + h / 2), (1.0, 0.5, 0.1), tip=0.0)
thing(fire, "fire", "logs, flames", parent=fireplace)

picture = root("Framed picture")
box(picture, "frame", (0.6, 0.03, 0.45), (2.8, 2.785, 1.6), (0.4, 0.3, 0.1))
box(picture, "canvas", (0.5, 0.005, 0.35), (2.8, 2.768, 1.6), (0.3, 0.5, 0.7))
thing(picture, "picture", parent=room)

torch = root("Wall torch")
box(torch, "plate", (0.02, 0.1, 0.15), (3.79, -2.0, 1.8), (0.2, 0.2, 0.2))
box(torch, "arm", (0.15, 0.03, 0.03), (3.705, -2.0, 1.8), (0.2, 0.2, 0.2))
rod(torch, "stick", 0.025, 0.4, (3.62, -2.0, 1.9), (0.4, 0.25, 0.1))
rod(torch, "flame", 0.035, 0.12, (3.62, -2.0, 2.16), (1.0, 0.5, 0.1), tip=0.0)
thing(torch, "torch", parent=room)

rack = root("Sword rack")
box(rack, "board", (0.03, 0.8, 0.12), (-3.785, 1.4, 1.5), (0.4, 0.25, 0.1))
box(rack, "south peg", (0.08, 0.03, 0.03), (-3.73, 1.15, 1.45), (0.4, 0.25, 0.1))
box(rack, "north peg", (0.08, 0.03, 0.03), (-3.73, 1.6, 1.45), (0.4, 0.25, 0.1))
thing(rack, "rack", parent=room)

sword = root("Sword")
box(sword, "blade", (0.02, 0.7, 0.04), (-3.72, 1.35, 1.485), (0.8, 0.8, 0.85))
box(sword, "guard", (0.03, 0.02, 0.12), (-3.72, 1.71, 1.485), (0.7, 0.6, 0.2))
box(sword, "grip", (0.025, 0.15, 0.025), (-3.72, 1.795, 1.485), (0.3, 0.15, 0.05))
thing(sword, "sword", parent=rack)

platform = root("Loft platform")
box(platform, "deck", (2.0, 1.0, 1.2), (2.0, -2.4, 0.6), (0.5, 0.35, 0.2))
thing(platform, "platform")

ladder = root("Ladder")
lean = math.atan2(0.6, 1.2)
length = 1.3
for x in (1.8, 2.2):
    box(ladder, "rail %g" % x, (0.04, 0.04, length), (x, -1.6, 0.6), (0.6, 0.45, 0.25), (lean, 0, 0))
for i in range(4):
    t = (i + 1) / 5 - 0.5
    box(ladder, "rung %d" % i, (0.36, 0.03, 0.03), (2.0, -1.6 - t * length * math.sin(lean),
        0.6 + t * length * math.cos(lean)), (0.6, 0.45, 0.25), (lean, 0, 0))
thing(ladder, "ladder", parent=platform)

chair = root("Side chair", (-1.0, 1.5, 0))
box(chair, "seat", (0.42, 0.42, 0.04), (-1.0, 1.5, 0.45))
for i, (x, y) in enumerate(((-1.19, 1.31), (-0.81, 1.31), (-1.19, 1.69), (-0.81, 1.69))):
    box(chair, "leg %d" % i, (0.04, 0.04, 0.43), (x, y, 0.215))
box(chair, "back", (0.42, 0.04, 0.45), (-1.0, 1.69, 0.695))
thing(chair, "chair")
copy_thing(chair, (-0.4, 1.5, 0))

person = root("Character")
for side, x in (("left", -2.08), ("right", -1.92)):
    box(person, side + " foot", (0.1, 0.25, 0.06), (x, 0.55, 0.03), (0.2, 0.15, 0.1))
    box(person, side + " leg", (0.1, 0.1, 0.8), (x, 0.5, 0.46), (0.2, 0.25, 0.5))
box(person, "torso", (0.36, 0.2, 0.6), (-2.0, 0.5, 1.16), (0.6, 0.2, 0.2))
box(person, "left arm", (0.08, 0.08, 0.6), (-2.22, 0.5, 1.1), (0.8, 0.6, 0.5))
box(person, "right arm", (0.08, 0.08, 0.6), (-1.78, 0.5, 1.1), (0.8, 0.6, 0.5))
box(person, "neck", (0.08, 0.08, 0.04), (-2.0, 0.5, 1.48), (0.8, 0.6, 0.5))
box(person, "head", (0.22, 0.22, 0.24), (-2.0, 0.5, 1.62), (0.8, 0.6, 0.5))
thing(person, "person")

cat = root("Cat")
box(cat, "body", (0.45, 0.2, 0.18), (2.5, 0.2, 0.1), (0.9, 0.5, 0.1))
box(cat, "head", (0.14, 0.14, 0.13), (2.76, 0.2, 0.16), (0.9, 0.5, 0.1))
box(cat, "left ear", (0.03, 0.03, 0.04), (2.76, 0.16, 0.24), (0.9, 0.5, 0.1))
box(cat, "right ear", (0.03, 0.03, 0.04), (2.76, 0.24, 0.24), (0.9, 0.5, 0.1))
box(cat, "tail", (0.3, 0.04, 0.04), (2.14, 0.2, 0.03), (0.9, 0.5, 0.1))
thing(cat, "cat", parent=rug)

desk = root("Study desk")  # real problems in the same room, which the checks still report
box(desk, "top", (0.8, 0.4, 0.75), (-3.2, -0.2, 0.375))
thing(desk, "desk")
over = root("Desk shelf")
box(over, "board", (0.8, 0.25, 0.04), (-3.2, -0.2, 1.6))
thing(over, "shelf")
sign = root("Hovering sign")
box(sign, "board", (1.2, 0.1, 0.4), (8, 0, 2.0))
thing(sign, "sign")
doubled = root("Doubled book")
box(doubled, "cover", (0.25, 0.18, 0.04), (8, 3, -0.18))
box(doubled, "cover again", (0.25, 0.18, 0.04), (8.01, 3, -0.17))
thing(doubled, "book")
statue = root("Roof statue")
box(statue, "figure", (0.4, 0.4, 1.2), (-3.0, -2.5, 3.8))
thing(statue, "statue")
'''

ROOM_THINGS = ("Room", "West window", "East window", "Door", "Dining table", "Open books", "Tray", "Mug",
               "Pendant lamp", "Tucked chair", "Bookshelf", "Lower shelf books", "Upper shelf books", "Floor book",
               "Rug", "Sofa", "Throw cushion", "Fireplace", "Fire", "Framed picture", "Wall torch", "Sword rack", "Sword",
               "Loft platform", "Ladder", "Side chair", "Character", "Cat")
ROOM_PROBLEMS = ("Study desk", "Desk shelf", "Hovering sign", "Doubled book", "Roof statue")
ROOM_INFO = ("objects", "lights", "world", "camera", "frame_range", "fps", "engine", "other_objects", "free_space",
             "things", "things_more", "textures", "generated_3d", "shadow_lights", "shadow_note")


def test_correct_room():
    """A room built right, with every common arrangement of things on, in, under and against each other: no check
    reports any of its things, while the real problems built beside them (``ROOM_PROBLEMS``) are still reported."""
    import json

    from eachlabs import scene_build

    scene = bpy.data.scenes.new("eachlabs_correct_room")
    build = scene_build.SceneBuild(scene, "room-run")
    try:
        built = _step(build, CORRECT_ROOM_CODE)
        chairs = [o.name for o in scene.objects if o.name.startswith("Side chair") and o.parent is None]
        check("room: the correct room is built, with a copy of the side chair", built.get("ok") and len(chairs) == 2,
              "%s %s" % (chairs, json.dumps(built)[:600]))
        seen = build.read_scene()
        found = {k: v for k, v in seen.items() if k not in ROOM_INFO}
        print("room findings: %s" % json.dumps(found, indent=1, sort_keys=True))
        about = re.compile(r'"(%s)(?:[ ./][^"]*)?"' % "|".join(re.escape(n) for n in ROOM_THINGS + ROOM_PROBLEMS))
        text = json.dumps([e for v in found.values() for e in (v if isinstance(v, list) else [v])
                           if not set(about.findall(json.dumps(e))) & set(ROOM_PROBLEMS)])
        named = sorted(set(about.findall(text)))
        check("room: no check reports a thing of the correct room", not named, ", ".join(named))
        under = {e["thing"]: e["under"] for e in seen.get("under") or []}
        check("room: a desk in the room under a shelf that hangs from nothing is still under it",
              under.get("Study desk") == "Desk shelf", str(under))
        check("room: a big sign hanging from nothing over the yard still floats",
              "Hovering sign" in {e["thing"] for e in seen.get("floats_above") or []}, str(seen.get("floats_above")))
        check("room: a book laid over its own copy is still doubled, though the shelves' rows of books are not",
              "Doubled book" in {e["thing"] for e in seen.get("duplicates") or []}, str(seen.get("duplicates")))
        check("room: a statue on the roof stands on the room, though its windows in the wall openings do not",
              any(e.get("thing", "").startswith("Roof statue") and e.get("on", "").startswith("Room")
                  for e in seen.get("overlaps") or []), str(seen.get("overlaps")))
    finally:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)


EMISSION_CODE = '''
for name, color, x, power in (("Glow white", (1.0, 1.0, 0.95, 1.0), 0.0, 30.0),
                              ("Glow warm", (1.0, 0.4, 0.08, 1.0), 2.0, 30.0),
                              ("Glow flame", (1.0, 0.4, 0.08, 1.0), 4.0, 2.5)):
    m = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=0.3, radius2=0.0, depth=1.0)
    bm.to_mesh(m)
    bm.free()
    o = bpy.data.objects.new(name, m)
    scene.collection.objects.link(o)
    o.location = (x, 0, 0.5)
    mat = bpy.data.materials.new(name)
    if mat.node_tree is None:
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Emission Color"].default_value = color
    bsdf.inputs["Emission Strength"].default_value = power
    o.data.materials.append(mat)
'''


def test_emission():
    """A strong flat white emitter is reported, and a coloured one so strong it renders white; a warm flame at flame
    strength is not."""
    from eachlabs import scene_build
    from eachlabs.checks import emission

    scene = bpy.data.scenes.new("eachlabs_emission_test")
    build = scene_build.SceneBuild(scene, "emission-run")
    try:
        check("emission: the glows are built", _step(build, EMISSION_CODE).get("ok"))
        found = emission.harsh_emitters(build._objects(), build._mine)
        check("emission: the flat white glow and the washed-out warm one are listed, the flame is not",
              [f["material"] for f in found] == ["Glow white", "Glow warm"]
              and found[1].get("washes_out") and not found[0].get("washes_out"), str(found))
    finally:
        bpy.data.scenes.remove(scene)


GLASS_CODE = '''
def block(name, size, loc, glass=False):
    m = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(m)
    bm.free()
    o = bpy.data.objects.new(name, m)
    scene.collection.objects.link(o)
    o.location = loc
    o.scale = size
    mat = bpy.data.materials.new(name)
    if mat.node_tree is None:
        mat.use_nodes = True
    if glass:
        mat.node_tree.nodes.get("Principled BSDF").inputs["Transmission Weight"].default_value = 1.0
    o.data.materials.append(mat)
    return o
block("Pane", (1.0, 0.05, 1.0), (0, 2, 1.5), glass=True)
block("Snow hill", (8.0, 1.0, 3.0), (0, 12, 1.5))
cam_data = bpy.data.cameras.new("Glass cam")
cam = bpy.data.objects.new("Glass cam", cam_data)
scene.collection.objects.link(cam)
cam.location = (0, -2, 1.5)
cam.rotation_euler = (1.5708, 0, 0)
scene.camera = cam
'''


def test_through_glass():
    """The camera's view past a pane names what stands behind it, and the sky when that is moved away."""
    from eachlabs import scene_build
    from eachlabs.checks import through_glass

    scene = bpy.data.scenes.new("eachlabs_glass_test")
    build = scene_build.SceneBuild(scene, "glass-run")
    try:
        check("through glass: the pane, the hill and the camera are built", _step(build, GLASS_CODE).get("ok"))
        for layer in scene.view_layers:
            layer.update()
        depsgraph = build._depsgraph(scene)
        found = through_glass.views(build._objects(), build._mine, scene, depsgraph, lambda o: o.name)
        check("through glass: the pane shows the hill behind it",
              found and found[0]["glass"] == "Pane" and "Snow hill" in found[0]["sees"], str(found))
        scene.objects["Snow hill"].location.z = -50.0
        for layer in scene.view_layers:
            layer.update()
        found = through_glass.views(build._objects(), build._mine, scene, depsgraph, lambda o: o.name)
        check("through glass: with the hill gone the pane shows the sky",
              found and found[0]["sees"] == [through_glass.SKY], str(found))
    finally:
        bpy.data.scenes.remove(scene)


PIERCE_CODE = """# A hut whose roof a pole passes right through, and a post that only ends under the roof
import bmesh
def box(name, size, at):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    bmesh.ops.translate(bm, vec=at, verts=bm.verts)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    return ob
hut = bpy.data.objects.new("Hut", None)
scene.collection.objects.link(hut)
attach(box("Hut roof", (6, 6, 0.3), (0, 0, 3)), hut)
attach(box("Hut pole", (0.1, 0.1, 4), (0, 0, 3)), hut)
attach(box("Hut post", (0.1, 0.1, 1.8), (2, 2, 1.95)), hut)
attach(box("Hut window bar", (2, 0.05, 0.05), (10, 0, 1.5)), hut)
attach(box("Hut window rail", (0.05, 0.05, 2), (10, 0, 1.5)), hut)
area = bpy.data.objects.new("Zone Village", None)
area["zone"] = "Village"
scene.collection.objects.link(area)
stall = bpy.data.objects.new("Stall", None)
scene.collection.objects.link(stall)
stall.location = (30, 0, 0)
attach(stall, area)
attach(box("Stall counter", (3, 1, 0.1), (30, 0, 1)), stall)
attach(box("Stall canopy", (3, 2, 0.1), (30, 0, 2.5)), stall)
attach(box("Stall canopy pole", (0.08, 0.08, 2.4), (30, 0, 1.3)), stall)
shed = bpy.data.objects.new("Shed", None)
scene.collection.objects.link(shed)
attach(shed, area)
attach(box("Shed roof", (4, 4, 0.2), (40, 0, 2.5)), shed)
attach(box("Shed mast", (0.1, 0.1, 3), (40, 0, 2.5)), shed)
"""


def test_pierces():
    """A thin part passing right through another part of its own thing is listed; one ending at it is not."""
    import json

    from eachlabs import chat_loop, scene_build

    scene = bpy.data.scenes.new("eachlabs_pierces")
    build = scene_build.SceneBuild(scene, "pierce-run")
    try:
        check("pierces: the hut is built", _step(build, PIERCE_CODE).get("ok"))
        found = build.read_scene().get("pierces") or []
        parts = {e["part"] for e in found}
        check("pierces: the pole through the roof is listed", "Hut pole" in parts, json.dumps(found))
        check("pierces: the post that ends under the roof is not", "Hut post" not in parts, json.dumps(found))
        check("pierces: two thin bars crossing are a joint, not listed",
              not parts & {"Hut window bar", "Hut window rail"}, json.dumps(found))
        check("pierces: a pole that stays inside its thing is not listed", "Stall canopy pole" not in parts,
              json.dumps(found))
        check("pierces: a thing standing in a zone is measured", "Shed mast" in parts, json.dumps(found))
        check("pierces: it is a placement problem the fix stage gets",
              "pierces" in chat_loop.placement_problems({"pierces": found}))
    finally:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)


FLOATS_CODE = """# A peak, a cap hanging three metres over it, a crate resting on the ground and a small bird in the air
import bmesh
def box(name, size, at):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    bmesh.ops.translate(bm, vec=at, verts=bm.verts)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    return ob
box("Float ground", (40, 40, 0.2), (0, 0, -0.1))
box("Float peak", (6, 6, 6), (0, 0, 3))
box("Float cap", (5, 5, 1), (0, 0, 9.5))
box("Float crate", (1.2, 1.2, 1.2), (10, 0, 0.6))
box("Float bird", (0.3, 0.3, 0.2), (-10, 0, 4))
"""


def test_floats():
    """A large thing hanging over the surface under it is listed as floating; resting things and small flyers not."""
    import json

    from eachlabs import chat_loop, scene_build

    scene = bpy.data.scenes.new("eachlabs_floats")
    build = scene_build.SceneBuild(scene, "float-run")
    try:
        check("floats: the scene is built", _step(build, FLOATS_CODE).get("ok"))
        found = build.read_scene().get("floats_above") or []
        names = {e["thing"]: e for e in found}
        check("floats: the cap over the peak is listed with its gap",
              "Float cap" in names and abs(names["Float cap"]["gap_m"] - 3.0) < 0.1, json.dumps(found))
        check("floats: the crate on the ground is not listed", "Float crate" not in names, json.dumps(found))
        check("floats: the small bird is not listed", "Float bird" not in names, json.dumps(found))
        check("floats: it is a placement problem the fix stage gets",
              "floats_above" in chat_loop.placement_problems({"floats_above": found}))
    finally:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)


TEXTURE_SCALE_CODE = """# A long wall made by scaling a cube, and a small plane scaled up into the ground
import bmesh
def scaled(name, scale, coords):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    ob.scale = scale
    mat = bpy.data.materials.new(name + " stone")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    tc = nodes.new("ShaderNodeTexCoord")
    tex = nodes.new("ShaderNodeTexBrick")
    links.new(tc.outputs[coords], tex.inputs["Vector"])
    links.new(tex.outputs["Color"], nodes["Principled BSDF"].inputs["Base Color"])
    ob.data.materials.append(mat)
    return ob
scaled("Long wall", (40, 0.3, 3), "Object")
scaled("Big ground", (100, 100, 0.02), "Object")
scaled("Real wall", (1, 1, 1), "Generated")
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=1.0)
bmesh.ops.scale(bm, vec=(9.4, 8.0, 0.22), verts=bm.verts)
me = bpy.data.meshes.new("Ceiling")
bm.to_mesh(me)
bm.free()
ceiling = bpy.data.objects.new("Ceiling", me)
scene.collection.objects.link(ceiling)
mat = bpy.data.materials.new("Ceiling timber")
mat.use_nodes = True
nodes, links = mat.node_tree.nodes, mat.node_tree.links
tc = nodes.new("ShaderNodeTexCoord")
mp = nodes.new("ShaderNodeMapping")
mp.inputs["Scale"].default_value = (9.0, 1.4, 1.4)
wave = nodes.new("ShaderNodeTexWave")
links.new(tc.outputs["Generated"], mp.inputs["Vector"])
links.new(mp.outputs["Vector"], wave.inputs["Vector"])
links.new(wave.outputs["Color"], nodes["Principled BSDF"].inputs["Base Color"])
ceiling.data.materials.append(mat)
for i in range(9):  # more stretched walls than read_scene lists
    scaled("Plank wall %d" % i, (30, 0.2, 2), "Object")
"""


def test_texture_scale():
    """A texture on an object's own coordinates is stretched along a long wall and blown up over a scaled ground:
    both are listed; a generated texture is mapped by world position, the same size on every axis."""
    import json

    from eachlabs import scene_build, textures
    from tests import glb_fixture

    scene = bpy.data.scenes.new("eachlabs_texscale")
    build = scene_build.SceneBuild(scene, "texscale-run")
    try:
        check("texture scale: the scene is built", _step(build, TEXTURE_SCALE_CODE).get("ok"))
        found = {e["object"]: e for e in build.read_scene().get("texture_scale") or []}
        check("texture scale: the long wall's texture is listed as stretched",
              found.get("Long wall", {}).get("stretch", 0) >= 13, json.dumps(found))
        check("texture scale: the scaled-up ground's texture is listed as blown up",
              found.get("Big ground", {}).get("blown_up", 0) >= 100, json.dumps(found))
        check("texture scale: a cube at its real size is not listed", "Real wall" not in found, json.dumps(found))
        check("texture scale: a ceiling whose wood grain repeats 5x longer one way is listed as stretched",
              found.get("Ceiling", {}).get("stretch", 0) >= 5, json.dumps(found))
        build.note_change()
        build.end_stage("materials")
        after = build.read_scene()
        left = {e["object"] for e in after.get("texture_scale") or []}
        check("texture scale: the end of a stage places listed patterns per metre, so they are no longer listed",
              not left & {"Ceiling", "Long wall", "Big ground"}, json.dumps(after.get("texture_scale")))
        check("texture scale: walls past the listed number are placed per metre too",
              not any(name.startswith("Plank wall") for name in left), json.dumps(sorted(left)))
        check("texture scale: read_scene names the materials it placed per metre",
              "Ceiling timber" in (after.get("textures_rescaled") or []), json.dumps(after.get("textures_rescaled")))
        check("texture scale: a material it was not listed for keeps its coordinates", any(
            link.from_node.type == "TEX_COORD" for link in bpy.data.materials["Real wall stone"].node_tree.links))
        path = os.path.join(WORK, "tile.png")
        with open(path, "wb") as fh:
            fh.write(glb_fixture.png())
        textures.apply(build, "Long wall stone", path, tile_m=2.0)
        nodes = bpy.data.materials["Long wall stone"].node_tree.nodes
        geometry = [n for n in nodes if n.type == "NEW_GEOMETRY" and n.name.startswith(textures.NODE_PREFIX)]
        mapping = [n for n in nodes if n.type == "MAPPING" and n.name.startswith(textures.NODE_PREFIX)]
        check("texture scale: a generated texture is mapped by world position, 2 m a tile on every axis",
              geometry and geometry[0].outputs["Position"].is_linked and mapping
              and tuple(round(v, 3) for v in mapping[0].inputs["Scale"].default_value) == (0.5, 0.5, 0.5),
              str([n.type for n in nodes]))
    finally:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)


LOOK_CODE = """# A sign seen from behind, a post right in front of the camera, a shop behind it
import bmesh
def box(name, size, at):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    scene.collection.objects.link(ob)
    ob.location = at
    return ob
box("Shop", (6, 4, 4), (0, 12, 2))
box("Post", (0.3, 0.3, 3), (0, 1.5, 1.5))
cu = bpy.data.curves.new("Shop sign", "FONT")
cu.body = "OPEN"
sign = bpy.data.objects.new("Shop sign", cu)
scene.collection.objects.link(sign)
sign.location = (0, 9.9, 3)
sign.rotation_euler = (1.5708, 0, 0)
cam_data = bpy.data.cameras.new("Shot")
cam = bpy.data.objects.new("Shot", cam_data)
scene.collection.objects.link(cam)
cam.location = (0, 0, 1.6)
cam.rotation_euler = (1.5708, 0, 0)
scene.camera = cam
"""


def test_look_checks():
    """A text object seen from behind is listed as reading backwards; a post right in front of the lens is a near
    blocker; Poly Haven's files go on a material and on the chat's own world."""
    import json

    from eachlabs import scene_build
    from eachlabs.polyhaven import apply as haven_apply
    from tests import glb_fixture

    scene = bpy.data.scenes.new("eachlabs_look")
    build = scene_build.SceneBuild(scene, "look-run")
    try:
        check("look: the scene is built", _step(build, LOOK_CODE).get("ok"))
        seen = build.read_scene()
        check("look: a sign facing the camera reads right", not seen.get("mirrored_text"),
              json.dumps(seen.get("mirrored_text")))
        bpy.data.objects["Shop sign"].rotation_euler = (1.5708, 0, 3.1416)  # its back to the camera
        found = build.read_scene().get("mirrored_text")
        check("look: a sign whose back faces the camera reads backwards", found == ["Shop sign"], json.dumps(found))
        view = build.camera_view()
        blockers = [b["name"] for f in view.get("frames", []) for b in f.get("near_blockers", [])]
        check("look: the post in front of the lens is a near blocker", "Post" in blockers, json.dumps(view)[:400])
        path = os.path.join(WORK, "haven.png")
        with open(path, "wb") as fh:
            fh.write(glb_fixture.png())
        mat = bpy.data.materials.new("Shop plaster")
        build.tag(mat)
        haven_apply.set_maps(build, "Shop plaster", {"color": path, "roughness": path, "normal": path}, 1.5)
        nodes = mat.node_tree.nodes
        bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
        check("look: a free texture fills colour, roughness and normal",
              all(bsdf.inputs[k].is_linked for k in ("Base Color", "Roughness", "Normal")))
        world = haven_apply.set_sky(build, path, 0.8, 90)
        check("look: a free sky lights the scene on a world of the chat's own",
              scene.world is not None and scene.world.name == world and build.owns(scene.world)
              and any(n.type == "TEX_ENVIRONMENT" for n in scene.world.node_tree.nodes))
        tree = scene.world.node_tree
        out = next(n for n in tree.nodes if n.type == "OUTPUT_WORLD")
        mix = out.inputs["Surface"].links[0].from_node
        fac = mix.inputs["Fac"].links[0] if mix.inputs["Fac"].is_linked else None
        seen = mix.inputs[2].links[0].from_node if mix.inputs[2].is_linked else None
        lit = mix.inputs[1].links[0].from_node if mix.inputs[1].is_linked else None
        check("look: the camera sees a gradient sky, while the sky picture lights the scene",
              mix.type == "MIX_SHADER" and fac is not None and fac.from_socket.name == "Is Camera Ray"
              and seen is not None and seen.type == "BACKGROUND" and seen.inputs["Color"].links[0].from_node.type
              == "VALTORGB" and lit is not None and lit.inputs["Color"].links[0].from_node.type == "TEX_ENVIRONMENT",
              "%s %s %s" % (mix.type, seen and seen.type, lit and lit.type))
    finally:
        for obj in list(scene.objects):
            bpy.data.objects.remove(obj)
        bpy.data.scenes.remove(scene)
