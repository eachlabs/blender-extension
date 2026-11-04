import unittest

from eachlabs.ui.text_field import TextField


def field(history=None, mac=False):
    return TextField(history or [], mac=mac)


def type_text(f, s):
    for c in s:
        f.handle("", char=c)


class TypingTest(unittest.TestCase):
    def test_type_caret_and_delete(self):
        f = field()
        type_text(f, "abc")
        self.assertEqual((f.text, f.caret), ("abc", 3))
        f.handle("LEFT_ARROW")
        f.handle("BACK_SPACE")
        self.assertEqual((f.text, f.caret), ("ac", 1))
        f.handle("DEL")
        self.assertEqual((f.text, f.caret), ("a", 1))
        f.handle("HOME")
        self.assertEqual(f.caret, 0)
        f.handle("END")
        self.assertEqual(f.caret, 1)

    def test_backspace_at_start_and_delete_at_end_do_nothing(self):
        f = field()
        type_text(f, "a")
        f.handle("DEL")
        f.handle("HOME")
        f.handle("BACK_SPACE")
        self.assertEqual(f.text, "a")

    def test_tab_is_ignored(self):
        f = field()
        type_text(f, "a")
        self.assertIsNone(f.handle("TAB", char="\t"))
        self.assertEqual(f.text, "a")

    def test_control_characters_are_not_inserted(self):
        f = field()
        f.handle("", char="\x01")
        self.assertEqual(f.text, "")


class WordJumpTest(unittest.TestCase):
    def test_non_mac_uses_ctrl(self):
        f = field()
        type_text(f, "a street at dusk")
        f.handle("LEFT_ARROW", ctrl=True)
        self.assertEqual(f.caret, 12)
        f.handle("LEFT_ARROW", ctrl=True)
        self.assertEqual(f.caret, 9)
        f.handle("HOME")
        f.handle("RIGHT_ARROW", ctrl=True)
        self.assertEqual(f.caret, 1)
        f.handle("RIGHT_ARROW", ctrl=True)
        self.assertEqual(f.caret, 8)

    def test_mac_uses_alt_and_ctrl_does_nothing(self):
        f = field(mac=True)
        type_text(f, "a street at dusk")
        f.handle("LEFT_ARROW", ctrl=True)
        self.assertEqual(f.caret, 15)
        f.handle("LEFT_ARROW", alt=True)
        self.assertEqual(f.caret, 12)

    def test_mac_cmd_arrows_go_to_line_ends(self):
        f = field(mac=True)
        type_text(f, "one")
        f.handle("LEFT_ARROW", cmd=True)
        self.assertEqual(f.caret, 0)
        f.handle("RIGHT_ARROW", cmd=True)
        self.assertEqual(f.caret, 3)

    def test_word_backspace(self):
        f = field()
        type_text(f, "a street")
        f.handle("BACK_SPACE", ctrl=True)
        self.assertEqual(f.text, "a ")


class SelectionTest(unittest.TestCase):
    def test_select_all_then_type_replaces(self):
        f = field()
        type_text(f, "old")
        f.handle("A", ctrl=True)
        self.assertEqual((f.anchor, f.caret), (0, 3))
        f.handle("", char="x")
        self.assertEqual((f.text, f.caret, f.anchor), ("x", 1, None))

    def test_shift_arrows_extend_then_typing_replaces(self):
        f = field()
        type_text(f, "hello")
        f.handle("LEFT_ARROW", shift=True)
        f.handle("LEFT_ARROW", shift=True)
        self.assertEqual((f.anchor, f.caret), (5, 3))
        f.handle("", char="y")
        self.assertEqual(f.text, "hely")

    def test_arrow_collapses_selection_to_its_edge(self):
        f = field()
        type_text(f, "hello")
        f.handle("A", ctrl=True)
        f.handle("LEFT_ARROW")
        self.assertEqual((f.caret, f.anchor), (0, None))

    def test_backspace_removes_selection(self):
        f = field()
        type_text(f, "hello")
        f.handle("LEFT_ARROW", shift=True, ctrl=True)
        f.handle("BACK_SPACE")
        self.assertEqual(f.text, "")

    def test_shift_back_to_anchor_clears_selection(self):
        f = field()
        type_text(f, "ab")
        f.handle("LEFT_ARROW", shift=True)
        f.handle("RIGHT_ARROW", shift=True)
        self.assertIsNone(f.anchor)


class ClipboardTest(unittest.TestCase):
    def test_copy_keeps_selection(self):
        f = field()
        type_text(f, "hello")
        f.handle("A", ctrl=True)
        self.assertEqual(f.handle("C", ctrl=True), "copy")
        self.assertEqual(f.copy(), "hello")
        self.assertEqual(f.text, "hello")
        self.assertEqual(f.copy(), "hello")

    def test_cut_returns_then_deletes(self):
        f = field()
        type_text(f, "hello")
        f.handle("LEFT_ARROW", shift=True)
        self.assertEqual(f.handle("X", ctrl=True), "cut")
        self.assertEqual(f.text, "hello")
        self.assertEqual(f.cut(), "o")
        self.assertEqual(f.text, "hell")

    def test_copy_and_cut_without_selection_do_nothing(self):
        f = field()
        type_text(f, "hi")
        self.assertIsNone(f.handle("C", ctrl=True))
        self.assertIsNone(f.handle("X", ctrl=True))
        self.assertEqual(f.copy(), "")

    def test_paste_shortcut_and_replace(self):
        f = field()
        type_text(f, "abc")
        f.handle("A", ctrl=True)
        self.assertEqual(f.handle("V", ctrl=True), "paste")
        f.paste("xyz")
        self.assertEqual((f.text, f.caret), ("xyz", 3))

    def test_paste_normalises_line_endings(self):
        f = field()
        f.paste("a\r\nb\rc")
        self.assertEqual(f.text, "a\nb\nc")
        self.assertEqual(f.caret, 5)

    def test_unicode_paste_and_caret_by_character(self):
        f = field()
        s = "улица 🌆 夕方"
        f.paste(s)
        self.assertEqual(f.text, s)
        self.assertEqual(f.caret, len(s))
        f.handle("BACK_SPACE")
        self.assertEqual(f.text, "улица 🌆 夕")
        f.handle("LEFT_ARROW")
        self.assertEqual(f.caret, len(s) - 2)


class PlatformTest(unittest.TestCase):
    def test_non_mac_ignores_cmd(self):
        f = field(mac=False)
        type_text(f, "abc")
        self.assertIsNone(f.handle("A", cmd=True))
        self.assertIsNone(f.anchor)

    def test_mac_uses_cmd_not_ctrl(self):
        f = field(mac=True)
        type_text(f, "abc")
        self.assertIsNone(f.handle("A", ctrl=True))
        self.assertIsNone(f.anchor)
        f.handle("A", cmd=True)
        self.assertEqual(f.anchor, 0)
        self.assertEqual(f.handle("V", cmd=True), "paste")

    def test_cmd_letter_does_not_type(self):
        f = field(mac=True)
        f.handle("A", cmd=True, char="a")
        self.assertEqual(f.text, "")


class SubmitTest(unittest.TestCase):
    def test_enter_submits_and_shift_enter_adds_line(self):
        f = field()
        type_text(f, "ab")
        f.handle("RET", shift=True)
        type_text(f, "cd")
        self.assertEqual(f.text, "ab\ncd")
        self.assertEqual(f.handle("RET"), "submit")
        self.assertEqual(f.handle("NUMPAD_ENTER"), "submit")
        self.assertEqual(f.text, "ab\ncd")

    def test_escape_blurs(self):
        self.assertEqual(field().handle("ESC"), "blur")

    def test_clear_resets_everything(self):
        f = field()
        type_text(f, "abc")
        f.handle("A", ctrl=True)
        f.clear()
        self.assertEqual((f.text, f.caret, f.anchor), ("", 0, None))
        f.handle("Z", ctrl=True)
        self.assertEqual(f.text, "")


class HistoryTest(unittest.TestCase):
    def test_up_down_restores_draft(self):
        f = field(["newest", "older"])
        type_text(f, "draft")
        f.handle("UP_ARROW")
        self.assertEqual((f.text, f.caret), ("newest", 6))
        f.handle("UP_ARROW")
        self.assertEqual(f.text, "older")
        f.handle("UP_ARROW")
        self.assertEqual(f.text, "older")
        f.handle("DOWN_ARROW")
        self.assertEqual(f.text, "newest")
        f.handle("DOWN_ARROW")
        self.assertEqual(f.text, "draft")
        f.handle("DOWN_ARROW")
        self.assertEqual(f.text, "draft")

    def test_up_moves_between_lines_before_history(self):
        f = field(["old"])
        type_text(f, "ab")
        f.handle("RET", shift=True)
        type_text(f, "cde")
        f.handle("UP_ARROW")
        self.assertEqual(f.text, "ab\ncde")
        self.assertEqual(f.caret, 2)
        f.handle("DOWN_ARROW")
        self.assertEqual(f.caret, 5)
        f.handle("UP_ARROW")
        f.handle("UP_ARROW")
        self.assertEqual(f.text, "old")
        f.handle("DOWN_ARROW")
        self.assertEqual(f.text, "ab\ncde")

    def test_does_not_mutate_callers_list(self):
        h = ["a"]
        f = field(h)
        f.handle("UP_ARROW")
        f.set_history(["x", "y"])
        self.assertEqual(h, ["a"])
        f.handle("UP_ARROW")
        self.assertEqual(f.text, "x")

    def test_up_without_history_goes_to_start(self):
        f = field()
        type_text(f, "abc")
        f.handle("UP_ARROW")
        self.assertEqual(f.caret, 0)


class UndoTest(unittest.TestCase):
    def test_typing_coalesces_words(self):
        f = field()
        type_text(f, "hello world")
        f.handle("Z", ctrl=True)
        self.assertEqual(f.text, "hello ")
        f.handle("Z", ctrl=True)
        self.assertEqual(f.text, "hello")
        f.handle("Z", ctrl=True)
        self.assertEqual(f.text, "")

    def test_redo(self):
        f = field()
        type_text(f, "abc")
        f.handle("Z", ctrl=True)
        self.assertEqual(f.text, "")
        f.handle("Z", ctrl=True, shift=True)
        self.assertEqual((f.text, f.caret), ("abc", 3))
        f.handle("Z", ctrl=True)
        f.handle("Y", ctrl=True)
        self.assertEqual(f.text, "abc")

    def test_mac_redo(self):
        f = field(mac=True)
        type_text(f, "abc")
        f.handle("Z", cmd=True)
        f.handle("Z", cmd=True, shift=True)
        self.assertEqual(f.text, "abc")

    def test_new_edit_drops_redo(self):
        f = field()
        type_text(f, "abc")
        f.handle("Z", ctrl=True)
        type_text(f, "x")
        f.handle("Z", ctrl=True, shift=True)
        self.assertEqual(f.text, "x")

    def test_undo_restores_selection_replace(self):
        f = field()
        type_text(f, "abc")
        f.handle("A", ctrl=True)
        f.handle("", char="x")
        f.handle("Z", ctrl=True)
        self.assertEqual(f.text, "abc")

    def test_stack_is_capped_at_fifty(self):
        f = field()
        for _ in range(80):
            f.handle("", char="a")
            f.handle("", char=" ")
        for _ in range(100):
            f.handle("Z", ctrl=True)
        self.assertEqual(len(f.text), 160 - 50)


class AltGrTest(unittest.TestCase):
    def test_ctrl_alt_types_the_character_on_windows_and_linux(self):
        f = field()
        for key, char in (("A", "ą"), ("C", "ć"), ("X", "ź"), ("Z", "ż"), ("V", "v")):
            self.assertIsNone(f.handle(key, ctrl=True, alt=True, char=char))
        self.assertEqual(f.text, "ąćźżv")

    def test_ctrl_alone_is_still_a_command(self):
        f = field()
        type_text(f, "ab")
        self.assertIsNone(f.handle("A", ctrl=True, char="a"))
        self.assertEqual(f.selection(), (0, 2))
        self.assertEqual(f.handle("C", ctrl=True), "copy")

    def test_mac_cmd_alt_stays_a_command(self):
        f = field(mac=True)
        type_text(f, "ab")
        f.handle("A", cmd=True, alt=True)
        self.assertEqual(f.selection(), (0, 2))


class SetCaretTest(unittest.TestCase):
    def test_moves_and_clamps(self):
        f = field()
        type_text(f, "hello")
        f.set_caret(2)
        self.assertEqual((f.caret, f.selection()), (2, None))
        f.set_caret(99)
        self.assertEqual(f.caret, 5)
        f.set_caret(-3)
        self.assertEqual(f.caret, 0)

    def test_extend_selects_from_the_old_caret(self):
        f = field()
        type_text(f, "hello")
        f.set_caret(1)
        f.set_caret(4, extend=True)
        self.assertEqual(f.selection(), (1, 4))
        f.set_caret(2)
        self.assertIsNone(f.selection())

    def test_ends_undo_coalescing(self):
        f = field()
        type_text(f, "abc")
        f.set_caret(0)
        type_text(f, "xy")
        self.assertEqual(f.text, "xyabc")
        f.handle("Z", ctrl=True)
        self.assertEqual(f.text, "abc")


if __name__ == "__main__":
    unittest.main()


class LimitsTest(unittest.TestCase):
    def test_paste_is_cut_to_the_cap_without_error(self):
        from eachlabs.ui.text_field import MAX_CHARS

        f = TextField()
        f.paste("ab" * 2000)
        self.assertEqual(len(f.text), MAX_CHARS)
        f.handle("A", char="z")
        self.assertEqual(len(f.text), MAX_CHARS)
        f.handle("BACK_SPACE")
        f.paste("0123")
        self.assertEqual(len(f.text), MAX_CHARS)
        self.assertTrue(f.text.endswith("0"))

    def test_paste_over_a_selection_may_fill_its_room(self):
        from eachlabs.ui.text_field import MAX_CHARS

        f = TextField()
        f.paste("a" * MAX_CHARS)
        f.handle("A", cmd=True, ctrl=True)
        f.paste("b" * 10)
        self.assertEqual(f.text, "b" * 10)

    def test_control_characters_and_lone_surrogates_are_stripped(self):
        f = TextField()
        f.paste("a\x00b\x1bc\td\ud800e\r\nf‍g")
        self.assertEqual(f.text, "abc de\nf‍g")
        f.handle("A", char="\udc00")
        self.assertEqual(f.text, "abc de\nf‍g")


class MouseSelectionTest(unittest.TestCase):
    def test_drag_selects_from_the_click(self):
        f = field()
        type_text(f, "make the tower taller")
        f.set_caret(5)
        f.drag_to(14)
        self.assertEqual(f.copy(), "the tower")
        f.drag_to(0)  # dragging back past the click selects the other way
        self.assertEqual(f.copy(), "make ")

    def test_typing_replaces_a_dragged_selection(self):
        f = field()
        type_text(f, "a red roof")
        f.set_caret(2)
        f.drag_to(5)
        type_text(f, "blue")
        self.assertEqual(f.text, "a blue roof")

    def test_double_click_selects_the_word(self):
        f = field()
        type_text(f, "make the tower taller")
        f.select_word(10)
        self.assertEqual(f.copy(), "tower")
        f.select_word(14)  # just after the word
        self.assertEqual(f.copy(), "tower")
        f.select_word(len(f.text))
        self.assertEqual(f.copy(), "taller")

    def test_double_click_on_spaces_selects_the_spaces(self):
        f = field()
        type_text(f, "a   b")
        f.select_word(2)
        self.assertEqual(f.copy(), "   ")

    def test_double_click_stays_on_one_line(self):
        f = field()
        f.paste("one\ntwo")
        f.select_word(5)
        self.assertEqual(f.copy(), "two")

    def test_double_click_in_empty_field_selects_nothing(self):
        f = field()
        f.select_word(0)
        self.assertIsNone(f.selection())
