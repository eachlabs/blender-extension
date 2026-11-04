import textwrap
import types
import unittest
from unittest import mock

from eachlabs import code_check as cc, thread_safety


def refused_rule(code):
    try:
        cc.check(textwrap.dedent(code))
    except cc.Refused as exc:
        return exc.rule
    return None


class RefusedTest(unittest.TestCase):
    def assertRefused(self, rule, code):
        self.assertEqual(refused_rule(code), rule, code)

    def test_refusals_say_what_to_use_instead(self):
        def text(code):
            try:
                cc.check(code)
            except cc.Refused as exc:
                return str(exc)
            return ""
        self.assertIn("`re` is not allowed; use str methods such as split", text("import re"))
        self.assertIn("`collections` is not allowed; use a plain dict or list", text("from collections import Counter"))
        self.assertIn("`numpy` is not allowed. Allowed imports: bpy", text("import numpy"))
        self.assertIn('like setattr(obj, "location", value); write one line per attribute',
                      text("setattr(o, name, 1)"))
        self.assertIn('like getattr(obj, "location"); write one line per attribute', text("getattr(o, name)"))

    def test_parent_inverse_from_a_fresh_world_matrix_names_attach(self):
        self.assertRefused("parenting", "part.parent = root\npart.matrix_parent_inverse = root.matrix_world.inverted()")
        self.assertRefused("parenting", "o.matrix_parent_inverse = parent.matrix_world.inverted_safe()")
        try:
            cc.check("ob.matrix_parent_inverse = p.matrix_world.inverted()")
        except cc.Refused as exc:
            self.assertIn("attach(part, root)", str(exc))
        self.assertIsNone(refused_rule("attach(part, root)"))
        self.assertIsNone(refused_rule("part.matrix_parent_inverse = root.matrix_basis.inverted()"))
        self.assertIsNone(refused_rule("m = root.matrix_world.inverted()"))

    def test_imports_outside_the_list(self):
        for code in ("import statistics", "import re", "from collections import deque",
                     "from bpy_extras.object_utils import world_to_camera_view", "import json as j",
                     "from . import scene_build", "from bpy import *", "import urllib.request"):
            self.assertRefused("import", code)

    def test_system_modules(self):
        for code in ("import os", "import sys", "import subprocess", "import socket", "import shutil",
                     "import pathlib", "import importlib", "import ctypes", "from os import path",
                     "bpy.utils.os.listdir('.')", "x = os", "from bpy import sys",
                     "getattr(bpy.utils, 'os')"):
            self.assertRefused("system-module", code)

    def test_blocked_names(self):
        for name in sorted(cc.BLOCKED_NAMES - {"__import__"}):
            self.assertRefused("blocked-name", "%s()" % name)
        self.assertRefused("blocked-name", "f = open")
        self.assertRefused("blocked-name", "__import__('os')")

    def test_dynamic_attributes(self):
        self.assertRefused("dynamic-attribute", "name = 'location'\ngetattr(bpy.context.object, name)")
        self.assertRefused("dynamic-attribute", "setattr(bpy.context.object, 'na' + 'me', 1)")
        self.assertRefused("dynamic-attribute", "delattr(bpy.context.object, n)")
        self.assertRefused("dynamic-attribute", "g = getattr")

    def test_dunders(self):
        for code in ("().__class__.__bases__", "bpy.__dict__", "x = __builtins__",
                     "getattr(bpy, '__loader__')", "from bpy import __path__", "super().__init__()"):
            self.assertRefused("dunder", code)

    def test_blocked_bpy_paths(self):
        for code in ("bpy.ops.wm.quit_blender()", "bpy.ops.wm.save_as_mainfile(check_existing=False)",
                     "bpy.ops.preferences.addon_enable(module='x')",
                     "bpy.ops.extensions.package_install()", "bpy.data.libraries.load('/tmp/x.blend')",
                     "bpy.utils.register_class(object)", "bpy.utils.unregister_class(object)",
                     "bpy.app.handlers.frame_change_pre.append(print)", "bpy.app.timers.register(print)",
                     "from bpy.app import handlers", "from bpy.app.handlers import persistent",
                     "import bpy.app.timers", "ops = bpy.ops\nops.wm.quit_blender()",
                     "from bpy import ops as o\no.wm.quit_blender()", "import bpy as b\nb.ops.wm.read_homefile()",
                     "w = getattr(bpy.ops, 'wm')", "u = bpy.utils\nu.register_class(object)"):
            self.assertRefused("blocked-api", code)

    def test_code_that_runs_other_code(self):
        for code in ("t = bpy.data.texts.new('x')", "d = bpy.data\nd.texts['x'].as_module()",
                     "bpy.utils.execfile('x.py')", "bpy.ops.text.run_script()", "bpy.ops.script.reload()",
                     "bpy.app.driver_namespace['f'] = print",
                     "fc = obj.driver_add('location', 0)\nfc.driver.expression = 'frame'",
                     "setattr(fc.driver, 'expression', 'frame')", "x.use_scripts_auto_execute = True",
                     "x.use_autoexec = True"):
            self.assertRefused("runs-code", code)

    def test_file_access(self):
        for code in ("bpy.ops.export_scene.gltf()", "bpy.ops.import_scene.obj()", "bpy.ops.image.open()",
                     "bpy.ops.file.pack_all()", "bpy.ops.sound.open()", "bpy.ops.mesh.import_x()",
                     "bpy.ops.object.load_reference_image()", "img.save()",
                     "bpy.data.images['Render Result'].save_render('x.png')", "img.pack()", "img.unpack()",
                     "bpy.data.images.load('/tmp/x.png')", "img.filepath = '/tmp/x.png'",
                     "img.filepath_raw = 'x'", "scene.render.filepath = '/tmp/out'",
                     "bpy.data.images.new('x', 4, 4).filepath = 'y'", "node.directory = 'x'",
                     "f(filepath='/tmp/x')", "f(filename='x')", "bpy.ops.mesh.primitive_cube_add(**opts)"):
            self.assertRefused("file-access", code)

    def test_ops_outside_the_allowlist(self):
        for code in ("bpy.ops.render.render(write_still=True)", "bpy.ops.render.render()",
                     "bpy.ops.screen.animation_play()", "bpy.ops.outliner.orphans_purge()",
                     "bpy.ops.ed.undo()", "getattr(bpy.ops, 'sculpt')"):
            self.assertRefused("ops-module", code)

    def test_credentials(self):
        for code in ('key = bpy.context.preferences.addons["eachlabs"].preferences.api_key',
                     "p = bpy.context.preferences", "C = bpy.context\nprint(C.preferences)",
                     "bpy.types.AddonPreferences", "addons = x.addons.get('eachlabs')",
                     "token = 1", "x.secret_value", "prefs['api_key']", "getattr(p, 'password')",
                     "my_apikey = 'x'"):
            self.assertRefused("credentials", code)
        with self.assertRaises(cc.Refused) as ctx:
            cc.check("bpy.context.preferences.addons['eachlabs'].preferences.api_key")
        self.assertIn("the chat's code cannot read add-on settings", str(ctx.exception))

    def test_broad_except(self):
        for code in ("try:\n    pass\nexcept:\n    pass", "try:\n    pass\nexcept BaseException:\n    pass",
                     "try:\n    pass\nexcept (ValueError, BaseException):\n    pass",
                     "while True:\n    try:\n        pass\n    finally:\n        continue",
                     "def f():\n    try:\n        pass\n    finally:\n        return 1"):
            self.assertRefused("broad-except", code)
        self.assertIsNone(cc.check("try:\n    pass\nexcept Exception:\n    pass\nfinally:\n    x = 1"))

    def test_private_names_and_attributes(self):
        for code in ("bpy.utils._os.system('true')", "bpy.utils._sys.modules['os']", "bpy.path._os.listdir('/')",
                     "random._os.system('true')", "bpy.utils._bpy.data.objects",
                     "getattr(bpy.utils, '_os')", "bpy.utils._addon_utils.disable('x')", "_x = 1",
                     "def _helper():\n    pass", "obj._internal", "'{0.ops.x}'.format(obj)",
                     "'{0[0]}'.format(obj)", "x = d['_hidden']"):
            self.assertRefused("private", code)

    def test_frame_attributes(self):
        for name in sorted(cc.FRAME_ATTRS):
            self.assertRefused("frame-access", "x = thing.%s" % name)
        self.assertRefused("frame-access", "g = (x for x in [1])\nf = g.gi_frame.f_builtins['open']")

    def test_module_values_only_start_a_chain(self):
        for code in ("o = [bpy.ops][0]\no.wm.quit_blender()", "for o in [bpy.ops]:\n    pass",
                     "o, = (bpy.ops,)", "def f():\n    return bpy.ops", "(bpy.ops if 1 else 0)",
                     "(lambda o=bpy.ops: o)()", "a = [bpy.app][0]", "x = {'a': bpy.data}", "x = {bpy.types}",
                     "x = [m for m in (bpy.utils,)]", "f(bpy.props)", "f(*bpy.path)", "f(**bpy.context)",
                     "'{0}'.format(bpy)", "x = bpy.ops.mesh, 1", "for o in bpy.ops:\n    pass",
                     "f(math)", "f(bmesh.ops)", "y = (o := bpy.ops)", "bpy"):
            self.assertRefused("module-value", code)

    def test_blocked_attribute_names_anywhere(self):
        cases = {"blocked-api": ("x.wm", "x.handlers", "x.timers", "x.libraries.write('x', set())", "x.msgbus",
                                 "x.register_class(c)", "x.unregister_module(c)", "x.register_tool(c)",
                                 "bpy.types.WM_OT_quit_blender",
                                 "bpy.msgbus.subscribe_rna(key=k, owner=o, args=(), notify=f)"),
                 "runs-code": ("x.driver_add('location')", "x.driver_namespace", "print(x.expression)",
                               "x.as_module()", "x.execfile('a')", "x.run_script()"),
                 "file-access": ("x.save()", "x.save_as()", "x.save_render", "x.pack()", "x.unpack()",
                                 "print(x.filepath)", "x.filepath_raw", "x.directory", "x.filename",
                                 "setattr(r, 'filepath', '/tmp/x')")}
        for rule, codes in cases.items():
            for code in codes:
                self.assertRefused(rule, code)

    def test_deferred_code(self):
        for code in ("bpy.types.SpaceView3D.draw_handler_add(f, (), 'WINDOW', 'POST_VIEW')",
                     "h = x.draw_handler_remove(h, 'WINDOW')",
                     "p = bpy.props.FloatProperty(update=lambda s, c: None)",
                     "p = bpy.props.IntProperty(get=g, set=s)",
                     "bpy.types.Object.x = 1", "setattr(bpy.types.Object, 'x', 1)",
                     "T = bpy.types\nT.Scene.y = 2"):
            self.assertRefused("deferred-code", code)

    def test_time_limit_escapes(self):
        for code in ("class S:\n    def __exit__(self, *a):\n        return True",
                     "class S:\n    async def __aexit__(self, *a):\n        return True",
                     "class D:\n    def __del__(self):\n        pass", "class E:\n    def __enter__(self):\n        pass"):
            self.assertRefused("dunder", code)
        for code in ("B = BaseException", "x = GeneratorExit", "raise KeyboardInterrupt", "raise SystemExit(1)",
                     "E = (Exception,)\ntry:\n    pass\nexcept E:\n    pass",
                     "try:\n    pass\nexcept x.Error:\n    pass",
                     "try:\n    pass\nexcept (Exception, err):\n    pass"):
            self.assertRefused("broad-except", code)
        self.assertIsNone(cc.check("class P:\n    def __init__(self):\n        pass\n    def __repr__(self):\n"
                                   "        return 'p'\n    def __str__(self):\n        return 'p'"))

    def test_syntax(self):
        try:
            cc.check("for i in range(3)\n    pass")
        except cc.Refused as exc:
            self.assertEqual(exc.rule, "syntax")
            self.assertTrue(exc.message.startswith("line 1: "), exc.message)
        else:
            self.fail("no refusal")

    def test_message_names_the_rule_and_the_allowed_imports(self):
        with self.assertRaises(cc.Refused) as ctx:
            cc.check("import statistics")
        text = str(ctx.exception)
        self.assertIn("import rule", text)
        self.assertIn("statistics", text)
        self.assertIn("bpy, bmesh, mathutils, math, random", text)
        self.assertIn("line 1", text)


ALLOWED = {
    "bmesh mesh": """
        import bpy, bmesh
        from mathutils import Vector, Matrix, Euler, Quaternion, Color
        mesh = bpy.data.meshes.new("eachlabs_tower")
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.translate(bm, vec=Vector((0, 0, 0.5)), verts=bm.verts)
        bm.to_mesh(mesh)
        bm.free()
        obj = bpy.data.objects.new("eachlabs_tower", mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.rotation_euler = Euler((0, 0, 0.3))
        """,
    "material nodes": """
        mat = bpy.data.materials.new("eachlabs_glass")
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        bsdf = nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = (0.8, 0.2, 0.1, 1.0)
        bsdf.inputs["Emission Strength"].default_value = 4.0
        noise = nodes.new("ShaderNodeTexNoise")
        mat.node_tree.links.new(noise.outputs["Fac"], bsdf.inputs["Roughness"])
        """,
    "keyframes": """
        cam = bpy.data.objects.new("eachlabs_cam", bpy.data.cameras.new("eachlabs_cam"))
        bpy.context.scene.collection.objects.link(cam)
        for frame, x in ((1, 0.0), (96, 5.0)):
            cam.location.x = x
            cam.keyframe_insert(data_path="location", frame=frame)
        bpy.context.scene.frame_end = 96
        """,
    "math": """
        import math as m
        import random
        from mathutils import noise
        from math import *
        random.seed(4)
        points = [(m.cos(a) * 3, m.sin(a) * 3, random.uniform(0, 1)) for a in [i * pi / 8 for i in range(16)]]
        q = mathutils.Quaternion((0, 0, 1), m.radians(45))
        v = q @ mathutils.Vector((1, 0, 0))
        value = getattr(bpy.context.scene, "frame_end")
        setattr(bpy.context.scene, "frame_start", 1)
        if hasattr(v, "x"):
            print(round(v.x, 3))
        if __name__ == "__main__":
            pass
        """,
    "helper class": """
        class Builder:
            def __init__(self, name):
                self.name = name
        Builder("eachlabs_x")
        """,
    "allowed operators": """
        bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 1))
        bpy.ops.object.shade_smooth()
        bpy.ops.object.modifier_add(type="BEVEL")
        bpy.ops.transform.translate(value=(1, 0, 0))
        bpy.ops.anim.keyframe_insert()
        print(bpy.app.version, bpy.context.scene.frame_end)
        for obj in bpy.data.objects:
            obj.hide_render = False
        ops = bpy.ops
        ops.object.select_all(action="DESELECT")
        if hasattr(bpy.ops, "mesh"):
            pass
        try:
            x = 1 / 0
        except (ZeroDivisionError, KeyError) as e:
            print("{:.2f} {}".format(1.0, e))
        print(f"{bpy.context.scene.name}")
        for _ in range(2):
            pass
        """,
}


class RedactTest(unittest.TestCase):
    def test_secrets_replaced_everywhere(self):
        key = "sk-live-0123456789"
        value = {"summary": {"new_objects": [{"name": "eachlabs_" + key, "location": [1.0, 2.0]}],
                             "touched_other": (key,)},
                 "error": "Traceback\nValueError: %s" % key, key: 3, "n": 4}
        out = cc.redact(value, [key, "", None, "abc"])
        self.assertNotIn(key, repr(out))
        self.assertEqual(out["summary"]["new_objects"][0]["name"], "eachlabs_[redacted]")
        self.assertEqual(out["summary"]["touched_other"], ("[redacted]",))
        self.assertEqual(out["summary"]["new_objects"][0]["location"], [1.0, 2.0])
        self.assertEqual(out["[redacted]"], 3)
        self.assertEqual(out["n"], 4)

    def test_no_secrets_leaves_the_value(self):
        value = {"a": "abc"}
        self.assertIs(cc.redact(value, []), value)
        self.assertEqual(cc.redact("abc", ["abc"]), "abc")  # too short to replace safely


OVERRIDES = (
    "with bpy.context.temp_override(area=None):\n    bpy.ops.object.select_all(action='SELECT')",
    "C = bpy.context\nwith C.temp_override():\n    pass",
    "o = getattr(bpy.context, 'temp_override')",
    # Blender 4.2's own operators that call bpy.ops inside temp_override
    "bpy.ops.object.quick_smoke()",
    "bpy.ops.object.quick_fur(density='LOW')",
    "o = bpy.ops.object\no.quick_explode()",
    "ops = bpy.ops\nops.object.quick_liquid()",
    "from bpy.ops import object as obj_ops\nobj_ops.quick_smoke()",
    "f = getattr(bpy.ops.object, 'quick_fur')",
    "bpy.ops.object.quick_liquid.poll()",
)


class TempOverrideTest(unittest.TestCase):
    """Python before 3.12 (Blender 4.2) refuses temp_override and the operators that use it; the version check
    is patched, not ``sys``."""

    def test_refused_before_python_3_12(self):
        with mock.patch.object(thread_safety, "override_races", return_value=True):
            for code in OVERRIDES:
                with self.subTest(code):
                    self.assertEqual(refused_rule(code), "context-override")
            for code in (OVERRIDES[0], OVERRIDES[3]):
                with self.assertRaises(cc.Refused) as ctx:
                    cc.check(code)
                text = str(ctx.exception)
                self.assertIn("overrides Blender's context", text)
                self.assertIn("call operators without temp_override", text)
                self.assertIn("bpy.data and bmesh", text)
            self.assertIn("bpy.ops.object.quick_smoke", text)
            self.assertIsNone(refused_rule("bpy.ops.object.select_all(action='SELECT')"))

    def test_allowed_from_python_3_12(self):
        with mock.patch.object(thread_safety, "override_races", return_value=False):
            for code in OVERRIDES:
                with self.subTest(code):
                    self.assertIsNone(refused_rule(code))

    def test_blender_pythons(self):
        for version, races in (((3, 11, 7), True), ((3, 11, 13), True), ((3, 12, 0), False), ((3, 13, 13), False)):
            with self.subTest(version), mock.patch.object(thread_safety, "sys",
                                                          types.SimpleNamespace(version_info=version)):
                self.assertIs(thread_safety.override_races(), races)


class AllowedTest(unittest.TestCase):
    def test_scene_building_code_passes(self):
        for name, code in ALLOWED.items():
            with self.subTest(name):
                self.assertIsNone(cc.check(textwrap.dedent(code)))


if __name__ == "__main__":
    unittest.main()
