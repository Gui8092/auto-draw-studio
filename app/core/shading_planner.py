"""Sombreamento: hachuras determinísticas + pontilhismo simples.

EXPERIMENTAL: não integrado ao pipeline principal (`pipeline.build_plan`
não o utiliza). Corrigido e testado de forma isolada; a integração fica
para uma fase futura.
"""
from __future__ import annotations

import numpy as np


def plan_hatching(
    gray: np.ndarray,
    mask: np.ndarray | None = None,
    angle_deg: float = 45.0,
    spacing: int = 6,
    dark_thr: int = 200,
    intensity: float = 0.5,
) -> list[list[tuple[float, float]]]:
    """Gera hachuras paralelas onde há tom médio/escuro.

    gray: escala de cinza original (0=preto). Só gera traço onde
    gray < dark_thr e (mask tinta se fornecida). Densidade varia com
    intensity: 0 → só tons bem escuros; 1 → inclui tons mais claros.
    """
    h, w = gray.shape[:2]
    thr = int(255 - (255 - int(dark_thr)) * (0.3 + 0.7 * float(intensity)))
    thr = max(40, min(240, thr))
    target = (gray < thr)
    if mask is not None:
        target = target & (mask > 127)
    theta = np.deg2rad(float(angle_deg))
    dx, dy = np.cos(theta), np.sin(theta)
    nx, ny = -dy, dx
    spacing = max(2, int(spacing))
    diag = int(np.hypot(w, h))
    cx, cy = w / 2.0, h / 2.0
    strokes: list[list[tuple[float, float]]] = []
    n_lines = diag // spacing + 1
    for i in range(-n_lines // 2, n_lines // 2 + 1):
        ox = cx + nx * i * spacing
        oy = cy + ny * i * spacing
        # Amostra ao longo da linha, rastreando o último pixel válido.
        seg_start: tuple[float, float] | None = None
        last_on: tuple[int, int] | None = None
        prev_on = False
        for t in range(-diag, diag, 1):
            x = int(round(ox + dx * t))
            y = int(round(oy + dy * t))
            on = 0 <= x < w and 0 <= y < h and bool(target[y, x])
            if on and not prev_on:
                seg_start = (float(x), float(y))
            if on:
                last_on = (x, y)
            if not on and prev_on and seg_start is not None and last_on is not None:
                strokes.append([seg_start, (float(last_on[0]), float(last_on[1]))])
                seg_start = None
                last_on = None
            prev_on = on
        if prev_on and seg_start is not None and last_on is not None:
            strokes.append([seg_start, (float(last_on[0]), float(last_on[1]))])
    return [s for s in strokes if abs(s[1][0] - s[0][0]) + abs(s[1][1] - s[0][1]) >= 2]


def plan_stipple(
    gray: np.ndarray,
    mask: np.ndarray | None = None,
    step: int = 5,
    dark_thr: int = 150,
) -> list[list[tuple[float, float]]]:
    """Pontilhismo: um ponto (segmento degenerado) por célula escura."""
    h, w = gray.shape[:2]
    step = max(2, int(step))
    dots: list[list[tuple[float, float]]] = []
    for y in range(0, h, step):
        for x in range(0, w, step):
            if gray[y, x] < int(dark_thr):
                if mask is not None and mask[y, x] < 128:
                    continue
                dots.append([(float(x), float(y)), (float(x), float(y))])
    return dots
