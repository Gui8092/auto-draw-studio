"""Calibração da área de destino na tela."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ScreenArea:
    x: int
    y: int
    width: int
    height: int

    @property
    def is_valid(self) -> bool:
        return self.width >= 20 and self.height >= 20

    def inset(self, margin: int) -> "ScreenArea":
        m = max(0, int(margin))
        return ScreenArea(
            self.x + m, self.y + m,
            max(1, self.width - 2 * m), max(1, self.height - 2 * m),
        )

    def fit_aspect(self, image_w: int, image_h: int) -> "ScreenArea":
        """Maior retângulo dentro da área preservando a proporção da imagem."""
        if image_w <= 0 or image_h <= 0:
            return self
        scale = min(self.width / image_w, self.height / image_h)
        dw, dh = int(image_w * scale), int(image_h * scale)
        return ScreenArea(
            self.x + (self.width - dw) // 2,
            self.y + (self.height - dh) // 2,
            dw, dh,
        )


def validate_area(area: ScreenArea | None, has_strokes: bool) -> tuple[bool, str]:
    if area is None:
        return False, "Nenhuma área de desenho selecionada."
    if not area.is_valid:
        return False, "Área de desenho inválida (muito pequena)."
    if not has_strokes:
        return False, "Plano sem traços: processe uma imagem primeiro."
    return True, "Pronto para desenhar."
