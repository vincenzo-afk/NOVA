"""Hybrid virus scanner (VirusTotal + local heuristics)."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
import time
from pathlib import Path
from typing import Any

import requests


class VirusScanner:
    def __init__(self, api_key: str = "", timeout_seconds: int = 15):
        self.api_key = (api_key or "").strip()
        self.timeout_seconds = max(3, int(timeout_seconds))

    def scan_text_buffer(self, text: str, filename: str = "buffer.txt") -> dict[str, Any]:
        data = (text or "").encode("utf-8", errors="ignore")
        local = self._heuristic_scan(data, filename)
        return {
            "status": "ok",
            "source": "local_heuristic",
            "safe": local["detections"] == 0,
            "detections": local["detections"],
            "total_engines": local["total_checks"],
            "details": local["notes"],
            "permalink": "",
        }

    def scan_file(self, path: str) -> dict[str, Any]:
        target = Path(path).expanduser().resolve(strict=False)
        if not target.exists() or not target.is_file():
            return {"status": "error", "reason": "file_not_found", "path": str(target)}

        try:
            data = target.read_bytes()
        except Exception as exc:
            return {"status": "error", "reason": f"read_failed:{exc}", "path": str(target)}

        local = self._heuristic_scan(data, target.name)
        online = self._vt_scan_file(target, data) if self.api_key else None

        detections = local["detections"] + int(online.get("detections", 0) if online else 0)
        total_engines = local["total_checks"] + int(online.get("total_engines", 0) if online else 0)
        notes = list(local["notes"])
        if online and online.get("note"):
            notes.append(str(online["note"]))

        return {
            "status": "ok",
            "path": str(target),
            "safe": detections == 0,
            "detections": detections,
            "total_engines": total_engines,
            "permalink": (online or {}).get("permalink", ""),
            "details": notes,
            "local": local,
            "online": online or {"status": "skipped", "reason": "no_api_key"},
        }

    def _heuristic_scan(self, data: bytes, filename: str) -> dict[str, Any]:
        checks = 0
        detections = 0
        notes: list[str] = []
        lowered_name = (filename or "").lower()

        # 1) Entropy-based packed/encrypted suspicion.
        checks += 1
        if len(data) > 1024:
            entropy = self._entropy(data[: min(len(data), 64 * 1024)])
            if entropy >= 7.6:
                detections += 1
                notes.append(f"High entropy payload ({entropy:.2f})")

        # 2) Executable magic / suspicious sections.
        checks += 1
        if data[:2] == b"MZ":
            if any(sec in data for sec in (b".upx", b".aspack", b".packed")):
                detections += 1
                notes.append("Packed PE section marker detected")

        # 3) Suspicious command strings.
        checks += 1
        bad_strings = [
            b"powershell -enc",
            b"cmd.exe /c",
            b"frombase64string",
            b"downloadstring(",
            b"invoke-webrequest",
            b"certutil -urlcache",
            b"rundll32",
        ]
        haystack = data.lower()
        if any(sig in haystack for sig in bad_strings):
            detections += 1
            notes.append("Suspicious command/execution string detected")

        # 4) Embedded URLs/IPs in executables/scripts.
        checks += 1
        is_risky_ext = lowered_name.endswith(
            (".exe", ".dll", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".jar", ".py")
        )
        if is_risky_ext:
            blob = data[: min(len(data), 2_000_000)].decode("latin-1", errors="ignore")
            url_hits = re.findall(r"https?://[^\s\"'<>]+", blob, flags=re.IGNORECASE)
            ip_hits = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", blob)
            public_ip_hits = 0
            for item in ip_hits[:100]:
                try:
                    ip = ipaddress.ip_address(item)
                    if not (ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_multicast):
                        public_ip_hits += 1
                except Exception:
                    continue
            if len(url_hits) >= 5 or public_ip_hits >= 3:
                detections += 1
                notes.append("Large number of embedded URLs/public IPs")

        # 5) Script auto-run patterns.
        checks += 1
        autorun_patterns = [
            b"schtasks /create",
            b"reg add hkcu\\software\\microsoft\\windows\\currentversion\\run",
            b"crontab -e",
            b"launchctl load",
        ]
        if any(p in haystack for p in autorun_patterns):
            detections += 1
            notes.append("Persistence/autorun pattern detected")

        return {
            "status": "ok",
            "detections": detections,
            "total_checks": checks,
            "notes": notes,
        }

    @staticmethod
    def _entropy(data: bytes) -> float:
        if not data:
            return 0.0
        counts = [0] * 256
        for b in data:
            counts[b] += 1
        total = len(data)
        entropy = 0.0
        for c in counts:
            if c == 0:
                continue
            p = c / total
            entropy -= p * math.log2(p)
        return entropy

    def _vt_scan_file(self, path: Path, data: bytes) -> dict[str, Any]:
        headers = {"x-apikey": self.api_key}
        sha256 = hashlib.sha256(data).hexdigest()
        base = "https://www.virustotal.com/api/v3"
        file_url = f"{base}/files/{sha256}"

        # First: hash lookup to avoid upload if report exists.
        try:
            report = requests.get(file_url, headers=headers, timeout=self.timeout_seconds)
            if report.status_code == 200:
                return self._parse_vt_file_report(report.json(), sha256)
        except Exception:
            pass

        # Upload when hash not found.
        try:
            with path.open("rb") as fh:
                up = requests.post(
                    f"{base}/files",
                    headers=headers,
                    files={"file": (path.name, fh)},
                    timeout=self.timeout_seconds,
                )
            if up.status_code >= 300:
                return {
                    "status": "error",
                    "detections": 0,
                    "total_engines": 0,
                    "note": f"VirusTotal upload failed:{up.status_code}",
                }
            up_json = up.json()
            analysis_id = (
                ((up_json.get("data") or {}).get("id"))
                or ((up_json.get("meta") or {}).get("analysis_id"))
                or ""
            )
            if not analysis_id:
                return {
                    "status": "error",
                    "detections": 0,
                    "total_engines": 0,
                    "note": "VirusTotal upload missing analysis id",
                }
        except Exception as exc:
            return {
                "status": "error",
                "detections": 0,
                "total_engines": 0,
                "note": f"VirusTotal upload exception:{exc}",
            }

        # Poll analysis completion briefly.
        for _ in range(8):
            try:
                poll = requests.get(f"{base}/analyses/{analysis_id}", headers=headers, timeout=self.timeout_seconds)
                if poll.status_code != 200:
                    time.sleep(1.2)
                    continue
                pjson = poll.json()
                attrs = (pjson.get("data") or {}).get("attributes") or {}
                status = str(attrs.get("status") or "").lower()
                if status in {"queued", "in-progress"}:
                    time.sleep(1.2)
                    continue
                # Analysis finished: fetch file report by hash.
                final_report = requests.get(file_url, headers=headers, timeout=self.timeout_seconds)
                if final_report.status_code == 200:
                    return self._parse_vt_file_report(final_report.json(), sha256)
                break
            except Exception:
                time.sleep(1.2)

        return {
            "status": "pending",
            "detections": 0,
            "total_engines": 0,
            "permalink": f"https://www.virustotal.com/gui/file/{sha256}",
            "note": "VirusTotal analysis pending",
        }

    @staticmethod
    def _parse_vt_file_report(report: dict[str, Any], sha256: str) -> dict[str, Any]:
        attrs = ((report.get("data") or {}).get("attributes") or {})
        stats = attrs.get("last_analysis_stats") or {}
        malicious = int(stats.get("malicious", 0) or 0)
        suspicious = int(stats.get("suspicious", 0) or 0)
        harmless = int(stats.get("harmless", 0) or 0)
        undetected = int(stats.get("undetected", 0) or 0)
        total = malicious + suspicious + harmless + undetected
        detections = malicious + suspicious
        return {
            "status": "ok",
            "detections": detections,
            "total_engines": total,
            "permalink": f"https://www.virustotal.com/gui/file/{sha256}",
            "raw_stats": stats,
        }


def scan_file(path: str, api_key: str = "") -> dict[str, Any]:
    return VirusScanner(api_key=api_key).scan_file(path)

