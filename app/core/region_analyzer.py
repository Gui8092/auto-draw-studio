"""Análise de regiões conexas (sólidos, buracos, ruídos)."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class RegionStats:
    num_components: int
    areas: list[float]
    total_ink_px: int
    ink_ratio: float
    num_holes: int
    noise_components: int
    is_empty: bool
    is_complex: bool


def analyze_regions(mask: np.ndarray, min_area: float = 20.0) -> RegionStats:
    """Usa connectedComponents para tinta e para o fundo (buracos)."""
    ink = (mask > 127).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats((ink * 255).astype(np.uint8), 8)
    areas: list[float] = []
    noise = 0
    for i in range(1, n):
        a = float(stats[i, cv2.CC_STAT_AREA])
        areas.append(a)
        if a < float(min_area):
            noise += 1
    total = int(ink.sum())
    ratio = float(total / ink.size) if ink.size else 0.0
    # Buracos = componentes de fundo não conectados à borda
    inv = (1 - ink).astype(np.uint8) * 255
    nh, labels, bstats, _ = cv2.connectedComponentsWithStats(inv, 8)
    border_label = set()
    h, w = labels.shape
    border_label.update(np.unique(labels[0, :]).tolist())
    border_label.update(np.unique(labels[-1, :]).tolist())
    border_label.update(np.unique(labels[:, 0]).tolist())
    border_label.update(np.unique(labels[:, -1]).tolist())
    holes = sum(1 for i in range(1, nh) if i not in border_label)
    return RegionStats(
        num_components=max(0, n - 1),
        areas=areas,
        total_ink_px=total,
        ink_ratio=ratio,
        num_holes=holes,
        noise_components=noise,
        is_empty=(n - 1) == 0,
        is_complex=ratio > 0.55 and (n - 1) > 40,
    )
