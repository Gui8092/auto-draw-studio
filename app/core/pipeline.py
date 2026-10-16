"""Pipeline: máscara + cinza → DrawingPlan (híbrido por região)."""
from __future__ import annotations

import cv2
import numpy as np

from app.core.centerline import plan_centerlines
from app.core.contour_extractor import contours_to_polylines, extract_contours
from app.core.fill_planner import plan_fill_zigzag
from app.core.path_optimizer import order_plan, simplify_plan
from app.core.strategy import STRATEGIES, classify_components
from app.models.drawing_plan import DrawingPlan, Stroke, StrokeType
from app.models.settings import ProcessingSettings


def _contour_label(cx: float, cy: float, labels: np.ndarray) -> int:
    h, w = labels.shape[:2]
    x, y = int(round(cx)), int(round(cy))
    if 0 <= x < w and 0 <= y < h:
        return int(labels[y, x])
    return -1


def build_plan(
    mask: np.ndarray,
    settings: ProcessingSettings | None = None,
) -> DrawingPlan:
    """Monta o plano conforme a estratégia (`settings.strategy`).

    - "fill": zigue-zague global + contornos (comportamento anterior).
    - "contour": só contornos/detalhes (bordas limpas, sem preenchimento).
    - "centerline": só linhas centrais (line art; sem preenchimento).
    - "auto": por componente — traço fino vira centerline (sem contorno
      duplicado), região sólida vira zigue-zague + contornos, furos
      preservados em todos os modos.

    Nota: `shading_planner` permanece experimental e NÃO está integrado.
    `detail_strength`/`shading_intensity` continuam reservados.
    """
    s = settings or ProcessingSettings()
    h, w = mask.shape[:2]
    strat = getattr(s, "strategy", "auto")
    if strat not in STRATEGIES:
        strat = "auto"
    plan = DrawingPlan(strokes=[], image_width=w, image_height=h,
                       spacing_px=float(max(1, s.fill_spacing)))
    ink = (np.asarray(mask) > 127).astype(np.uint8)
    _, labels = cv2.connectedComponents(ink, 8)

    if strat == "centerline":
        for chain in plan_centerlines((ink * 255).astype(np.uint8)):
            plan.strokes.append(Stroke(points=chain, kind=StrokeType.CENTERLINE))
    elif strat == "contour":
        _add_contours(plan, mask, s, thin_labels=None, labels=labels)
    else:
        thin_labels: set[int] | None = None
        fill_m = mask
        if strat == "auto":
            thin_px = max(3.0, float(s.fill_spacing))
            decision = classify_components(mask, thin_px=thin_px,
                                           min_area=float(s.min_detail_area))
            plan.strategy_notes = decision.explain()
            thin_labels = set(decision.thin_labels)
            if thin_labels:
                keep = np.isin(labels, list(thin_labels))
                thin_m = np.where(keep, 255, 0).astype(np.uint8)
                for chain in plan_centerlines(thin_m):
                    plan.strokes.append(Stroke(points=chain, kind=StrokeType.CENTERLINE))
                fill_m = np.where(~keep, np.asarray(mask), 0).astype(np.uint8)
        # 1. Preenchimento contínuo em zigue-zague (interiores sem listras de
        # levantamentos; cada polilinha = um único mouse-down/up).
        for poly in plan_fill_zigzag(fill_m, spacing=max(1, int(s.fill_spacing)), margin=1):
            plan.strokes.append(Stroke(points=poly, kind=StrokeType.FILL))
        # 2. Contornos (externos + buracos) e detalhes — exceto contornos de
        # componentes finos, já cobertos pela centerline.
        _add_contours(plan, mask, s, thin_labels=thin_labels, labels=labels)

    # 3. Simplificação + ordenação
    simplify_plan(plan, float(s.simplify_epsilon))
    order_plan(plan)
    return plan


def _add_contours(plan: DrawingPlan, mask: np.ndarray, s: ProcessingSettings,
                  thin_labels: set[int] | None, labels: np.ndarray):
    mains, details = extract_contours(
        mask, min_area=float(s.min_detail_area),
        epsilon_factor=max(0.0005, float(s.simplify_epsilon) / 500.0),
    )
    for c in details:
        if c.is_hole:
            continue
        if thin_labels and c.points.size:
            cx = float(c.points[:, 0, 0].mean())
            cy = float(c.points[:, 0, 1].mean())
            if _contour_label(cx, cy, labels) in thin_labels:
                continue
        for poly in contours_to_polylines([c], close=False):
            if len(poly) >= 2:
                plan.strokes.append(Stroke(points=poly, kind=StrokeType.DETAIL))
    for c in mains:
        if not c.is_hole and thin_labels and c.points.size:
            cx = float(c.points[:, 0, 0].mean())
            cy = float(c.points[:, 0, 1].mean())
            if _contour_label(cx, cy, labels) in thin_labels:
                continue  # centerline já cobre este componente fino
        for poly in contours_to_polylines([c], close=True):
            kind = StrokeType.INNER_CONTOUR if c.is_hole else StrokeType.OUTER_CONTOUR
            plan.strokes.append(Stroke(points=poly, kind=kind))


def process_to_plan(
    gray: np.ndarray,
    settings: ProcessingSettings,
) -> tuple[np.ndarray, DrawingPlan]:
    """Aplica denoise→binarize→morfologia→plano. Retorna (máscara, plano)."""
    from app.core.morphology import apply_morphology
    from app.core.preprocessing import apply_adjustments, denoise
    from app.core.thresholding import binarize

    adj = apply_adjustments(gray, settings.brightness, settings.contrast, settings.gamma)
    adj = denoise(adj, settings.denoise)
    mask = binarize(adj, settings.method, settings.threshold, settings.invert)
    mask = apply_morphology(mask, settings.morph_op, settings.morph_kernel)
    plan = build_plan(mask, settings)
    return mask, plan
