from __future__ import annotations

from pathlib import Path

from control.adb.qr_pairing import QRPairing
from control.adb.watcher import PhoneWatcher
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


def test_install_tailscale_uses_available_package_manager(monkeypatch):
    calls: list[list[str]] = []

    monkeypatch.setattr(tailscale, "is_tailscale_installed", lambda: False)
    result = tailscale.install_tailscale(
        system_name="Darwin",
        run_fn=lambda cmd, check=True: calls.append(cmd),
        which_fn=lambda name: "/opt/homebrew/bin/brew" if name == "brew" else None,
    )

    assert result is True
    assert calls == [["brew", "install", "--cask", "tailscale"]]


def test_reconnect_tailscale_runs_up(monkeypatch):
    calls: list[list[str]] = []

    monkeypatch.setattr(tailscale, "ensure_tailscale_available", lambda: True)

    result = tailscale.reconnect_tailscale(run_fn=lambda cmd, check=True: calls.append(cmd))

    assert result is True
    assert calls == [["tailscale", "up"]]


def test_qr_pairing_remote_mode_ensures_tailscale(monkeypatch):
    pairing = QRPairing(adb_port=5555)
    marker = {"ensured": False}

    monkeypatch.setattr("control.adb.qr_pairing.ensure_tailscale_connected", lambda: marker.__setitem__("ensured", True))
    monkeypatch.setattr("control.adb.qr_pairing.tailscale_ip_v4", lambda: "100.88.1.9")

    uri = pairing.adb_uri(prefer_remote=True)

    assert marker["ensured"] is True
    assert uri == "adb_connect://100.88.1.9:5555"


def test_qr_pairing_builds_uri_and_file(monkeypatch, tmp_path):
    pairing = QRPairing(adb_port=5555)
    monkeypatch.setattr(pairing, "local_ip", lambda: "192.168.1.9")

    uri = pairing.adb_uri()
    assert uri == "adb_connect://192.168.1.9:5555"

    out = tmp_path / "adb_qr.png"
    generated = pairing.generate(str(out))
    assert Path(generated).exists()


def test_phone_watcher_summarizes_notifications_and_sms():
    watcher = PhoneWatcher(adb=None)  # type: ignore[arg-type]

    assert (
        watcher._summarize_notifications(
            "NotificationRecord{ pkg=com.phone call incoming call from +12345 }"
        )
        == "Phone alert: incoming call detected. Want me to help answer or silence it?"
    )

    summary = watcher._summarize_sms(
        "Row: address=+15551234567 body=Running late\n"
        "Row: address=+15557654321 body=On my way"
    )
    assert "new SMS activity" in summary
    assert "+15551234567" in summary
