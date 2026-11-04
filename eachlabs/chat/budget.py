"""Rounds and money: how many rounds a request needs, the scaled limits, and the cost line the bar shows."""

from dataclasses import replace


def time_text(seconds):
    """``42 S`` under a minute, else whole minutes: ``8 MIN``."""
    return "%d S" % round(seconds) if seconds < 59.5 else "%d MIN" % round(seconds / 60.0)



def cost_text(rounds, cost, seconds=None):
    """``45 ROUNDS · 8 MIN · $0.689``: the rounds, the run's time without the plan's wait for Build, the cost."""
    text = "%d ROUND%s" % (rounds, "" if rounds == 1 else "S")
    if seconds is not None and seconds >= 0:
        text += " · " + time_text(seconds)
    if cost is None or cost < 0:
        return text
    money = "0" if cost == 0 else "<0.001" if cost < 0.0005 else ("%.3f" % cost).rstrip("0").rstrip(".")
    return "%s · $%s" % (text, money)



def _balance(client):
    try:
        value = client.get_balance().get("balance_usd")
    except Exception:  # A missing balance only hides the cost.
        return None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None



SCALE_FROM = 6  # planned things a run's default rounds cover; each one more adds rounds, up to the cap
ROUNDS_PER_THING = 2
ROUND_PRICE = 0.035  # dollars one model round costs on average, for a model not measured below
# Dollars one round of each model cost on dev (a two-prompt cabin, its calls only): the plan's estimate.
ROUND_PRICES = (("openai/gpt-6.1-terra", 0.014), ("openai/gpt-6-sol", 0.025), ("openai/gpt-6-astra", 0.10), ("anthropic/claude-sonnet-5.5", 0.05),
                ("anthropic/claude-opus-5.5", 0.10))
BUDGET_TEXT = ("This request needs about %d rounds, %d of them for detail (about $%.2f). Your limit is %d, so some "
               "things may not be built.")



def rounds_needed(limits, things):
    """Rounds a request that lists ``things`` needs before the detail stage."""
    return limits.total_rounds + max(0, things - SCALE_FROM) * ROUNDS_PER_THING



def _scaled_limits(limits, things, cap, detail=0):
    """``limits`` for a request that lists ``things``: a big request gets more rounds, the layout a share of them,
    never more in total than ``cap``. ``detail``: the rounds the detail stage will likely use; it and the complete
    and fix stages share what the stages before them leave of ``cap``, never more."""
    total = max(limits.total_rounds, min(cap - detail, rounds_needed(limits, things)))
    total = min(total, max(limits.total_rounds, cap))
    added = total - limits.total_rounds
    stage_rounds = dict(limits.stage_rounds)
    if added > 0:
        stage_rounds["layout"] = limits.rounds_for("layout") + added // 2
    left = max(0, cap - total)
    return replace(limits, total_rounds=total, stage_rounds=stage_rounds, extra_rounds=left, detail_rounds=left)



def run_text(rounds, cost, pictures=0.0):
    """The plan's line for the whole run: ``This run: about 26 rounds · about $1.20, up to $2.10 in all``."""
    text = "This run: about %d rounds · about $%.2f" % (rounds, cost)
    return text + (", up to $%.2f in all" % (cost + pictures) if pictures > 0 else "")



def with_run(looks, rounds, cost, pictures=0.0):
    """``looks`` (the plan's looks line, or ``""``) followed by the run line."""
    line = run_text(rounds, cost, pictures)
    return "%s. %s" % (looks, line) if looks else line



def round_price(model):
    """Dollars one round of ``model`` costs on average."""
    model = (model or "").strip().lower()
    return next((price for prefix, price in ROUND_PRICES if model.startswith(prefix)), ROUND_PRICE)



def estimate_cost(needed, limits, model, light_model="", detail_model="", main_rounds=0):
    """Dollars ``needed`` rounds cost when the light and materials stages' share of them goes to ``light_model``
    and ``main_rounds`` of them, the main objects' detail, go to ``detail_model``."""
    from .stage_models import LIGHT_STAGES

    light = min(needed, sum(limits.rounds_for(s) for s in LIGHT_STAGES)) if light_model else 0
    main = min(needed - light, max(0, main_rounds)) if detail_model else 0
    return ((needed - light - main) * round_price(model) + light * round_price(light_model)
            + main * round_price(detail_model))
