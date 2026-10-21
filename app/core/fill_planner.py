"""Preenchimento por varredura (scanline) — módulo crítico.

NÃO basta detectar bordas: este módulo gera segmentos no INTERIOR
das regiões sólidas a partir da máscara binária (255=tinta).
Cada intervalo contínuo de tinta em uma linha de varredura vira um
segmento com mouse-down no início e mouse-up no fim.
Buracos (0) são respeitados automaticamente pois quebram o intervalo.
"""
from __future__ import annotations

import cv2
import numpy as np


def _row_intervals(row: np.ndarray) -> list[tuple[int, int]]:
    """Intervalos [x0, x1) de tinta em uma linha binária 0/1."""
    padded = np.concatenate([[0], row, [0]])
    diff = np.diff(padded.astype(np.int8))
    starts = np.where(diff == 1)[0]
    ends = np.where(diff == -1)[0]  # exclusivo
    return list(zip(starts.tolist(), ends.tolist()))


def _clip_interval(x0: int, x1: int, margin: int,
                    min_length: int) -> tuple[int, int] | None:
    """Recorta [x0, x1) com margem; retorna (xa, xb) inclusivos ou None."""
    xa = x0 + margin
    xb = x1 - 1 - margin
    if xb - xa + 1 >= int(min_length) and xb > xa:
        return (xa, xb)
    return None


def _safe_row_segments(ink_row: np.ndarray, eroded_row: np.ndarray,
                       margin: int, min_length: int) -> list[tuple[int, int]]:
    """Intervalos (xa, xb) inclusivos de uma linha, com fallback por linha.

    Prefere a máscara erodida (margem de segurança); se a erosão apagou a
    linha inteira, usa a máscara original com margem (detalhes finos).
    Mesma semântica de `plan_fill_strokes_safe` para margin > 0.
    """
    eroded = [(x0, x1 - 1) for x0, x1 in _row_intervals(eroded_row)
              if x1 - x0 >= int(min_length)]
    if eroded:
        return eroded
    out: list[tuple[int, int]] = []
    for x0, x1 in _row_intervals(ink_row):
        c = _clip_interval(x0, x1, margin, min_length)
        if c is not None:
            out.append(c)
    return out


def _bresenham(x0: int, y0: int, x1: int, y1: int):
    """Pixels do segmento (x0, y0) → (x1, y1), inclusive."""
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        yield x, y
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy


def _link_safe(ink: np.ndarray, labels: np.ndarray,
               x0: int, y0: int, x1: int, y1: int) -> bool:
    """Conexão pintada é segura se ambas as pontas estão no mesmo componente
    de tinta e todo o segmento passa sobre tinta da máscara original."""
    h, w = ink.shape[:2]
    if not (0 <= x0 < w and 0 <= y0 < h and 0 <= x1 < w and 0 <= y1 < h):
        return False
    l0 = int(labels[y0, x0])
    if l0 == 0 or l0 != int(labels[y1, x1]):
        return False
    for x, y in _bresenham(x0, y0, x1, y1):
        if ink[y, x] == 0:
            return False
    return True


def plan_fill_zigzag(
    mask: np.ndarray,
    spacing: int = 4,
    margin: int = 1,
    min_length: int = 2,
    max_drift: int | None = None,
    cancel_check=None,
) -> list[list[tuple[float, float]]]:
    """Preenchimento contínuo bidirecional (boustrophedon / zigue-zague).

    Linhas consecutivas alternam a direção e são unidas em uma polilinha
    quando a conexão é geometricamente segura: mesma componente conexa de
    tinta e segmento integralmente sobre tinta (nunca atravessa branco,
    furos ou regiões separadas). Sem conexão segura, a polilinha fecha e
    uma nova começa (o executor levanta o mouse entre elas).
    Retorna polilinhas de 2+ pontos; linhas isoladas viram segmentos retos.

    `cancel_check` (opcional): callback consultado a cada linha de
    varredura; se retornar True, o laço aborta com
    `app.core.pipeline.ProcessingCancelled`.
    """
    if mask.dtype != np.uint8:
        mask = mask.astype(np.uint8)
    h, w = mask.shape[:2]
    spacing = max(1, int(spacing))
    margin = max(0, int(margin))
    if max_drift is None:
        max_drift = max(2 * spacing, 6)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    ink = (mask > 127).astype(np.uint8)
    if margin > 0:
        eroded = cv2.erode(ink * 255, kernel, iterations=1)
        ink_eroded = (eroded > 127).astype(np.uint8)
    else:
        ink_eroded = ink
    _, labels = cv2.connectedComponents(ink, 8)

    rows: list[tuple[int, list[tuple[int, int]]]] = []
    for y in range(0, h, spacing):
        if cancel_check is not None and cancel_check():
            from app.core.pipeline import ProcessingCancelled

            raise ProcessingCancelled("Preenchimento cancelado.")
        if margin > 0:
            segs = _safe_row_segments(ink[y], ink_eroded[y], margin, min_length)
        else:
            segs = []
            for x0, x1 in _row_intervals(ink[y]):
                if x1 - x0 >= int(min_length):
                    segs.append((x0, x1 - 1))
        if segs:
            rows.append((y, segs))

    strokes: list[list[tuple[float, float]]] = []
    consumed = [[False] * len(segs) for _, segs in rows]
    for i, (y, segs) in enumerate(rows):
        order = range(len(segs)) if i % 2 == 0 else range(len(segs) - 1, -1, -1)
        for j in order:
            if consumed[i][j]:
                continue
            consumed[i][j] = True
            xa, xb = segs[j]
            pts: list[tuple[float, float]] = [(float(xa), float(y))]
            if xb != xa:
                pts.append((float(xb), float(y)))
            # Extremidade atual da polilinha em construção.
            cx = xb if i % 2 == 0 else xa
            cy = y
            ci = i
            while True:
                ni = ci + 1
                if ni >= len(rows):
                    break
                ny, nsegs = rows[ni]
                best = None  # (custo, k, entrada)
                # 1ª passada: candidatos PRÓXIMOS (preferidos).
                # 2ª passada: candidatos mais distantes — numa curva o
                # deslocamento entre duas linhas de varredura pode
                # passar do limite (no topo de um círculo r=40 com
                # espaçamento 4, o deslocamento é ~9px > 8px), e a
                # cadeia se partia em vários traços. A segurança
                # continua garantida por `_link_safe` (mesma componente
                # e segmento integralmente sobre tinta).
                for limit in (max_drift, max_drift * 4):
                    for k, (a, b) in enumerate(nsegs):
                        if consumed[ni][k]:
                            continue
                        for e in (a, b):
                            if abs(e - cx) > limit:
                                continue
                            if not _link_safe(ink, labels, cx, cy, e, ny):
                                continue
                            d = abs(e - cx)
                            if best is None or d < best[0]:
                                best = (d, k, e)
                    if best is not None:
                        break
                if best is None:
                    break
                _, k, e = best
                consumed[ni][k] = True
                a, b = nsegs[k]
                f = b if e == a else a
                pts.append((float(e), float(ny)))
                if f != e:
                    pts.append((float(f), float(ny)))
                ci, cy, cx = ni, ny, f
            # Remove duplicatas consecutivas (intervalos de 1px com min_length=1).
            dedup = [pts[0]]
            for p in pts[1:]:
                if p != dedup[-1]:
                    dedup.append(p)
            if len(dedup) >= 2:
                strokes.append(dedup)
    return strokes


def plan_fill_strokes(
    mask: np.ndarray,
    spacing: int = 4,
    margin: int = 1,
    min_length: int = 2,
) -> list[list[tuple[float, float]]]:
    """Varre a máscara a cada `spacing` linhas e extrai intervalos de tinta.

    - spacing: distância vertical entre linhas (configurável, >=1).
    - margin: encolhe cada intervalo nas bordas para não invadir o branco.
    - min_length: ignora fiapos menores que isso.
    Retorna lista de segmentos [(x0,y),(x1,y)] como polilinhas de 2 pontos.
    """
    if mask.dtype != np.uint8:
        mask = mask.astype(np.uint8)
    h, w = mask.shape[:2]
    spacing = max(1, int(spacing))
    margin = max(0, int(margin))
    strokes: list[list[tuple[float, float]]] = []
    ink = (mask > 127).astype(np.uint8)
    for y in range(0, h, spacing):
        for x0, x1 in _row_intervals(ink[y]):
            xa = x0 + margin
            xb = x1 - 1 - margin
            if xb - xa + 1 >= int(min_length) and xb > xa:
                strokes.append([(float(xa), float(y)), (float(xb), float(y))])
            elif x1 - x0 >= int(min_length) and margin == 0:
                strokes.append([(float(x0), float(y)), (float(x1 - 1), float(y))])
    return strokes


def plan_fill_strokes_safe(
    mask: np.ndarray,
    spacing: int = 4,
    margin: int = 1,
    min_length: int = 2,
) -> list[list[tuple[float, float]]]:
    """Variante com erosão de segurança: evita que o traço encoste no branco.

    Erode a máscara em 1px antes de varrer quando margin>0. O fallback é
    por linha: nas linhas em que a erosão elimina toda a tinta mas a
    máscara original possui tinta, usam-se os intervalos da máscara
    original (com margem). Assim regiões espessas ganham margem de
    segurança e detalhes finos (1px) são preservados. Não há duplicação:
    cada linha de varredura contribui com no máximo uma das duas fontes.
    """
    if margin <= 0:
        return plan_fill_strokes(mask, spacing, 0, min_length)
    if mask.dtype != np.uint8:
        mask = mask.astype(np.uint8)
    h, _ = mask.shape[:2]
    spacing = max(1, int(spacing))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    eroded = cv2.erode((mask > 127).astype(np.uint8) * 255, kernel, iterations=1)
    ink = (mask > 127).astype(np.uint8)
    ink_eroded = (eroded > 127).astype(np.uint8)
    strokes: list[list[tuple[float, float]]] = []
    for y in range(0, h, spacing):
        for xa, xb in _safe_row_segments(ink[y], ink_eroded[y], margin, min_length):
            strokes.append([(float(xa), float(y)), (float(xb), float(y))])
    return strokes
