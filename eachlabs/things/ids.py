"""Thing ids, labels and names: pure, no Blender."""

import re
import uuid

THING = "eachlabs_thing"  # every object of the chat's: the id of the thing it belongs to
KIND = "eachlabs_kind"  # a thing's root object: what it is, as the model says
LABELS = "eachlabs_labels"  # a thing's root object: other words for it, comma separated
PARENT = "eachlabs_parent"  # a thing's root object: the parent thing's id, or ""
COPY_OF = "eachlabs_copy_of"  # a copy's root object: the id of the thing it copies

LABELS_MAX = 6
WORD_MAX = 40
NAME_MAX = 60  # Blender names hold 63 bytes; leave room for its ".001"


def new_id(taken=()):
    while True:
        tid = uuid.uuid4().hex[:8]
        if tid not in taken:
            return tid


def clean_word(text):
    """One kind or label: plain words, single spaces, lower case, at most ``WORD_MAX`` characters."""
    words = re.sub(r"[_\-./]+", " ", str(text or "")).split()
    return " ".join(words).lower()[:WORD_MAX].strip()


def labels(value, kind=""):
    """Labels from a string ("wall, perimeter") or a list, cleaned, without the kind, at most ``LABELS_MAX``."""
    items = value.split(",") if isinstance(value, str) else list(value or ())
    out, base = [], clean_word(kind)
    for item in items:
        word = clean_word(item)
        if word and word != base and word not in out:
            out.append(word)
    return out[:LABELS_MAX]


def kind_from_name(name):
    """A kind for a thing the model did not describe: its name without numbers and copy suffixes."""
    word = clean_word(re.sub(r"\.\d+$", "", str(name or "")))
    word = re.sub(r"(\s\d+)+$", "", word).strip()
    return word or "thing"


def base_name(name):
    """The name a thing goes by, from the name the model gave its root: separators as spaces, copy numbers and
    Blender's ``.001`` dropped, the first letter upper case, the rest as written (``town_hall.002`` ->
    ``Town hall``, ``Building A`` stays)."""
    text = re.sub(r"\.\d+$", "", str(name or ""))
    text = " ".join(re.sub(r"[_]+", " ", text).split())
    text = re.sub(r"(\s\d+)+$", "", text).strip()
    return title(text) or "Thing"


def title(text):
    """``town hall`` -> ``Town hall``."""
    text = str(text or "").strip()
    return text[:1].upper() + text[1:]


def thing_name(kind, parent=None):
    """``Clock (Town hall)`` for a thing with a parent thing, ``Town hall`` without one."""
    base = title(kind)
    name = "%s (%s)" % (base, parent) if parent else base
    return name[:NAME_MAX]


def part_name(thing, part, kind=""):
    """``Town hall / Roof``: a part named under its thing, from the name the model gave it, without the thing's own
    words repeated (``town hall roof`` -> ``Roof``)."""
    words = re.sub(r"[_\-./]+", " ", re.sub(r"\.\d+$", "", str(part or ""))).split()
    known = set(clean_word(thing).split()) | set(clean_word(kind).split())
    rest = [w for w in words if w.lower() not in known] or words or ["part"]
    return ("%s / %s" % (thing, title(" ".join(rest))))[:NAME_MAX]


def matches(entry, word):
    """Whether a request word names this inventory entry by its name, kind or a label (whole words, any order)."""
    want = set(clean_word(word).split())
    if not want:
        return False
    for text in [entry.get("name", ""), entry.get("kind", "")] + list(entry.get("labels") or ()):
        if want <= set(clean_word(text).split()):
            return True
    return False


def subtree(parents, tid):
    """``tid`` and every thing below it, from ``{id: parent id}``."""
    out, todo = [], [tid]
    while todo:
        cur = todo.pop()
        if cur in out:
            continue
        out.append(cur)
        todo.extend(k for k, v in parents.items() if v == cur)
    return out


def inventory_line(entry):
    """``Town hall | kind: building | also: hall, civic building | in: Larger village | 42 parts``: one line the
    intent call reads."""
    bits = [entry["name"], "kind: %s" % (entry.get("kind") or "thing")]
    if entry.get("labels"):
        bits.append("also: %s" % ", ".join(entry["labels"]))
    if entry.get("parent"):
        bits.append("in: %s" % entry["parent"])
    if entry.get("parts"):
        bits.append("%d parts" % entry["parts"])
    return " | ".join(bits)
