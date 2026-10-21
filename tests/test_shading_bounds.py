"""Regressão CORREÇÃO 4: hachuras sempre dentro dos limites da imagem."""
import numpy as np

from app.core.shading_planner import plan_hatching, plan_stipple


def assert_in_bounds(strokes, w, h):
    for seg in strokes:
        for x, y in seg:
            assert 0 <= x <= w - 1, f"x={x} fora de [0,{w - 1}]"
            assert 0 <= y <= h - 1, f"y={y} fora de [0,{h - 1}]"


def test_black_60x60_no_out_of_bounds():
    g = np.full((60, 60), 0, np.uint8)
    for angle in (0.0, 45.0, 90.0, 135.0):
        strokes = plan_hatching(g, spacing=6, angle_deg=angle)
        assert strokes, f"imagem preta deve gerar hachuras (ângulo {angle})"
        assert_in_bounds(strokes, 60, 60)


def test_hatch_points_belong_to_target():
    g = np.full((60, 60), 255, np.uint8)
    g[10:50, 10:50] = 0  # quadrado escuro central
    strokes = plan_hatching(g, spacing=5, angle_deg=45.0)
    assert strokes
    assert_in_bounds(strokes, 60, 60)
    for seg in strokes:
        for x, y in seg:
            assert g[int(y), int(x)] < 200, f"ponto {(x, y)} fora da região escura"


def test_hatch_respects_mask():
    g = np.full((40, 40), 0, np.uint8)
    mask = np.zeros((40, 40), np.uint8)
    mask[:, :20] = 255  # só metade esquerda permite tinta
    strokes = plan_hatching(g, mask=mask, spacing=4)
    assert_in_bounds(strokes, 40, 40)
    for seg in strokes:
        for x, y in seg:
            assert mask[int(y), int(x)] == 255


def test_hatch_edge_regions_and_empty():
    g = np.full((30, 30), 255, np.uint8)
    g[0:3, :] = 0  # faixa encostada na borda superior
    strokes = plan_hatching(g, spacing=3)
    assert_in_bounds(strokes, 30, 30)
    white = np.full((20, 20), 255, np.uint8)
    assert plan_hatching(white) == []
    assert plan_stipple(white) == []


def test_stipple_in_bounds():
    g = np.full((25, 25), 0, np.uint8)
    dots = plan_stipple(g, step=5)
    assert dots
    assert_in_bounds(dots, 25, 25)
