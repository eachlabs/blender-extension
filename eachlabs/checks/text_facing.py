"""Text that reads backwards from the camera: a sign seen from behind, or mirrored by a negative scale.

Seen on a neon street whose "CYBER" sign read backwards. A text object reads correctly from the side its local
+Z faces; a negative scale on one axis mirrors it.
"""

LISTED = 8


def reads_backwards(facing_dot, determinant):
    """``facing_dot``: the text's front direction dotted with the direction to the camera; ``determinant``: of its
    world matrix. Backwards when seen from behind, or seen from the front with a mirroring scale."""
    seen_from_front = facing_dot > 0
    mirrored = determinant < 0
    return seen_from_front == mirrored


def mirrored_text(objects, camera):
    """Names of the chat's visible text objects that read backwards from ``camera`` at the current frame."""
    if camera is None:
        return []
    from mathutils import Vector  # Blender's maths, only where Blender runs this

    eye = camera.matrix_world.translation
    found = []
    for obj in objects:
        if obj.type != "FONT" or obj.hide_render:
            continue
        world = obj.matrix_world
        front = (world.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
        to_eye = eye - world.translation
        if to_eye.length < 1e-6:
            continue
        if reads_backwards(front.dot(to_eye.normalized()), world.to_3x3().determinant()):
            found.append(obj.name)
            if len(found) >= LISTED:
                break
    return found
