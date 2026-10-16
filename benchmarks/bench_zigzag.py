"""Benchmark reproduzível: estratégia legada (segmentos) vs zigue-zague.

Uso:  python benchmarks/bench_zigzag.py
Saída: tabela no console + PNGs em benchmarks/out/ (mascara, legado, novo).
"""
import math
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.contour_extractor import contours_to_polylines, extract_contours
from app.core.fill_planner import plan_fill_strokes_safe, plan_fill_zigzag
from app.core.path_optimizer import order_plan, simplify_plan, stroke_metrics
from app.core.quality_checker import check_quality, rasterize_plan
from app.models.drawing_plan import DrawingPlan, Stroke, StrokeType
from app.models.settings import ProcessingSettings

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(parents=True, exist_ok=True)
SPEED, DELAY = 1200.0, 0.03


def legacy_order(strokes):
    """Cópia fiel do order_plan anterior (guloso só pelo início, sem reversão)."""
    if len(strokes) <= 1:
        return strokes
    remaining = strokes[:]
    ordered = [remaining.pop(0)]
    cur = ordered[0].points[0]
    while remaining:
        bi, bd = 0, float("inf")
        for i, s in enumerate(remaining):
            p = s.points[0]
            d = (p[0] - cur[0]) ** 2 + (p[1] - cur[1]) ** 2
            if d < bd:
                bd, bi = d, i
        nxt = remaining.pop(bi)
        ordered.append(nxt)
        cur = nxt.points[-1]
    return ordered


def legacy_plan(mask, s):
    strokes = [Stroke(points=seg, kind=StrokeType.FILL)
               for seg in plan_fill_strokes_safe(mask, spacing=s.fill_spacing, margin=1)]
    mains, details = extract_contours(mask, min_area=s.min_detail_area,
                                      epsilon_factor=max(0.0005, s.simplify_epsilon / 500.0))
    for poly in contours_to_polylines([c for c in details if not c.is_hole], close=False):
        if len(poly) >= 2:
            strokes.append(Stroke(points=poly, kind=StrokeType.DETAIL))
    for c in mains:
        for poly in contours_to_polylines([c], close=True):
            strokes.append(Stroke(
                points=poly,
                kind=StrokeType.INNER_CONTOUR if c.is_hole else StrokeType.OUTER_CONTOUR))
    plan = DrawingPlan(strokes=strokes, image_width=mask.shape[1],
                       image_height=mask.shape[0], spacing_px=float(s.fill_spacing))
    simplify_plan(plan, float(s.simplify_epsilon))
    plan.strokes = legacy_order(plan.strokes)
    return plan


def new_plan(mask, s):
    strokes = [Stroke(points=poly, kind=StrokeType.FILL)
               for poly in plan_fill_zigzag(mask, spacing=s.fill_spacing, margin=1)]
    mains, details = extract_contours(mask, min_area=s.min_detail_area,
                                      epsilon_factor=max(0.0005, s.simplify_epsilon / 500.0))
    for poly in contours_to_polylines([c for c in details if not c.is_hole], close=False):
        if len(poly) >= 2:
            strokes.append(Stroke(points=poly, kind=StrokeType.DETAIL))
    for c in mains:
        for poly in contours_to_polylines([c], close=True):
            strokes.append(Stroke(
                points=poly,
                kind=StrokeType.INNER_CONTOUR if c.is_hole else StrokeType.OUTER_CONTOUR))
    plan = DrawingPlan(strokes=strokes, image_width=mask.shape[1],
                       image_height=mask.shape[0], spacing_px=float(s.fill_spacing))
    simplify_plan(plan, float(s.simplify_epsilon))
    order_plan(plan)
    return plan


def oob_points(plan):
    n = 0
    for s in plan.strokes:
        for x, y in s.points:
            if not (0 <= x <= plan.image_width - 1 and 0 <= y <= plan.image_height - 1):
                n += 1
    return n


def cases():
    out = {}
    m = np.zeros((200, 200), np.uint8); m[40:160, 40:160] = 255; out["quadrado"] = m
    m = np.zeros((200, 200), np.uint8); cv2.circle(m, (100, 100), 70, 255, -1); out["circulo"] = m
    m = np.zeros((200, 200), np.uint8)
    cv2.circle(m, (100, 100), 70, 255, -1); cv2.circle(m, (100, 100), 35, 0, -1)
    out["anel"] = m
    m = np.zeros((200, 200), np.uint8)
    cv2.fillPoly(m, [np.array([[100, 20], [20, 170], [180, 170]])], 255)
    cv2.line(m, (20, 20), (180, 180), 255, 2); out["triangulo_diag"] = m
    m = np.zeros((200, 200), np.uint8)
    cv2.rectangle(m, (15, 15), (85, 85), 255, -1)
    cv2.circle(m, (145, 50), 35, 255, -1)
    cv2.rectangle(m, (110, 110), (185, 185), 255, -1); out["logo_3regioes"] = m
    m = np.zeros((200, 200), np.uint8)
    m[30:150, 30:150] = 255; m[160, 10:190] = 255; out["espesso_fino"] = m
    return out


def side_by_side(mask, old, new, name):
    h, w = mask.shape[:2]
    canvas = np.full((h, w * 3 + 20), 255, np.uint8)
    canvas[:, :w] = 255 - mask
    canvas[:, w + 10:2 * w + 10] = 255 - rasterize_plan(old, 2)
    canvas[:, 2 * w + 20:3 * w + 20] = 255 - rasterize_plan(new, 2)
    cv2.imwrite(str(OUT / f"{name}.png"), canvas)


def main():
    s = ProcessingSettings(fill_spacing=4)
    print(f"{'caso':<14}{'tracos':>12}{'lifts':>10}{'penUp':>12}{'eta(s)':>10}{'cobert':>9}")
    print(f"{'':<14}{'old>new':>12}{'old>new':>10}{'old>new':>12}{'old>new':>10}{'old>new':>9}")
    for name, mask in cases().items():
        old, new = legacy_plan(mask, s), new_plan(mask, s)
        mo, mn = stroke_metrics(old), stroke_metrics(new)
        ro = check_quality(old, mask, thickness=2)
        rn = check_quality(new, mask, thickness=2)
        eo = old.estimate_duration(SPEED, DELAY)
        en = new.estimate_duration(SPEED, DELAY)
        print(f"{name:<14}{mo['total_strokes']:>5}>{mn['total_strokes']:<5}"
              f"{mo['lifts']:>5}>{mn['lifts']:<4}{mo['pen_up']:>6.0f}>{mn['pen_up']:<5.0f}"
              f"{eo:>5.1f}>{en:<4.1f}{ro.coverage:>5.0%}>{rn.coverage:<4.0%}  "
              f"overflow {ro.overflow:.0%}>{rn.overflow:.0%} buracos {ro.holes_preserved}>{rn.holes_preserved} "
              f"oob {oob_points(old)}>{oob_points(new)}")
        side_by_side(mask, old, new, name)
    print(f"\nPNGs em {OUT} (colunas: máscara | legado | novo).")


if __name__ == "__main__":
    main()
