import unittest

from eachlabs.chat import budget


class CostTextTest(unittest.TestCase):
    def test_rounds_time_and_cost(self):
        self.assertEqual(budget.cost_text(45, 0.689, 512), "45 ROUNDS \u00b7 9 MIN \u00b7 $0.689")
        self.assertEqual(budget.cost_text(1, 0.001, 42), "1 ROUND \u00b7 42 S \u00b7 $0.001")

    def test_without_a_time_or_a_cost(self):
        self.assertEqual(budget.cost_text(3, 0.0), "3 ROUNDS \u00b7 $0")
        self.assertEqual(budget.cost_text(3, None, 70), "3 ROUNDS \u00b7 1 MIN")

    def test_time_text(self):
        self.assertEqual([budget.time_text(s) for s in (0, 59, 60, 89, 91, 600)],
                         ["0 S", "59 S", "1 MIN", "1 MIN", "2 MIN", "10 MIN"])


class RunTextTest(unittest.TestCase):
    def test_the_run_line_adds_the_pictures(self):
        self.assertEqual(budget.run_text(26, 1.2, 0.9), "This run: about 26 rounds \u00b7 about $1.20, up to $2.10 in all")
        self.assertEqual(budget.run_text(12, 0.13), "This run: about 12 rounds \u00b7 about $0.13")

    def test_with_run_follows_the_looks_line(self):
        self.assertEqual(budget.with_run("Looks: up to 6 textures \u00b7 up to $0.90", 26, 1.2, 0.9),
                         "Looks: up to 6 textures \u00b7 up to $0.90. This run: about 26 rounds \u00b7 about $1.20, "
                         "up to $2.10 in all")
        self.assertEqual(budget.with_run("", 10, 0.11), "This run: about 10 rounds \u00b7 about $0.11")

    def test_final_routing_prices_the_stages_by_their_models(self):
        from eachlabs.chat.run_types import Limits
        cost = budget.estimate_cost(26, Limits(), "openai/gpt-6-sol", "anthropic/claude-sonnet-5.5",
                                    "openai/gpt-6-astra", 5)
        self.assertAlmostEqual(cost, 6 * 0.05 + 5 * 0.10 + 15 * 0.025)


if __name__ == "__main__":
    unittest.main()
