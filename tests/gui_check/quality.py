"""The quality picker."""

from eachlabs.ui import tokens
from tests.gui_check.bar_input import bar_point, click, key, move, placed, viewport_centre
from tests.gui_check.bar_models import addon_prefs
from tests.gui_check.common import check, screenshot


def quality_picker():
    """The quality pill opens its menu; Esc and a click outside close it; an item sets the preference."""
    from eachlabs import overlay, preferences

    prefs = addon_prefs()
    check("picker: the pill shows the default mode", placed()[4].quality_label == "Prototype"
          and "quality" in placed()[1].hits and prefs.chat_quality == preferences.DEFAULT_QUALITY,
          "%r %s" % (placed()[4].quality_label, sorted(placed()[1].hits)))
    click(*bar_point("quality"))
    yield 0.4
    hits = placed()[1].hits
    check("picker: a click on the pill opens the menu with both modes and gives the bar the keys",
          overlay.UI["quality_menu"] and len(placed()[4].quality_menu) == len(tokens.QUALITIES) and overlay.UI["focused"]
          and all("quality_%d" % i in hits for i in range(len(tokens.QUALITIES))), str(sorted(hits)))
    screenshot("bar-04-quality-menu.png")
    key("ESC")
    yield 0.4
    check("picker: Esc closes the menu and the bar keeps the keys",
          not overlay.UI["quality_menu"] and not placed()[4].quality_menu and overlay.UI["focused"])
    click(*bar_point("quality"))
    yield 0.4
    click(*viewport_centre())
    yield 0.3
    move(*viewport_centre())
    yield 0.3
    check("picker: a click outside the bar closes the menu", not overlay.UI["quality_menu"]
          and not placed()[4].quality_menu and not overlay.UI["focused"])
    click(*bar_point("quality"))
    yield 0.4
    click(*bar_point("quality_1"))
    yield 0.4
    check("picker: choosing Final sets the quality preference and closes the menu",
          prefs.chat_quality == "ADVANCED" and not overlay.UI["quality_menu"]
          and placed()[4].quality_label == "Final", "%r %r" % (prefs.chat_quality, placed()[4].quality_label))
    screenshot("bar-05-quality-advanced.png")
    prefs.chat_quality = preferences.DEFAULT_QUALITY
    key("ESC")
    yield 0.3
