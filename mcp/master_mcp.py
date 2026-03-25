"""Dynamic MCP orchestrator scaffold."""

from __future__ import annotations

from typing import Any, Callable


class MasterMCP:
    def __init__(self):
        self._servers: dict[str, dict[str, Any]] = {}

    def connect(self, service: str, config: dict) -> None:
        self._servers[service.lower()] = config

    def is_connected(self, service: str) -> bool:
        return service.lower() in self._servers

    def list_services(self) -> list[str]:
        return sorted(self._servers)

    def list_tools(self, service: str | None = None) -> list[dict]:
        if service:
            return list(self._servers.get(service.lower(), {}).get("tools", []))
        tools: list[dict] = []
        for svc, config in self._servers.items():
            for tool in config.get("tools", []):
                tools.append({"service": svc, **tool})
        return tools

    def call_tool(self, service: str, tool_name: str, **kwargs):
        server = self._servers.get(service.lower())
        if not server:
            return {"error": f"service_not_connected: {service}"}

        handlers: dict[str, Callable[..., Any]] = server.get("handlers", {})
        fn = handlers.get(tool_name)
        if fn is None:
            return {"error": f"tool_not_found: {tool_name}"}
        return fn(**kwargs)
