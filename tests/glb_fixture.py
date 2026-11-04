"""Small GLB files for tests: a textured box shaped like a generated model (Y up, under a root node)."""

import base64
import io
import json
import struct
import zipfile
import zlib


def png(r=200, g=40, b=20):
    """A 2x2 RGB PNG."""
    raw = b"".join(b"\x00" + bytes((r, g, b)) * 2 for _ in range(2))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def box_glb(size=(2.0, 1.0, 0.5), data_uri=False, pbr=True, root=None):
    """A box ``size`` wide (x), tall (glTF y) and deep (glTF z), one material with a base colour texture, and with
    ``pbr`` a metallic-roughness texture too. ``data_uri`` stores the images as base64 data URIs, as the 3D model's
    PBR file does. ``root``: the root node's fields (translation, rotation, scale)."""
    sx, sy, sz = (s / 2 for s in size)
    corners = [(-sx, -sy, -sz), (sx, -sy, -sz), (sx, sy, -sz), (-sx, sy, -sz),
               (-sx, -sy, sz), (sx, -sy, sz), (sx, sy, sz), (-sx, sy, sz)]
    faces = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (2, 3, 7), (2, 7, 6), (1, 2, 6), (1, 6, 5), (3, 0, 4), (3, 4, 7)]
    uvs = [(0, 0), (1, 0), (1, 1), (0, 1)] * 2
    blob = bytearray()
    views, accessors = [], []

    def add(data, target=None):
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)})
        if target:
            views[-1]["target"] = target
        blob.extend(data)
        return len(views) - 1

    idx = add(struct.pack("<%dH" % (3 * len(faces)), *[i for f in faces for i in f]), 34963)
    accessors.append({"bufferView": idx, "componentType": 5123, "count": 3 * len(faces), "type": "SCALAR"})
    pos = add(struct.pack("<%df" % 24, *[v for c in corners for v in c]), 34962)
    accessors.append({"bufferView": pos, "componentType": 5126, "count": 8, "type": "VEC3",
                      "min": [-sx, -sy, -sz], "max": [sx, sy, sz]})
    uv = add(struct.pack("<%df" % 16, *[v for t in uvs for v in t]), 34962)
    accessors.append({"bufferView": uv, "componentType": 5126, "count": 8, "type": "VEC2"})
    images = []
    for colour in ((200, 40, 20), (0, 128, 255)) if pbr else ((200, 40, 20),):
        data = png(*colour)
        if data_uri:
            images.append({"uri": "data:image/png;base64," + base64.b64encode(data).decode()})
        else:
            images.append({"bufferView": add(data), "mimeType": "image/png"})
    material = {"name": "PBR_Material", "pbrMetallicRoughness": {
        "baseColorFactor": [1, 1, 1, 1], "metallicFactor": 1.0, "roughnessFactor": 1.0,
        "baseColorTexture": {"index": 0}}}
    if pbr:
        material["pbrMetallicRoughness"]["metallicRoughnessTexture"] = {"index": 1}
    doc = {"asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
           "nodes": [dict({"name": "world", "children": [1]}, **(root or {})), {"name": "demo", "mesh": 0}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 1, "TEXCOORD_0": 2}, "indices": 0, "mode": 4,
                                       "material": 0}]}],
           "materials": [material], "textures": [{"source": i} for i in range(len(images))], "images": images,
           "accessors": accessors, "bufferViews": views, "buffers": [{"byteLength": len(blob)}]}
    text = json.dumps(doc).encode()
    text += b" " * (-len(text) % 4)
    while len(blob) % 4:
        blob.append(0)
    body = struct.pack("<II", len(text), 0x4E4F534A) + text + struct.pack("<II", len(blob), 0x004E4942) + bytes(blob)
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def model_zip(pbr_size=(2.0, 1.0, 0.5)):
    """A zip shaped like the 3D model's result: images, OBJ files and two GLBs, the PBR one the larger."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("image.png", png())
        archive.writestr("demo.obj", "v 0 0 0\n")
        archive.writestr("demo_textured.glb", box_glb((1.0, 1.0, 1.0), pbr=False))
        archive.writestr("demo_textured_pbr.glb", box_glb(pbr_size, data_uri=True))
    return out.getvalue()
