"""What the camera sees through the chat's glass: the first thing past each pane in the frame.

Seen in a cabin whose window showed a pale disc where the request asked for snowy mountains. A ray from the camera
through the pane goes on past the glass; whatever it meets first is what the window shows, or the sky when it meets
nothing. The model compares that with what the request says is seen through it; nothing here knows what a window is.
"""

TRANSMISSION_MIN = 0.5  # a material letting through at least this much reads as glass
ALPHA_MAX = 0.5  # or one this transparent
SAMPLES = ((0.0, 0.0), (0.25, 0.0), (-0.25, 0.0), (0.0, 0.25))  # points across a pane, as a share of its size
PASSES = 4  # glass panes a ray may go through before it gives up
DISTANCE = 2000.0
LISTED = 6
SKY = "the sky (nothing)"
BLOCKED = "%s, in front of the glass"


def is_glass(material):
    """True when the material lets light through: a Glass node, high transmission, or low alpha."""
    tree = getattr(material, "node_tree", None)
    if tree is None:
        return False
    for node in tree.nodes:
        if node.type == "BSDF_GLASS":
            return True
        if node.type == "BSDF_PRINCIPLED":
            weight = node.inputs.get("Transmission Weight") or node.inputs.get("Transmission")
            alpha = node.inputs.get("Alpha")
            if weight is not None and not weight.is_linked and weight.default_value >= TRANSMISSION_MIN:
                return True
            if alpha is not None and not alpha.is_linked and alpha.default_value <= ALPHA_MAX:
                return True
    return False


def _glass_objects(objects, owns):
    out = []
    for obj in objects:
        if obj.type != "MESH" or obj.hide_render:
            continue
        if any(s.material is not None and owns(s.material) and is_glass(s.material) for s in obj.material_slots):
            out.append(obj)
    return out


def views(objects, owns, scene, depsgraph, label):
    """``[{"glass", "sees"}]``: for each pane of the chat's in the camera's frame, the things seen past it."""
    camera = scene.camera
    if camera is None:
        return []
    from bpy_extras.object_utils import world_to_camera_view  # Blender's maths, only where Blender runs this
    from mathutils import Vector

    panes = _glass_objects(objects, owns)
    glass = {o.session_uid for o in panes}
    eye = camera.matrix_world.translation
    found = []
    for pane in panes:
        corners = [pane.matrix_world @ Vector(c) for c in pane.bound_box]
        centre = sum(corners, Vector()) / 8.0
        x, y, z = world_to_camera_view(scene, camera, centre)
        if z <= 0 or not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            continue
        size = max((max(c[i] for c in corners) - min(c[i] for c in corners)) for i in range(3))
        side = (centre - eye).cross(Vector((0.0, 0.0, 1.0)))
        side = side.normalized() if side.length > 1e-6 else Vector((1.0, 0.0, 0.0))
        seen = []
        for dx, dz in SAMPLES:
            target = centre + side * (dx * size) + Vector((0.0, 0.0, dz * size))
            name = _past_glass(scene, depsgraph, eye, (target - eye).normalized(), glass, label)
            if name not in seen:
                seen.append(name)
        found.append({"glass": pane.name, "sees": seen})
        if len(found) >= LISTED:
            break
    return found


def _past_glass(scene, depsgraph, origin, direction, glass, label):
    """The label of the first thing a ray meets past the glass it goes through, or ``SKY``."""
    passed = False
    for _ in range(PASSES + 1):
        hit, location, _normal, _index, obj, _matrix = scene.ray_cast(depsgraph, origin, direction, distance=DISTANCE)
        if not hit:
            return SKY
        obj = getattr(obj, "original", obj)
        if obj.session_uid in glass:
            passed = True
            origin = location + direction * 0.01
            continue
        return label(obj) if passed else BLOCKED % label(obj)
    return SKY
