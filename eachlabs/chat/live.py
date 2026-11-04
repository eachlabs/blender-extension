"""Late access to ``chat_run``'s module state (the current run, the scene build, the bar's state).

The modules of this package read that state as ``chat_run.<name>`` when they run, never when they load, so the
package can be imported in any order and ``chat_run`` can import them in turn.
"""


class _ChatRun:
    def __getattr__(self, name):
        from .. import chat_run

        return getattr(chat_run, name)


chat_run = _ChatRun()
