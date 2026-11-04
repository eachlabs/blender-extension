"""Short notes a run adds to the model's messages: pictures, last rounds, cut-off steps, generated objects."""

from ..chat.stages import EDIT


CONCEPT_NOTE = ("This picture is a concept of the scene, drawn from the request. Use it as a reference for the "
                "layout, the colours and the mood; build what the request asks, and where they differ, the request "
                "wins.")
FREE_ASSETS_RULE = (
    "free_texture and free_sky take real, free photo assets from Poly Haven (CC0) at once. In the light stage, "
    "call free_sky once for a scene under the open sky, describing its time of day and weather, then tune its "
    "strength and add your own sun and practical lights; keep your own world for interiors and night scenes lit "
    "by lamps. In the materials stage, call free_texture for the main families of surfaces (one material shared "
    "by all the walls of one kind, one by all the roofs), never for small objects. When a call fails, build that "
    "look with procedural nodes. Keep one look for the whole scene: see the style rule.\n")
TEXTURE_RULE = (
    "generate_texture orders a real photo texture for one of your materials (at most %d more in this scene). Use "
    "it for the few large surfaces the camera sees most, such as walls, a floor, a road or a lawn, never for small "
    "objects. Make the material with run_python first, then call generate_texture with its exact name; the texture "
    "replaces its Base Color when it is ready, so keep the material's other settings and do not rebuild it.\n")  # every stage: the three tools
LOOK = ("This is what the camera sees now. Fix anything clearly wrong: things floating, overlapping, standing in "
        "water or under something where they should stand beside it, sunk into what they rest on, too small or too "
        "big for real life, cut off, out of frame, too dark, the wrong time of day.")
LOOK_OVERVIEW = "You have no camera yet, so this picture is a view from above at an angle of what you built."
LOOK_FRAME = "Frame %s:"
LOOK_AROUND = ("These are the four sides look_at rendered, in plain shading with temporary cameras; the scene camera "
               "did not move. Fix what they show is wrong; the render is not the final look.")
# Added for the stage whose picture cannot be judged on everything yet. Without it the layout's unlit frame made
# the model light the scene in the layout stage.
LOOK_NOTES = {"layout": "There are no materials or lights of yours yet, so judge only the shapes: their size, their "
                        "place and how they stand.",
              EDIT: "This was a change to the target only. Check that what the request asked for shows in this "
                    "picture; if it is on a side the camera does not see, put it where it shows, on the target "
                    "only. If it shows, answer with one plain sentence that says what changed, and no tool calls."}
# Sent in place of a picture the model refused: the same check, from read_scene and camera_view.
NO_PICTURE = ("Check the scene once more from read_scene and camera_view, and fix anything clearly wrong: things "
              "floating, overlapping, too small or too big for real life, cut off, out of frame, too dark, the wrong "
              "time of day.")
# Sent for one extra round when the light stage ends and the scene has no lights of the run's own.
NO_LIGHTS = ("The scene has no lights of your own, so the render will be dark. Add them now in one run_python step: "
             "a real light at every light source the scene shows, and a soft fill.")
# Added before the check stage's last round, so the run ends with a reply for the person.
LAST_ROUND = ("This is the last round of this stage. Do not call a tool: tell the person now, in one or two plain "
              "sentences, what the scene shows.")
LAST_EDIT_ROUND = ("This is the last round. Do not call a tool: tell the person now, in one plain sentence, what "
                   "changed.")
CUT_OFF = ("your last step was too long and was cut off, so it did not run. Split it into steps of about 80 "
           "lines and send one per reply")
# Sent when a reply holds code as text instead of a run_python call: nothing ran, so the stage goes on.
CODE_AS_TEXT = ("Your code came as text, so it did not run and the scene did not change. Send it as a run_python "
                "call.")
# Sent when a reply was cut off before any tool call came through: the stage goes on instead of ending.
CUT_OFF_REPLY = ("Your last step was too long and was cut off; nothing in it ran. Split it: send one run_python "
                 "call of about 80 lines now, and the rest in later replies.")
NO_MATERIAL = ("These meshes of yours have no material, so they render plain white: %s. Give each a material that "
               "fits it now, in one run_python step: a loop over them by name.")
GENERATE_RULE = (
    "Each object the request message lists under 3D objects already has a real 3D model ordered. Build a simple code "
    "version of each copy with run_python at its final place and real size, standing where it belongs (a car on the "
    "driveway, a tree on the lawn), as one root object per copy with its parts parented to it, the root named "
    "exactly as listed; build a vehicle with its length along Y and turn the root object. Each 3D model replaces its "
    "code version when it is ready; if it cannot be made, the code version stays. Build the code versions together "
    "with the rest of the scene, so every listed thing is in the scene by the end of this stage.\n")
GENERATED_RULE = (
    "Objects that read_scene marks generated: true are real 3D models with their own textures: never give them "
    "materials or modifiers and never build them again; you may move, turn and scale them. Objects marked placeholder are "
    "code versions waiting for their 3D model: give them materials like the rest, never delete or rename them. "
    "generated_3d in read_scene lists the 3D models and their state.\n")
