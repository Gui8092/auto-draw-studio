"""Otimização: simplificação + ordenação para reduzir deslocamentos."""
from __future__ import annotations

import math

import cv2
import numpy as np

from app.models.drawing_plan import DrawingPlan, Stroke, StrokeType


def simplify_polyline(points: list[tuple[float, float]], epsilon: float) -> list[tuple[float, float]]:
    if len(points) <= 2 or epsilon <= 0:
        return list(points)
    arr = np.array(points, dtype=np.float32).reshape(-1, 1, 2)
    approx = cv2.approxPolyDP(arr, float(epsilon), False)
    out = [(float(p[0][0]), float(p[0][1])) for p in approx]
    # Segmentos de fill (2 pontos) nunca devem colapsar para 1 ponto
    if len(out) < 2 and len(points) >= 2:
        return [points[0], points[-1]]
    return out


def simplify_plan(plan: DrawingPlan, epsilon: float) -> DrawingPlan:
    if epsilon <= 0:
        return plan
    for s in plan.strokes:
        # Não simplifica fills retos de 2 pontos nem pontos de stipple
        if s.kind in (StrokeType.FILL, StrokeType.STIPPLE) and len(s.points) <= 2:
            continue
        s.points = simplify_polyline(s.points, epsilon)
    plan.strokes = [s for s in plan.strokes if len(s.points) >= 2]
    return plan


def _stroke_start(s: Stroke) -> tuple[float, float]:
    return s.points[0] if s.points else (0.0, 0.0)


def _stroke_end(s: Stroke) -> tuple[float, float]:
    return s.points[-1] if s.points else (0.0, 0.0)


def pen_down_length(strokes: list[Stroke]) -> float:
    """Comprimento total percorrido com o botão pressionado (px)."""
    dist = 0.0
    for s in strokes:
        pts = s.points
        for i in range(1, len(pts)):
            dist += math.hypot(pts[i][0] - pts[i - 1][0],
                               pts[i][1] - pts[i - 1][1])
    return dist


def pen_up_travel(strokes: list[Stroke]) -> float:
    """Distância total de reposicionamento com o botão liberado (px)."""
    dist = 0.0
    prev = None
    for s in strokes:
        if prev is not None and s.points:
            dist += math.hypot(s.points[0][0] - prev[0],
                               s.points[0][1] - prev[1])
        if s.points:
            prev = s.points[-1]
    return dist


def stroke_metrics(plan: DrawingPlan) -> dict:
    """Métricas de execução de um plano ordenado.

    lifts/presses = nº de traços (cada traço = 1 down + 1 up).
    """
    return {
        "total_strokes": plan.total_strokes,
        "lifts": plan.total_strokes,
        "presses": plan.total_strokes,
        "pen_down": pen_down_length(plan.strokes),
        "pen_up": pen_up_travel(plan.strokes),
    }


_ORDER = {
    StrokeType.FILL: 0,
    StrokeType.HATCH: 1,
    StrokeType.STIPPLE: 1,
    StrokeType.DETAIL: 2,
    StrokeType.CENTERLINE: 2,
    StrokeType.INNER_CONTOUR: 3,
    StrokeType.OUTER_CONTOUR: 4,
}


def order_plan(plan: DrawingPlan) -> DrawingPlan:
    """Ordena por etapa lógica e vizinho mais próximo (guloso).

    Avalia ambas as pontas de cada candidato: se começar pelo fim for
    mais barato, a polilinha é invertida (operação segura para tinta —
    o conjunto de pixels pintados não muda). Minimiza deslocamentos
    com o botão liberado sem conectar trajetórias independentes.
    """
    if len(plan.strokes) <= 1:
        return plan
    grouped: dict[int, list[Stroke]] = {}
    for s in plan.strokes:
        grouped.setdefault(_ORDER.get(s.kind, 2), []).append(s)
    ordered: list[Stroke] = []
    for key in sorted(grouped):
        group = grouped[key]
        # Guloso a partir do primeiro — com distâncias vetorizadas em
        # NumPy (antes: loop Python O(n²) que congelava em imagens com
        # milhares de traços). Critério idêntico: menor distância
        # quadrada, desempate pelo primeiro, `d0 <= d1` sem inverter.
        s_arr = np.array([_stroke_start(s) for s in group], dtype=np.float64)
        e_arr = np.array([_stroke_end(s) for s in group], dtype=np.float64)
        alive = np.ones(len(group), dtype=bool)
        alive[0] = False
        ordered.append(group[0])
        cur = s_arr[0]
        while alive.any():
            d0 = ((s_arr - cur) ** 2).sum(axis=1)
            d1 = ((e_arr - cur) ** 2).sum(axis=1)
            d0[~alive] = float("inf")
            d1[~alive] = float("inf")
            best = np.minimum(d0, d1)
            i = int(np.argmin(best))
            rev = bool(d1[i] < d0[i])
            nxt = group[i]
            alive[i] = False
            if rev and len(nxt.points) >= 2:
                nxt.points = nxt.points[::-1]
            ordered.append(nxt)
            cur = np.array(nxt.points[-1], dtype=np.float64)
    plan.strokes = ordered
    return plan
