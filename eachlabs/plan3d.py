"""The plan the chat shows before it spends anything: which objects are built in code, which solid pieces are
generated in 3D, and which objects get a reference picture.

One model call returns the plan as JSON (``INSTRUCTIONS``, ``request``, ``parse``). Every object is built in code
from real parts; only a solid single piece (a statue, a boulder: no parts of its own) may be generated as a 3D
model, because a generated model is one closed surface. The person can move a solid piece between 3D and code, then
press Build; nothing is paid for before that. Pure Python, no ``bpy``.
"""

import colorsys
import json
import re
from dataclasses import dataclass, field

from . import workflow_3d
from .asset_cache import key

from .placement import area_rules
from .instructions.plan import CODE_MAX, FOLLOW_UP, INSTRUCTIONS, request, system  # noqa: F401

TIERS = ("large", "medium")
MAX_ITEMS = 24  # chips one plan shows
NAME_CHARS = 32
PLAN_TOKENS = 2400
DETAILS = ("high", "medium", "low")
REFERENCES_MAX = 4  # reference pictures one plan may order


def _stem(word):
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def name_words(name):
    """An object or item name as plain words, without copy numbers: "Trees_2.001" -> ["tree"]."""
    words = re.split(r"[^a-z0-9]+", str(name or "").lower())
    return [_stem(w) for w in words if w and not w.isdigit()]


def root_name(item_name, copy=None):
    """The name the chat gives the root object of an item's code version: "Sports car", or "Trees 2" for a copy."""
    base = " ".join(str(item_name).split())
    base = base[:1].upper() + base[1:]
    return base if copy is None else "%s %d" % (base, copy)


# What the person says to ask for a real 3D model. Their words are binding: the item named next to them goes in 3D.
REAL_WORDS = ("hyper-realistic", "hyperrealistic", "hyper realistic", "photorealistic", "photoreal", "realistic",
              "real", "3d model", "3d models", "generated in 3d", "in 3d")
REAL_WINDOW = 6  # words before an item's name in which the person's words count for it
PHRASE_BREAKS = frozenset(("and", "or", "but", "then", "with", "add", "make", "put", "place", "replace", "remove",
                           "to", "of", "on", "by", "near", "next", "beside", "behind"))  # where the item's words end


def asked_real(prompt, item_name):
    """True when the prompt asks for the item to be real: one of ``REAL_WORDS`` within a few words before its name,
    or right after it ("a car in 3D")."""
    words = name_words(prompt.replace("-", " ").replace("3D", "3d"))
    target = name_words(item_name)
    if not target:
        return False
    text_real = [name_words(w.replace("-", " ")) for w in REAL_WORDS]
    for start in range(len(words) - len(target) + 1):
        if words[start:start + len(target)] != target:
            continue
        before = words[max(0, start - REAL_WINDOW):start]
        for cut in range(len(before) - 1, -1, -1):  # only the words describing this item: back to "and", "with"…
            if before[cut] in PHRASE_BREAKS:
                before = before[cut + 1:]
                break
        after = words[start + len(target):start + len(target) + 3]
        for real in text_real:
            n = len(real)
            if any(before[i:i + n] == real for i in range(len(before) - n + 1)) or after[:n] == real:
                return True
    return False


def bind(plan, prompt):
    """Move every solid piece the person asked to be real into 3D, as their own choice; returns the items moved. An
    object with parts stays in code and gets high detail instead."""
    moved = []
    for item in plan.items:
        if item.mode == "code" and not item.solid and asked_real(prompt, item.name):
            item.detail = "high"
            continue
        if item.mode == "code" and item.solid and asked_real(prompt, item.name):
            item.mode, item.chosen = "3d", True
            if item.tier not in TIERS:
                item.tier = "large"
            moved.append(item)
    return moved


def asks_real(prompt):
    """True when the prompt asks for something to be real (hyper-realistic, photoreal, a 3D model…)."""
    words = name_words(prompt.replace("-", " ").replace("3D", "3d"))
    for real in REAL_WORDS:
        real = name_words(real.replace("-", " "))
        if any(words[i:i + len(real)] == real for i in range(len(words) - len(real) + 1)):
            return True
    return False


def upgrade(plan, label, targets, size):
    """Make the plan upgrade existing objects in place, when the plan calls them a solid piece: that item goes in 3D,
    with ``targets`` as its code version and the size of what exists. ``size``: (width, depth, height) in metres.
    ``None`` for anything with parts: it stays in code, and the change adds detail to it there."""
    item = next((i for i in plan.items if names_item(i.name, label) or any(names_item(t, i.name) for t in targets)),
                None)
    if item is None or not item.solid:
        return None
    item.mode, item.chosen, item.targets = "3d", True, list(targets)
    if item.tier not in TIERS:
        item.tier = "large"
    width, depth, height = size
    item.measure = "height" if height >= max(width, depth) else "length"
    item.size_m = round(height if item.measure == "height" else max(width, depth), 3) or None
    plan.adds_objects = True
    return item


PICTURE_PARTS = 10  # part names an upgrade's picture prompt carries
PICTURE_LOOKS = 6  # materials it carries


def colour_word(rgb):
    """A plain colour word for a linear RGB base colour: "red", "dark grey"."""
    r, g, b = (max(0.0, min(1.0, float(c))) ** (1 / 2.2) for c in rgb[:3])  # as the eye sees it
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    if sat < 0.15 or light < 0.08 or light > 0.95:
        return "black" if light < 0.15 else "white" if light > 0.85 else "dark grey" if light < 0.4 else "grey"
    names = ((0.04, "red"), (0.10, "orange"), (0.18, "yellow"), (0.45, "green"), (0.53, "teal"), (0.72, "blue"),
             (0.83, "purple"), (0.95, "pink"), (1.01, "red"))
    word = next(name for edge, name in names if hue < edge)
    if word == "orange" and light < 0.35:
        word = "brown"
    return ("dark " if light < 0.25 else "light " if light > 0.75 else "") + word


def upgrade_picture(name, request, parts, looks):
    """The picture prompt for an upgrade to 3D, from the object as it is: its name, its parts' names, its
    materials (``[(material name, colour word)]``) and the person's request."""
    own = set(name_words(name))
    kept = []
    for part in parts:
        words = [w for w in name_words(part) if w not in own]
        text = " ".join(words)
        if text and text not in kept:
            kept.append(text)
    shown = []
    for material, colour in looks:
        words = " ".join(w for w in name_words(material) if w not in own and w not in ("material", "mat"))
        text = ("%s %s" % (colour, words)).strip() if colour and colour not in words else words or colour
        if text and text not in shown:
            shown.append(text)
    label = " ".join(str(name).split())
    lines = ["%s, as the person asked: \"%s\"" % (label, " ".join(str(request).split())[:160])]
    if kept:
        lines.append("with " + ", ".join(kept[:PICTURE_PARTS]))
    if shown:
        lines.append("in " + ", ".join(shown[:PICTURE_LOOKS]))
    lines.append("the whole %s fully in view at full size, three-quarter view" % label)
    return "; ".join(lines)


def looks_cost(concept, textures, price, references=(), reference_price=0.0, concept_price=None):
    """The most the looks may cost, in dollars: the concept picture, up to ``textures`` textures, the references."""
    return ((price if concept_price is None else concept_price) * (1 if concept else 0) + price * max(0, textures)
            + reference_price * len(references))


def looks_text(concept, textures, price, references=(), reference_price=0.0, concept_price=None):
    """The plan's line for what the looks may cost: the concept picture (at ``concept_price``, else ``price``) and up
    to ``textures`` textures at ``price`` each, and a reference picture of each object in ``references`` at
    ``reference_price``; ``""`` when none is on."""
    parts = []
    if concept or textures > 0:
        what = " and ".join(([("a concept picture")] if concept else [])
                            + (["up to %d texture%s" % (textures, "" if textures == 1 else "s")] if textures > 0
                               else []))
        total = (price if concept_price is None else concept_price) * (1 if concept else 0) + price * max(0, textures)
        parts.append("Looks: %s · %s$%s" % (what, "up to " if textures > 0 else "", _money(total)))
    if references:
        parts.append("References: %s · $%.2f" % (", ".join(references), reference_price * len(references)))
    return ". ".join(parts)


def _money(total):
    """``0.21`` for dollars, or three places under a cent (``0.005``)."""
    return "%.2f" % total if total >= 0.01 or total == 0 else "%.3f" % total


def looks_plan(concept, textures, price, concept_price=None):
    """The plan shown when no plan of objects is: only the looks line, so a concept picture or a texture is never
    paid for before Build. ``None`` when neither can be made."""
    looks = looks_text(concept, textures, price, concept_price=concept_price)
    return Plan(adds_objects=False, looks=looks, looks_only=True) if looks else None


def mentions(object_name, item_name):
    """True when an object's name has every word of the item's name: "Sidewalk_left" for "sidewalks"."""
    words = set(name_words(item_name))
    return bool(words) and words <= set(name_words(object_name))


def missing(plan, object_names, done=(), placed=None):
    """The plan's items that are not in the scene, as the names the chat should build them under. A 3D item is in
    the scene when its model arrived (``done`` holds its name) or its code version has its exact name; a code item
    when some object of the chat's own is named after it. ``placed(item, holder)``, when given, also says whether
    an item with a holder (books on a bookshelf) stands on or in it: one that stands elsewhere is missing too."""
    out = []
    for item in plan.items:
        if item.mode == "3d":
            present = (item.name in done or any(names_item(n, item.name) for n in object_names)
                       or any(t in object_names for t in item.targets))
        else:  # "church and hall" is two things: each must be there, under a name of its own
            parts = [p for p in re.split(r"\s+(?:and|&)\s+|\s*,\s*", item.name) if p.strip()] or [item.name]
            present = all(any(mentions(n, part) for n in object_names) for part in parts)
        if present and item.holder and placed is not None and not placed(item.name, item.holder):
            present = False
        if not present:
            out.append(item)
    return out


def missing_text(item):
    """How the chat is asked to build a missing item."""
    if item.mode == "3d":
        return "\"%s\" (the code version of a 3D object: one root object named exactly \"%s\")" % (
            root_name(item.name), root_name(item.name))
    if item.holder:
        return "%s (named after it, on or in the %s)" % (item.name, item.holder)
    return "%s (named after it)" % item.name


def names_item(object_name, item_name):
    """True when an object's name is the item's name, with or without a copy number: the root of its code
    version."""
    return bool(name_words(item_name)) and name_words(object_name) == name_words(item_name)


@dataclass
class Item:
    name: str  # what the chip says: "car"
    description: str  # what is generated: "red 1970s muscle car"
    tier: str = "large"
    mode: str = "3d"  # "3d" or "code"
    cached: bool = False  # a 3D item the cache already holds: no run, no cost
    chosen: bool = False  # the person moved it; their choice always stands
    picture_prompt: str = ""  # the chat's words for drawing it for 3D; the description when empty
    size_m: float = None  # its real size in metres along ``measure``; the code version's size when unknown
    measure: str = ""  # "height" or "length"
    targets: list = field(default_factory=list)  # existing objects it upgrades: they become its code version
    solid: bool = False  # a solid single piece with no parts of its own: the only kind that may be generated in 3D
    detail: str = "medium"  # how much detail its code version needs: high, medium or low
    holder: str = ""  # the planned thing it stands on or in ("bookshelf" for books): built there, checked there
    part_of: str = ""  # the planned thing it belongs to as a thing of its own (a sign on a shop): its parent thing
    colour: str = ""  # "#rrggbb" when the request names its colour: read_scene checks the thing has it


@dataclass
class Plan:
    items: list = field(default_factory=list)
    limit: int = 2  # 3D items the chat may suggest; the person may move any number more to 3D
    note: str = ""
    adds_objects: bool = True  # False for a change that only removes, moves or recolours: no plan is shown
    looks: str = ""  # the plan's one line for the concept picture and the textures (``looks_text``)
    looks_only: bool = False  # no objects: the plan only asks before the concept picture and textures are paid for
    rounds_needed: int = 0  # rounds the request needs when that is more than the person's limit, else 0
    rounds_limit: int = 0  # the person's limit then
    areas: list = field(default_factory=list)  # how the request relates its places (placement.area_rules)

    @property
    def three_d(self):
        return [i for i in self.items if i.mode == "3d"]

    @property
    def code(self):
        return [i for i in self.items if i.mode == "code"]

    @property
    def paid(self):
        return [i for i in self.three_d if not i.cached]

    @property
    def movable(self):
        """The items the person may move between 3D and code: the solid pieces."""
        return [i for i in self.items if i.solid]

    def references(self, limit=REFERENCES_MAX):
        """The code items that get a reference picture: the high-detail ones, in the plan's order."""
        return [i for i in self.code if i.detail == "high"][:max(0, limit)]

    def asks(self):
        """True when the plan has something for the person to decide or pay for before Build, or the request needs
        more rounds than the person allows."""
        return bool(self.movable or self.three_d or self.looks or self.rounds_needed)

    def toggle(self, index):
        """Move a solid piece between 3D and code. The person's choice is never refused for a solid piece (the
        limit is for the chat's own suggestions only); an object with parts always stays in code."""
        if not 0 <= index < len(self.items):
            return False
        item = self.items[index]
        if not item.solid:
            return False
        item.mode = "code" if item.mode == "3d" else "3d"
        item.chosen = True
        return True

    def cost(self):
        return round(len(self.paid) * workflow_3d.COST, 2)

    def minutes(self):
        """About how long the 3D objects take one by one: the 3D models are made one at a time."""
        seconds = sum(workflow_3d.TIER_SECONDS.get(i.tier, 200) for i in self.paid)
        return max(1, round(seconds / 60.0)) if seconds else 0

    def summary_3d(self):
        """``3D: car, house · 2 × $0.45 = $0.90 · about 6 min one by one``, cached items counted as free; ``""``
        when nothing is made in 3D, so the plan shows no 3D line."""
        names = [i.name for i in self.three_d]
        if not names:
            return ""
        parts = ["3D: " + ", ".join(names)]
        if self.paid:
            parts.append("%d × $%.2f = $%.2f" % (len(self.paid), workflow_3d.COST, self.cost()))
        cached = len(self.three_d) - len(self.paid)
        if cached:
            parts.append("%d cached, free" % cached)
        if self.paid:
            parts.append("about %d min one by one" % self.minutes())
        return " · ".join(parts)

    def summary_code(self):
        names = [i.name for i in self.code]
        return "Code: " + (", ".join(names) if names else "the rest of the scene")

    def brief(self):
        """For the layout stage: the code version each approved 3D item needs, under its exact name."""
        lines = ["3D objects the person approved; their 3D models are already ordered. Build a simple code version "
                 "of each now, with its root object named exactly as given (copies: the name and a number):"
                 ] if self.three_d else []
        lines += ["- \"%s\" (copies \"%s\", \"%s\"…): %s%s" % (
            root_name(i.name), root_name(i.name, 1), root_name(i.name, 2), i.description,
            ", %g m %s" % (i.size_m, "tall" if i.measure == "height" else "long") if i.size_m else "")
            for i in self.three_d if not i.targets]
        lines += ["- %s: already in the scene as %s; keep it as it is, its 3D model replaces it." % (
            i.name, ", ".join(i.targets)) for i in self.three_d if i.targets]
        code = [i.name for i in self.code]
        if code:
            lines.append("Build these with run_python as usual, named after them: %s." % ", ".join(code))
        owned = ["%s belongs to the %s" % (i.name, i.part_of) for i in self.items if i.part_of]
        if owned:
            lines.append("Things that belong to another (give it as parent= in thing()): %s." % "; ".join(owned))
        return "\n".join(lines)

    def queue(self):
        """Every approved 3D item in the order its models are made: large tier first, then the plan's order."""
        rank = {"large": 0, "medium": 1}
        return sorted(self.three_d, key=lambda i: (rank.get(i.tier, 2), self.items.index(i)))


def _json(text):
    """The first JSON object in ``text``, also inside a code fence; ``None`` when there is none."""
    text = text or ""
    start = text.find("{")
    while start != -1:
        depth = 0
        for end in range(start, len(text)):
            if text[end] == "{":
                depth += 1
            elif text[end] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(text[start:end + 1])
                    except ValueError:
                        break
                    return value if isinstance(value, dict) else None
        start = text.find("{", start + 1)
    return None


def _name(value):
    return " ".join(str(value or "").split())[:NAME_CHARS].strip()


def _drawing(item, entry):
    """The item with the chat's picture prompt, size and detail, when it gave them."""
    if entry.get("detail") in DETAILS:
        item.detail = entry["detail"]
    if entry.get("solid") is True:
        item.solid = True
    holder = entry.get("on") or entry.get("in")
    if isinstance(holder, str) and holder.strip():
        item.holder = " ".join(holder.split())[:60].lower()
    owner = entry.get("part_of")
    if isinstance(owner, str) and owner.strip():
        item.part_of = " ".join(owner.split())[:60].lower()
    colour = entry.get("colour") or entry.get("color")
    if isinstance(colour, str) and re.fullmatch(r"#?[0-9a-fA-F]{6}", colour.strip()):
        item.colour = "#" + colour.strip().lstrip("#").lower()
    prompt = entry.get("picture_prompt")
    if isinstance(prompt, str) and prompt.strip():
        item.picture_prompt = " ".join(prompt.split())[:400]
    size = entry.get("size_m")
    if isinstance(size, (int, float)) and not isinstance(size, bool) and 0.01 <= size <= 1000:
        item.size_m = float(size)
        item.measure = entry.get("measure") if entry.get("measure") in ("height", "length") else "height"
    return item


# Words that make a plan entry a removal, which is done with code and is never a thing the build checks is there.
REMOVAL_WORDS = frozenset(("remove", "removal", "removed", "delete", "deleted", "deletion", "demolish", "demolition",
                           "without"))


def is_removal(name):
    """True for an entry that names taking something away ("lighthouse removal"), not a thing to build."""
    return bool(REMOVAL_WORDS & set(str(name).lower().replace("-", " ").split()))


def parse(text, limit, cached=lambda description, tier: False):
    """A ``Plan`` from the model's answer; ``None`` when it holds no plan. A tiny object and every 3D object past
    ``limit`` go to code; ``cached(description, tier)`` marks the ones the cache holds."""
    data = _json(text)
    if data is None:
        return None
    plan = Plan(limit=max(0, limit), adds_objects=data.get("adds_objects") is not False,
                areas=area_rules.parse(data.get("areas")))
    seen = set()
    for entry in data.get("objects_3d") or []:
        if not isinstance(entry, dict):
            continue
        name = _name(entry.get("name") or entry.get("description"))
        description = " ".join(str(entry.get("description") or name).split())[:120]
        if not name or key(description) in seen:
            continue
        seen.add(key(description))
        tier = entry.get("tier") if entry.get("tier") in TIERS + ("tiny",) else "large"
        mode = "3d" if tier in TIERS and len(plan.three_d) < plan.limit else "code"
        tier = tier if tier in TIERS else "medium"
        item = _drawing(Item(name.lower(), description, tier, mode), entry)
        item.solid = True  # the chat put it in objects_3d: a solid piece
        plan.items.append(item)
    for entry in (data.get("code") or [])[:CODE_MAX]:
        name = _name(entry if isinstance(entry, str) else (entry or {}).get("name") if isinstance(entry, dict) else "")
        if name and key(name) not in seen and not is_removal(name):
            seen.add(key(name))
            item = Item(name.lower(), name, "medium", "code")
            plan.items.append(_drawing(item, entry) if isinstance(entry, dict) else item)
    del plan.items[MAX_ITEMS:]
    for item in plan.items:
        item.cached = bool(cached(item.description, item.tier))
    return plan


def mark_cached(plan, cached):
    """Set ``cached`` again on every item, after a move between 3D and code."""
    for item in plan.items:
        item.cached = bool(cached(item.description, item.tier))
