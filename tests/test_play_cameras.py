"""Play through a camera: which cameras, in what order, their hints, and the bar's Play button and camera menu."""

import dataclasses
import types
import unittest

from eachlabs.chat import play_cameras
from eachlabs.ui import bar, bar_state, tokens
from eachlabs.ui.text_field import TextField

MOVE = [[(1.0, 0.0), (120.0, 8.0)], [(1.0, 2.0), (120.0, 2.0)]]  # x moves over the range, z stays
STILL_KEYS = [[(1.0, 3.0), (120.0, 3.0)]]
RANGE = (1, 120)


def done_state(**kw):
    stages = {s: "done" for s in ("layout", "materials", "light", "camera", "check")}
    values = dict(mode="done", field=TextField([], mac=False), stages=stages, reply="Built a street.",
                  cost_text="9 ROUNDS · $0.004", actions=["play", "frame", "final", "undo", "new"])
    values.update(kw)
    return bar.BarState(**values)


def inside(inner, outer):
    ix, iy, iw, ih = inner
    ox, oy, ow, oh = outer
    return ox <= ix and oy <= iy and ix + iw <= ox + ow and iy + ih <= oy + oh


def overlaps(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


class CameraListTest(unittest.TestCase):
    def test_the_chats_camera_comes_first_then_the_others_by_name(self):
        names = ["Zoom cam", "Camera", "Chat camera", "aerial"]
        self.assertEqual(play_cameras.order(names, "Chat camera", "Camera"),
                         ["Chat camera", "aerial", "Camera", "Zoom cam"])

    def test_without_the_chats_camera_the_scene_camera_comes_first(self):
        self.assertEqual(play_cameras.order(["B", "A", "Scene"], "", "Scene"), ["Scene", "A", "B"])
        self.assertEqual(play_cameras.order(["B", "A"], "Gone", "Also gone"), ["A", "B"])

    def test_the_chosen_camera_stays_while_it_exists(self):
        names = ["Camera", "Chat camera"]
        self.assertEqual(play_cameras.chosen(names, "Camera", "Chat camera", "Camera"), "Camera")
        self.assertEqual(play_cameras.chosen(names, "Deleted", "Chat camera", "Camera"), "Chat camera")
        self.assertEqual(play_cameras.chosen(names, "", "", "Camera"), "Camera")
        self.assertEqual(play_cameras.chosen([], "Camera", "", ""), "")

    def test_a_camera_that_moves_over_the_range_names_its_length(self):
        self.assertTrue(play_cameras.moves(MOVE, RANGE))
        self.assertEqual(play_cameras.hint(MOVE, RANGE, 24, True), "the chat's camera move · 5 s")
        self.assertEqual(play_cameras.hint(MOVE, (1, 60), 24, False), "camera move · 2.5 s")

    def test_a_camera_without_a_change_in_the_range_is_still(self):
        self.assertFalse(play_cameras.moves([], RANGE))
        self.assertFalse(play_cameras.moves(STILL_KEYS, RANGE))
        self.assertFalse(play_cameras.moves([[(200.0, 0.0), (300.0, 5.0)]], RANGE))  # moves after the range
        self.assertTrue(play_cameras.moves([[(100.0, 0.0), (300.0, 5.0)]], RANGE))  # starts moving inside it
        self.assertEqual(play_cameras.hint(STILL_KEYS, RANGE, 24, True), "still")

    def test_menu_marks_the_chosen_camera(self):
        items = play_cameras.menu({"Camera": [], "Chat camera": MOVE}, "", "Chat camera", "Camera", RANGE, 24)
        self.assertEqual(items, [("Chat camera", "the chat's camera move · 5 s", True), ("Camera", "still", False)])
        items = play_cameras.menu({"Camera": [], "Chat camera": MOVE}, "Camera", "Chat camera", "Camera", RANGE, 24)
        self.assertEqual([chosen for _n, _h, chosen in items], [False, True])


CAMERAS = [("Chat camera", "the chat's camera move · 5 s", True), ("Camera", "still", False)]


def chat(**kw):
    values = dict(prompt="", stages={s: "done" for s in ("layout", "camera")}, status="done", thinking_since=None,
                  round=0, total=20, tools=[], reply="Built it.", error="", cost=None, cost_text="", running=False,
                  failed_stage=None, history=[], changed=["layout", "camera"], code_check_on=False,
                  code_check_state="", code_check_reason="", attempt="", code_steps=[], unchanged=False)
    values.update(kw)
    return types.SimpleNamespace(**values)


class PlayStateTest(unittest.TestCase):
    def state(self, c=None, **kw):
        return bar_state.from_chat(c or chat(), TextField([], mac=False), False, 100.0, **kw)

    def test_play_names_the_chosen_camera(self):
        s = self.state(cameras=CAMERAS)
        self.assertEqual((s.play_camera, s.playing, s.camera_menu), ("Chat camera", False, []))
        self.assertEqual(bar.play_label(s), "Play as Chat camera")

    def test_the_open_menu_lists_every_camera(self):
        s = self.state(cameras=CAMERAS, camera_menu=True)
        self.assertEqual(s.camera_menu, CAMERAS)
        self.assertEqual(bar_state.camera_picked("camera_1", s.camera_menu), "Camera")
        self.assertIsNone(bar_state.camera_picked("camera_5", s.camera_menu))
        self.assertIsNone(bar_state.camera_picked("play", s.camera_menu))

    def test_while_playing_the_button_is_pause_without_a_menu(self):
        s = self.state(cameras=CAMERAS, camera_menu=True, playing=True)
        self.assertEqual((s.playing, s.camera_menu, bar.play_label(s)), (True, [], "Pause"))

    def test_no_camera_is_plain_play(self):
        s = self.state(cameras=[], camera_menu=True)
        self.assertEqual((s.play_camera, s.camera_menu, bar.play_label(s)), ("", [], "Play"))

    def test_the_quality_menu_closes_the_camera_menu(self):
        s = self.state(cameras=CAMERAS, camera_menu=True, quality="PROTOTYPE", menu=True)
        self.assertEqual((bool(s.quality_menu), s.camera_menu), (True, []))

    def test_states_without_play_have_no_camera(self):
        s = self.state(chat(status="cancelled", reply=""), cameras=CAMERAS, camera_menu=True)
        self.assertEqual((s.play_camera, s.camera_menu), ("", []))

    def test_menu_hits_come_before_the_rest(self):
        for name in tokens.CAMERA_HITS + ("play_menu", "play"):
            self.assertIn(name, bar_state._HIT_ORDER)


class PlayRenderTest(unittest.TestCase):
    def check_controls(self, frame):
        controls = {k: v for k, v in frame.hits.items() if k != "bar"}
        for key, rect in controls.items():
            self.assertTrue(inside(rect, frame.bar_rect), key)
        keys = sorted(controls)
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                self.assertFalse(overlaps(controls[a], controls[b]), (a, b))

    def test_split_button_at_both_widths(self):
        for width in (640, 240):
            for name in ("Chat camera", "A camera with a very long name that cannot fit on the button at all"):
                with self.subTest(width=width, name=name):
                    frame = bar.render(done_state(play_camera=name), width, 2)
                    self.assertIn("play", frame.hits)
                    self.assertIn("play_menu", frame.hits)
                    px, py, pw, ph = frame.hits["play"]
                    mx, my, mw, mh = frame.hits["play_menu"]
                    self.assertEqual((px + pw, py, ph), (mx, my, mh))  # the chevron part right of the main part
                    self.check_controls(frame)

    def test_menu_lists_cameras_above_the_actions(self):
        menu = CAMERAS + [("Camera %d" % i, "still", False) for i in range(12)]
        for width in (640, 240):
            with self.subTest(width=width):
                frame = bar.render(done_state(play_camera="Chat camera", camera_menu=menu), width, 2)
                self.assertEqual({h for h in frame.hits if h.startswith("camera_")}, set(tokens.CAMERA_HITS))
                tops = [frame.hits[h][1] for h in tokens.CAMERA_HITS]
                self.assertEqual(tops, sorted(tops))
                self.assertLess(frame.hits[tokens.CAMERA_HITS[-1]][1], frame.hits["play"][1])
                self.assertIn("play_menu", frame.hits)  # a click on the chevron closes it again
                self.check_controls(frame)
        closed = bar.render(done_state(play_camera="Chat camera"), 640, 1)
        opened = bar.render(done_state(play_camera="Chat camera", camera_menu=CAMERAS), 640, 1)
        self.assertGreater(opened.bar_rect[3], closed.bar_rect[3])
        self.assertNotEqual(opened.rgba, bar.render(done_state(play_camera="Chat camera", camera_menu=[
            (n, h, not c) for n, h, c in CAMERAS]), 640, 1).rgba)  # the chosen item is marked

    def test_pause_while_playing_has_no_chevron(self):
        for width in (640, 240):
            with self.subTest(width=width):
                playing = bar.render(done_state(play_camera="Chat camera", playing=True), width, 2)
                self.assertIn("play", playing.hits)
                self.assertNotIn("play_menu", playing.hits)
                self.check_controls(playing)
                still = bar.render(done_state(play_camera="Chat camera"), width, 2)
                self.assertNotEqual(playing.rgba, still.rgba)

    def test_no_camera_is_plain_play(self):
        state = done_state()
        frame = bar.render(state, 640, 2)
        self.assertIn("play", frame.hits)
        self.assertNotIn("play_menu", frame.hits)
        self.assertLess(frame.hits["play"][2], bar.render(dataclasses.replace(state, play_camera="Camera"),
                                                          640, 2).hits["play"][2])


if __name__ == "__main__":
    unittest.main()
