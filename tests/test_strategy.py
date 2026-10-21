"""Fase B: seleção de estratégia por região + perfis."""
import cv2
import numpy as np

from app.core.pipeline import build_plan
from app.core.strategy import (PROFILE_NAMES, PROFILES, apply_profile,
                               classify_components)
from app.models.drawing_plan import StrokeType
from app.models.settings import ProcessingSettings


def test_thin_goes_centerline_solid_goes_fill():
    m = np.zeros((120, 120), np.uint8)
    m[10:60, 10:60] = 255      # sólido 50x50
    m[100, 10:110] = 255       # traço fino 1px
    dec = classify_components(m, thin_px=4.0)
    by_area = sorted(dec.components, key=lambda c: c.area)
    assert by_area[0].strategy == "centerline"
    assert by_area[-1].strategy == "fill"
    assert len(dec.thin_labels) == 1
    assert dec.explain(), "explicação exigida pela Fase 2.5"


def test_hole_flagged():
    m = np.zeros((80, 80), np.uint8)
    cv2.circle(m, (40, 40), 30, 255, -1)
    cv2.circle(m, (40, 40), 10, 0, -1)
    dec = classify_components(m, thin_px=4.0)
    assert any(c.has_hole for c in dec.components)
    assert all(c.strategy == "fill" for c in dec.components)


def test_profiles_change_params_coherently():
    base = ProcessingSettings()
    fast = apply_profile(base, "rapido")
    assert fast.fill_spacing > base.fill_spacing
    assert fast.simplify_epsilon > base.simplify_epsilon
    assert base.fill_spacing == 4, "perfil não pode mutar o original"
    line = apply_profile(base, "linha_fina")
    assert line.strategy == "centerline"
    assert apply_profile(base, "inexistente") == base
    assert set(PROFILE_NAMES) == set(PROFILES)


def test_pipeline_modes():
    m = np.zeros((100, 100), np.uint8)
    m[20:80, 20:80] = 255
    m[50, 0:100] = 255  # corta com linha fina? não — sólido; usa outra imagem
    thin = np.zeros((100, 100), np.uint8)
    cv2.line(thin, (5, 50), (95, 50), 255, 2)
    p_fill = build_plan(m, ProcessingSettings(fill_spacing=4, strategy="fill"))
    assert p_fill.strokes_by_kind(StrokeType.FILL)
    assert not p_fill.strokes_by_kind(StrokeType.CENTERLINE)
    p_con = build_plan(m, ProcessingSettings(fill_spacing=4, strategy="contour"))
    assert not p_con.strokes_by_kind(StrokeType.FILL)
    assert not p_con.strokes_by_kind(StrokeType.CENTERLINE)
    assert p_con.strokes_by_kind(StrokeType.OUTER_CONTOUR)
    p_cen = build_plan(thin, ProcessingSettings(fill_spacing=4, strategy="centerline"))
    assert p_cen.strokes_by_kind(StrokeType.CENTERLINE)
    assert not p_cen.strokes_by_kind(StrokeType.FILL)
    # auto: fino vira centerline SEM contorno duplicado
    p_auto = build_plan(thin, ProcessingSettings(fill_spacing=4, strategy="auto"))
    assert p_auto.strokes_by_kind(StrokeType.CENTERLINE)
    assert not p_auto.strokes_by_kind(StrokeType.OUTER_CONTOUR), \
        "contorno duplicaria a linha fina"
    assert p_auto.strategy_notes, "auto deve explicar as escolhas"
    # auto no sólido: igual ao fill + notas
    p_as = build_plan(m, ProcessingSettings(fill_spacing=4, strategy="auto"))
    assert p_as.strokes_by_kind(StrokeType.FILL)
    assert p_as.strategy_notes


def test_auto_hole_preserved_with_centerline_nearby():
    m = np.zeros((120, 120), np.uint8)
    cv2.circle(m, (40, 40), 30, 255, -1)
    cv2.circle(m, (40, 40), 10, 0, -1)
    cv2.line(m, (90, 10), (90, 110), 255, 2)
    plan = build_plan(m, ProcessingSettings(fill_spacing=4, strategy="auto"))
    assert plan.strokes_by_kind(StrokeType.INNER_CONTOUR), "furo preservado"
    assert plan.strokes_by_kind(StrokeType.CENTERLINE)
    assert plan.strokes_by_kind(StrokeType.FILL)
