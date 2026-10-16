"""Mapeamento imagem → área de desenho → tela."""
from __future__ import annotations

from app.automation.screen_calibration import ScreenArea


class CoordinateMapper:
    def __init__(self, image_w: int, image_h: int, area: ScreenArea):
        if image_w <= 0 or image_h <= 0:
            raise ValueError("Dimensões da imagem inválidas.")
        self.image_w = image_w
        self.image_h = image_h
        self.area = area.fit_aspect(image_w, image_h)
        self.sx = self.area.width / image_w
        self.sy = self.area.height / image_h

    def to_screen(self, x: float, y: float) -> tuple[int, int]:
        return (int(round(self.area.x + x * self.sx)),
                int(round(self.area.y + y * self.sy)))

    def map_stroke(self, points: list[tuple[float, float]]) -> list[tuple[int, int]]:
        return [self.to_screen(x, y) for x, y in points]
