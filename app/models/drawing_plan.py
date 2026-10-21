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
        pts = data.get("points", []) if isinstance(data, dict) else []
        try:
            points = [(float(x), float(y)) for x, y in (pts or [])]
        except (TypeError, ValueError):
            points = []
        try:
            kind = StrokeType(data.get("kind", "fill"))
        except (ValueError, AttributeError):
            kind = StrokeType.FILL
        return Stroke(points=points, kind=kind)


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
        travel_speed_px_s: float | None = None, scale: float = 1.0,
    ) -> float:
        """Estimativa em segundos.

        Soma o percurso com o botão pressionado E os reposicionamentos com
        o botão liberado, mais um atraso por traço (levantar/pressionar).
        Cada deslocamento (pen-down ou pen-up) cujo tempo ficaria <=
        `PYAUTOGUI_MINIMUM_DURATION` custa ~0: o PyAutoGUI o move
        instantaneamente, sem tween — igual ao executor real, que dá
        `duration` proporcional também ao travel pen-up.

        `scale` converte de PX DE IMAGEM para PX DE TELA: o executor
        percorre a tela, não a imagem. Sem este fator a ETA errava pelo
        tamanho da área de destino (medido: 0.30s estimado vs ~0.91s
        real para uma imagem 512px numa área 1080px).
        """
        import math

        if move_speed_px_s <= 0:
            move_speed_px_s = 800.0
        travel = travel_speed_px_s if travel_speed_px_s and travel_speed_px_s > 0 else move_speed_px_s
        scale = float(scale) if scale and scale > 0 else 1.0
        down = 0.0
        up = 0.0
        prev_end: tuple[float, float] | None = None
        for s in self.strokes:
            pts = s.points
            for i in range(1, len(pts)):
                seg = math.hypot(pts[i][0] - pts[i - 1][0],
                                 pts[i][1] - pts[i - 1][1]) * scale
                if seg / move_speed_px_s > PYAUTOGUI_MINIMUM_DURATION:
                    down += seg
            if pts:
                if prev_end is not None:
                    jump = math.hypot(pts[0][0] - prev_end[0],
                                      pts[0][1] - prev_end[1]) * scale
                    # Travel pen-up é um único moveTo no executor: abaixo do
                    # piso, é instantâneo e custa ~0 (mesma regra do pen-down).
                    if jump / travel > PYAUTOGUI_MINIMUM_DURATION:
                        up += jump
                prev_end = pts[-1]
        return (down / move_speed_px_s + up / travel
                + len(self.strokes) * max(0.0, stroke_delay_s))

    def to_dict(self) -> dict:
        return {
            "image_width": self.image_width,
            "image_height": self.image_height,
            "spacing_px": self.spacing_px,
            "strokes": [s.to_dict() for s in self.strokes],
            # As notas da estratégia ajudam a entender o plano salvo.
            "strategy_notes": list(self.strategy_notes),
        }

    @staticmethod
    def from_dict(data: dict) -> "DrawingPlan":
        data = data if isinstance(data, dict) else {}
        strokes = data.get("strokes", []) or []
        notes = data.get("strategy_notes", []) or []
        return DrawingPlan(
            strokes=[Stroke.from_dict(s) for s in strokes
                     if isinstance(s, dict)],
            image_width=int(data.get("image_width", 0)),
            image_height=int(data.get("image_height", 0)),
            spacing_px=float(data.get("spacing_px", 4.0)),
            strategy_notes=[str(n) for n in notes if isinstance(n, str)],
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
