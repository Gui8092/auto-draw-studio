"""Sombreamento: hachuras determinísticas + pontilhismo simples.

Integrado ao pipeline no modo "sombreado" (regions sólidas de tom
médio viram hachuras em vez de preenchimento chapado).

`plan_hatching` é a versão legada (amostragem ponto a ponto, lenta);
`plan_hatch` é a versão vetorizada usada pelo pipeline.
"""
from __future__ import annotations

import numpy as np


def hatch_spacing_for(tone: float, base_spacing: int,
                      intensity: float = 0.5) -> int:
    """Espaçamento das hachuras para um tom (0=preto, 255=branco).

    `base_spacing` é o espaçamento BASE (o que o controle "Hach. px"
    mostra). Tons mais claros → hachuras mais espaçadas;
    `intensity` ajusta a densidade (1 = denso, 0 = ralo).
    """
    base = max(2, int(base_spacing))
    tone = float(np.clip(tone, 0.0, 255.0))
    # Fator de tom: 0.6 (preto) … 2.0 (branco).
    tone_factor = 0.6 + tone / 128.0
    # Fator de densidade: 0.5 (ralo) … 1.5 (denso).
    density = 0.5 + float(np.clip(intensity, 0.0, 1.0))
    return int(max(2, min(base * 4, round(base * tone_factor / density))))


def plan_hatch(
    gray: np.ndarray,
    mask: np.ndarray | None = None,
    angle_deg: float = 45.0,
    spacing: int = 6,
    dark_thr: int = 200,
    bbox: tuple[int, int, int, int] | None = None,
) -> list[list[tuple[float, float]]]:
    """Hachuras paralelas onde o tom é escuro (vetorizado por linha).

    Para cada linha da grade de hachura, amostra o tom ao longo dela e
    emite um segmento por intervalo escuro contínuo. `mask` (255=tinta)
    recorta as hachuras a uma região.

    `bbox` (x0, y0, x1, y1) restringe o traçado a essa caixa: sem ele,
    cada chamada varre a imagem INTEIRA (e o sombreado chama uma vez
    por componente — O(n × imagem)).
    """
    gray = np.asarray(gray)
    if gray.ndim != 2:
        return []
    h, w = gray.shape[:2]
    thr = int(dark_thr)
    spacing = max(2, int(spacing))
    theta = np.deg2rad(float(angle_deg))
    dx, dy = float(np.cos(theta)), float(np.sin(theta))
    nx, ny = -dy, dx
    diag = int(np.hypot(w, h)) + 1
    cx, cy = w / 2.0, h / 2.0
    strokes: list[list[tuple[float, float]]] = []

    if bbox is not None:
        bx0, by0, bx1, by1 = bbox
        bx0 = max(0, int(bx0)); by0 = max(0, int(by0))
        bx1 = min(w, int(bx1)); by1 = min(h, int(by1))
        if bx1 <= bx0 or by1 <= by0:
            return []
        # Só as linhas da grade que atravessam a caixa, e só o trecho
        # da linha dentro dela.
        pcx, pcy = (bx0 + bx1) / 2.0 - cx, (by0 + by1) / 2.0 - cy
        proj = pcx * nx + pcy * ny
        ext = ((bx1 - bx0) * abs(nx) + (by1 - by0) * abs(ny)) / 2.0
        i_min = int(np.floor((proj - ext) / spacing)) - 1
        i_max = int(np.ceil((proj + ext) / spacing)) + 1
        dproj = pcx * dx + pcy * dy
        dext = ((bx1 - bx0) * abs(dx) + (by1 - by0) * abs(dy)) / 2.0
        t = np.arange(-dext - 1, dext + 1, 1.0)
    else:
        i_min = -(diag // spacing) - 1
        i_max = (diag // spacing) + 1
        t = np.arange(-diag, diag, 1.0)

    mask_arr = None if mask is None else np.asarray(mask)
    for i in range(i_min, i_max + 1):
        ox = cx + nx * i * spacing
        oy = cy + ny * i * spacing
        xs = np.rint(ox + dx * t).astype(np.int64)
        ys = np.rint(oy + dy * t).astype(np.int64)
        ok = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
        if not ok.any():
            continue
        xi, yi = xs[ok], ys[ok]
        target = gray[yi, xi] < thr
        if mask_arr is not None:
            target &= (mask_arr[yi, xi] > 127)
        if not target.any():
            continue
        idx = np.flatnonzero(target)
        if idx.size < 2:
            continue
        breaks = np.flatnonzero(np.diff(idx) > 1)
        starts = np.r_[idx[0], idx[breaks + 1]]
        ends = np.r_[idx[breaks], idx[-1]]
        for s, e in zip(starts, ends):
            if e - s < 1:
                continue
            strokes.append([(float(xi[s]), float(yi[s])),
                            (float(xi[e]), float(yi[e]))])
    return strokes


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

    NOTA: `intensity` era invertido — 0 incluía tons CLAROS e 1 só os
    muito escuros, o contrário do documentado.
    """
    thr = int(255 - (255 - int(dark_thr)) * (1.0 - 0.7 * float(intensity)))
    thr = max(40, min(240, thr))
    return plan_hatch(gray, mask, angle_deg=angle_deg, spacing=spacing,
                      dark_thr=thr)


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
