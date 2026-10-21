"""Regressões da Fase 0: execução segura (ciclo de vida, pausa, atalhos).

Cobre os bugs:
- start() aceitava uma segunda execução (duas threads movendo o mouse);
- pausa perdida na transição countdown→running (desenho travado);
- ausência de atalho de retomada (pausa virava via sem volta);
- encerramento sem `terminate()` e com cancelamento cooperativo.
"""
import threading
import time

import numpy as np
import pytest

from app.automation.coordinate_mapper import CoordinateMapper
from app.automation.execution_controller import ExecState, ExecutionController
from app.automation.mouse_executor import MockBackend, MouseExecutor
from app.automation.screen_calibration import ScreenArea
from app.models.drawing_plan import DrawingPlan, Stroke, StrokeType
from app.models.settings import ProcessingSettings


def _plan(n=3):
    return DrawingPlan(
        strokes=[Stroke(points=[(float(i * 10), 0.0), (float(i * 10 + 5), 0.0)],
                        kind=StrokeType.FILL) for i in range(n)],
        image_width=100, image_height=100,
    )


def _mapper():
    return CoordinateMapper(100, 100, ScreenArea(0, 0, 200, 200))


def _slow_ctl(countdown=2, delay=0.02):
    """Controlador com contagem regressiva longa o bastante para pausar.

    O estado é publicado de forma SINCRÔNICA no `start()` (correção do
    bug de execução dupla), então logo após `start()` o estado já é
    COUNTDOWN — sem depender de timing.
    """
    ctl = ExecutionController(executor=MouseExecutor(backend=MockBackend()),
                              sleep_fn=lambda s: time.sleep(delay))
    ctl.countdown_seconds = countdown
    return ctl


def _wait_state(ctl, *wanted, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if ctl.state in wanted:
            return ctl.state
        time.sleep(0.02)
    return ctl.state


# ----------------------------------------------------------------------
# 0.1 — start() não pode aceitar duas execuções
# ----------------------------------------------------------------------
def test_second_start_refused_before_worker_publishes_state():
    """A janela entre `start()` e o primeiro `_set` da thread não abre.

    Antes, o estado só era publicado DENTRO da thread: nesse intervalo
    `is_busy` era False e um segundo `start()` era aceito — duas threads
    movendo o mouse ao mesmo tempo.
    """
    gate = threading.Event()
    ctl = ExecutionController(executor=MouseExecutor(backend=MockBackend()),
                              sleep_fn=lambda s: None)
    original_set = ctl._set

    def slow_set(s, msg="", run_id=None):
        if s == ExecState.COUNTDOWN:
            gate.wait(timeout=3)
        original_set(s, msg, run_id)

    ctl._set = slow_set
    assert ctl.start(_plan(2), _mapper(), stroke_delay=0) is True
    # A thread está bloqueada no primeiro `_set` — o estado JÁ é busy.
    assert ctl.state == ExecState.COUNTDOWN
    assert ctl.is_busy is True
    assert ctl.start(_plan(2), _mapper(), stroke_delay=0) is False, \
        "segunda execução aceita: duas threads moveriam o mouse"
    gate.set()
    ctl.wait_finished(timeout=10)


def test_only_one_thread_draws_after_rejected_start():
    """A thread rejeitada não existe (nenhuma corrida de mouse)."""
    gate = threading.Event()
    ctl = ExecutionController(executor=MouseExecutor(backend=MockBackend()),
                              sleep_fn=lambda s: None)
    original_set = ctl._set

    def slow_set(s, msg="", run_id=None):
        if s == ExecState.COUNTDOWN:
            gate.wait(timeout=3)
        original_set(s, msg, run_id)

    ctl._set = slow_set
    assert ctl.start(_plan(2), _mapper(), stroke_delay=0) is True
    assert ctl.start(_plan(2), _mapper(), stroke_delay=0) is False
    gate.set()
    ctl.wait_finished(timeout=10)
    assert len([t for t in threading.enumerate() if t.name.startswith("Thread-")]) == 0


def test_restart_after_cancel_waits_for_previous_thread():
    """Reiniciar após cancelar não deixa a thread antiga desenhar."""
    backend = MockBackend()
    ctl = _slow_ctl()
    ctl.executor = MouseExecutor(backend=backend)
    ctl.start(_plan(3), _mapper(), stroke_delay=0.02)
    assert ctl.state == ExecState.COUNTDOWN
    ctl.cancel()
    assert _wait_state(ctl, ExecState.CANCELLED) == ExecState.CANCELLED
    backend.calls.clear()
    assert ctl.start(_plan(1), _mapper(), stroke_delay=0) is True
    ctl.wait_finished(timeout=10)
    assert ctl.state == ExecState.COMPLETED
    assert ctl.done_count == 1, "a thread antiga também desenhou"


# ----------------------------------------------------------------------
# 0.3 — a pausa não pode ser perdida
# ----------------------------------------------------------------------
def test_pause_survives_running_transition():
    """A fase interna pode virar RUNNING; o estado público segue PAUSED."""
    ctl = _slow_ctl()
    ctl.start(_plan(2), _mapper(), stroke_delay=0)
    assert ctl.state == ExecState.COUNTDOWN
    assert ctl.pause() is True
    assert ctl.state == ExecState.PAUSED
    # Simula a virada da fase enquanto pausado (o que a thread faz).
    ctl._set(ExecState.RUNNING, "Desenhando…", ctl._active_run)
    assert ctl.state == ExecState.PAUSED, "a pausa foi sobrescrita"
    assert ctl.resume() is True
    assert ctl.state == ExecState.RUNNING
    ctl.cancel()
    ctl.wait_finished(timeout=10)


def test_pause_exactly_at_countdown_to_running_keeps_pause():
    """Pausa no último tick do countdown: a virada para RUNNING não a perde."""
    ctl = ExecutionController(executor=MouseExecutor(backend=MockBackend()))
    ticks = {"n": 0}

    def sleeper(s):
        ticks["n"] += 1
        if ticks["n"] == 20:      # último tick de 1s de contagem (20 x 50ms)
            ctl.pause()
        time.sleep(0.005)

    ctl = ExecutionController(executor=MouseExecutor(backend=MockBackend()),
                              sleep_fn=sleeper)
    ctl.countdown_seconds = 1
    ctl.start(_plan(2), _mapper(), stroke_delay=0)
    time.sleep(0.4)
    assert ctl.state == ExecState.PAUSED, \
        f"pausa perdida na virada (estado={ctl.state})"
    assert ctl.resume() is True
    assert _wait_state(ctl, ExecState.COMPLETED, timeout=10) == ExecState.COMPLETED
    assert ctl.done_count == 2


def test_toggle_pause_alternates():
    ctl = _slow_ctl()
    ctl.start(_plan(2), _mapper(), stroke_delay=0)
    assert ctl.state == ExecState.COUNTDOWN
    assert ctl.toggle_pause() is True
    assert ctl.state == ExecState.PAUSED
    assert ctl.toggle_pause() is True
    assert ctl.state in (ExecState.COUNTDOWN, ExecState.RUNNING)
    ctl.cancel()
    ctl.wait_finished(timeout=10)


def test_wait_finished_reports_thread_end():
    ctl = ExecutionController(executor=MouseExecutor(backend=MockBackend()),
                              sleep_fn=lambda s: None)
    ctl.start(_plan(1), _mapper(), stroke_delay=0)
    assert ctl.wait_finished(timeout=10) is True
    assert ctl.state == ExecState.COMPLETED


# ----------------------------------------------------------------------
# 0.4 — atalhos: pausa alterna, retomada existe
# ----------------------------------------------------------------------
def test_hotkey_pause_binding_toggles_pause():
    """F10 alterna pausar/retomar (não existe mais via sem volta)."""
    from app.automation.hotkeys import GlobalHotkeys

    calls = []
    ctl = _slow_ctl()
    h = GlobalHotkeys(on_start=lambda: calls.append("start"),
                      on_pause=ctl.toggle_pause,
                      on_resume=ctl.resume,
                      on_cancel=ctl.cancel)
    h.bindings = {"start": "f9", "pause": "f10", "resume": "f11",
                  "cancel": "esc"}
    assert h._key_to_action("f10") == "pause"
    assert h._key_to_action("f11") == "resume"

    ctl.start(_plan(2), _mapper(), stroke_delay=0)
    assert ctl.state == ExecState.COUNTDOWN
    assert h._dispatch("pause") is True
    assert ctl.state == ExecState.PAUSED
    assert h._dispatch("pause") is True      # mesmo atalho, agora retoma
    assert ctl.state in (ExecState.COUNTDOWN, ExecState.RUNNING)
    ctl.cancel()
    ctl.wait_finished(timeout=10)


def test_hotkey_modifier_combination():
    from app.automation.hotkeys import GlobalHotkeys

    h = GlobalHotkeys(on_start=lambda: None)
    h.bindings = {"start": "ctrl+f9"}
    assert h._key_to_action("f9", {"ctrl"}) == "start"
    assert h._key_to_action("f9", {"shift"}) is None
    assert h._key_to_action("f9") is None


def test_hotkey_auto_repeat_is_ignored(monkeypatch):
    """Segurar a tecla não re-dispara a ação."""
    from app.automation.hotkeys import GlobalHotkeys

    import sys
    import types

    created = []

    class FakeListener:
        def __init__(self, on_press=None, on_release=None):
            self.on_press = on_press
            self.on_release = on_release

        def start(self):
            pass

        def stop(self):
            pass

    fake_keyboard = types.SimpleNamespace(Listener=FakeListener)
    monkeypatch.setitem(sys.modules, "pynput", types.SimpleNamespace(keyboard=fake_keyboard))
    monkeypatch.setitem(sys.modules, "pynput.keyboard", fake_keyboard)

    calls = []
    h = GlobalHotkeys(on_start=lambda: calls.append("start"))
    h.start({"start": "f9"})
    listener = created[-1] if created else h._listener

    class FakeKey:
        name = "f9"

    listener.on_press(FakeKey())
    listener.on_press(FakeKey())   # auto-repeat
    assert calls.count("start") == 1, "auto-repeat re-disparou a ação"


# ----------------------------------------------------------------------
# 0.2 — cancelamento cooperativo do processamento
# ----------------------------------------------------------------------
def test_process_to_plan_raises_processing_cancelled():
    from app.core.pipeline import ProcessingCancelled, process_to_plan

    gray = np.full((60, 60), 255, np.uint8)
    gray[10:50, 10:50] = 0
    with pytest.raises(ProcessingCancelled):
        process_to_plan(gray, ProcessingSettings(), cancel_check=lambda: True)


def test_process_to_plan_cancels_midway():
    """O cancelamento é percebido durante o trabalho (não só no início)."""
    from app.core.pipeline import ProcessingCancelled, process_to_plan

    gray = np.full((200, 200), 255, np.uint8)
    gray[20:180, 20:180] = 0
    calls = {"n": 0}

    def check():
        calls["n"] += 1
        return calls["n"] > 2

    with pytest.raises(ProcessingCancelled):
        process_to_plan(gray, ProcessingSettings(), cancel_check=check)
    assert calls["n"] > 2


def test_worker_emits_cancelled(qapp):
    """O worker sinaliza o cancelamento em vez de travar o encerramento."""
    from PySide6.QtCore import QCoreApplication

    from app.ui.process_worker import ProcessWorker

    worker = ProcessWorker()
    got = []
    worker.cancelled.connect(lambda gen: got.append(gen))
    worker.request_stop()
    assert worker.stop_requested is True
    worker.request(1, np.full((40, 40), 255, np.uint8), ProcessingSettings())
    deadline = time.time() + 5
    while not got and time.time() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert got == [1], "worker não sinalizou o cancelamento"


def test_close_waits_for_thread_without_terminate(make_window):
    """O encerramento NUNCA usa terminate() e espera o fim real."""
    w = make_window()
    terminated = []
    try:
        w._proc_thread.terminate = lambda: terminated.append(True)
    except Exception:
        pass  # Shiboken pode não permitir; o teste do tempo cobre o caso
    w.close()
    assert not w._proc_thread.isRunning()
    assert terminated == [], "terminate() não pode ser usado no encerramento"
