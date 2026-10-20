# The Last Light: a 2 min 10 s example film

A lighthouse guides a small fishing boat home through a storm, in 13 ten-second shots. The film is made
the way the add-on is meant to be used: block the scene and the camera moves in Blender with plain
primitives, then let Eachlabs render each shot.

| Step | What happens | Model |
|---|---|---|
| Style frame | Generate Image from View on a camera that sees the whole set | `p-image-edit` |
| 13 shots | Generate Video from Camera Move per shot: the gray-box clip is `@Video1`, the style frame `@Image1` | `bytedance-seedance-2-5-reference-to-video`, draft, 480p, 16:9, 10 s, with audio |
| Movie | Export movie: the sequencer with every shot and its sound, as one MP4 | local |

`shots.py` holds the story, camera moves and prompts; `build_scene.py` builds the set and one camera per
shot (bound to timeline markers); `make_movie.py` drives the add-on's pipeline the way an agent would.

## Run it

```bash
BLENDER=/path/to/blender
OUT=examples/lighthouse/output          # git-ignored

$BLENDER --background --factory-startup --python examples/lighthouse/build_scene.py -- --out $OUT

# Free rehearsal: every call goes to a local stand-in that returns the previs.
$BLENDER --background --online-mode $OUT/lighthouse.blend --python examples/lighthouse/make_movie.py -- --fake

# Paid run on production (draft mode exists only there). The key file must be chmod 600.
$BLENDER --background --online-mode $OUT/lighthouse.blend --python examples/lighthouse/make_movie.py -- \
    --key-file ~/.config/eachlabs/api-key --budget 25
```

Open `$OUT/lighthouse.blend` afterwards: the shots sit on the timeline with their audio, ready to
trim and reorder, and `$OUT/eachlabs/lighthouse/<id>_movie.mp4` is the exported film.
`$OUT/movie-receipt.json` lists every prediction, its settled cost and its `draft_id`.

## Cost

Production lists 480p with a reference video at $0.0708 per second of output plus $0.0708 per second
of reference video: about $1.42 per 10 s shot and $18.50 for the film, plus $0.01 for the style frame.
Draft generation is described as lower-cost but has no separate listed price, so the first shot runs
alone and its settled cost becomes the estimate. The run stops before the estimate would pass
`--budget`.

## Finalizing at 1080p

Each draft can be upgraded within 7 days with `bytedance-seedance-2-5-draft-completion`
(`{"draft_id": ...}`, listed at $0.6629 per second, about $86 for the whole film). The add-on keeps every
`draft_id` in the job manifests and the receipt; completion is not automated yet.
