"""The stages a chat run goes through, their round budgets, and which tools and pictures each stage gets."""

from .. import scene_tools


STAGES = ("layout", "materials", "light", "camera", "check")
# A stage usually uses its whole budget, and a round takes 10-40 s, so these keep a scene to a few minutes.
# The camera needs three: build the move, measure it, fix it; with two it often had no round left to fix.
STAGE_ROUNDS = {"layout": 4, "materials": 3, "light": 3, "camera": 3, "check": 2}
TOTAL_ROUNDS = sum(STAGE_ROUNDS.values())
COMPLETE = "complete"  # an extra stage after layout and after check that builds planned things still missing
COMPLETE_ROUNDS = 2  # within the total cap
COMPLETE_REPEATS = 4  # complete stages in a run, each one only while the one before built something
FIX = "fix"  # a stage that fixes what the add-on measured: things on nothing, through each other, outside zones
EDIT = "edit"  # the one stage of a request that changes only the objects it points at
EDIT_ROUNDS = 3
# After the layout, the main objects get more detail in conversations of their own (``detail.py``). The stage runs
# only when the caller hands ``run`` a ``detail`` function; its rounds come on top of the total cap.
DETAIL = "detail"
ORDER = (STAGES[0], DETAIL) + STAGES[1:]  # every stage a run can show, in order


def is_full(stages):
    """True when ``stages`` are every stage of a run (with or without the detail stage), not a retry of later ones."""
    return tuple(s for s in stages if s != DETAIL) == STAGES


STAGE_TOOLS = {stage: scene_tools.BASE_TOOLS for stage in STAGES + (COMPLETE, EDIT, FIX)}
ASSET_TOOLS = {"materials": ("free_texture",), "light": ("free_sky",)}  # Poly Haven, when it is switched on
LOOK_TOOLS = {"check": ("look_at",), FIX: ("look_at",)}  # with the visual check on: four sides, solid or X-ray
TEXTURE_STAGES = ("materials",)  # the stages that may order generated textures
CONCEPT_STAGES = ("layout", "materials")  # the stages that see the concept picture


# The visual check: a small render the model looks at. The stages in LOOK_AFTER get it when their work is done,
# with one more round to fix what it shows; the check stage gets it with the scene it starts from.
LOOK_AFTER = ("layout", "light", "camera")
LOOK_STAGES = LOOK_AFTER + ("check",)
LOOK_MOVES = ("camera", "check")  # these also see the middle and the last frame when the camera moves
LOOK_ROUNDS = len(LOOK_AFTER)  # rounds the visual check may add to a run; the caller raises the total cap by them
# An edit's look adds a round to fix what it shows and the edit's closing round without tools.
EDIT_LOOK_ROUNDS = 2
REPLY_STAGES = ("check", EDIT)  # their last round goes without tools, so the run ends with a reply


# Stages whose calls go without the model's hidden reasoning: the check stage reads a finished scene and changes
# little, and reasoning made a call up to twice as long. Code check reviews go without it too. The camera stage
# keeps it: without it the model often sent its camera code as text, so the camera was never built.
QUICK_STAGES = ("check",)
