"""Shorten camera_view's lists: group objects of one kind, and measure the empty share of the frame."""

import re

from .common import _r


GRID = (48, 27)  # cells across and down the frame for the empty share
GROUP_MIN = 3  # objects of one kind (name apart from its numbers, type, materials) listed as one entry



def _kind(entry):
    """What makes objects one kind; for lights also their power and colour, so a group hides no difference."""
    return (entry.get("type"), re.sub(r"\d+", "#", entry["name"]), tuple(entry.get("materials") or ()),
            entry.get("energy"), tuple(entry.get("color") or ()))



def _grouped(entries):
    """``entries`` with each run of ``GROUP_MIN`` or more of one kind folded into one entry: the first and the
    last name, the count, and the space they fill, so a large scene fits in one list."""
    kinds = {}
    for entry in entries:
        kinds.setdefault(_kind(entry), []).append(entry)
    out, done = [], set()
    for entry in entries:
        kind = _kind(entry)
        group = kinds[kind]
        if len(group) < GROUP_MIN:
            out.append(entry)
            continue
        if kind in done:
            continue
        done.add(kind)
        folded = {"names": [group[0]["name"], group[-1]["name"]], "name_pattern": kind[1], "count": len(group),
                  "type": kind[0]}
        if group[0].get("materials"):
            folded["materials"] = group[0]["materials"]
        if "energy" in group[0]:
            folded["energy"] = group[0]["energy"]
            folded["color"] = group[0]["color"]
        boxes = []
        for item in group:
            if "bounds" in item:
                boxes.append(item["bounds"])
            elif "dimensions" in item:
                boxes.append([[c - d / 2 for c, d in zip(item["location"], item["dimensions"])],
                              [c + d / 2 for c, d in zip(item["location"], item["dimensions"])]])
            else:
                boxes.append([item["location"], item["location"]])
        folded["spread"] = [_r([min(b[0][i] for b in boxes) for i in range(3)], 1),
                            _r([max(b[1][i] for b in boxes) for i in range(3)], 1)]
        out.append(folded)
    return out



def _empty_share(rects):
    """The share of the frame no rectangle covers, counted on a ``GRID`` of cell centres."""
    cols, rows = GRID
    empty = 0
    for j in range(rows):
        y = (j + 0.5) / rows
        for i in range(cols):
            x = (i + 0.5) / cols
            if not any(r[0] <= x <= r[1] and r[2] <= y <= r[3] for r in rects):
                empty += 1
    return empty / float(cols * rows)
