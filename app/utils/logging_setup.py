"""Logging centralizado."""
import logging


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    handlers: list = [logging.StreamHandler()]
    try:
        from app.utils.persistence import app_data_dir
        logs_dir = app_data_dir() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(logs_dir / "auto_draw.log",
                                            encoding="utf-8"))
    except Exception:
        pass  # CWD/pasta só-leitura: segue só com console, sem crashar
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    return logging.getLogger("auto_draw_studio")
