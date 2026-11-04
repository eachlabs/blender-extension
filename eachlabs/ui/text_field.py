"""Editable prompt text, with no Blender or drawing code.

Clipboard contract: ``handle`` returns ``"copy"``, ``"cut"`` or ``"paste"`` and
leaves the text alone; the caller then reads ``copy()`` / ``cut()`` or passes
the clipboard text to ``paste()``. The selection is kept until that call.
"""

import sys
import unicodedata

UNDO_LIMIT = 50
MAX_CHARS = 2000  # a prompt longer than this is cut, not refused
_COMMAND_KEYS = {"A", "C", "X", "V", "Z", "Y", "HOME", "END"}


def clean(text):
    """``text`` without control characters (except ``\\n``) and lone surrogates; a tab becomes a space."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    if text.isprintable():
        return text
    return "".join(ch for ch in text if ch == "\n" or unicodedata.category(ch) not in ("Cc", "Cs"))


def _is_word(ch):
    return ch.isalnum() or ch == "_"


class TextField:
    def __init__(self, history=None, mac=None):
        self.mac = sys.platform == "darwin" if mac is None else mac
        self.text = ""
        self.caret = 0
        self.anchor = None
        self._history = list(history or [])
        self._hist_index = -1
        self._draft = ""
        self._undo = []
        self._redo = []
        self._coalescing = False

    # -- history -----------------------------------------------------------

    def set_history(self, history):
        self._history = list(history or [])
        self._hist_index = -1

    def clear(self):
        self.text = ""
        self.caret = 0
        self.anchor = None
        self._hist_index = -1
        self._draft = ""
        self._undo = []
        self._redo = []
        self._coalescing = False

    # -- selection and clipboard ---------------------------------------------

    def selection(self):
        if self.anchor is None or self.anchor == self.caret:
            return None
        return min(self.anchor, self.caret), max(self.anchor, self.caret)

    def copy(self):
        sel = self.selection()
        return self.text[sel[0]:sel[1]] if sel else ""

    def cut(self):
        s = self.copy()
        if s:
            self._replace(*self.selection(), "")
        return s

    def paste(self, text):
        """Insert clipboard text, cleaned and cut to what still fits in ``MAX_CHARS``."""
        self._insert(text or "", coalesce=False)

    # -- editing ---------------------------------------------------------------

    def _snapshot(self):
        return (self.text, self.caret, self.anchor)

    def _push_undo(self):
        self._undo.append(self._snapshot())
        del self._undo[:-UNDO_LIMIT]
        self._redo = []

    def _replace(self, start, end, s, coalesce=False):
        if not coalesce or not self._coalescing:
            self._push_undo()
        self._coalescing = coalesce
        self.text = self.text[:start] + s + self.text[end:]
        self.caret = start + len(s)
        self.anchor = None
        self._hist_index = -1

    def _insert(self, s, coalesce):
        sel = self.selection()
        if sel:
            coalesce = False
            start, end = sel
        else:
            start = end = self.caret
        s = clean(s)[:max(0, MAX_CHARS - len(self.text) + (end - start))]
        if s or sel:
            self._replace(start, end, s, coalesce)

    def _undo_step(self):
        if self._undo:
            self._redo.append(self._snapshot())
            self.text, self.caret, self.anchor = self._undo.pop()
        self._coalescing = False

    def _redo_step(self):
        if self._redo:
            self._undo.append(self._snapshot())
            self.text, self.caret, self.anchor = self._redo.pop()
        self._coalescing = False

    # -- movement helpers --------------------------------------------------------

    def _word_left(self, i):
        t = self.text
        while i > 0 and not _is_word(t[i - 1]):
            i -= 1
        while i > 0 and _is_word(t[i - 1]):
            i -= 1
        return i

    def _word_right(self, i):
        t = self.text
        n = len(t)
        while i < n and not _is_word(t[i]):
            i += 1
        while i < n and _is_word(t[i]):
            i += 1
        return i

    def _line_start(self, i):
        return self.text.rfind("\n", 0, i) + 1

    def _line_end(self, i):
        j = self.text.find("\n", i)
        return len(self.text) if j < 0 else j

    def _move(self, target, shift):
        if shift:
            if self.anchor is None:
                self.anchor = self.caret
        else:
            self.anchor = None
        self.caret = target
        if self.anchor == self.caret:
            self.anchor = None
        self._coalescing = False

    def _vertical(self, up, shift):
        start = self._line_start(self.caret)
        col = self.caret - start
        if up:
            if start == 0:
                return False
            prev_start = self._line_start(start - 1)
            target = min(prev_start + col, start - 1)
        else:
            end = self._line_end(self.caret)
            if end >= len(self.text):
                return False
            next_start = end + 1
            target = min(next_start + col, self._line_end(next_start))
        self._move(target, shift)
        return True

    def _recall(self, up):
        if up:
            if self._hist_index + 1 >= len(self._history):
                return
            if self._hist_index == -1:
                self._draft = self.text
            self._hist_index += 1
        else:
            if self._hist_index < 0:
                return
            self._hist_index -= 1
        self.text = (
            self._draft if self._hist_index < 0 else self._history[self._hist_index]
        )
        self.caret = len(self.text)
        self.anchor = None
        self._coalescing = False

    # -- key handling -------------------------------------------------------------

    def set_caret(self, index, extend=False):
        """Put the caret at ``index`` (a click); ``extend`` selects from the old caret. Ends undo coalescing."""
        self._move(max(0, min(len(self.text), index)), extend)

    def drag_to(self, index):
        """A mouse drag that started at the last click: select from there to ``index``."""
        self.set_caret(index, extend=True)

    def select_word(self, index):
        """A double click: select the word, or the run of spaces or signs, at ``index``."""
        t, n = self.text, len(self.text)
        if not t:
            return
        i = max(0, min(n - 1, index))
        if 0 < index and (index >= n or not _is_word(t[index]) and _is_word(t[index - 1])):
            i = index - 1  # a click just after a word selects that word
        kind = _is_word(t[i])
        start, end = i, i + 1
        while start > 0 and _is_word(t[start - 1]) == kind and t[start - 1] != "\n":
            start -= 1
        while end < n and _is_word(t[end]) == kind and t[end] != "\n":
            end += 1
        self.anchor, self.caret = start, end
        self._coalescing = False

    def handle(self, key, ctrl=False, alt=False, shift=False, cmd=False, char=""):
        """Apply one key press; returns "submit", "blur", "copy", "cut", "paste" or None."""
        if not self.mac and ctrl and alt:
            ctrl = alt = False  # AltGr arrives as Ctrl+Alt on Windows: AltGr+A types "ą", not Select all.
        command = cmd if self.mac else ctrl
        word = alt if self.mac else ctrl

        if command and (self.mac or key in _COMMAND_KEYS):
            return self._command(key, shift)

        if key == "RET" or key == "NUMPAD_ENTER":
            if shift:
                self._insert("\n", coalesce=False)
                return None
            return "submit"
        if key == "ESC":
            return "blur"
        if key == "TAB":
            return None

        if key == "LEFT_ARROW":
            sel = self.selection()
            if sel and not shift and not word:
                self._move(sel[0], False)
            elif word:
                self._move(self._word_left(self.caret), shift)
            else:
                self._move(max(0, self.caret - 1), shift)
        elif key == "RIGHT_ARROW":
            sel = self.selection()
            if sel and not shift and not word:
                self._move(sel[1], False)
            elif word:
                self._move(self._word_right(self.caret), shift)
            else:
                self._move(min(len(self.text), self.caret + 1), shift)
        elif key == "HOME":
            self._move(self._line_start(self.caret), shift)
        elif key == "END":
            self._move(self._line_end(self.caret), shift)
        elif key == "UP_ARROW":
            if not self._vertical(True, shift):
                if shift or not self._history:
                    self._move(0, shift)
                else:
                    self._recall(True)
        elif key == "DOWN_ARROW":
            if not self._vertical(False, shift):
                if shift or self._hist_index < 0:
                    self._move(len(self.text), shift)
                else:
                    self._recall(False)
        elif key == "BACK_SPACE":
            sel = self.selection()
            if sel:
                self._replace(*sel, "")
            elif self.caret > 0:
                start = self._word_left(self.caret) if word else self.caret - 1
                self._replace(start, self.caret, "")
        elif key == "DEL":
            sel = self.selection()
            if sel:
                self._replace(*sel, "")
            elif self.caret < len(self.text):
                end = self._word_right(self.caret) if word else self.caret + 1
                self._replace(self.caret, end, "")
        elif char and char.isprintable():
            self._insert(char, coalesce=_is_word(char))
        return None

    def _command(self, key, shift):
        if key == "A":
            self.anchor = 0
            self.caret = len(self.text)
            if not self.text:
                self.anchor = None
            self._coalescing = False
        elif key == "C":
            return "copy" if self.selection() else None
        elif key == "X":
            return "cut" if self.selection() else None
        elif key == "V":
            return "paste"
        elif key == "Z":
            self._redo_step() if shift else self._undo_step()
        elif key == "Y" and not self.mac:
            self._redo_step()
        elif key in ("LEFT_ARROW", "RIGHT_ARROW") and self.mac:
            if key == "LEFT_ARROW":
                self._move(self._line_start(self.caret), shift)
            else:
                self._move(self._line_end(self.caret), shift)
        elif key == "HOME":
            self._move(0, shift)
        elif key == "END":
            self._move(len(self.text), shift)
        return None
