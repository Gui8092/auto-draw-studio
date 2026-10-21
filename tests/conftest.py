"""Fixtures compartilhadas dos testes de UI (PySide6, offscreen)."""
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    """QApplication única da sessão (reaproveita a existente)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def make_window(qapp):
    """Instancia MainWindow garantindo fechamento em todos os caminhos.

    Cada janela mantém uma worker QThread viva; sem o close, a thread
    sobrevive até o teardown do interpretador e aborta o processo.
    O yield com try/finally fecha mesmo quando asserções falham.
    """
    from app.ui.main_window import MainWindow
    wins = []

    def _make(*a, **k):
        w = MainWindow(*a, **k)
        wins.append(w)
        return w

    yield _make
    for w in wins:
        try:
            w.close()
        except Exception:
            pass
