# Working on this repository

## Code structure

- **One job per module.** A module holds one domain: one check, one part of a run, one card of the bar.
- **Split a module past about 400 lines** into a package of smaller ones, by job, not by size alone.
- **Pure logic without `bpy`** stays in modules that import nothing from Blender, so the unit tests cover it.
  Blender access sits in thin modules around it.
- **Module state stays in one place** (`chat_run.py`, `overlay.py`, `preferences.py`); the modules split out of
  them read it late, through the package's `live.py`, never at import time.
- **Every package has a `README.md` stating what it is for**: its modules, its neighbours, what stays out of it and
  where its tests are. Update it in the same commit that changes the package's modules.

Why: a module with one job is readable in one sitting, reviewable as one change, and testable on its own.

Known exceptions, each one job:

- `chat_loop.py` (about 600 lines): most of it is `run()`, the stage loop. Its inner steps share the run's state
  (rounds, queue, problems found), so splitting it is a redesign of that state, not a move.
- `plan3d.py` (about 430 lines): the plan's model and its parsing. Its name helpers are shared by the parsing and the
  upgrade pictures, so a further split needs a shared naming module first.

## Restructuring

- **One commit per move**: one domain out of one file, with its import updates.
- Each commit passes the unit tests and imports in Blender on its own.
- Keep operator ids, preference names and saved-file property keys unchanged, so preferences and `.blend` files
  keep working.

See `docs/architecture.md` for the package map and `README.md` (Develop) for the test commands.
