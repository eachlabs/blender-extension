import unittest

from eachlabs import undo_steps

# As printed by WindowManager.print_undo_steps() in Blender 4.2.23 and 5.2.3.
PRINTED = """Undo 3 Steps (*: active, #=applied, M=memfile-active, S=skip)
[    ]   0 {0x756603a408} type='Global Undo', name='Original'
[* M ]   1 {0x75656afc88} type='Global Undo', name='Eachlabs: light'
[    ]   2 {0x75656afd00} type='Global Undo', name='Select'
"""


class ParseTest(unittest.TestCase):
    def test_active_step_is_the_starred_one(self):
        self.assertEqual(undo_steps.parse(PRINTED), "Eachlabs: light")

    def test_last_step_active(self):
        text = PRINTED.replace("[* M ]", "[    ]").replace("[    ]   2", "[* M ]   2")
        self.assertEqual(undo_steps.parse(text), "Select")

    def test_unreadable_output_is_unknown(self):
        for text in (None, "", "Undo 0 Steps\n", "garbage [*] name='x"):
            self.assertIsNone(undo_steps.parse(text), repr(text))


if __name__ == "__main__":
    unittest.main()
