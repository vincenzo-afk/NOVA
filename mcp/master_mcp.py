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
    "home_assistant",  # Feature 9
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
        if service == "home_assistant":
            return self._home_assistant_connector(api_key)
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
                if response.status_code in retryable_codes:
                    if attempt < self.max_retries:
                        delay = self.backoff_base_seconds * (2 ** attempt)
                        if delay > 0:
                            self._sleep_fn(delay)
                        continue
                response.raise_for_status()
                return response
            except requests.HTTPError as exc:
                last_error = exc
                status_code = getattr(exc.response, "status_code", None)
                if status_code not in retryable_codes or attempt >= self.max_retries:
                    break
                delay = self.backoff_base_seconds * (2 ** attempt)
                if delay > 0:
                    self._sleep_fn(delay)
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

    def _home_assistant_connector(
        self,
        api_key: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Callable[..., Any]]]:
        """Feature 9: Home Assistant REST API connector.

        api_key format:  <base_url>|<long_lived_token>
        e.g.  http://homeassistant.local:8123|eyJ...

        The pipe separator lets connect_builtin receive everything in one string
        without requiring a separate endpoint parameter.
        """
        if "|" in api_key:
            base_url, token = api_key.split("|", 1)
        else:
            # Assume localhost HA with the entire string as the token
            base_url = "http://homeassistant.local:8123"
            token = api_key

        base_url = base_url.rstrip("/")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        def get_state(entity_id: str) -> dict:
            """Return the current state of a Home Assistant entity."""
            response = self._request_with_retry(
                method="get",
                url=f"{base_url}/api/states/{entity_id}",
                headers=headers,
                timeout=10,
            )
            return self._safe_json(response)

        def list_entities(domain: str = "") -> list:
            """List all entities, optionally filtered by domain (e.g. 'light', 'switch')."""
            response = self._request_with_retry(
                method="get",
                url=f"{base_url}/api/states",
                headers=headers,
                timeout=15,
            )
            try:
                data = response.json()
            except Exception:
                return []
            entities = [
                {
                    "entity_id": e.get("entity_id"),
                    "state": e.get("state"),
                    "friendly_name": e.get("attributes", {}).get("friendly_name"),
                }
                for e in (data if isinstance(data, list) else [])
            ]
            if domain:
                entities = [e for e in entities if str(e.get("entity_id", "")).startswith(domain + ".")]
            return entities

        def call_service(
            domain: str, service: str, entity_id: str = "", **extra
        ) -> dict:
            """Call a HA service (e.g. domain='light', service='turn_on', entity_id='light.living_room')."""
            payload: dict[str, Any] = {**extra}
            if entity_id:
                payload["entity_id"] = entity_id
            response = self._request_with_retry(
                method="post",
                url=f"{base_url}/api/services/{domain}/{service}",
                headers=headers,
                json=payload,
                timeout=10,
            )
            try:
                result = response.json()
                return {"ok": True, "result": result}
            except Exception:
                return {"ok": response.ok, "status_code": response.status_code}

        def get_history(entity_id: str, hours: int = 1) -> list:
            """Return the state history for an entity over the last N hours."""
            from datetime import datetime, timedelta, timezone
            start = (datetime.now(timezone.utc) - timedelta(hours=max(1, hours))).isoformat()
            response = self._request_with_retry(
                method="get",
                url=f"{base_url}/api/history/period/{start}",
                headers=headers,
                params={"filter_entity_id": entity_id},
                timeout=15,
            )
            try:
                data = response.json()
                if isinstance(data, list) and data:
                    return data[0]
            except Exception:
                pass
            return []

        def list_automations() -> list:
            response = self._request_with_retry(
                method="get",
                url=f"{base_url}/api/states",
                headers=headers,
                timeout=15,
            )
            try:
                data = response.json()
            except Exception:
                return []
            rows = []
            for e in (data if isinstance(data, list) else []):
                if not isinstance(e, dict):
                    continue
                entity_id = str(e.get("entity_id", ""))
                if not entity_id.startswith("automation."):
                    continue
                rows.append(
                    {
                        "entity_id": entity_id,
                        "state": e.get("state"),
                        "friendly_name": e.get("attributes", {}).get("friendly_name"),
                    }
                )
            return rows

        def trigger_automation(automation_id: str) -> dict:
            entity_id = automation_id if automation_id.startswith("automation.") else f"automation.{automation_id}"
            response = self._request_with_retry(
                method="post",
                url=f"{base_url}/api/services/automation/trigger",
                headers=headers,
                json={"entity_id": entity_id},
                timeout=10,
            )
            try:
                return {"ok": response.ok, "result": response.json()}
            except Exception:
                return {"ok": response.ok, "status_code": response.status_code}

        def set_climate(entity_id: str, temperature: float) -> dict:
            response = self._request_with_retry(
                method="post",
                url=f"{base_url}/api/services/climate/set_temperature",
                headers=headers,
                json={"entity_id": entity_id, "temperature": float(temperature)},
                timeout=10,
            )
            try:
                return {"ok": response.ok, "result": response.json()}
            except Exception:
                return {"ok": response.ok, "status_code": response.status_code}

        def get_energy_stats(period: str = "day") -> dict:
            # Home Assistant energy endpoint availability varies by version; use
            # recorder statistics endpoint as a stable fallback.
            response = self._request_with_retry(
                method="get",
                url=f"{base_url}/api/recorder/statistics_during_period",
                headers=headers,
                params={"period": period},
                timeout=20,
            )
            try:
                payload = response.json()
                return {"ok": response.ok, "period": period, "result": payload}
            except Exception:
                return {"ok": response.ok, "period": period, "status_code": response.status_code}

        tools = [
            {"name": "get_state", "description": "Get current state of a Home Assistant entity."},
            {"name": "list_entities", "description": "List Home Assistant entities, filtered by domain."},
            {"name": "call_service", "description": "Call a Home Assistant service (e.g. turn lights on/off)."},
            {"name": "get_history", "description": "Get state history for an entity over the last N hours."},
            {"name": "list_automations", "description": "List Home Assistant automations."},
            {"name": "trigger_automation", "description": "Trigger a Home Assistant automation entity."},
            {"name": "set_climate", "description": "Set thermostat temperature for a climate entity."},
            {"name": "get_energy_stats", "description": "Get Home Assistant energy/recorder statistics."},
        ]
        return tools, {
            "get_state": get_state,
            "list_entities": list_entities,
            "call_service": call_service,
            "get_history": get_history,
            "list_automations": list_automations,
            "trigger_automation": trigger_automation,
            "set_climate": set_climate,
            "get_energy_stats": get_energy_stats,
        }
