"""Ask before an action that removes, undoes or stops something: a dialog that says what happens and what stays,
with Cancel.

An operator asks only when it is invoked: a click in the prompt bar, the sidebar or Preferences. Run from a script
(``EXEC_DEFAULT``, the default for ``bpy.ops`` calls), it runs at once.
"""

asked = []  # (title, message) of each dialog opened, newest last; the GUI check reads it


def ask(operator, context, event, title, message, confirm_text):
    """Open the dialog for ``operator``; its ``execute`` runs only on the confirm button."""
    asked.append((title, message))
    del asked[:-20]
    return context.window_manager.invoke_confirm(operator, event, title=title, message=message,
                                                 confirm_text=confirm_text, icon="WARNING")
