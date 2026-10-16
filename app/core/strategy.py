"""Seleção de estratégia de desenho por região + perfis de utilização.

Cada componente conexo de tinta é classificado por área, espessura local
(máximo da transformada de distância) e presença de furos, e recebe uma
estratégia explícita:

- "centerline": traços finos (espessura <= limiar) — o mouse segue o MEIO
  da linha em vez de preencher ambos os lados.
- "fill": regiões sólidas amplas — zigue-zague contínuo.
- "contour": componentes pequenos ou bordas relevantes — só o contorno.

Critérios determinísticos e explicáveis (`explain()`); o usuário pode
forçar uma estratégia global pelo modo avançado (`strategy`).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class ComponentInfo:
    label: int
    area: float
    bbox: tuple[int, int, int, int]  # x, y, w, h
    max_thickness: float  # largura local máxima (px, via distanceTransform)
    has_hole: bool
    strategy: str = "fill"
    reason: str = ""


@dataclass
class StrategyDecision:
    components: list[ComponentInfo] = field(default_factory=list)
    thin_labels: set[int] = field(default_factory=set)

    def explain(self) -> list[str]:
        lines = []
        for c in self.components:
            lines.append(f"região #{c.label}: área={c.area:.0f}px "
                         f"espessura≈{c.max_thickness:.1f}px → {c.strategy} ({c.reason})")
        return lines


def classify_components(mask: np.ndarray, thin_px: float = 4.0,
                        min_area: float = 20.0) -> StrategyDecision:
    """Classifica cada componente conexo de tinta (255=tinta)."""
    ink = (np.asarray(mask) > 127).astype(np.uint8)
    h, w = ink.shape[:2]
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink * 255, 8)
    # Furos: componentes de fundo cercados de tinta
    inv = (1 - ink).astype(np.uint8) * 255
    nh, hlabels, _, _ = cv2.connectedComponentsWithStats(inv, 8)
    border = set(np.unique(hlabels[0, :])) | set(np.unique(hlabels[-1, :])) | set(
        np.unique(hlabels[:, 0])) | set(np.unique(hlabels[:, -1]))
    hole_map: dict[int, bool] = {}
    for i in range(1, nh):
        if i in border:
            continue
        ys, xs = np.nonzero(hlabels == i)
        if len(xs) == 0:
            continue
        # A qual componente de tinta este furo pertence? Olha a vizinhança.
        yy = np.clip(ys, 0, h - 1)
        xx = np.clip(xs, 0, w - 1)
        adj = labels[np.clip(yy + 1, 0, h - 1), xx]
        adj = adj[adj > 0]
        if len(adj):
            hole_map[int(np.bincount(adj).argmax())] = True
    dec = StrategyDecision()
    for i in range(1, n):
        area = float(stats[i, cv2.CC_STAT_AREA])
        x, y, bw, bh = (int(stats[i, cv2.CC_STAT_LEFT]),
                        int(stats[i, cv2.CC_STAT_TOP]),
                        int(stats[i, cv2.CC_STAT_WIDTH]),
                        int(stats[i, cv2.CC_STAT_HEIGHT]))
        comp = (labels == i).astype(np.uint8)
        dist = cv2.distanceTransform(comp, cv2.DIST_L2, 3)
        thick = float(dist.max()) * 2.0
        has_hole = hole_map.get(i, False)
        if thick <= float(thin_px):
            strat, reason = "centerline", f"traço fino (≤{thin_px:.0f}px)"
        elif area < float(min_area):
            strat, reason = "contour", f"detalhe pequeno ({area:.0f}px)"
        else:
            strat, reason = "fill", "região sólida ampla"
        info = ComponentInfo(label=i, area=area, bbox=(x, y, bw, bh),
                             max_thickness=thick, has_hole=has_hole,
                             strategy=strat, reason=reason)
        dec.components.append(info)
        if strat == "centerline":
            dec.thin_labels.add(i)
    return dec


STRATEGIES = ("auto", "fill", "contour", "centerline")

PROFILES: dict[str, dict] = {
    # Nome: ajustes sobre os parâmetros existentes (sem controles novos).
    "equilibrado": {},
    "rapido": {"fill_spacing": 6, "simplify_epsilon": 2.0,
               "min_detail_area": 60.0, "denoise": 1, "morph_op": "open"},
    "fidelidade": {"fill_spacing": 3, "simplify_epsilon": 0.5,
                   "min_detail_area": 8.0, "denoise": 0, "morph_op": "none"},
    "linha_fina": {"fill_spacing": 3, "simplify_epsilon": 0.5,
                   "min_detail_area": 4.0, "denoise": 0, "morph_op": "none",
                   "strategy": "centerline"},
    "logo": {"fill_spacing": 4, "simplify_epsilon": 1.0,
             "min_detail_area": 20.0, "denoise": 1, "morph_op": "close",
             "strategy": "auto"},
}

PROFILE_NAMES = tuple(PROFILES)


def apply_profile(settings, name: str):
    """Aplica um perfil sobre ProcessingSettings (retorna novo objeto)."""
    from dataclasses import replace
    updates = PROFILES.get(name, {})
    valid = {k: v for k, v in updates.items() if hasattr(settings, k)}
    return replace(settings, **valid)
