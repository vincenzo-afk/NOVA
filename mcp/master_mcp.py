"""Dynamic MCP orchestrator for local handlers and HTTP MCP servers."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable

import requests


BUILTIN_SERVICES = {
    "github",
    "notion",
    "slack",
    "linear",
    "google_drive",
    "jira",
}


@dataclass
class ServiceConfig:
    service: str
    kind: str  # local | http
    tools: list[dict[str, Any]]
    handlers: dict[str, Callable[..., Any]]
    endpoint: str = ""
    headers: dict[str, str] | None = None
    timeout_seconds: int = 20


class MasterMCP:
    def __init__(
        self,
        max_retries: int = 2,
        backoff_base_seconds: float = 0.35,
        sleep_fn: Callable[[float], None] | None = None,
    ):
        self._servers: dict[str, ServiceConfig] = {}
        self.max_retries = max(0, int(max_retries))
        self.backoff_base_seconds = max(0.0, float(backoff_base_seconds))
        self._sleep_fn = sleep_fn or time.sleep

    def connect(self, service: str, config: dict) -> None:
        svc = service.lower().strip()
        endpoint = (config.get("endpoint") or "").strip()
        if endpoint:
            self.connect_http(
                service=svc,
                endpoint=endpoint,
                headers=config.get("headers"),
                timeout_seconds=int(config.get("timeout_seconds", 20)),
                discover=bool(config.get("discover", True)),
            )
            return

        tools = list(config.get("tools", []))
        handlers = dict(config.get("handlers", {}))
        self._servers[svc] = ServiceConfig(
            service=svc,
            kind="local",
            tools=tools,
            handlers=handlers,
        )

    def connect_http(
        self,
        service: str,
        endpoint: str,
        headers: dict[str, str] | None = None,
        timeout_seconds: int = 20,
        discover: bool = True,
    ) -> None:
        svc = service.lower().strip()
        clean_endpoint = endpoint.rstrip("/")
        tools: list[dict[str, Any]] = []
        if discover:
            tools = self._discover_http_tools(clean_endpoint, headers=headers, timeout_seconds=timeout_seconds)
        self._servers[svc] = ServiceConfig(
            service=svc,
            kind="http",
            tools=tools,
            handlers={},
            endpoint=clean_endpoint,
            headers=headers or {},
            timeout_seconds=timeout_seconds,
        )

    def connect_builtin(self, service: str, api_key: str) -> None:
        svc = service.lower().strip()
        if svc not in BUILTIN_SERVICES:
            raise ValueError(f"unsupported builtin service: {service}")
        tools, handlers = self._builtin_connector(service=svc, api_key=api_key)
        self._servers[svc] = ServiceConfig(
            service=svc,
            kind="local",
            tools=tools,
            handlers=handlers,
        )

    def is_connected(self, service: str) -> bool:
        return service.lower() in self._servers

    def list_services(self) -> list[str]:
        return sorted(self._servers)

    def list_tools(self, service: str | None = None) -> list[dict]:
        if service:
            cfg = self._servers.get(service.lower())
            return list(cfg.tools) if cfg else []
        tools: list[dict] = []
        for svc, config in self._servers.items():
            for tool in config.tools:
                tools.append({"service": svc, **tool})
        return tools

    def call_tool(self, service: str, tool_name: str, **kwargs):
        server = self._servers.get(service.lower())
        if not server:
            return self._error(
                code="service_not_connected",
                message=f"service_not_connected: {service}",
                service=service,
                tool_name=tool_name,
            )

        if server.kind == "http":
            return self._call_http_tool(server, tool_name, kwargs)

        fn = server.handlers.get(tool_name)
        if fn is None:
            return self._error(
                code="tool_not_found",
                message=f"tool_not_found: {tool_name}",
                service=service,
                tool_name=tool_name,
            )
        try:
            return fn(**kwargs)
        except Exception as exc:
            return self._error(
                code="local_tool_call_failed",
                message=str(exc),
                service=service,
                tool_name=tool_name,
                args=kwargs,
            )

    def _discover_http_tools(
        self,
        endpoint: str,
        headers: dict[str, str] | None,
        timeout_seconds: int,
    ) -> list[dict]:
        try:
            response = self._request_with_retry(
                method="get",
                url=f"{endpoint}/tools",
                headers=headers or {},
                timeout=timeout_seconds,
            )
            payload = response.json()
            if isinstance(payload, list):
                return [item for item in payload if isinstance(item, dict)]
            if isinstance(payload, dict):
                data = payload.get("tools", [])
                if isinstance(data, list):
                    return [item for item in data if isinstance(item, dict)]
        except Exception:
            pass
        return []

    def _call_http_tool(self, server: ServiceConfig, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._request_with_retry(
                method="post",
                url=f"{server.endpoint}/tools/{tool_name}/invoke",
                headers=server.headers or {},
                json={"args": args},
                timeout=server.timeout_seconds,
            )
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            return {"result": payload}
        except Exception as exc:
            return self._error(
                code="http_tool_call_failed",
                message=str(exc),
                service=server.service,
                tool_name=tool_name,
                args=args,
            )

    def _builtin_connector(
        self,
        service: str,
        api_key: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Callable[..., Any]]]:
        if service == "github":
            return self._github_connector(api_key)
        if service == "notion":
            return self._notion_connector(api_key)
        if service == "slack":
            return self._slack_connector(api_key)
        if service == "linear":
            return self._linear_connector(api_key)
        if service == "google_drive":
            return self._gdrive_connector(api_key)
        if service == "jira":
            return self._jira_connector(api_key)
        raise ValueError(f"unsupported builtin service: {service}")

    @staticmethod
    def _safe_json(response: requests.Response) -> dict:
        try:
            data = response.json()
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {"status_code": response.status_code, "text": response.text[:500]}

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        retryable_codes = {429, 500, 502, 503, 504}
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.request(method=method, url=url, **kwargs)
                if response.status_code in retryable_codes and attempt < self.max_retries:
                    delay = self.backoff_base_seconds * (2 ** attempt)
                    if delay > 0:
                        self._sleep_fn(delay)
                    continue
                response.raise_for_status()
                return response
            except Exception as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                delay = self.backoff_base_seconds * (2 ** attempt)
                if delay > 0:
                    self._sleep_fn(delay)

        if last_error is not None:
            raise last_error
        raise RuntimeError("request_failed_without_error")

    @staticmethod
    def _error(
        code: str,
        message: str,
        *,
        service: str,
        tool_name: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": code,
                "message": message,
                "service": service,
                "tool": tool_name,
                "args": args or {},
            },
        }

    def _github_connector(
        self,
        api_key: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Callable[..., Any]]]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        def list_open_prs(owner: str, repo: str, state: str = "open", per_page: int = 10):
            response = self._request_with_retry(
                method="get",
                url=f"https://api.github.com/repos/{owner}/{repo}/pulls",
                headers=headers,
                params={"state": state, "per_page": max(1, min(per_page, 100))},
                timeout=20,
            )
            payload = response.json()
            return [
                {
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "state": pr.get("state"),
                    "url": pr.get("html_url"),
                }
                for pr in payload
                if isinstance(pr, dict)
            ]

        def get_repo(owner: str, repo: str):
            response = self._request_with_retry(
                method="get",
                url=f"https://api.github.com/repos/{owner}/{repo}",
                headers=headers,
                timeout=20,
            )
            data = self._safe_json(response)
            return {
                "full_name": data.get("full_name"),
                "description": data.get("description"),
                "default_branch": data.get("default_branch"),
                "open_issues_count": data.get("open_issues_count"),
                "url": data.get("html_url"),
            }

        tools = [
            {"name": "list_open_prs", "description": "List pull requests for a repository."},
            {"name": "get_repo", "description": "Fetch repository metadata."},
        ]
        return tools, {"list_open_prs": list_open_prs, "get_repo": get_repo}

    def _notion_connector(
        self,
        api_key: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Callable[..., Any]]]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

        def search(query: str, page_size: int = 10):
            response = self._request_with_retry(
                method="post",
                url="https://api.notion.com/v1/search",
                headers=headers,
                json={"query": query, "page_size": max(1, min(page_size, 100))},
                timeout=20,
            )
            data = self._safe_json(response)
            return data.get("results", [])

        tools = [{"name": "search", "description": "Search Notion pages and databases."}]
        return tools, {"search": search}

    def _slack_connector(
        self,
        api_key: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Callable[..., Any]]]:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        def list_channels(limit: int = 100):
            response = self._request_with_retry(
                method="get",
                url="https://slack.com/api/conversations.list",
                headers=headers,
                params={"limit": max(1, min(limit, 1000))},
                timeout=20,
            )
            data = self._safe_json(response)
            return data.get("channels", [])

        def post_message(channel: str, text: str):
            response = self._request_with_retry(
                method="post",
                url="https://slack.com/api/chat.postMessage",
                headers=headers,
                json={"channel": channel, "text": text},
                timeout=20,
            )
            return self._safe_json(response)

        tools = [
            {"name": "list_channels", "description": "List Slack channels."},
            {"name": "post_message", "description": "Post a message to Slack."},
        ]
        return tools, {"list_channels": list_channels, "post_message": post_message}

    def _linear_connector(
        self,
        api_key: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Callable[..., Any]]]:
        headers = {"Authorization": api_key, "Content-Type": "application/json"}

        def list_issues(team: str | None = None, limit: int = 25):
            filter_block = ""
            if team:
                filter_block = f'filter: {{ team: {{ key: {{ eq: "{team}" }} }} }},'
            query = (
                "query Issues { "
                f"issues({filter_block} first: {max(1, min(limit, 100))}) "
                "{ nodes { id identifier title state { name } url } } }"
            )
            response = self._request_with_retry(
                method="post",
                url="https://api.linear.app/graphql",
                headers=headers,
                json={"query": query},
                timeout=20,
            )
            payload = self._safe_json(response)
            return payload.get("data", {}).get("issues", {}).get("nodes", [])

        tools = [{"name": "list_issues", "description": "List Linear issues."}]
        return tools, {"list_issues": list_issues}

    def _gdrive_connector(
        self,
        api_key: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Callable[..., Any]]]:
        headers = {"Authorization": f"Bearer {api_key}"}

        def list_files(page_size: int = 20, q: str | None = None):
            params: dict[str, Any] = {
                "pageSize": max(1, min(page_size, 100)),
                "fields": "files(id,name,mimeType,modifiedTime,webViewLink)",
            }
            if q:
                params["q"] = q
            response = self._request_with_retry(
                method="get",
                url="https://www.googleapis.com/drive/v3/files",
                headers=headers,
                params=params,
                timeout=20,
            )
            data = self._safe_json(response)
            return data.get("files", [])

        tools = [{"name": "list_files", "description": "List Google Drive files."}]
        return tools, {"list_files": list_files}

    def _jira_connector(
        self,
        api_key: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Callable[..., Any]]]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        def search_issues(base_url: str, jql: str, max_results: int = 20):
            response = self._request_with_retry(
                method="post",
                url=f"{base_url.rstrip('/')}/rest/api/3/search/jql",
                headers=headers,
                json={"jql": jql, "maxResults": max(1, min(max_results, 100))},
                timeout=20,
            )
            data = self._safe_json(response)
            return data.get("issues", [])

        tools = [{"name": "search_issues", "description": "Search Jira issues by JQL."}]
        return tools, {"search_issues": search_issues}
