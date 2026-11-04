import threading
import unittest

from eachlabs import detail_judge
from eachlabs.chat.detail_pick import Settings, Target


class Fake:
    def __init__(self, letter):
        self.calls, self.letter, self.stashes = [], letter, 0

    def execute(self, name, args):
        self.calls.append((name, dict(args)))
        if name == "candidate_stash":
            self.stashes += 1
            return {"key": "k%d" % self.stashes}
        if name == "candidate_shot":
            return {"images": ["data:%d" % self.stashes]}
        return {}

    def quick(self, messages, tools):
        return {"choices": [{"message": {"content": "%s. better" % self.letter}}]}


def run(letter):
    fake, built = Fake(letter), []

    def once():
        built.append(1)
        return [{"stage": "detail"}], "", 1.0
    result = detail_judge.improve_best(Target("Cabin"), "a cabin", fake.quick, fake.execute, threading.Event(),
                                       Settings(candidates=2), once, lambda v: v)
    return fake, built, result


class ImproveBest(unittest.TestCase):
    def test_no_pictures_still_name_the_object_and_the_version_kept(self):
        class NoShots(Fake):
            def execute(self, name, args):
                found = super().execute(name, args)
                return {"images": []} if name == "candidate_shot" else found
        fake = NoShots("A")
        _steps, _line, _seconds, verdict = detail_judge.improve_best(
            Target("Cabin"), "a cabin", fake.quick, fake.execute, threading.Event(), Settings(candidates=2),
            lambda: ([{"stage": "detail"}], "", 1.0), lambda v: v)
        self.assertEqual((verdict["object"], verdict["kept"], verdict["error"]), ("Cabin", 2, "no pictures to compare"))

    def test_the_first_version_wins_and_comes_back(self):
        fake, built, (steps, _line, seconds, verdict) = run("A")
        self.assertEqual(len(built), 2)
        self.assertEqual(seconds, 2.0)
        self.assertEqual(verdict["kept"], 1)
        names = [c[0] for c in fake.calls]
        # start stashed, version 1 built, shot, stashed; start restored, version 2, shot, stashed; version 1 back
        self.assertEqual(names, ["candidate_stash", "candidate_shot", "candidate_stash", "candidate_restore",
                                 "candidate_shot", "candidate_stash", "candidate_restore", "candidate_drop"])
        self.assertEqual(fake.calls[3][1]["key"], "k1")  # the start
        self.assertEqual(fake.calls[6][1]["key"], "k2")  # version 1
        self.assertEqual(fake.calls[-1][1]["keys"], ["k1", "k2", "k3"])

    def test_the_last_version_wins_and_stays(self):
        fake, _built, (_steps, _line, _seconds, verdict) = run("B")
        self.assertEqual(verdict["kept"], 2)
        self.assertEqual([c[0] for c in fake.calls].count("candidate_restore"), 1)  # only to rebuild from the start

    def test_an_empty_second_build_puts_the_first_version_back(self):
        fake, results = Fake("B"), iter([([{"stage": "detail"}], "", 1.0), ([], "", 0.0)])
        steps, _line, _seconds, verdict = detail_judge.improve_best(
            Target("Boat"), "a harbour", fake.quick, fake.execute, threading.Event(), Settings(candidates=2),
            lambda: next(results), lambda v: v)
        restores = [c[1]["key"] for c in fake.calls if c[0] == "candidate_restore"]
        self.assertEqual(restores, ["k1", "k2"])  # the start for version 2, then version 1 back
        self.assertEqual(verdict["kept"], 1)
        self.assertEqual(len(steps), 1)
        self.assertEqual(fake.calls[-1][0], "candidate_drop")

    def test_a_failure_puts_the_first_version_back(self):
        fake = Fake("A")
        real = fake.execute

        def execute(name, args):
            if name == "candidate_shot" and fake.stashes == 2 and [c[0] for c in fake.calls].count("candidate_shot"):
                raise RuntimeError("render failed")
            return real(name, args)
        _steps, _line, _seconds, verdict = detail_judge.improve_best(
            Target("Boat"), "a harbour", fake.quick, execute, threading.Event(), Settings(candidates=2),
            lambda: ([{"stage": "detail"}], "", 1.0), lambda v: v)
        self.assertEqual(verdict["kept"], 1)
        self.assertEqual([c[1].get("key") for c in fake.calls if c[0] == "candidate_restore"][-1], "k2")

    def test_only_main_objects_and_only_with_pictures(self):
        from eachlabs.chat.pictures import Visual
        targets = [Target("A"), Target("B", level="medium"), Target("C"), Target("D")]
        self.assertEqual(detail_judge.eligible(targets, Settings(candidates=2), Visual()), {"A", "C"})
        self.assertEqual(detail_judge.eligible(targets, Settings(candidates=1), Visual()), set())
        self.assertEqual(detail_judge.eligible(targets, Settings(candidates=2), None), set())
        self.assertEqual(detail_judge.extra_rounds(targets, Settings(candidates=2, rounds=3), Visual()), 6)


if __name__ == "__main__":
    unittest.main()
