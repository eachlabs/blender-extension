"""Late access to ``preferences`` (the add-on's saved settings), so readers always use its current helpers.

The modules of this package call ``preferences.<name>`` when they run, never when they load.
"""


class _Preferences:
    def __getattr__(self, name):
        from .. import preferences

        return getattr(preferences, name)


preferences = _Preferences()
