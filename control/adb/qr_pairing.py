"""Generate QR for ADB pairing."""

from __future__ import annotations

from pathlib import Path
import socket
import subprocess

import qrcode

from config.settings import settings
from control.adb.tailscale import ensure_tailscale_connected, tailscale_ip_v4


class QRPairing:
    def __init__(self, adb_port: int = 5555):
        self.adb_port = adb_port

    def local_ip(self) -> str:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
        finally:
            sock.close()

    def resolve_target_ip(self, prefer_remote: bool = False) -> str:
        if prefer_remote:
            ensure_tailscale_connected()
            remote = settings.TAILSCALE_PHONE_IP.strip() or tailscale_ip_v4()
            if remote:
                return remote
        try:
            return self.local_ip()
        except Exception:
            return settings.TAILSCALE_PHONE_IP.strip() or tailscale_ip_v4()

    def adb_uri(self, prefer_remote: bool = False) -> str:
        ip = self.resolve_target_ip(prefer_remote=prefer_remote)
        if not ip:
            raise RuntimeError("Could not resolve local or remote IP for ADB pairing.")
        return f"adb_connect://{ip}:{self.adb_port}"

    def generate(self, out_path: str = "assets/adb_qr.png", prefer_remote: bool = False) -> str:
        uri = self.adb_uri(prefer_remote=prefer_remote)
        img = qrcode.make(uri)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path)
        return out_path

    def print_terminal_qr(self, prefer_remote: bool = False) -> str:
        uri = self.adb_uri(prefer_remote=prefer_remote)
        qr = qrcode.QRCode(border=1)
        qr.add_data(uri)
        matrix = qr.get_matrix()
        lines = []
        for row in matrix:
            lines.append("".join("██" if cell else "  " for cell in row))
        art = "\n".join(lines)
        print(art)
        print(uri)
        return uri

    def enable_tcpip(self, device: str | None = None) -> str:
        cmd = ["adb"]
        if device:
            cmd.extend(["-s", device])
        cmd.extend(["tcpip", str(self.adb_port)])
        return subprocess.check_output(cmd, text=True).strip()
