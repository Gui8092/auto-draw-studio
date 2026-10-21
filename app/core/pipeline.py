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
    if strat == "sombreado":
        # O sombreamento precisa dos tons (cinza) — só
        # `build_shaded_plan` sabe fazer. Sem os tons, cai no "auto".
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


def build_shaded_plan(
    mask: np.ndarray,
    gray: np.ndarray,
    settings: ProcessingSettings | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> DrawingPlan:
    """Plano com hachuras nas regiões de tom médio (modo "sombreado").

    - Traços finos → linha central (como no modo "auto").
    - Regiões escuras (tom médio da região < `hatch_threshold`) →
      preenchimento sólido por zigue-zague.
    - Regiões de tom médio → hachuras paralelas, com espaçamento
      proporcional à claridade (tom claro = hachura mais rala).

    É o que faz uma foto/ilustração virar um desenho a lápis: as áreas
    escuras ficam chapadas e as médias ganham textura.
    """
    from app.core.shading_planner import hatch_spacing_for, plan_hatch

    s = settings or ProcessingSettings()
    h, w = mask.shape[:2]
    plan = DrawingPlan(strokes=[], image_width=w, image_height=h,
                       spacing_px=float(max(1, s.fill_spacing)))
    ink = (np.asarray(mask) > 127).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    _check_cancel(cancel_check)

    thin_px = max(2.0, float(getattr(s, "thin_line_px", 4.0)))
    decision = classify_components(mask, thin_px=thin_px,
                                   min_area=float(s.min_detail_area),
                                   cancel_check=cancel_check)
    plan.strategy_notes = decision.explain()
    thin_labels = set(decision.thin_labels)

    # Tom médio de cada componente (bincount: O(1) por componente).
    gray_f = np.asarray(gray, dtype=np.float32)
    if gray_f.shape != ink.shape:
        gray_f = np.zeros(ink.shape, np.float32)
    sums = np.bincount(labels.ravel(), weights=gray_f.ravel(), minlength=n)
    counts = np.bincount(labels.ravel(), minlength=n)
    means = np.zeros(n, np.float32)
    np.divide(sums, np.maximum(counts, 1), out=means, where=counts > 0)

    solid_thr = float(getattr(s, "hatch_threshold", 120.0))
    hatch_labels: set[int] = set()
    for i in range(1, n):
        if i in thin_labels:
            continue
        if float(stats[i, cv2.CC_STAT_AREA]) < float(s.min_detail_area):
            continue  # detalhe pequeno: só contorno
        if float(means[i]) >= solid_thr:
            hatch_labels.add(i)

    # 1) Linhas centrais dos componentes finos.
    if thin_labels:
        thin_m = np.where(np.isin(labels, list(thin_labels)), 255, 0).astype(np.uint8)
        for chain in plan_centerlines(thin_m, cancel_check=cancel_check):
            plan.strokes.append(Stroke(points=chain, kind=StrokeType.CENTERLINE))

    # 2) Preenchimento sólido das regiões escuras (as hachuradas viram
    #    "buracos" e ficam de fora).
    exclude = set(thin_labels) | hatch_labels
    fill_m = np.asarray(mask)
    if exclude:
        fill_m = np.where(np.isin(labels, list(exclude)), 0, fill_m).astype(np.uint8)
    for poly in plan_fill_zigzag(fill_m, spacing=max(1, int(s.fill_spacing)),
                                 margin=1, cancel_check=cancel_check):
        plan.strokes.append(Stroke(points=poly, kind=StrokeType.FILL))

    # 3) Hachuras das regiões de tom médio.
    angle = float(getattr(s, "hatch_angle", 45.0))
    intensity = float(getattr(s, "shading_intensity", 0.5))
    base_sp = int(getattr(s, "hatch_spacing", 6))
    for i in sorted(hatch_labels):
        _check_cancel(cancel_check)
        # Trabalha só sobre a caixa do componente: `np.where(labels==i)`
        # e a varredura da grade de hachura varram a imagem INTEIRA
        # (o sombreado ficava ~10x mais lento que o modo "auto").
        lx = int(stats[i, cv2.CC_STAT_LEFT])
        ly = int(stats[i, cv2.CC_STAT_TOP])
        lw = int(stats[i, cv2.CC_STAT_WIDTH])
        lh = int(stats[i, cv2.CC_STAT_HEIGHT])
        x0, x1 = max(0, lx), min(w, lx + lw)
        y0, y1 = max(0, ly), min(h, ly + lh)
        sub_labels = labels[y0:y1, x0:x1]
        comp = np.where(sub_labels == i, 255, 0).astype(np.uint8)
        tone = float(means[i])
        spacing = hatch_spacing_for(tone, base_sp, intensity)
        # Hachura onde o pixel é mais escuro que o tom da região (as
        # sombras internas). A margem garante que uma região de tom
        # UNIFORME também receba hachura (sem ela, `gray < tom` nunca
        # seria verdade e a região ficaria vazia).
        thr = int(min(255.0, max(20.0, tone * 1.15 + 3.0)))
        sub_gray = gray[y0:y1, x0:x1]
        for poly in plan_hatch(sub_gray, comp, angle_deg=angle,
                               spacing=spacing, dark_thr=thr,
                               bbox=(0, 0, x1 - x0, y1 - y0)):
            if len(poly) >= 2:
                plan.strokes.append(Stroke(points=[
                    (p[0] + x0, p[1] + y0) for p in poly],
                    kind=StrokeType.HATCH))

    # 4) Contornos (externos + buracos) e detalhes.
    _add_contours(plan, mask, s, thin_labels=thin_labels, labels=labels)

    if not any(st.kind == StrokeType.HATCH for st in plan.strokes):
        plan.strategy_notes.append(
            "Sombreado: nenhuma hachura foi gerada. As hachuras cobrem os "
            "tons MÉDIOS — aumente o limiar (≈180) para incluí-los.")

    _check_cancel(cancel_check)
    simplify_plan(plan, float(s.simplify_epsilon))
    _check_cancel(cancel_check)
    order_plan(plan)
    return plan


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
    if getattr(settings, "strategy", "auto") == "sombreado":
        # O sombreamento usa os tons JÁ AJUSTADOS (brilho/contraste/gama):
        # a máscara saiu deles, e decidir "hachura ou preenchimento" com
        # o cinza ORIGINAL media o tom errado.
        plan = build_shaded_plan(mask, adj, settings, cancel_check=cancel_check)
    else:
        plan = build_plan(mask, settings, cancel_check=cancel_check)
    return mask, plan
