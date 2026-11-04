"""The instructions' Blender 4 and Blender 5 lines, run as steps in this Blender."""

import bpy

from eachlabs import chat_loop
from tests.smoke.common import _step, check


NOTES_COMMON = """# The world and material lines of the instructions
world = bpy.data.worlds.new("Notes world")
if world.node_tree is None:
    world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
bg.inputs["Color"].default_value = (0.02, 0.03, 0.06, 1)
bg.inputs["Strength"].default_value = 0.3
scene.world = world
mat = bpy.data.materials.new("Notes glow")
if mat.node_tree is None:
    mat.use_nodes = True
bsdf = mat.node_tree.nodes.get("Principled BSDF")
bsdf.inputs["Base Color"].default_value = (0.9, 0.6, 0.3, 1)
bsdf.inputs["Transmission Weight"].default_value = 0.0
bsdf.inputs["Emission Color"].default_value = (1.0, 0.6, 0.3, 1)
bsdf.inputs["Emission Strength"].default_value = 12.0
mat.diffuse_color = (0.9, 0.6, 0.3, 1)
sky = world.node_tree.nodes.new("ShaderNodeTexSky")
ids = [i.identifier for i in scene.render.bl_rna.properties["engine"].enum_items]
engine = [i for i in ids if "EEVEE" in i][0]
scene.render.engine = engine
mover = bpy.data.objects.new("Notes mover", None)
scene.collection.objects.link(mover)
mover.location = (0, 0, 0)
mover.keyframe_insert("location", frame=1)
mover.location = (0, 4, 0)
mover.keyframe_insert("location", frame=24)
print(engine, hasattr(world, "diffuse_color"), hasattr(mover.animation_data.action, "fcurves"))
"""

NOTES_FOUR = """# The Blender 4 lines
for name in ("NISHITA", "HOSEK_WILKIE", "PREETHAM"):
    bpy.data.worlds["Notes world"].node_tree.nodes["Sky Texture"].sky_type = name
action = bpy.data.objects["Notes mover"].animation_data.action
print(len(action.fcurves), hasattr(action, "layers"), hasattr(scene, "node_tree"))
"""

NOTES_FIVE = """# The Blender 5 lines
for name in ("SINGLE_SCATTERING", "MULTIPLE_SCATTERING", "PREETHAM", "HOSEK_WILKIE"):
    bpy.data.worlds["Notes world"].node_tree.nodes["Sky Texture"].sky_type = name
sky = bpy.data.worlds["Notes world"].node_tree.nodes["Sky Texture"]
names = [i.identifier for i in sky.bl_rna.properties["sky_type"].enum_items]
print("NISHITA" in names, hasattr(scene, "node_tree"))
"""

# Every API line of the look rules: bevels, surface variation, soft shadows, motion blur.
NOTES_LOOKS = """# The look lines of the instructions
mesh = bpy.data.meshes.new("Notes block")
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=1.0)
bm.to_mesh(mesh)
bm.free()
block = bpy.data.objects.new("Notes block", mesh)
scene.collection.objects.link(block)
bevel = block.modifiers.new("Bevel", "BEVEL")
bevel.width = 0.02
bevel.segments = 3
mat = bpy.data.materials.new("Notes rough")
if mat.node_tree is None:
    mat.use_nodes = True
nodes, links = mat.node_tree.nodes, mat.node_tree.links
bsdf = nodes.get("Principled BSDF")
noise = nodes.new("ShaderNodeTexNoise")
noise.inputs["Scale"].default_value = 80.0
ranged = nodes.new("ShaderNodeMapRange")
ranged.inputs["To Min"].default_value = 0.45
ranged.inputs["To Max"].default_value = 0.55
links.new(noise.outputs["Fac"], ranged.inputs["Value"])
links.new(ranged.outputs["Result"], bsdf.inputs["Roughness"])
bump = nodes.new("ShaderNodeBump")
bump.inputs["Strength"].default_value = 0.1
links.new(noise.outputs["Fac"], bump.inputs["Height"])
links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
block.data.materials.append(mat)
point = bpy.data.lights.new("Notes point", "POINT")
point.shadow_soft_size = 0.3
point.use_shadow_jitter = True
area = bpy.data.lights.new("Notes area", "AREA")
area.size = 2.0
area.use_shadow_jitter = True
for data in (point, area):
    lamp = bpy.data.objects.new(data.name, data)
    scene.collection.objects.link(lamp)
scene.render.use_motion_blur = True
scene.render.motion_blur_shutter = 0.5
print(len(block.modifiers), len(mat.node_tree.links) >= 4, scene.render.use_motion_blur)
"""

NOTES_LOOKS_FOUR = """# The Blender 4 look lines
scene.eevee.use_gtao = True
scene.eevee.gtao_distance = 1.0
print(scene.eevee.use_gtao, hasattr(scene.eevee, "use_fast_gi"))
"""

NOTES_LOOKS_FIVE = """# The Blender 5 look lines
scene.eevee.use_fast_gi = True
print(scene.eevee.use_fast_gi, hasattr(scene.eevee, "use_gtao"), hasattr(scene.eevee, "use_bloom"))
"""


def test_version_notes():
    """Every API line of the version notes the model gets runs in this Blender, through the rule filter."""
    from eachlabs import scene_build

    scene = bpy.data.scenes.new("eachlabs_notes")
    build = scene_build.SceneBuild(scene, "notes")
    five = bpy.app.version >= (5, 0, 0)
    common = _step(build, NOTES_COMMON)
    check("version notes: the world, material, engine and keyframe lines run",
          common.get("ok") and common.get("output") == "%s False %s\n" % (
              "BLENDER_EEVEE" if five else "BLENDER_EEVEE_NEXT", not five)
          and scene.world.name == "Notes world" and scene.frame_end >= 1, str(common)[:400])
    own = _step(build, NOTES_FIVE if five else NOTES_FOUR)
    check("version notes: the %s lines run" % ("Blender 5" if five else "Blender 4"),
          own.get("ok") and own.get("output") == ("False False\n" if five else "3 False True\n"), str(own)[:400])
    looks = _step(build, NOTES_LOOKS)
    check("version notes: the look lines run (bevel, surface noise, soft shadows, motion blur)",
          looks.get("ok") and looks.get("output") == "1 True True\n", str(looks)[:400])
    own_looks = _step(build, NOTES_LOOKS_FIVE if five else NOTES_LOOKS_FOUR)
    check("version notes: this version's ambient occlusion line runs",
          own_looks.get("ok") and own_looks.get("output") == ("True False False\n" if five else "True False\n"),
          str(own_looks)[:400])
    light_text = chat_loop.INSTRUCTIONS["light"]
    check("version notes: the rules name soft shadows, glow, ambient occlusion and motion blur",
          "use_shadow_jitter" in light_text and "no bloom setting" in light_text
          and "use_motion_blur" in light_text and "Ambient occlusion" in light_text)
    text = chat_loop.system_text(chat_loop.INSTRUCTIONS["light"], bpy.app.version)
    check("version notes: the instructions carry this version's notes",
          ("This is Blender 5." in text) == five and ("This is Blender 4." in text) == (not five))
    for obj in [o for o in bpy.data.objects if o.get(scene_build.RUN) == "notes"]:
        bpy.data.objects.remove(obj, do_unlink=True)
    coll = bpy.data.collections.get(build.collection_name or "")
    if coll is not None:
        bpy.data.collections.remove(coll)
    bpy.data.scenes.remove(scene)
