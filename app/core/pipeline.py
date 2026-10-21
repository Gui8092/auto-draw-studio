"""Pipeline: máscara + cinza → DrawingPlan (híbrido por região)."""
from __future__ import annotations

from typing import Callable

import cv2
import numpy as np

from app.core.centerline import plan_centerlines
from app.core.contour_extractor import contours_to_polylines, extract_contours
from app.core.fill_planner import plan_fill_zigzag
from app.core.path_optimizer import order_plan, simplify_plan
from app.core.strategy import STRATEGIES, classify_components
from app.models.drawing_plan import DrawingPlan, Stroke, StrokeType
from app.models.settings import ProcessingSettings


class ProcessingCancelled(Exception):
    """Cancelamento cooperativo do processamento.

    Levantada quando o `cancel_check` informado indica que o trabalho
    deve ser abortado (ex.: a janela está sendo fechada).
    """


def _check_cancel(cancel_check: Callable[[], bool] | None) -> None:
    if cancel_check is not None and cancel_check():
        raise ProcessingCancelled("Processamento cancelado.")


def _contour_label(cx: float, cy: float, labels: np.ndarray) -> int:
    h, w = labels.shape[:2]
    x, y = int(round(cx)), int(round(cy))
    if 0 <= x < w and 0 <= y < h:
        return int(labels[y, x])
    return -1


def _contour_component_label(c, labels: np.ndarray) -> int:
    """Label da componente de tinta a que o contorno pertence.

    Procura um VÉRTICE do contorno (e não a média dos vértices): em
    formas não convexes (U, O, C, V) a média cai no FUNDO, o label
    vinha 0 e o componente fino não era identificado — ele era
    desenhado DUAS vezes (centerline + contorno duplicado).
    """
    if not c.points.size:
        return -1
    h, w = labels.shape[:2]
    n = len(c.points)
    for i in (0, n // 2, n - 1):
        x = int(round(float(c.points[i, 0, 0])))
        y = int(round(float(c.points[i, 0, 1])))
        if 0 <= x < w and 0 <= y < h:
            lab = int(labels[y, x])
            if lab > 0:
                return lab
    # Fallback: média dos vértices (forma convexa, sem vértice na tinta).
    cx = float(c.points[:, 0, 0].mean())
    cy = float(c.points[:, 0, 1].mean())
    return _contour_label(cx, cy, labels)


def build_plan(
    mask: np.ndarray,
    settings: ProcessingSettings | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> DrawingPlan:
    """Monta o plano conforme a estratégia (`settings.strategy`).

    - "fill": zigue-zague global + contornos (comportamento anterior).
    - "contour": só contornos/detalhes (bordas limpas, sem preenchimento).
    - "centerline": só linhas centrais (line art; sem preenchimento).
    - "auto": por componente — traço fino vira centerline (sem contorno
      duplicado), região sólida vira zigue-zague + contornos, furos
      preservados em todos os modos.

    `cancel_check` (opcional): callback consultado em pontos seguros;
    quando retorna True, levanta `ProcessingCancelled`.

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
    _check_cancel(cancel_check)

    if strat == "centerline":
        for chain in plan_centerlines((ink * 255).astype(np.uint8),
                                      cancel_check=cancel_check):
            plan.strokes.append(Stroke(points=chain, kind=StrokeType.CENTERLINE))
        if not plan.strokes:
            # Uma região SÓLIDA colapsa num único pixel no esqueleto e
            # não gera traço nenhum: o plano ficava vazio e sem aviso.
            plan.strategy_notes.append(
                "Estratégia 'centerline': nenhuma linha central encontrada "
                "(a imagem tem regiões sólidas, não traços finos).")
    elif strat == "contour":
        _add_contours(plan, mask, s, thin_labels=None, labels=labels)
    else:
        thin_labels: set[int] | None = None
        fill_m = mask
        if strat == "auto":
            # `thin_line_px` é independente do espaçamento do
            # preenchimento: antes, `thin_px` vinha de `fill_spacing` e
            # mudar o espaçamento trocava linha↔sólido em silêncio.
            thin_px = max(2.0, float(getattr(s, "thin_line_px", 4.0)))
            decision = classify_components(mask, thin_px=thin_px,
                                           min_area=float(s.min_detail_area),
                                           cancel_check=cancel_check)
            plan.strategy_notes = decision.explain()
            thin_labels = set(decision.thin_labels)
            if thin_labels:
                keep = np.isin(labels, list(thin_labels))
                thin_m = np.where(keep, 255, 0).astype(np.uint8)
                for chain in plan_centerlines(thin_m, cancel_check=cancel_check):
                    plan.strokes.append(Stroke(points=chain, kind=StrokeType.CENTERLINE))
                fill_m = np.where(~keep, np.asarray(mask), 0).astype(np.uint8)
        # 1. Preenchimento contínuo em zigue-zague (interiores sem listras de
        # levantamentos; cada polilinha = um único mouse-down/up).
        for poly in plan_fill_zigzag(fill_m, spacing=max(1, int(s.fill_spacing)),
                                     margin=1, cancel_check=cancel_check):
            plan.strokes.append(Stroke(points=poly, kind=StrokeType.FILL))
        # 2. Contornos (externos + buracos) e detalhes — exceto contornos de
        # componentes finos, já cobertos pela centerline.
        _add_contours(plan, mask, s, thin_labels=thin_labels, labels=labels)

    # 3. Simplificação + ordenação
    _check_cancel(cancel_check)
    simplify_plan(plan, float(s.simplify_epsilon))
    _check_cancel(cancel_check)
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
            if _contour_component_label(c, labels) in thin_labels:
                continue
        # `close=True`: um detalhe é um contorno, não uma curva aberta —
        # desenhado aberto, ficava com uma fresta.
        for poly in contours_to_polylines([c], close=True):
            if len(poly) >= 2:
                plan.strokes.append(Stroke(points=poly, kind=StrokeType.DETAIL))
    for c in mains:
        if not c.is_hole and thin_labels and c.points.size:
            if _contour_component_label(c, labels) in thin_labels:
                continue  # centerline já cobre este componente fino
        for poly in contours_to_polylines([c], close=True):
            kind = StrokeType.INNER_CONTOUR if c.is_hole else StrokeType.OUTER_CONTOUR
            plan.strokes.append(Stroke(points=poly, kind=kind))


def process_to_plan(
    gray: np.ndarray,
    settings: ProcessingSettings,
    cancel_check: Callable[[], bool] | None = None,
) -> tuple[np.ndarray, DrawingPlan]:
    """Aplica denoise→binarize→morfologia→plano. Retorna (máscara, plano).

    `cancel_check` (opcional): callback consultado entre as etapas e
    dentro dos laços longos; quando retorna True, levanta
    `ProcessingCancelled` — encerramento seguro do worker thread.
    """
    from app.core.morphology import apply_morphology
    from app.core.preprocessing import apply_adjustments, denoise
    from app.core.thresholding import binarize

    _check_cancel(cancel_check)
    adj = apply_adjustments(gray, settings.brightness, settings.contrast, settings.gamma)
    _check_cancel(cancel_check)
    adj = denoise(adj, settings.denoise)
    _check_cancel(cancel_check)
    mask = binarize(adj, settings.method, settings.threshold, settings.invert)
    _check_cancel(cancel_check)
    mask = apply_morphology(mask, settings.morph_op, settings.morph_kernel)
    _check_cancel(cancel_check)
    plan = build_plan(mask, settings, cancel_check=cancel_check)
    return mask, plan
