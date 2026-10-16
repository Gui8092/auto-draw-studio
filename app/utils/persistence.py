"""Persistência: configurações e projetos (JSON)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.models.settings import AppSettings

log = logging.getLogger("auto_draw_studio.persistence")


SETTINGS_VERSION = 2


def save_settings(settings: AppSettings, path: str | Path = "settings.json"):
    data = {"version": SETTINGS_VERSION, **settings.to_dict()}
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_settings(path: str | Path = "settings.json") -> AppSettings:
    p = Path(path)
    if not p.exists():
        return AppSettings()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("version", 1) > SETTINGS_VERSION:
            log.warning("Configurações de versão futura (%s); usando padrões.",
                        data.get("version"))
            return AppSettings()
        return AppSettings.from_dict(data if isinstance(data, dict) else {})
    except Exception as e:
        # Recuperação segura: registra o erro e usa os padrões.
        log.warning("Configurações corrompidas em %s (%s); usando padrões.", p, e)
        return AppSettings()


def save_project(path: str | Path, image_path: str, settings: AppSettings,
                 plan_dict: dict | None = None):
    data = {"image_path": image_path, "settings": settings.to_dict(),
            "plan": plan_dict}
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_project(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
