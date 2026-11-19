"""Keeping a scene chat's each::sense session: a finished run stores its lines, an opened file reads its prompts.

Both happen on a thread of their own and never on the run's path: a chat works the same with the API unreachable,
with history turned off, or for an organization whose chats each::sense does not store."""

import threading

from .. import code_check, main_thread, preferences, scene_build
from .live import chat_run
from . import debug_log, session_log

RESTORE_MAX = 20  # scene chats of one opened file whose sessions are read
SHOWN_MAX = 200  # lines of one scene chat the history view keeps
_lock = threading.Lock()  # one request at a time, so two runs never start two sessions for one scene


def _on(context=None):
    return not chat_run._sessions["off"] and preferences.chat_history(context)


def _failed(exc, what, secrets=()):
    if session_log.unavailable(exc):
        chat_run._sessions["off"] = True
    debug_log.debug_log({"session": what, "error": str(exc) or type(exc).__name__}, secrets)


def record(run, status):
    """Main thread, when a run ended: store its prompt and what the bar answered. Never raises."""
    try:
        state, build = chat_run.STATE, run.build
        from .. import VERSION

        detail = {"target": state.run_target, "stages": dict(state.stages), "changed": list(state.changed),
                  "cost": state.cost, "addon": VERSION}
        lines = session_log.lines_for(run.turn, run.request or state.prompt, state.reply or state.error, status,
                                      detail, retry=run.retry)
        lines = code_check.redact(lines, run.secrets)
        _show(build.run_id, session_log.entries(lines))  # the bar's history has it, stored or not
        if not _on() or getattr(run, "on_eachsense", False):  # each::sense stored the build it ran itself
            return
        client, scope, secrets = run.client, build.run_id, run.secrets
    except Exception as exc:  # a run's end must not depend on its history
        _failed(exc, "record")
        return

    def work():
        with _lock:
            try:
                build.session_id = session_log.write(client, scope, lines, getattr(build, "session_id", None))
            except Exception as exc:
                _failed(exc, "write", secrets)

    threading.Thread(target=work, name="eachlabs-session-write", daemon=True).start()


def restore(run_ids, context=None):
    """Main thread, after a file opened: read the stored prompts of the scene chats it holds, so the first
    follow-up knows the earlier requests and the bar's history has them. Never raises."""
    restored = chat_run._sessions["restored"]
    restored.clear()
    chat_run._sessions["lines"].clear()
    try:
        scopes = sorted(run_ids)[:RESTORE_MAX]
        if not scopes or not _on(context):
            return
        client = preferences.client(context)
        if not client.api_key:
            return
        limit = chat_run.MAX_HISTORY
    except Exception as exc:
        _failed(exc, "restore")
        return

    def work():
        for scope in scopes:
            with _lock:
                try:
                    session_id, messages = session_log.read_all(client, scope)
                except Exception as exc:
                    _failed(exc, "read", (client.api_key,))
                    return
            if session_id:
                prompts = session_log.prompts_from(messages, limit)
                restored[scope] = (session_id, prompts)
                shown = session_log.entries(messages)
                main_thread.call_soon(lambda scope=scope, prompts=prompts, shown=shown: _remember(scope, prompts, shown))

    threading.Thread(target=work, name="eachlabs-session-read", daemon=True).start()


def _remember(scope, prompts, shown):
    """Main thread: the stored prompts join the bar's history, after the ones typed in this session, and the
    stored lines become the scene chat's history view, before anything this session already added."""
    state = chat_run.STATE
    state.history = (state.history + [p for p in prompts if p not in state.history])[:chat_run.MAX_HISTORY]
    lines = chat_run._sessions["lines"]
    lines[scope] = (list(shown) + lines.get(scope, []))[-SHOWN_MAX:]


def _show(scope, shown):
    """Main thread: add what a run just showed to its scene chat's history view."""
    lines = chat_run._sessions["lines"]
    lines[scope] = (lines.get(scope, []) + list(shown))[-SHOWN_MAX:]


def transcript(scene=None):
    """The history view's entries for the scene chat the next prompt continues: the current build's, or after a
    file was opened the stored chat of a collection in ``scene``. Empty when there is none."""
    lines = chat_run._sessions["lines"]
    if not lines:
        return []
    build = chat_run._build
    if build is not None:
        return lines.get(build.run_id, [])
    try:
        tags = {c.get(scene_build.RUN) for c in scene.collection.children_recursive}
    except Exception:  # no scene in this context
        return []
    return next((shown for scope, shown in lines.items() if scope in tags), [])


def resume(build):
    """Main thread, when a prompt continues a scene chat from an opened file: give the build its stored session
    and prompts. Does nothing for a build that already has prompts."""
    stored = chat_run._sessions["restored"].pop(build.run_id, None)
    if stored is None or build.prompts:
        return
    build.session_id, build.prompts[:] = stored[0], list(stored[1])
