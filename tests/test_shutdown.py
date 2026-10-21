"""Hotfix: encerramento seguro durante processamento ativo (determinístico)."""
import threading
import time

import numpy as np
from PySide6.QtWidgets import QApplication

from app.models.drawing_plan import DrawingPlan


def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _long_task_factory(started: threading.Event, seconds: float = 3.0):
    """process_to_plan controlado: sinaliza entrada e dorme (> antigo limite 2s).

    Aceita `cancel_check` (o worker passa esse kwarg) e o ignora de
    propósito: a tarefa é determinística e NÃO reage ao cancelamento,
    o que permite verificar que o closeEvent aguarda o término REAL.
    """
    def _task(gray, settings, cancel_check=None):
        started.set()
        time.sleep(seconds)
        mask = np.zeros((10, 10), np.uint8)
        return mask, DrawingPlan(strokes=[], image_width=10, image_height=10)
    return _task


def test_close_during_active_processing(make_window, monkeypatch):
    """Fechar no meio de tarefa longa (>2s): aguarda, sem destruir thread ativa."""
    _ensure_qapp()
    import app.ui.process_worker as pw_mod
    started = threading.Event()
    monkeypatch.setattr(pw_mod, "process_to_plan", _long_task_factory(started, 3.0))
    w = make_window()
    w.gray = np.full((40, 40), 30, np.uint8)  # com tinta: detectaria callback tardio
    w.reprocess()
    assert started.wait(timeout=10), "worker não iniciou a tarefa"
    t0 = time.perf_counter()
    w.close()  # deve bloquear até o término real (~3s), nunca abortar
    dt = time.perf_counter() - t0
    assert dt >= 2.5, "close retornou antes do término — thread destruída ativa?"
    assert not w._proc_thread.isRunning()
    assert w._closing
    # Callbacks tardios (done na fila) não tocam a UI após o close
    for _ in range(20):
        QApplication.processEvents()
        time.sleep(0.01)
    assert w.plan is None, "callback tardio aplicou plano após encerramento"


def test_close_without_work_is_fast(make_window):
    """Fechar sem trabalho em andamento é imediato."""
    _ensure_qapp()
    w = make_window()
    t0 = time.perf_counter()
    w.close()
    assert time.perf_counter() - t0 < 2.0
    assert not w._proc_thread.isRunning()


def test_close_with_queued_reprocess(make_window):
    """Fechar com reprocessamentos enfileirados: encerra limpo."""
    _ensure_qapp()
    w = make_window()
    w.gray = np.full((30, 30), 200, np.uint8)
    w.reprocess()
    w.reprocess()
    w.reprocess()
    w.close()
    assert not w._proc_thread.isRunning()


def test_many_windows_open_close_sequentially(make_window):
    """Múltiplas aberturas/fechamentos na mesma sessão (cenário do prompt)."""
    _ensure_qapp()
    for _ in range(3):
        w = make_window()
        w.gray = np.full((20, 20), 200, np.uint8)
        w.reprocess()
        w.close()
        assert not w._proc_thread.isRunning()
