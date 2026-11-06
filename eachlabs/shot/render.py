"""The shot's renders: a grey clay clip of the camera move and a realistic still per key frame. Main thread only.

Renders run one at a time through ``render_export``, which puts back every setting changed here, the engine, shading,
size and camera included, whether the render finishes, fails or is cancelled."""

import os
import shutil

from .. import compat, main_thread, render_export, thread_safety, visual_check

GREY = (0.7, 0.7, 0.7)
KEY_SAMPLES = 32
KEY_QUALITY = 90

_SHARED = (
    ("render", "engine"),
    ("render", "resolution_x"),
    ("render", "resolution_y"),
    ("render", "film_transparent"),
    ("", "camera"),
)
_CLAY = _SHARED + (
    ("display.shading", "light"),
    ("display.shading", "color_type"),
    ("display.shading", "single_color"),
    ("display.shading", "show_cavity"),
    ("display.shading", "show_shadows"),
    ("display.shading", "show_object_outline"),
)
_KEYS = _SHARED + (
    ("render", "use_motion_blur"),
    ("render", "use_compositing"),
    ("render.image_settings", "quality"),
    ("eevee", "taa_render_samples"),
)


def _through(scene, camera, size):
    scene.camera = camera
    scene.render.resolution_x, scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False


def clay_clip(context, scene, camera, plan, size, path, on_done, on_fail, on_wait=None, still_wanted=None):
    """Render ``plan``'s frames in grey Workbench through ``camera`` and encode them, with the last frame held
    ``plan.hold`` times, to the MP4 ``path``. ``on_done(path)``, or ``on_fail(message)``; ``on_wait()`` when
    encoding waits for the scene chat. Once ``still_wanted()`` is false (the job was stopped) nothing more runs."""
    folder = os.path.splitext(path)[0] + "_frames"
    os.makedirs(folder, exist_ok=True)
    frames = []
    wanted = still_wanted or (lambda: True)

    def failed(message):
        shutil.rmtree(folder, ignore_errors=True)
        on_fail(message)

    def configure(target):
        render_export._png(target)
        target.render.engine = "BLENDER_WORKBENCH"
        _through(target, camera, size)
        shading = target.display.shading
        shading.light, shading.color_type, shading.single_color = "STUDIO", "SINGLE", GREY
        shading.show_cavity, shading.show_shadows, shading.show_object_outline = True, True, False
        target.render.filepath = os.path.join(folder, "clay_")
        target.render.use_file_extension = True
        target.frame_start, target.frame_end = plan.frame_start, plan.frame_end
        frames[:] = [target.render.frame_path(frame=f) for f in range(plan.frame_start, plan.frame_end + 1)]
        return list(frames)

    def rendered():
        if not wanted():
            shutil.rmtree(folder, ignore_errors=True)
            return
        if thread_safety.ops_override_unsafe():  # encoding renders under temp_override: wait for the chat
            if on_wait:
                on_wait()
            main_thread.add_task(lambda: thread_safety.ops_override_unsafe() or rendered() or False)
            return
        try:
            held = _hold(frames[-1], plan.hold)
            render_export.encode_mp4(frames + held, scene.render.fps, scene.render.fps_base, path)
        except (RuntimeError, OSError) as exc:
            failed("Making the clay clip failed: %s" % exc)
            return
        shutil.rmtree(folder, ignore_errors=True)
        on_done(path)

    _start(context, scene, configure, True, rendered, failed, _CLAY)


def _hold(last, count):
    """``count`` copies of the last frame beside it, so the encoder reads them as more frames."""
    stem, ext = os.path.splitext(last)
    copies = []
    for index in range(1, count + 1):
        copy = "%s_hold%04d%s" % (stem, index, ext)
        shutil.copyfile(last, copy)
        copies.append(copy)
    return copies


def key_frames(context, scene, camera, frames, size, folder, on_done, on_fail, still_wanted=None):
    """Render each of ``frames`` in Eevee through ``camera`` as a JPEG in ``folder``, one after another.
    ``on_done(paths)`` in frame order, or ``on_fail(message)``. Once ``still_wanted()`` is false nothing more runs."""
    os.makedirs(folder, exist_ok=True)
    paths = []
    wanted = still_wanted or (lambda: True)

    def one(index):
        if not wanted():
            return
        frame = frames[index]
        expected = []

        def configure(target):
            settings = target.render.image_settings
            compat.set_image_output(settings, "JPEG")
            settings.color_mode, settings.quality = "RGB", KEY_QUALITY
            target.render.use_sequencer = False
            target.render.engine = visual_check._eevee(target)
            _through(target, camera, size)
            target.render.use_motion_blur = False
            target.render.use_compositing = False
            eevee = getattr(target, "eevee", None)
            if eevee is not None and hasattr(eevee, "taa_render_samples"):
                eevee.taa_render_samples = KEY_SAMPLES
            target.render.filepath = os.path.join(folder, "key_")
            target.render.use_file_extension = True
            target.frame_start = target.frame_end = frame
            expected[:] = [target.render.frame_path(frame=frame)]
            return list(expected)

        def rendered():
            if not wanted():
                return
            paths.append(expected[0])
            if index + 1 < len(frames):
                _when_free(lambda: one(index + 1))
            else:
                on_done(list(paths))

        _start(context, scene, configure, True, rendered, on_fail, _KEYS)

    _when_free(lambda: one(0))  # the clay clip's render may not have let go yet


def _start(context, scene, configure, animation, on_done, on_fail, extra):
    try:
        error = render_export._run(context, scene, configure, animation, render_export.STILL, on_done, on_fail,
                                   extra=extra)
    except Exception as exc:  # a setting Blender refuses: report it on the job instead of losing the chain
        error = "%s: %s" % (type(exc).__name__, exc)
    if error:
        on_fail(error)


def _when_free(start):
    """Run ``start`` now, or once Blender's previous render has let go."""
    if not render_export.busy():
        start()
        return
    main_thread.add_task(lambda: render_export.busy() or start() or False)
