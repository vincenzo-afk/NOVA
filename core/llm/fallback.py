"""Fallback helpers for cloud -> local model selection."""

from __future__ import annotations

import socket


class NetworkState:
    @staticmethod
    def is_online(timeout: float = 1.5) -> bool:
        try:
            sock = socket.create_connection(("1.1.1.1", 53), timeout=timeout)
            sock.close()
            return True
        except OSError:
            return False
