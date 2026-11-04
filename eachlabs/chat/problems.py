"""Problems the run reads from read_scene and camera_view, and how it words them for the model and the reply."""

import json
import re


# read_scene's lists of things in the wrong place: what a fix stage gets, and what the reply names if they remain.
# Standing on water stays in read_scene for the model to judge (a bridge or a boat is meant to); it is no fix list.
PLACEMENT_KEYS = ("nothing_below", "floats_above", "under", "sunk_into", "overlaps", "crossing", "hidden_parts",
                  "outside_ground", "zones", "empty_groups", "gaps", "pierces", "harsh_emission",
                  "duplicates", "colour_off")
FIX_MAX = 3  # fix stages in a run: after the layout or the detail stage, and before the check



def placement_problems(scene):
    """The placement lists of a ``read_scene`` result (a dict), with zones kept only when something is wrong."""
    found = {}
    for key in PLACEMENT_KEYS:
        value = scene.get(key) if isinstance(scene, dict) else None
        if key == "zones" and isinstance(value, list):
            value = [z for z in value if isinstance(z, dict) and (z.get("outside") or z.get("overlaps")
                                                                  or z.get("too_close") or z.get("ground_fit")
                                                                  or z.get("relation_unmet") or z.get("underfilled"))]
        if value:
            found[key] = value
    return found



def _name_of(entry, key="thing"):
    if isinstance(entry, dict):
        return str(entry.get(key) or entry.get("name") or "?")
    return str(entry)



# The reply's words for each kind of problem, by the things it was found on: what a person reads, never part names.
PERSON_WORDS = {
    "nothing_below": "%s standing on nothing", "floats_above": "%s floating", "on_not_walkable": "%s standing on "
    "something it cannot", "sunk_into": "%s sinking into what is under it", "crossing": "%s passing through other "
    "things", "overlaps": "%s standing inside other things", "under": "%s under other things",
    "hidden_parts": "hidden parts in %s", "outside_ground": "%s partly off the ground", "gaps": "loose parts on %s",
    "pierces": "parts poking through on %s", "duplicates": "doubled parts on %s", "harsh_emission": "%s glowing too "
    "bright", "colour_off": "%s in the wrong colour", "empty_groups": "%s with no parts", "zones": "%s out of place",
}
REPLY_GROUPS = 2  # kinds of problem the reply names before "and N more"


def _thing_of(key, entry):
    """The whole thing a problem was found on: the name before " / " (parts are named "Cat / Left ear")."""
    if key == "duplicates":
        name = _name_of(entry, "copy")
    elif key == "hidden_parts":
        name = _name_of(entry, "part")
    elif key == "harsh_emission" and isinstance(entry, dict) and entry.get("objects"):
        name = str(entry["objects"][0])
    elif key == "zones":
        name = _name_of(entry, "name")
    else:
        name = _name_of(entry)
    return name.split(" / ")[0].strip()


def _tagged(problems):
    """``(phrase, kind, thing)`` per measured problem; the phrase is what two measurements are compared by."""
    out = []
    for key in PLACEMENT_KEYS + ("on_not_walkable",):
        for entry in problems.get(key) or []:
            for phrase in problem_items({key: [entry]}):
                out.append((phrase, key, _thing_of(key, entry)))
    return out


def _plural(word):
    if re.search(r"(s|x|ch|sh)$", word):
        return word + "es"
    if re.search(r"[^aeiou]y$", word):
        return word[:-1] + "ies"
    return word + "s"


def _things_text(names):
    """``the dragon``, ``4 guests`` (the same kind with a number), or ``the chair and the lamp``."""
    kinds = {}
    for name in dict.fromkeys(names):
        base = re.sub(r"[\s_.-]*\d+$", "", name).strip() or name
        kinds.setdefault(base.lower(), []).append(name)
    parts = [("the %s" % base) if len(group) == 1 else "%d %s" % (len(group), _plural(base))
             for base, group in kinds.items()]
    return parts[0] if len(parts) == 1 else "%s and %s" % (", ".join(parts[:-1]), parts[-1])


def person_text(tagged, limit=REPLY_GROUPS):
    """The tagged problems in a person's words, grouped by kind: "doubled parts on 4 guests; the window floating"."""
    groups = {}
    for _phrase, key, thing in tagged:
        groups.setdefault(key, []).append(thing)
    said = [PERSON_WORDS.get(key, "%s out of place") % _things_text(things) for key, things in groups.items()]
    more = len(said) - limit
    return "%s%s" % ("; ".join(said[:limit]), " and %d more" % more if more > 0 else "")


def problems_line(problems, limit=REPLY_GROUPS):
    """One plain line for measured problems that remain: "Still to fix: the camp standing on nothing"."""
    tagged = _tagged(problems)
    return "Still to fix: %s." % person_text(tagged, limit) if tagged else ""


def verified_line(before, after, limit=REPLY_GROUPS):
    """After a fix stage, the problems it was given that the add-on no longer measures: "Fixed: ...", or ""."""
    still = set(problem_items(after))
    gone = [t for t in _tagged(before) if t[0] not in still]
    return "Fixed: %s." % person_text(gone, limit) if gone else ""


def problem_items(problems):
    """Each measured problem as a short plain phrase, in a fixed order, so two measurements can be compared."""
    said = []
    for entry in problems.get("nothing_below") or []:
        said.append("%s stands on nothing" % _name_of(entry))
    for entry in problems.get("floats_above") or []:
        said.append("%s floats %s m above %s" % (_name_of(entry), entry.get("gap_m", "?"), _name_of(entry, "over")))
    for entry in problems.get("on_not_walkable") or []:
        said.append("%s stands on %s" % (_name_of(entry), _name_of(entry, "on")))
    for entry in problems.get("sunk_into") or []:
        said.append("%s sinks into %s" % (_name_of(entry), _name_of(entry, "into")))
    for entry in problems.get("crossing") or []:
        said.append("%s passes through %s" % (_name_of(entry), _name_of(entry, "crosses")))
    for entry in problems.get("overlaps") or []:
        other = _name_of(entry, "inside") if isinstance(entry, dict) and entry.get("inside") else (
            _name_of(entry, "overlaps_existing") if isinstance(entry, dict) and entry.get("overlaps_existing")
            else _name_of(entry, "on"))
        said.append("%s stands in %s" % (_name_of(entry), other))
    for entry in problems.get("under") or []:
        said.append("%s is under %s" % (_name_of(entry), _name_of(entry, "under")))
    for entry in problems.get("hidden_parts") or []:
        said.append("%s is hidden inside %s" % (_name_of(entry, "part"), _name_of(entry, "inside")))
    for entry in problems.get("outside_ground") or []:
        said.append("%s is partly off the ground" % _name_of(entry))
    for entry in problems.get("gaps") or []:
        said.append("parts of %s float off it" % _name_of(entry))
    for entry in problems.get("pierces") or []:
        said.append("a part of %s pokes through %s" % (_name_of(entry), entry.get("through", "another part")))
    for entry in problems.get("duplicates") or []:
        said.append("%s is a second copy of %s in the same place" % (_name_of(entry, "copy"), _name_of(entry, "copy_of")))
    for entry in problems.get("harsh_emission") or []:
        said.append("%s glows %s" % (", ".join(entry.get("objects") or [_name_of(entry, "material")]),
                                     "so bright it renders white" if entry.get("washes_out") else "flat white"))
    for entry in problems.get("colour_off") or []:
        said.append("%s is %s, not the asked %s" % (_name_of(entry), entry.get("has", "?"), entry.get("asked", "?")))
    for entry in problems.get("empty_groups") or []:
        said.append("%s holds no parts" % _name_of(entry))
    for zone in problems.get("zones") or []:
        if zone.get("outside"):
            said.append("parts of %s stand outside it" % _name_of(zone, "name"))
        for other in zone.get("overlaps") or []:
            said.append("%s overlaps %s" % (_name_of(zone, "name"), other))
        for close in zone.get("too_close") or []:
            said.append("%s is closer to %s than asked" % (_name_of(zone, "name"), close.get("zone")))
        if zone.get("relation_unmet"):
            said.append("%s: %s" % (_name_of(zone, "name"), zone["relation_unmet"]))
        if zone.get("underfilled"):
            full = zone["underfilled"]
            said.append("%s holds %s of the %s things it should" % (_name_of(zone, "name"), full.get("things"),
                                                                   full.get("holds")))
        if zone.get("ground_fit"):
            said.append("the ground does not fit the areas on it")
    return said



NOT_YOURS_MAX = 10.0  # % of the frame the person's objects may cover
SUBJECT_MIN_PCT = 2.0  # % of the frame the subject must keep at every checked point of a camera move
CAMERA_MOVING = 0.1  # metres between the first and the last frame that count as a camera move
CAMERA_STILL = 0.05  # metres under which the camera counts as still



def loose_problems(scene):
    """A sentence per group of parts that float apart in a ``read_scene`` result (JSON text)."""
    try:
        groups = json.loads(scene).get("loose_parts") or []
    except (ValueError, AttributeError):
        return []
    return ["Parts of %s float apart: %s parts in %s pieces; apart from the rest: %s. Unless they float on purpose, "
            "like a speech bubble, move them back against the rest." % (
                g.get("parts_of"), g.get("parts"), g.get("pieces"), ", ".join(str(n) for n in g.get("apart") or []))
            for g in groups if isinstance(g, dict)]



def overlap_problems(scene):
    """A sentence per thing that stands on or inside another in a ``read_scene`` result (JSON text)."""
    try:
        found = json.loads(scene).get("overlaps") or []
    except (ValueError, AttributeError):
        return []
    problems = []
    for o in found:
        if not isinstance(o, dict):
            continue
        part = " (%s)" % o["part"] if o.get("part") else ""
        if o.get("overlaps_existing"):
            where = ("No free area fits it: extend the ground at its edge with a new block or lawn, place it there, "
                     "and say so in your reply." if o.get("note") else
                     "Move it into free space (free_space in read_scene lists the empty areas).")
            problems.append("%s is new and stands through %s, which was there before. %s Move or remove %s only if "
                            "the request asked for that." % (o.get("thing"), o.get("overlaps_existing"), where,
                                                            o.get("overlaps_existing")))
        elif o.get("on"):
            problems.append("%s stands on top of %s%s. Unless it belongs there, like a lamp on a table, move it "
                            "down to the ground beside it." % (o.get("thing"), o.get("on"), part))
        elif o.get("inside"):
            problems.append("%s is inside %s%s. Unless it belongs there, move it out so they do not overlap." % (
                o.get("thing"), o.get("inside"), part))
    return problems



def _camera_move(scene):
    """``camera.move_m`` of a ``read_scene`` result (JSON text), or ``None``."""
    try:
        camera = json.loads(scene).get("camera")
    except (ValueError, AttributeError):
        return None
    move = camera.get("move_m") if isinstance(camera, dict) else None
    return move if isinstance(move, (int, float)) and not isinstance(move, bool) else None



def camera_problems(start, scene):
    """A sentence when the camera moved in ``start`` (the scene when the run began) and no longer moves in
    ``scene``; both are ``read_scene`` results."""
    before, now = _camera_move(start), _camera_move(scene)
    if before is None or now is None or before < CAMERA_MOVING or now >= CAMERA_STILL:
        return []
    return ["The camera does not move although the scene had a camera move of %s m from the first to the last "
            "frame: unless the request asks for a still camera, key the move again, with both location keys moved "
            "by the same offset." % before]



def view_problems(view):
    """Sentences for what a ``camera_view`` result (JSON text) shows clearly wrong, for the check stage."""
    try:
        data = json.loads(view)
        frames = data.get("frames") or []
    except (ValueError, AttributeError):
        return []
    problems = []
    subject = data.get("subject")
    if isinstance(subject, str):
        for point in frames + [p for p in data.get("during_move") or [] if isinstance(p, dict)]:
            state = point.get("subject") if isinstance(point, dict) else None
            if not isinstance(state, dict):
                continue
            n = point.get("frame")
            if not state.get("in_frame") or (state.get("coverage_pct") or 0) < SUBJECT_MIN_PCT:
                problems.append("At frame %s, the subject %s is out of the frame or almost gone: change the camera "
                                "move so it stays in view the whole time." % (n, subject))
            elif state.get("hidden_by"):
                problems.append("At frame %s, %s hides the subject %s from the camera: move the camera or its path "
                                "so the subject stays in clear view." % (n, state["hidden_by"], subject))
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        n = frame.get("frame")
        cover = frame.get("not_yours_cover_pct") or 0
        if cover > NOT_YOURS_MAX:
            problems.append("At frame %s, objects that are not yours cover %s%% of the frame: move the camera so "
                            "they leave the shot." % (n, cover))
        if (frame.get("toward_target") or {}).get("first_hit") == "(not yours)":
            problems.append("At frame %s, an object that is not yours stands between the camera and its aim "
                            "point." % n)
        if frame.get("camera_enclosed") is False:
            problems.append("At frame %s, the camera is not inside walls of yours: if the request is an interior, "
                            "move the camera inside the room." % n)
    return problems



def _unpainted(scene):
    """The ``no_material`` names of a ``read_scene`` result (JSON text)."""
    try:
        bare = json.loads(scene).get("no_material") or []
    except (ValueError, AttributeError):
        return []
    return [str(n) for n in bare]



def _has_no_lights(scene):
    """True when a ``read_scene`` result (JSON text) lists no lights of the run's own; ``False`` when unreadable."""
    try:
        data = json.loads(scene)
    except ValueError:
        return False
    return isinstance(data, dict) and data.get("lights") == []
