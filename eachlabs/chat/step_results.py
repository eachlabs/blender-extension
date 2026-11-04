"""Reading what a step or a stage came back with: errors, Code check refusals, enum hints and stages cut short."""

import re

from .. import code_check
from . import run_types


def _stopped_total(limits, reply="", skipped=()):
    """The round limit ends the run as done: what was built is kept, and a follow-up continues the scene. A reply
    the check stage already gave stays the reply."""
    if reply:
        return run_types.RunResult("done", "\n".join([reply] + list(skipped)), limits.total_rounds, None)
    return run_types.RunResult("done", "\n".join(["Stopped after %d rounds. What was built is kept." % limits.total_rounds]
                                       + list(skipped)), limits.total_rounds, None)



def _result_error(result):
    """The error of a tool result that reports one (``{"ok": False, "error": ...}``), else ``None``."""
    if isinstance(result, dict) and result.get("ok") is False:
        return str(result.get("error") or "the step failed")
    return None



def _detail(error):
    """One line of an error for the chat row: the last line of a traceback."""
    lines = [line for line in str(error).strip().splitlines() if line.strip()]
    return lines[-1].strip() if lines else str(error)



CHECK_REFUSALS = 3  # Code check refusals in a row that stop the run
NO_CONTEXT = "could not read which objects the chat made"  # Code check refuses the step without a review



def refusal_ends(event):
    """True when a ``post`` event shows the model moved on from a step Code check refused: a stage changed,
    a reply came, or its next tool call started."""
    kind = event.get("type")
    return kind in ("stage", "reply") or (kind == "tool" and event.get("state") == "running")



_ENUM = re.compile(r'enum "([^"]*)" not found in \(([^)]*)\)')
PARTLY_DONE = "%s: partly done, %s."
SKIPPED_AT_CAP = "%s: skipped, the round limit was reached."



def enum_hint(error):
    """For an error that names a wrong enum value: the line that lists the allowed values, else ``""``."""
    found = _ENUM.search(str(error or ""))
    if not found:
        return ""
    return "Use one of these values exactly: %s." % found.group(2).strip()



def _passes_filter(code):
    """True when the rule filter lets ``code`` through, so Code check has something to read.
    ``execute`` checks the code again on purpose, so a step the review allowed is still filtered."""
    try:
        code_check.check(code)
    except code_check.Refused:
        return False
    return True
