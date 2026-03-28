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
    "ctypes",
    "signal",
    "multiprocessing",
    "threading",
}


def _restricted_import(name: str, *args, **kwargs):
    """Block dangerous imports in plugins."""
    if name in _BLOCKED_IMPORTS:
        raise ImportError(f"Plugin attempted to import blocked module: {name}")
    import builtins
    return builtins.__import__(name, *args, **kwargs)

def _check_ast(source: str):
    tree = ast.parse(source)
    restricted = {"__class__", "__mro__", "__subclasses__", "__globals__", "__builtins__", "eval", "exec"}
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


def load_plugins(dispatcher, plugin_dir: str = "plugins") -> list[str]:
    loaded = []
    for path in Path(plugin_dir).glob("*.py"):
        spec = spec_from_file_location(path.stem, path)
        if not spec or not spec.loader:
            continue
        module = module_from_spec(spec)
        # Fix 4.4: Execute plugin in restricted namespace
        import builtins
        safe_builtins = {
            k: v for k, v in vars(builtins).items()
            if k not in {"__import__", "open"}
        }
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
                import logging
                logging.getLogger(__name__).warning("Plugin attempted to shadow builtin tool '%s'. Skipping.", name)
                continue
            fn_name = tool.get("fn") or tool.get("function") or name
            fn = restricted_globals.get(fn_name)
            if not fn:
                continue
            schema = _resolve_schema(tool, restricted_globals)
            dispatcher.register(name, fn, schema)
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
