"""Web scraping utilities with SSRF protection.

Fix 4.2: validate URLs against private IP ranges (RFC1918, link-local, loopback)
         using the `ipaddress` stdlib module to prevent SSRF attacks.
"""

from __future__ import annotations

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from urllib.parse import urlparse

import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup


_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / AWS metadata
    ipaddress.ip_network("100.64.0.0/10"),    # Tailscale / CGNAT
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        if getattr(addr, "ipv4_mapped", None):
            addr = addr.ipv4_mapped
        
        # Check against all networks, catching type mismatches cleanly
        for net in _PRIVATE_NETWORKS:
            try:
                if addr in net:
                    return True
            except TypeError:
                continue
        return False
    except ValueError:
        return False


def _resolve_host(hostname: str, timeout_seconds: float = 5.0) -> list[str]:
    def _run() -> list[str]:
        addr_info = socket.getaddrinfo(hostname, None)
        return [info[4][0] for info in addr_info]

    pool = ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(_run)
    try:
        return fut.result(timeout=timeout_seconds)
    except FuturesTimeout as exc:
        fut.cancel()
        raise ValueError(f"DNS resolution timed out for {hostname!r}") from exc
    finally:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            pool.shutdown(wait=False)


def _validate_url(url: str) -> tuple[str, str, str]:
    """Raise ValueError if the URL resolves to a private/internal IP (SSRF guard)."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise ValueError(f"Disallowed URL scheme: {scheme!r}")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname")
    try:
        resolved_ips = _resolve_host(hostname, timeout_seconds=5.0)
    except (socket.gaierror, ValueError) as exc:
        raise ValueError(f"DNS resolution failed for {hostname!r}: {exc}") from exc
    for ip in resolved_ips:
        if _is_private_ip(ip):
            raise ValueError(
                f"SSRF blocked: {hostname!r} resolves to private/internal IP {ip}"
            )
    return scheme, hostname, resolved_ips[0]


def scrape_text(url: str) -> str:
    current_url = url
    response = None
    for _ in range(5):
        scheme, hostname, resolved_ip = _validate_url(current_url)
        headers = {"User-Agent": "Mozilla/5.0 (NOVA/1.0)"}
        request_url = current_url
        if scheme == "http":
            parsed = urlparse(current_url)
            netloc = resolved_ip
            if parsed.port:
                netloc = f"{resolved_ip}:{parsed.port}"
            request_url = parsed._replace(netloc=netloc).geturl()
            headers["Host"] = hostname
        else:
            _validate_url(current_url)
        response = requests.get(request_url, timeout=20, headers=headers, allow_redirects=False)
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            if not location:
                break
            current_url = urljoin(current_url, location)
            continue
        break
    if response is None:
        raise ValueError("Failed to fetch URL")
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    
    import re
    from core.think.reasoning import detect_prompt_injection
    
    text = soup.get_text("\n", strip=True)
    
    # Fix 16 & Sec 3: Prompt Injection Guard
    detected = detect_prompt_injection(text)
    if isinstance(detected, tuple):
        is_injected, reason = bool(detected[0]), str(detected[1] or "injection_detected")
    else:
        is_injected, reason = bool(detected), "injection_detected"
    if is_injected:
        return f"[Content from web (untrusted) - BLOCKED due to prompt injection: {reason}]"
        
    text = re.sub(r"\[/?tool_call\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r'\{[^{}]*"tool"\s*:\s*"[^"]+"[^{}]*\}', "", text, flags=re.IGNORECASE)
    
    return "[Content from web (untrusted)]\n" + text.strip()
