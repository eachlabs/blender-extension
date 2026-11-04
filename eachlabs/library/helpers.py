"""The helpers in a step's code, which ones a later step calls, and which ones fit a request. Pure Python, no ``bpy``.

A helper is a top-level function the model wrote in a step that ran and was kept. It is stored with its source and
a short description, and filtered by the same code filter as any step again when it is reused, so a stored helper
can never do more than a step may.
"""

import ast
import hashlib
import re

LINES_MIN = 3  # a helper shorter than this is not worth keeping
SOURCE_CHARS_MAX = 4000
DESCRIPTION_CHARS = 120
OFFERED = 6  # helpers named to the model in one run
_WORD = re.compile(r"[a-z]+")
_STOP = frozenset(("a", "an", "and", "the", "of", "in", "on", "with", "to", "for", "make", "build", "add", "def"))


def words(text):
    return {w for w in _WORD.findall(str(text or "").lower().replace("_", " ")) if len(w) > 2 and w not in _STOP}


def _description(node, lines):
    doc = ast.get_docstring(node)
    if doc:
        return " ".join(doc.split())[:DESCRIPTION_CHARS]
    above = lines[node.lineno - 2].strip() if node.lineno >= 2 else ""
    if above.startswith("#"):
        return " ".join(above.lstrip("#").split())[:DESCRIPTION_CHARS]
    return node.name.replace("_", " ")


def extract(code, allowed):
    """``[{"name", "args", "source", "description", "hash"}]`` for the helpers in ``code`` that ``allowed(source)``
    (the code filter) lets through."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    lines = code.splitlines()
    out = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name.startswith("_"):
            continue
        if node.end_lineno - node.lineno + 1 < LINES_MIN:
            continue
        source = ast.get_source_segment(code, node)
        if not source or len(source) > SOURCE_CHARS_MAX or not allowed(source):
            continue
        args = ", ".join(a.arg for a in node.args.args)
        out.append({"name": node.name, "args": args, "source": source, "description": _description(node, lines),
                    "hash": hashlib.sha1(source.encode()).hexdigest()[:12]})
    return out


def relevant(entries, request, limit=OFFERED):
    """The entries whose name and description share the most words with ``request``, best first; none in common
    means not offered."""
    asked = words(request)
    scored = []
    for index, entry in enumerate(entries):
        score = len(asked & (words(entry["name"]) | words(entry.get("description"))))
        if score:
            scored.append((-score, -index, entry))
    scored.sort(key=lambda row: (row[0], row[1]))
    return [entry for _s, _i, entry in scored[:limit]]


def offer_text(entries):
    """The note that names the offered helpers to the model, or ``""``."""
    if not entries:
        return ""
    rows = ["- %s(%s): %s" % (e["name"], e["args"], e["description"]) for e in entries]
    return ("Helpers that worked in earlier scenes on this computer. Call one by its name in run_python and it is "
            "defined for you; never define it again:\n" + "\n".join(rows))


def prelude(code, entries):
    """The sources of the stored helpers ``code`` calls by name and does not define itself, joined, or ``""``."""
    defined = set(re.findall(r"^\s*def\s+([A-Za-z_]\w*)", code, re.M))
    called = set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", code))
    chosen, seen = [], set()
    for entry in entries:
        name = entry["name"]
        if name in called and name not in defined and name not in seen:
            seen.add(name)
            chosen.append(entry["source"])
    return "\n\n".join(chosen)
