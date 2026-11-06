import types
import unittest

from eachlabs.ui import bar, bar_state, input_rows, tab_row, tokens, video_card, video_tab, video_texts as V
from eachlabs.ui.text_field import TextField

CAMERAS = [("Island flora camera", "camera move · 9 s", True), ("Still camera", "still", False)]


def shot(**kw):
    values = dict(cameras=list(CAMERAS), camera="Island flora camera", seconds=9, longest=9, move_seconds=9,
                  photos={4: 1, 5: 1, 6: 1, 8: 1, 9: 1})
    values.update(kw)
    return video_tab.Shot(**values)


def chat(**kw):
    values = dict(prompt="", stages={}, status="idle", thinking_since=None, round=0, total=20, tools=[], reply="",
                  error="", cost=None, cost_text="", running=False, failed_stage=None, history=[], changed=[],
                  code_check_on=False, code_check_state="", code_check_reason="", attempt="", code_steps=[],
                  unchanged=False, video="", video_job="", video_message="", video_seconds=0, video_progress=0,
                  video_stage="", video_info={})
    values.update(kw)
    return types.SimpleNamespace(**values)


def tab_state(c=None, s=None, now=100.0, **kw):
    return bar_state.from_chat(c or chat(), TextField([], mac=False), False, now, tab="video", quality="PROTOTYPE",
                               shot=s or shot(), **kw)


class TabTest(unittest.TestCase):
    def test_video_is_the_fourth_tab(self):
        self.assertEqual([t for t, _label in tokens.TABS], ["scene", "asset", "character", "video"])
        self.assertEqual(tokens.TAB_HITS[3], "tab_video")

    def test_each_tab_has_its_line_and_placeholder(self):
        cases = {"scene": tokens.PLACEHOLDER_FIRST, "asset": tokens.PLACEHOLDER_ASSET,
                 "character": tokens.PLACEHOLDER_CHARACTER, "video": V.PLACEHOLDER}
        for tab, hint in cases.items():
            with self.subTest(tab):
                s = bar.BarState(tab=tab)
                self.assertEqual(input_rows.placeholder(s), hint)
                self.assertTrue(tab_row.tab_line(s))
        self.assertEqual(tab_row.tab_line(bar.BarState(tab="video")), V.TAB_LINE)

    def test_the_video_tab_draws_from_the_shot_and_ignores_the_chat_card(self):
        s = tab_state(chat(status="done", reply="A room.", cost_text="34 ROUNDS"))
        self.assertEqual((s.mode, s.tab, s.reply, s.video_card), ("video", "video", "", ""))
        self.assertTrue(s.send_enabled)
        self.assertEqual(s.quality_label, "Prototype")  # the quality pill stays on the input row

    def test_a_chat_run_shows_on_the_video_tab_as_on_the_others(self):
        s = tab_state(chat(running=True, status="running", stages={"layout": "active"}, round=1))
        self.assertEqual(s.mode, "building")
        self.assertFalse(s.tabs_enabled)

    def test_no_shot_draws_the_usual_bar(self):
        self.assertNotEqual(bar_state.from_chat(chat(), TextField([], mac=False), False, 1.0, tab="video").mode,
                            "video")


class SettingsTest(unittest.TestCase):
    def test_defaults(self):
        s = video_tab.Shot()
        self.assertEqual((s.aspect, s.resolution), ("16:9", "480p"))

    def test_chips_and_price(self):
        s = shot()
        self.assertEqual(video_tab.chips(s), [("vchip_camera", "Island flora camera"), ("vchip_aspect", "16:9"),
                                              ("vchip_resolution", "480p"), ("vchip_seconds", "9 s"),
                                              ("vchip_model", "Seedance 2.5")])
        self.assertEqual(video_tab.price_text(s), "≈ $1.44")  # 9 s × $0.155 + one photo
        self.assertEqual(video_tab.price_text(shot(photos={})), V.COUNTING)

    def test_menus_list_their_items_with_prices(self):
        s = shot(menu="resolution")
        title, items = video_tab.menu(s)
        self.assertEqual(title, "Resolution · 9 s · total")
        self.assertEqual(items, [("480p", "draft · $1.44", True), ("720p", "$2.79", False),
                                 ("1080p", "$6.30", False)])
        title, items = video_tab.menu(shot(menu="seconds"))
        self.assertEqual(title, "Duration · 480p · total")
        self.assertEqual([n for n, _h, _c in items], ["4 s", "5 s", "6 s", "8 s", "9 s"])
        self.assertEqual(items[-1], ("9 s", "whole move · $1.44", True))
        self.assertEqual(items[0][1], "$0.67")
        _title, items = video_tab.menu(shot(menu="camera"))
        self.assertEqual(items, [("Island flora camera", "camera move · 9 s", True), ("Still camera", "still", False)])
        _title, items = video_tab.menu(shot(menu="aspect"))
        self.assertEqual(items[0], ("16:9", "wide", True))
        self.assertEqual(len(items), 6)
        _title, items = video_tab.menu(shot(menu="model"))
        self.assertEqual(items, [("Seedance 2.5", V.MODEL_HINT, True)])
        self.assertEqual(video_tab.menu(shot()), ("", []))

    def test_a_menu_item_picks_its_value(self):
        self.assertEqual(video_tab.picked(shot(menu="resolution"), "vmenu_1"), ("resolution", "720p"))
        self.assertEqual(video_tab.picked(shot(menu="seconds"), "vmenu_0"), ("seconds", 4))
        self.assertEqual(video_tab.picked(shot(menu="camera"), "vmenu_1"), ("camera", "Still camera"))
        self.assertIsNone(video_tab.picked(shot(menu="model"), "vmenu_3"))
        self.assertIsNone(video_tab.picked(shot(menu="aspect"), "send"))

    def test_a_still_camera_lists_every_usual_length_up_to_15_s(self):
        s = shot(camera="Still camera", seconds=5, longest=15)
        self.assertEqual(video_tab.durations(s), [4, 5, 6, 8, 10, 12, 15])
        self.assertFalse(any("whole move" in h for _n, h, _c in video_tab.menu(
            video_tab.Shot(**dict(vars(s), menu="seconds")))[1]))

    def test_notes(self):
        self.assertEqual(video_tab.notes(shot()), [])
        self.assertEqual(video_tab.notes(shot(camera="Still camera")), [V.STILL])
        self.assertEqual(video_tab.notes(shot(move_seconds=22, longest=15, seconds=15)),
                         ["The move is 22 s; videos are up to 15 s, so it uses the first 15 s."])
        self.assertEqual(video_tab.notes(shot(camera="", cameras=[])), [V.NO_CAMERA])

    def test_no_camera_turns_send_off_with_the_reason(self):
        s = tab_state(s=shot(camera="", cameras=[]))
        self.assertFalse(s.send_enabled)
        self.assertEqual(s.send_tip, V.NO_CAMERA)
        self.assertEqual((s.video_chips, s.video_notes), ([], [V.NO_CAMERA]))
        busy = tab_state(chat(video="generating", video_job="j"))
        self.assertEqual((busy.send_enabled, busy.send_tip), (False, V.BUSY))

    def test_an_open_menu_shows_on_the_state(self):
        s = tab_state(s=shot(menu="resolution"))
        self.assertEqual((s.video_open_chip, s.video_menu_title), ("resolution", "Resolution · 9 s · total"))
        self.assertEqual(len(s.video_menu), 3)


class ConfirmTest(unittest.TestCase):
    def test_send_shows_the_confirm_card(self):
        s = tab_state(s=shot(confirm=True))
        self.assertEqual(s.video_card, "confirm")
        self.assertEqual(s.video_meta, "Total $1.44 · Video $1.40 · 1 photo $0.05")
        self.assertEqual(s.video_text, "Make a 9 s, 480p video through Island flora camera with Seedance 2.5. One "
                                       "photo of the scene sets the look. It may still be billed after Stop.")
        self.assertEqual(s.actions, ["video_make", "video_cancel"])
        self.assertEqual(s.labels["video_make"], "Make video · $1.44")
        self.assertIn("video_make", s.primary)

    def test_several_photos(self):
        meta, text, _label = video_tab.confirm(shot(photos={9: 3}))
        self.assertIn("3 photos", meta)
        self.assertIn("3 photos of the scene set the look.", text)

    def test_a_changed_scene_shows_the_new_price_and_says_so(self):
        s = tab_state(s=shot(confirm=True, changed=True, photos={9: 2}))
        self.assertEqual((s.video_card, s.video_error), ("confirm", V.CHANGED))
        self.assertEqual(s.labels["video_make"], "Make video · $1.49")
        self.assertEqual(tab_state(s=shot(confirm=True)).video_error, "")

    def test_no_confirm_while_counting_or_without_a_camera(self):
        self.assertIsNone(video_tab.confirm(shot(photos={})))
        self.assertEqual(tab_state(s=shot(confirm=True, camera="", cameras=[])).video_card, "")


def making(video, stage="", message="", **kw):
    values = dict(video=video, video_job="j1", video_stage=stage, video_message=message,
                  video_info={"seconds": 9, "photos": 1, "price": 1.44, "started": 59.0})
    values.update(kw)
    return chat(**values)


class CardTest(unittest.TestCase):
    def test_stage_chips_follow_the_job(self):
        cases = {
            ("rendering", "camera", ""): ["active", "todo", "todo", "todo", "todo"],
            ("rendering", "keys", ""): ["done", "active", "todo", "todo", "todo"],
            ("photos", "look", "1 of 1"): ["done", "done", "active", "todo", "todo"],
            ("generating", "video", ""): ["done", "done", "done", "active", "todo"],
            ("generating", "sequencer", ""): ["done", "done", "done", "done", "active"],
            ("done", "sequencer", ""): ["done"] * 5,
            ("failed", "look", "Photo 1 failed: refused"): ["done", "done", "failed", "todo", "todo"],
            ("stopped", "video", ""): ["done", "done", "done", "cancelled", "todo"],
        }
        for (video, stage, message), states in cases.items():
            with self.subTest(video=video, stage=stage):
                self.assertEqual(list(video_card.chips(making(video, stage, message)).values()), states)
        self.assertEqual(list(video_card.chips(making("photos", "look", "1 of 1"))),
                         ["Camera move", "Key frames", "Look 1/1", "Video", "Sequencer"])

    def test_progress(self):
        s = tab_state(making("photos", "look", "1 of 1"))
        self.assertEqual(s.video_card, "progress")
        self.assertEqual(s.video_meta, "0:41 · $1.44")
        self.assertEqual(s.video_text, "Turning the key frame into a photo of the real scene. Next, Seedance films "
                                       "the camera move (about 4 min).")
        self.assertEqual(s.video_line, "Making the look: photo 1 of 1…")
        self.assertEqual(s.actions, ["video_stop"])
        self.assertEqual(video_card.live(making("rendering", "camera", video_progress=40)),
                         "Recording the camera move… 40%")
        self.assertEqual(video_card.live(making("generating", "video", video_seconds=80)),
                         "Seedance 2.5 is making it… 1:20")
        self.assertEqual(video_card.live(making("photos", "look")), V.LIVE["upload"])
        self.assertIn("about 4 min", video_card.sentence(making("generating", "video")))
        self.assertIn("20–60 s per photo", video_card.sentence(making("rendering", "keys")))

    def test_stop_asks_first_inline(self):
        s = tab_state(making("generating", "video"), shot(stop_ask=True))
        self.assertEqual((s.video_ask, s.actions), (V.STOP_ASK, ["video_stop_yes", "video_stop_no"]))
        s = tab_state(making("rendering", "camera"), shot(stop_ask=True))
        self.assertEqual(s.video_ask, V.STOP_ASK_FREE)  # nothing sent yet

    def test_ready(self):
        s = tab_state(making("done", "sequencer", video_info={"seconds": 9, "price": 1.44, "started": 0.0,
                                                               "ended": 230.0}))
        self.assertEqual(s.video_card, "ready")
        self.assertEqual(s.video_meta, "4 min · $1.44")
        self.assertEqual(s.video_text, "Your 9 s video is in the Video Sequencer, next to the scene it was made from.")
        self.assertEqual(s.actions, ["video_open", "video_file", "video_another"])
        self.assertIn("video_open", s.primary)

    def test_failed(self):
        s = tab_state(making("failed", "look", "Photo 1 failed: the photo was refused"))
        self.assertEqual(s.video_card, "failed")
        self.assertEqual(s.video_error, "The look failed: photo 1 failed: the photo was refused.")
        self.assertEqual(s.actions, ["video_retry", "video_edit"])
        early = tab_state(making("failed", "keys", "Eevee could not render"))
        self.assertTrue(early.video_error.endswith(V.NOTHING_MORE), early.video_error)
        self.assertEqual(early.video_meta, "Failed · $0.00")
        refused = tab_state(making("failed", "", "Add your Eachlabs API key to start", video_job=""))
        self.assertEqual(refused.actions, ["video_edit"])  # nothing to retry: Send starts it

    def test_stopped(self):
        s = tab_state(making("stopped", "video"))
        self.assertEqual((s.video_card, s.video_error, s.video_meta), ("stopped", V.STOPPED, "Stopped"))
        self.assertEqual(s.actions, ["video_retry", "video_edit"])

    def test_make_another_hides_the_card(self):
        self.assertEqual(tab_state(making("done", "sequencer"), shot(card=False)).video_card, "")


class RenderTest(unittest.TestCase):
    def inside(self, rect, outer):
        return (rect[0] >= outer[0] and rect[1] >= outer[1] and rect[0] + rect[2] <= outer[0] + outer[2]
                and rect[1] + rect[3] <= outer[1] + outer[3])

    def test_every_state_draws_inside_the_bar_at_every_width(self):
        states = {
            "settings": tab_state(),
            "menu": tab_state(s=shot(menu="resolution")),
            "confirm": tab_state(s=shot(confirm=True)),
            "progress": tab_state(making("photos", "look", "1 of 1")),
            "ask": tab_state(making("generating", "video"), shot(stop_ask=True)),
            "ready": tab_state(making("done", "sequencer")),
            "failed": tab_state(making("failed", "look", "Photo 1 failed: refused")),
            "no camera": tab_state(s=shot(camera="", cameras=[])),
            "still": tab_state(s=shot(camera="Still camera", seconds=5, longest=15)),
        }
        for name, s in states.items():
            for width in (640, 240):
                with self.subTest(name, width=width):
                    frame = bar.render(s, width, 1)
                    for hit_id, rect in frame.hits.items():
                        self.assertTrue(self.inside(rect, frame.bar_rect), (hit_id, rect))
                    for action in s.actions:
                        self.assertIn(action, frame.hits)
        frame = bar.render(states["settings"], 640, 1)
        self.assertTrue(set(V.CHIP_HITS) <= set(frame.hits))
        self.assertIn(V.SEND_OFF, bar.render(states["no camera"], 640, 1).hits)
        self.assertEqual([h for h in V.MENU_HITS if h in bar.render(states["menu"], 640, 1).hits], list(V.MENU_HITS[:3]))
        for hit_id in frame.hits:
            self.assertEqual(bar_state.hit(frame.hits, frame.hits[hit_id][0] + 1, frame.hits[hit_id][1] + 1) is not None,
                             True)


if __name__ == "__main__":
    unittest.main()
