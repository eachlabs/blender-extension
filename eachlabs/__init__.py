"""Eachlabs Blender extension: send renders to Eachlabs models and workflows, get results back.

Submodules that import ``bpy`` are loaded in ``register()`` so the pure modules (``api_client``,
``capabilities``, ``jobs``, ``naming``, ``timing``) stay importable for unit tests outside Blender.
"""

VERSION = "0.1.0"


def register():
    import bpy

    from . import main_thread, operators, panels, pipeline, preferences, props

    preferences.register()
    props.register()
    operators.register()
    panels.register()
    main_thread.add_hook(pipeline.tick_hook)
    main_thread.start()
    bpy.app.handlers.load_pre.append(pipeline.on_load_pre)
    bpy.app.handlers.load_post.append(pipeline.on_load_post)


def unregister():
    import bpy

    from . import catalog, main_thread, operators, panels, pipeline, preferences, props

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
