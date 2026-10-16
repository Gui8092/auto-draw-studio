"""Carregamento de imagens com EXIF, transparência e resize.

Convenção de máscara (válida em todo o projeto):
  máscara binária uint8 onde 255 = precisa de tinta (preto) e 0 = papel (branco).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

SUPPORTED_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


@dataclass
class LoadedImage:
    rgb: np.ndarray  # HxWx3 uint8
    gray: np.ndarray  # HxW uint8
    width: int
    height: int
    source_path: str


def load_image(
    path: str | Path,
    max_size: int = 512,
    background: tuple[int, int, int] = (255, 255, 255),
) -> LoadedImage:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Imagem não encontrada: {path}")
    if p.suffix.lower() not in SUPPORTED_EXTS:
        raise ValueError(f"Formato não suportado: {p.suffix} (use PNG/JPG/BMP/WEBP)")
    try:
        with Image.open(p) as im:
            try:
                img = ImageOps.exif_transpose(im)
            except Exception:
                img = im
            # Força o carregamento para memória antes de fechar o arquivo
            # (no Windows, arquivo aberto pode bloquear renomear/excluir).
            img.load()
            img = img.copy()
    except (FileNotFoundError, ValueError):
        raise
    except Exception as e:
        raise ValueError(f"Falha ao abrir imagem: {e}") from e

    # Trata transparência: compõe sobre fundo (branco por padrão)
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (*background, 255))
        img = Image.alpha_composite(bg, img)
    img = img.convert("RGB")

    # Resize preservando proporção
    w, h = img.size
    scale = min(1.0, max_size / max(w, h)) if max(w, h) > 0 else 1.0
    if scale < 1.0:
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)

    rgb = np.array(img, dtype=np.uint8)
    # Conversão luminance manual (evita depender de cv2 aqui)
    gray = (0.299 * rgb[:, :, 0] + 0.587 * rgb[:, :, 1] + 0.114 * rgb[:, :, 2]).astype(np.uint8)
    hh, ww = gray.shape
    return LoadedImage(rgb=rgb, gray=gray, width=ww, height=hh, source_path=str(p))
