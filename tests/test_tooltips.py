"""The bar's tooltips: a text for every control, and the card's layout. Needs ``skia-python`` for the card."""

import os
import tempfile
import unittest

import skia  # noqa: F401  (a missing Skia fails the suite instead of skipping it)

from eachlabs.ui import bar, bar_state, fonts, tokens, tooltip_card, tooltips

SNAPSHOTS = os.environ.get("EACHLABS_BAR_SNAPSHOTS") or os.path.join(tempfile.gettempdir(), "bar-snapshots")


class TextsTest(unittest.TestCase):
    def test_every_hit_id_the_bar_can_produce_has_a_tooltip(self):
        ids = set(bar_state._HIT_ORDER) - {"bar"}  # the bar's own background is no control
        ids |= set(tokens.QUALITY_HITS) | set(tokens.CAMERA_HITS) | set(tokens.TAB_HITS) | set(tokens.PLAN_HITS)
        ids |= {tokens.TAB_CLEAR}
        for hit_id in sorted(ids):
            with self.subTest(hit_id):
                self.assertTrue(tooltips.text(hit_id).strip())
        for hit_id in ("plan_item_0", "plan_item_%d" % (tokens.PLAN_ITEMS - 1)):  # chips by pattern
            self.assertEqual(tooltips.text(hit_id), tooltips.PLAN_ITEM)
        self.assertEqual(tooltips.text("bar"), "")
        self.assertEqual(len(tooltips.QUALITY_ITEMS), len(tokens.QUALITIES))

    def test_every_control_a_rendered_bar_shows_has_a_tooltip(self):
        from tests.test_bar_render import mockups

        for name, (state, _ids) in mockups().items():
            frame = bar.render(state, 640, 1)
            for hit_id in frame.hits:
                if hit_id != "bar":
                    self.assertTrue(tooltips.text(hit_id), (name, hit_id))

    def test_video_tooltips_exist(self):
        for hit_id in ("video_stop", "video_retry", "video_file"):
            self.assertTrue(tooltips.text(hit_id), hit_id)

    def test_the_approved_texts(self):
        self.assertEqual(tooltips.text("tab_scene"), "Scene: build a whole scene with its camera move, or change "
                         "anything in it. Start here with a description of the place you imagine.")
        self.assertEqual(tooltips.text("send"), "Send the prompt (Enter). Shift+Enter starts a new line.")
        self.assertEqual(tooltips.text("stop"), "Stop the run (Esc). What was built stays.")
        self.assertEqual(tooltips.text("quality"), "Prototype builds a quick draft for about $0.5. Final builds full "
                         "detail with the models set in Preferences, for about $5–10. Click to choose.")
        self.assertEqual(tooltips.text("widen"), "Run the change again, this time also allowed to change the named "
                         "objects.")


class CardTest(unittest.TestCase):
    LONG = tooltips.TEXTS["tab_scene"]

    def test_a_long_text_wraps_at_280_and_a_short_one_is_narrower(self):
        w, h = tooltip_card.size(self.LONG)
        self.assertLessEqual(w, tokens.TIP_MAX)
        self.assertGreater(h, tokens.TIP_LINE + 2 * tokens.TIP_PAD_Y)  # more than one line
        for line in tooltip_card.lines(self.LONG):
            self.assertLessEqual(fonts.measure(line, "regular", tokens.TIP_SIZE), tokens.TIP_MAX - 2 * tokens.TIP_PAD_X)
        short_w, short_h = tooltip_card.size(tooltips.TEXTS["play_menu"])
        self.assertLess(short_w, tokens.TIP_MAX)
        self.assertEqual(short_h, tokens.TIP_LINE + 2 * tokens.TIP_PAD_Y)

    def test_the_card_sits_above_its_control_inside_the_region(self):
        region = (800, 600)
        for scale in (1, 2):
            card = tooltip_card.render(self.LONG, scale)
            self.assertEqual((card.width, card.height), tuple(round(v * scale) for v in tooltip_card.size(self.LONG)))
            for control in ((10, 40, 30, 27), (400, 40, 36, 36), (780, 40, 20, 20)):  # left edge, middle, right edge
                with self.subTest(scale=scale, control=control):
                    x, y = tooltip_card.place((card.width, card.height), control, region, scale)
                    self.assertGreaterEqual(x, 0)
                    self.assertLessEqual(x + card.width, region[0])
                    self.assertLessEqual(y + card.height, region[1])
                    self.assertGreaterEqual(y, control[1] + control[3])  # above it: never over the control
        os.makedirs(SNAPSHOTS, exist_ok=True)
        bar.save_png(bar.Frame(rgba=card.rgba, width=card.width, height=card.height, hits={}, bar_rect=(0, 0, 0, 0)),
                     os.path.join(SNAPSHOTS, "tooltip-card.png"))

    def test_it_keeps_clear_of_the_sidebar_and_goes_below_without_room_above(self):
        card = tooltip_card.size(self.LONG)
        x, _y = tooltip_card.place(card, (700, 40, 30, 27), (800, 600), 1, left=0, right=200)
        self.assertLessEqual(x + card[0], 600)
        low = (400, 450, 36, 36)  # a control near the top of a short region
        x, y = tooltip_card.place(card, low, (800, 500), 1)
        self.assertLessEqual(y + card[1], low[1])  # below it, still not over it
        self.assertGreaterEqual(y, 0)


if __name__ == "__main__":
    unittest.main()
