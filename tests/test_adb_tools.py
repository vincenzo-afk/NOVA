from __future__ import annotations

from pathlib import Path

from control.adb.qr_pairing import QRPairing
from control.adb import tailscale


def test_tailscale_ip_returns_empty_when_not_installed(monkeypatch):
    monkeypatch.setattr(tailscale, "is_tailscale_installed", lambda: False)
    assert tailscale.tailscale_ip_v4() == ""


def test_tailscale_ip_parses_first_ipv4(monkeypatch):
    monkeypatch.setattr(tailscale, "is_tailscale_installed", lambda: True)
    monkeypatch.setattr(
        tailscale.subprocess,
        "check_output",
        lambda *a, **k: "100.70.1.2\n100.80.2.3\n",
    )
    assert tailscale.tailscale_ip_v4() == "100.70.1.2"


def test_qr_pairing_builds_uri_and_file(monkeypatch, tmp_path):
    pairing = QRPairing(adb_port=5555)
    monkeypatch.setattr(pairing, "local_ip", lambda: "192.168.1.9")

    uri = pairing.adb_uri()
    assert uri == "adb_connect://192.168.1.9:5555"

    out = tmp_path / "adb_qr.png"
    generated = pairing.generate(str(out))
    assert Path(generated).exists()
