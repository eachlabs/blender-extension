"""What each model or workflow accepts and produces, using only metadata the API declares.

The catalog declares a model's output (``output_type``) and its input/output categories
(``category.Slug`` such as ``image-to-video``) but not which request field takes which media, or
which field is a first or last frame. Bindings are therefore chosen by the user unless the declared
metadata leaves exactly one sensible choice. See ``docs/architecture.md``.
"""

from dataclasses import dataclass, field

IMAGE = "IMAGE"
VIDEO = "VIDEO"

MODEL = "model"
WORKFLOW = "workflow"

# Conditioning inputs produced by render export. Adding a pass (depth, mask) means adding a role here
# and an exporter in render_export; bindings, uploads and re-run handle roles generically.
SOURCES = {
    "still": {"label": "Rendered still", "media": "image", "actions": (IMAGE,)},
    "clip": {"label": "Clip (MP4)", "media": "video", "actions": (VIDEO,)},
    "first_frame": {"label": "First frame", "media": "image", "actions": (VIDEO,)},
    "last_frame": {"label": "Last frame", "media": "image", "actions": (VIDEO,)},
    # A file the user picks (style frame, character sheet, reference audio); its role is per field.
    "file": {"label": "File…", "media": None, "actions": (IMAGE, VIDEO)},
}
FILE = "file"

# The source used when a target has a single input of a declared media kind.
PRIMARY_SOURCE = {
    (IMAGE, "image"): "still",
    (VIDEO, "video"): "clip",
    (VIDEO, "image"): "first_frame",
}

ACCEPTED_INPUTS = {
    IMAGE: frozenset(("image",)),
    VIDEO: frozenset(("image", "video", "reference")),
}

WORKFLOW_MEDIA_TYPES = frozenset(("image", "video"))


@dataclass
class InputField:
    name: str
    title: str
    is_array: bool = False
    required: bool = False
    media: str = None  # Declared media kind (workflows only); models do not declare one.
    description: str = ""


@dataclass
class Param:
    name: str
    title: str
    type: str  # "enum", "int", "float", "bool" or "string"
    choices: tuple = ()
    default: object = None
    minimum: float = None
    maximum: float = None
    required: bool = False
    description: str = ""


@dataclass
class Target:
    kind: str
    key: str
    title: str
    output_kind: str = None
    input_kinds: frozenset = frozenset()
    category: str = ""
    fields: list = field(default_factory=list)
    params: list = field(default_factory=list)
    required: frozenset = frozenset()
    defaults: dict = field(default_factory=dict)
    has_prompt: bool = False
    has_seed: bool = False
    version_id: str = None
    price: str = None

    @property
    def label(self):
        if self.kind == WORKFLOW:
            return "%s [workflow]" % self.title
        return "%s [%s]" % (self.title, self.key)


def _schema_type(prop):
    value = prop.get("type")
    if isinstance(value, list):
        value = next((t for t in value if t != "null"), None)
    if value is None and isinstance(prop.get("anyOf"), list):
        for option in prop["anyOf"]:
            if isinstance(option, dict) and option.get("type") not in (None, "null"):
                return option["type"]
    return value


def _is_uri(prop):
    return "uri" in str(prop.get("format") or "")


def _uri_field(name, prop, required):
    items = prop.get("items") if isinstance(prop.get("items"), dict) else {}
    if _is_uri(prop):
        return InputField(name, prop.get("title") or name, False, name in required, None, prop.get("description") or "")
    if _schema_type(prop) == "array" and _is_uri(items):
        return InputField(name, prop.get("title") or name, True, name in required, None, prop.get("description") or "")
    return None


def _param(name, prop, required):
    kind = _schema_type(prop)
    common = dict(title=prop.get("title") or name, default=prop.get("default"), required=name in required,
                  description=prop.get("description") or "")
    enum = prop.get("enum")
    if isinstance(enum, list) and enum:
        choices = tuple(v for v in enum if v is not None)
        if choices:
            return Param(name, type="enum", choices=choices, **common)
    if kind == "integer":
        return Param(name, type="int", minimum=prop.get("minimum"), maximum=prop.get("maximum"), **common)
    if kind == "number":
        return Param(name, type="float", minimum=prop.get("minimum"), maximum=prop.get("maximum"), **common)
    if kind == "boolean":
        return Param(name, type="bool", **common)
    if kind == "string" and not prop.get("format"):
        return Param(name, type="string", **common)
    return None


def _category_parts(slug):
    if "-to-" not in (slug or ""):
        return None, None
    source, _, output = slug.partition("-to-")
    return source, output


def model_target(entry):
    """Build a Target from one ``GET /v1/models`` entry."""
    category = entry.get("category") or {}
    if isinstance(category, dict):
        slug = category.get("Slug") or category.get("slug") or ""
    else:
        slug = str(category)
    source_kind, category_output = _category_parts(slug)
    output_type = str(entry.get("output_type") or "").lower()
    output_kind = output_type if output_type in ("image", "video") else (
        category_output if category_output in ("image", "video") else None)
    schema = entry.get("request_schema") or {}
    props = schema.get("properties") or {}
    required = frozenset(schema.get("required") or ())
    target = Target(
        kind=MODEL,
        key=entry.get("slug") or "",
        title=entry.get("title") or entry.get("name") or entry.get("slug") or "",
        output_kind=output_kind,
        input_kinds=frozenset((source_kind,)) if source_kind else frozenset(),
        category=slug,
        required=required,
    )
    for name, prop in props.items():
        if not isinstance(prop, dict):
            continue
        if "default" in prop:
            target.defaults[name] = prop["default"]
        uri = _uri_field(name, prop, required)
        if uri:
            target.fields.append(uri)
        elif name == "prompt" and _schema_type(prop) == "string":
            target.has_prompt = True
        elif name == "seed" and _schema_type(prop) in ("integer", "number"):
            target.has_seed = True
        else:
            param = _param(name, prop, required)
            if param:
                target.params.append(param)
    return target


def pick_version(versions):
    """The version to trigger: the production one, else the most recently updated active one."""
    active = [v for v in versions or () if v.get("status", "active") == "active"]
    for version in active:
        if version.get("production"):
            return version
    published = [v for v in active if v.get("published")]
    pool = published or active
    if not pool:
        return None
    return max(pool, key=lambda v: v.get("updated_at") or v.get("created_at") or "")


def workflow_target(detail):
    """Build a Target from ``GET /v1/workflows/{id}``; ``None`` when no version has a definition."""
    version = pick_version(detail.get("versions"))
    if not version or not isinstance(version.get("definition"), dict):
        return None
    props = (version["definition"].get("input_schema") or {}).get("properties") or {}
    target = Target(
        kind=WORKFLOW,
        key=detail.get("workflow_id") or "",
        title=detail.get("name") or detail.get("slug") or "",
        version_id=version.get("version_id"),
        category=",".join(detail.get("categories") or ()),
    )
    required = set()
    for name, spec in props.items():
        if not isinstance(spec, dict):
            continue
        kind = spec.get("type")
        if spec.get("required"):
            required.add(name)
        if "default_value" in spec:
            target.defaults[name] = spec["default_value"]
        description = spec.get("description") or ""
        if kind in WORKFLOW_MEDIA_TYPES:
            target.fields.append(InputField(name, name, False, bool(spec.get("required")), kind, description))
        elif name == "prompt" and kind == "string":
            target.has_prompt = True
        elif name == "seed" and kind == "number":
            target.has_seed = True
        elif kind in ("string", "number", "boolean"):
            ptype = {"string": "string", "number": "float", "boolean": "bool"}[kind]
            target.params.append(Param(name, name, ptype, default=spec.get("default_value"),
                                       required=bool(spec.get("required")), description=description))
    target.required = frozenset(required)
    target.input_kinds = frozenset(f.media for f in target.fields)
    return target


def offers(target, action, show_all=False):
    """Whether a target is listed for an action."""
    if not target.fields:
        return False
    if target.kind == WORKFLOW:
        wanted = ("image",) if action == IMAGE else ("image", "video")
        return any(f.media in wanted for f in target.fields)
    wanted_output = "image" if action == IMAGE else "video"
    if target.output_kind != wanted_output:
        return False
    return show_all or bool(target.input_kinds & ACCEPTED_INPUTS[action])


def sources_for(action):
    return [role for role, spec in SOURCES.items() if action in spec["actions"]]


def default_bindings(target, action):
    """Pre-selected ``{field: role}`` bindings; empty unless declared metadata makes one obvious."""
    if target.kind == WORKFLOW:
        bindings = {}
        for media in ("image", "video"):
            matching = [f for f in target.fields if f.media == media]
            role = PRIMARY_SOURCE.get((action, media))
            if role and len(matching) == 1:
                bindings[matching[0].name] = role
        return bindings
    if len(target.fields) != 1:
        return {}
    declared = [k for k in target.input_kinds if k in ("image", "video")]
    if len(declared) != 1:
        return {}
    role = PRIMARY_SOURCE.get((action, declared[0]))
    return {target.fields[0].name: role} if role else {}


def build_input(target, bindings, urls, prompt="", seed=None, params=None, extra=None):
    """The request ``input``/``inputs`` object for a target.

    ``bindings`` maps field names to source roles, ``urls`` maps roles to public URLs.
    """
    values = {}
    by_name = {f.name: f for f in target.fields}
    for name, role in (bindings or {}).items():
        if not role or name not in by_name or role not in urls:
            continue
        values[name] = [urls[role]] if by_name[name].is_array else urls[role]
    if target.has_prompt and prompt and prompt.strip():
        values["prompt"] = prompt.strip()
    if target.has_seed and seed is not None:
        values["seed"] = int(seed)
    values.update(params or {})
    values.update(extra or {})
    for name in target.required:
        if name not in values and name in target.defaults and target.defaults[name] is not None:
            values[name] = target.defaults[name]
    return values


def file_role(field_name):
    """Upload role for a field bound to a user-picked file; one per field so files stay distinct."""
    return "%s:%s" % (FILE, field_name)


def match_duration(target, seconds):
    """``(name, value)`` for the target's ``duration`` input closest to covering ``seconds``.

    Enumerated durations (Seedance sends them as strings, such as ``"10"``) pick the shortest choice
    that is at least the rendered length, else the longest; numeric ones round and clamp. Returns
    ``None`` when the target has no duration input.
    """
    param = next((p for p in target.params if p.name == "duration"), None)
    if param is None or seconds <= 0:
        return None
    if param.type == "enum":
        numeric = []
        for choice in param.choices:
            try:
                numeric.append((float(choice), choice))
            except (TypeError, ValueError):
                continue
        if not numeric:
            return None
        numeric.sort()
        covering = [choice for value, choice in numeric if value >= seconds - 0.05]
        return param.name, covering[0] if covering else numeric[-1][1]
    if param.type in ("int", "float"):
        value = round(seconds) if param.type == "int" else round(seconds, 2)
        if param.minimum is not None:
            value = max(value, param.minimum)
        if param.maximum is not None:
            value = min(value, param.maximum)
        return param.name, int(value) if param.type == "int" else float(value)
    return None


def missing_required(target, values):
    return sorted(name for name in target.required if values.get(name) in (None, "", []))


def bound_roles(bindings):
    return sorted({role for role in (bindings or {}).values() if role})
