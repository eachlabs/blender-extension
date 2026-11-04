"""Free areas of the ground, for read_scene."""


FREE_CELLS = 48  # cells along the ground's longer side when looking for free space
FREE_AREAS = 3  # free areas read_scene lists



def free_areas(ground, obstacles, count=FREE_AREAS, cells=FREE_CELLS):
    """The biggest empty rectangles on the ground, biggest first: ``{"size": [w, d], "centre": [x, y], "turn": 0}``.
    ``ground`` and every obstacle are ``(x0, y0, x1, y1)``; geometry only, measured on a grid."""
    gx0, gy0, gx1, gy1 = ground
    w, d = gx1 - gx0, gy1 - gy0
    if w <= 0 or d <= 0:
        return []
    step = max(w, d) / cells
    cols, rows = max(1, int(round(w / step))), max(1, int(round(d / step)))
    sx, sy = w / cols, d / rows
    full = [[False] * cols for _ in range(rows)]
    for x0, y0, x1, y1 in obstacles:
        c0, c1 = max(0, int((x0 - gx0) // sx)), min(cols - 1, int((x1 - gx0) // sx))
        r0, r1 = max(0, int((y0 - gy0) // sy)), min(rows - 1, int((y1 - gy0) // sy))
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                full[r][c] = True
    areas = []
    for _ in range(count):
        best = None  # (area, row0, row1, col0, col1)
        heights = [0] * cols
        for r in range(rows):
            heights = [0 if full[r][c] else heights[c] + 1 for c in range(cols)]
            stack = []  # the largest rectangle under the histogram of empty cells ending at row r
            for c in range(cols + 1):
                h = heights[c] if c < cols else 0
                start = c
                while stack and stack[-1][1] >= h:
                    start, top = stack.pop()
                    area = top * (c - start) * sx * sy
                    if top and (best is None or area > best[0]):
                        best = (area, r - top + 1, r, start, c - 1)
                stack.append((start, h))
        if best is None or best[0] < 1.0:
            break
        _area, r0, r1, c0, c1 = best
        areas.append({"size": [round((c1 - c0 + 1) * sx, 1), round((r1 - r0 + 1) * sy, 1)],
                      "centre": [round(gx0 + (c0 + c1 + 1) / 2 * sx, 1), round(gy0 + (r0 + r1 + 1) / 2 * sy, 1)],
                      "turn": 0})
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                full[r][c] = True
    return areas



def fits(areas, size):
    """True when a footprint ``size`` ([w, d]) fits one of ``areas``, turned or not."""
    w, d = size
    return any((a["size"][0] >= w and a["size"][1] >= d) or (a["size"][0] >= d and a["size"][1] >= w) for a in areas)
