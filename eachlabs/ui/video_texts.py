"""What the bar's Video tab says, and the hit ids of its chips, menu items and buttons. No Blender code."""

TAB_LINE = "Film the scene through its camera. Seedance makes it real; your camera move and layout stay."
PLACEHOLDER = "Describe the shot (optional): golden hour, light mist…"

# The settings row: one chip per setting, then the price at its right end.
CHIPS = ("camera", "aspect", "resolution", "seconds", "model")
CHIP_HITS = tuple("vchip_" + name for name in CHIPS)
MENU_ITEMS = 12  # the most items a chip's menu lists
MENU_HITS = tuple("vmenu_%d" % i for i in range(MENU_ITEMS))
DURATIONS = (4, 5, 6, 8, 10, 12, 15)  # the duration menu's lengths, with the move's own length added
PRICE = "≈ %s"
COUNTING = "≈ …"  # while the camera's view is measured for the photos
MENU_TITLES = {"camera": "Camera", "aspect": "Aspect", "resolution": "Resolution · %d s · total",
               "seconds": "Duration · %s · total", "model": "Model"}  # the prices listed are the whole video's
ASPECT_HINTS = {"16:9": "wide", "9:16": "tall, for phones", "1:1": "square", "4:3": "classic", "3:4": "portrait",
                "21:9": "cinema wide"}
DRAFT = "draft · %s"  # the cheapest resolution
WHOLE_MOVE = "whole move · %s"
MODEL_HINT = "realistic video with sound"

NO_CAMERA = "This scene has no camera. Add one, or ask the chat for a camera move."
STILL = "This camera doesn't move: the video is a still shot. Ask the chat for a camera move to get one."
TOO_LONG = "The move is %d s; videos are up to %d s, so it uses the first %d s."
BUSY = "One video at a time: this one finishes or stops first."

# Send asks first, in the bar.
CONFIRM_META = "Total %s · Video %s · %s %s"
CONFIRM_TEXT = ("Make a %d s, %s video through %s with %s. %s of the scene %s the look. "
                "It may still be billed after Stop.")
MAKE = "Make video · %s"
CHANGED = "The scene changed; check the new price. Nothing was made or billed."

# While it is made: the stage chips, one sentence on the stage and the next, and the live line.
STAGES = (("camera", "Camera move"), ("keys", "Key frames"), ("look", "Look"), ("video", "Video"),
          ("sequencer", "Sequencer"))
NOW = {
    "camera": "Recording the camera move as a grey clay clip. Next, the key frames are rendered (a few seconds).",
    "keys": "Rendering the key frames of the scene. Next, each becomes a photo of the real scene "
            "(about 20–60 s per photo).",
    "look": "Turning %s into %s of the real scene. Next, Seedance films the camera move (about 4 min).",
    "video": "Seedance is filming the camera move (about 4 min). Next, the video goes into the Video Sequencer.",
    "sequencer": "Putting the video into the Video Sequencer. Next, it is ready to play.",
}
LIVE = {
    "camera": "Recording the camera move… %d%%",
    "keys": "Rendering the key frames… %d%%",
    "upload": "Uploading the clip and the key frames…",
    "look": "Making the look: photo %s…",
    "video": "%s is making it… %s",
    "sequencer": "Adding it to the Video Sequencer…",
}
STOP_ASK = "Stop the video? It may still be billed."
STOP_ASK_FREE = "Stop the video? Nothing was sent yet, so nothing is billed."

READY = "Your %d s video is in the Video Sequencer, next to the scene it was made from."
FAILED = "%s failed: %s."
FAILED_WHAT = {"camera": "The camera move", "keys": "The key frames", "look": "The look", "video": "The video",
               "sequencer": "Adding it to the Sequencer"}
NOTHING_MORE = "Nothing more was spent."
STOPPED = "The video stopped. Work already sent to each::labs may still be billed."

LABELS = {"video_make": "Make video", "video_cancel": "Cancel", "video_stop_yes": "Stop",
          "video_stop_no": "Keep going", "video_another": "Make another", "video_edit": "Edit the settings"}
ICONS = {"video_make": "play", "video_cancel": "close", "video_stop": "stop", "video_stop_yes": "stop",
         "video_open": "play", "video_file": "open_file", "video_another": "sparkle", "video_retry": "retry",
         "video_edit": "ring"}
PRIMARY = ("video_make", "video_open", "video_retry")
ACTIONS = ("video_make", "video_cancel", "video_stop_yes", "video_stop_no", "video_another", "video_edit")
SEND_OFF = "send_off"  # the dimmed send button, for its tooltip
HITS = CHIP_HITS + MENU_HITS + ACTIONS + (SEND_OFF,)
