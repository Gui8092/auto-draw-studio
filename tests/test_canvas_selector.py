"""Regressão CORREÇÃO 3: convenção de coordenadas do seletor de área."""
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

from app.automation.screen_calibration import ScreenArea
from app.ui.canvas_selector import (CanvasSelector,
                                    local_rect_to_screen_area,
                                    normalize_points,
                                    screen_area_to_local_rect)


def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_origin_zero():
    area = local_rect_to_screen_area(QRect(10, 20, 300, 200), QPoint(0, 0))
    assert (area.x, area.y, area.width, area.height) == (10, 20, 300, 200)


def test_negative_x_origin():
    area = local_rect_to_screen_area(QRect(10, 20, 300, 200), QPoint(-1920, 0))
    assert (area.x, area.y) == (-1910, 20)
    assert (area.width, area.height) == (300, 200)


def test_negative_xy_origin():
    area = local_rect_to_screen_area(QRect(10, 20, 300, 200), QPoint(-1920, -1080))
    assert (area.x, area.y) == (-1910, -1060)


def test_various_rects_roundtrip():
    origin = QPoint(-1920, -300)
    for x, y, w, h in [(0, 0, 100, 100), (50, 60, 1, 1), (0, 0, 3840, 1080)]:
        area = local_rect_to_screen_area(QRect(x, y, w, h), origin)
        back = screen_area_to_local_rect(area, origin)
        assert (back.x(), back.y(), back.width(), back.height()) == (x, y, w, h)
        # Normalização: pontos invertidos geram o mesmo retângulo (modelo
        # inclusivo do QRect: QRect(p0, p1) inclui ambos os cantos).
        n1 = normalize_points(QPoint(x + w, y + h), QPoint(x, y))
        n2 = normalize_points(QPoint(x, y), QPoint(x + w, y + h))
        assert (n1.x(), n1.y(), n1.width(), n1.height()) == \
            (n2.x(), n2.y(), n2.width(), n2.height())
        assert (n1.width(), n1.height()) == (w + 1, h + 1)


def test_widget_finish_matches_visual_rect():
    """O ScreenArea deve corresponder exatamente ao retângulo desenhado."""
    _ensure_qapp()
    sel = CanvasSelector()
    sel.move(-1920, 0)  # simula overlay no monitor secundário
    sel.resize(3840, 1080)
    sel._p0 = QPoint(100, 100)  # pontos LOCAIS (como position() entrega)
    sel._p1 = QPoint(400, 300)
    got = []
    sel.selection_done.connect(lambda a: got.append(a))
    sel.finish_selection()
    assert len(got) == 1
    area = got[0]
    # global = local + origem do widget (modelo inclusivo do QRect:
    # arrastar de (100,100) a (400,300) inclui ambos os cantos → 301x201,
    # idêntico ao retângulo desenhado no paintEvent).
    assert (area.x, area.y) == (-1920 + 100, 0 + 100)
    assert (area.width, area.height) == (301, 201)
    # E o paint desenharia exatamente esse QRect: confere inverso
    back = screen_area_to_local_rect(area, sel.pos())
    assert (back.x(), back.y(), back.width(), back.height()) == (100, 100, 301, 201)


def test_widget_cancel_emits_none():
    _ensure_qapp()
    sel = CanvasSelector()
    got = []
    sel.selection_done.connect(lambda a: got.append(a))
    sel.cancel_selection()
    assert got == [None]
    assert sel.selected is None


def test_widget_unexpected_close_acts_as_cancel():
    """Fechamento por caminho alternativo equivale a cancelar, uma única vez."""
    _ensure_qapp()
    sel = CanvasSelector()
    got = []
    sel.selection_done.connect(lambda a: got.append(a))
    sel.close()  # sem finish/cancel: closeEvent converte em cancelamento
    assert got == [None]
    assert sel.selected is None
    sel.close()  # segundo close não reemite
    assert got == [None]


def test_widget_close_after_finish_does_not_reemit():
    """Sem recursão: finish fecha a janela sem segunda emissão no closeEvent."""
    _ensure_qapp()
    from PySide6.QtCore import QPoint
    sel = CanvasSelector()
    got = []
    sel.selection_done.connect(lambda a: got.append(a))
    sel._p0 = QPoint(0, 0)
    sel._p1 = QPoint(60, 60)
    sel.finish_selection()
    assert len(got) == 1
    assert sel.selected is not None
