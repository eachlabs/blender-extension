import unittest

from eachlabs.chat import detail_budget
from eachlabs.chat.detail_pick import Settings, Target


def targets():
    return [Target("house", "high"), Target("well", "medium"), Target("tree", "light"), Target("cart", "high")]


class StageRoundsTest(unittest.TestCase):
    def test_counts_close_ups_and_candidates(self):
        settings = Settings(rounds=3, light_rounds=1, candidates=2)
        # high 3+1, medium 2+1, light 1, high 3+1 = 12; candidates: two high objects, 3 more each
        self.assertEqual(detail_budget.stage_rounds(targets(), settings, True), 12 + 6)

    def test_no_pictures_means_no_close_ups_and_no_candidates(self):
        settings = Settings(rounds=3, light_rounds=1, candidates=2)
        self.assertEqual(detail_budget.stage_rounds(targets(), settings, False), 3 + 2 + 1 + 3)


class FitTest(unittest.TestCase):
    def test_everything_fits(self):
        settings = Settings(rounds=3, light_rounds=1, candidates=2)
        kept, dropped, candidates = detail_budget.fit(targets(), settings, True, 40)
        self.assertEqual([t.name for t in kept], ["house", "well", "tree", "cart"])
        self.assertEqual(dropped, [])
        self.assertTrue(candidates)

    def test_candidates_go_first(self):
        settings = Settings(rounds=3, light_rounds=1, candidates=2)
        kept, dropped, candidates = detail_budget.fit(targets(), settings, True, 12)
        self.assertEqual(len(kept), 4)
        self.assertEqual(dropped, [])
        self.assertFalse(candidates)

    def test_light_objects_go_before_main_ones(self):
        settings = Settings(rounds=3, light_rounds=1, candidates=1)
        kept, dropped, _ = detail_budget.fit(targets(), settings, True, 10)
        self.assertEqual([t.name for t in kept], ["house", "well"])
        self.assertEqual(dropped, ["cart", "tree"])

    def test_no_limit_keeps_all(self):
        kept, dropped, candidates = detail_budget.fit(targets(), Settings(), True, None)
        self.assertEqual(len(kept), 4)
        self.assertTrue(candidates)

    def test_zero_limit_drops_all(self):
        kept, dropped, _ = detail_budget.fit(targets(), Settings(), True, 0)
        self.assertEqual(kept, [])
        self.assertEqual(len(dropped), 4)


class EstimateTest(unittest.TestCase):
    def test_estimate_counts_main_light_and_candidates(self):
        settings = Settings(rounds=3, light_rounds=1, candidates=2, objects=6, light_objects=6)
        main = [("house", "high"), ("well", "medium")]
        # house 4 + well 3 + 2 light + house candidate 3
        self.assertEqual(detail_budget.estimate(main, 2, settings, True), 12)

    def test_no_detail_stage(self):
        self.assertEqual(detail_budget.estimate([("house", "high")], 3, None, True), 0)

    def test_main_objects_capped(self):
        settings = Settings(rounds=3, light_rounds=0, candidates=1, objects=1)
        self.assertEqual(detail_budget.estimate([("a", "high"), ("b", "high")], 0, settings, False), 3)


class ScaledLimitsTest(unittest.TestCase):
    def test_detail_shares_the_cap_with_the_later_stages(self):
        from eachlabs.chat import budget
        from eachlabs.chat.run_types import Limits
        limits = budget._scaled_limits(Limits(total_rounds=20), 10, 60, detail=30)
        self.assertEqual(limits.total_rounds, 28)  # 20 + 4 things past six × 2
        self.assertEqual(limits.detail_rounds, 32)
        self.assertEqual(limits.extra_rounds, 32)

    def test_over_the_limit_the_main_stages_keep_their_default(self):
        from eachlabs.chat import budget
        from eachlabs.chat.run_types import Limits
        limits = budget._scaled_limits(Limits(total_rounds=20), 20, 40, detail=30)
        self.assertEqual(limits.total_rounds, 20)
        self.assertEqual(limits.detail_rounds, 20)
        self.assertLessEqual(limits.total_rounds + limits.detail_rounds, 40)


if __name__ == "__main__":
    unittest.main()
