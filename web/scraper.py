"""Web scraping utilities with SSRF protection.

Fix 4.2: validate URLs against private IP ranges (RFC1918, link-local, loopback)
         using the `ipaddress` stdlib module to prevent SSRF attacks.
"""

from __future__ import annotations

import atexit
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
_DNS_RESOLVER_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dns_resolver")
atexit.register(lambda: _DNS_RESOLVER_POOL.shutdown(wait=False, cancel_futures=True))


def _is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        # Handle IPv4-mapped IPv6 addresses (e.g. ::ffff:192.168.1.1)
        if hasattr(addr, "ipv4_mapped") and addr.ipv4_mapped:
            addr = addr.ipv4_mapped

        for net in _PRIVATE_NETWORKS:
            if addr.version == net.version:
                if addr in net:
                    return True
        return False
    except ValueError:
        return False


def _resolve_host(hostname: str, timeout_seconds: float = 5.0) -> list[str]:
    def _run() -> list[str]:
        previous_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(timeout_seconds)
            addr_info = socket.getaddrinfo(hostname, None)
            return [info[4][0] for info in addr_info]
        finally:
            socket.setdefaulttimeout(previous_timeout)

    fut = _DNS_RESOLVER_POOL.submit(_run)
    try:
        return fut.result(timeout=timeout_seconds)
    except FuturesTimeout as exc:
        fut.cancel()
        raise ValueError(f"DNS resolution timed out for {hostname!r}") from exc


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


def _format_host_for_netloc(host: str) -> str:
    """Format host for URL netloc, bracketing IPv6 literals when needed."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    if ip.version == 6:
        return f"[{host}]"
    return host


def scrape_text(url: str) -> str:
    current_url = url
    response = None
    redirect_count = 0
    max_redirects = 5

    while redirect_count <= max_redirects:
        scheme, hostname, resolved_ip = _validate_url(current_url)
        headers = {"User-Agent": "Mozilla/5.0 (NOVA/1.0)"}
        request_url = current_url

        if scheme in {"http", "https"}:
            parsed = urlparse(current_url)
            safe_host = _format_host_for_netloc(resolved_ip)
            netloc = safe_host
            if parsed.port:
                netloc = f"{safe_host}:{parsed.port}"
            request_url = parsed._replace(netloc=netloc).geturl()
            headers["Host"] = hostname

        response = requests.get(
            request_url,
            timeout=20,
            headers=headers,
            allow_redirects=False,
            stream=True,
        )

        if response.is_redirect or response.is_permanent_redirect:
            redirect_count += 1
            if redirect_count > max_redirects:
                raise ValueError(f"Too many redirects (limit={max_redirects})")
            location = response.headers.get("Location")
            if not location:
                break
            current_url = urljoin(current_url, location)
            continue
        break

    if response is None:
        raise ValueError("Failed to fetch URL")
    response.raise_for_status()
    from core.think.reasoning import detect_prompt_injection
    raw_chunks: list[str] = []
    try:
        for chunk in response.iter_content(chunk_size=8192, decode_unicode=True):
            if not chunk:
                continue
            if detect_prompt_injection(chunk):
                response.close()
                return "[Content from web (untrusted) - BLOCKED due to prompt injection: injection_detected]"
            raw_chunks.append(chunk)
    finally:
        response.close()

    raw_text = "".join(raw_chunks)
    if detect_prompt_injection(raw_text):
        return "[Content from web (untrusted) - BLOCKED due to prompt injection: injection_detected]"
    soup = BeautifulSoup(raw_text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    
    import re
    
    text = soup.get_text("\n", strip=True)
    
    # Prompt Injection Guard
    if detect_prompt_injection(text):
        return "[Content from web (untrusted) - BLOCKED due to prompt injection: injection_detected]"
        
    text = re.sub(r"\[/?tool_call\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r'\{[^{}]*"tool"\s*:\s*"[^"]+"[^{}]*\}', "", text, flags=re.IGNORECASE)
    
    return "[Content from web (untrusted)]\n" + text.strip()


# ── Level 3: JS-rendered text extraction via Playwright ──────────────────────

def scrape_js(url: str) -> str:
    """Feature 6 Level 3: scrape fully JS-rendered page using Playwright browser.

    Falls back to scrape_text() if Playwright is not installed.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return scrape_text(url)  # graceful fallback to L1/L2

    # SSRF guard still applies
    _validate_url(url)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_default_timeout(20_000)
            page.goto(url, wait_until="networkidle")
            html = page.inner_text("body")
        finally:
            browser.close()

    import re
    from core.think.reasoning import detect_prompt_injection

    html = re.sub(r"\[/?tool_call\]", "", html, flags=re.IGNORECASE)
    if detect_prompt_injection(html):
        return "[Content from web (untrusted) - BLOCKED: prompt injection detected]"
    return "[Content from web (untrusted, JS-rendered)]\n" + html.strip()


# ── Level 4: Visual page analysis via screenshot + OmniParser ────────────────

def scrape_visual(
    url: str,
    omniparser_url: str = "http://localhost:8000",
    return_screenshot_bytes: bool = False,
) -> dict:
    """Feature 6 Level 4: screenshot a page and run OmniParser UI element detection.

    Returns:
        {
            "text": str,              # JS-rendered text (L3)
            "ui_elements": [...],     # OmniParser-detected elements
            "screenshot_path": str,   # saved PNG path (if saved)
        }

    Falls back gracefully when browser or OmniParser is unavailable.
    """
    result: dict = {"text": "", "ui_elements": [], "screenshot_path": None}

    # Step 1 — JS-rendered text (L3)
    try:
        result["text"] = scrape_js(url)
    except Exception as exc:
        result["text"] = f"[scrape_js failed: {exc}]"

    # Step 2 — Screenshot
    screenshot_bytes: bytes | None = None
    try:
        from playwright.sync_api import sync_playwright

        _validate_url(url)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_default_timeout(20_000)
                page.goto(url, wait_until="networkidle")
                screenshot_bytes = page.screenshot(full_page=False)
            finally:
                browser.close()

        # Optionally save
        from pathlib import Path
        import hashlib, time

        assets_dir = Path("assets")
        assets_dir.mkdir(exist_ok=True)
        slug = hashlib.md5(url.encode()).hexdigest()[:8]
        fname = assets_dir / f"scrape_{slug}_{int(time.time())}.png"
        fname.write_bytes(screenshot_bytes)
        result["screenshot_path"] = str(fname)

    except ImportError:
        pass  # Playwright not installed — skip screenshot
    except Exception as exc:
        result["screenshot_errors"] = str(exc)

    # Step 3 — OmniParser element detection (L4)
    if screenshot_bytes:
        try:
            from vision.omniparser import OmniParserClient

            client = OmniParserClient(omniparser_url)
            result["ui_elements"] = client.ui_elements(screenshot_bytes)
        except Exception as exc:
            result["omniparser_error"] = str(exc)

    return result
