"""Regressão da otimização: zigue-zague contínuo, seguro e fiel."""
import cv2
import numpy as np
import pytest

from app.core.fill_planner import plan_fill_strokes_safe, plan_fill_zigzag
from app.core.path_optimizer import (order_plan, pen_down_length,
                                     pen_up_travel, stroke_metrics)
from app.core.quality_checker import check_quality
from app.models.drawing_plan import DrawingPlan, Stroke, StrokeType
from app.models.settings import ProcessingSettings


def square(size=100, sq=60):
    m = np.zeros((size, size), np.uint8)
    m[(size - sq) // 2:(size + sq) // 2, (size - sq) // 2:(size + sq) // 2] = 255
    return m


def ring():
    m = np.zeros((100, 100), np.uint8)
    cv2.circle(m, (50, 50), 35, 255, -1)
    cv2.circle(m, (50, 50), 15, 0, -1)
    return m


def test_zigzag_square_single_continuous_chain():
    m = square()
    zz = plan_fill_zigzag(m, spacing=4, margin=1)
    old = plan_fill_strokes_safe(m, spacing=4, margin=1)
    assert len(zz) < len(old), "zigue-zague deve unir linhas"
    assert len(zz) == 1
    rows = {int(round(y)) for _, y in zz[0]}
    assert len(rows) > 5, "cadeia deve cobrir várias linhas do interior"
    for x, y in zz[0]:
        assert 0 <= x <= 99 and 0 <= y <= 99
        assert m[int(y), int(x)] == 255, "vértice fora da tinta"


def test_zigzag_ring_never_crosses_hole():
    m = ring()
    zz = plan_fill_zigzag(m, spacing=4, margin=1)
    assert len(zz) >= 1
    # Vértices sobre tinta e dentro dos limites
    for seg in zz:
        for x, y in seg:
            assert 0 <= x <= 99 and 0 <= y <= 99
            assert m[int(y), int(x)] == 255
    # Rasteriza só os fills: o centro do furo deve continuar branco
    canvas = np.zeros_like(m)
    for seg in zz:
        pts = np.array([(int(round(x)), int(round(y))) for x, y in seg], np.int32)
        cv2.polylines(canvas, [pts], False, 255, 1, cv2.LINE_8)
    assert canvas[50, 50] == 0, "zigue-zague atravessou o furo"
    assert (canvas[44:57, 44:57] == 0).all(), "interior do furo invadido"


def test_zigzag_does_not_join_separate_regions():
    m = np.zeros((100, 100), np.uint8)
    cv2.rectangle(m, (5, 20), (30, 80), 255, -1)
    cv2.rectangle(m, (60, 20), (90, 80), 255, -1)
    zz = plan_fill_zigzag(m, spacing=4, margin=1)
    assert zz, "regiões precisam de preenchimento"
    for seg in zz:
        xs = [x for x, _ in seg]
        assert not (min(xs) < 31 and max(xs) > 59), \
            f"cadeia conectou regiões independentes: {seg}"


def test_zigzag_preserves_thin_and_thick():
    m = np.zeros((40, 60), np.uint8)
    m[5:15, 5:55] = 255
    m[30, 5:55] = 255
    zz = plan_fill_zigzag(m, spacing=1, margin=1)
    rows = sorted({int(round(y)) for seg in zz for _, y in seg})
    assert 30 in rows, "detalhe fino perdido no zigue-zague"
    assert any(5 <= y <= 14 for y in rows), "região espessa sem fill"
    assert zz != [] and plan_fill_zigzag(np.zeros((20, 20), np.uint8)) == []


def test_zigzag_no_duplicates_valid_coords():
    m = square(60, 40)
    zz = plan_fill_zigzag(m, spacing=3, margin=1)
    seen = set()
    for seg in zz:
        assert len(seg) >= 2
        for i in range(1, len(seg)):
            assert seg[i] != seg[i - 1], "vértices consecutivos duplicados"
        for x, y in seg:
            assert 0 <= x <= 59 and 0 <= y <= 59
            assert m[int(y), int(x)] == 255
        key = tuple(seg)
        assert key not in seen
        seen.add(key)


def test_order_reversal_reduces_travel_preserves_ink():
    strokes = [Stroke(points=[(float(i * 20), 0.0), (float(i * 20 + 10), 0.0)],
                      kind=StrokeType.FILL) for i in (0, 2, 1, 3)]
    plan = DrawingPlan(strokes=[Stroke(points=list(s.points), kind=s.kind)
                                for s in strokes],
                       image_width=100, image_height=100)
    down_before = pen_down_length(plan.strokes)
    order_plan(plan)
    assert pen_down_length(plan.strokes) == down_before, "reversão mudou a tinta"
    assert plan.total_strokes == 4
    # Conjunto de segmentos inalterado (a menos de direção)
    segs = {frozenset((round(x), round(y)) for x, y in s.points) for s in plan.strokes}
    assert len(segs) == 4


def test_metrics_and_estimate_include_travel():
    s1 = Stroke(points=[(0.0, 0.0), (10.0, 0.0)], kind=StrokeType.FILL)
    s2 = Stroke(points=[(100.0, 0.0), (110.0, 0.0)], kind=StrokeType.FILL)
    plan = DrawingPlan(strokes=[s1, s2], image_width=200, image_height=50)
    m = stroke_metrics(plan)
    assert m["total_strokes"] == 2 and m["lifts"] == 2 and m["presses"] == 2
    assert m["pen_down"] == 20.0
    assert m["pen_up"] == 90.0
    eta = plan.estimate_duration(10.0, 0.0)
    assert eta == pytest.approx((20.0 + 90.0) / 10.0), "ETA deve incluir travel pen-up"
    single = DrawingPlan(strokes=[s1], image_width=200, image_height=50)
    assert stroke_metrics(single)["pen_up"] == 0.0


def test_estimate_models_instant_move_floor():
    # 5px a 1000px/s = 0,005s <= piso 0,1s → move instantâneo, custa ~0.
    tiny = DrawingPlan(
        strokes=[Stroke(points=[(0.0, 0.0), (5.0, 0.0)], kind=StrokeType.FILL)],
        image_width=200, image_height=50)
    assert tiny.estimate_duration(1000.0, 0.0) == pytest.approx(0.0)
    # 500px a 1000px/s = 0,5s > piso → contado normalmente.
    long = DrawingPlan(
        strokes=[Stroke(points=[(0.0, 0.0), (500.0, 0.0)], kind=StrokeType.FILL)],
        image_width=600, image_height=50)
    assert long.estimate_duration(1000.0, 0.0) == pytest.approx(0.5)


def test_zigzag_quality_matches_legacy():
    for m in (square(), ring()):
        s = ProcessingSettings(fill_spacing=4)
        old = [Stroke(points=seg, kind=StrokeType.FILL)
               for seg in plan_fill_strokes_safe(m, spacing=4, margin=1)]
        new = [Stroke(points=poly, kind=StrokeType.FILL)
               for poly in plan_fill_zigzag(m, spacing=4, margin=1)]
        po = DrawingPlan(strokes=old, image_width=100, image_height=100)
        pn = DrawingPlan(strokes=new, image_width=100, image_height=100)
        ro = check_quality(po, m, thickness=2)
        rn = check_quality(pn, m, thickness=2)
        assert rn.coverage >= ro.coverage - 0.02, (ro.coverage, rn.coverage)
        assert rn.overflow <= ro.overflow + 0.02, (ro.overflow, rn.overflow)
        assert rn.holes_preserved and not rn.missing_fill
