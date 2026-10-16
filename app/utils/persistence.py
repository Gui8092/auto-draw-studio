"""Persistência: configurações e projetos (JSON)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from app.models.settings import AppSettings

log = logging.getLogger("auto_draw_studio.persistence")


SETTINGS_VERSION = 2


def app_data_dir() -> Path:
    """Pasta de dados do usuário (fora do CWD e da pasta de instalação).

    Antes: `settings.json`/`logs/` no diretório atual — quebrava com
    erro de permissão ao rodar instalado em Program Files ou quando o
    CWD era só-leitura. Agora: `~/.auto_draw_studio`.
    """
    d = Path.home() / ".auto_draw_studio"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def default_settings_path() -> Path:
    return app_data_dir() / "settings.json"


def save_settings(settings: AppSettings, path: str | Path | None = None):
    p = Path(path) if path is not None else default_settings_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    data = {"version": SETTINGS_VERSION, **settings.to_dict()}
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_settings_file(p: Path) -> AppSettings | None:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Configurações corrompidas em %s (%s); usando padrões.", p, e)
        return AppSettings()
    if isinstance(data, dict) and data.get("version", 1) > SETTINGS_VERSION:
        log.warning("Configurações de versão futura (%s); usando padrões.",
                    data.get("version"))
        return AppSettings()
    return AppSettings.from_dict(data if isinstance(data, dict) else {})


def load_settings(path: str | Path | None = None) -> AppSettings:
    if path is not None:
        p = Path(path)
        if not p.exists():
            return AppSettings()
        return _read_settings_file(p) or AppSettings()
    default = default_settings_path()
    if default.exists():
        return _read_settings_file(default) or AppSettings()
    # Migração: quem já usava settings.json no CWD aproveita o arquivo.
    legacy = Path("settings.json")
    if legacy.exists():
        loaded = _read_settings_file(legacy) or AppSettings()
        try:
            save_settings(loaded, default)
        except Exception:
            pass
        return loaded
    return AppSettings()


def save_project(path: str | Path, image_path: str, settings: AppSettings,
                 plan_dict: dict | None = None):
    data = {"image_path": image_path, "settings": settings.to_dict(),
            "plan": plan_dict}
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_project(path: str | Path) -> dict:
    """Carrega um projeto com validação (antes: KeyError em arquivo ruim)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Projeto não encontrado: {path}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"Projeto inválido ({p.name}): não é JSON: {e}") from e
    if not isinstance(data, dict) or not data.get("image_path"):
        raise ValueError(f"Projeto inválido ({p.name}): sem 'image_path'.")
    return data
