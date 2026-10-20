"""Shot list for "The Last Light": 13 ten-second shots, 2 min 10 s at 24 fps.

Each shot is a camera move over the gray-box island in build_scene.py. The prompts cite the
previsualization as @Video1 (camera, framing, timing) and one shared style frame as @Image1 (look).
They avoid editing words (add, remove, replace, extend, continue), which switch Seedance 2.5 to video
editing and override the requested duration.
"""

FPS = 24
SHOT_SECONDS = 10
SHOT_FRAMES = FPS * SHOT_SECONDS

# Frame where the boat is moored, so the style frame shows every element of the film.
STYLE_FRAME = 2700
STYLE_CAMERA = {"location": (3.0, -19.0, 6.0), "target": (-4.0, 3.0, 2.0)}
STYLE_PROMPT = (
    "Turn this gray-box layout into a photoreal cinematic frame at dusk: a lonely white lighthouse with a "
    "red band and a dark red lantern roof on a small rocky island, a little stone cottage with warm windows, "
    "a wooden dock with a small red fishing boat with a white cabin, a calm dark sea and a dramatic sky. "
    "Anamorphic 35 mm film look, moody teal and amber grade. Keep the composition and every object."
)

LOOK = (
    "Photoreal cinematic footage, anamorphic 35 mm film look, moody teal and amber grade, matching the "
    "lighthouse, island, cottage, boat and palette of @Image1. Follow the camera movement, framing and timing "
    "of @Video1 exactly; @Video1 is a gray-box previsualization, so show real water, rock, sky, rain and "
    "light in place of its flat shapes."
)
SCORE = "Music: a sparse, melancholic piano and strings theme."

# Boat path: (frame, x, y). It waits on the horizon, crosses the storm, and moors at the dock.
BOAT_PATH = [
    (1, -70.0, 40.0), (961, -70.0, 40.0), (1201, -58.0, 32.0), (1441, -48.0, 26.0), (1681, -40.0, 21.0),
    (1921, -32.0, 16.0), (2161, -24.0, 12.0), (2401, -14.0, 8.0), (2640, -9.6, 6.2), (3120, -9.6, 6.2),
]

SHOTS = [
    {"name": "01_arrival", "move": "line", "camera": ((60, -60, 22), (16, -16, 7)), "target": ((0, 0, 4), (0, 0, 4.5)),
     "prompt": "Dusk over a calm dark sea. The camera glides low over the water toward a lonely white lighthouse "
               "with a red band on a small rocky island. Soft wind and distant gulls."},
    {"name": "02_rocks", "move": "orbit", "center": ((0, 0), (0, 0)), "radius": 9, "height": 2.0, "angles": (200, 300),
     "target": ((0, 0, 2.5), (0, 0, 2.5)),
     "prompt": "Waves break against the dark rocks at the foot of the lighthouse as the camera circles its base. "
               "Spray and foam catch the last orange light. Sound of surf and wind."},
    {"name": "03_tower", "move": "line", "camera": ((4, -5, 1.5), (4, -5, 9)), "target": ((0, 0, 1.5), (0, 0, 8.2)),
     "prompt": "The camera rises slowly up the weathered white tower to the lantern room at the top. The great lamp "
               "flickers, then glows warm gold. A soft mechanical hum joins the music."},
    {"name": "04_beam", "move": "line", "camera": ((-34, -26, 3), (-30, -30, 3.5)), "target": ((0, 0, 5), (0, 0, 5)),
     "prompt": "Wide view from the open sea: the lighthouse beam begins to sweep across the darkening water while "
               "heavy storm clouds roll in on the horizon. Low thunder rumbles far away."},
    {"name": "05_boat", "move": "line", "camera": ((-68, 26, 2.5), (-55, 18, 2.5)),
     "target": ((-70, 40, 0.5), (-58, 32, 0.5)),
     "prompt": "Far out at sea, a small red fishing boat with a white cabin rides the swell, seen from the side as "
               "it heads toward the distant island. Rising wind and creaking wood."},
    {"name": "06_storm", "move": "line", "camera": ((-40, 14, 4), (-50, 22, 2)), "target": ((-58, 32, 0.5), (-48, 26, 0.5)),
     "prompt": "The storm arrives. Rain lashes the sea as the camera pushes toward the little red boat climbing "
               "steep, foaming waves. Roaring wind and rain."},
    {"name": "07_swell", "move": "orbit", "center": ((-48, 26), (-40, 21)), "radius": 6, "height": 2.5, "angles": (0, 120),
     "target": ((-48, 26, 0.5), (-40, 21, 0.5)),
     "prompt": "The camera circles the red boat in heavy swell; lightning flashes reveal the churning water around "
               "it. Thunder cracks and waves slam against the hull."},
    {"name": "08_signal", "move": "line", "camera": ((-0.8, 0.5, 8.0), (-0.9, 0.6, 8.0)),
     "target": ((-40, 21, 0), (-32, 16, 0)),
     "prompt": "From high in the lantern room, the rotating beam sweeps through the rain and lands on the distant "
               "red boat, which turns toward the light. The lamp hums; the storm howls outside."},
    {"name": "09_tower_storm", "move": "line", "camera": ((6, -4, 0.8), (5, -5, 1.2)), "target": ((0, 0, 6), (0, 0, 7)),
     "prompt": "Low angle at the base of the lighthouse in the storm: the white tower rises above, its beam cutting "
               "through sheets of rain under a black sky. Thunder and pounding surf."},
    {"name": "10_follow", "move": "line", "camera": ((-34, 20, 3), (-22, 13, 2.5)), "target": ((-24, 12, 0.5), (-14, 8, 0.5)),
     "prompt": "Behind the red boat as it follows the sweeping beam through the rain toward the island's sheltered "
               "harbor. The engine putters and the rain eases. The theme returns softly."},
    {"name": "11_harbor", "move": "line", "camera": ((-12, -1, 2.5), (-11, 0, 2)), "target": ((-14, 8, 0.5), (-9.6, 6.2, 0.5)),
     "prompt": "The red boat glides into the small harbor and comes to rest beside a wooden dock and a little stone "
               "cottage with warm glowing windows. Gentle lapping water as the rain fades."},
    {"name": "12_dawn", "move": "line", "camera": ((10, 10, 2), (16, 16, 16)), "target": ((0, 0, 3), (0, 0, 2)),
     "prompt": "Dawn. The storm has cleared and golden light spills over the island as the camera rises above the "
               "lighthouse, the cottage and the moored red boat. Birdsong over a calm sea."},
    {"name": "13_last_light", "move": "line", "camera": ((12, -12, 6), (70, -70, 30)), "target": ((-2, 1, 3), (-2, 2, 2)),
     "prompt": "A slow final pull back into a wide aerial view: the lighthouse, the island and the safe boat bathed "
               "in sunrise over a calm, glittering sea. The piano theme resolves to its last note."},
]


def frame_range(index):
    """Inclusive frame range of shot ``index`` (0-based)."""
    start = 1 + index * SHOT_FRAMES
    return start, start + SHOT_FRAMES - 1


def prompt(shot):
    return "%s %s %s" % (shot["prompt"], LOOK, SCORE)
