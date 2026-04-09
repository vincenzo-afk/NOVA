"""Plugin auto-loader."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any
import ast

from pydantic import BaseModel, create_model


# Fix 4.4: Restricted namespace for plugin sandboxing
_BLOCKED_IMPORTS = {
    "subprocess",
    "os",
    "socket",
    "sys",
    "requests",
    "urllib",
    "urllib3",
    "http",
    "http.client",
    "ssl",
    "ftplib",
    "smtplib",
    "pathlib",
    "io",
    "tempfile",
    "shutil",
    "pathlib",
    "importlib",
    "importlib.util",
    "importlib.machinery",
    "importlib.abc",
    "ctypes",
    "_ctypes",
    "_io",
    "signal",
    "multiprocessing",
    "threading",
    "builtins",
    "_thread",
    "gc",
    "weakref",
}


def _restricted_import(name: str, *args, **kwargs):
    """Block dangerous imports in plugins."""
    lowered = (name or "").strip().lower()
    if lowered in _BLOCKED_IMPORTS or lowered.startswith("_"):
        raise ImportError(f"Plugin attempted to import blocked module: {name}")
    import builtins
    return builtins.__import__(name, *args, **kwargs)

def _check_ast(source: str):
    tree = ast.parse(source)
    restricted = {
        "__class__", "__mro__", "__subclasses__", "__globals__", "__builtins__",
        "__bases__", "__code__", "__func__", "__closure__", "__dict__", "__module__", "__getattribute__",
        "eval", "exec", "compile", "getattr", "setattr", "delattr",
        "vars", "locals", "globals", "dir", "hasattr", "__import__",
    }
    restricted_builtin_keys = {
        "eval", "exec", "compile", "__import__", "open", "getattr", "setattr", "delattr",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in restricted:
            raise ValueError(f"Restricted identifier used: {node.id}")
        if isinstance(node, ast.Attribute) and node.attr in restricted:
            raise ValueError(f"Restricted attribute used: {node.attr}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and node.args[1].value in restricted
        ):
            raise ValueError(f"Restricted getattr target used: {node.args[1].value}")
        if isinstance(node, ast.Subscript):
            target_name = node.value.id if isinstance(node.value, ast.Name) else ""
            if target_name == "__builtins__":
                key_node = node.slice
                if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                    if key_node.value in restricted_builtin_keys:
                        raise ValueError(f"Restricted __builtins__ key access: {key_node.value}")


def load_plugins(dispatcher, plugin_dir: str = "plugins") -> list[str]:
    import logging
    loaded = []
    tool_owners: dict[str, str] = {}
    for path in Path(plugin_dir).glob("*.py"):
        spec = spec_from_file_location(path.stem, path)
        if not spec or not spec.loader:
            continue
        module = module_from_spec(spec)
        # Fix 4.4: Execute plugin in restricted namespace
        import builtins
        allowed_builtin_names = {
            "abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "isinstance",
            "len", "list", "max", "min", "pow", "print", "range", "reversed", "round",
            "set", "slice", "sorted", "str", "sum", "tuple", "zip", "map", "filter",
        }
        safe_builtins = {k: v for k, v in vars(builtins).items() if k in allowed_builtin_names}
        safe_builtins["__import__"] = _restricted_import
        restricted_globals = {
            "__builtins__": safe_builtins,
        }
        try:
            source = path.read_text(encoding="utf-8")
            _check_ast(source)
            code = compile(source, str(path), "exec")
            exec(code, restricted_globals)
        except Exception as exc:
            print(f"[plugin] Blocked dangerous import or error in {path.name}: {exc}")
            continue
            
        tools = restricted_globals.get("PLUGIN_TOOLS", [])
        for tool in tools:
            name = tool["name"]
            if name in dispatcher.registry:
                owner = tool_owners.get(name, "builtin/previous registration")
                logging.getLogger(__name__).warning(
                    "Plugin tool '%s' in %s conflicts with existing '%s'; skipping this tool.",
                    name,
                    path.name,
                    owner,
                )
                print(f"[plugin] Conflict: tool '{name}' in {path.name} skipped (already provided by {owner}).")
                continue
            fn_name = tool.get("fn") or tool.get("function") or name
            fn = restricted_globals.get(fn_name)
            if not fn:
                continue
            schema = _resolve_schema(tool, restricted_globals)
            dispatcher.register(name, fn, schema)
            tool_owners[name] = path.name
        loaded.append(path.name)
    return loaded


def _resolve_schema(tool: dict[str, Any], module: Any) -> type[BaseModel]:
    schema = tool.get("schema")
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema
    if isinstance(schema, str):
        candidate = module.get(schema) if isinstance(module, dict) else getattr(module, schema, None)
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return candidate

    args = tool.get("args")
    if isinstance(args, dict):
        fields = {name: (Any, None) for name in args.keys()}
        return create_model(f"{tool['name'].replace('.', '_')}_Args", **fields)

    return create_model(f"{tool['name'].replace('.', '_')}_Args")
