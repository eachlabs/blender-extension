"""How a scene should look: one style, figures, soft things, signs, light at night, framing and contents.

Each rule is general: it names no kind of object the add-on knows, only how to build any of them well. Each came
from a defect seen in a test render (blocky people, steam as zigzag sticks, a mirrored shop sign, a dark night
scene, a post filling the frame, an empty bookshelf).
"""

STYLE = (
    "One look for the whole scene. Before you make materials, choose one style and keep every material in it: "
    "simple and stylised (soft colours, low contrast, large calm patterns) unless the request asks for realism "
    "(\"realistic\", \"hyper-realistic\", \"photo\"), then photographic for everything. Group materials by family "
    "and share one material per family (all plaster walls one material, all roofs of one kind another), so every "
    "house looks like it belongs to the same place. Give a texture to every large family the camera sees or to "
    "none: a few photo-textured walls next to flat-coloured houses look like two scenes. looks in read_scene lists "
    "the large families with a picture texture and those without one when they are mixed.\n"
)

FIGURES = (
    "People and animals: real proportions (a head about one eighth of an adult's height, shoulders about a quarter "
    "of it, arms reaching mid-thigh), rounded limbs from cylinders or smoothed cages, never cubes, separate "
    "clothing parts (a coat, a hood, a belt, boots) in the clothes' own colours, hands and feet, a neck, and a face "
    "that reads at a distance (eyes as dark dots, a nose, a darker band of hair). Pose them for what they do: "
    "seated figures bend at the hips and knees, workers hold their tools, walkers step. An animal is a body, a head "
    "on a neck, four legs and a tail in its real proportions, curled or lying when it sleeps, with what makes it "
    "read from the camera: ears, a muzzle or a beak, dark eyes and a nose, fur or feather colour that varies "
    "between back and belly.\n"
    "Organic bodies only (an animal, a body, a soft toy): make the round parts overlap, then fuse them into one "
    "smooth surface with blend([body, neck, head, leg, ...], softness), softness 0.3-0.7, which every step has "
    "defined; it keeps the parts' materials. Leave eyes, the nose, a collar, claws, clothes, thin flat parts "
    "(ears, fins, wings) and every hard-edged part out of blend, so they stay separate. Never blend buildings, machines or furniture.\n"
)

FIRE = (
    "Fire is never sharp cones and never create_cone: a few tongues as soft, rounded, flattened teardrops, wider "
    "at the base, of varied heights and leaning slightly. Make each from a UV sphere: scale it to about 1 wide, "
    "0.5 deep and 2.5 tall, pull the upper vertices toward the centre line with a curve (x and y times "
    "(1 - t) ** 0.7, t the height from 0 to 1, so the tip stays round), bend the top a little sideways, and add "
    "a Subdivision Surface. Give them an emission material whose colour runs from deep orange at the base to "
    "yellow at the tips (a gradient or noise through a colour ramp, never white) and a fine noise bump, plus a "
    "warm point light inside. Embers glow dark red in the logs. When the camera moves, key the tongues' height and "
    "the light's power a little over the frames so the fire flickers. harsh_emission in read_scene lists strong "
    "emitters in a flat near-white colour: tint them, and vary a flame's colour through a noise and a colour "
    "ramp; an entry with washes_out is a coloured glow so strong it renders white: lower its strength to 1.5-3.\n"
)

BACKDROP = (
    "What the camera sees far away (mountains, a skyline, a coast) has depth, not cut-outs: several layers at "
    "different distances, each one paler and bluer with distance, with shading on its slopes from the scene's "
    "light, built as shaped meshes and never as flat triangles or a single painted plane.\n"
)

SOFT = (
    "Soft and loose things are never sticks or spikes: steam, smoke, mist and clouds are a Principled Volume in a "
    "smooth, soft-edged shape, or a few large, semi-transparent smoothed blobs; fur, fleece and grass are many "
    "short, varied, curved strands or a smoothed lumpy surface with a fine bump, never a field of identical cones; "
    "snow lies in smooth rounded drifts. Rock and snow on a mountain are broad patches that follow the slope, "
    "never round dots that read as eyes.\n"
)

SIGNS = (
    "Signs and text read the right way round from the camera: a text object reads correctly when the camera looks "
    "at its front (the side its local +Z faces, or its front face after a rotation). Turn the sign to face the "
    "camera or the street, and never mirror it with a negative scale. mirrored_text in read_scene lists text that "
    "reads backwards from the camera.\n"
)

CONTENTS = (
    "What holds things holds them: a bookshelf is full of books of varied heights and colours, a market stall shows "
    "its goods, a table has what the request puts on it. What the request says is seen through a window or a door "
    "(snow, a street, the sea) is built outside it, in the camera's line of sight through the opening. "
    "through_glass in read_scene lists what the camera sees past each pane of glass in the frame (the sky when "
    "nothing): it shows what the request says is seen through it, at a real distance and size.\n"
)

EXPOSURE = (
    "A night or a dark scene is still readable: the subject is lit by its own practical lights, every area the "
    "camera sees has some light, and the frame's average brightness stays above about 10%. A dark sky is fine; a "
    "black subject is not. brightness in the picture's notes gives the frame's average and its brightest tenth: "
    "raise the practical lights and the fill when it says too dark, never by making the sky bright at night.\n"
)

FRAMING = (
    "Frame the shot like a cinematographer: nothing of yours stands between the camera and the subject within a "
    "few metres of the lens (a post, a branch, a person's head), the planned main things the request names are "
    "in the frame at the first and the last frame, the subject sits off-centre with space in front of it, and "
    "empty ground or sky fills less than half of the frame. near_blockers in camera_view lists what stands right "
    "in front of the lens; missing_from_view lists your big things the camera never shows: bring in those the request is about. In a change to an existing "
    "scene, keep the camera's move: shift or widen it so a new thing shows, never replace the move with another "
    "path or a still shot unless the request asks.\n"
)
