import json
import threading
import unittest

from eachlabs.chat import review

NAMES = ["Spiral ladder", "Tree house", "Oak tree"]


def problem(thing, what="The ladder does not reach the door.", fix="Extend the ladder up to the door sill."):
    return {"thing": thing, "what": what, "fix": fix}


def reply(*problems, **extra):
    return json.dumps(dict({"matches": False, "missing": [], "problems": list(problems)}, **extra))


class Parse(unittest.TestCase):
    def test_valid_reply_keeps_its_problems(self):
        kept = review.parse(reply(problem("Spiral ladder")), NAMES)
        self.assertEqual(kept, [problem("Spiral ladder")])

    def test_fenced_json_is_read(self):
        self.assertEqual(len(review.parse("```json\n%s\n```" % reply(problem("Oak tree")), NAMES)), 1)

    def test_invalid_json_is_no_review(self):
        for text in ("The ladder is too short.", "", None, "[1, 2]", '{"problems": "none"}', '{"matches": true}'):
            self.assertEqual(review.parse(text, NAMES), [], text)

    def test_unknown_names_are_dropped(self):
        kept = review.parse(reply(problem("Ladder"), problem("spiral ladder"), problem("Tree house")), NAMES)
        self.assertEqual([p["thing"] for p in kept], ["Tree house"])
        self.assertEqual(review.parse(reply(problem("Ladder")), NAMES), [])

    def test_fixes_that_remove_something_are_dropped(self):
        for fix in ("Remove the ladder.", "Delete the extra steps.", "Drop the second trunk.",
                    "Get rid of the floating board.", "Erase the old treads.", "Removing it solves it."):
            self.assertEqual(review.parse(reply(problem("Spiral ladder", fix=fix)), NAMES), [], fix)
        self.assertEqual(len(review.parse(reply(problem("Spiral ladder", fix="Move the treads out of the trunk.")),
                                          NAMES)), 1)

    def test_more_than_three_are_cut(self):
        many = [problem(n, what="Problem %d." % i) for i, n in enumerate(NAMES * 2)]
        kept = review.parse(reply(*many), NAMES)
        self.assertEqual([p["what"] for p in kept], ["Problem 0.", "Problem 1.", "Problem 2."])

    def test_empty_or_partial_entries_are_dropped(self):
        kept = review.parse(reply(problem("Oak tree", what=""), problem("Oak tree", fix=" "), "Oak tree",
                                  problem("Oak tree"), problem("Oak tree")), NAMES)
        self.assertEqual(kept, [problem("Oak tree")])

    def test_second_look(self):
        self.assertEqual(review.parse_again('{"solved": [true, false], "worse": false}', 2), ([True, False], False))
        self.assertEqual(review.parse_again('{"solved": [true], "worse": true}', 2), ([True, False], True))
        self.assertEqual(review.parse_again('{"solved": ["yes"], "worse": "yes"}', 1), ([False], False))
        self.assertIsNone(review.parse_again("solved", 1))
        self.assertIsNone(review.parse_again('{"worse": true}', 1))


class Messages(unittest.TestCase):
    def test_review_call_has_the_request_things_and_pictures(self):
        sent = review.messages("a tree house  with a spiral ladder", ["a forest"], ["Oak tree | kind: tree"],
                               ["data:1", "data:2", "data:3", "data:4"])
        self.assertEqual(sent[0]["content"], review.text.SYSTEM)
        parts = sent[1]["content"]
        self.assertIn("a tree house with a spiral ladder", parts[0]["text"])
        self.assertIn("- a forest", parts[0]["text"])
        self.assertIn("Oak tree | kind: tree", parts[0]["text"])
        self.assertEqual([p["image_url"]["url"] for p in parts[1:]], ["data:1", "data:2", "data:3", "data:4"])

    def test_fix_text_carries_each_problem(self):
        said = review.fix_text([problem("Spiral ladder")])
        self.assertIn("1. Spiral ladder: The ladder does not reach the door. Fix: Extend the ladder", said)
        self.assertIn("never by removing", said)

    def test_second_look_shows_before_and_after(self):
        parts = review.again_messages([problem("Oak tree")], ["data:b"], ["data:a"])[1]["content"]
        self.assertEqual([p.get("text") or p["image_url"]["url"] for p in parts][1:],
                         [review.text.BEFORE, "data:b", review.text.AFTER, "data:a"])


class DoneLine(unittest.TestCase):
    def test_fixed_and_not_fixed(self):
        treads = problem("Spiral ladder", what="The spiral ladder's treads were inside the trunk.")
        door = problem("Tree house")
        self.assertEqual(review.done_line([treads], [True]),
                         "Review: the spiral ladder's treads were inside the trunk — fixed.")
        self.assertEqual(review.done_line([door], [False]), "Review: the ladder does not reach the door (not fixed).")

    def test_two_then_and_more(self):
        line = review.done_line([problem(n, what="Thing %d is off." % i) for i, n in enumerate(NAMES)],
                                [True, False, True])
        self.assertEqual(line, "Review: thing 0 is off — fixed; thing 1 is off (not fixed) and 1 more.")

    def test_nothing_found_says_nothing(self):
        self.assertEqual(review.done_line([]), "")

    def test_how_the_fix_ended_is_said(self):
        door = [problem("Tree house")]
        self.assertTrue(review.done_line(door, [True], review.UNDONE).endswith(
            "(not fixed). The fix made the scene worse, so it was undone."))
        self.assertTrue(review.done_line(door, None, review.NO_ROOM).endswith(
            "(not fixed). No rounds were left within your limit to fix it."))
        self.assertIn("could not be undone", review.done_line(door, [True], review.NOT_UNDONE))
        self.assertIn("Undo stage takes it back", review.done_line(door, [True], review.ASK_UNDO))
        self.assertEqual(review.done_line(door, None, review.UNCHECKED),
                         "Review: the ladder does not reach the door (fix tried).")

    def test_capitals_of_names_stay(self):
        self.assertTrue(review.done_line([problem("Oak tree", what="TV stand floats.")], [False]).startswith(
            "Review: TV stand floats"))
        self.assertTrue(review.done_line([problem("Tree house", what="Tree house has no door.")], [True]).startswith(
            "Review: Tree house has no door — fixed"))


class Estimate(unittest.TestCase):
    def test_counts_two_rounds_when_on(self):
        self.assertEqual(review.rounds(True), 2)
        self.assertEqual(review.rounds(False), 0)


class FakeExecute:
    def __init__(self, views):
        self.views, self.calls = list(views), []

    def __call__(self, name, args):
        self.calls.append(name)
        if name == "review_views":
            return self.views.pop(0)
        if name == "review_undo":
            return {"undone": True}
        return {}


def answer(text):
    return lambda messages, tools: {"choices": [{"message": {"content": text}}]}


class ReviewerCalls(unittest.TestCase):
    VIEWS = {"images": ["data:1", "data:2"], "names": NAMES, "things": NAMES}

    def reviewer(self, ask, quick=None, views=None):
        posted = []
        execute = FakeExecute(views if views is not None else [self.VIEWS, dict(self.VIEWS, images=["data:3"])])
        return review.Reviewer(ask, quick or ask, execute, threading.Event(), posted.append, "a tree house"), execute

    def test_find_then_again(self):
        found, execute = self.reviewer(answer(reply(problem("Spiral ladder"))),
                                       answer('{"solved": [true], "worse": false}'))
        kept = found.find()
        self.assertEqual(kept, [problem("Spiral ladder")])
        self.assertEqual(found.again(kept), ([True], False))
        self.assertEqual(found.undo(), review.UNDONE)
        self.assertEqual(execute.calls, ["review_views", "review_views", "review_undo"])

    def test_a_failed_call_or_render_is_no_review(self):
        def broken(messages, tools):
            raise RuntimeError("HTTP 502")
        self.assertEqual(self.reviewer(broken)[0].find(), [])
        self.assertEqual(self.reviewer(answer(reply(problem("Oak tree"))), views=[{"images": [], "names": NAMES}])[0]
                         .find(), [])

    def test_no_second_look_without_a_review(self):
        found, execute = self.reviewer(answer("not json"))
        self.assertEqual(found.find(), [])
        self.assertIsNone(found.again([problem("Oak tree")]))
        self.assertEqual(execute.calls, ["review_views"])


if __name__ == "__main__":
    unittest.main()
