"""Eachlabs Blender extension: send renders to Eachlabs models and workflows, get results back.

Submodules that import ``bpy`` are loaded in ``register()`` so the pure modules (``api_client``,
``capabilities``, ``jobs``, ``naming``, ``timing``) stay importable for unit tests outside Blender.
"""

VERSION = "0.1.0"


def register():
    import bpy

    from . import chat_run, main_thread, operators, overlay, panels, pipeline, preferences, props, viewport_marks

    preferences.register()
    props.register()
    operators.register()
    panels.register()
    overlay.register()
    viewport_marks.register()
    main_thread.add_hook(pipeline.tick_hook)
    main_thread.add_hook(chat_run.hook)
    main_thread.start()
    chat_run.register_handlers()
    from .chat import playback

    playback.register()  # puts the view back when playback through a camera stops
    bpy.app.handlers.load_pre.append(pipeline.on_load_pre)
    bpy.app.handlers.load_post.append(pipeline.on_load_post)


def unregister():
    import bpy

    from . import catalog, chat_run, main_thread, operators, overlay, panels, pipeline, preferences, props, viewport_marks

    chat_run.unregister_handlers()
    from .chat import playback

    playback.unregister()
    from .shot import render_window, view_cache

    view_cache.forget()
    render_window.restore()  # a shot still rendering: the person's render window setting comes back
    viewport_marks.unregister()
    overlay.unregister()
    pipeline.shutdown()
    for handlers, func in ((bpy.app.handlers.load_pre, pipeline.on_load_pre),
                           (bpy.app.handlers.load_post, pipeline.on_load_post)):
        if func in handlers:
            handlers.remove(func)
    main_thread.stop()
    panels.unregister()
    operators.unregister()
    props.unregister()
    preferences.unregister()
    catalog.clear()
