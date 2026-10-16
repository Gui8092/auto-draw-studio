"""Pré-processamento: brilho, contraste, gama e redução de ruído."""
from __future__ import annotations

import cv2
import numpy as np


def apply_adjustments(
    gray: np.ndarray,
    brightness: int = 0,
    contrast: float = 1.0,
    gamma: float = 1.0,
) -> np.ndarray:
    """Aplica brilho (-100..100), contraste (0.5..2.0) e gama (0.2..3.0)."""
    img = gray.astype(np.float32)
    img = img * float(contrast) + float(brightness)
    img = np.clip(img, 0, 255)
    if abs(float(gamma) - 1.0) > 1e-6 and float(gamma) > 0:
        lut = np.array([((i / 255.0) ** (1.0 / float(gamma))) * 255.0 for i in range(256)],
                       dtype=np.float32)
        img = lut[np.clip(img, 0, 255).astype(np.uint8)]
    return np.clip(img, 0, 255).astype(np.uint8)


def denoise(gray: np.ndarray, strength: int = 0) -> np.ndarray:
    """Redução de ruído. strength 0..5 → blur crescente."""
    s = int(strength)
    if s <= 0:
        return gray
    k = 3 + (s - 1) * 2  # 3,5,7,9,11
    if k % 2 == 0:
        k += 1
    # Mediano remove sal-e-pimenta; gaussiano suaviza em seguida se forte
    out = cv2.medianBlur(gray, min(k, 7))
    if s >= 4:
        out = cv2.GaussianBlur(out, (3, 3), 0)
    return out


def to_grayscale(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
