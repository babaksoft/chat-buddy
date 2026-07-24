from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from chat_buddy.infrastructure.config import settings


def configure_logging() -> None:
    """
    Configure application-wide logging.

    Call once during application startup.
    """

    settings.LOG_DIR.mkdir(exist_ok=True)
    root_logger = logging.getLogger()

    if root_logger.handlers:
        return

    root_logger.setLevel(settings.LOG_LEVEL)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        logging.Formatter("[%(name)s] [%(levelname)s] %(message)s")
    )

    # File handler
    file_handler = RotatingFileHandler(
        filename=settings.LOG_FILE,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
        encoding="utf-8",
    )

    file_handler.setLevel(settings.LOG_LEVEL)
    file_handler.setFormatter(
        logging.Formatter(
            "[%(asctime)s] "
            "[%(name)s] "
            "[%(levelname)s] "
            "[%(module)s:%(lineno)d] "
            "%(message)s"
        )
    )

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


def log_messages() -> None:
    logger = logging.getLogger(__name__)
    logger.debug("A very low-level information")
    logger.info("Some user-friendly information")
    logger.warning("Something may be slightly malfunctioning...")
    logger.error("Oh NO! We're in serious trouble here.")
    logger.critical("Apocalypse now!")


if __name__ == "__main__":
    configure_logging()
    log_messages()
