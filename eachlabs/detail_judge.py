"""Candidates in the detail stage: build an object twice from the same start and keep the version the judge prefers.

Worker thread; every scene change goes through ``execute`` to the main thread (``candidate_stash``,
``candidate_restore``, ``candidate_shot``, ``candidate_drop``). Only the first few main objects get candidates, and
only while the model takes pictures: each extra version costs the object's rounds again plus one judge call.
"""

from . import chat_loop
from .chat import judge

OBJECTS = 2  # main objects per run that get candidates; the rest are built once


def eligible(targets, settings, visual):
    """Names of the targets that get candidates: the first ``OBJECTS`` high-detail ones."""
    if getattr(settings, "candidates", 1) < 2 or visual is None or not visual.accepted:
        return set()
    return set([t.name for t in targets if t.level == "high"][:OBJECTS])


def extra_rounds(targets, settings, visual):
    """Rounds the candidates add to the detail stage's budget, so the bar's count and the cap include them."""
    names = eligible(targets, settings, visual)
    return sum(t.rounds(settings.rounds, settings.light_rounds) * (settings.candidates - 1)
               for t in targets if t.name in names)


def improve_best(target, prompt, quick_llm, execute, cancel, settings, build_once, clean):
    """Build ``settings.candidates`` versions of ``target`` with ``build_once()`` (which returns ``(steps, line,
    seconds)``) and keep the best. Returns ``(steps, line, seconds, verdict)``; ``verdict`` names the object and the
    version kept, with an ``error`` when no judging happened (a picture failed, a build failed, the run stopped)."""
    keys, versions, steps, line, seconds = [], [], [], "", 0.0
    live_is_last = True  # the live object is the last version built, not the start put back

    def keep_first(reason):
        """A failed or empty second build never leaves the start in place: the first version comes back."""
        if versions and not live_is_last:
            execute("candidate_restore", {"object": target.name, "key": versions[0][0]})
        return steps, line, seconds, {"object": target.name, "kept": 1, "error": clean(reason)}

    try:
        start = execute("candidate_stash", {"object": target.name})["key"]
        keys.append(start)
        for n in range(max(1, settings.candidates)):
            if n:
                execute("candidate_restore", {"object": target.name, "key": start})
                live_is_last = False
            more, line, secs = build_once()
            steps += more
            seconds += secs
            if n and (not more or line):  # the second build ran no step or stopped part way
                return keep_first(line or "the second version ran no step")
            if cancel.is_set():
                return keep_first("stopped") if n else (steps, line, seconds, {"object": target.name, "kept": 1,
                                                                                 "error": "stopped"})
            shot = execute("candidate_shot", {"object": target.name})
            key = execute("candidate_stash", {"object": target.name})["key"]
            keys.append(key)
            versions.append((key, shot.get("images") or []))
            live_is_last = True
        if len(versions) < 2 or not all(images for _key, images in versions):  # nothing to compare: the last stays
            return steps, line, seconds, {"object": target.name, "versions": len(versions), "kept": len(versions),
                                          "error": "no pictures to compare"}
        best, reasons = 0, []
        for index in range(1, len(versions)):
            reply = chat_loop.retried(quick_llm, cancel)(
                judge.messages(prompt, target.name, versions[best][1], versions[index][1]), [])
            letter, reason = judge.verdict(reply["choices"][0]["message"].get("content") or "")
            reasons.append(clean(reason))
            if letter == "B":
                best = index
        if best != len(versions) - 1:  # the live object is the last version built
            execute("candidate_restore", {"object": target.name, "key": versions[best][0]})
        return steps, line, seconds, {"object": target.name, "versions": len(versions), "kept": best + 1,
                                      "reason": reasons[-1] if reasons else ""}
    except Exception as exc:  # judging is extra: the object keeps a version that was built
        try:
            return keep_first(str(exc) or type(exc).__name__)
        except Exception:  # putting it back failed too: say so in the log
            return steps, line, seconds, {"object": target.name, "error": clean(str(exc) or type(exc).__name__)}
    finally:
        try:
            execute("candidate_drop", {"keys": keys})
        except Exception:  # the stash scene goes with the file at worst; it holds no person's data
            pass
