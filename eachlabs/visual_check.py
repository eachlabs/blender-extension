"""The visual check: a small render of the scene for the chat model to look at. Main thread only.

The render is ``bpy.ops.render.render(write_still=True)`` with no ``temp_override``, called from the main-thread
queue while the chat worker waits for its answer. On Blender 4.2 only operators inside ``temp_override`` race a
running Python thread (see "Blender 4.2 and threads" in docs/architecture.md), so this is safe there too.

The scene's own render settings are lowered for the frame and put back in a ``finally``. The PNG lives in a
temporary folder only until it is read.
"""

import base64
import math
import os
import shutil
import tempfile
import time

import bpy
from mathutils import Vector

from .checks import exposure
from . import compat, render_export

LONG_SIDE = 640  # pixels of the frame's long side; the scene's aspect is kept
SAMPLES = 8  # EEVEE render samples
MOVED_M = 0.1  # metres the camera moves between the first and the last frame that count as a camera move
TURNED_DEG = 2.0  # or degrees it turns
OVERVIEW = "eachlabs_overview"
OVERVIEW_LENS = 35.0
OVERVIEW_ANGLES = (30.0, 30.0)  # degrees: around Z from the front, and up from the ground

# (owner path from the scene, attribute) of every setting the render changes.
_SETTINGS = (
    ("render", "engine"),
    ("render", "resolution_x"),
    ("render", "resolution_y"),
    ("render", "resolution_percentage"),
    ("render", "filepath"),
    ("render", "use_file_extension"),
    ("render", "use_motion_blur"),
    ("render", "use_border"),
    ("render", "use_compositing"),
    ("render", "use_sequencer"),
    ("render", "film_transparent"),
    ("render.image_settings", "media_type"),
    ("render.image_settings", "file_format"),
    ("render.image_settings", "color_mode"),
    ("render.image_settings", "color_depth"),
    ("render.image_settings", "compression"),
    ("eevee", "taa_render_samples"),
    ("", "camera"),
)


def _owner(scene, path):
    owner = scene
    for part in filter(None, path.split(".")):
        owner = getattr(owner, part)
    return owner


def _snapshot(scene):
    saved = []
    for path, attr in _SETTINGS:
        owner = _owner(scene, path)
        if hasattr(owner, attr):
            saved.append((path, attr, getattr(owner, attr)))
    return saved


def _restore(scene, saved):
    for path, attr, value in saved:
        try:
            setattr(_owner(scene, path), attr, value)
        except (AttributeError, TypeError, ValueError, ReferenceError):
            pass


def _eevee(scene):
    engines = [e.identifier for e in scene.render.bl_rna.properties["engine"].enum_items]
    return next((e for e in engines if "EEVEE" in e), scene.render.engine)


def _lower(scene, folder):
    render = scene.render
    render.engine = _eevee(scene)
    width, height = max(1, render.resolution_x), max(1, render.resolution_y)
    scale = LONG_SIDE / float(max(width, height))
    render.resolution_x, render.resolution_y = max(2, round(width * scale)), max(2, round(height * scale))
    render.resolution_percentage = 100
    render.use_motion_blur = False  # EEVEE renders a blurred frame several times over
    render.use_border = False
    render.use_compositing = False
    render.use_sequencer = False
    render.film_transparent = False  # the model must see the world, not black
    settings = render.image_settings
    compat.set_image_output(settings, "PNG")
    settings.color_mode, settings.color_depth, settings.compression = "RGB", "8", 50
    render.use_file_extension = False
    eevee = getattr(scene, "eevee", None)
    if eevee is not None and hasattr(eevee, "taa_render_samples"):
        eevee.taa_render_samples = min(eevee.taa_render_samples, SAMPLES)
    render.filepath = os.path.join(folder, "frame.png")


def _overview(build, scene):
    """A temporary camera that sees everything the chat built from above at an angle, or ``None`` when the chat
    built no geometry yet."""
    objects = build.frame_targets()
    corners = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
    if not corners:
        return None
    low = Vector([min(c[i] for c in corners) for i in range(3)])
    high = Vector([max(c[i] for c in corners) for i in range(3)])
    centre, radius = (low + high) / 2, max((high - low).length / 2, 1.0)
    data = bpy.data.cameras.new(OVERVIEW)
    data.lens = OVERVIEW_LENS
    cam = bpy.data.objects.new(OVERVIEW, data)
    scene.collection.objects.link(cam)
    render = scene.render
    aspect = render.resolution_x / float(max(1, render.resolution_y))
    half = data.angle / 2  # across the long side
    narrow = math.atan(math.tan(half) / aspect) if aspect >= 1 else half
    distance = radius / math.sin(narrow) * 1.05
    turn, up = (math.radians(a) for a in OVERVIEW_ANGLES)
    toward = Vector((math.sin(turn) * math.cos(up), -math.cos(turn) * math.cos(up), math.sin(up)))
    cam.location = centre + toward * distance
    cam.rotation_euler = (-toward).to_track_quat("-Z", "Y").to_euler()
    data.clip_start, data.clip_end = max(0.01, distance / 1000), distance + radius * 4
    scene.camera = cam
    return cam


def _drop(cam):
    if cam is None:
        return
    data = cam.data
    bpy.data.objects.remove(cam)
    if data is not None and data.users == 0:
        bpy.data.cameras.remove(data)


def _moves(scene, cam):
    """True when the camera moves or turns between the scene's first and last frame (also through a parent)."""
    poses = []
    layer = scene.view_layers[0]
    for frame in (scene.frame_start, scene.frame_end):
        scene.frame_set(frame)
        layer.update()  # a scene that is not in a window is evaluated only when asked
        poses.append(cam.evaluated_get(layer.depsgraph).matrix_world.copy())
    shift = (poses[1].translation - poses[0].translation).length
    turn = poses[0].to_quaternion().rotation_difference(poses[1].to_quaternion()).angle
    return shift >= MOVED_M or math.degrees(turn) >= TURNED_DEG


# The close-up of one object for the detail stage: the object alone, in plain shading, from four sides.
CLOSE_SIZE = (512, 384)
CLOSE_LENS = 50.0
# Degrees around Z from the front, and up from the ground: four sides, so the back of a building is seen too.
CLOSE_VIEWS = ((35.0, 20.0), (125.0, 20.0), (215.0, 20.0), (305.0, 20.0))
_CLOSE_SETTINGS = (
    ("display.shading", "light"),
    ("display.shading", "color_type"),
    ("display.shading", "show_cavity"),
    ("display.shading", "cavity_type"),
    ("display.shading", "show_shadows"),
    ("display.shading", "show_object_outline"),
    ("display", "render_aa"),
)


def _close_camera(scene, corners, turn, up):
    low = Vector([min(c[i] for c in corners) for i in range(3)])
    high = Vector([max(c[i] for c in corners) for i in range(3)])
    centre, radius = (low + high) / 2, max((high - low).length / 2, 0.05)
    data = bpy.data.cameras.new(OVERVIEW)
    data.lens = CLOSE_LENS
    cam = bpy.data.objects.new(OVERVIEW, data)
    scene.collection.objects.link(cam)
    aspect = CLOSE_SIZE[0] / float(CLOSE_SIZE[1])
    half = data.angle / 2
    narrow = math.atan(math.tan(half) / aspect) if aspect >= 1 else half
    distance = radius / math.sin(narrow) * 1.1
    turn, up = math.radians(turn), math.radians(up)
    toward = Vector((math.sin(turn) * math.cos(up), -math.cos(turn) * math.cos(up), math.sin(up)))
    cam.location = centre + toward * distance
    cam.rotation_euler = (-toward).to_track_quat("-Z", "Y").to_euler()
    data.clip_start, data.clip_end = max(0.001, distance / 1000), distance + radius * 4
    scene.camera = cam
    return cam


def _true_colours(objects):
    """Workbench's material colour is each material's viewport colour, which code that sets only the Base Color
    leaves grey or stale. For a close-up, the viewport colour of each material on ``objects`` takes its plain
    Base Color; returns what to put back with ``_put_colours``."""
    from .checks import colours

    saved, seen = [], set()
    for obj in objects:
        for slot in getattr(obj, "material_slots", ()):
            mat = slot.material
            if mat is None or mat.name in seen:
                continue
            seen.add(mat.name)
            base = colours._base_colour(mat)
            if tuple(mat.diffuse_color[:3]) != tuple(base):
                saved.append((mat, tuple(mat.diffuse_color)))
                mat.diffuse_color = tuple(base) + (mat.diffuse_color[3],)
    return saved


def _put_colours(saved):
    for mat, colour in saved:
        try:
            mat.diffuse_color = colour
        except ReferenceError:
            pass


def render_object(build, name):
    """Render the chat's object ``name`` and its parts alone, from four sides, in Workbench solid shading.

    Returns ``{"images": [data URL], "seconds": [s]}``; ``images`` is empty with a ``reason`` when nothing could be
    rendered. Every other object is hidden from the render for the frames and shown again in a ``finally``."""
    if render_export.busy() or bpy.app.is_job_running("RENDER"):
        return {"images": [], "reason": "another render is running"}
    scene = build.scene
    root = scene.objects.get(name)
    if root is None or not build.owns(root):
        return {"images": [], "reason": "%s is not one of the chat's objects" % name}
    tree = [root] + list(root.children_recursive)
    keep = {o.session_uid for o in tree}
    corners = [o.matrix_world @ Vector(c) for o in tree if o.type in ("MESH", "CURVE", "SURFACE", "FONT", "META")
               and not o.hide_render for c in o.bound_box]
    if not corners:
        return {"images": [], "reason": "%s has no geometry to show" % name}
    current, subframe = scene.frame_current, scene.frame_subframe
    saved = _snapshot(scene)
    shading = []
    for path, attr in _CLOSE_SETTINGS:
        owner = _owner(scene, path)
        if hasattr(owner, attr):
            shading.append((path, attr, getattr(owner, attr)))
    hidden = [(o, o.hide_render) for o in scene.objects if o.session_uid not in keep]
    folder = tempfile.mkdtemp(prefix="eachlabs-close-")
    cameras = []
    out = {"images": [], "seconds": []}
    coloured = []
    try:
        coloured = _true_colours(tree)
        _lower(scene, folder)
        engines = [e.identifier for e in scene.render.bl_rna.properties["engine"].enum_items]
        if "BLENDER_WORKBENCH" in engines:
            scene.render.engine = "BLENDER_WORKBENCH"
        scene.render.resolution_x, scene.render.resolution_y = CLOSE_SIZE
        display = scene.display.shading
        display.light, display.color_type = "STUDIO", "MATERIAL"
        display.show_cavity, display.show_shadows, display.show_object_outline = True, True, False
        if hasattr(display, "cavity_type"):
            display.cavity_type = "BOTH"
        for obj, _was in hidden:
            obj.hide_render = True
        for turn, up in CLOSE_VIEWS:
            cameras.append(_close_camera(scene, corners, turn, up))
            started = time.monotonic()
            bpy.ops.render.render(write_still=True, scene=scene.name)
            out["seconds"].append(round(time.monotonic() - started, 2))
            with open(scene.render.filepath, "rb") as handle:
                data = handle.read()
            os.remove(scene.render.filepath)
            out["images"].append("data:image/png;base64," + base64.b64encode(data).decode("ascii"))
        return out
    except (RuntimeError, OSError, ReferenceError) as exc:  # the close-up is extra: the run goes on without it
        return {"images": [], "reason": str(exc) or type(exc).__name__}
    finally:
        _put_colours(coloured)
        for obj, was in hidden:
            try:
                obj.hide_render = was
            except ReferenceError:
                pass
        _restore(scene, shading)
        _restore(scene, saved)
        for cam in cameras:
            _drop(cam)
        scene.frame_set(current, subframe=subframe)
        shutil.rmtree(folder, ignore_errors=True)


def render(build, moves=False):
    """Render the scene for the model. ``moves``: also the middle and the last frame when the camera moves.

    Returns ``{"images": [data URL], "frames": [n], "seconds": [s], "overview": bool}``; ``images`` is empty with a
    ``reason`` when nothing could be rendered. The chat's own camera is used; without one, a temporary overview
    camera."""
    if render_export.busy() or bpy.app.is_job_running("RENDER"):
        return {"images": [], "reason": "another render is running"}
    scene = build.scene
    current, subframe = scene.frame_current, scene.frame_subframe
    saved = _snapshot(scene)
    folder = tempfile.mkdtemp(prefix="eachlabs-look-")
    temporary = None
    out = {"images": [], "frames": [], "seconds": [], "overview": False}
    try:
        _lower(scene, folder)
        cam = scene.camera if scene.camera is not None and build.owns(scene.camera) else None
        if cam is None:
            temporary = cam = _overview(build, scene)
            out["overview"] = True
        if cam is None:
            return {"images": [], "reason": "nothing to see yet"}
        frames = [scene.frame_start]
        if moves and temporary is None and scene.frame_end != scene.frame_start and _moves(scene, cam):
            middle = (scene.frame_start + scene.frame_end) // 2  # an orbit can lose its subject halfway
            frames += [middle, scene.frame_end] if middle not in (scene.frame_start, scene.frame_end) \
                else [scene.frame_end]
        for frame in frames:
            scene.frame_set(frame)
            started = time.monotonic()
            bpy.ops.render.render(write_still=True, scene=scene.name)
            seconds = round(time.monotonic() - started, 2)
            with open(scene.render.filepath, "rb") as handle:
                data = handle.read()
            try:
                found = exposure.measure(scene.render.filepath)
            except (RuntimeError, OSError):  # the picture still goes to the model
                found = None
            os.remove(scene.render.filepath)
            out["images"].append("data:image/png;base64," + base64.b64encode(data).decode("ascii"))
            out["frames"].append(frame)
            out["seconds"].append(seconds)
            if found is not None and not out.get("overview"):
                note = exposure.assess(*found)
                if note and note not in out.setdefault("notes", []):
                    out["notes"].append(note)
        return out
    except (RuntimeError, OSError, ReferenceError) as exc:  # the check is extra: the run goes on without it
        return {"images": [], "reason": str(exc) or type(exc).__name__}
    finally:
        _restore(scene, saved)
        _drop(temporary)
        scene.frame_set(current, subframe=subframe)
        shutil.rmtree(folder, ignore_errors=True)
