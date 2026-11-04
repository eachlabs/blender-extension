"""Read a binary glTF (``.glb``) into plain lists, in Blender's axes (Z up). No ``bpy``.

Only what a generated 3D model needs: triangle meshes with positions, normals and one UV set, node transforms, and
metallic-roughness materials with embedded textures. The add-on builds the Blender data from the result with
``bpy.data`` alone (``objects_3d``), so no import operator runs.
"""

import base64
import binascii
import json
import math
import struct
import zipfile
from array import array
from dataclasses import dataclass, field

MAGIC = b"glTF"
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942
MAX_ZIP_GLB = 64 * 1024 * 1024  # bytes a GLB inside a downloaded zip may unpack to; a real model is about 6 MB
_COMPONENT = {5120: "b", 5121: "B", 5122: "h", 5123: "H", 5125: "I", 5126: "f"}
_NORMALIZE = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}
_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


class GlbError(ValueError):
    """The file is not a GLB this reader can use; the message says why."""


@dataclass
class Texture:
    data: bytes
    mime: str  # "image/png" or "image/jpeg"


@dataclass
class Material:
    name: str
    base_color: tuple = (1.0, 1.0, 1.0, 1.0)
    metallic: float = 1.0
    roughness: float = 1.0
    base_texture: int = None  # index into Model.textures
    mr_texture: int = None  # metallic in blue, roughness in green
    normal_texture: int = None


@dataclass
class Part:
    """One triangle list in world space: ``positions`` and ``normals`` as flat xyz, ``uvs`` as flat uv per vertex
    (Blender's v), ``triangles`` as flat vertex indices."""

    positions: list
    triangles: list
    normals: list = None
    uvs: list = None
    material: int = None  # index into Model.materials


@dataclass
class Model:
    parts: list = field(default_factory=list)
    materials: list = field(default_factory=list)
    textures: list = field(default_factory=list)

    @property
    def bounds(self):
        """``((x0, y0, z0), (x1, y1, z1))`` of every vertex."""
        lows, highs = [math.inf] * 3, [-math.inf] * 3
        for part in self.parts:
            p = part.positions
            for axis in range(3):
                values = p[axis::3]
                if values:
                    lows[axis] = min(lows[axis], min(values))
                    highs[axis] = max(highs[axis], max(values))
        if math.inf in lows:
            return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
        return tuple(lows), tuple(highs)

    @property
    def triangle_count(self):
        return sum(len(p.triangles) // 3 for p in self.parts)


BASE_PERCENTILE = 0.01  # share of a model's vertices allowed below its base: stray bits under a scanned model


def base_height(model, share=BASE_PERCENTILE):
    """The height a model stands on: a low percentile of its vertex heights, not the lowest one, so a stray point
    under it does not lift it off the ground."""
    heights = sorted(z for part in model.parts for z in part.positions[2::3])
    if not heights:
        return 0.0
    return heights[min(len(heights) - 1, int(len(heights) * share))]


def scale_for(bounds, size_m, measure=""):
    """The factor that makes a model ``size_m`` along ``measure``: its height (z), its length (the longer side on the
    ground), or else its longest side. ``bounds`` as ``Model.bounds``."""
    low, high = bounds
    extents = [high[i] - low[i] for i in range(3)]
    along = extents[2] if measure == "height" else max(extents[:2]) if measure == "length" else max(extents)
    return float(size_m) / along if along > 1e-9 else 1.0


def glb_from_zip(zip_path):
    """The GLB bytes inside a downloaded model zip: ``*_pbr.glb`` first (it adds metallic and roughness maps), then
    a textured one, then any ``.glb``."""
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise GlbError("The 3D result is neither a zip nor a GLB file") from None
    with archive:
        entries = [i for i in archive.infolist() if i.filename.lower().endswith(".glb") and not i.is_dir()]
        if not entries:
            raise GlbError("The 3D result has no GLB file")

        def rank(info):
            name = info.filename.lower()
            return (0 if name.endswith("_pbr.glb") else 1 if "textured" in name else 2, len(name))
        best = min(entries, key=rank)
        if best.file_size > MAX_ZIP_GLB:
            raise GlbError("The GLB in the 3D result is larger than %d MB" % (MAX_ZIP_GLB // 1048576))
        with archive.open(best) as handle:
            return handle.read()


def split(data):
    """``(json dict, binary chunk)`` of GLB bytes."""
    if len(data) < 20 or data[:4] != MAGIC:
        raise GlbError("Not a GLB file")
    version, length = struct.unpack_from("<II", data, 4)
    if version != 2:
        raise GlbError("glTF version %d is not supported" % version)
    offset, doc, binary = 12, None, b""
    while offset + 8 <= min(length, len(data)):
        size, kind = struct.unpack_from("<II", data, offset)
        chunk = data[offset + 8:offset + 8 + size]
        if kind == JSON_CHUNK and doc is None:
            try:
                doc = json.loads(chunk.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                raise GlbError("The GLB's JSON is unreadable") from None
        elif kind == BIN_CHUNK and not binary:
            binary = chunk
        offset += 8 + size + (-size % 4)
    if not isinstance(doc, dict):
        raise GlbError("The GLB has no JSON")
    return doc, binary


def _view(doc, binary, index):
    views = doc.get("bufferViews") or []
    if not isinstance(index, int) or not 0 <= index < len(views):
        raise GlbError("A buffer view is missing")
    view = views[index]
    if view.get("buffer", 0) != 0:
        raise GlbError("Only the GLB's own buffer is supported")
    start = view.get("byteOffset", 0)
    end = start + view["byteLength"]
    if end > len(binary):
        raise GlbError("A buffer view runs past the data")
    return binary[start:end], view.get("byteStride")


def accessor(doc, binary, index):
    """The values of an accessor as a flat list (floats or ints)."""
    accessors = doc.get("accessors") or []
    if not isinstance(index, int) or not 0 <= index < len(accessors):
        raise GlbError("An accessor is missing")
    acc = accessors[index]
    if acc.get("sparse"):
        raise GlbError("Sparse accessors are not supported")
    code = _COMPONENT.get(acc.get("componentType"))
    width = _COUNT.get(acc.get("type"))
    count = acc.get("count", 0)
    if code is None or width is None:
        raise GlbError("An accessor type is not supported")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise GlbError("An accessor count is not a number")
    size = struct.calcsize("<" + code)
    packed = width * size
    if acc.get("bufferView") is None:  # all zeros; never larger than the file's own data
        if count * packed > len(binary):
            raise GlbError("An accessor is larger than the GLB's data")
        return [0] * (count * width)
    data, stride = _view(doc, binary, acc["bufferView"])
    start = acc.get("byteOffset", 0)
    if not isinstance(start, int) or start < 0:
        raise GlbError("An accessor offset is not a number")
    if not stride or stride == packed:
        end = start + count * packed
        if end > len(data):
            raise GlbError("An accessor runs past its buffer view")
        values = array(code, data[start:end])
        if array("H", [1]).tobytes() != b"\x01\x00":  # big-endian host
            values.byteswap()
        values = values.tolist()
    else:
        last = start + (count - 1) * stride + packed if isinstance(stride, int) and count else 0
        if not isinstance(stride, int) or stride < packed or last > len(data):
            raise GlbError("An accessor runs past its buffer view")
        values = []
        for i in range(count):
            values.extend(struct.unpack_from("<%d%s" % (width, code), data, start + i * stride))
    if acc.get("normalized") and acc["componentType"] in _NORMALIZE:
        scale = _NORMALIZE[acc["componentType"]]
        values = [max(v / scale, -1.0) for v in values]
    return values


# 4x4 matrices as 16 floats, column-major like glTF.

IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


def _multiply(a, b):
    return tuple(sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4)) for c in range(4) for r in range(4))


def node_matrix(node):
    """A node's local matrix, from ``matrix`` or translation, rotation (x, y, z, w) and scale."""
    if isinstance(node.get("matrix"), list) and len(node["matrix"]) == 16:
        return tuple(float(v) for v in node["matrix"])
    tx, ty, tz = node.get("translation") or (0.0, 0.0, 0.0)
    x, y, z, w = node.get("rotation") or (0.0, 0.0, 0.0, 1.0)
    sx, sy, sz = node.get("scale") or (1.0, 1.0, 1.0)
    return (
        (1 - 2 * (y * y + z * z)) * sx, (2 * (x * y + z * w)) * sx, (2 * (x * z - y * w)) * sx, 0.0,
        (2 * (x * y - z * w)) * sy, (1 - 2 * (x * x + z * z)) * sy, (2 * (y * z + x * w)) * sy, 0.0,
        (2 * (x * z + y * w)) * sz, (2 * (y * z - x * w)) * sz, (1 - 2 * (x * x + y * y)) * sz, 0.0,
        tx, ty, tz, 1.0)


def _mesh_nodes(doc):
    """``(mesh index, world matrix)`` for every node with a mesh in the default scene, or in every root node."""
    nodes = doc.get("nodes") or []
    scenes = doc.get("scenes") or []
    scene = doc.get("scene", 0)
    if scenes and isinstance(scene, int) and 0 <= scene < len(scenes):
        roots = scenes[scene].get("nodes") or []
    else:
        children = {c for n in nodes for c in n.get("children") or []}
        roots = [i for i in range(len(nodes)) if i not in children]
    found, stack, seen = [], [(r, IDENTITY) for r in roots], set()
    while stack:
        index, parent = stack.pop()
        if not isinstance(index, int) or not 0 <= index < len(nodes) or index in seen:
            continue
        seen.add(index)
        node = nodes[index]
        world = _multiply(parent, node_matrix(node))
        if isinstance(node.get("mesh"), int):
            found.append((node["mesh"], world))
        stack.extend((c, world) for c in node.get("children") or [])
    return found


def _transform(values, m, direction=False):
    """xyz triples through matrix ``m`` (points, or directions without the translation), then from glTF's Y up to
    Blender's Z up: (x, y, z) -> (x, -z, y)."""
    out = []
    w = 0.0 if direction else 1.0
    for i in range(0, len(values), 3):
        x, y, z = values[i], values[i + 1], values[i + 2]
        tx = m[0] * x + m[4] * y + m[8] * z + m[12] * w
        ty = m[1] * x + m[5] * y + m[9] * z + m[13] * w
        tz = m[2] * x + m[6] * y + m[10] * z + m[14] * w
        if direction:
            length = math.sqrt(tx * tx + ty * ty + tz * tz) or 1.0
            tx, ty, tz = tx / length, ty / length, tz / length
        out.extend((tx, -tz, ty))
    return out


def _texture_index(doc, info):
    """The ``Model.textures`` index of a material's texture reference (one per image)."""
    if not isinstance(info, dict) or not isinstance(info.get("index"), int):
        return None
    textures = doc.get("textures") or []
    if not 0 <= info["index"] < len(textures):
        return None
    source = textures[info["index"]].get("source")
    return source if isinstance(source, int) else None


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"


def image_type(data):
    """``image/jpeg`` or ``image/png`` from the first bytes; ``None`` for anything else, which is never given to
    Blender's image loader."""
    data = data or b""
    if data[:3] == JPEG_SIGNATURE:
        return "image/jpeg"
    if data[:8] == PNG_SIGNATURE:
        return "image/png"
    return None


def read(data):
    """A ``Model`` from GLB bytes."""
    doc, binary = split(data)
    model = Model()
    for image in doc.get("images") or []:
        payload = None
        if "bufferView" in image:
            payload = bytes(_view(doc, binary, image["bufferView"])[0])
        elif str(image.get("uri") or "").startswith("data:") and ";base64," in image["uri"]:
            try:
                payload = base64.b64decode(image["uri"].split(";base64,", 1)[1])
            except (ValueError, binascii.Error):
                payload = None
        # An external file is not part of a generated model. The stated type can be wrong (a JPEG called PNG), so
        # the first bytes decide, and anything but PNG or JPEG is dropped.
        mime = image_type(payload) if payload else None
        model.textures.append(Texture(payload, mime) if mime else None)
    for i, mat in enumerate(doc.get("materials") or []):
        pbr = mat.get("pbrMetallicRoughness") or {}
        model.materials.append(Material(
            name=str(mat.get("name") or "material_%d" % i),
            base_color=tuple(pbr.get("baseColorFactor") or (1.0, 1.0, 1.0, 1.0)),
            metallic=float(pbr.get("metallicFactor", 1.0)), roughness=float(pbr.get("roughnessFactor", 1.0)),
            base_texture=_texture_index(doc, pbr.get("baseColorTexture")),
            mr_texture=_texture_index(doc, pbr.get("metallicRoughnessTexture")),
            normal_texture=_texture_index(doc, mat.get("normalTexture"))))
    meshes = doc.get("meshes") or []
    for mesh_index, world in _mesh_nodes(doc):
        if not 0 <= mesh_index < len(meshes):
            continue
        for prim in meshes[mesh_index].get("primitives") or []:
            if prim.get("mode", 4) != 4:
                continue  # points and lines carry no surface
            attrs = prim.get("attributes") or {}
            if "POSITION" not in attrs:
                continue
            positions = _transform(accessor(doc, binary, attrs["POSITION"]), world)
            count = len(positions) // 3
            if prim.get("indices") is not None:
                triangles = [int(v) for v in accessor(doc, binary, prim["indices"])]
            else:
                triangles = list(range(count))
            triangles = triangles[:len(triangles) - len(triangles) % 3]
            if any(v < 0 or v >= count for v in triangles):
                raise GlbError("A triangle points past the vertices")
            normals = _transform(accessor(doc, binary, attrs["NORMAL"]), world, True) if "NORMAL" in attrs else None
            uvs = None
            if "TEXCOORD_0" in attrs:
                raw = accessor(doc, binary, attrs["TEXCOORD_0"])
                uvs = [raw[i] if i % 2 == 0 else 1.0 - raw[i] for i in range(len(raw))]  # glTF's v runs down
            material = prim.get("material")
            model.parts.append(Part(positions, triangles, normals, uvs,
                                    material if isinstance(material, int) and material < len(model.materials) else None))
    if not model.parts:
        raise GlbError("The GLB has no triangle mesh")
    return model
