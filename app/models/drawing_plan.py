"""Modelos de dados: plano de desenho."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# Piso do PyAutoGUI: `moveTo` com duration <= MINIMUM_DURATION (0,1 s)
# move instantaneamente, sem tween (verificado no fonte instalado).
PYAUTOGUI_MINIMUM_DURATION = 0.1


class StrokeType(str, Enum):
    OUTER_CONTOUR = "outer_contour"
    INNER_CONTOUR = "inner_contour"
    DETAIL = "detail"
    FILL = "fill"
    HATCH = "hatch"
    STIPPLE = "stipple"
    CENTERLINE = "centerline"


@dataclass
class Stroke:
    """Um traço contínuo (mouse pressionado do início ao fim).

    points: lista de (x, y) em coordenadas da imagem (pixels).
    kind: categoria do traço.
    """

    points: list[tuple[float, float]]
    kind: StrokeType = StrokeType.FILL

    def __len__(self) -> int:
        return len(self.points)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "points": [[float(x), float(y)] for x, y in self.points],
        }

    @staticmethod
    def from_dict(data: dict) -> "Stroke":
        return Stroke(
            points=[(float(x), float(y)) for x, y in data["points"]],
            kind=StrokeType(data.get("kind", "fill")),
        )


@dataclass
class DrawingPlan:
    """Conjunto ordenado de traços pronto para execução."""

    strokes: list[Stroke] = field(default_factory=list)
    image_width: int = 0
    image_height: int = 0
    spacing_px: float = 4.0
    # Explicações da estratégia por região (efêmero; não serializado).
    strategy_notes: list[str] = field(default_factory=list)

    @property
    def total_strokes(self) -> int:
        return len(self.strokes)

    @property
    def total_points(self) -> int:
        return sum(len(s) for s in self.strokes)

    def strokes_by_kind(self, kind: StrokeType) -> list[Stroke]:
        return [s for s in self.strokes if s.kind == kind]

    def estimate_duration(
        self, move_speed_px_s: float = 800.0, stroke_delay_s: float = 0.05,
        travel_speed_px_s: float | None = None,
    ) -> float:
        """Estimativa em segundos.

        Soma o percurso com o botão pressionado E os reposicionamentos com
        o botão liberado, mais um atraso por traço (levantar/pressionar).
        Segmentos cujo tempo ficaria <= `PYAUTOGUI_MINIMUM_DURATION`
        custam ~0: o PyAutoGUI os move instantaneamente, sem tween.
        """
        import math

        if move_speed_px_s <= 0:
            move_speed_px_s = 800.0
        travel = travel_speed_px_s if travel_speed_px_s and travel_speed_px_s > 0 else move_speed_px_s
        down = 0.0
        up = 0.0
        prev_end: tuple[float, float] | None = None
        for s in self.strokes:
            pts = s.points
            for i in range(1, len(pts)):
                seg = math.hypot(pts[i][0] - pts[i - 1][0],
                                 pts[i][1] - pts[i - 1][1])
                if seg / move_speed_px_s > PYAUTOGUI_MINIMUM_DURATION:
                    down += seg
            if pts:
                if prev_end is not None:
                    up += math.hypot(pts[0][0] - prev_end[0], pts[0][1] - prev_end[1])
                prev_end = pts[-1]
        return (down / move_speed_px_s + up / travel
                + len(self.strokes) * max(0.0, stroke_delay_s))

    def to_dict(self) -> dict:
        return {
            "image_width": self.image_width,
            "image_height": self.image_height,
            "spacing_px": self.spacing_px,
            "strokes": [s.to_dict() for s in self.strokes],
        }

    @staticmethod
    def from_dict(data: dict) -> "DrawingPlan":
        return DrawingPlan(
            strokes=[Stroke.from_dict(s) for s in data.get("strokes", [])],
            image_width=int(data.get("image_width", 0)),
            image_height=int(data.get("image_height", 0)),
            spacing_px=float(data.get("spacing_px", 4.0)),
        )

    def to_svg(self, stroke_width: float = 1.0) -> str:
        colors = {
            StrokeType.OUTER_CONTOUR: "#1d4ed8",
            StrokeType.INNER_CONTOUR: "#0ea5e9",
            StrokeType.DETAIL: "#8b5cf6",
            StrokeType.FILL: "#111111",
            StrokeType.HATCH: "#b45309",
            StrokeType.STIPPLE: "#059669",
            StrokeType.CENTERLINE: "#059669",
        }
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{self.image_width}" height="{self.image_height}" '
            f'viewBox="0 0 {self.image_width} {self.image_height}">',
            f'<rect width="100%" height="100%" fill="white"/>',
        ]
        for s in self.strokes:
            if len(s.points) < 2:
                continue
            d = f'M {s.points[0][0]:.1f} {s.points[0][1]:.1f} ' + " ".join(
                f"L {x:.1f} {y:.1f}" for x, y in s.points[1:]
            )
            parts.append(
                f'<path d="{d}" fill="none" stroke="{colors.get(s.kind, "#111")}" '
                f'stroke-width="{stroke_width}" stroke-linecap="round" '
                f'stroke-linejoin="round"/>'
            )
        parts.append("</svg>")
        return "\n".join(parts)
