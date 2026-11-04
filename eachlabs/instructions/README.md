# instructions

Everything the language model is told, as plain text: the shared rules for writing Blender Python, each stage's
instructions, the plan call's format, and the short notes a run adds to its messages. Keeping the text here, apart
from the code that sends it, lets it be read and reviewed as one document.

## Modules

| Module | Job |
|-|-|
| `rules.py` | Shared rules: units, building with bmesh, parenting, placement calls, materials, version notes, shape examples |
| `stages.py` | Each stage's instructions, for a new scene and for a change to an existing one |
| `look.py` | How a scene should look: one style, figures, soft things, signs, fire, light at night, framing |
| `detail.py` | The detail stage: picking main objects, detailing one, the close-up, the comparison with the reference picture |
| `targets.py` | What a prompt builds by the bar's tab: the asset and character request text, their stages, and the quick call's note that a named thing counts only when it is of the tab's kind |
| `plan.py` | The plan call: its JSON shape, its rules and its request message |
| `review.py` | The scene review's call and its second look: what counts as a problem, the JSON answer, the fix stage's note |
| `notes.py` | Short notes a run adds: pictures, last rounds, cut-off steps, generated objects |

## Neighbours

- **Called by** `chat_loop.py`, `chat/` and `detail.py`, which build the messages.
- **Calls** nothing: these modules hold text and small functions that format it.

## Keep out

- No `bpy` and no imports from the rest of the add-on beyond plain text helpers.
- No knowledge of particular objects as rules in code; examples in the text use general things and never the
  scenes the tests use.

## Tests

`tests/test_chat_loop.py`, `tests/test_plan3d.py` and `tests/test_review.py` pin the phrases the checks and the model depend on.
