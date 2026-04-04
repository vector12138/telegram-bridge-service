# Unified logging configuration for telegram-bridge-service using loguru

from pathlib import Path
from loguru import logger
import sys

PROJECT_ROOT = Path(__file__).parent

def setup_logging():
    """Configure loguru logger:
    - Console output (INFO+)
    - File output with rotation and retention
    """
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level="INFO", colorize=True)
    logger.add(
        log_dir / "telegram_bridge.log",
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        compression="zip",
        encoding="utf-8",
    )
    return logger

# Initialize when imported
setup_logging()
