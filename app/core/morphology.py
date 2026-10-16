"""Operações morfológicas sobre a máscara (255=tinta)."""
from __future__ import annotations

import cv2
import numpy as np


def apply_morphology(
    mask: np.ndarray,
    op: str = "none",
    kernel_size: int = 3,
    iterations: int = 1,
) -> np.ndarray:
    op = (op or "none").lower()
    if op == "none":
        return mask
    k = int(kernel_size)
    if k % 2 == 0:
        k += 1
    k = max(3, min(k, 9))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    it = max(1, int(iterations))
    if op == "open":
        return cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=it)
    if op == "close":
        return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=it)
    if op == "erode":
        return cv2.erode(mask, kernel, iterations=it)
    if op == "dilate":
        return cv2.dilate(mask, kernel, iterations=it)
    raise ValueError(f"Operação morfológica desconhecida: {op}")
