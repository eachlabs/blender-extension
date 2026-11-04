import unittest

from eachlabs import settings_guard

NAMES = ("api_key", "base_url", "chat_code_check", "spare_key")


class Prefs:
    def __init__(self, fail_first_restore=False):
        object.__setattr__(self, "_fail", False)
        object.__setattr__(self, "writes", [])
        self.api_key = "key-one"
        self.base_url = "https://example.test"
        self.chat_code_check = True
        self.spare_key = "key-two"
        self.writes.clear()
        self._fail = fail_first_restore

    def __setattr__(self, name, value):
        if not name.startswith("_") and name != "writes":
            self.writes.append((name, value))
            if self._fail and name == "api_key" and value == "key-one":
                self._fail = False
                raise RuntimeError("cannot write")
        object.__setattr__(self, name, value)


def values(prefs):
    return {name: getattr(prefs, name) for name in NAMES}


class RunHiddenTests(unittest.TestCase):
    def setUp(self):
        self.prefs = Prefs()
        self.before = values(self.prefs)

    def run_step(self, step, prefs=None):
        return settings_guard.run_hidden(prefs or self.prefs, NAMES, ["key-one", "key-two"], step)

    def test_secrets_are_empty_during_the_step_and_back_after(self):
        seen = {}

        def step():
            seen.update(values(self.prefs))
            return "result"
        self.assertEqual(self.run_step(step), ("result", False))
        self.assertEqual(seen, dict(self.before, api_key="", spare_key=""))
        self.assertEqual(values(self.prefs), self.before)

    def test_secrets_come_back_when_the_step_raises(self):
        def step():
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.run_step(step)
        self.assertEqual(values(self.prefs), self.before)

    def test_a_changed_setting_is_put_back_and_reported(self):
        def step():
            self.prefs.base_url = "https://other.test"
            self.prefs.chat_code_check = False
        self.assertEqual(self.run_step(step), (None, True))
        self.assertEqual(values(self.prefs), self.before)

    def test_a_key_written_by_the_step_is_reported(self):
        def step():
            self.prefs.api_key = "chosen-by-the-step"
        self.assertEqual(self.run_step(step), (None, True))
        self.assertEqual(values(self.prefs), self.before)

    def test_a_failed_restore_still_puts_the_other_secrets_back(self):
        prefs = Prefs(fail_first_restore=True)
        _result, changed = self.run_step(lambda: None, prefs)
        self.assertTrue(changed)  # the first write failed; the comparison put it back
        self.assertEqual(values(prefs), self.before)
        restores = [w for w in prefs.writes if w[1] in ("key-one", "key-two")]
        self.assertEqual(restores, [("api_key", "key-one"), ("spare_key", "key-two"), ("api_key", "key-one")])

    def test_settings_without_a_secret_are_not_emptied(self):
        prefs = Prefs()
        prefs.api_key = ""
        seen = {}
        settings_guard.run_hidden(prefs, NAMES, ["key-two"], lambda: seen.update(values(prefs)))
        self.assertEqual((seen["api_key"], seen["base_url"], seen["spare_key"]), ("", "https://example.test", ""))


if __name__ == "__main__":
    unittest.main()
