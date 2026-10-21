"""Regressão CORREÇÃO 1: linhas finas preservadas com fallback por linha."""
import numpy as np

from app.core.fill_planner import plan_fill_strokes, plan_fill_strokes_safe


def rows(strokes):
    return sorted({s[0][1] for s in strokes})


def test_thick_region_isolated():
    m = np.zeros((40, 60), np.uint8)
    m[5:15, 5:55] = 255
    safe = plan_fill_strokes_safe(m, spacing=1, margin=1)
    assert rows(safe), "região espessa isolada deve gerar fills"
    # Margem de segurança: linhas erodidas ficam dentro da região
    for seg in safe:
        (x0, y0), (x1, y1) = seg
        assert 5 <= y0 <= 14
        assert 5 <= x0 <= x1 <= 54


def test_thin_line_isolated():
    m = np.zeros((40, 60), np.uint8)
    m[20, 5:55] = 255
    safe = plan_fill_strokes_safe(m, spacing=1, margin=1)
    assert len(safe) == 1, f"linha fina isolada deve gerar 1 segmento, gerou {len(safe)}"
    (x0, y0), (x1, y1) = safe[0]
    assert y0 == 20 and x0 <= 6 and x1 >= 53


def test_thin_line_with_thick_region_spacing1():
    """Caso obrigatório do prompt: espessa + detalhe de 1px, spacing=1."""
    m = np.zeros((40, 60), np.uint8)
    m[5:15, 5:55] = 255   # região espessa (linhas 5..14)
    m[30, 5:55] = 255     # detalhe fino (linha 30)
    safe = plan_fill_strokes_safe(m, spacing=1, margin=1)
    got = rows(safe)
    assert 30.0 in got, f"detalhe fino perdido! linhas geradas: {got}"
    assert any(5.0 <= y <= 14.0 for y in got), "região espessa deve continuar preenchida"
    # Linha fina cobre a extensão esperada (com margem)
    thin = [s for s in safe if s[0][1] == 30.0]
    assert len(thin) == 1
    assert thin[0][0][0] <= 6 and thin[0][1][0] >= 53


def test_holes_preserved_per_row():
    m = np.zeros((40, 60), np.uint8)
    m[5:25, 5:55] = 255
    m[10:15, 20:40] = 0  # furo
    safe = plan_fill_strokes_safe(m, spacing=2, margin=1)
    for seg in safe:
        (x0, y0), (x1, y1) = seg
        if 10 <= y0 <= 14:
            # Nenhum segmento deve atravessar o furo (x 20..39)
            assert not (x0 < 20 and x1 > 39), f"fill atravessou o furo: {seg}"


def test_empty_mask():
    m = np.zeros((30, 30), np.uint8)
    assert plan_fill_strokes_safe(m, spacing=1, margin=1) == []


def test_no_duplicates_or_invalid_coords():
    m = np.zeros((50, 50), np.uint8)
    m[5:40, 5:45] = 255
    m[10:12, 10:40] = 0
    safe = plan_fill_strokes_safe(m, spacing=2, margin=1)
    seen = set()
    h, w = m.shape
    for seg in safe:
        (x0, y0), (x1, y1) = seg
        assert y0 == y1 and x1 > x0
        assert 0 <= x0 < w and 0 <= x1 < w and 0 <= y0 < h
        key = (x0, y0, x1, y1)
        assert key not in seen, f"trajetória duplicada: {seg}"
        seen.add(key)
        # Segmentos devem estar sobre tinta da máscara original
        assert m[int(y0), int(x0)] == 255 and m[int(y1), int(x1)] == 255
