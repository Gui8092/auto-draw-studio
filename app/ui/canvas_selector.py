"""Seletor retangular da área de desenho (overlay fullscreen).

Convenção de coordenadas (explícita):
- Eventos de mouse e pintura usam coordenadas LOCAIS do widget
  (`event.position()`, origem no canto superior-esquerdo do overlay).
- `ScreenArea` retornado usa coordenadas GLOBAIS do desktop virtual.
- Conversão: ``global = local + overlay_geometry.topLeft()``.
  Nunca se presume que a origem do desktop virtual seja (0, 0);
  monitores à esquerda/acima geram origens negativas e são respeitados.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from app.automation.screen_calibration import ScreenArea


def normalize_points(p0: QPoint, p1: QPoint) -> QRect:
    """Retângulo local normalizado a partir de dois pontos locais.

    Independente da direção do arrasto (QRect(p0, p1) puro varia ±1px
    conforme a ordem; aqui as coordenadas são normalizadas primeiro).
    Modelo inclusivo: ambos os cantos pertencem à seleção.
    """
    x = min(p0.x(), p1.x())
    y = min(p0.y(), p1.y())
    w = abs(p1.x() - p0.x()) + 1
    h = abs(p1.y() - p0.y()) + 1
    return QRect(x, y, w, h)


def local_rect_to_screen_area(rect: QRect, origin: QPoint) -> ScreenArea:
    """Converte retângulo local em área global somando a origem do overlay."""
    r = rect.normalized()
    return ScreenArea(
        r.x() + origin.x(), r.y() + origin.y(), r.width(), r.height())


def screen_area_to_local_rect(area: ScreenArea, origin: QPoint) -> QRect:
    """Inverso (usado em testes de consistência visual ↔ coordenadas)."""
    return QRect(area.x - origin.x(), area.y - origin.y(),
                 area.width, area.height)


class CanvasSelector(QWidget):
    selection_done = Signal(object)  # ScreenArea ou None (cancelado)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self._p0: QPoint | None = None
        self._p1: QPoint | None = None
        self.selected: ScreenArea | None = None
        # True após o resultado final ter sido emitido exatamente uma vez.
        # Protege contra emissão duplicada e contra recursão, pois
        # finish/cancel chamam close(), que dispara closeEvent().
        self._finished = False

    def start(self):
        # União de TODOS os monitores (antes: só a geometria da tela
        # primária — em multi-monitor o overlay não cobria o 2º monitor
        # e a área de lá era inselecionável).
        rect = None
        try:
            for scr in QApplication.screens():
                g = scr.geometry()
                rect = g if rect is None else rect.united(g)
        except Exception:
            rect = None
        if rect is None:
            rect = QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(rect)
        self._p0 = self._p1 = None
        self.selected = None
        self._finished = False
        self.showFullScreen()

    def _local_pos(self, e) -> QPoint:
        pos = e.position().toPoint()
        return QPoint(int(pos.x()), int(pos.y()))

    def mousePressEvent(self, e):
        self._p0 = self._local_pos(e)
        self._p1 = self._p0
        self.update()

    def mouseMoveEvent(self, e):
        if self._p0 is not None:
            self._p1 = self._local_pos(e)
            self.update()

    def mouseReleaseEvent(self, e):
        if self._p0 is not None:
            self._p1 = self._local_pos(e)
            self.finish_selection()

    def _emit_once(self, payload) -> bool:
        """Emite o resultado final no máximo uma vez. Retorna se emitiu."""
        if self._finished:
            return False
        self._finished = True
        self.selected = payload
        try:
            self.selection_done.emit(payload)
        except Exception:
            pass
        return True

    def finish_selection(self):
        """Conclui a partir dos pontos locais; emite selection_done."""
        if self._p0 is None or self._p1 is None:
            self.cancel_selection()
            return
        rect = normalize_points(self._p0, self._p1)
        self._emit_once(local_rect_to_screen_area(rect, self.pos()))
        self.hide()
        # close() dispara closeEvent(), que é no-op pois _finished já está
        # marcado — sem recursão e sem segunda emissão.
        self.close()

    def cancel_selection(self):
        self._emit_once(None)
        self.hide()
        self.close()

    def closeEvent(self, e):
        # Fechamento por caminho alternativo (X, Alt+F4, taskbar, close()
        # direto): converte em cancelamento seguro em vez de deixar o
        # chamador esperando um sinal que nunca chegará.
        if not self._finished:
            self._emit_once(None)
        super().closeEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.cancel_selection()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))
        if self._p0 is not None and self._p1 is not None:
            # Pontos já são locais: o retângulo desenhado é exatamente
            # o que será convertido em ScreenArea.
            r = normalize_points(self._p0, self._p1)
            p.setPen(QPen(QColor("#22c55e"), 2))
            p.drawRect(r)
