"""Regressão CORREÇÃO 8: seleção assíncrona, sem espera ativa."""
import inspect

from PySide6.QtWidgets import QApplication

from app.automation.screen_calibration import ScreenArea


def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# Fixture `make_window` (fecha janelas e encerra worker threads em todos
# os caminhos) provida por `tests/conftest.py`.


def test_no_busy_loop_in_select_area():
    from app.ui.main_window import MainWindow
    src = inspect.getsource(MainWindow.select_area)
    assert "processEvents" not in src, "loop de espera ativa ainda presente"
    assert "while " not in src or "while sel" not in src


def test_select_area_is_nonblocking_and_guarded(monkeypatch, make_window):
    """select_area retorna de imediato; segunda chamada é ignorada."""
    _ensure_qapp()
    from app.ui import main_window as mw_mod

    created = []

    class FakeSelector:
        def __init__(self, *a, **k):
            created.append(self)
            self.started = False
            self._cb = None

        def start(self):
            self.started = True  # NÃO bloqueia

        @property
        def selection_done(self):
            class _Sig:
                def connect(inner, cb):
                    self._cb = cb
            return _Sig()

    monkeypatch.setattr(mw_mod, "CanvasSelector", FakeSelector)
    w = make_window()
    w.select_area()
    assert len(created) == 1 and created[0].started
    assert w._selector is not None
    # Segunda seleção simultânea é ignorada
    w.select_area()
    assert len(created) == 1, "duas seleções simultâneas!"
    # Conclusão via sinal: área válida
    w._on_area_selected(ScreenArea(5, 5, 200, 200))
    assert w._selector is None
    assert w.area is not None and (w.area.x, w.area.y) == (5, 5)
    # Cancelamento limpa o estado
    w.select_area()
    w._on_area_selected(None)
    assert w._selector is None


def test_area_selected_invalid_keeps_old(make_window):
    _ensure_qapp()
    w = make_window()
    old = ScreenArea(1, 1, 100, 100)
    w.area = old
    w._selector = object()  # simula seleção em andamento
    w._on_area_selected(ScreenArea(0, 0, 5, 5))  # inválida (<20px)
    assert w.area is old
    assert w._selector is None


def _real_selection(w):
    """Abre seleção real (offscreen) e retorna o seletor ativo."""
    w.select_area()
    assert w._selector is not None
    return w._selector


def test_confirm_clears_ref_and_sets_area(make_window):
    """Cenário 1: confirmar limpa a referência e aplica a área."""
    _ensure_qapp()
    from PySide6.QtCore import QPoint
    w = make_window()
    sel = _real_selection(w)
    emissions = []
    sel.selection_done.connect(lambda a: emissions.append(a))
    sel._p0 = QPoint(10, 10)
    sel._p1 = QPoint(200, 150)
    sel.finish_selection()
    assert w._selector is None
    assert w.area is not None and w.area.width >= 20
    assert len(emissions) == 1, "finalização deve emitir exatamente uma vez"


def test_cancel_clears_ref_and_keeps_old_area(make_window):
    """Cenários 2+6: cancelar limpa a referência e preserva a área anterior."""
    _ensure_qapp()
    w = make_window()
    old = ScreenArea(7, 7, 120, 120)
    w.area = old
    sel = _real_selection(w)
    emissions = []
    sel.selection_done.connect(lambda a: emissions.append(a))
    sel.cancel_selection()
    assert w._selector is None
    assert w.area is old
    assert emissions == [None]


def test_direct_close_clears_ref_and_unblocks(make_window):
    """Cenários 3+4: close() direto (fechamento inesperado) não prende o estado."""
    _ensure_qapp()
    w = make_window()
    old = ScreenArea(3, 3, 150, 150)
    w.area = old
    sel = _real_selection(w)
    emissions = []
    sel.selection_done.connect(lambda a: emissions.append(a))
    sel.close()  # caminho alternativo: sem finish/cancel explícitos
    assert w._selector is None, "close() direto deixou _selector preso"
    assert w.area is old, "fechamento inesperado deve preservar a área anterior"
    assert emissions == [None], "fechamento inesperado deve equivaler a cancelar"
    # Nova seleção precisa funcionar em seguida
    sel2 = _real_selection(w)
    assert sel2 is not sel
    sel2.close()
    assert w._selector is None


def test_restart_after_each_termination(make_window):
    """Cenário 5: nova seleção possível após confirmar, cancelar ou fechar."""
    _ensure_qapp()
    from PySide6.QtCore import QPoint
    w = make_window()
    # confirmar
    sel = _real_selection(w)
    sel._p0 = QPoint(0, 0)
    sel._p1 = QPoint(100, 100)
    sel.finish_selection()
    assert w._selector is None
    # cancelar
    sel = _real_selection(w)
    sel.cancel_selection()
    assert w._selector is None
    # fechar inesperadamente
    sel = _real_selection(w)
    sel.close()
    assert w._selector is None
    # e ainda é possível selecionar de novo
    sel = _real_selection(w)
    sel.close()
    assert w._selector is None


def test_no_duplicate_emissions_on_close_after_finish():
    """Cenário 7: finish seguido de close não emite duas vezes."""
    _ensure_qapp()
    from PySide6.QtCore import QPoint
    from app.ui.canvas_selector import CanvasSelector
    sel = CanvasSelector()
    got = []
    sel.selection_done.connect(lambda a: got.append(a))
    sel._p0 = QPoint(5, 5)
    sel._p1 = QPoint(50, 50)
    sel.finish_selection()
    sel.close()  # segundo fechamento não pode reemitir
    assert len(got) == 1
    sel2 = CanvasSelector()
    got2 = []
    sel2.selection_done.connect(lambda a: got2.append(a))
    sel2.cancel_selection()
    sel2.close()
    assert got2 == [None]


def test_connect_failure_leaves_no_stuck_state(monkeypatch, make_window):
    """Cenários 8+9: falha ao conectar não prende _selector; retry funciona."""
    _ensure_qapp()
    from app.ui import main_window as mw_mod
    from app.ui.main_window import MainWindow

    class BrokenSelector:
        def __init__(self, *a, **k):
            pass

        @property
        def selection_done(self):
            class _Sig:
                def connect(self, cb):
                    raise RuntimeError("sinal quebrado")
            return _Sig()

        def deleteLater(self):
            pass

    monkeypatch.setattr(mw_mod, "CanvasSelector", BrokenSelector)
    w = make_window()
    w.show()
    w.select_area()
    assert w._selector is None, "falha de conexão deixou _selector preso"
    assert not w.isHidden(), "janela principal não deve ficar oculta após falha"

    # Nova tentativa com seletor funcional precisa funcionar
    created = []

    class FakeSelector:
        def __init__(self, *a, **k):
            created.append(self)

        def start(self):
            pass

        def deleteLater(self):
            pass

        @property
        def selection_done(self):
            class _Sig:
                def connect(inner, cb):
                    self._cb = cb
            return _Sig()

    monkeypatch.setattr(mw_mod, "CanvasSelector", FakeSelector)
    w.select_area()
    assert w._selector is not None and len(created) == 1
    w._on_area_selected(ScreenArea(9, 9, 200, 200))
    assert w._selector is None
    assert (w.area.x, w.area.y) == (9, 9)
