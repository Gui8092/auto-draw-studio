"""Regressão CORREÇÃO 7: ciclo de vida do arquivo de imagem."""
import os

import numpy as np
import pytest
from PIL import Image

from app.core.image_loader import load_image


def test_png_valid(tmp_path):
    p = tmp_path / "img.png"
    Image.new("RGB", (60, 40), (10, 20, 30)).save(p)
    loaded = load_image(p, max_size=512)
    assert (loaded.width, loaded.height) == (60, 40)
    assert loaded.rgb.shape == (40, 60, 3)
    assert loaded.gray.shape == (40, 60)


def test_jpeg_valid(tmp_path):
    p = tmp_path / "img.jpg"
    Image.new("RGB", (50, 50), (200, 100, 50)).save(p, "JPEG")
    loaded = load_image(p, max_size=512)
    assert (loaded.width, loaded.height) == (50, 50)


def test_exif_orientation(tmp_path):
    """Orientation 6 (rotacionar 270 CW): 40x20 deve virar 20x40."""
    p = tmp_path / "exif.jpg"
    img = Image.new("RGB", (40, 20), (0, 128, 255))
    exif = img.getexif()
    exif[274] = 6
    img.save(p, "JPEG", exif=exif)
    loaded = load_image(p, max_size=512)
    assert (loaded.width, loaded.height) == (20, 40), (
        f"EXIF não corrigida: {(loaded.width, loaded.height)}")


def test_transparent_png(tmp_path):
    p = tmp_path / "t.png"
    img = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    px = img.load()
    for y in range(10, 30):
        for x in range(10, 30):
            px[x, y] = (0, 0, 0, 255)
    img.save(p)
    loaded = load_image(p, max_size=64, background=(255, 255, 255))
    assert loaded.gray[20, 20] < 100
    assert loaded.gray[0, 0] > 200


def test_invalid_file(tmp_path):
    p = tmp_path / "bad.png"
    p.write_bytes(b"isto nao e uma imagem")
    with pytest.raises(ValueError):
        load_image(p)


def test_unsupported_extension(tmp_path):
    p = tmp_path / "img.gif"
    p.write_bytes(b"GIF89a")
    with pytest.raises(ValueError):
        load_image(p)


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_image(tmp_path / "nao_existe.png")


def test_file_released_after_load(tmp_path):
    """No Windows, handle aberto impede renomear/excluir: deve funcionar."""
    p = tmp_path / "img.png"
    Image.new("RGB", (30, 30), (90, 90, 90)).save(p)
    load_image(p)
    q = tmp_path / "renomeada.png"
    os.rename(p, q)  # falha se o arquivo ainda estiver aberto
    assert q.exists()
    load_image(q)
    os.remove(q)  # falha se o arquivo ainda estiver aberto
    assert not q.exists()
