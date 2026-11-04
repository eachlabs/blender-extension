"""The inputs a render job sends: the target's inputs from its schema, parameters and the request body."""

import bpy
import json
import os

from . import capabilities as caps, catalog, naming


class Problem(Exception):
    """A user-facing reason an action cannot start."""



def _action_of(settings):
    return caps.IMAGE if settings.path_from_id().endswith("image") else caps.VIDEO



def on_target_changed(context, settings):
    target = catalog.resolve(settings.target)
    if target is None:
        if not settings.target:
            settings.bindings.clear()
            settings.params.clear()
            settings.bound_key = ""
        return
    if settings.bound_key != target.key:
        rebuild_inputs(settings, target, _action_of(settings))
    if target.kind == caps.MODEL:
        catalog.fetch_cost(target.key, context)



def rebuild_inputs(settings, target, action):
    settings.bindings.clear()
    defaults = caps.default_bindings(target, action)
    for field in target.fields:
        item = settings.bindings.add()
        item.name = field.name
        item.title = field.title
        item.action = action
        item.media = field.media or ""
        item.is_array = field.is_array
        item.required = field.required
        item.description = field.description[:500]
        item.source = defaults.get(field.name, "NONE")
    settings.params.clear()
    for param in target.params:
        item = settings.params.add()
        item.name = param.name
        item.title = param.title
        item.kind = param.type
        item.target_key = target.key
        item.required = param.required
        item.description = param.description[:500]
        item.enabled = param.required and param.default is None
        if param.type == "enum":
            catalog.register_enum(target.key, param)
            if param.default is not None and param.default in param.choices:
                item.value_enum = str(param.default)
        elif param.default is not None:
            try:
                setattr(item, "value_" + {"int": "int", "float": "float", "bool": "bool"}.get(param.type, "string"),
                        param.default if param.type != "string" else str(param.default))
            except (TypeError, ValueError, OverflowError):
                pass
    settings.bound_key = target.key



def _param_value(item):
    if item.kind == "enum":
        return catalog.enum_value(item.target_key, item.name, item.value_enum)
    return getattr(item, "value_" + {"int": "int", "float": "float", "bool": "bool"}.get(item.kind, "string"))



def build_request(settings, action, seconds=None, match_duration=False):
    """Resolve the target and turn the panel into ``(target, base_input, url_fields, files)``.

    ``files`` holds user-picked files bound to inputs; ``seconds`` is the rendered length, used to
    request a matching duration when ``match_duration`` is on and the user set none.
    """
    target = catalog.resolve(settings.target)
    if target is None:
        raise Problem("Choose a model or workflow first (refresh the list if it is empty).")
    if settings.bound_key != target.key:
        rebuild_inputs(settings, target, action)
    bindings, files = {}, {}
    for binding in settings.bindings:
        if binding.source == "NONE":
            continue
        if binding.source != caps.FILE:
            bindings[binding.name] = binding.source
            continue
        path = bpy.path.abspath(binding.filepath) if binding.filepath else ""
        if not os.path.isfile(path):
            raise Problem("Pick the file to send as %s." % binding.name)
        role = caps.file_role(binding.name)
        files[role] = {"path": path, "content_type": naming.content_type_for(path), "media": naming.upload_kind(path)}
        bindings[binding.name] = role
    if not any(role in caps.SOURCES for role in bindings.values()):
        raise Problem("Choose which input of %s receives the render." % target.title)
    extra = {}
    if settings.extra_json.strip():
        try:
            extra = json.loads(settings.extra_json)
        except ValueError as exc:
            raise Problem("Extra inputs is not valid JSON: %s" % exc)
        if not isinstance(extra, dict):
            raise Problem('Extra inputs must be a JSON object such as {"num_images": 2}.')
    params = {p.name: _param_value(p) for p in settings.params if p.enabled}
    if match_duration and seconds:
        matched = caps.match_duration(target, seconds)
        if matched and matched[0] not in params and matched[0] not in extra:
            params[matched[0]] = matched[1]
    placeholders = {role: "https://pending.invalid/" + role for role in caps.bound_roles(bindings)}
    values = caps.build_input(target, bindings, placeholders, settings.prompt,
                              settings.seed if settings.use_seed else None, params, extra)
    missing = caps.missing_required(target, values)
    if missing:
        raise Problem("%s needs: %s." % (target.title, ", ".join(missing)))
    by_name = {f.name: f for f in target.fields}
    url_fields = {name: (role, by_name[name].is_array) for name, role in bindings.items() if name not in extra}
    base_input = {k: v for k, v in values.items() if k not in url_fields}
    return target, base_input, url_fields, files



def _set_param(item, value):
    try:
        if item.kind == "enum":
            identifiers = {identifier for identifier, _, _ in catalog.enum_items(item.target_key, item.name)}
            if str(value) not in identifiers:
                return False
            item.value_enum = str(value)
        elif item.kind in ("int", "float", "bool"):
            setattr(item, "value_" + item.kind, value)
        else:
            item.value_string = str(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return True



def last_inputs(settings):
    if not settings.last_inputs:
        return None
    try:
        data = json.loads(settings.last_inputs)
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("files") else None
