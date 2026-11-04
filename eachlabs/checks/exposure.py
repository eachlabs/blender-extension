"""How bright the camera's frame is, so a night scene stays readable, and whether one colour covers all of it.
Seen on a refinery at night where only the loading bay could be made out, and on a cabin lit all orange. ``assess`` is pure; ``measure`` reads a rendered picture in Blender."""

DARK_MEAN = 0.10  # average brightness (0-1) under which the frame reads as too dark
DARK_P90 = 0.30  # brightest tenth under this: even the lit parts are dim
BRIGHT_MEAN = 0.85  # average over this: washed out
WARM_CAST = 1.8  # average red over average blue above this: the whole frame is orange
COOL_CAST = 0.55  # under this: the whole frame is blue
SAMPLES = 20000  # pixels read from a frame, evenly spread


def luminance(r, g, b):
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def levels(values):
    """``(mean, brightest tenth)`` of a list of brightness values."""
    if not values:
        return 0.0, 0.0
    ordered = sorted(values)
    return sum(ordered) / len(ordered), ordered[int(0.9 * (len(ordered) - 1))]


def cast(red, blue):
    """A note for the model when the frame's average ``red`` and ``blue`` (0-1) give it one colour all over, else
    ``""``. A warm or cool cast may be asked for; the note says so."""
    if blue <= 0.005 or red <= 0.005:
        return ""
    ratio = red / blue
    if ratio > WARM_CAST:
        return ("colour cast: the whole frame is orange (red %.1f times blue). Unless the request asks for warm or "
                "golden light all over, make the world and the fill neutral or cool and keep the warm colour to "
                "the lamps and the fire, so white things read white." % ratio)
    if ratio < COOL_CAST:
        return ("colour cast: the whole frame is blue (blue %.1f times red). Unless the request asks for it, warm "
                "the fill or the key light so skin and wood keep their colour." % (1 / ratio))
    return ""


def assess(mean, p90, red=None, blue=None):
    """A note for the model when the frame is too dark, washed out or has a colour cast, else ``""``."""
    if mean < DARK_MEAN or p90 < DARK_P90:
        return ("brightness: too dark (average %d%%, brightest tenth %d%%). Light the subject with its own practical "
                "lights and raise the fill until the average is above %d%%; keep a night sky dark."
                % (round(mean * 100), round(p90 * 100), round(DARK_MEAN * 100)))
    if mean > BRIGHT_MEAN:
        return ("brightness: washed out (average %d%%). Lower the sun, the world strength or the exposure."
                % round(mean * 100))
    if red is not None and blue is not None:
        return cast(red, blue)
    return ""


def measure(path):
    """``(mean, brightest tenth, mean red, mean blue)`` of the picture at ``path``, read through Blender, or
    ``None``."""
    import bpy  # only where Blender runs this

    image = bpy.data.images.load(path, check_existing=False)
    try:
        channels = image.channels
        pixels = list(image.pixels)  # floats 0-1, already display values for a saved PNG
    finally:
        bpy.data.images.remove(image)
    if channels < 3 or not pixels:
        return None
    count = len(pixels) // channels
    step = max(1, count // SAMPLES)
    picked = range(0, count, step)
    values = [luminance(pixels[i * channels], pixels[i * channels + 1], pixels[i * channels + 2]) for i in picked]
    red = sum(pixels[i * channels] for i in picked) / max(1, len(values))
    blue = sum(pixels[i * channels + 2] for i in picked) / max(1, len(values))
    return levels(values) + (red, blue)
