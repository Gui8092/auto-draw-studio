"""Logging centralizado."""
import logging
from pathlib import Path


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(logs_dir / "auto_draw.log", encoding="utf-8"),
        ],
    )
    return logging.getLogger("auto_draw_studio")
