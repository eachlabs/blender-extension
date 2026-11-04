"""The detail stage's rounds: what it will use, how much of it fits the person's limit, and the plan's estimate.

Pure Python, no ``bpy``. The detail stage runs after the layout and spends its rounds from the same limit as the
complete and fix stages, so the plan card can warn before Build and the run never passes what the person accepted.
"""

from .detail_pick import LIGHT, Target

JUDGE_OBJECTS = 2  # main objects that get candidate versions; as ``detail_judge.OBJECTS``


def object_rounds(target, settings, pictures):
    """Rounds one target gets: its own rounds, plus the close-up round when the model takes pictures."""
    return target.rounds(settings.rounds, settings.light_rounds) + (1 if pictures and target.looks(settings) else 0)


def candidate_names(targets, settings, pictures):
    """The first ``JUDGE_OBJECTS`` high-detail targets, which are built more than once; none without pictures."""
    if getattr(settings, "candidates", 1) < 2 or not pictures:
        return set()
    return set([t.name for t in targets if t.level == "high"][:JUDGE_OBJECTS])


def stage_rounds(targets, settings, pictures, candidates=True):
    """Rounds the whole detail stage uses for ``targets``; ``candidates`` False leaves the extra versions out."""
    total = sum(object_rounds(t, settings, pictures) for t in targets)
    if candidates:
        names = candidate_names(targets, settings, pictures)
        total += sum(t.rounds(settings.rounds, settings.light_rounds) * (settings.candidates - 1)
                     for t in targets if t.name in names)
    return total


def fit(targets, settings, pictures, limit):
    """``(kept, dropped, candidates_on)``: the targets the detail stage can afford within ``limit`` rounds.

    The extra versions go first, then the targets from the end of the pick (light ones before main ones), so the
    pick's order of importance decides. ``limit`` None keeps everything."""
    targets = list(targets)
    if limit is None or stage_rounds(targets, settings, pictures) <= limit:
        return targets, [], True
    kept = [t for t in targets if t.level != LIGHT] + [t for t in targets if t.level == LIGHT]
    dropped = []
    while kept and stage_rounds(kept, settings, pictures, candidates=False) > limit:
        dropped.insert(0, kept.pop())
    order = {t.name: i for i, t in enumerate(targets)}
    kept.sort(key=lambda t: order[t.name])
    return kept, [t.name for t in dropped], False


def estimate(main, secondary, settings, pictures):
    """Rounds the detail stage will likely use, for the plan card: ``main`` is ``[(name, level)]`` of the plan's
    main objects, ``secondary`` how many other planned things may get a light pass. Up to the settings' limits."""
    if settings is None:
        return 0
    targets = [Target(name=n, level=lv) for n, lv in list(main)[:settings.objects]]
    if settings.light_rounds > 0:
        targets += [Target(name="light %d" % i, level=LIGHT)
                    for i in range(min(settings.light_objects, max(0, secondary)))]
    return stage_rounds(targets, settings, pictures)
