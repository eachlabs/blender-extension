"""Keeps the add-on's settings out of reach of one step of the chat's code. Pure, no ``bpy``.

``code_runner`` passes the add-on preferences; any object with attributes works, so this is unit tested
without Blender.
"""


def run_hidden(prefs, names, secrets, step):
    """Call ``step()`` with every setting in ``names`` whose value is one of ``secrets`` set to ``""``.

    Afterwards, also when ``step`` raises, each secret is put back on its own, then every setting is compared
    with its value from before and put back when it differs. Returns ``(step's result, changed)``; ``changed``
    is True when the step left a setting different, a secret included. The values from before are kept in
    this function's locals only."""
    saved = {name: getattr(prefs, name) for name in names}
    hidden = [name for name, value in saved.items()
              if isinstance(value, str) and value.strip() and value.strip() in secrets]
    try:
        for name in hidden:
            setattr(prefs, name, "")
        result = step()
    finally:
        changed = _restore(prefs, saved, hidden)
    return result, changed


def _restore(prefs, saved, hidden):
    changed = False
    for name in hidden:
        try:
            changed = changed or getattr(prefs, name) != ""
        except Exception:  # noqa: BLE001 - unreadable counts as changed
            changed = True
        try:
            setattr(prefs, name, saved[name])
        except Exception:  # noqa: BLE001 - the other secrets are still put back; the comparison retries it
            pass
    for name, value in saved.items():
        try:
            if getattr(prefs, name) == value:
                continue
        except Exception:  # noqa: BLE001 - unreadable: write it back
            pass
        changed = True
        try:
            setattr(prefs, name, value)
        except Exception:  # noqa: BLE001 - one setting that cannot be written must not keep the others
            pass
    return changed
