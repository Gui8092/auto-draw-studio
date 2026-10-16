"""Binarização: gera máscara onde 255=tinta, 0=papel."""
from __future__ import annotations

import cv2
import numpy as np


def binarize(
    gray: np.ndarray,
    method: str = "global",
    threshold: int = 128,
    invert: bool = False,
    block_size: int = 21,
    c: int = 5,
) -> np.ndarray:
    """Retorna máscara uint8 (255=tinta).

    - global: pixels < threshold viram tinta.
    - otsu: limiar automático.
    - adaptive: limiar adaptativo gaussiano.
    - invert: inverte o resultado final.
    """
    if gray.dtype != np.uint8:
        gray = np.clip(gray, 0, 255).astype(np.uint8)
    m = str(method).lower()
    if m == "otsu":
        _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    elif m == "adaptive":
        bs = int(block_size)
        if bs % 2 == 0:
            bs += 1
        bs = max(3, bs)
        mask = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, bs, int(c),
        )
    else:  # global
        _, mask = cv2.threshold(gray, int(threshold), 255, cv2.THRESH_BINARY_INV)
    if invert:
        mask = cv2.bitwise_not(mask)
    # Garante binário estrito
    _, mask = cv2.threshold(mask, 127, 255, cv2.THRESH_BINARY)
    return mask
