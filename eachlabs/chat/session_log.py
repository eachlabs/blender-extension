"""A scene chat as an each::sense session: the lines one run stores and the prompts read back (no Blender).

The session's surface is ``blender`` and its scope the build's run id, the tag the chat's collections carry in the
``.blend``. each::sense only stores these lines and gives them back; the add-on still runs the chat itself."""

SURFACE = "blender"
LINE_CHARS = 20000  # the service's limit for one line
UNAVAILABLE = (400, 403, 404, 405)  # the API has no session lines, or does not store them for this organization


def _cut(text):
    text = str(text or "")
    return text if len(text) <= LINE_CHARS else text[:LINE_CHARS - 1] + "…"


def lines_for(turn, prompt, reply, status, detail=None, retry=False):
    """The lines one run adds: the person's prompt, then what the bar answered. A retry sends the same prompt
    again, so it adds only its answer. ``turn`` names the run; the line ids come from it, so sending the same
    lines twice stores them once."""
    lines = []
    if not retry and (prompt or "").strip():
        lines.append({"line_id": "%s-user" % turn, "role": "user", "kind": "user", "content": _cut(prompt)})
    kind = "assistant" if status in ("done", "found") else "error"
    answer = {"line_id": "%s-reply" % turn, "role": "assistant", "kind": kind, "content": _cut(reply or status)}
    extra = dict(detail or {}, status=status, retry=bool(retry))
    extra = {k: v for k, v in extra.items() if v is not False and v not in (None, "", [], {})}
    if extra:
        answer["detail"] = extra
    lines.append(answer)
    return lines


def prompts_from(messages, limit):
    """The person's prompts in a stored session, newest first, at most ``limit``."""
    prompts = [m.get("content", "") for m in messages or () if isinstance(m, dict) and m.get("role") == "user"]
    return [p for p in reversed(prompts) if p.strip()][:limit]


def entries(messages):
    """What the bar's history shows for stored messages or for lines just written, oldest first: one
    ``{"role", "text", "status", "cost"}`` per line that has text."""
    shown = []
    for m in messages or ():
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant"):
            continue
        text = str(m.get("content") or "").strip()
        if not text:
            continue
        detail = m.get("detail") if isinstance(m.get("detail"), dict) else {}
        cost = detail.get("cost")
        shown.append({"role": m["role"], "text": text, "status": str(detail.get("status") or ""),
                      "cost": float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else 0.0})
    return shown


def unavailable(exc):
    """True when the API says it stores no Blender chats here: asking again in this session is pointless."""
    return getattr(exc, "status", None) in UNAVAILABLE


def find(client, scope):
    """The id of the scene chat's stored session, or ``None`` when it has none yet."""
    sessions = client.list_sessions(SURFACE, scope, limit=1)
    return sessions[0].get("id") if sessions else None


def write(client, scope, lines, session_id=None):
    """Store ``lines`` on the scene chat's session and return its id. Without an id the session is looked up by
    its scope first, so a reopened file continues its session instead of starting a second one."""
    session_id = session_id or find(client, scope)
    return client.append_session_lines(SURFACE, scope, lines, session_id=session_id)


def read_all(client, scope):
    """``(session id, messages oldest first)`` of the scene chat's stored session; ``(None, [])`` when none."""
    session_id = find(client, scope)
    if not session_id:
        return None, []
    return session_id, client.get_session(session_id)


def read(client, scope, limit):
    """``(session id, prompts newest first)`` of the scene chat's stored session; ``(None, [])`` when none."""
    session_id, messages = read_all(client, scope)
    return session_id, prompts_from(messages, limit)
