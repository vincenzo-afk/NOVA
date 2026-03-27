"""Web scraping utilities with SSRF protection.

Fix 4.2: validate URLs against private IP ranges (RFC1918, link-local, loopback)
         using the `ipaddress` stdlib module to prevent SSRF attacks.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / AWS metadata
    ipaddress.ip_network("100.64.0.0/10"),    # Tailscale / CGNAT
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in net for net in _PRIVATE_NETWORKS)
    except ValueError:
        return False


def _validate_url(url: str) -> None:
    """Raise ValueError if the URL resolves to a private/internal IP (SSRF guard)."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise ValueError(f"Disallowed URL scheme: {scheme!r}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")
    try:
        resolved_ip = socket.gethostbyname(hostname)
    except socket.gaierror as exc:
        raise ValueError(f"DNS resolution failed for {hostname!r}: {exc}") from exc
    if _is_private_ip(resolved_ip):
        raise ValueError(
            f"SSRF blocked: {hostname!r} resolves to private/internal IP {resolved_ip}"
        )


def scrape_text(url: str) -> str:
    _validate_url(url)
    response = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (JARVIS/1.0)"})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)
