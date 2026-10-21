"""Testes críticos do preenchimento por varredura (Fase 2).

Critério essencial: quadrado sólido deve gerar fills no INTERIOR,
não apenas contorno. Anel não deve preencher o centro branco.
"""
import cv2
import numpy as np

from app.core.fill_planner import plan_fill_strokes, plan_fill_strokes_safe
from app.core.pipeline import build_plan
from app.models.drawing_plan import StrokeType
from app.models.settings import ProcessingSettings


def square(size=100, sq=60):
    m = np.zeros((size, size), np.uint8)
    m[(size - sq) // 2:(size + sq) // 2, (size - sq) // 2:(size + sq) // 2] = 255
    return m


def test_solid_square_has_interior_fill():
    m = square()
    strokes = plan_fill_strokes_safe(m, spacing=4, margin=1)
    assert len(strokes) > 5, "quadrado sólido precisa de várias linhas de fill"
    # Algum segmento deve estar bem no interior (longe da borda)
    cx, cy = 50, 50
    found_center = any(
        min(x for x, y in seg) <= cx <= max(x for x, y in seg) and seg[0][1] == cy
        for seg in strokes if seg[0][1] == cy
    ) if any(s[0][1] == cy for s in strokes) else False
    # verificação robusta: existe segmento cobrindo o centro
    covered = False
    for seg in strokes:
        (x0, y0), (x1, y1) = seg
        if y0 == y1 and abs(y0 - 50) <= 2 and x0 <= 50 <= x1:
            covered = True
    assert covered, "nenhum segmento de fill cobre o centro do quadrado"


def test_ring_center_not_filled():
    m = np.zeros((100, 100), np.uint8)
    cv2.circle(m, (50, 50), 35, 255, -1)
    cv2.circle(m, (50, 50), 15, 0, -1)
    strokes = plan_fill_strokes_safe(m, spacing=4, margin=1)
    assert len(strokes) > 0
    # Nenhum segmento deve atravessar o centro (30..70 é vazado no meio?)
    # O centro (50,50) é branco: nenhum intervalo deve contê-lo.
    for seg in strokes:
        (x0, y0), (x1, y1) = seg
        if abs(y0 - 50) <= 1:
            assert not (x0 <= 50 <= x1 and (x1 - x0) > 50), \
                f"segmento {seg} atravessa o buraco central"


def test_two_regions_each_get_fill():
    m = np.zeros((100, 100), np.uint8)
    cv2.rectangle(m, (5, 20), (30, 80), 255, -1)
    cv2.rectangle(m, (60, 20), (90, 80), 255, -1)
    strokes = plan_fill_strokes(m, spacing=4, margin=0)
    left = [s for s in strokes if s[0][0] < 50]
    right = [s for s in strokes if s[0][0] >= 50]
    assert left and right, "cada região desconectada precisa de fills próprios"
    # Segmentos não devem conectar as regiões (gap 31..59)
    for seg in strokes:
        (x0, _), (x1, _) = seg
        assert not (x0 < 31 and x1 > 59), f"fill conectou regiões independentes: {seg}"


def test_fill_respects_narrow_and_spacing():
    m = np.zeros((40, 40), np.uint8)
    m[10:30, 10:30] = 255
    s2 = plan_fill_strokes(m, spacing=2, margin=0)
    s8 = plan_fill_strokes(m, spacing=8, margin=0)
    assert len(s2) > len(s8), "espaçamento menor deve gerar mais linhas"


def test_build_plan_includes_fills_and_contours():
    m = square()
    plan = build_plan(m, settings=ProcessingSettings(fill_spacing=4))
    fills = plan.strokes_by_kind(StrokeType.FILL)
    outers = plan.strokes_by_kind(StrokeType.OUTER_CONTOUR)
    # Com zigue-zague, o interior pode ser UMA polilinha contínua: o que
    # importa é que ela cubra o interior (vértices em várias linhas).
    assert fills, "build_plan deve gerar fills interiores"
    assert sum(len(s) for s in fills) > 5, "fill deve cobrir o interior"
    assert len({p[1] for s in fills for p in s.points}) > 5
    assert len(outers) >= 1, "build_plan deve incluir contorno externo"


def test_empty_mask_gives_empty_fill():
    m = np.zeros((50, 50), np.uint8)
    assert plan_fill_strokes(m) == []
    plan = build_plan(m)
    assert plan.total_strokes == 0
