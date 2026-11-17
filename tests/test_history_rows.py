"""The bar's chat history view. Needs ``pip install skia-python==144.1``; fails without it."""

import os
import tempfile
import unittest

import skia  # noqa: F401  (a missing Skia fails the suite instead of skipping it)

from eachlabs.chat import session_log
from eachlabs.ui import bar, bar_state, history_rows, tokens
from eachlabs.ui.text_field import TextField

from .test_bar_state import chat, state

SNAPSHOTS = os.environ.get("EACHLABS_BAR_SNAPSHOTS") or os.path.join(tempfile.gettempdir(), "bar-snapshots")
WIDTH = 640
INNER = WIDTH - tokens.PAD_LEFT - tokens.PAD_RIGHT
SHORT = [("user", "a street at dusk", ""), ("assistant", "Built a street with 12 buildings.", "done  ·  $0.38")]
LONG = [(role, "%s %d: " % (role, i) + "a long line about the street and its lamps " * 4, "done" if role != "user" else "")
        for i in range(12) for role in ("user", "assistant")]


def bar_with(entries, scroll=0.0, **kw):
    values = dict(mode="typing", field=TextField([], mac=False), focused=True, settings=True, history_button=True,
                  history_open=True, history=entries, history_scroll=scroll)
    values.update(kw)
    return bar.BarState(**values)


class EntriesTest(unittest.TestCase):
    def test_stored_messages_become_entries_with_how_the_run_ended(self):
        shown = session_log.entries([
            {"role": "user", "kind": "user", "content": "a street at dusk"},
            {"role": "assistant", "kind": "assistant", "content": "A street.", "detail": {"status": "done", "cost": 0.3785}},
            {"role": "assistant", "kind": "error", "content": "  ", "detail": {"status": "failed"}},
            {"role": "system", "content": "not a chat line"}, "junk"])
        self.assertEqual(shown, [{"role": "user", "text": "a street at dusk", "status": "", "cost": 0.0},
                                 {"role": "assistant", "text": "A street.", "status": "done", "cost": 0.3785}])

    def test_the_lines_a_run_writes_read_the_same_as_stored_ones(self):
        lines = session_log.lines_for("t1", "add rain", "Rain added.", "done", {"cost": 0.1})
        self.assertEqual([(e["role"], e["text"], e["status"]) for e in session_log.entries(lines)],
                         [("user", "add rain", ""), ("assistant", "Rain added.", "done")])

    def test_the_view_shows_status_and_cost_on_answers_and_cuts_a_very_long_text(self):
        shown = bar_state.history_entries([
            {"role": "user", "text": "x" * (tokens.HISTORY_TEXT_MAX + 50), "status": "", "cost": 0.0},
            {"role": "assistant", "text": "A street.", "status": "done", "cost": 0.3785},
            {"role": "assistant", "text": "Stopped.", "status": "cancelled", "cost": 0.0}])
        self.assertEqual(len(shown[0][1]), tokens.HISTORY_TEXT_MAX)
        self.assertEqual(shown[0][2], "")
        self.assertEqual(shown[1][2], "done" + tokens.HINT_SEPARATOR + "$0.38")
        self.assertEqual(shown[2][2], "cancelled")


class StateTest(unittest.TestCase):
    LINES = [{"role": "user", "text": "a street", "status": "", "cost": 0.0}]

    def test_the_button_shows_only_for_a_scene_chat_with_history(self):
        self.assertFalse(state(chat()).history_button)
        s = state(chat(), history=self.LINES)
        self.assertTrue(s.history_button)
        self.assertFalse(s.history_open)

    def test_open_carries_the_entries_and_the_scroll(self):
        s = state(chat(), history=self.LINES, history_open=True, history_scroll=30)
        self.assertEqual((s.history_open, s.history, s.history_scroll), (True, [("user", "a street", "")], 30.0))

    def test_a_run_and_the_video_tab_hide_it(self):
        running = state(chat(running=True, status="running"), history=self.LINES, history_open=True)
        self.assertFalse(running.history_button or running.history_open)
        video = state(chat(), history=self.LINES, history_open=True, tab="video")
        self.assertFalse(video.history_button or video.history_open)

    def test_its_hits_are_matched_before_the_bar(self):
        for name in tokens.HISTORY_HITS:
            self.assertLess(bar_state._HIT_ORDER.index(name), bar_state._HIT_ORDER.index("bar"))


class ViewTest(unittest.TestCase):
    def test_a_short_history_fits_and_does_not_scroll(self):
        self.assertEqual(history_rows.max_scroll(SHORT, INNER), 0)
        frame = bar.render(bar_with(SHORT), WIDTH, 1.0)
        self.assertLessEqual({"history", "history_close", "field", "send", "settings", "bar"}, set(frame.hits))
        self.assertFalse({"history_up", "history_down"} & set(frame.hits))

    def test_a_long_history_scrolls_inside_a_view_of_fixed_height(self):
        furthest = history_rows.max_scroll(LONG, INNER)
        self.assertGreater(furthest, 0)
        self.assertEqual(history_rows.view_height(LONG, INNER), tokens.HISTORY_MAX_H)
        newest = bar.render(bar_with(LONG), WIDTH, 1.0)
        oldest = bar.render(bar_with(LONG, scroll=furthest), WIDTH, 1.0)
        self.assertLessEqual({"history_up", "history_down", "history_close"}, set(newest.hits))
        self.assertEqual((newest.width, newest.height), (oldest.width, oldest.height))  # the bar does not grow
        self.assertNotEqual(newest.rgba, oldest.rgba)  # other entries show
        past = bar.render(bar_with(LONG, scroll=furthest + 500), WIDTH, 1.0)
        self.assertEqual(past.rgba, oldest.rgba)  # a scroll past the start stops at the first entry
        os.makedirs(SNAPSHOTS, exist_ok=True)
        bar.save_png(newest, os.path.join(SNAPSHOTS, "history-newest.png"))
        bar.save_png(oldest, os.path.join(SNAPSHOTS, "history-oldest.png"))

    def test_scroll_is_kept_between_the_ends(self):
        furthest = history_rows.max_scroll(LONG, INNER)
        self.assertEqual(history_rows.clamp_scroll(-20, LONG, INNER), 0.0)
        self.assertEqual(history_rows.clamp_scroll(furthest + 1, LONG, INNER), float(furthest))

    def test_the_button_takes_room_from_the_field_only_when_shown(self):
        with_button = bar.render(bar_with(SHORT, history_open=False), WIDTH, 1.0)
        without = bar.render(bar.BarState(mode="typing", field=TextField([], mac=False), settings=True), WIDTH, 1.0)
        self.assertNotIn("history", without.hits)
        self.assertLess(with_button.hits["field"][2], without.hits["field"][2])

    def test_a_run_draws_its_status_not_the_history(self):
        frame = bar.render(bar_with(SHORT, mode="building", stages={"layout": "active"}, status="Building"), WIDTH, 1.0)
        self.assertNotIn("history_close", frame.hits)

    def test_text_skia_cannot_encode_is_cleaned(self):
        bar.render(bar_with([("user", "broken \ud800 text", "")]), WIDTH, 1.0)


class ScrollInputTest(unittest.TestCase):
    def test_wheel_keys_and_trackpad_move_the_view(self):
        self.assertEqual(history_rows.step("WHEELUPMOUSE", "PRESS"), tokens.HISTORY_STEP)
        self.assertEqual(history_rows.step("WHEELDOWNMOUSE", "PRESS"), -tokens.HISTORY_STEP)
        self.assertGreater(history_rows.step("PAGE_UP", "PRESS"), 0)
        self.assertLess(history_rows.step("PAGE_DOWN", "PRESS"), 0)
        self.assertEqual(history_rows.step("PAGE_UP", "RELEASE"), 0)
        self.assertEqual(history_rows.step("TRACKPADPAN", "NOTHING", moved=12), -12)
        self.assertEqual(history_rows.step("MOUSEMOVE", "NOTHING", moved=12), 0)
