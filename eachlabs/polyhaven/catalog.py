"""Poly Haven's free assets: picking one for a description and the files to download. No Blender, no network.

Poly Haven publishes its assets under CC0 at api.polyhaven.com: ``/assets?t=hdris|textures`` lists them with their
name, tags, categories and, for skies, the time of day and the weather; ``/files/<id>`` lists the files of one.
"""

import re

API = "https://api.polyhaven.com"
CREDIT = "Poly Haven, CC0"
KINDS = {"sky": "hdris", "texture": "textures"}
SKY_RESOLUTIONS = ("2k", "1k")  # 2k is sharp enough as a background and about 6 MB
TEXTURE_RESOLUTIONS = ("1k", "2k")
MAPS = (("Diffuse", "color"), ("Rough", "roughness"), ("nor_gl", "normal"))  # Poly Haven's names, ours
MIN_SCORE = 2.0  # a weaker match than this is no match: the model builds the look with procedural nodes
MIN_COVERAGE = 0.34  # share of the description's words an asset must match; one shared word is not a match
OFF_NAME = 1.5  # taken off for each word of the asset's name the description lacks ("gravel" for limestone)
TILE_DEFAULT_M, TILE_MIN_M, TILE_MAX_M = 2.0, 0.2, 20.0
WEIGHTS = {"name": 3.0, "attributes": 2.5, "tags": 2.0, "categories": 1.5, "description": 0.5}
STOP = {"a", "an", "the", "of", "and", "with", "in", "on", "for", "at", "to", "texture", "sky", "hdri", "photo",
        "real", "realistic", "seamless", "surface", "material", "light", "lighting"}
_ID = re.compile(r"^[a-z0-9_]{1,80}$")


def words(text):
    """The meaningful lower-case words of ``text``, with a plural's last s dropped."""
    found = set()
    for word in re.findall(r"[a-z0-9]+", str(text or "").lower().replace("_", " ")):
        if word in STOP or len(word) < 2:
            continue
        found.add(word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word)
    return found


def _fields(asset):
    attributes = asset.get("attributes") if isinstance(asset.get("attributes"), dict) else {}
    return {
        "name": words(asset.get("name")),
        "attributes": words(" ".join(str(v) for v in attributes.values())),
        "tags": words(" ".join(str(t) for t in asset.get("tags") or ())),
        "categories": words(" ".join(str(c) for c in asset.get("categories") or ())),
        "description": words(asset.get("description")),
    }


def score(asset, wanted, names_describe=True):
    """How well ``asset`` matches the set of words ``wanted``: each word counts once, in its best field. When the
    asset's name describes it (textures: "Gravel Stones", not a sky's place name), matching too few of the words
    scores 0 and each name word ``wanted`` lacks counts against it, so a name about something else loses."""
    fields = _fields(asset)
    total, matched = 0.0, 0
    for word in wanted:
        weight = max((WEIGHTS[f] for f, found in fields.items() if word in found), default=0.0)
        total += weight
        matched += weight > 0
    if not names_describe:
        return total
    if not wanted or matched / len(wanted) < MIN_COVERAGE:
        return 0.0
    off = [w for w in fields["name"] if w not in wanted and not w.isdigit()]
    return total - OFF_NAME * len(off)


SKY_ONLY_BONUS = 1.0  # a sky picture of sky alone (Poly Haven's "skies" category) wins over a landscape


def _sky_only(asset, names_describe):
    if names_describe:
        return 0.0
    return SKY_ONLY_BONUS if "skies" in words(" ".join(str(c) for c in asset.get("categories") or ())) else 0.0


def best(assets, description, names_describe=True):
    """``(asset_id, asset)`` matching ``description`` best, or ``None`` when nothing matches well enough."""
    wanted = words(description)
    if not wanted or not isinstance(assets, dict):
        return None
    ranked = sorted(((score(a, wanted, names_describe) + _sky_only(a, names_describe), i) for i, a in assets.items()
                     if valid_id(i) and isinstance(a, dict)),
                    key=lambda pair: (-pair[0], pair[1]))
    if not ranked or ranked[0][0] < MIN_SCORE:
        return None
    return ranked[0][1], assets[ranked[0][1]]


def valid_id(asset_id):
    return isinstance(asset_id, str) and bool(_ID.match(asset_id))


def list_url(kind):
    return "%s/assets?t=%s" % (API, KINDS[kind])


def files_url(asset_id):
    if not valid_id(asset_id):
        raise ValueError("not a Poly Haven asset id: %r" % (asset_id,))
    return "%s/files/%s" % (API, asset_id)


def _entry(node):
    if isinstance(node, dict) and isinstance(node.get("url"), str) and node["url"].startswith("https://"):
        return {"url": node["url"], "md5": str(node.get("md5") or ""), "size": int(node.get("size") or 0)}
    return None


def sky_file(files):
    """The sky picture to download from ``/files/<id>``: ``{"url", "md5", "size", "ext"}`` or ``None``."""
    sizes = (files or {}).get("hdri") if isinstance(files, dict) else None
    for resolution in SKY_RESOLUTIONS:
        formats = (sizes or {}).get(resolution) or {}
        entry = _entry(formats.get("hdr"))
        if entry:
            return dict(entry, ext="hdr")
    return None


def texture_files(files):
    """``{role: {"url", "md5", "size", "ext"}}`` for colour, roughness and normal; ``{}`` without a colour map."""
    found = {}
    for theirs, ours in MAPS:
        sizes = (files or {}).get(theirs) if isinstance(files, dict) else None
        for resolution in TEXTURE_RESOLUTIONS:
            entry = _entry(((sizes or {}).get(resolution) or {}).get("jpg"))
            if entry:
                found[ours] = dict(entry, ext="jpg")
                break
    return found if "color" in found else {}


def tile_m(asset):
    """Metres one tile of a texture covers in the real world, from Poly Haven's dimensions in millimetres."""
    dims = asset.get("dimensions") if isinstance(asset, dict) else None
    try:
        metres = float(dims[0]) / 1000.0
    except (TypeError, ValueError, IndexError):
        return TILE_DEFAULT_M
    return min(TILE_MAX_M, max(TILE_MIN_M, metres)) if metres > 0 else TILE_DEFAULT_M
