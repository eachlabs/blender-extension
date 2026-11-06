"""Colours, type and sizes of the prompt bar, in logical pixels at scale 1."""

# Colours are (r, g, b, alpha) with alpha 0..1.
ORANGE = (0xFF, 0x3C, 0x15)
WHITE = (0xFF, 0xFF, 0xFF)
GREEN = (0x4F, 0xD4, 0x86)
RED = (0xF2, 0x7C, 0x84)
GREY = (0x8A, 0x8A, 0x8A)

BAR_FILL = (0x0A, 0x0A, 0x0A, 0.92)
BAR_STROKE = WHITE + (0.10,)
BAR_FOCUS = ORANGE + (0.60,)
SHADOW = (0, 0, 0, 0.45)
SHADOW_DY = 8
SHADOW_BLUR = 24
# Transparent space around the bar so the shadow fits inside the image.
MARGIN_X = 36
MARGIN_TOP = 28
MARGIN_BOTTOM = 44

PAD_LEFT = 16
PAD_RIGHT = 8  # leaves room for the send/stop button
TEXT_RIGHT = 16  # right inset of right-aligned text (round, status, cost), as PAD_LEFT
PAD_TOP = 8
PAD_TOP_ROWS = 14
PAD_BOTTOM = 8
ROW_GAP = 10
RADIUS_ROWS = 20

# Input row
MARK_SIZE = 14
MARK_GAP = 10
TEXT_SIZE = 14
TEXT_LINE = 20
TEXT = WHITE + (0.92,)
PLACEHOLDER = WHITE + (0.45,)
PLACEHOLDER_FIRST = "Describe the scene you imagine…"
PLACEHOLDER_NEXT = "Ask for a change: warmer light, a bigger window…"  # while there is a scene the next prompt changes
PLACEHOLDER_ASSET = "Add an object: a wooden barrel by the door…"
PLACEHOLDER_ASSET_CHANGE = "Change %s: make it walnut, move it to the window…"  # an object is selected
PLACEHOLDER_CHARACTER = "Add a character: a ginger cat asleep by the fire…"
PLACEHOLDER_CHARACTER_CHANGE = "Change %s: make it bigger, let it sleep…"
# The tab row above the input: what the next prompt builds. (target, label), in this order.
TABS = (("scene", "Scene"), ("asset", "Assets"), ("character", "Characters"))
TAB_HITS = tuple("tab_" + target for target, _label in TABS)
TAB_TEXT = WHITE + (0.70,)
# The line under the tabs: what the next prompt does (the chosen tab names itself). %s is the selected thing.
TAB_LINE_SCENE_FIRST = "Build the whole scene and its camera move. Start here."
TAB_LINE_SCENE_NEXT = "Change anything in the scene: light, layout, colours, the camera."
TAB_LINE_ASSET = "Add one object to the scene. Select an object to change it instead."
TAB_LINE_ASSET_CHANGE = "Changing %s. Click empty space to add a new object."
TAB_LINE_CHARACTER = "Add a person or an animal, built at full detail. Select one to change it."
TAB_LINE_CHARACTER_CHANGE = "Changing %s. Click empty space to add a new character."
TAB_LINE_SIZE = 12
TAB_LINE_LINE = 16
TAB_LINE_GAP = 6  # between the tabs and their line
TAB_LINE_LINES = 2  # the line wraps to at most this many lines
TAB_CHIP_SIZE = 11  # the selected thing's chip after the line: its name and a cross that clears the selection
TAB_CHIP_H = 20
TAB_CHIP_PAD_X = 8
TAB_CHIP_CROSS = 8
TAB_CHIP_GAP = 6
TAB_CHIP_NAME_MAX = 140  # a longer name ends in an ellipsis
TAB_CLEAR = "tab_clear"  # the chip's hit
SELECTION = ORANGE + (0.30,)
CARET = ORANGE + (1.0,)
CARET_W = 1.5
CARET_H = 18
BUTTON = 36
BUTTON_GAP = 12
SEND_DISABLED_ALPHA = 0.35
STOP_FILL = WHITE + (0.10,)
STOP_STROKE = WHITE + (0.16,)
STOP_SQUARE = 11
MAX_LINES = 6

# Stage chips
CHIP_PAD_X = 10
CHIP_PAD_Y = 5
CHIP_GAP = 6
CHIP_LINE = 16
CHIP_FILL = WHITE + (0.04,)
CHIP_STROKE = WHITE + (0.08,)
CHIP_ACTIVE_FILL = ORANGE + (0.14,)
CHIP_ACTIVE_STROKE = ORANGE + (0.50,)
CHIP_FAILED_FILL = RED + (0.18,)
CHIP_FAILED_STROKE = RED + (0.70,)
DOT = 6
DOT_GAP = 6
DOT_DONE = GREEN + (1.0,)
DOT_TODO = WHITE + (0.24,)
DOT_FAILED = RED + (1.0,)
SPINNER = 12
SPINNER_RING = WHITE + (0.16,)
CHIP_TEXT_SIZE = 12
CHIP_TEXT = WHITE + (0.85,)
CHIP_TEXT_TODO = WHITE + (0.45,)

# Metadata: Geist Mono capitals
META_SIZE = 11
META_LINE = 14
META = GREY + (1.0,)
META_SPACING = 0.04  # of the font size, between letters
TEXT_SPACING = -0.01  # Inter, every size

# Status, reply and the thinking line
STATUS_LINE = 18
STATUS = WHITE + (0.85,)
REPLY = WHITE + (0.92,)
THINKING = "Thinking"
THINKING_DOT = 4
THINKING_DOT_GAP = 2
THINKING_ALPHAS = (1.0, 0.6, 0.3)
SLOW_AFTER = 15
SLOW_TEXT = "Still working… You can keep using Blender."
SLOW_SIZE = 12
SLOW_LINE = 16
SLOW = GREY + (1.0,)
INLINE_GAP = 8

# Error row
ERROR_DOT = 8
ERROR_TEXT = WHITE + (0.92,)
ERROR_WEIGHT = {"error": "medium"}  # by mode; a stop report (several lines) is regular

# Action pills
PILL_SIZE = 12
PILL_LINE = 15
PILL_PAD_Y = 6
PILL_PAD_LEFT = 10
PILL_PAD_RIGHT = 12
PILL_ICON = 10
PILL_ICON_GAP = 6
PILL_GAP = 8
PRIMARY_FILL = ORANGE + (1.0,)
SECONDARY_FILL = WHITE + (0.08,)
SECONDARY_STROKE = WHITE + (0.16,)
PILL_TEXT = WHITE + (1.0,)
PRIMARY_ACTIONS = ("play", "retry", "consent_check", "plan_build")

# Hint row
HINT_SIZE = 11
ASKED_LABEL = "You asked:"  # before the prompt of the run, above its reply
ASKED_LINES_OPEN = 8  # lines of the prompt shown once the person clicked it
HINT_LINE = 14
HINT = GREY + (1.0,)
HINTS = ("↑ earlier prompts", "Shift+Enter new line", "Enter sends", "Esc gives keys back",
         "Shift+Alt+Space opens the bar")
HINT_SEPARATOR = "  ·  "

# Code check: the badge beside the round count, and its lines
BADGE_TEXT = "CODE CHECK"
BADGE_SIZE = 9
BADGE_LINE = 12
BADGE_ICON = 10
BADGE_ICON_GAP = 4
BADGE_PAD_X = 5
BADGE_PAD_Y = 2
BADGE_GAP = 12  # to the round text
BADGE_FILL = GREEN + (0.10,)
BADGE_STROKE = GREEN + (0.55,)
BADGE_INK = GREEN + (1.0,)
CHECKING_TEXT = "Code check: reading the step before it runs…"
REFUSED_TEXT = "Code check stopped a step: %s. The chat is rewriting it without that."
CHECK_STOPPED = "Code check stopped the run:"  # how chat_loop starts the message of a run it stopped
CHECK_OFF_TEXT = "You can turn Code check off in the Eachlabs tab."

# Refusals the bar answers with its own next step
EMPTY_PROMPT = "Describe the scene you imagine first."
ONLINE_OFF = "Online access is off. Enable it in Preferences > System > Network > Allow Online Access."
OFFLINE_MODE = "Blender was started with --offline-mode. Restart without it to use Eachlabs."
START_FAILED = "The chat could not start. Try again."
NOTHING_CHANGED = "Nothing in the scene changed. Try again or reword the request."
SETTINGS_CHANGED = "A step changed the add-on's settings. They were put back and the run was stopped."
CODE_ICON = "</>"

# Code check (a second model reading each step before it runs) is off and hidden: it blocked ordinary build steps
# after the layout. True brings back its preference, the consent card's choice and the badge.
CODE_CHECK_AVAILABLE = False

# Consent card, shown on the first send
CONSENT_TITLE = "The chat builds your scene by writing Blender Python"
CONSENT_BODY = ("The code runs right here in Blender. It is not a sandbox.\n"
                "Every step is one undo, and you can see the code it ran.")
CONSENT_HINT = ("Code check tries to block steps that touch your files, go online or reach outside the scene. "
                "It can be wrong. Change it in the Eachlabs tab.")
TITLE_SIZE = 15
TITLE_LINE = 20
BODY_SIZE = 13
BODY_LINE = 16
BODY = WHITE + (0.80,)
CANCEL_TEXT = WHITE + (0.70,)

# Quality picker: a pill on the input row, and a menu above the input when it is open.
# (mode, name, hint); the menu lists them in this order. The plan card shows each run's price.
QUALITIES = (
    ("PROTOTYPE", "Prototype", "Quick drafts · fewer rounds, GPT-6.1 Terra · about $1 a room"),
    ("ADVANCED", "Final (experimental)", "Full detail · more rounds, detail and reference pictures"),
)
FINAL_RENDERING = "Final render: rendering in its own window with Cycles. Esc there stops it."
FINAL_SAVED = "Final render saved in %s: %s, next to the .blend file."
FINAL_STOPPED = "Final render stopped. Final render starts it again."
FINAL_FAILED = "Final render failed: %s. Final render tries again."
# The shot video's line on the done card, and its part of the folded line (upper-cased there).
VIDEO_RENDERING = "Video: recording the camera move… %d%%"
VIDEO_PHOTOS = "Video: making the look (%s)…"
VIDEO_UPLOADING = "Video: making the look…"
VIDEO_GENERATING = "Video: %s is making it… %s"
VIDEO_DONE = "Video: in the Video Sequencer"
VIDEO_FAILED = "Video failed: %s"
VIDEO_STOPPED = "Video stopped; it may still be billed"
VIDEO_RETRY_LATER = " · Retry when the chat finishes."  # while a chat runs: Retry would render under it
VIDEO_FOLDED = {"rendering": "Video %d%%", "photos": "Video look %s", "generating": "Video %s", "done": "Video ready",
                "stopped": "Video stopped"}
QUALITY_HITS = tuple("quality_%d" % i for i in range(len(QUALITIES)))  # the menu's items, in QUALITIES order
QUALITY_PILL_MAX = 160  # a longer label ends in an ellipsis
QUALITY_FIELD_MIN = 200  # text width the pill leaves on the input row; below it the pill takes a row of its own
QUALITY_CHEVRON = 8
SETTINGS = 28  # the round settings button left of the send button; it opens the add-on's preferences
MENU_TITLE = "Mode"
MENU_PAD_X = 10
MENU_PAD_Y = 7
MENU_GAP = 2  # between items
MENU_NAME_SIZE = 13
MENU_NAME_LINE = 18
MENU_HINT_SIZE = 12
MENU_HINT_LINE = 16
MENU_HINT = GREY + (1.0,)
MENU_CHOSEN_FILL = ORANGE + (0.14,)
MENU_CHOSEN_STROKE = ORANGE + (0.50,)
MENU_RADIUS = 10

# The done card folds to one line so the scene shows; the mouse on the bar opens it again.
FOLD_AFTER = 4.0  # seconds after the card first shows; later the mouse opens and folds it at once
FOLDED_PARTLY = "A stage partly done"  # added to the folded line when Retry stage waits under it

# Tooltips: a card over the control the mouse rests on (texts in ``tooltips.py``).
TIP_DELAY = 0.6  # seconds the mouse rests on a control before its tooltip shows
TIP_MAX = 280  # widest card, logical px; the text wraps inside it
TIP_SIZE = 12
TIP_LINE = 16
TIP_PAD_X = 10
TIP_PAD_Y = 7
TIP_RADIUS = 8
TIP_GAP = 8  # between the card and its control
TIP_EDGE = 8  # the card stays this far inside the 3D view
TIP_FILL = (0x0A, 0x0A, 0x0A, 0.96)

# Play through a camera: a split button on the done card, and a menu of the scene's cameras above the actions.
PLAY = "Play"
PLAY_AS = "Play as %s"
PAUSE = "Pause"
PLAY_NAME_MAX = 150  # a longer camera name on the button ends in an ellipsis
SPLIT_CHEVRON_W = 26  # the chevron part of the split Play button
SPLIT_DIVIDER = WHITE + (0.35,)
CAMERA_MENU_TITLE = "Play through"
CAMERA_MENU_MAX = 10  # items the bar's menu lists; the sidebar's menu lists every camera
CAMERA_HITS = tuple("camera_%d" % i for i in range(CAMERA_MENU_MAX))  # the menu's items, top to bottom
CAMERA_MORE = "+%d more cameras in the Eachlabs sidebar"

# The plan of 3D objects: the 3D items and the code items as chips; a click moves one between them.
PLANNING_TEXT = "Planning the scene…"
PLAN_HINT = ("Click a solid piece to move it between 3D and code. Objects with parts are always built in code. "
             "Nothing is paid for before Build.")
STOPPED_BILLED = "Stopped — a 3D run already started may still be billed."
LOOKS_HINT = "Nothing is drawn before Build. Turn them off in the add-on's Preferences."
PLAN_ITEMS = 24
PLAN_HITS = tuple("plan_item_%d" % i for i in range(PLAN_ITEMS))  # the chips, in the plan's order
PLAN_3D_FILL = ORANGE + (0.14,)
PLAN_3D_STROKE = ORANGE + (0.50,)
PLAN_3D_DOT = ORANGE + (1.0,)
PLAN_TITLE_SIZE = 13
PLAN_TITLE_LINE = 18
PLAN_CACHED = "cached, free"

# Asked before an action that removes, undoes or stops something: (title, what happens and what stays, button).
CONFIRM_NEW_SCENE = ("Start a new scene?", "The next prompt builds in a new, empty scene. This scene stays as it is "
                     "in Blender's scene list.", "New scene")
CONFIRM_UNDO_STAGE = ("Undo the %s stage?", "What that stage built or changed is removed. The earlier stages "
                      "stay.", "Undo stage")
CONFIRM_STOP_PAID = ("Stop the chat?", "What was built stays. 3D objects or pictures already being made on "
                     "each::labs are still billed, and that spend is not refunded.", "Stop")
CONFIRM_CLEAR_FILES = ("Delete the generated files?", "The 3D models, textures and pictures kept on this computer "
                       "are deleted. Objects in your scenes stay.", "Delete")
CONFIRM_CANCEL_JOB = ("Stop this job?", "It stops now, and nothing more is made. A run that already started on "
                      "each::labs is billed, and that spend is not refunded.", "Stop job")
CONFIRM_CANCEL_LOCAL = ("Stop this job?", "Its render stops now. Nothing was sent to each::labs, so nothing is "
                        "billed.", "Stop job")
CONFIRM_STOP_VIDEO = ("Stop the video?", "It stops now and nothing more is made. Photos or the video already being "
                      "made on each::labs may still be billed.", "Stop video")
CONFIRM_CLEAR_JOBS = ("Clear finished jobs?", "Finished jobs leave this list. Their files and anything in your "
                      "scenes stay.", "Clear")
OBJECTS_WAIT_TEXT = "Waiting for the 3D models to replace their code versions…"
CONCEPT_DRAWING = "Drawing a concept picture of the scene…"
LOOKING = "Looking at the frame…"
