"""Testes de processamento: load, ajustes, binarização, morfologia, transparência."""
import numpy as np
from PIL import Image

from app.core.morphology import apply_morphology
from app.core.preprocessing import apply_adjustments, denoise
from app.core.thresholding import binarize


def _gray_square(size=100, sq=60):
    img = np.full((size, size), 255, np.uint8)
    img[(size - sq) // 2:(size + sq) // 2, (size - sq) // 2:(size + sq) // 2] = 0
    return img


def test_binarize_global_square(tmp_path):
    g = _gray_square()
    m = binarize(g, method="global", threshold=128)
    assert m.dtype == np.uint8
    assert set(np.unique(m)).issubset({0, 255})
    assert (m == 255).sum() > 3000  # interior virou tinta


def test_binarize_otsu_and_adaptive():
    g = _gray_square()
    for method in ("otsu", "adaptive"):
        m = binarize(g, method=method, threshold=128)
        assert (m == 255).sum() > 1000


def test_invert():
    g = _gray_square()
    a = binarize(g, method="global", threshold=128, invert=False)
    b = binarize(g, method="global", threshold=128, invert=True)
    assert (a == 255).sum() + (b == 255).sum() == a.size


def test_adjustments_brightness_contrast_gamma():
    g = np.full((10, 10), 100, np.uint8)
    brighter = apply_adjustments(g, brightness=50)
    assert brighter.mean() > g.mean()
    higher = apply_adjustments(g, contrast=1.5)
    assert higher is not None
    gm = apply_adjustments(g, gamma=2.0)
    assert gm.mean() != g.mean()


def test_denoise_and_morphology_noise_removal():
    rng = np.random.default_rng(0)
    m = np.zeros((100, 100), np.uint8)
    m[30:70, 30:70] = 255
    # ruído sal-e-pimenta
    pts = rng.integers(0, 100, size=(60, 2))
    for y, x in pts:
        m[y, x] = 255
    opened = apply_morphology(m, "open", 3)
    assert opened.dtype == np.uint8
    # open deve remover parte do ruído isolado
    assert (opened == 255).sum() <= (m == 255).sum()
    d = denoise(np.full((20, 20), 128, np.uint8), 2)
    assert d.shape == (20, 20)


def test_transparency_composition(tmp_path):
    from app.core.image_loader import load_image
    p = tmp_path / "t.png"
    img = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    px = img.load()
    for y in range(10, 30):
        for x in range(10, 30):
            px[x, y] = (0, 0, 0, 255)
    img.save(p)
    loaded = load_image(p, max_size=64, background=(255, 255, 255))
    assert loaded.gray.shape == (40, 40)
    # centro escuro, borda clara (fundo branco)
    assert loaded.gray[20, 20] < 100
    assert loaded.gray[0, 0] > 200


def test_invalid_and_tiny_detail_image():
    tiny = np.full((30, 30), 255, np.uint8)
    tiny[14:16, 14:16] = 0  # detalhe 2x2
    m = binarize(tiny, method="global", threshold=128)
    assert (m == 255).sum() == 4
