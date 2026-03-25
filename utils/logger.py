"""Centralized structured logger."""

from __future__ import annotations

from loguru import logger


def setup_logger() -> None:
    logger.remove()
    logger.add(
        sink=lambda msg: print(msg, end=""),
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}",
    )


def get_logger():
    return logger
