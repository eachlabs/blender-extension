"""Groups of parts that do not touch the rest of their thing, for read_scene."""

from .part_groups import ASSEMBLY_MIN, _groups, _label, _overlap


TOUCH_GAP = 0.05  # metres between two parts' boxes that still count as touching
LOOSE_MAX = 12  # groups listed in read_scene's loose_parts
LOOSE_NAMES = 6  # names listed per group



def loose_parts(parts):
    """Groups of the chat's objects whose parts do not touch. ``parts``: ``{"name", "parent", "box"}`` per object,
    with ``parent`` the name of a chat parent or ``None`` and ``box`` ``(low, high)`` in world space, or ``None`` for an
    object with no geometry. A group is one parent with everything under it, or else the objects that share a
    name start: ``Person_A_*`` for three-part names, ``House_*`` for two-part ones."""
    groups, how = _groups(parts)
    loose = []
    for key, members in groups.items():
        solid = [p for p in members if p.get("box") is not None]
        if len(members) < ASSEMBLY_MIN or len(solid) < 2:
            continue
        piece = list(range(len(solid)))

        def find(i):
            while piece[i] != i:
                piece[i] = piece[piece[i]]
                i = piece[i]
            return i
        for i in range(len(solid)):
            for j in range(i + 1, len(solid)):
                if _overlap(solid[i]["box"], solid[j]["box"], TOUCH_GAP):
                    piece[find(i)] = find(j)
        sizes = {}
        for i in range(len(solid)):
            sizes.setdefault(find(i), []).append(solid[i]["name"])
        if len(sizes) < 2:
            continue
        main = max(sizes.values(), key=len)
        apart = sorted(name for names in sizes.values() if names is not main for name in names)
        loose.append({"parts_of": _label(key, how),
                      "parts": len(solid), "pieces": len(sizes),
                      "apart": apart[:LOOSE_NAMES] + (["+%d more" % (len(apart) - LOOSE_NAMES)]
                                                      if len(apart) > LOOSE_NAMES else [])})
    loose.sort(key=lambda g: (-g["pieces"], g["parts_of"]))
    return loose[:LOOSE_MAX]
