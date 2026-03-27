"""Plugin auto-loader."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

from pydantic import BaseModel, create_model


# Fix 4.4: Restricted namespace for plugin sandboxing
_BLOCKED_IMPORTS = {
    "subprocess",
    "os",
    "socket",
    "sys",
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
    return __builtins__["__import__"](name, *args, **kwargs)


def load_plugins(dispatcher, plugin_dir: str = "plugins") -> list[str]:
    loaded = []
    for path in Path(plugin_dir).glob("*.py"):
        spec = spec_from_file_location(path.stem, path)
        if not spec or not spec.loader:
            continue
        module = module_from_spec(spec)
        # Fix 4.4: Execute plugin in restricted namespace
        restricted_globals = {
            "__builtins__": {k: v for k, v in __builtins__.items() if k != "__import__"},
            "__import__": _restricted_import,
        }
        try:
            spec.loader.exec_module(module, restricted_globals)
        except ImportError as exc:
            print(f"[plugin] Blocked dangerous import in {path.name}: {exc}")
            continue
        tools = getattr(module, "PLUGIN_TOOLS", [])
        for tool in tools:
            name = tool["name"]
            fn_name = tool.get("fn") or tool.get("function") or name
            fn = getattr(module, fn_name)
            schema = _resolve_schema(tool, module)
            dispatcher.register(name, fn, schema)
        loaded.append(path.name)
    return loaded


def _resolve_schema(tool: dict[str, Any], module: Any) -> type[BaseModel]:
    schema = tool.get("schema")
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema
    if isinstance(schema, str):
        candidate = getattr(module, schema, None)
        if isinstance(candidate, type) and issubclass(candidate, BaseModel):
            return candidate

    args = tool.get("args")
    if isinstance(args, dict):
        fields = {name: (Any, None) for name in args.keys()}
        return create_model(f"{tool['name'].replace('.', '_')}_Args", **fields)

    return create_model(f"{tool['name'].replace('.', '_')}_Args")
