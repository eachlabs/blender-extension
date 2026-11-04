"""Which model answers which stage: the scene's model answers every stage, except the light and materials stages,
which a second model may take, and the main objects' detail, which a third may take. No Blender here."""

from dataclasses import dataclass

from . import model_calls

LIGHT_STAGES = ("light", "materials")  # the stages the light and materials model answers



@dataclass(frozen=True)
class Route:
    """One stage's model: ``llm(messages, tools)``, the same without hidden reasoning, its reply cap and its id."""
    llm: object
    quick: object
    cap: object
    model: str



def route_for(call, model):
    """A ``Route`` for ``model``; ``call(model, messages, tools, max_tokens, reasoning)`` sends one round."""
    cap = model_calls.reply_cap(model)

    def llm(messages, tools):
        return call(model, messages, tools, cap.tokens, True)

    quick = model_calls.WithoutReasoning(lambda messages, tools, reasoning: call(model, messages, tools, cap.tokens,
                                                                                 reasoning),
                                         accepted=model_calls.reasoning_optional(model))
    return Route(llm, quick, cap, model)



def routes(main, light, call):
    """``stage -> Route`` for the stages a second model answers, else ``None`` (the run's own model). ``None`` when
    there is no second model, or it is the scene's model."""
    light = (light or "").strip()
    if not light or light == (main or "").strip():
        return None
    route = route_for(call, light)
    return lambda stage: route if stage in LIGHT_STAGES else None



def detail_route(main, detail, call):
    """The ``Route`` that details the main objects, or ``None`` when the scene's model does."""
    detail = (detail or "").strip()
    return route_for(call, detail) if detail and detail != (main or "").strip() else None



def stage_model(main, light, stage):
    """The model id that answers ``stage``."""
    light = (light or "").strip()
    return light if light and stage in LIGHT_STAGES else main
