"""What the model may say about where a thing or an area goes, checked and put in one shape.

A thing: ``place(thing, zone=, on=, near=, facing=, against=, apart_m=, around=, row=)``.
An area: ``zone(name, size=, ring_m=, inside=, around=, near=, apart_m=)``.
Many copies: ``scatter(thing, zone=, count=, gap_m=, size=, turn=)``.
Names are the model's own; nothing here knows kinds of things."""

import difflib

ON_GROUND = "ground"
GAP_DEFAULT_M = 0.5  # open space kept around a placed thing
SCATTER_MAX = 2000


class Wrong(ValueError):
    """A relation the model wrote that cannot be used; the message says what to write instead."""


def _number(value, what, low=0.0, high=1e6):
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise Wrong("%s must be a number of metres, not %r." % (what, value)) from None
    if not low <= n <= high:
        raise Wrong("%s must be between %g and %g, not %g." % (what, low, high, n))
    return n


def _range(value, what):
    """``near`` as ``(to, min_m, max_m)``: a name, or ``[name, max]``, or ``[name, min, max]``, or a dict."""
    if isinstance(value, str):
        return value, 0.0, None
    if isinstance(value, dict):
        to, low, high = value.get("to"), value.get("min_m", 0.0), value.get("max_m")
    elif isinstance(value, (list, tuple)) and 2 <= len(value) <= 3:
        to = value[0]
        low, high = (0.0, value[1]) if len(value) == 2 else (value[1], value[2])
    else:
        raise Wrong("%s is a name, [name, max_m] or [name, min_m, max_m]." % what)
    if not isinstance(to, str) or not to:
        raise Wrong("%s needs the name of a thing or an area." % what)
    low = _number(low, what + " min_m")
    high = None if high is None else _number(high, what + " max_m")
    if high is not None and high < low:
        raise Wrong("%s max_m is less than min_m." % what)
    return to, low, high


def _apart(value, what):
    """``apart_m`` as ``{name: metres}``; a bare number means from every other area."""
    if value is None:
        return {}
    if isinstance(value, (int, float)):
        return {"*": _number(value, what)}
    if isinstance(value, dict):
        return {str(k): _number(v, what) for k, v in value.items()}
    raise Wrong("%s is metres, or {name: metres}." % what)


def thing(name, zone=None, on=ON_GROUND, near=None, facing=None, against=None, apart_m=None, around=None,
          row=None, gap_m=GAP_DEFAULT_M):
    if not isinstance(name, str) or not name:
        raise Wrong("place() needs the name of the thing to place.")
    out = {"thing": name, "zone": zone, "on": on or ON_GROUND, "facing": facing, "against": against,
           "apart": _apart(apart_m, "apart_m"), "gap_m": _number(gap_m, "gap_m", 0.0, 50.0)}
    out["near"] = _range(near, "near") if near is not None else None
    if around is not None:
        if isinstance(around, str):
            around = {"to": around}
        if not isinstance(around, dict) or not around.get("to"):
            raise Wrong("around is a name or {\"to\": name, \"radius_m\": m}.")
        out["around"] = {"to": around["to"], "radius_m": None if around.get("radius_m") is None else
                         _number(around["radius_m"], "around radius_m")}
    else:
        out["around"] = None
    if row is not None:
        if not isinstance(row, dict) or "from" not in row or "to" not in row:
            raise Wrong("row is {\"from\": [x, y], \"to\": [x, y]} or {\"from\": name, \"to\": name}.")
        out["row"] = {"from": row["from"], "to": row["to"]}
    else:
        out["row"] = None
    return out


def area(name, size=None, ring_m=None, inside=None, around=None, near=None, apart_m=None, gap_m=2.0, holds=None):
    if not isinstance(name, str) or not name:
        raise Wrong("zone() needs the area's name.")
    if size is None and ring_m is None:
        raise Wrong("zone() needs size=[width, depth] in metres, or ring_m=width with around=name.")
    out = {"zone": name, "inside": inside, "apart": _apart(apart_m, "apart_m"), "gap_m": _number(gap_m, "gap_m"),
           "holds": None if holds is None else int(_number(holds, "holds", 1, SCATTER_MAX))}
    if size is not None:
        if not isinstance(size, (list, tuple)) or len(size) != 2:
            raise Wrong("size is [width, depth] in metres.")
        out["size"] = (_number(size[0], "width", 1.0), _number(size[1], "depth", 1.0))
    else:
        out["size"] = None
    out["ring_m"] = None if ring_m is None else _number(ring_m, "ring_m", 1.0)
    if out["ring_m"] is not None and not around:
        raise Wrong("ring_m makes a ring around something: give around=name too.")
    out["around"] = around
    out["near"] = _range(near, "near") if near is not None else None
    return out


def scatter(name, zone, count, gap_m=None, size=(0.8, 1.2), turn=True, seed=0):
    if not isinstance(name, str) or not name:
        raise Wrong("scatter() needs the name of the thing to copy.")
    if not isinstance(zone, str) or not zone:
        raise Wrong("scatter() needs zone=, the area to fill.")
    count = int(_number(count, "count", 1, SCATTER_MAX))
    if not isinstance(size, (list, tuple)) or len(size) != 2:
        raise Wrong("size is [smallest, largest] scale, like [0.8, 1.2].")
    low, high = _number(size[0], "size", 0.05, 20), _number(size[1], "size", 0.05, 20)
    return {"scatter": name, "zone": zone, "count": count, "gap_m": None if gap_m is None else
            _number(gap_m, "gap_m", 0.0, 100.0), "size": (min(low, high), max(low, high)), "turn": bool(turn),
            "seed": int(_number(seed, "seed", 0, 1e9))}


def names_in(relation):
    """Every name a relation refers to (other than the thing or area it is about)."""
    out = []
    for key in ("zone", "facing", "against", "inside"):
        if isinstance(relation.get(key), str):
            out.append(relation[key])
    if relation.get("on") not in (None, ON_GROUND):
        out.append(relation["on"])
    if relation.get("around"):
        out.append(relation["around"]["to"] if isinstance(relation["around"], dict) else relation["around"])
    if relation.get("near"):
        out.append(relation["near"][0])
    for key in (relation.get("apart") or {}):
        if key != "*":
            out.append(key)
    row = relation.get("row") or {}
    for end in (row.get("from"), row.get("to")):
        if isinstance(end, str):
            out.append(end)
    return out


def closest(name, known):
    """The known name ``name`` most likely means, for the error message."""
    hit = difflib.get_close_matches(name, list(known), n=1, cutoff=0.6)
    return hit[0] if hit else None
