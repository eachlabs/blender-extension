import unittest

from eachlabs.chat import model_calls, stage_models


class StageModelsTest(unittest.TestCase):
    def setUp(self):
        self.sent = []

        def call(model, messages, tools, tokens, reasoning):
            self.sent.append((model, tokens, reasoning))
            return {"model": model}

        self.call = call

    def test_light_and_materials_go_to_the_second_model(self):
        routes = stage_models.routes("openai/gpt-6-sol", "anthropic/claude-sonnet-5.5", self.call)
        for stage in ("light", "materials"):
            route = routes(stage)
            self.assertEqual(route.model, "anthropic/claude-sonnet-5.5")
            self.assertEqual(route.cap, model_calls.reply_cap("anthropic/claude-sonnet-5.5"))
            self.assertEqual(route.llm([], [])["model"], "anthropic/claude-sonnet-5.5")
        for stage in ("layout", "detail", "camera", "check", "edit", "complete", "fix"):
            self.assertIsNone(routes(stage))

    def test_no_second_model_or_the_same_one_routes_nothing(self):
        self.assertIsNone(stage_models.routes("openai/gpt-6-sol", "", self.call))
        self.assertIsNone(stage_models.routes("openai/gpt-6-sol", None, self.call))
        self.assertIsNone(stage_models.routes("openai/gpt-6-sol", " openai/gpt-6-sol ", self.call))

    def test_a_model_that_needs_reasoning_is_never_asked_without(self):
        route = stage_models.route_for(self.call, "anthropic/claude-sonnet-5.5")
        route.quick([], [])
        self.assertEqual(self.sent[-1][2], True)
        route = stage_models.route_for(self.call, "openai/gpt-6-sol")
        route.quick([], [])
        self.assertEqual(self.sent[-1][2], False)

    def test_main_objects_detail_route(self):
        route = stage_models.detail_route("openai/gpt-6-sol", "openai/gpt-6-astra", self.call)
        self.assertEqual(route.llm([], [])["model"], "openai/gpt-6-astra")
        self.assertIsNone(stage_models.detail_route("openai/gpt-6-sol", "", self.call))
        self.assertIsNone(stage_models.detail_route("openai/gpt-6-astra", "openai/gpt-6-astra", self.call))

    def test_stage_model(self):
        self.assertEqual(stage_models.stage_model("a", "b", "light"), "b")
        self.assertEqual(stage_models.stage_model("a", "b", "layout"), "a")
        self.assertEqual(stage_models.stage_model("a", "", "light"), "a")


class EstimateCostTest(unittest.TestCase):
    def test_light_and_materials_rounds_are_priced_at_their_model(self):
        from eachlabs.chat import budget
        from eachlabs.chat_loop import Limits

        limits = Limits()
        light = sum(limits.rounds_for(s) for s in stage_models.LIGHT_STAGES)
        one = budget.estimate_cost(40, limits, "openai/gpt-6-sol")
        two = budget.estimate_cost(40, limits, "openai/gpt-6-sol", "anthropic/claude-sonnet-5.5")
        self.assertAlmostEqual(one, 40 * budget.round_price("openai/gpt-6-sol"))
        self.assertAlmostEqual(two - one, light * (budget.round_price("anthropic/claude-sonnet-5.5")
                                                   - budget.round_price("openai/gpt-6-sol")))
        self.assertEqual(budget.round_price("vendor/unknown"), budget.ROUND_PRICE)

    def test_main_objects_detail_rounds_are_priced_at_their_model(self):
        from eachlabs.chat import budget
        from eachlabs.chat_loop import Limits

        one = budget.estimate_cost(40, Limits(), "openai/gpt-6-sol")
        three = budget.estimate_cost(40, Limits(), "openai/gpt-6-sol", "", "openai/gpt-6-astra", 10)
        self.assertAlmostEqual(three - one, 10 * (budget.round_price("openai/gpt-6-astra")
                                                  - budget.round_price("openai/gpt-6-sol")))


if __name__ == "__main__":
    unittest.main()
