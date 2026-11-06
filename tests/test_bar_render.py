"""The prompt bar drawn with Skia. Needs ``pip install skia-python==144.1``; fails without it."""

import dataclasses
import os
import tempfile
import time
import types
import unittest

import skia  # noqa: F401  (a missing Skia fails the suite instead of skipping it)

from eachlabs.ui import bar, fonts, tokens
from eachlabs.ui.text_field import TextField

SNAPSHOTS = os.environ.get("EACHLABS_BAR_SNAPSHOTS") or os.path.join(tempfile.gettempdir(), "bar-snapshots")
PROMPT = "a street at dusk, slow dolly forward over 5 seconds"
REPLY = ("Built a street with 12 buildings, 10 lamps and a dusk sky. "
         "The camera dollies forward over 5 seconds.")


def field(text="", caret=None):
    f = TextField([], mac=False)
    f.text = text
    f.caret = len(text) if caret is None else caret
    return f


def mockups():
    """One state per approved mockup frame, with the hit ids its controls must have."""
    building = {"layout": "done", "materials": "done", "light": "active", "camera": "todo", "check": "todo"}
    done = {s: "done" for s in ("layout", "materials", "light", "camera", "check")}
    checking = {"layout": "done", "materials": "active", "light": "todo", "camera": "todo", "check": "todo"}
    return {
        "01-idle": (bar.BarState(mode="idle", field=field()), {"send", "field", "bar"}),
        "02-typing": (bar.BarState(mode="typing", field=field(PROMPT), focused=True, caret_on=True),
                      {"send", "field", "bar"}),
        "03-building": (bar.BarState(mode="building", field=field(PROMPT), stages=building, round=5, total=20,
                                     status="Adding street lamps and a low warm sun…", spinner_phase=0.3),
                        {"stop", "field", "bar"}),
        "04-done": (bar.BarState(mode="done", field=field(), stages=done, reply=REPLY + " — press Space to play.",
                                 cost_text="9 ROUNDS · $0.004 · CTRL+Z UNDOES ONE STAGE"),
                    {"send", "field", "bar"}),
        "05-error": (bar.BarState(mode="error", field=field(), error="API key was rejected (HTTP 401).",
                                  actions=["prefs"], send_enabled=False),
                     {"prefs", "field", "bar"}),
        "08-done-undo": (bar.BarState(mode="done", field=field(), stages=done, reply=REPLY,
                                      cost_text="9 ROUNDS · $0.004", actions=["play", "frame", "undo"]),
                         {"play", "frame", "undo", "send", "field", "bar"}),
        "09-retry": (bar.BarState(mode="stopped", field=field(),
                                  stages={"layout": "done", "materials": "done", "light": "done", "camera": "failed", "check": "todo"},
                                  error="Camera stage stopped: the camera step failed 3 times — the look-at "
                                        "point was inside a building. Layout and light are kept.",
                                  actions=["retry", "keep"]),
                     {"retry", "keep", "send", "field", "bar"}),
        "10-multiline": (bar.BarState(mode="typing", field=field(PROMPT + "\nwet asphalt with reflections from the lamps"),
                                      focused=True, caret_on=True),
                         {"send", "field", "bar"}),
        "13-waiting": (bar.BarState(mode="waiting", field=field(PROMPT), stages=building, round=4, total=20,
                                    thinking_seconds=18, spinner_phase=0.6),
                       {"stop", "field", "bar"}),
        "15-consent": (bar.BarState(mode="consent", field=field(PROMPT), focused=True, caret_on=False,
                                    actions=["consent_plain", "consent_cancel"]),
                       {"consent_plain", "consent_cancel", "send", "field", "bar"}),
        "16-code-check": (bar.BarState(mode="building", field=field(PROMPT), stages=checking, round=4, total=20,
                                       code_check=True, status=tokens.CHECKING_TEXT, spinner_phase=0.3),
                          {"stop", "field", "bar"}),
        "17-refused": (bar.BarState(mode="building", field=field(PROMPT), stages=checking, round=4, total=20,
                                    code_check=True, spinner_phase=0.3, actions=["code", "halt"],
                                    error=tokens.REFUSED_TEXT % "it tried to read a file outside Blender"),
                       {"code", "halt", "stop", "field", "bar"}),
    }


def overlaps(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def inside(inner, outer):
    ix, iy, iw, ih = inner
    ox, oy, ow, oh = outer
    return ox <= ix and oy <= iy and ix + iw <= ox + ow and iy + ih <= oy + oh


def pixel(frame, x, y):
    i = (y * frame.width + x) * 4
    return tuple(frame.rgba[i:i + 4])


def bar_height(frame):
    return frame.bar_rect[3]


class AvailableTest(unittest.TestCase):
    def test_available_when_skia_imports(self):
        self.assertTrue(bar.available())

    def test_missing_fonts_make_the_bar_unavailable_without_a_system_font(self):
        saved = fonts.FONT_DIR
        with tempfile.TemporaryDirectory() as empty:
            fonts.FONT_DIR = empty
            try:
                self.assertFalse(bar.available())
                with self.assertRaises(RuntimeError):
                    bar.render(bar.BarState(field=field("abc")), 640, 1)
                self.assertFalse([k for k in fonts._fonts if k[0] == empty])
            finally:
                fonts.FONT_DIR = saved
        self.assertTrue(bar.available())


class ShapeTest(unittest.TestCase):
    def test_unfocused_multi_line_prompt_has_rounded_corners_and_the_mark_inside(self):
        for n in (3, 6):
            with self.subTest(lines=n):
                text = "\n".join("line %d" % i for i in range(n))
                frame = bar.render(bar.BarState(mode="idle", field=field(text)), 640, 1)
                bx, by, bw, bh = frame.bar_rect
                # Inside a 20 px corner, outside a full pill's corner.
                self.assertAlmostEqual(pixel(frame, bx + 3, by + 12)[3], round(0.92 * 255), delta=12)
                orange = [(x, y) for y in range(by, by + bh) for x in range(bx, bx + 40)
                          if pixel(frame, x, y)[0] > 150 and pixel(frame, x, y)[1] < 100]
                self.assertTrue(orange)
                r = tokens.RADIUS_ROWS
                for x, y in orange:
                    cx = min(max(x + 0.5, bx + r), bx + bw - r)
                    cy = min(max(y + 0.5, by + r), by + bh - r)
                    self.assertLessEqual((x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2, r * r, (x, y))

    def test_single_row_bar_stays_a_pill(self):
        frame = bar.render(bar.BarState(mode="idle", field=field()), 640, 1)
        bx, by, bw, bh = frame.bar_rect
        self.assertLess(pixel(frame, bx + 3, by + 12)[3], 200)


class MockupStatesTest(unittest.TestCase):
    def test_every_mockup_state_renders_with_its_controls(self):
        os.makedirs(SNAPSHOTS, exist_ok=True)
        width = round((640 + 2 * tokens.MARGIN_X) * 2)
        for name, (state, ids) in mockups().items():
            with self.subTest(name):
                frame = bar.render(state, 640, 2)
                bar.save_png(frame, os.path.join(SNAPSHOTS, name + ".png"))
                self.assertEqual(frame.width, width)
                self.assertEqual(len(frame.rgba), frame.width * frame.height * 4)
                bx, by, bw, bh = frame.bar_rect
                self.assertEqual(bw, 1280)
                self.assertTrue(inside(frame.bar_rect, (0, 0, frame.width, frame.height)))
                self.assertEqual(set(frame.hits), ids)
                self.assertEqual(frame.hits["bar"], frame.bar_rect)
                controls = {k: v for k, v in frame.hits.items() if k != "bar"}
                for key, rect in controls.items():
                    self.assertTrue(inside(rect, frame.bar_rect), key)
                    self.assertGreater(rect[2] * rect[3], 0, key)
                keys = sorted(controls)
                for i, a in enumerate(keys):
                    for b in keys[i + 1:]:
                        self.assertFalse(overlaps(controls[a], controls[b]), (a, b))

    def test_mockup_bar_heights(self):
        # Logical heights measured on the approved frames (scale 1), within 2 px.
        expected = {"01-idle": 52, "03-building": 122, "04-done": 164, "05-error": 93,
                    "08-done-undo": 178, "09-retry": 178, "10-multiline": 86, "13-waiting": 148,
                    "15-consent": 167, "16-code-check": 123, "17-refused": 179}
        states = mockups()
        for name, height in expected.items():
            with self.subTest(name):
                frame = bar.render(states[name][0], 640, 1)
                self.assertAlmostEqual(bar_height(frame), height, delta=2)

    def test_pixels_are_premultiplied_with_a_clear_margin(self):
        frame = bar.render(mockups()["03-building"][0], 640, 2)
        self.assertEqual(pixel(frame, 0, 0), (0, 0, 0, 0))
        bx, by, bw, bh = frame.bar_rect
        r, g, b, a = pixel(frame, bx + bw // 2, by + 4)
        self.assertAlmostEqual(a, round(0.92 * 255), delta=3)
        for i in range(0, len(frame.rgba), 4 * 97):
            r, g, b, a = frame.rgba[i:i + 4]
            self.assertTrue(r <= a and g <= a and b <= a)


class LayoutTest(unittest.TestCase):
    def test_five_stage_chips_fit_a_narrow_bar(self):
        stages = {"layout": "done", "materials": "done", "light": "active", "camera": "todo", "check": "todo"}
        state = bar.BarState(mode="building", field=field(PROMPT), stages=stages, round=12, total=20,
                             status="Street lamps")
        for width in (640, 568):
            with self.subTest(width=width):
                frame = bar.render(state, width, 2)
                self.assertEqual(frame.bar_rect[2], width * 2)
                self.assertTrue(inside(frame.hits["stop"], frame.bar_rect))

    def test_narrow_region_wraps_the_reply_and_keeps_send_inside(self):
        reply = ("Built a street with twelve buildings, ten lamps and a dusk sky; "
                 "the camera dollies forward over five seconds, ok. Enjoy!")
        self.assertEqual(len(reply), 120)
        short = bar.render(bar.BarState(mode="done", field=field(), reply="Built it.", stages={"layout": "done"}),
                           568, 2)
        long = bar.render(bar.BarState(mode="done", field=field(), reply=reply, stages={"layout": "done"}), 568, 2)
        self.assertEqual(long.bar_rect[2], 568 * 2)
        self.assertGreaterEqual(bar_height(long) - bar_height(short), tokens.STATUS_LINE * 2)
        self.assertTrue(inside(long.hits["send"], long.bar_rect))
        self.assertGreaterEqual(len(bar.wrap(reply, "regular", tokens.TEXT_SIZE, 568 - 24)), 2)

    def test_scale_multiplies_pixels_and_hits(self):
        state = mockups()["08-done-undo"][0]
        one, two = bar.render(state, 640, 1), bar.render(state, 640, 2)
        self.assertEqual(two.width, one.width * 2)
        for key in one.hits:
            for a, b in zip(one.hits[key], two.hits[key]):
                self.assertAlmostEqual(b, a * 2, delta=2)

    def test_input_grows_up_to_six_lines_then_scrolls(self):
        heights = []
        for n in (1, 2, 6, 9):
            text = "\n".join("line %d" % i for i in range(n))
            heights.append(bar_height(bar.render(bar.BarState(mode="typing", field=field(text)), 640, 1)))
        self.assertLess(heights[0], heights[1])
        self.assertLess(heights[1], heights[2])
        self.assertEqual(heights[2], heights[3])

    def test_caret_blinks(self):
        on = bar.render(bar.BarState(mode="typing", field=field("abc"), focused=True, caret_on=True), 640, 1)
        off = bar.render(bar.BarState(mode="typing", field=field("abc"), focused=True, caret_on=False), 640, 1)
        self.assertNotEqual(on.rgba, off.rgba)

    def test_focus_changes_the_outline_only(self):
        a = bar.render(bar.BarState(mode="idle", field=field()), 640, 1)
        b = bar.render(bar.BarState(mode="idle", field=field(), focused=True), 640, 1)
        self.assertEqual(a.bar_rect, b.bar_rect)
        self.assertNotEqual(a.rgba, b.rgba)

    def test_spinner_and_thinking_dots_move_with_the_phase(self):
        state = mockups()["13-waiting"][0]
        a = bar.render(state, 640, 1)
        state.spinner_phase = 0.1
        self.assertNotEqual(a.rgba, bar.render(state, 640, 1).rgba)

    def test_slow_line_only_after_fifteen_seconds(self):
        state = mockups()["13-waiting"][0]
        state.thinking_seconds = 14
        quick = bar_height(bar.render(state, 640, 1))
        state.thinking_seconds = 15
        self.assertGreater(bar_height(bar.render(state, 640, 1)), quick)

    def test_any_script_draws(self):
        text = "кафе 日本の街 \U0001f306 street " * 4
        frame = bar.render(bar.BarState(mode="typing", field=field(text, caret=7), focused=True, caret_on=True),
                           600 - 32, 2)
        self.assertGreater(frame.height, 0)

    def test_selection_draws(self):
        f = field("select me")
        f.anchor = 0
        plain = bar.render(bar.BarState(mode="typing", field=field("select me"), focused=True), 640, 1)
        self.assertNotEqual(plain.rgba, bar.render(bar.BarState(mode="typing", field=f, focused=True), 640, 1).rgba)

    def test_hint_drops_items_that_do_not_fit(self):
        wide = bar.hint_text(616)
        narrow = bar.hint_text(300)
        self.assertTrue(wide.startswith("↑ earlier prompts"))
        self.assertLess(len(narrow), len(wide))
        self.assertLessEqual(bar.measure(narrow, "medium", tokens.HINT_SIZE), 300)

    def test_action_labels_name_the_stage(self):
        stages = {"layout": "done", "materials": "done", "light": "done", "camera": "failed", "check": "todo"}
        self.assertEqual(bar.action_label("retry", stages), "Retry camera stage")
        self.assertEqual(bar.action_label("undo", {"layout": "done", "check": "done"}), "Undo stage: Check")
        self.assertEqual(bar.action_label("prefs", {}), "Open preferences")
        self.assertEqual(bar.action_label("undo", {"camera": "done", "check": "done"}, "camera"), "Undo stage: Camera")
        self.assertEqual(bar.action_label("new", {}), "New scene")

    def test_placeholder_asks_for_a_change_while_there_is_a_scene(self):
        self.assertEqual(bar.placeholder(bar.BarState()), "Describe the scene you imagine…")
        self.assertEqual(bar.placeholder(bar.BarState(mode="done", has_scene=True)),
                         "Ask for a change: warmer light, a bigger window…")
        self.assertEqual(bar.placeholder(bar.BarState(mode="done")), "Describe the scene you imagine…")


GEIST = os.path.join(os.path.dirname(bar.__file__), os.pardir, "fonts", "geist-mono", "GeistMono-Medium.ttf")


class FallbackFontTest(unittest.TestCase):
    """A character Inter lacks is drawn from the first fallback font that has it."""

    def tearDown(self):
        bar.set_fallback_fonts([])

    def test_missing_glyph_comes_from_a_fallback_file(self):
        box = bar.measure("\u2500", "regular", 14)  # Inter has no box drawing; Geist Mono does
        state = bar.BarState(mode="typing", field=field("a\u2500b"), focused=True, caret_on=False)
        before = bar.render(state, 640, 1).rgba
        bar.set_fallback_fonts([os.path.join(tempfile.gettempdir(), "no-such-font.woff2"), GEIST])
        self.assertNotAlmostEqual(bar.measure("\u2500", "regular", 14), box, places=2)
        self.assertNotEqual(bar.render(state, 640, 1).rgba, before)

    def test_text_inter_has_is_unchanged(self):
        width = bar.measure("street", "regular", 14)
        bar.set_fallback_fonts([GEIST])
        self.assertAlmostEqual(bar.measure("street", "regular", 14), width, places=3)


class IndexAtTest(unittest.TestCase):
    def test_click_maps_to_the_nearest_character_edge(self):
        state = bar.BarState(mode="typing", field=field("hello world"), focused=True)
        frame = bar.render(state, 640, 1)
        _, _, _, fh = frame.hits["field"]
        mid = fh / 2
        self.assertEqual(bar.index_at(state, 640, -5, mid), 0)
        self.assertEqual(bar.index_at(state, 640, bar.measure("hello", "regular", 14) + 1, mid), 5)
        self.assertEqual(bar.index_at(state, 640, 600, mid), 11)

    def test_second_line(self):
        state = bar.BarState(mode="typing", field=field("one\ntwo three"), focused=True)
        frame = bar.render(state, 640, 1)
        _, _, _, fh = frame.hits["field"]
        top = (fh - 2 * tokens.TEXT_LINE) / 2
        self.assertEqual(bar.index_at(state, 640, 0, top + 5), 0)
        self.assertEqual(bar.index_at(state, 640, bar.measure("two", "regular", 14), top + tokens.TEXT_LINE + 5), 7)

    def test_empty_field_is_zero(self):
        self.assertEqual(bar.index_at(bar.BarState(field=field()), 640, 50, 10), 0)


WIDEST = {  # the longest action rows of each state, for the narrowest bar
    "narrow-done": bar.BarState(mode="done", field=field(), reply=REPLY, cost_text="9 ROUNDS · $0.004",
                                stages={s: "done" for s in ("layout", "materials", "light", "camera", "check")},
                                actions=["play", "frame", "final", "undo", "code", "new"], undo_stage="materials"),
    "narrow-cancelled": bar.BarState(mode="stopped", field=field(), error="Stopped. What was built is kept.",
                                     stages={"layout": "done", "materials": "done", "light": "cancelled"},
                                     actions=["undo", "code", "new", "keep"], undo_stage="materials"),
    "narrow-failed": bar.BarState(mode="stopped", field=field(), error="Stopped: run_python kept failing: boom",
                                  stages={"layout": "done", "materials": "done", "light": "failed"},
                                  actions=["retry", "undo", "code", "new"], undo_stage="materials"),
    "narrow-check-stopped": bar.BarState(
        mode="stopped", field=field(), stages={"layout": "done", "materials": "failed"},
        error="Code check stopped the run: it reads a file. " + tokens.CHECK_OFF_TEXT, actions=["retry", "code", "new"]),
    "narrow-error": bar.BarState(mode="error", field=field(), error="The model call failed: timed out",
                                 actions=["retry", "code", "new"]),
    "narrow-consent": bar.BarState(mode="consent", field=field(PROMPT), focused=True,
                                   actions=list(bar.CONSENT_ACTIONS)),
    "narrow-refused": bar.BarState(mode="building", field=field(PROMPT), round=4, total=20, code_check=True,
                                   stages={"layout": "done", "materials": "active", "light": "todo", "camera": "todo",
                                           "check": "todo"},
                                   error=tokens.REFUSED_TEXT % "it reads a file", actions=["code", "halt"]),
}


class NarrowActionsTest(unittest.TestCase):
    def test_widest_action_rows_wrap_at_the_minimum_width(self):
        os.makedirs(SNAPSHOTS, exist_ok=True)
        for name, state in WIDEST.items():
            for width in (240, 640):
                with self.subTest(name, width=width):
                    frame = bar.render(state, width, 2)
                    bar.save_png(frame, os.path.join(SNAPSHOTS, "%s-%d.png" % (name, width)))
                    self.assertEqual(set(state.actions) - set(frame.hits), set())  # nothing dropped
                    controls = {k: v for k, v in frame.hits.items() if k != "bar"}
                    for key, rect in controls.items():
                        self.assertTrue(inside(rect, frame.bar_rect), key)
                    keys = sorted(controls)
                    for i, a in enumerate(keys):
                        for b in keys[i + 1:]:
                            self.assertFalse(overlaps(controls[a], controls[b]), (a, b))

    def test_badge_and_round_take_their_own_line_when_the_chips_do_not_fit(self):
        state = WIDEST["narrow-refused"]
        wide = bar.render(state, 640, 1)
        narrow = bar.render(state, 240, 1)
        self.assertGreater(bar_height(narrow), bar_height(wide))
        frame = bar.render(dataclasses.replace(state, code_check=False), 640, 1)
        self.assertNotEqual(frame.rgba, wide.rgba)  # the badge draws

    def test_long_code_check_reason_is_cut_but_the_way_out_stays(self):
        reason = " ".join("reason%d" % i for i in range(200))
        error = "Code check stopped the run: %s. %s" % (reason, tokens.CHECK_OFF_TEXT)
        state = dataclasses.replace(WIDEST["narrow-check-stopped"], error=error)
        os.makedirs(SNAPSHOTS, exist_ok=True)
        bar.save_png(bar.render(state, 240, 2), os.path.join(SNAPSHOTS, "narrow-long-reason-240.png"))
        for width in (240 - 24 - 16, 640 - 24 - 16):
            lines, shown = bar.error_lines(error, "regular", width)
            self.assertGreater(len(lines), bar.MAX_TEXT_LINES)
            self.assertEqual(len(shown), bar.MAX_TEXT_LINES)
            self.assertEqual(" ".join(shown).split("…")[-1].strip(), tokens.CHECK_OFF_TEXT)
            self.assertIn("…", " ".join(shown))
        _, short = bar.error_lines("Code check stopped the run: x. " + tokens.CHECK_OFF_TEXT, "regular", 200)
        self.assertNotIn("…", " ".join(short))

    def test_checking_line_has_a_spinner(self):
        state = mockups()["16-code-check"][0]
        a = bar.render(state, 640, 1)
        self.assertNotEqual(a.rgba, bar.render(dataclasses.replace(state, spinner_phase=0.7), 640, 1).rgba)
        plain = bar.render(dataclasses.replace(state, status="Street lamps", stages={}), 640, 1)
        self.assertEqual(plain.height, bar.render(dataclasses.replace(state, stages={}), 640, 1).height)

    def test_show_code_pill_has_the_code_glyphs(self):
        self.assertEqual(bar.action_label("code", {}), "Show code")
        self.assertEqual(bar.action_label("halt", {}), "Stop")
        self.assertEqual(bar.action_label("retry", {}), "Retry")


class CodeCheckOffTest(unittest.TestCase):
    def test_the_consent_card_offers_build_and_shows_code_check_only_when_it_is_offered(self):
        from unittest import mock

        from eachlabs.ui import bar_state, tooltips

        self.assertFalse(tokens.CODE_CHECK_AVAILABLE)
        consent = bar_state.from_chat(types.SimpleNamespace(
            prompt="", stages={}, status="idle", thinking_since=None, round=0, total=20, tools=[], reply="",
            error="", cost=None, cost_text="", running=False, failed_stage=None, history=[], changed=[],
            unchanged=False), field(PROMPT), True, 100.0, consent=True)
        frame = bar.render(consent, 640, 1)
        self.assertEqual(consent.actions, ["consent_plain", "consent_cancel"])
        self.assertNotIn("consent_check", frame.hits)
        self.assertNotIn("Code check", tooltips.text("consent_plain"))
        with mock.patch.object(tokens, "CODE_CHECK_AVAILABLE", True):
            offered = bar.BarState(mode="consent", field=field(PROMPT), focused=True,
                                   actions=list(bar.CONSENT_ACTIONS))
            frame_on = bar.render(offered, 640, 1)
            self.assertIn("consent_check", frame_on.hits)
            self.assertEqual(bar.action_label("consent_plain", {}), "Build without check")
            self.assertGreater(bar_height(frame_on), bar_height(frame))  # the hint row is back


class NoteTest(unittest.TestCase):
    def test_a_note_draws_under_the_reply(self):
        done = {s: "done" for s in ("layout", "materials", "light", "camera", "check")}
        state = bar.BarState(mode="done", field=field(), stages=done, reply="A room.", note="3D: car $0.45",
                             actions=["play", "frame", "code", "new"])
        self.assertGreater(bar_height(bar.render(state, 640, 1)),
                           bar_height(bar.render(dataclasses.replace(state, note=""), 640, 1)))

    def test_a_done_run_that_changed_nothing_draws_its_line_and_retry(self):
        done = {s: "done" for s in ("layout", "materials", "light", "camera", "check")}
        state = bar.BarState(mode="done", field=field(), stages=done, reply="The scene shows the car.",
                             error=tokens.NOTHING_CHANGED, cost_text="15 ROUNDS", actions=["retry", "new"])
        frame = bar.render(state, 640, 1)
        plain = bar.render(dataclasses.replace(state, error=""), 640, 1)
        self.assertIn("retry", frame.hits)
        self.assertTrue(inside(frame.hits["retry"], frame.bar_rect))
        self.assertGreater(bar_height(frame), bar_height(plain))


class FoldedTest(unittest.TestCase):
    def done(self, **kw):
        stages = {s: "done" for s in ("layout", "materials", "light", "camera", "check")}
        values = dict(mode="done", field=field(), stages=stages, reply=REPLY, cost_text="34 ROUNDS · 6 MIN · $0.38",
                      actions=["play", "frame", "new"])
        values.update(kw)
        return bar.BarState(**values)

    def test_a_folded_card_is_one_line_with_no_buttons(self):
        open_card = bar.render(self.done(), 640, 1)
        folded = bar.render(self.done(folded=True), 640, 1)
        self.assertLess(bar_height(folded), bar_height(open_card) - 60)
        for name in ("play", "frame", "new"):
            self.assertIn(name, open_card.hits)
            self.assertNotIn(name, folded.hits)
        self.assertIn("field", folded.hits)  # a follow-up can still be typed
        self.assertIn("bar", folded.hits)

    def test_the_folded_line_says_done_and_the_cost(self):
        from eachlabs.ui import status_rows

        self.assertEqual(status_rows._folded_line(self.done()), "DONE · 34 ROUNDS · 6 MIN · $0.38")
        self.assertEqual(status_rows._folded_line(self.done(actions=["play", "retry"])),
                         "DONE · 34 ROUNDS · 6 MIN · $0.38 · A STAGE PARTLY DONE")
        self.assertEqual(status_rows._folded_line(self.done(cost_text="")), "DONE")


LONG_PROMPT = ("I want a mountain with a snow peak, a forest around it, a small village in the forest and a larger "
               "village with a stone fence, wooden gates, a marketplace, a church and a town hall with a big clock.")


class AskedTest(unittest.TestCase):
    def test_the_prompt_shows_while_building_done_and_after_an_error(self):
        done = {s: "done" for s in ("layout", "materials", "light", "camera", "check")}
        states = [bar.BarState(mode="building", field=field(), stages={"layout": "active"}, status="Building…"),
                  bar.BarState(mode="done", field=field(), stages=done, reply="A valley.", actions=["play", "new"]),
                  bar.BarState(mode="error", field=field(), error="The model did not answer.", actions=["retry"])]
        for state in states:
            frame = bar.render(dataclasses.replace(state, asked=LONG_PROMPT), 640, 1)
            plain = bar.render(state, 640, 1)
            self.assertIn("asked", frame.hits, state.mode)
            self.assertTrue(inside(frame.hits["asked"], frame.bar_rect), state.mode)
            self.assertEqual(bar_height(frame) - bar_height(plain), tokens.HINT_LINE + tokens.ROW_GAP, state.mode)
            self.assertNotIn("asked", plain.hits)

    def test_a_click_opens_the_whole_prompt(self):
        state = bar.BarState(mode="done", field=field(), stages={"layout": "done"}, reply="A valley.",
                             actions=["new"], asked=LONG_PROMPT)
        closed, opened = bar.render(state, 640, 1), bar.render(dataclasses.replace(state, asked_open=True), 640, 1)
        self.assertGreater(bar_height(opened), bar_height(closed))
        self.assertEqual(closed.hits["asked"][3], tokens.HINT_LINE)


class RightInsetTest(unittest.TestCase):
    """Right-aligned metadata keeps the left padding's 16 px from the bar's right edge."""

    def rightmost_text(self, frame):
        bx, by, bw, bh = frame.bar_rect
        rows_end = frame.hits["field"][1]  # only the rows above the input row
        xs = [x for y in range(by + 2, rows_end) for x in range(bx + bw // 2, bx + bw)
              if min(pixel(frame, x, y)[:3]) > 90]
        return max(xs) + 1 if xs else None

    def test_round_done_and_cost_are_16_px_in(self):
        done = {s: "done" for s in ("layout", "materials", "light", "camera", "check")}
        building = {"layout": "done", "materials": "done", "light": "active", "camera": "todo", "check": "todo"}
        states = [bar.BarState(mode="building", field=field(PROMPT), stages=building, round=5, total=20,
                               status="Adding lamps"),
                  bar.BarState(mode="done", field=field(), stages=done, reply="Built it.",
                               cost_text="9 ROUNDS · $0.004", actions=["play", "frame", "undo"])]
        for scale in (1, 2):
            for state in states:
                with self.subTest(mode=state.mode, scale=scale):
                    frame = bar.render(state, 640, scale)
                    bx, _, bw, _ = frame.bar_rect
                    right = self.rightmost_text(frame)
                    self.assertIsNotNone(right)
                    self.assertLessEqual(right, bx + bw - tokens.TEXT_RIGHT * scale)
                    self.assertGreater(right, bx + bw - (tokens.TEXT_RIGHT + 4) * scale)

    def test_send_button_keeps_its_8_px(self):
        frame = bar.render(bar.BarState(mode="idle", field=field()), 640, 1)
        bx, _, bw, _ = frame.bar_rect
        sx, _, sw, _ = frame.hits["send"]
        self.assertEqual(sx + sw, bx + bw - tokens.PAD_RIGHT)


if __name__ == "__main__":
    unittest.main()


class RobustnessTest(unittest.TestCase):
    def test_huge_unbroken_paste_renders_fast(self):
        f = TextField()
        f.paste("x" * 30000)
        self.assertEqual(len(f.text), 2000)
        state = bar.BarState(mode="typing", field=f, focused=True)
        bar.render(state, 640, 2)  # warm the font caches
        started = time.perf_counter()
        frame = bar.render(state, 640, 2)
        self.assertLess(time.perf_counter() - started, 0.1)
        self.assertGreater(frame.height, 0)

    def test_wrap_of_a_long_run_matches_measure(self):
        text = "a" * 500 + " " + "W" * 300
        width = 200
        lines = bar.wrap(text, "regular", tokens.TEXT_SIZE, width)
        self.assertEqual("".join(text[s:e] for s, e in lines), text)
        for s, e in lines:
            self.assertLessEqual(bar.measure(text[s:e].rstrip(), "regular", tokens.TEXT_SIZE), width + 0.01)
        started = time.perf_counter()
        bar.wrap("y" * 30000, "regular", tokens.TEXT_SIZE, 500)
        self.assertLess(time.perf_counter() - started, 0.1)

    def test_lone_surrogate_renders(self):
        f = TextField()
        f.paste("street \ud800 at dusk\x07")
        self.assertEqual(f.text, "street  at dusk")
        frame = bar.render(bar.BarState(mode="done", field=f, reply="Built \udfff it.", error=""), 640, 1)
        self.assertGreater(frame.height, 0)
        frame = bar.render(bar.BarState(mode="error", field=f, error="Bad \ud83d text"), 640, 1)
        self.assertGreater(frame.height, 0)

    def test_long_reply_and_error_are_clamped_to_six_lines(self):
        words = " ".join("word%d" % i for i in range(3000))
        short = bar.render(bar.BarState(mode="done", field=field(), reply="Built it."), 640, 1)
        long = bar.render(bar.BarState(mode="done", field=field(), reply=words), 640, 1)
        self.assertLessEqual(bar_height(long) - bar_height(short), tokens.STATUS_LINE * 5 + 1)
        err = bar.render(bar.BarState(mode="error", field=field(), error=words), 640, 1)
        self.assertLessEqual(bar_height(err), bar_height(short) + tokens.STATUS_LINE * 6)
        shown = bar.clamp(words, bar.wrap(words, "regular", tokens.TEXT_SIZE, 300), "regular", tokens.TEXT_SIZE, 300)
        self.assertEqual(len(shown), 6)
        self.assertTrue(shown[-1].endswith("…"))
        self.assertLessEqual(bar.measure(shown[-1], "regular", tokens.TEXT_SIZE), 300)


class QualityPickerRenderTest(unittest.TestCase):
    MENU = [("Prototype", "Quick drafts · fewer rounds, GPT-6.1 Terra · about $1 a room", True),
            ("Final (experimental)", "Full detail · more rounds, detail and reference pictures", False)]

    def check_controls(self, frame):
        controls = {k: v for k, v in frame.hits.items() if k != "bar"}
        for key, rect in controls.items():
            self.assertTrue(inside(rect, frame.bar_rect), key)
        keys = sorted(controls)
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                self.assertFalse(overlaps(controls[a], controls[b]), (a, b))

    def test_pill_sits_left_of_send_at_640_and_on_its_own_row_at_240(self):
        os.makedirs(SNAPSHOTS, exist_ok=True)
        state = bar.BarState(mode="idle", field=field(), quality_label="Prototype")
        wide, narrow = bar.render(state, 640, 2), bar.render(state, 240, 2)
        bar.save_png(wide, os.path.join(SNAPSHOTS, "picker-640.png"))
        bar.save_png(narrow, os.path.join(SNAPSHOTS, "picker-240.png"))
        self.assertEqual(set(wide.hits), {"quality", "send", "field", "bar"})
        self.assertEqual(set(narrow.hits), {"quality", "send", "field", "bar"})
        mx, my, mw, mh = wide.hits["quality"]
        sx, sy, sw, sh = wide.hits["send"]
        self.assertLess(mx + mw, sx)
        self.assertLess(sy, my + mh // 2 + 1)
        self.assertLess(my, sy + sh)  # one row
        self.assertLessEqual(wide.hits["field"][0] + wide.hits["field"][2], mx)
        self.assertEqual(bar_height(wide), bar_height(bar.render(bar.BarState(mode="idle", field=field()), 640, 2)))
        nx, ny, nw, nh = narrow.hits["quality"]
        self.assertLess(ny + nh, narrow.hits["send"][1])  # a row above the input
        self.assertEqual(nx + nw, narrow.hits["send"][0] + narrow.hits["send"][2])  # right-aligned with send
        self.assertGreaterEqual(narrow.hits["field"][2], 2 * 140)  # the field keeps its width
        for frame in (wide, narrow):
            self.check_controls(frame)

    def test_open_menu_draws_every_item_at_both_widths(self):
        os.makedirs(SNAPSHOTS, exist_ok=True)
        state = bar.BarState(mode="typing", field=field("a street"), focused=True, quality_label="Prototype",
                             quality_menu=list(self.MENU))
        for width in (640, 240):
            with self.subTest(width=width):
                frame = bar.render(state, width, 2)
                bar.save_png(frame, os.path.join(SNAPSHOTS, "picker-menu-%d.png" % width))
                self.assertEqual(set(frame.hits), set(tokens.QUALITY_HITS) | {"quality", "send", "field", "bar"})
                tops = [frame.hits[h][1] for h in tokens.QUALITY_HITS]
                self.assertEqual(tops, sorted(tops))  # in the listed order, top to bottom
                self.assertLess(frame.hits[tokens.QUALITY_HITS[-1]][1], frame.hits["quality"][1])
                self.check_controls(frame)
        closed = bar.render(dataclasses.replace(state, quality_menu=[]), 640, 1)
        self.assertGreater(bar_height(bar.render(state, 640, 1)), bar_height(closed))

    def test_menu_replaces_the_state_rows_and_keeps_their_way_out(self):
        done = {s: "done" for s in ("layout", "materials", "light", "camera", "check")}
        state = bar.BarState(mode="done", field=field(), stages=done, reply=REPLY, actions=["play", "new"],
                             quality_label="Prototype", quality_menu=list(self.MENU))
        frame = bar.render(state, 640, 1)
        self.assertNotIn("play", frame.hits)
        self.assertIn("quality", frame.hits)  # a click on the pill closes the menu again
        self.assertIn("play", bar.render(dataclasses.replace(state, quality_menu=[]), 640, 1).hits)

    def test_disabled_pill_draws_dimmed_without_a_hit(self):
        stages = {"layout": "done", "materials": "active"}
        state = bar.BarState(mode="building", field=field(), stages=stages, round=3, total=15, status="Lamps",
                             quality_label="Prototype", quality_enabled=False)
        for width in (640, 240):
            with self.subTest(width=width):
                frame = bar.render(state, width, 2)
                self.assertEqual(set(frame.hits), {"stop", "field", "bar"})
                self.assertNotEqual(frame.rgba, bar.render(dataclasses.replace(state, quality_enabled=True),
                                                           width, 2).rgba)

    def test_a_long_label_is_cut_and_the_field_keeps_room(self):
        state = bar.BarState(mode="idle", field=field(), quality_label="vendor/" + "x" * 200)
        frame = bar.render(state, 640, 1)
        self.assertLessEqual(frame.hits["quality"][2], tokens.QUALITY_PILL_MAX + 40)
        self.assertGreaterEqual(frame.hits["field"][2], tokens.QUALITY_FIELD_MIN)

    def test_a_click_maps_to_the_caret_with_the_pill_on_the_row(self):
        state = bar.BarState(mode="typing", field=field("abc def"), quality_label="Prototype")
        self.assertEqual(bar.index_at(state, 640, 10000, 10), len("abc def"))
        self.assertEqual(bar.index_at(state, 640, 0, 10), 0)


def plan_state():
    from eachlabs import plan3d
    from eachlabs.ui import bar_state

    answer = ('{"objects_3d": [{"name": "muscle car", "description": "red 1970s muscle car", "tier": "large"}, '
              '{"name": "street lamp", "description": "black iron street lamp", "tier": "medium"}, '
              '{"name": "tree", "description": "leafy oak tree", "tier": "medium"}], '
              '"code": [{"name": "boulder", "solid": true}, "road", "sidewalks", "buildings", "lane marks"]}')
    plan = plan3d.parse(answer, 4, cached=lambda d, t: d == "leafy oak tree")
    s = bar.BarState(mode="plan", field=field(), actions=["plan_build", "plan_cancel"], send_enabled=False,
                     quality_label="Prototype", quality_enabled=False)
    s.plan_3d, s.plan_code, s.plan_chips, s.plan_note = bar_state.plan_fields(plan)
    return s, plan


class PlanRenderTest(QualityPickerRenderTest):
    def test_plan_draws_every_chip_build_and_cancel_at_both_widths(self):
        os.makedirs(SNAPSHOTS, exist_ok=True)
        state, plan = plan_state()
        self.assertEqual(state.plan_3d, "3D: muscle car, street lamp, tree · 2 × $0.45 = $0.90 · 1 cached, free · "
                                        "about 6 min one by one")
        chips = {tokens.PLAN_HITS[i] for i in range(4)}  # the solid pieces; objects with parts have no chip
        for width in (640, 240):
            with self.subTest(width=width):
                frame = bar.render(state, width, 2)
                bar.save_png(frame, os.path.join(SNAPSHOTS, "plan-%d.png" % width))
                self.assertEqual(set(frame.hits), chips | {"plan_build", "plan_cancel", "stop", "field", "bar"})
                self.check_controls(frame)
                three_d = [frame.hits[tokens.PLAN_HITS[i]] for i in range(3)]
                code = [frame.hits[tokens.PLAN_HITS[3]]]
                self.assertLess(max(r[1] for r in three_d), min(r[1] for r in code))  # the 3D chips come first
                self.assertLess(max(r[1] for r in code), frame.hits["plan_build"][1])
                self.assertEqual(frame.hits["plan_cancel"][1], frame.hits["plan_build"][1])  # Cancel on Build's line

    def test_a_looks_only_plan_draws_its_line_build_and_cancel(self):
        from eachlabs import plan3d
        from eachlabs.ui import bar_state

        os.makedirs(SNAPSHOTS, exist_ok=True)
        plan = plan3d.looks_plan(True, 6, 0.15)
        state = bar.BarState(mode="plan", field=field(), actions=["plan_build", "plan_cancel"], send_enabled=False,
                             quality_label="Prototype", quality_enabled=False, plan_looks=plan.looks)
        state.plan_3d, state.plan_code, state.plan_chips, state.plan_note = bar_state.plan_fields(plan)
        for width in (640, 240):
            with self.subTest(width=width):
                frame = bar.render(state, width, 2)
                bar.save_png(frame, os.path.join(SNAPSHOTS, "plan-looks-%d.png" % width))
                self.assertEqual(set(frame.hits), {"plan_build", "plan_cancel", "stop", "field", "bar"})
                self.check_controls(frame)
        full, _plan = plan_state()
        self.assertLess(bar.render(state, 640, 1).height, bar.render(full, 640, 1).height)

    def test_a_moved_chip_changes_the_lines(self):
        state, plan = plan_state()
        plan.toggle(0)
        from eachlabs.ui import bar_state

        moved = dataclasses.replace(state)
        moved.plan_3d, moved.plan_code, moved.plan_chips, moved.plan_note = bar_state.plan_fields(plan)
        self.assertEqual(moved.plan_3d,
                         "3D: street lamp, tree · 1 × $0.45 = $0.45 · 1 cached, free · about 3 min one by one")
        self.assertTrue(moved.plan_code.startswith("Code: muscle car, boulder, road"))
        self.assertNotEqual(bar.render(moved, 640, 1).rgba, bar.render(state, 640, 1).rgba)

    def test_job_lines_while_building(self):
        os.makedirs(SNAPSHOTS, exist_ok=True)
        stages = {"layout": "done", "materials": "active", "light": "todo", "camera": "todo", "check": "todo"}
        state = bar.BarState(mode="building", field=field(), stages=stages, round=4, total=16, status="Brick walls",
                             objects=["Generating the muscle car… 2:10", "Bringing in the tree from the cache…"])
        for width in (640, 240):
            with self.subTest(width=width):
                frame = bar.render(state, width, 2)
                bar.save_png(frame, os.path.join(SNAPSHOTS, "objects-%d.png" % width))
                self.check_controls(frame)
                self.assertGreater(bar_height(frame), bar_height(bar.render(
                    dataclasses.replace(state, objects=[]), width, 2)))

    def test_job_lines_are_cleaned_and_cut(self):
        stages = {"layout": "active"}
        base = bar.BarState(mode="building", field=field(), stages=stages, round=1, total=16, status="Road")
        plain = dataclasses.replace(base, objects=["Generating the car 2:10"])
        dirty = dataclasses.replace(base, objects=["Generating the \x1b[31mcar\x00\n\r\t 2:10\ud800"])
        long = dataclasses.replace(base, objects=["Generating the " + "very long name " * 40])
        for width in (640, 240):
            with self.subTest(width=width):
                one = bar_height(bar.render(plain, width, 1))
                frame = bar.render(dirty, width, 1)  # no control character, newline or lone surrogate reaches Skia
                self.check_controls(frame)
                self.assertEqual(bar_height(frame), bar_height(bar.render(
                    dataclasses.replace(base, objects=["Generating the [31mcar 2:10"]), width, 1)))
                self.assertLessEqual(bar_height(bar.render(long, width, 1)), one + tokens.SLOW_LINE)  # two lines

    def test_the_waiting_line_says_it_is_working_and_nothing_about_the_model(self):
        self.assertEqual(tokens.SLOW_TEXT, "Still working… You can keep using Blender.")

    def test_a_long_item_name_is_cut_to_fit_a_narrow_bar(self):
        state, _plan = plan_state()
        state.plan_chips = [(0, "A very long name for one object " * 3, "3d", True)] + state.plan_chips[1:]
        frame = bar.render(state, 240, 1)
        self.check_controls(frame)


class TabRowRenderTest(unittest.TestCase):
    def test_the_tabs_above_the_input_fit_at_every_width_and_wrap_in_reading_order(self):
        os.makedirs(SNAPSHOTS, exist_ok=True)
        state = bar.BarState(mode="idle", field=field(), tab="asset", quality_label="Prototype")
        for width in (640, 240):
            with self.subTest(width=width):
                frame = bar.render(state, width, 2)
                bar.save_png(frame, os.path.join(SNAPSHOTS, "tabs-%d.png" % width))
                for hit_id in tokens.TAB_HITS:
                    self.assertTrue(inside(frame.hits[hit_id], frame.bar_rect), hit_id)
                    self.assertLess(frame.hits[hit_id][1], frame.hits["field"][1])  # above the input
                places = [(frame.hits[h][1], frame.hits[h][0]) for h in tokens.TAB_HITS]
                self.assertEqual(places, sorted(places))  # line by line, left to right
                self.assertEqual(len({y for y, _x in places}), 1 if width == 640 else 2)
                controls = {k: v for k, v in frame.hits.items() if k != "bar"}
                keys = sorted(controls)
                for i, a in enumerate(keys):
                    for b in keys[i + 1:]:
                        self.assertFalse(overlaps(controls[a], controls[b]), (a, b))

    def test_the_chosen_tab_is_marked_and_no_tab_draws_no_row(self):
        chosen = bar.render(bar.BarState(mode="idle", field=field(), tab="scene"), 640, 1)
        other = bar.render(bar.BarState(mode="idle", field=field(), tab="character"), 640, 1)
        self.assertNotEqual(chosen.rgba, other.rgba)
        none = bar.render(bar.BarState(mode="idle", field=field()), 640, 1)
        self.assertFalse(set(tokens.TAB_HITS) & set(none.hits))
        self.assertGreater(bar_height(chosen), bar_height(none))

    def test_while_a_run_goes_the_tabs_are_dimmed_without_hits(self):
        state = bar.BarState(mode="building", field=field(), stages={"layout": "active"}, round=2, total=12,
                             status="Barrel", tab="asset", tabs_enabled=False)
        frame = bar.render(state, 640, 1)
        self.assertFalse(set(tokens.TAB_HITS) & set(frame.hits))
        self.assertNotEqual(frame.rgba, bar.render(dataclasses.replace(state, tabs_enabled=True), 640, 1).rgba)

    def test_each_tab_has_its_placeholder(self):
        from eachlabs.ui import input_rows

        self.assertEqual(input_rows.placeholder(bar.BarState(tab="asset")), tokens.PLACEHOLDER_ASSET)
        self.assertEqual(input_rows.placeholder(bar.BarState(tab="character")), tokens.PLACEHOLDER_CHARACTER)
        self.assertEqual(input_rows.placeholder(bar.BarState(tab="scene", has_scene=True)), tokens.PLACEHOLDER_NEXT)
        self.assertEqual(input_rows.placeholder(bar.BarState(tab="scene")), tokens.PLACEHOLDER_FIRST)


# The six states of the approved tab design: (tab, has_scene, thing) -> (line, placeholder).
TAB_STATES = {
    "scene-empty": (("scene", False, ""), "Build the whole scene and its camera move. Start here.",
                    "Describe the scene you imagine…"),
    "scene-built": (("scene", True, ""), "Change anything in the scene: light, layout, colours, the camera.",
                    "Ask for a change: warmer light, a bigger window…"),
    "assets-add": (("asset", True, ""), "Add one object to the scene. Select an object to change it "
                   "instead.", "Add an object: a wooden barrel by the door…"),
    "assets-change": (("asset", True, "Barrel"), "Changing Barrel. Click empty space to add a new object.",
                      "Change Barrel: make it walnut, move it to the window…"),
    "characters-add": (("character", True, ""), "Add a person or an animal, built at full detail. "
                       "Select one to change it.", "Add a character: a ginger cat asleep by the fire…"),
    "characters-change": (("character", True, "Ginger cat"), "Changing Ginger cat. Click empty space "
                          "to add a new character.", "Change Ginger cat: make it bigger, let it sleep…"),
}


class TabLineRenderTest(unittest.TestCase):
    def state(self, key, **kw):
        (tab, has_scene, thing), _line, _hint = TAB_STATES[key]
        return bar.BarState(mode="idle", field=field(), tab=tab, has_scene=has_scene, thing=thing,
                            quality_label="Prototype", settings=True, **kw)

    def test_each_state_has_its_line_and_placeholder(self):
        from eachlabs.ui import tab_row

        for key, (_args, line, hint) in TAB_STATES.items():
            with self.subTest(key):
                state = self.state(key)
                self.assertEqual(tab_row.tab_line(state), line)
                self.assertEqual(bar.placeholder(state), hint)

    def test_scene_ignores_the_selection_and_no_tab_has_no_line(self):
        from eachlabs.ui import tab_row

        state = bar.BarState(tab="scene", has_scene=True, thing="Barrel")
        self.assertEqual(tab_row.tab_line(state), tokens.TAB_LINE_SCENE_NEXT)
        self.assertEqual(tab_row.chip_label(state), "")
        self.assertIsNone(tab_row.tab_line(bar.BarState()))

    def test_every_state_fits_from_the_narrowest_bar_up_and_the_line_wraps_to_two_lines(self):
        from eachlabs.ui import tab_row

        os.makedirs(SNAPSHOTS, exist_ok=True)
        for key in TAB_STATES:
            for width in (640, 360, 240):
                with self.subTest(key=key, width=width):
                    state = self.state(key)
                    frame = bar.render(state, width, 2)
                    if width in (640, 240):
                        bar.save_png(frame, os.path.join(SNAPSHOTS, "tabline-%s-%d.png" % (key, width)))
                    inner = width - tokens.PAD_LEFT - tokens.PAD_RIGHT
                    lines, chip = tab_row.line_layout(state, inner)
                    self.assertLessEqual(len(lines), 2)
                    self.assertTrue(all(fonts.measure(t, "regular", tokens.TAB_LINE_SIZE) <= inner for t in lines))
                    self.assertFalse(lines[0].startswith(dict(tokens.TABS)[state.tab]))  # the tab names itself
                    self.assertEqual(chip is not None, bool(state.thing))
                    controls = {k: v for k, v in frame.hits.items() if k != "bar"}
                    for name, rect in controls.items():
                        self.assertTrue(inside(rect, frame.bar_rect), name)
                    keys = sorted(controls)
                    for i, a in enumerate(keys):
                        for b in keys[i + 1:]:
                            self.assertFalse(overlaps(controls[a], controls[b]), (a, b))

    def test_the_chip_sits_between_the_tabs_and_the_field_and_its_hit_wins(self):
        from eachlabs.ui import bar_state

        for key in ("assets-change", "characters-change"):
            for width in (640, 240):
                with self.subTest(key=key, width=width):
                    frame = bar.render(self.state(key), width, 1)
                    x, y, w, h = frame.hits[tokens.TAB_CLEAR]
                    self.assertGreater(y, frame.hits["tab_scene"][1] + frame.hits["tab_scene"][3])
                    self.assertLess(y + h, frame.hits["field"][1])
                    self.assertEqual(bar_state.hit(frame.hits, x + w - 4, y + h / 2), tokens.TAB_CLEAR)
        for key in ("assets-add", "characters-add", "scene-built"):
            self.assertNotIn(tokens.TAB_CLEAR, bar.render(self.state(key), 640, 1).hits)

    def test_a_long_name_is_cut_in_the_chip_and_the_chip_has_no_hit_while_a_run_goes(self):
        from eachlabs.ui import tab_row

        state = self.state("assets-change")
        state.thing = "A very long name of a wooden barrel " * 4
        self.assertLessEqual(fonts.measure(tab_row.chip_label(state), "medium", tokens.TAB_CHIP_SIZE),
                             tokens.TAB_CHIP_NAME_MAX)
        self.assertTrue(tab_row.chip_label(state).endswith("…"))
        frame = bar.render(state, 240, 1)
        self.assertIn(tokens.TAB_CLEAR, frame.hits)
        state.tabs_enabled = False
        self.assertNotIn(tokens.TAB_CLEAR, bar.render(state, 240, 1).hits)


class SettingsButtonRenderTest(unittest.TestCase):
    def test_sits_between_the_pill_and_send_and_fits_at_every_width(self):
        os.makedirs(SNAPSHOTS, exist_ok=True)
        state = bar.BarState(mode="idle", field=field(), quality_label="Prototype", settings=True, tab="scene")
        for width in (640, 240):
            with self.subTest(width=width):
                frame = bar.render(state, width, 2)
                bar.save_png(frame, os.path.join(SNAPSHOTS, "settings-%d.png" % width))
                sx, sy, sw, sh = frame.hits["settings"]
                self.assertTrue(inside(frame.hits["settings"], frame.bar_rect))
                self.assertLess(sx + sw, frame.hits["send"][0])
                self.assertLessEqual(frame.hits["field"][0] + frame.hits["field"][2], sx)
                if width == 640:
                    self.assertLess(frame.hits["quality"][0] + frame.hits["quality"][2], sx)
                controls = {k: v for k, v in frame.hits.items() if k != "bar"}
                keys = sorted(controls)
                for i, a in enumerate(keys):
                    for b in keys[i + 1:]:
                        self.assertFalse(overlaps(controls[a], controls[b]), (a, b))

    def test_the_bar_always_offers_it(self):
        from eachlabs.ui import bar_state
        from eachlabs.ui.text_field import TextField

        c = types.SimpleNamespace(prompt="", stages={}, status="idle", thinking_since=None, round=0, total=20, tools=[],
                                  reply="", error="", cost=None, cost_text="", running=True, failed_stage=None,
                                  history=[], changed=[], code_check_on=False, code_check_state="",
                                  code_check_reason="", attempt="", code_steps=[], unchanged=False)
        self.assertTrue(bar_state.from_chat(c, TextField([], mac=False), False, 1.0).settings)

