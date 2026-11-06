"""The price of a shot video. No ``bpy``."""

from decimal import ROUND_HALF_UP, Decimal

from . import models


def total(resolution, seconds, photos):
    """Dollars for the clip plus one edited picture per photo."""
    return models.VIDEO["per_second"][resolution] * seconds + models.PHOTO["price"] * photos


def text(amount):
    """``$3.19``: cents rounded half up, after the float sum's noise is cut (3.05 + 0.135 is 3.18499…)."""
    return "$%s" % Decimal(repr(round(amount, 6))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
