"""Compatibility re-exports for shared logging utilities."""

from chat_buddy.shared.config.logging import configure_logging, log_messages

__all__ = [
    "configure_logging",
    "log_messages",
]
