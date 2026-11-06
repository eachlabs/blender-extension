"""The bar's Video tab: its settings chips and their menus, the price, the notes under the chips, the confirm card
that Send opens, and what the tab puts on the bar's state. No Blender code.

The Blender side (``chat/video_tab.py``) reads the scene into a ``Shot``; everything the tab shows follows from it."""

import dataclasses

from ..shot import models, price
from . import video_card, video_texts as V


@dataclasses.dataclass
class Shot:
    cameras: list = dataclasses.field(default_factory=list)  # (name, hint, moves) per camera, in menu order
    camera: str = ""  # the camera the video is filmed through; "" when the scene has none
    aspect: str = "16:9"
    resolution: str = "480p"
    seconds: int = 5  # the chosen duration, within ``longest``
    longest: int = 15  # the longest video for this camera
    move_seconds: int = 0  # the scene's frame range in whole seconds
    photos: dict = dataclasses.field(default_factory=dict)  # duration -> photos; empty while the view is measured
    menu: str = ""  # the chip whose menu is open
    confirm: bool = False  # Send asked: the confirm card shows
    stop_ask: bool = False  # Stop video asked: the question shows instead of Stop
    card: bool = True  # the video's own card shows; Make another and Edit the settings hide it
    prompt: str = ""  # the field's text: the shot's direction
    changed: bool = False  # Make video found the scene changed since Send: the card shows the new price and says so


def moves(shot):
    """True when the chosen camera moves within the frame range."""
    return next((m for name, _hint, m in shot.cameras if name == shot.camera), False)


def durations(shot):
    """The duration menu's lengths: the usual ones up to the longest, and the longest itself."""
    return sorted({s for s in V.DURATIONS if models.VIDEO["min_seconds"] <= s <= shot.longest} | {shot.longest})


def cost(shot, resolution=None, seconds=None):
    """The video's total for these settings (the shot's own by default), or ``None`` while photos are counted."""
    seconds = shot.seconds if seconds is None else seconds
    photos = shot.photos.get(seconds)
    if photos is None:
        return None
    return price.total(resolution or shot.resolution, seconds, photos)


def price_text(shot):
    total = cost(shot)
    return V.COUNTING if total is None else V.PRICE % price.text(total)


def chips(shot):
    """``(hit id, label)`` of each settings chip, in order."""
    labels = {"camera": shot.camera, "aspect": shot.aspect, "resolution": shot.resolution,
              "seconds": "%d s" % shot.seconds, "model": models.VIDEO["label"]}
    return [(hit, labels[name]) for name, hit in zip(V.CHIPS, V.CHIP_HITS)]


def notes(shot):
    """The lines under the chips: no camera, a still camera, or a move longer than the longest video."""
    if not shot.camera:
        return [V.NO_CAMERA]
    if not moves(shot):
        return [V.STILL]
    high = models.VIDEO["max_seconds"]
    if shot.move_seconds > high:
        return [V.TOO_LONG % (shot.move_seconds, high, high)]
    return []


def _priced(shot, resolution, seconds, fmt="%s"):
    total = cost(shot, resolution, seconds)
    return fmt % price.text(total) if total is not None else "…"


def menu_values(shot, which):
    """``[(value, name, hint)]`` of a chip's menu, in order."""
    if which == "camera":
        return [(name, name, hint) for name, hint, _m in shot.cameras][:V.MENU_ITEMS]
    if which == "aspect":
        return [(a, a, V.ASPECT_HINTS.get(a, "")) for a in models.ASPECTS]
    if which == "resolution":
        first = models.RESOLUTIONS[0]
        return [(r, r, _priced(shot, r, shot.seconds, V.DRAFT if r == first else "%s")) for r in models.RESOLUTIONS]
    if which == "seconds":
        whole = moves(shot) and shot.longest
        return [(s, "%d s" % s, _priced(shot, shot.resolution, s, V.WHOLE_MOVE if s == whole else "%s"))
                for s in durations(shot)]
    if which == "model":
        return [("seedance", models.VIDEO["label"], V.MODEL_HINT)]
    return []


def menu(shot):
    """``(title, [(name, hint, chosen)])`` of the open chip's menu, or ``("", [])``."""
    chosen = {"camera": shot.camera, "aspect": shot.aspect, "resolution": shot.resolution,
              "seconds": shot.seconds, "model": "seedance"}
    values = menu_values(shot, shot.menu)
    if not values:
        return "", []
    title = V.MENU_TITLES[shot.menu]
    if shot.menu == "resolution":
        title %= shot.seconds
    elif shot.menu == "seconds":
        title %= shot.resolution
    return title, [(name, hint, value == chosen[shot.menu]) for value, name, hint in values]


def picked(shot, hit_id):
    """``(setting, value)`` a menu item's hit chooses in the open menu, else ``None``."""
    if hit_id not in V.MENU_HITS:
        return None
    values = menu_values(shot, shot.menu)
    index = V.MENU_HITS.index(hit_id)
    return (shot.menu, values[index][0]) if index < len(values) else None


def send_block(shot, busy):
    """Why Send cannot open the confirm card, or ``""`` when it can. ``busy``: a video is being made."""
    if not shot.camera:
        return V.NO_CAMERA
    if busy:
        return V.BUSY
    return ""


def _photos(n, capital=True):
    return ("One photo" if capital else "1 photo") if n == 1 else "%d photos" % n


def confirm(shot):
    """``(meta, sentence, Make video label)`` of the confirm card, or ``None`` while photos are counted."""
    photos = shot.photos.get(shot.seconds)
    if photos is None:
        return None
    total = price.text(price.total(shot.resolution, shot.seconds, photos))
    video = price.text(models.VIDEO["per_second"][shot.resolution] * shot.seconds)
    meta = V.CONFIRM_META % (total, video, _photos(photos, False), price.text(models.PHOTO["price"] * photos))
    text = V.CONFIRM_TEXT % (shot.seconds, shot.resolution, shot.camera, models.VIDEO["label"], _photos(photos),
                             "sets" if photos == 1 else "set")
    return meta, text, V.MAKE % total


def apply(s, chat, shot, now):
    """Fill the bar state ``s`` for the Video tab: the card above the tabs, the menu, the chips and the notes."""
    s.mode, s.stages, s.reply, s.error, s.note, s.actions = "video", {}, "", "", "", []
    s.objects, s.cost_text, s.asked = [], "", ""
    busy = getattr(chat, "video", "") in video_card.RUNNING
    s.video_chips = chips(shot) if shot.camera else []
    s.video_price = price_text(shot) if shot.camera else ""
    s.video_notes = notes(shot)
    s.video_menu_title, s.video_menu = menu(shot) if shot.camera else ("", [])
    s.video_open_chip = shot.menu if s.video_menu else ""
    block = send_block(shot, busy)
    s.send_enabled, s.send_tip = not block, block
    s.labels, s.primary = dict(V.LABELS), V.PRIMARY
    asked = confirm(shot) if shot.confirm and not block else None
    if asked is not None:
        s.video_card, s.video_meta, s.video_text = "confirm", asked[0], asked[1]
        s.video_error = V.CHANGED if shot.changed else ""
        s.labels["video_make"] = asked[2]
        s.actions = ["video_make", "video_cancel"]
        return s
    if shot.card:
        video_card.apply(s, chat, shot, now)
    return s
