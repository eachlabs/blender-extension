"""The helper library in a run: load it and pick what to offer when the run starts, keep new helpers when it ends.

Main thread. The library lives in the add-on's own folder on this computer; with the setting off nothing is read
or written.
"""

import traceback

from .. import code_check
from ..library import helpers, store
from .live import chat_run

FOLDER = "library"


def _allowed(source):
    try:
        code_check.check(source)
        return True
    except code_check.Refused:
        return False


def prepare(run, prompt, context=None):
    """Load the library onto the run's build and set the note that offers the fitting helpers."""
    run.library_folder, run.library_offer = None, ""
    if not chat_run.preferences.helper_library(context):
        run.build.library = []
        return
    try:
        folder = chat_run.preferences.user_folder(FOLDER)
    except OSError:
        run.build.library = []
        return
    entries = [e for e in store.load(folder) if _allowed(e["source"])]  # the filter of this version decides
    run.library_folder = folder
    run.build.library = entries
    run.library_offer = helpers.offer_text(helpers.relevant(entries, prompt))


def keep(run, steps):
    """After a run that finished: store the helpers of its steps that ran without an error."""
    folder = getattr(run, "library_folder", None)
    if not folder:
        return
    found = []
    for step in steps:
        if step.get("state") == "ok" and step.get("code"):
            found.extend(helpers.extract(step["code"], _allowed))
    if not found:
        return
    try:
        merged = store.merged(store.load(folder), found)
        store.save(folder, merged)
        run.build.library = merged
    except OSError:  # a full disk or a read-only folder: the run's result stands without it
        traceback.print_exc()
