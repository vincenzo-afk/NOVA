"""Centralized structured logger."""

from __future__ import annotations

import sys
import logging
import threading
from pathlib import Path

try:
    from loguru import logger as _loguru_logger
except Exception:  # pragma: no cover
    _loguru_logger = None


def setup_logger(log_dir: str = "logs", level: str = "INFO") -> None:
    """Configure loguru with stdout + rotating file sink."""
    if _loguru_logger is None:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=getattr(logging, level.upper(), logging.INFO),
            format="%(asctime)s | %(levelname)s | %(name)s:%(lineno)d | %(message)s",
            handlers=[
                logging.StreamHandler(sys.stderr),
                logging.FileHandler(str(Path(log_dir) / "jarvis.log"), encoding="utf-8"),
            ],
        )
        return

    _loguru_logger.remove()

    # Stdout sink — human-readable
    _loguru_logger.add(
        sys.stderr,
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
        colorize=False,
    )

    # File sink — persistent structured log
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    _loguru_logger.add(
        sink=str(log_path / "jarvis.log"),
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{function}:{line} | {message}",
        rotation="10 MB",
        retention="7 days",
        compression="gz",
        encoding="utf-8",
    )


# Fix 6.6: Auto-setup logger on first import to ensure all code paths get configured logger
_logger_initialized = False
_logger_init_lock = threading.Lock()


def _ensure_logger_initialized():
    """Ensure logger is initialized on first use."""
    global _logger_initialized
    if _logger_initialized:
        return
    with _logger_init_lock:
        if _logger_initialized:
            return
        setup_logger()
        _logger_initialized = True


def get_logger(name=None):
    """Return configured logger, auto-initializing if needed."""
    _ensure_logger_initialized()
    if _loguru_logger is not None:
        return _loguru_logger.bind(name=name) if name else _loguru_logger
    return logging.getLogger(name or "nova")
