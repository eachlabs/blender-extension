"""Refuses Blender Python from the chat model that uses something outside scene building. Pure, no ``bpy``.

This is a filter for honest mistakes and obvious misuse, not a sandbox: Blender's Python can still reach
files and the network in ways a source check cannot see. ``check`` raises ``Refused`` naming the rule.

Module values (``bpy``, ``bpy.ops`` and the like) may only start an attribute chain, be called, or be given
a plain alias (``ops = bpy.ops``), so every path the code uses can be read from the source.

``redact`` replaces exact copies of a secret in anything sent back to the model. It is a guard against
accidents, not against deliberate exfiltration (an encoded or reversed key passes it); the primary guard
is that the ``credentials`` and ``private`` rules keep the code away from the add-on's settings.
"""

import ast
import builtins
import string

from . import thread_safety

ALLOWED_IMPORTS = ("bpy", "bmesh", "mathutils", "math", "random")
STAR_IMPORTS = ("math", "mathutils", "random")  # ``from bpy import *`` would hide which names it binds
OPS_ALLOWED = ("object", "mesh", "curve", "material", "node", "transform", "view3d", "anim", "scene")
BLOCKED_NAMES = frozenset((
    "open", "eval", "exec", "compile", "__import__", "globals", "locals", "vars", "breakpoint", "input",
    "exit", "quit",
))
ATTRIBUTE_FUNCTIONS = frozenset(("getattr", "setattr", "delattr"))
SYSTEM_MODULES = frozenset(("os", "sys", "subprocess", "socket", "shutil", "pathlib", "importlib", "ctypes"))
BLOCKED_PATHS = (
    "bpy.ops.wm", "bpy.ops.preferences", "bpy.ops.extensions", "bpy.data.libraries",
    "bpy.utils.register", "bpy.utils.unregister", "bpy.app.handlers", "bpy.app.timers", "bpy.msgbus",
)
# Module values: they may only start an attribute chain, be called, or be aliased by a plain assignment.
MODULE_PATHS = frozenset(ALLOWED_IMPORTS + (
    "bpy.ops", "bpy.app", "bpy.utils", "bpy.data", "bpy.types", "bpy.props", "bpy.msgbus", "bpy.path",
    "bpy.context", "bpy.app.handlers", "bpy.app.timers", "bpy.app.translations", "bpy.app.icons",
    "bpy.utils.units", "bpy.utils.previews", "bmesh.ops", "bmesh.types", "bmesh.utils", "bmesh.geometry",
    "mathutils.noise", "mathutils.geometry", "mathutils.bvhtree", "mathutils.kdtree", "mathutils.interpolate",
))
ATTR_RULES = {
    "wm": "blocked-api", "handlers": "blocked-api", "timers": "blocked-api", "libraries": "blocked-api",
    "msgbus": "blocked-api", "draw_handler_add": "deferred-code", "draw_handler_remove": "deferred-code",
    "driver_add": "runs-code", "driver_namespace": "runs-code", "expression": "runs-code",
    "as_module": "runs-code", "execfile": "runs-code", "run_script": "runs-code", "texts": "runs-code",
    "save": "file-access", "save_as": "file-access", "save_render": "file-access", "pack": "file-access",
    "unpack": "file-access", "filepath": "file-access", "filepath_raw": "file-access",
    "directory": "file-access", "filename": "file-access",
}
FRAME_ATTRS = frozenset((
    "gi_frame", "cr_frame", "ag_frame", "tb_frame", "tb_next", "f_back", "f_globals", "f_locals", "f_builtins",
    "f_trace", "gi_code", "cr_code", "ag_code", "f_code", "co_code", "co_consts",
))
CODE_OPS = ("bpy.ops.text", "bpy.ops.script")
AUTORUN_WORDS = ("autoexec", "auto_exec", "auto_run")
FILE_ATTRS = frozenset(("filepath", "filepath_raw", "directory", "filename"))
FILE_CALLS = frozenset(("load", "reload"))
FILE_OPS = ("image", "file", "sound")
FILE_OP_WORDS = ("import", "export", "save", "load", "file", "pack")
CREDENTIAL_ATTRS = frozenset(("preferences", "user_preferences", "addons", "AddonPreferences"))
CREDENTIAL_WORDS = ("api_key", "apikey", "token", "secret", "password")
PROPERTY_CALLBACKS = frozenset(("update", "get", "set", "poll"))
ALLOWED_DUNDER_NAMES = frozenset(("__name__",))  # ``if __name__ == "__main__":`` is common and harmless
ALLOWED_DUNDER_METHODS = frozenset(("__init__", "__repr__", "__str__"))
STOP_CATCHERS = frozenset(("BaseException", "GeneratorExit", "KeyboardInterrupt", "SystemExit"))
CATCHABLE = frozenset(name for name, value in vars(builtins).items()
                      if isinstance(value, type) and issubclass(value, Exception))

REDACTED = "[redacted]"

_ALLOWED_TEXT = "Allowed imports: %s." % ", ".join(ALLOWED_IMPORTS)
# What to use instead of a module the model often reaches for. Text only: the rules do not change.
INSTEAD = {
    "re": "use str methods such as split, startswith and replace",
    "collections": "use a plain dict or list",
    "itertools": "use loops",
    "functools": "use loops",
    "statistics": "use sum() and len()",
    "bpy_extras": "use mathutils, and the camera_view tool for what the camera sees",
}
# What to write instead of a refused name the model often reaches for: in the after-test, __import__ made a third of
# the failed steps. Text only: the rules do not change.
NAME_INSTEAD = {
    "__import__": "Every step already has bpy, bmesh, mathutils, math and random imported: use them by name "
                  "(random.Random(seed) for seeded variation); no other module is available.",
    "eval": "Write the expression directly.",
    "exec": "Write the code directly in this step.",
    "globals": "Keep values in variables or a dict of your own.",
    "locals": "Keep values in variables or a dict of your own.",
    "vars": "Read the attributes by name.",
}
PRIVATE_INSTEAD = "Name your own variables and helpers without a leading underscore (helper, not _helper)."
_GEOMETRY = "Use bpy.data and bmesh to build the scene; no file access."
_MESSAGES = {
    "system-module": "`%s` reaches outside Blender. " + _GEOMETRY,
    "blocked-name": "`%s` is not allowed. " + _GEOMETRY,
    "dunder": "`%s` is not allowed; use the plain bpy attributes.",
    "private": "`%s` starts with `_`; names and attributes starting with `_` are not allowed.",
    "frame-access": "`%s` is not allowed; use the plain bpy attributes.",
    "blocked-api": "`%s` is outside scene building. " + _GEOMETRY,
    "runs-code": "`%s` runs other code; write the code in this step instead.",
    "deferred-code": "`%s` would run code later; do the work in this step instead.",
    "file-access": "`%s` reads or writes files. " + _GEOMETRY,
    "ops-module": "`%s` is not allowed; bpy.ops may only use " + ", ".join(OPS_ALLOWED) + ". " + _GEOMETRY,
    "credentials": "`%s`: the chat's code cannot read add-on settings.",
    "module-value": "`%s` may only be used as `%s.something`, called, or named with a plain `name = %s`.",
    "broad-except": "%s",
    "context-override": "`%s` overrides Blender's context, which can crash this Blender while the chat runs; "
                        "call operators without temp_override, or build with bpy.data and bmesh.",
}
# Blender 4.2's own operators, in allowed modules, whose Python calls bpy.ops inside temp_override
# (scripts/startup/bl_operators/object_quick_effects.py). Refused like temp_override on Python before 3.12.
OVERRIDE_OPS = frozenset(("bpy.ops.object.quick_fur", "bpy.ops.object.quick_explode", "bpy.ops.object.quick_smoke",
                          "bpy.ops.object.quick_liquid"))


class Refused(Exception):
    def __init__(self, rule, message):
        super().__init__(rule, message)
        self.rule = rule
        self.message = message

    def __str__(self):
        return "Refused by the %s rule: %s" % (self.rule, self.message)


def _raise(rule, node, detail):
    line = getattr(node, "lineno", None)
    where = "line %d: " % line if line else ""
    raise Refused(rule, "%s%s %s" % (where, detail, _ALLOWED_TEXT))


def _is_dunder(name):
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def _starts(path, prefix):
    return path == prefix or path.startswith(prefix + ".")


def _literal_name(call):
    """The attribute name of ``getattr(x, "name")`` and friends, or ``None`` when it is not a string literal."""
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant) and isinstance(call.args[1].value, str):
        return call.args[1].value
    return None


def _name_rule(name, stored=False):
    """``(rule, subject)`` for a variable name on its own, or ``None``."""
    low = name.lower()
    if name in CREDENTIAL_ATTRS or any(word in low for word in CREDENTIAL_WORDS):
        return "credentials", name
    if name in STOP_CATCHERS:
        return "broad-except", "`%s` is not allowed; catch `Exception` so the time limit can stop the step." % name
    if _is_dunder(name):
        return (None if name in ALLOWED_DUNDER_NAMES else ("dunder", name))
    if name.startswith("_") and name != "_":  # a bare ``_`` is the usual throwaway loop variable
        return "private", name
    if name in SYSTEM_MODULES:
        return "system-module", name
    if any(word in low for word in AUTORUN_WORDS):
        return "runs-code", name
    if stored and name in FILE_ATTRS:  # a keyword argument
        return "file-access", name
    return None


def _attr_rule(name):
    """``(rule, subject)`` for an attribute name, wherever it appears, or ``None``."""
    found = _name_rule(name)
    if found is not None:
        return found
    if name == "_":
        return "private", name
    if name in FRAME_ATTRS:
        return "frame-access", name
    if name == "temp_override" and thread_safety.override_races():
        return "context-override", name
    if name in ATTR_RULES:
        return ATTR_RULES[name], name
    if name.startswith(("register", "unregister")) or "_OT_" in name:
        return "blocked-api", name
    return None


def _path_rule(path):
    """``(rule, subject)`` for a dotted path rooted at a module, or ``None``."""
    if not path:
        return None
    if _starts(path, "bpy.context.preferences") or path.startswith("bpy.types.AddonPreferences"):
        return "credentials", path
    for blocked in BLOCKED_PATHS:
        if _starts(path, blocked) or (blocked.endswith("register") and path.startswith(blocked)):
            return "blocked-api", blocked
    for prefix in CODE_OPS:
        if _starts(path, prefix):
            return "runs-code", prefix
    parts = path.split(".")
    if len(parts) >= 3 and parts[:2] == ["bpy", "ops"]:
        module = parts[2]
        if module.startswith(("export_", "import_")) or module in FILE_OPS:
            return "file-access", "bpy.ops." + module
        if module not in OPS_ALLOWED:
            return "ops-module", "bpy.ops." + module
        if len(parts) >= 4 and any(word in parts[3] for word in FILE_OP_WORDS):
            return "file-access", ".".join(parts[:4])
        if ".".join(parts[:4]) in OVERRIDE_OPS and thread_safety.override_races():
            return "context-override", ".".join(parts[:4])
    return None


def _is_module_value(path):
    return bool(path) and (path in MODULE_PATHS or (path.startswith("bpy.ops.") and path.count(".") == 2))


class _Checker:
    def __init__(self, tree):
        self.tree = tree
        self.aliases = {name: name for name in ALLOWED_IMPORTS}  # local name -> dotted module path
        self.parents = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                self.parents[id(child)] = parent

    def dotted(self, node):
        """``bpy.ops.wm`` for an attribute chain rooted at a known module alias, else ``None``."""
        if isinstance(node, ast.Name):
            return self.aliases.get(node.id)
        if isinstance(node, ast.Attribute):
            base = self.dotted(node.value)
            return base + "." + node.attr if base else None
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
                and node.args):
            base, name = self.dotted(node.args[0]), _literal_name(node)
            return base + "." + name if base and name else None
        return None

    def collect_aliases(self):
        """Names bound by imports and by plain ``name = <module path>`` assignments, until nothing changes."""
        for _ in range(8):
            before = dict(self.aliases)
            for node in ast.walk(self.tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.asname:
                            self.aliases[alias.asname] = alias.name
                        else:
                            root = alias.name.split(".")[0]
                            self.aliases[root] = root
                elif isinstance(node, ast.ImportFrom) and node.module:
                    for alias in node.names:
                        if alias.name != "*":
                            self.aliases[alias.asname or alias.name] = node.module + "." + alias.name
                elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                    path = self.dotted(node.value)
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Name) and path:
                            self.aliases[target.id] = path
            if self.aliases == before:
                return

    @staticmethod
    def refuse(node, found):
        if found is not None:
            rule, subject = found
            text = _MESSAGES[rule] % ((subject,) * _MESSAGES[rule].count("%s"))
            instead = NAME_INSTEAD.get(subject) or (PRIVATE_INSTEAD if rule == "private" else "")
            _raise(rule, node, text + (" " + instead if instead else ""))

    def check_import(self, node):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
            paths = list(modules)
        else:
            if node.level:
                _raise("import", node, "Relative imports are not allowed.")
            modules = [node.module]
            paths = [node.module + "." + alias.name for alias in node.names if alias.name != "*"]
            if any(alias.name == "*" for alias in node.names) and node.module not in STAR_IMPORTS:
                _raise("import", node, "`from %s import *` is not allowed; import the names you use." % node.module)
        for module in modules:
            root = module.split(".")[0]
            if root in SYSTEM_MODULES:
                self.refuse(node, ("system-module", root))
            if root not in ALLOWED_IMPORTS:
                instead = INSTEAD.get(root)
                _raise("import", node, "`%s` is not allowed%s." % (module, "; " + instead if instead else ""))
        for path in paths:
            self.refuse(node, _path_rule(path))
            for part in path.split("."):
                self.refuse(node, _attr_rule(part))
        for alias in node.names:
            if alias.asname:
                self.refuse(node, _name_rule(alias.asname))

    def check_module_value(self, node):
        """A module value used anywhere but as an attribute base, a callee or a plain alias is refused."""
        if isinstance(getattr(node, "ctx", None), (ast.Store, ast.Del)):
            return
        path = self.dotted(node)
        if not _is_module_value(path):
            return
        parent = self.parents.get(id(node))
        if isinstance(parent, ast.Attribute) and parent.value is node:
            return
        if isinstance(parent, ast.Call) and (parent.func is node or (
                isinstance(parent.func, ast.Name) and parent.func.id in ("getattr", "hasattr")
                and parent.args and parent.args[0] is node and _literal_name(parent) is not None)):
            return
        if (isinstance(parent, (ast.Assign, ast.AnnAssign)) and parent.value is node
                and all(isinstance(t, ast.Name) for t in getattr(parent, "targets", [getattr(parent, "target", None)]))):
            return
        self.refuse(node, ("module-value", path))

    def check_call(self, node):
        func = node.func
        if isinstance(func, ast.Name) and func.id in ATTRIBUTE_FUNCTIONS:
            name = _literal_name(node)
            if name is None:
                _raise("dynamic-attribute", node,
                       "`%s` needs a plain string name, like %s(obj, \"location\"%s); write one line per "
                       "attribute." % (
                           func.id, func.id, ", value" if func.id == "setattr" else ""))
            self.refuse(node, _attr_rule(name))
            self.refuse(node, _path_rule(self.dotted(node)))  # getattr(bpy.ops, "wm")
            if func.id == "setattr":
                self.check_store(node, self.dotted(node.args[0]) if node.args else None)
        path = self.dotted(func)
        self.refuse(node, _path_rule(path))
        for keyword in node.keywords:
            if keyword.arg is None and path and path.startswith("bpy."):
                _raise("file-access", node, "Pass bpy options by name, not with `**`.")
            if keyword.arg is not None:
                self.refuse(node, _name_rule(keyword.arg, stored=True))
        if path and path.startswith("bpy.props.") and any(k.arg in PROPERTY_CALLBACKS for k in node.keywords):
            self.refuse(node, ("deferred-code", path + "(update/get/set=...)"))
        if isinstance(func, ast.Attribute) and func.attr in FILE_CALLS:
            self.refuse(node, ("file-access", "." + func.attr + "()"))
        if isinstance(func, ast.Attribute) and func.attr in ("format", "format_map") and isinstance(
                func.value, ast.Constant) and isinstance(func.value.value, str):
            try:
                fields = [f for _, f, _, _ in string.Formatter().parse(func.value.value) if f]
            except ValueError:
                fields = []
            if any("." in f or "[" in f for f in fields):
                _raise("private", node, "Format fields may not read attributes or items; use an f-string.")

    def check_store(self, node, path):
        """Writing onto ``bpy.types`` adds properties or callbacks Blender runs later."""
        if path and _starts(path, "bpy.types"):
            self.refuse(node, ("deferred-code", path + " = ..."))

    @staticmethod
    def check_parent_inverse(node):
        """``x.matrix_parent_inverse = root.matrix_world.inverted()``: a root made in this step has no world matrix
        yet, so the part lands at twice the root's offset. Not unsafe, only wrong, and attach() does it right."""
        value = node.value
        if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                and value.func.attr in ("inverted", "inverted_safe")
                and isinstance(value.func.value, ast.Attribute) and value.func.value.attr == "matrix_world"):
            return
        if any(isinstance(t, ast.Attribute) and t.attr == "matrix_parent_inverse" for t in node.targets):
            raise Refused("parenting", "line %d: matrix_parent_inverse = <root>.matrix_world.inverted() puts the part "
                          "at twice the root's offset when the root was made in this step. Call attach(part, root) "
                          "instead; every step has it defined, and it keeps the part where it stands." % node.lineno)

    def check_handler(self, node):
        if node.type is None:
            _raise("broad-except", node, "Catch `Exception`, not everything, so the time limit can stop the step.")
        names = node.type.elts if isinstance(node.type, ast.Tuple) else [node.type]
        for name in names:
            if not (isinstance(name, ast.Name) and name.id in CATCHABLE):
                _raise("broad-except", node, "`except` may only name built-in exceptions such as `Exception` or "
                                             "`KeyError`.")

    def run(self):
        self.collect_aliases()
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self.check_import(node)
            elif isinstance(node, ast.Name):
                if node.id in BLOCKED_NAMES:
                    self.refuse(node, ("blocked-name", node.id))
                self.refuse(node, _name_rule(node.id))
                if node.id in ATTRIBUTE_FUNCTIONS and not (
                        isinstance(self.parents.get(id(node)), ast.Call) and self.parents[id(node)].func is node):
                    _raise("dynamic-attribute", node, "`%s` may only be called directly." % node.id)
                self.check_module_value(node)
            elif isinstance(node, ast.Attribute):
                self.refuse(node, _path_rule(self.dotted(node)))
                self.refuse(node, _attr_rule(node.attr))
                if isinstance(node.ctx, ast.Store):
                    self.check_store(node, self.dotted(node.value))
                self.check_module_value(node)
            elif isinstance(node, ast.Call):
                self.check_call(node)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if _is_dunder(node.name):
                    if node.name not in ALLOWED_DUNDER_METHODS:
                        self.refuse(node, ("dunder", "def " + node.name))
                else:
                    self.refuse(node, _name_rule(node.name))
            elif isinstance(node, ast.arg):
                self.refuse(node, _name_rule(node.arg))
            elif isinstance(node, ast.ExceptHandler):
                self.check_handler(node)
            elif isinstance(node, ast.Assign):
                self.check_parent_inverse(node)
            elif isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
                for inner in (n for stmt in node.finalbody for n in ast.walk(stmt)):
                    if isinstance(inner, (ast.Return, ast.Break, ast.Continue)):
                        _raise("broad-except", inner, "No `return`, `break` or `continue` inside `finally`; it "
                                                      "would hide the time limit's stop.")
            elif isinstance(node, ast.Subscript):
                key = node.slice
                if isinstance(key, ast.Constant) and isinstance(key.value, str):  # prefs["api_key"]
                    found = _name_rule(key.value)
                    self.refuse(node, found if found and found[0] in ("credentials", "private", "dunder") else None)


def check(code):
    """Raise ``Refused`` when ``code`` breaks a rule; return ``None`` when it may run."""
    try:
        tree = ast.parse(code, "<step>")
    except SyntaxError as exc:
        raise Refused("syntax", "line %s: %s" % (exc.lineno, exc.msg)) from None
    except ValueError as exc:  # null bytes in the source
        raise Refused("syntax", str(exc)) from None
    _Checker(tree).run()


def redact(value, secrets):
    """``value`` with every exact copy of a secret replaced by ``[redacted]``, through dicts, lists and tuples.

    A secret shorter than 4 characters is ignored, since replacing it would garble ordinary text."""
    secrets = sorted({s for s in secrets or () if isinstance(s, str) and len(s) >= 4}, key=len, reverse=True)
    if not secrets:
        return value

    def walk(item):
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, REDACTED)
            return item
        if isinstance(item, dict):
            return {walk(k): walk(v) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return type(item)(walk(v) for v in item)
        return item
    return walk(value)
