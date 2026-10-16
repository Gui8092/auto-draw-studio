"""Extração de contornos externos/internos e detalhes."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class ContourInfo:
    points: np.ndarray  # Nx1x2
    area: float
    is_hole: bool
    level: int


def extract_contours(
    mask: np.ndarray,
    min_area: float = 20.0,
    epsilon_factor: float = 0.002,
) -> tuple[list[ContourInfo], list[ContourInfo]]:
    """Retorna (externos/internos_sólidos, detalhes_pequenos).

    Usa RETR_CCOMP (2 níveis: externo + buracos) para respeitar vazios.
    Contornos com área < min_area vão para 'detalhes' (podem ser filtrados).
    """
    if mask.dtype != np.uint8:
        mask = mask.astype(np.uint8)
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    mains: list[ContourInfo] = []
    details: list[ContourInfo] = []
    if hierarchy is None or len(contours) == 0:
        return mains, details
    hier = hierarchy[0]
    for i, cnt in enumerate(contours):
        area = float(cv2.contourArea(cnt))
        parent = int(hier[i][3])
        is_hole = parent != -1
        # Simplificação proporcional ao perímetro
        peri = float(cv2.arcLength(cnt, True))
        eps = max(1.0, float(epsilon_factor) * peri)
        approx = cv2.approxPolyDP(cnt, eps, True)
        info = ContourInfo(points=approx, area=area, is_hole=is_hole, level=1 if is_hole else 0)
        if area < float(min_area):
            details.append(info)
        else:
            mains.append(info)
    # Externos primeiro (área decrescente), buracos junto por proximidade
    mains.sort(key=lambda c: (c.is_hole, -c.area))
    return mains, details


def contours_to_polylines(
    contours: list[ContourInfo], close: bool = True
) -> list[list[tuple[float, float]]]:
    polylines = []
    for c in contours:
        pts = c.points.reshape(-1, 2)
        line = [(float(x), float(y)) for x, y in pts]
        if close and len(line) >= 3:
            line = line + [line[0]]
        if len(line) >= 2:
            polylines.append(line)
    return polylines
