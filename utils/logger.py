"""Centralized structured logger."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_logger(log_dir: str = "logs", level: str = "INFO") -> None:
    """Configure loguru with stdout + rotating file sink."""
    logger.remove()

    # Stdout sink — human-readable
    logger.add(
        sys.stderr,
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
        colorize=False,
    )

    # File sink — persistent structured log
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    logger.add(
        sink=str(log_path / "jarvis.log"),
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name}:{function}:{line} | {message}",
        rotation="10 MB",
        retention="7 days",
        compression="gz",
        encoding="utf-8",
    )


def get_logger():
    return logger
