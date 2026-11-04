"""Late access to ``overlay``'s module state (the prompt field, the bar's UI state, placed frames).

The modules of this package read that state as ``overlay.<name>`` when they run, never when they load, so they
can be imported in any order and ``overlay`` can import them in turn.
"""


class _Overlay:
    def __getattr__(self, name):
        from .. import overlay

        return getattr(overlay, name)


overlay = _Overlay()
