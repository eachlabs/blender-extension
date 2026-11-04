"""A spatial grid of 2D boxes, so a candidate spot is tested against only the boxes near it."""

import math

CELL_M = 4.0


class Grid:
    def __init__(self, cell=CELL_M):
        self.cell = cell
        self.cells = {}
        self.count = 0

    def _keys(self, box):
        c = self.cell
        for i in range(int(math.floor(box[0] / c)), int(math.floor(box[2] / c)) + 1):
            for j in range(int(math.floor(box[1] / c)), int(math.floor(box[3] / c)) + 1):
                yield i, j

    def add(self, box, tag=None):
        entry = (box, tag)
        for key in self._keys(box):
            self.cells.setdefault(key, []).append(entry)
        self.count += 1

    def hit(self, box, margin=0.0, ignore=()):
        """The tag of a box overlapping ``box`` (grown by ``margin``), or ``None``; tags in ``ignore`` do not count."""
        grown = (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)
        for key in self._keys(grown):
            for other, tag in self.cells.get(key, ()):
                if tag in ignore:
                    continue
                if (grown[0] < other[2] and other[0] < grown[2] and grown[1] < other[3]
                        and other[1] < grown[3]):
                    return tag if tag is not None else True
        return None
