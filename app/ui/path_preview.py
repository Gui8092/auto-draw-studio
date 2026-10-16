"""Prévia das trajetórias: contornos/fills/hachuras diferenciados por cor+estilo."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from app.models.drawing_plan import DrawingPlan, StrokeType

STYLE = {
    StrokeType.OUTER_CONTOUR: (QColor("#3b82f6"), 2.0, Qt.SolidLine, "contorno externo"),
    StrokeType.INNER_CONTOUR: (QColor("#22d3ee"), 1.8, Qt.DashLine, "contorno interno / buraco"),
    StrokeType.DETAIL: (QColor("#a78bfa"), 1.4, Qt.DotLine, "detalhe"),
    StrokeType.FILL: (QColor("#e4e4e7"), 1.0, Qt.SolidLine, "preenchimento"),
    StrokeType.HATCH: (QColor("#f59e0b"), 1.0, Qt.DashDotLine, "sombra / hachura"),
    StrokeType.STIPPLE: (QColor("#34d399"), 2.0, Qt.SolidLine, "pontilhismo"),
    StrokeType.CENTERLINE: (QColor("#f472b6"), 1.6, Qt.SolidLine, "linha central"),
}


class PathPreview(QWidget):
    """Renderiza o DrawingPlan com zoom, pan e filtros por tipo.

    Rodinha = zoom centrado no cursor; arrastar com botão direito = pan;
    duplo-clique restaura o ajuste. Legenda textual acompanha (não só cor).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.plan: DrawingPlan | None = None
        self.show_travel = True  # deslocamentos com o botão solto (tracejado)
        self.visible = {k: True for k in STYLE}
        self._zoom = 1.0
        self._pan = [0.0, 0.0]
        self._drag: list | None = None
        # Cache por traço: (kind, minx, miny, maxx, maxy). Evita recalcular
        # bbox a cada repaint e permite pular traços fora da viewport
        # (culling) em vez de redesenhar milhares de segmentos no pan/zoom.
        self._cache: list = []
        self.setMinimumSize(200, 200)
        self.setStyleSheet("background:#101013; border-radius:8px;")

    def set_plan(self, plan: DrawingPlan | None):
        self.plan = plan
        self._zoom = 1.0
        self._pan = [0.0, 0.0]
        self._cache = []
        for s in (plan.strokes if plan is not None else []):
            if len(s.points) >= 2:
                xs = [p[0] for p in s.points]
                ys = [p[1] for p in s.points]
                self._cache.append((s.kind, min(xs), min(ys), max(xs), max(ys)))
            else:
                self._cache.append((s.kind, 0.0, 0.0, -1.0, -1.0))
        self.update()

    def set_kind_visible(self, kind: StrokeType, on: bool):
        self.visible[kind] = bool(on)
        self.update()

    def set_show_travel(self, on: bool):
        self.show_travel = bool(on)
        self.update()

    def reset_view(self):
        self._zoom = 1.0
        self._pan = [0.0, 0.0]
        self.update()

    def wheelEvent(self, e):
        if not self.plan:
            return
        factor = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        old = self._zoom
        self._zoom = max(0.2, min(20.0, self._zoom * factor))
        # Zoom ancorado no cursor: o ponto de conteúdo sob o cursor fica
        # parado. pan' = (pos-c) - ((pos-c) - pan) * (z'/z), por eixo,
        # com c = centro do widget (origem do pan).
        r = self._zoom / old
        pos = e.position()
        cx, cy = self.width() / 2, self.height() / 2
        self._pan[0] = (pos.x() - cx) - ((pos.x() - cx) - self._pan[0]) * r
        self._pan[1] = (pos.y() - cy) - ((pos.y() - cy) - self._pan[1]) * r
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self._drag = [e.position().x(), e.position().y(),
                          self._pan[0], self._pan[1]]

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self._pan[0] = self._drag[2] + (e.position().x() - self._drag[0])
            self._pan[1] = self._drag[3] + (e.position().y() - self._drag[1])
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.RightButton:
            self._drag = None

    def mouseDoubleClickEvent(self, e):
        self.reset_view()

    def legend(self) -> str:
        if not self.plan:
            return "Sem trajetórias."
        counts = {}
        for s in self.plan.strokes:
            counts[s.kind] = counts.get(s.kind, 0) + 1
        parts = []
        for kind, (_, _, _, label) in STYLE.items():
            if kind in counts:
                parts.append(f"{label}: {counts[kind]}")
        return " | ".join(parts) if parts else "Sem trajetórias."

    def _view(self):
        """(escala, ox, oy): ajuste à tela × zoom, com pan em px de tela."""
        if (not self.plan or self.plan.image_width <= 0
                or self.plan.image_height <= 0
                or self.width() <= 0 or self.height() <= 0):
            return 1.0, 0.0, 0.0
        base = min(self.width() / self.plan.image_width,
                   self.height() / self.plan.image_height)
        s = base * self._zoom
        cx = self.width() / 2 + self._pan[0]
        cy = self.height() / 2 + self._pan[1]
        return s, cx - (self.plan.image_width * s) / 2, cy - (self.plan.image_height * s) / 2

    def _visible_content_rect(self, s, ox, oy):
        """Retângulo de conteúdo (coords da imagem) visível no widget."""
        if s <= 0:
            return None
        x0 = (0 - ox) / s
        y0 = (0 - oy) / s
        x1 = (self.width() - ox) / s
        y1 = (self.height() - oy) / s
        return (x0, y0, x1, y1)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#101013"))
        if (not self.plan or not self.plan.strokes
                or self.plan.image_width <= 0 or self.plan.image_height <= 0):
            p.setPen(QColor("#71717a"))
            p.drawText(self.rect(), Qt.AlignCenter, "Sem trajetórias")
            return
        s, ox, oy = self._view()
        if s <= 0:
            return
        view = self._visible_content_rect(s, ox, oy)
        for idx, stroke in enumerate(self.plan.strokes):
            if len(stroke.points) < 2 or not self.visible.get(stroke.kind, True):
                continue
            # Culling: pula traços com bbox fora da viewport.
            if view is not None and idx < len(self._cache):
                _, bx0, by0, bx1, by1 = self._cache[idx]
                vx0, vy0, vx1, vy1 = view
                if bx1 < vx0 or bx0 > vx1 or by1 < vy0 or by0 > vy1:
                    continue
            color, w, style, _ = STYLE.get(stroke.kind, (QColor("#e4e4e7"), 1.0, Qt.SolidLine, ""))
            pen = QPen(color, w, style, Qt.RoundCap, Qt.RoundJoin)
            p.setPen(pen)
            pts = stroke.points
            for i in range(1, len(pts)):
                p.drawLine(int(ox + pts[i - 1][0] * s), int(oy + pts[i - 1][1] * s),
                           int(ox + pts[i][0] * s), int(oy + pts[i][1] * s))
        if self.show_travel:
            # Reposicionamentos com o botão SOLTO: o que o executor faz entre
            # traços (mesma ordem do plano). Tracejado cinza ≠ tinta.
            p.setPen(QPen(QColor("#71717a"), 1.0, Qt.DashLine, Qt.RoundCap, Qt.RoundJoin))
            prev = None
            for stroke in self.plan.strokes:
                if len(stroke.points) < 2 or not self.visible.get(stroke.kind, True):
                    continue
                if prev is not None:
                    p.drawLine(int(ox + prev[0] * s), int(oy + prev[1] * s),
                               int(ox + stroke.points[0][0] * s),
                               int(oy + stroke.points[0][1] * s))
                prev = stroke.points[-1]
