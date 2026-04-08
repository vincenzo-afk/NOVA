"""Peer registry and lightweight discovery for A2A."""

from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

_SERVICE_TYPE = "_nova._tcp.local."


class PeerRegistry:
    def __init__(self, path: str | Path = ".jarvis/a2a_peers.json"):
        self.path = Path(path)
        self._peers: dict[str, dict[str, Any]] = {}
        self._zc = None
        self._service_info = None
        self._advertised_name = ""
        self._load()

    def upsert_self(
        self,
        *,
        agent_name: str,
        session: str,
        tools: list[str],
        capabilities_hash: str,
        health_port: int = 8765,
    ) -> dict:
        host = socket.gethostname()
        record = {
            "agent_name": str(agent_name),
            "host": host,
            "session": str(session),
            "tools": sorted(set(tools)),
            "capabilities_hash": str(capabilities_hash),
            "health_port": int(health_port),
            "updated_at": int(time.time()),
        }
        self._peers[record["agent_name"]] = record
        self._save()
        self._advertise_self(record)
        return record

    def list_peers(self) -> list[dict]:
        return [self._peers[k] for k in sorted(self._peers.keys())]

    def merge_external(self, peers: list[dict]) -> None:
        for peer in peers:
            if not isinstance(peer, dict):
                continue
            name = str(peer.get("agent_name", "")).strip()
            if not name:
                continue
            self._peers[name] = dict(peer)
        self._save()

    def discover_tailscale_peers(self) -> list[dict]:
        if not shutil_which("tailscale"):
            return []
        try:
            out = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if out.returncode != 0 or not out.stdout.strip():
                return []
            payload = json.loads(out.stdout)
            peers = payload.get("Peer", {}) if isinstance(payload, dict) else {}
            rows: list[dict] = []
            for _, info in peers.items():
                if not isinstance(info, dict):
                    continue
                rows.append(
                    {
                        "agent_name": str(info.get("HostName", "")),
                        "host": str(info.get("HostName", "")),
                        "tailscale_ips": info.get("TailscaleIPs", []),
                        "online": bool(info.get("Online", False)),
                    }
                )
            return rows
        except Exception:
            return []

    def discover_mdns_peers(self, timeout_seconds: float = 1.2) -> list[dict]:
        try:
            from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
        except Exception:
            return []

        hits: dict[str, dict[str, Any]] = {}

        class _Listener(ServiceListener):
            def add_service(self, zc, service_type, name):
                try:
                    info = zc.get_service_info(
                        service_type,
                        name,
                        timeout=max(100, int(timeout_seconds * 1000)),
                    )
                except Exception:
                    return
                if info is None:
                    return
                props: dict[str, str] = {}
                for key, value in (info.properties or {}).items():
                    if isinstance(key, bytes):
                        k = key.decode("utf-8", errors="ignore")
                    else:
                        k = str(key)
                    if isinstance(value, bytes):
                        v = value.decode("utf-8", errors="ignore")
                    else:
                        v = str(value)
                    props[k] = v
                agent_name = str(props.get("agent_name") or name.split("._nova._tcp.local", 1)[0]).strip()
                if not agent_name:
                    return
                host = str(info.server or "").rstrip(".")
                ips: list[str] = []
                try:
                    ips = list(info.parsed_addresses())
                except Exception:
                    ips = []
                tools = [t.strip() for t in str(props.get("tools", "")).split(",") if t.strip()]
                hits[agent_name] = {
                    "agent_name": agent_name,
                    "host": host,
                    "session": str(props.get("session", "")),
                    "tools": tools,
                    "capabilities_hash": str(props.get("capabilities_hash", "")),
                    "mdns_ips": ips,
                    "updated_at": int(time.time()),
                }

            def update_service(self, zc, service_type, name):
                self.add_service(zc, service_type, name)

            def remove_service(self, zc, service_type, name):
                _ = (zc, service_type, name)
                return

        zc = Zeroconf()
        listener = _Listener()
        try:
            ServiceBrowser(zc, _SERVICE_TYPE, listener)
            time.sleep(max(0.1, float(timeout_seconds)))
        finally:
            try:
                zc.close()
            except Exception:
                pass
        rows = [hits[k] for k in sorted(hits.keys())]
        if rows:
            self.merge_external(rows)
        return rows

    def close(self) -> None:
        self._close_mdns()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        if isinstance(data, list):
            for row in data:
                if isinstance(row, dict) and row.get("agent_name"):
                    self._peers[str(row["agent_name"])] = row
        elif isinstance(data, dict):
            for name, row in data.items():
                if isinstance(row, dict):
                    self._peers[str(name)] = row

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.list_peers()
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _advertise_self(self, record: dict[str, Any]) -> None:
        try:
            from zeroconf import ServiceInfo, Zeroconf
        except Exception:
            return
        agent_name = str(record.get("agent_name", "")).strip()
        if not agent_name:
            return
        ip = self._best_local_ipv4()
        try:
            address = socket.inet_aton(ip)
        except OSError:
            return
        if self._zc is None:
            try:
                self._zc = Zeroconf()
            except Exception:
                self._zc = None
                return
        port = int(record.get("health_port") or 8765)
        tools_csv = ",".join(record.get("tools", []))[:1024]
        properties = {
            b"agent_name": agent_name.encode("utf-8"),
            b"session": str(record.get("session", "")).encode("utf-8"),
            b"capabilities_hash": str(record.get("capabilities_hash", "")).encode("utf-8"),
            b"tools": tools_csv.encode("utf-8"),
        }
        info = ServiceInfo(
            type_=_SERVICE_TYPE,
            name=f"{agent_name}.{_SERVICE_TYPE}",
            addresses=[address],
            port=port,
            properties=properties,
            server=f"{socket.gethostname()}.local.",
        )
        try:
            if self._service_info is not None:
                try:
                    self._zc.unregister_service(self._service_info)
                except Exception:
                    pass
            self._zc.register_service(info, allow_name_change=True)
            self._service_info = info
            self._advertised_name = agent_name
        except Exception:
            return

    def _close_mdns(self) -> None:
        if self._zc is None:
            return
        try:
            if self._service_info is not None:
                self._zc.unregister_service(self._service_info)
        except Exception:
            pass
        try:
            self._zc.close()
        except Exception:
            pass
        self._zc = None
        self._service_info = None

    @staticmethod
    def _best_local_ipv4() -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                return str(sock.getsockname()[0])
        except Exception:
            return "127.0.0.1"

    def __del__(self):
        try:
            self._close_mdns()
        except Exception:
            pass


def shutil_which(cmd: str) -> str | None:
    import shutil

    return shutil.which(cmd)
