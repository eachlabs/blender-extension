"""The scene review: one call that judges the finished scene from four pictures, the guards on what it says, the
second look after its fix stage, and the done card's line. No Blender: the pictures and the undo come through
``execute`` (``review_run.py`` on the main thread)."""

import json
import re
import time

from ..instructions import review as text
from .messages import EARLIER_CHARS, EARLIER_MAX

ROUNDS = 2  # the one fix stage the review may add, as the plan's estimate counts it
PROBLEMS_MAX = 3
SAID_MAX = 2  # problems the done line names before "and N more"
TEXT_CHARS = 200  # each "what" and "fix" cut to this length
REQUEST_CHARS = 1500
THINGS_MAX = 80  # inventory lines sent with the review
# A fix that takes something away starts a cascade when the finding is wrong: such problems are dropped.
_REMOVES = re.compile(r"\b(remov\w*|delet\w*|drop\w*|get(?:ting)? rid of|eras\w*|discard\w*)\b", re.IGNORECASE)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")

# How the second look ended, for the done line.
FIXED, NO_ROOM, UNDONE, NOT_UNDONE, UNCHECKED = "fixed", "no_room", "undone", "not_undone", "unchecked"
ASK_UNDO = "ask_undo"  # Blender 4.2: the person takes the fix back
_AFTER = {NO_ROOM: " No rounds were left within your limit to fix it.",
          UNDONE: " The fix made the scene worse, so it was undone.",
          NOT_UNDONE: " The fix made the scene worse and could not be undone.",
          ASK_UNDO: " The fix made the scene worse: Undo stage takes it back."}


def rounds(on):
    """Rounds the plan's run estimate counts for the review: ``ROUNDS`` when it is on, else 0."""
    return ROUNDS if on else 0


def _json(reply):
    """The JSON object in a reply's text (a fenced block is fine), or ``None``."""
    body = _FENCE.sub("", str(reply or "").strip())
    try:
        found = json.loads(body)
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def _sentence(value):
    return " ".join(str(value).split())[:TEXT_CHARS] if isinstance(value, str) else ""


def parse(reply, names):
    """The problems of a review reply worth fixing: at most ``PROBLEMS_MAX``, each on a thing named exactly as in
    ``names``, with a fix that removes nothing. ``[]`` when the reply is no review (not JSON, nothing valid)."""
    found = _json(reply)
    problems = found.get("problems") if found is not None else None
    if not isinstance(problems, list):
        return []
    names = set(names)
    kept, seen = [], set()
    for entry in problems:
        if not isinstance(entry, dict) or not isinstance(entry.get("thing"), str):
            continue
        thing, what, fix = entry["thing"].strip(), _sentence(entry.get("what")), _sentence(entry.get("fix"))
        if thing not in names or not what or not fix or _REMOVES.search(fix) or (thing, what) in seen:
            continue
        seen.add((thing, what))
        kept.append({"thing": thing, "what": what, "fix": fix})
    return kept[:PROBLEMS_MAX]


def missing(reply):
    """The reply's ``missing`` list (for the debug log only: nothing is built from it)."""
    found = _json(reply)
    listed = found.get("missing") if found is not None else None
    return [_sentence(m) for m in listed if _sentence(m)] if isinstance(listed, list) else []


def parse_again(reply, count):
    """``(solved, worse)`` from the second look's reply, ``solved`` one bool per problem; ``None`` when unreadable."""
    found = _json(reply)
    if found is None or not isinstance(found.get("solved"), list):
        return None
    solved = [value is True for value in found["solved"][:count]]
    return solved + [False] * (count - len(solved)), found.get("worse") is True


def _pictures(images):
    return [{"type": "image_url", "image_url": {"url": url}} for url in images]


def messages(request, earlier, things, images):
    """The review call: the person's request and earlier requests, the things by name, then the pictures."""
    request = " ".join(str(request or "").split())[:REQUEST_CHARS]
    earlier = [" ".join(p.split())[:EARLIER_CHARS] for p in earlier if isinstance(p, str) and p.strip()][:EARLIER_MAX]
    before = text.EARLIER % "\n".join("- " + p for p in earlier) if earlier else ""
    ask = text.ASK % (request, before, "\n".join(things[:THINGS_MAX]), text.VIEWS)
    return [{"role": "system", "content": text.SYSTEM},
            {"role": "user", "content": [{"type": "text", "text": ask}] + _pictures(images)}]


def _numbered(problems):
    return "\n".join("%d. %s: %s" % (n, p["thing"], p["what"]) for n, p in enumerate(problems, 1))


def again_messages(problems, before, after):
    """The second look: the problems, then the same views before and after the fix."""
    parts = [{"type": "text", "text": text.AGAIN_ASK % _numbered(problems)}, {"type": "text", "text": text.BEFORE}]
    parts += _pictures(before) + [{"type": "text", "text": text.AFTER}] + _pictures(after)
    return [{"role": "system", "content": text.AGAIN_SYSTEM}, {"role": "user", "content": parts}]


def fix_text(problems):
    """What the fix stage is told, next to the measured problems."""
    return text.FIX_TEXT % "\n".join("%d. %s: %s Fix: %s" % (n, p["thing"], p["what"], p["fix"])
                                     for n, p in enumerate(problems, 1))


def _said(what, thing=""):
    """``what`` inside the line: no full stop, and a capital only where a name or a word like ``TV`` keeps it."""
    what = what.strip().rstrip(".!")
    if thing and what.startswith(thing):
        return what
    if len(what) > 1 and what[0].isupper() and what[1].islower():
        what = what[0].lower() + what[1:]
    return what


def done_line(problems, solved=None, ended=FIXED):
    """The done card's line: ``Review: the ladder does not reach the door (not fixed).``; ``""`` for no problems.
    ``solved``: one bool per problem from the second look; ``ended``: how the fix went (``FIXED`` … ``UNCHECKED``)."""
    if not problems:
        return ""
    said = []
    for index, problem in enumerate(problems):
        if ended == UNCHECKED:
            state = " (fix tried)"
        elif ended == FIXED and solved and index < len(solved) and solved[index]:
            state = " — fixed"
        else:
            state = " (not fixed)"
        said.append(_said(problem["what"], problem.get("thing", "")) + state)
    more = len(said) - SAID_MAX
    line = "Review: %s%s." % ("; ".join(said[:SAID_MAX]), " and %d more" % more if more > 0 else "")
    return line + _AFTER.get(ended, "")


class Reviewer:
    """The review of one run, on the worker thread. ``ask`` is the scene's model, ``quick`` the same without its
    hidden reasoning; both take ``(messages, tools)``. ``execute`` reaches the main thread: ``review_views``,
    ``review_mark`` and ``review_undo``. Any failure is no review: the run goes on as if it were off."""

    def __init__(self, ask, quick, execute, cancel, post, request, earlier=(), log=None):
        self.ask, self.quick, self.execute, self.cancel, self.post = ask, quick, execute, cancel, post
        self.request, self.earlier = request, list(earlier)
        self.log = log or (lambda entry: None)
        self.before = []  # the review's pictures, for the second look

    def _views(self):
        if self.cancel.is_set():
            return None
        self.post({"type": "looking", "state": True})
        try:
            found = self.execute("review_views", {})
        except Exception as exc:  # the review is extra: the run goes on without it
            self.log({"review": "views", "error": str(exc) or type(exc).__name__})
            return None
        finally:
            self.post({"type": "looking", "state": False})
        if not isinstance(found, dict) or not found.get("images") or not found.get("names"):
            self.log({"review": "views", "reason": found.get("reason") if isinstance(found, dict) else None})
            return None
        return found

    def _call(self, ask, sent):
        if self.cancel.is_set():
            return None
        self.post({"type": "thinking", "since": time.monotonic()})
        try:
            reply = ask(sent, [])
            return reply["choices"][0]["message"].get("content") or ""
        except Exception as exc:  # a failed call is no review
            self.log({"review": "call", "error": str(exc) or type(exc).__name__})
            return None
        finally:
            self.post({"type": "thinking", "since": None})

    def find(self):
        """The problems the review keeps, or ``[]``."""
        self.before = []
        found = self._views()
        if found is None:
            return []
        reply = self._call(self.ask, messages(self.request, self.earlier, list(found.get("things") or found["names"]),
                                              found["images"]))
        kept = parse(reply, found["names"])
        self.log({"review": "found", "reply": reply, "kept": kept, "missing": missing(reply)})
        if kept:
            self.before = list(found["images"])
        return kept

    def mark(self):
        """Before the fix stage: the main thread notes the undo steps so far, so only that stage is undone."""
        try:
            self.execute("review_mark", {})
        except Exception:  # without the mark the undo refuses; the fix still runs
            pass

    def again(self, problems):
        """``(solved, worse)`` after the fix stage, or ``None`` when the second look could not be made."""
        found = self._views() if self.before else None
        if found is None:
            return None
        reply = self._call(self.quick, again_messages(problems, self.before, found["images"]))
        outcome = parse_again(reply, len(problems))
        self.log({"review": "again", "reply": reply, "outcome": outcome})
        return outcome

    def undo(self):
        """Undo the fix stage on the main thread: ``UNDONE``, ``ASK_UNDO`` (the person does it), or ``NOT_UNDONE``."""
        try:
            done = self.execute("review_undo", {})
        except Exception as exc:
            self.log({"review": "undo", "error": str(exc) or type(exc).__name__})
            return NOT_UNDONE
        self.log({"review": "undo", "result": done})
        if isinstance(done, dict) and done.get("undone") is True:
            return UNDONE
        return ASK_UNDO if isinstance(done, dict) and done.get("ask") else NOT_UNDONE
