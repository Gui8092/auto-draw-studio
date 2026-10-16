"""Centerlines: esqueletização e traçado do meio das linhas finas.

Usado para desenhos compostos por traços finos (esboços, line art,
símbolos): o mouse segue o MEIO do traço em vez de preencher ambos os
lados. NUNCA aplicado a regiões sólidas (destruiria o preenchimento) —
a escolha é feita por `strategy.py` a partir da espessura local.

Sem dependências novas: thinning de Zhang-Suen implementado em NumPy
(`cv2.ximgproc.thinning` exigiria opencv-contrib).
"""
from __future__ import annotations

import numpy as np


def skeletonize(ink: np.ndarray, max_iter: int = 100) -> np.ndarray:
    """Esqueleto morfológico (Zhang-Suen) de máscara binária 0/1.

    Preserva topologia; retorna uint8 0/1 com linhas de 1px.
    """
    img = (ink > 0).astype(np.uint8)
    if img.sum() == 0:
        return img
    for _ in range(max_iter):
        # Sequencial (não paralelo): a sub-iteração 2 opera sobre o
        # resultado da 1, senão as duas fileiras centrais de regiões com
        # largura par se apagam mutuamente no mesmo passo.
        before = int(img.sum())
        img[_zs_step(img, 0)] = 0
        img[_zs_step(img, 1)] = 0
        if int(img.sum()) == before:
            break
    return img


def _zs_step(img: np.ndarray, step: int) -> np.ndarray:
    """Máscara de pixels a remover em uma sub-iteração de Zhang-Suen."""
    p = np.pad(img, 1, mode="constant")
    # Vizinhos p2..p9 (sentido horário a partir do norte)
    p2 = p[:-2, 1:-1]
    p3 = p[:-2, 2:]
    p4 = p[1:-1, 2:]
    p5 = p[2:, 2:]
    p6 = p[2:, 1:-1]
    p7 = p[2:, :-2]
    p8 = p[1:-1, :-2]
    p9 = p[:-2, :-2]
    nbrs = [p2, p3, p4, p5, p6, p7, p8, p9]
    # Transições 0→1 na sequência ordenada
    seq = nbrs + [p2]
    trans = sum(((seq[i] == 0) & (seq[i + 1] == 1)).astype(np.uint8)
                for i in range(8))
    ncount = sum(nbrs)
    if step == 0:
        cond = (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
    else:
        cond = (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)
    return (img == 1) & (trans == 1) & (ncount >= 2) & (ncount <= 6) & cond


def _neighbors8(y: int, x: int, h: int, w: int):
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w:
                yield ny, nx


def trace_skeleton(skel: np.ndarray, prune_len: int = 3) -> list[list[tuple[int, int]]]:
    """Converte esqueleto 0/1 em polilinhas ordenadas (caminhada por vizinhos).

    Ramificações espúrias menores que `prune_len` são podadas somente se
    terminarem em ponta livre (nunca remove pontes entre junções).
    Cada pixel do esqueleto pertence a no máximo uma polilinha.
    """
    sk = (skel > 0).astype(np.uint8)
    h, w = sk.shape[:2]
    if sk.sum() == 0:
        return []
    degree = np.zeros_like(sk, dtype=np.int32)
    ys, xs = np.nonzero(sk)
    for y, x in zip(ys.tolist(), xs.tolist()):
        degree[y, x] = sum(sk[ny, nx] for ny, nx in _neighbors8(y, x, h, w))
    used = np.zeros_like(sk, dtype=bool)
    chains: list[list[tuple[int, int]]] = []

    def walk(sy: int, sx: int) -> list[tuple[int, int]]:
        path = [(sx, sy)]
        used[sy, sx] = True
        cy, cx = sy, sx
        prev: tuple[int, int] | None = None
        while True:
            cands = [(ny, nx) for ny, nx in _neighbors8(cy, cx, h, w)
                     if sk[ny, nx] and not used[ny, nx]]
            if not cands:
                break
            # Prefere seguir reto (menos zigue-zague no traço)
            nxt = cands[0]
            if prev is not None:
                for ny, nx in cands:
                    if (ny - cy, nx - cx) == prev:
                        nxt = (ny, nx)
                        break
            prev = (nxt[0] - cy, nxt[1] - cx)
            cy, cx = nxt
            path.append((cx, cy))
            used[cy, cx] = True
            if degree[cy, cx] > 2:
                break  # para nas junções; outro ramo continua depois
        return path

    # Começa pelas pontas (grau 1), depois junções, depois resto.
    order = sorted(zip(ys.tolist(), xs.tolist()),
                   key=lambda p: (0 if degree[p] == 1 else 1, p[0], p[1]))
    for y, x in order:
        if used[y, x]:
            continue
        if degree[y, x] == 0:
            used[y, x] = True
            continue  # pixel isolado: ruído, descarta
        chains.append(walk(y, x))
    # Poda: remove cadeias curtas que terminam em ponta livre.
    kept = []
    for ch in chains:
        if len(ch) <= max(1, int(prune_len)):
            ex, ey = ch[-1]
            if degree[ey, ex] == 1:
                continue  # esporão de ruído
        kept.append(ch)
    return [c for c in kept if len(c) >= 2]


def plan_centerlines(mask: np.ndarray, min_length: int = 4,
                     prune_len: int = 3) -> list[list[tuple[float, float]]]:
    """Traços centrais da máscara (para regiões finas já recortadas)."""
    m = np.asarray(mask)
    # Aceita 0/255 ou 0/1 (pipeline interno usa 0/1 em alguns caminhos).
    ink = ((m > 0).astype(np.uint8) if m.max() <= 1
           else (m > 127).astype(np.uint8))
    if ink.sum() == 0:
        return []
    skel = skeletonize(ink)
    out = []
    for chain in trace_skeleton(skel, prune_len=prune_len):
        if len(chain) >= max(2, int(min_length)):
            out.append([(float(x), float(y)) for x, y in chain])
    return out
