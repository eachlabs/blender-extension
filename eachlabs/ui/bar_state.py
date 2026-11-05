"""What the prompt bar shows for a chat run, and where it sits in the 3D view. No Blender code."""

import os

from . import tokens as T
from .bar import BUDGET_ACTIONS, CONSENT_ACTIONS, PLAN_ACTIONS, BarState

MAX_WIDTH = 640
MIN_WIDTH = 240
SIDE_GAP = 32  # logical px the bar leaves free across the region
BOTTOM_GAP = 36  # logical px between the bar and the region bottom

KEY_ERRORS = ("Add your Eachlabs API key to start.", "API key was rejected (HTTP 401).")
CANCELLED = "Stopped. What was built is kept."
_HIT_ORDER = T.CAMERA_HITS + ("play_menu", "play", "frame", "final", "undo", "code", "new", "retry", "keep", "prefs", "network", "halt") + CONSENT_ACTIONS + (
    T.PLAN_HITS + PLAN_ACTIONS + ("plan_limit", "plan_raise", "missing", "widen", "asked") + T.QUALITY_HITS
    + (T.TAB_CLEAR,) + T.TAB_HITS + ("settings", "quality", "send", "stop", "field", "bar"))


OBJECT_LINES = 3  # job lines while a run goes; more are one "+N more" line


def _clock(seconds):
    seconds = int(max(0, seconds))
    return "%d:%02d" % divmod(seconds, 60)


def object_lines(rows):
    """The 3D jobs of the running run, one at a time: ``Generating the car… 1:20 · then: garage, house``, then a
    line per object that failed."""
    textures = [r for r in rows if r.get("kind") == "texture"]
    rows = [r for r in rows if r.get("kind") != "texture"]
    queued = [r.get("name") or "object" for r in sorted(
        (r for r in rows if r.get("state") == "queued"), key=lambda r: tuple(r.get("priority") or (0, 0)))]
    then = " · then: " + ", ".join(queued) if queued else ""
    lines = []
    busy = False
    for row in rows:
        state, name = row.get("state"), row.get("name") or "object"
        if state in ("starting", "running", "downloading", "ready"):
            text = ("Bringing in the %s from the cache…" % name if row.get("cached")
                    else "Generating the %s… %s" % (name, _clock(row.get("seconds") or 0)))
            if not busy and not row.get("cached"):
                text, busy = text + then, True
        elif state == "failed":
            text = "The %s stays built in code: its 3D model was not made." % name
        else:
            continue
        lines.append(text)
    if queued and not busy:
        lines.insert(0, "Waiting to generate: " + ", ".join(queued))
    for row in textures:  # textures run beside the 3D objects, one at a time
        state, name = row.get("state"), row.get("name") or "material"
        if state in ("starting", "running", "downloading", "ready") and not row.get("cached"):
            lines.append("Drawing the %s texture… %s" % (name, _clock(row.get("seconds") or 0)))
        elif state == "failed":
            lines.append("The %s texture was not made; it keeps its own colour." % name)
    if len(lines) > OBJECT_LINES:
        lines = lines[:OBJECT_LINES - 1] + ["+%d more 3D objects" % (len(lines) - OBJECT_LINES + 1)]
    return lines


def free_note(names, shown=4):
    """The done card's line for the free Poly Haven skies and textures a run used."""
    names = list(names)
    listed = ", ".join(names[:shown]) + (" +%d more" % (len(names) - shown) if len(names) > shown else "")
    return "Free: %s (Poly Haven, CC0)" % listed


def objects_note(rows):
    """After the run: what each 3D object and texture cost, or that it came from the cache or was built in code."""
    objects = [r for r in rows if r.get("kind") != "texture"]
    textures = [r for r in rows if r.get("kind") == "texture"]
    lines = [_note_parts(objects, "3D: "), _note_parts(textures, "Textures: ")]
    return " · ".join(line for line in lines if line)


def _note_parts(rows, head):
    parts = []
    for row in rows:
        name, state = row.get("name") or "object", row.get("state")
        if state == "failed" and row.get("kind") == "texture":
            parts.append("%s not made" % name)
        elif state == "done" and row.get("cached"):
            parts.append("%s cached, free" % name)
        elif state == "done":
            cost = row.get("cost")
            parts.append("%s $%.2f" % (name, cost) if isinstance(cost, (int, float)) else name)
        elif state == "failed":
            parts.append("%s built in code" % name)
        elif state == "cancelled":
            parts.append("%s stopped" % name)
    return head + " · ".join(parts) if parts else ""


def plan_fields(plan):
    """The bar's plan fields from a ``plan3d.Plan``: the 3D line, the code line, the chips and the note."""
    if getattr(plan, "looks_only", False):  # only the looks line asks for Build
        return "", "", [], plan.note or T.LOOKS_HINT
    chips = []
    for i, item in enumerate(plan.items):
        if not item.solid:  # an object with parts is always built in code: the code line names it, no chip
            continue
        label = item.name[:1].upper() + item.name[1:]
        chips.append((i, label, item.mode, item.cached))
    return plan.summary_3d(), plan.summary_code(), chips, plan.note


def _error_text(error):
    return KEY_ERRORS[1] if "(HTTP 401)" in error else error


def _status(chat):
    if chat.tools:
        last = chat.tools[-1]
        text = last.get("summary") or last.get("name") or ""
        text = text[:1].upper() + text[1:]
        return text + "…" if last.get("state") == "running" else text
    return chat.reply


def _reason(text):
    return (text or "").strip().rstrip(".") or "it was not safe to run"


def consent_shown(asked, allowed):
    """The consent card shows while a send asked for it and the person has not agreed yet."""
    return bool(asked) and not allowed


def consent_after_send(asked, started):
    """The card's flag after a send: a run that started closes it; a refused send keeps what the send set."""
    return False if started else bool(asked)


def quality_name(mode):
    """The pill's text for a quality mode; an unknown mode reads as the first, Prototype."""
    return next((name for slug, name, _hint in T.QUALITIES if slug == mode), T.QUALITIES[0][1])


def final_line(chat):
    """The done card's line about the Final render, starting with a line break, or ``""``."""
    from ..chat import final_settings

    state = getattr(chat, "final_render", "")
    if state == "rendering":
        return "\n" + T.FINAL_RENDERING
    if state == "saved":
        return "\n" + T.FINAL_SAVED % (final_settings.seconds_text(chat.final_seconds),
                                        os.path.basename(chat.final_path))
    if state == "cancelled":
        return "\n" + T.FINAL_STOPPED
    if state == "failed":
        return "\n" + T.FINAL_FAILED % (chat.final_error or "unknown error")
    return ""


def quality_menu(mode):
    """The menu's items, ``(name, hint, chosen)`` in ``T.QUALITIES`` order; an unknown mode marks the first."""
    mode = mode if any(slug == mode for slug, _n, _h in T.QUALITIES) else T.QUALITIES[0][0]
    return [(name, hint, slug == mode) for slug, name, hint in T.QUALITIES]


def picked(hit_id):
    """The quality mode a menu item's hit id chooses, or ``None`` for any other hit."""
    return T.QUALITIES[T.QUALITY_HITS.index(hit_id)][0] if hit_id in T.QUALITY_HITS else None


def camera_picked(hit_id, menu):
    """The camera name a camera menu item's hit id chooses from ``menu`` (``BarState.camera_menu``), else ``None``."""
    if hit_id not in T.CAMERA_HITS:
        return None
    index = T.CAMERA_HITS.index(hit_id)
    return menu[index][0] if index < len(menu) else None


def from_chat(chat, field, focused, now, caret_on=True, spinner_phase=0.0, key_changed=False, has_scene=False,
              undoable=None, consent=False, quality="", menu=False, asked_open=False, advanced=True, tab="",
              cameras=(), camera_menu=False, playing=False, thing=""):
    """See ``_from_chat``; ``thing``: the selected thing (``thing_label``), changed by a prompt on Assets or
    Characters; ``quality``: the quality mode, shown on the pill (none for ``""``); ``menu``: its menu is open. Both are off while a run is going: the pill is dimmed. ``advanced``: Show code, Final render and New scene are shown (Preferences, "Show advanced tools"); ``tab``: the chosen tab, none for ``""``. ``cameras``: the scene's cameras as ``(name, hint, chosen)`` (``play_cameras.menu``); ``camera_menu``: their menu is open; ``playing``: the animation plays."""
    s = _from_chat(chat, field, focused, now, caret_on, spinner_phase, key_changed, has_scene, undoable, consent)
    if not advanced:
        s.actions = _without_advanced(s.actions)
    rows = getattr(chat, "objects", None) or []
    if chat.running and s.mode in ("building", "waiting"):
        s.objects = object_lines(rows)
        if getattr(chat, "concept", "") == "drawing":
            s.objects = [T.CONCEPT_DRAWING] + s.objects
        if getattr(chat, "looking", False):
            s.objects = [T.LOOKING] + s.objects
        if getattr(chat, "objects_wait", False) and s.mode == "building":
            s.status = T.OBJECTS_WAIT_TEXT
    elif not chat.running and s.mode in ("done", "stopped") and rows:
        s.note = objects_note(rows)
    free = getattr(chat, "free_assets", ())
    if not chat.running and s.mode in ("done", "stopped") and free:
        s.note = " · ".join(t for t in (s.note, free_note(free)) if t)
    if not chat.running and getattr(chat, "billed", False) and s.mode in ("done", "stopped") and (
            s.error != T.STOPPED_BILLED):  # the wait limit, or a run that stopped on its own
        s.note = " · ".join(t for t in (T.STOPPED_BILLED, s.note) if t)
    if s.mode in ("building", "waiting", "done", "stopped", "error"):
        s.asked = getattr(chat, "attempt", "") or ""  # what was sent; the field is empty for the next request
        s.asked_open = bool(asked_open)
    s.quality_label = quality_name(quality) if quality else ""
    s.tab, s.tabs_enabled = tab, not chat.running
    s.thing = thing if tab in ("asset", "character") else ""
    s.settings = True
    s.quality_enabled = not chat.running
    if menu and s.quality_label and not chat.running and s.mode != "consent":
        s.quality_menu = quality_menu(quality)
    _play(s, cameras, camera_menu and not s.quality_menu, playing)
    return s


def thing_label(names):
    """The selected things as the tab line names them: ``Barrel``, or ``Barrel and 2 more``; ``""`` for none."""
    names = [n for n in names if n]
    if not names:
        return ""
    return names[0] + (" and %d more" % (len(names) - 1) if len(names) > 1 else "")


def _play(s, cameras, menu_open, playing):
    """The Play button: Pause while the animation plays, else Play as the chosen camera with its menu."""
    if "play" not in s.actions:
        return
    s.playing = bool(playing)
    s.play_camera = next((name for name, _hint, chosen in cameras if chosen), "")
    if menu_open and s.play_camera and not s.playing:
        s.camera_menu = list(cameras)


def foldable(s):
    """True for a done card that may fold to one line: no choice waits on it. A run that changed nothing, an
    edit kept from some objects, planned things not built or an open menu keep the whole card."""
    return (s.mode == "done" and not s.error and not s.camera_menu and not s.quality_menu
            and not any(a in s.actions for a in ("widen", "missing")))


def folded(done_since, over_bar, now):
    """True once ``FOLD_AFTER`` seconds passed since the card first showed, while the mouse is off the bar. After
    that first wait the mouse opens and folds it at once. ``done_since``: when the card became foldable."""
    if done_since is None or over_bar:
        return False
    return now - done_since >= T.FOLD_AFTER


ADVANCED_ACTIONS = ("code", "final", "new")  # shown only with "Show advanced tools" on


def _without_advanced(actions):
    """``actions`` without the advanced ones; New scene stays when it is the card's only way on."""
    kept = [a for a in actions if a not in ADVANCED_ACTIONS]
    return kept or (["new"] if "new" in actions else [])


def _from_chat(chat, field, focused, now, caret_on=True, spinner_phase=0.0, key_changed=False, has_scene=False,
               undoable=None, consent=False):
    """``chat`` is a ``chat_run.ChatState``; ``key_changed``: the API key differs from when a key error showed;
    ``has_scene``: the next prompt changes the current scene; ``undoable``: the stages *Undo stage* may
    undo (``chat_run.undoable_stages()``), else the finished stages in ``chat.changed``; ``consent``: the
    consent card is open. Every state that is not running offers a next step besides typing."""
    s = BarState(field=field, focused=focused, caret_on=caret_on, spinner_phase=spinner_phase,
                 stages=dict(chat.stages), round=chat.round, total=chat.total, has_scene=has_scene)
    error = _error_text(chat.error or "")
    if error == T.EMPTY_PROMPT:
        error = ""  # typing is the next step; the bar shows its usual state and the placeholder
    if chat.running:
        s.code_check = bool(getattr(chat, "code_check_on", False))
        check = getattr(chat, "code_check_state", "")
        plan = getattr(chat, "plan", None)
        if plan is not None and getattr(chat, "plan_waiting", False):  # nothing runs until Build
            needed = getattr(plan, "rounds_needed", 0)
            actions = BUDGET_ACTIONS if needed else PLAN_ACTIONS
            s.mode, s.stages, s.actions, s.send_enabled = "plan", {}, list(actions), False
            if needed:
                s.raise_label = "Use %d for this run" % needed
            s.plan_3d, s.plan_code, s.plan_chips, s.plan_note = plan_fields(plan)
            s.plan_looks = getattr(plan, "looks", "")
            return s
        if getattr(chat, "planning", False):
            s.mode, s.round, s.status = "building", max(1, chat.round), T.PLANNING_TEXT
            return s
        if check == "refused":  # stays while the model rewrites the step
            s.mode, s.round = "building", max(1, chat.round)
            s.error = T.REFUSED_TEXT % _reason(getattr(chat, "code_check_reason", ""))
            s.actions = ["code", "halt"]
        elif chat.thinking_since is not None:
            s.mode, s.thinking_seconds = "waiting", max(0.0, now - chat.thinking_since)
            s.round = min(chat.round + 1, chat.total) if chat.total else chat.round + 1
        else:
            s.mode, s.round = "building", max(1, chat.round)
            s.status = T.CHECKING_TEXT if check == "checking" else _status(chat)
        return s
    if consent:
        s.mode, s.actions, s.stages = "consent", list(CONSENT_ACTIONS), {}
        return s
    if undoable is None:
        undoable = [st for st in chat.changed if chat.stages.get(st) == "done"]
    undo = ["undo"] if undoable else []
    s.undo_stage = undoable[-1] if undoable else ""
    code = ["code"] if getattr(chat, "code_steps", None) else []
    retry = ["retry"] if chat.failed_stage or getattr(chat, "attempt", "") else []
    if error == T.ONLINE_OFF:
        retry = ["network"]  # Retry cannot help until online access is on
    elif error == T.OFFLINE_MODE:
        retry = []  # only a restart helps
    if error in KEY_ERRORS:
        if not key_changed:
            s.mode, s.error, s.actions, s.send_enabled, s.stages = "error", error, ["prefs"], False, {}
            return s
    elif chat.status == "stopped" and chat.failed_stage:
        s.mode, s.error = "stopped", error
        if error.startswith(T.CHECK_STOPPED):
            s.error = "%s %s" % (error, T.CHECK_OFF_TEXT) if error.endswith(".") else "%s. %s" % (
                error, T.CHECK_OFF_TEXT)
            s.actions = ["retry"] + code + ["new"]
        elif error == T.SETTINGS_CHANGED:  # running the same steps again would change them again
            s.actions = code + ["new"]
        else:
            s.actions = ["retry"] + undo + code + ["new"]
        return s
    elif error and chat.status != "cancelled":  # a start that was refused, or a run that broke off
        s.mode, s.error, s.stages = "error", error, {}
        s.actions = retry + code + (["new"] if has_scene else [])
        return s
    elif chat.status == "done" and getattr(chat, "unchanged", False):  # the bar says so, not only the reply
        s.mode, s.reply, s.cost_text, s.error = "done", chat.reply, chat.cost_text, T.NOTHING_CHANGED
        s.actions = ["retry"] + undo + code + ["new"]
        return s
    elif chat.status == "found":  # a find or a list: nothing was built
        s.mode, s.reply, s.cost_text, s.stages = "done", chat.reply, chat.cost_text, {}
        s.actions = ["frame", "new"]
        return s
    elif chat.status == "done":
        s.mode, s.reply, s.cost_text = "done", chat.reply, chat.cost_text
        partly = ["retry"] if chat.failed_stage else []  # a stage was left partly done
        missing = ["missing"] if getattr(chat, "missing", None) else []  # planned things the run did not build
        if missing:
            s.missing_label = "Build the missing things (about %d rounds)" % (
                4 + 2 * len(chat.missing))
        blocked = list(getattr(chat, "blocked", None) or [])  # objects an edit was kept from changing
        widen = ["widen"] if blocked else []
        if blocked:
            verb = "Also remove" if getattr(chat, "removal", False) else "Also let it change"
            s.widen_label = "%s %s%s" % (verb, blocked[0], " and %d more" % (len(blocked) - 1)
                                         if len(blocked) > 1 else "")
        rendering = getattr(chat, "final_render", "") == "rendering"
        final = [] if rendering else ["final"]  # one Final render at a time; Esc in its window stops it
        s.reply = s.reply + final_line(chat) if s.reply else final_line(chat).lstrip("\n")
        s.actions = ["play", "frame"] + final + widen + missing + partly + undo + code + ["new"]
        return s
    elif chat.status == "cancelled":
        stopped = T.STOPPED_BILLED if getattr(chat, "billed", False) else CANCELLED
        s.mode, s.error, s.actions = "stopped", stopped, undo + code + ["new", "keep"]
        return s
    s.mode, s.stages = ("typing" if focused else "idle"), {}
    return s


def bar_width(region_logical):
    return max(MIN_WIDTH, min(MAX_WIDTH, int(region_logical) - SIDE_GAP))


def image_origin(frame_size, bar_rect, region_w, scale, left=0, right=0, bottom=0):
    """Bottom-left of the bar image in region px (y up): the bar centred in the width the overlapping
    toolbar (``left`` px) and sidebar (``right`` px) leave free, BOTTOM_GAP above the bottom or above
    an overlapping asset shelf (``bottom`` px)."""
    frame_w, frame_h = frame_size
    bx, by, bw, bh = bar_rect
    x = left + (region_w - left - right - bw) // 2 - bx
    y = bottom + round(BOTTOM_GAP * scale) - (frame_h - (by + bh))
    return x, y


def to_image(mx, my, origin, frame_h):
    """A region point (px, y up) as an image point (px, y down from the image top)."""
    return mx - origin[0], frame_h - (my - origin[1])


def hit(hits, x, y):
    """The control under an image point, most specific first; ``None`` outside the bar."""
    for name in _HIT_ORDER:
        rect = hits.get(name)
        if rect and rect[0] <= x < rect[0] + rect[2] and rect[1] <= y < rect[1] + rect[3]:
            return name
    return None
