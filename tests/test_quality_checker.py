"""Testes do quality_checker via rasterização."""
import cv2
import numpy as np

from app.core.pipeline import build_plan
from app.core.quality_checker import check_quality, rasterize_plan
from app.models.settings import ProcessingSettings


def square(size=100, sq=60):
    m = np.zeros((size, size), np.uint8)
    m[(size - sq) // 2:(size + sq) // 2, (size - sq) // 2:(size + sq) // 2] = 255
    return m


def test_good_plan_high_coverage():
    m = square()
    plan = build_plan(m, settings=ProcessingSettings(fill_spacing=3))
    rep = check_quality(plan, m, thickness=2)
    assert rep.coverage > 0.85, f"cobertura {rep.coverage:.0%} insuficiente"
    assert not rep.missing_fill
    assert rep.holes_preserved


def test_contour_only_plan_warns_missing_fill():
    # Simula o bug "só bordas": plano só com contorno
    m = square()
    empty_plan = build_plan(np.zeros_like(m))
    rep = check_quality(empty_plan, m, thickness=2)
    assert rep.coverage < 0.5
    assert len(rep.warnings) > 0


def test_ring_holes_preserved():
    m = np.zeros((100, 100), np.uint8)
    cv2.circle(m, (50, 50), 35, 255, -1)
    cv2.circle(m, (50, 50), 15, 0, -1)
    plan = build_plan(m, settings=ProcessingSettings(fill_spacing=4))
    rep = check_quality(plan, m, thickness=2)
    assert rep.holes_preserved, f"avisos: {rep.warnings}"


def test_empty_plan_and_empty_mask():
    m = np.zeros((50, 50), np.uint8)
    plan = build_plan(m)
    rep = check_quality(plan, m)
    assert rep.coverage == 1.0
    assert rep.simulated_ink_px == 0


def test_rasterize_thickness():
    m = square(40, 20)
    plan = build_plan(m, settings=ProcessingSettings(fill_spacing=4))
    thin = rasterize_plan(plan, thickness=1)
    thick = rasterize_plan(plan, thickness=3)
    assert thick.sum() >= thin.sum()
