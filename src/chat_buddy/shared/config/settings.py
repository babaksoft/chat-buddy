import logging
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent.parent

LOG_DIR = PKG_ROOT / "logs"
LOG_FILE = LOG_DIR / "chat_buddy.log"
LOG_LEVEL = logging.DEBUG
