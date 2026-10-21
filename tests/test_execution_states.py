"""Regressão CORREÇÕES 5/6: pausa no countdown, retomada e reset do executor."""
import threading
import time

import pytest

from app.automation.coordinate_mapper import CoordinateMapper
from app.automation.execution_controller import ExecState, ExecutionController
from app.automation.mouse_executor import MockBackend, MouseExecutor
from app.automation.screen_calibration import ScreenArea
from app.models.drawing_plan import DrawingPlan, Stroke, StrokeType


def _plan(n=3):
    return DrawingPlan(
        strokes=[Stroke(points=[(float(i * 10), 0.0), (float(i * 10 + 5), 0.0)],
                        kind=StrokeType.FILL) for i in range(n)],
        image_width=100, image_height=100,
    )


def _mapper():
    return CoordinateMapper(100, 100, ScreenArea(0, 0, 200, 200))


def _wait_state(ctl, *wanted, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if ctl.state in wanted:
            return ctl.state
        time.sleep(0.02)
    return ctl.state


def test_pause_during_countdown_and_resume():
    ctl = ExecutionController(executor=MouseExecutor(backend=MockBackend()),
                              sleep_fn=lambda s: time.sleep(0.01))
    assert ctl.start(_plan(2), _mapper(), stroke_delay=0) is True
    assert _wait_state(ctl, ExecState.COUNTDOWN, ExecState.RUNNING) == ExecState.COUNTDOWN
    assert ctl.pause() is True
    assert ctl.state == ExecState.PAUSED
    time.sleep(0.05)
    assert ctl.state == ExecState.PAUSED, "pausado não deve avançar sozinho"
    assert ctl.resume() is True
    # Retoma o countdown (não pula para RUNNING/COMPLETED direto)
    assert ctl.state == ExecState.COUNTDOWN
    assert _wait_state(ctl, ExecState.COMPLETED, timeout=10) == ExecState.COMPLETED
    assert ctl.done_count == 2


def test_cancel_during_countdown():
    ctl = ExecutionController(executor=MouseExecutor(backend=MockBackend()),
                              sleep_fn=lambda s: time.sleep(0.01))
    ctl.start(_plan(2), _mapper(), stroke_delay=0)
    assert _wait_state(ctl, ExecState.COUNTDOWN, ExecState.RUNNING) == ExecState.COUNTDOWN
    ctl.cancel()
    assert _wait_state(ctl, ExecState.CANCELLED) == ExecState.CANCELLED


def test_pause_resume_during_drawing():
    gate = threading.Event()
    backend = MockBackend()
    real_move = backend.moveTo

    def slow_move(x, y, duration=0):
        gate.wait(timeout=5)
        return real_move(x, y, duration=duration)

    backend.moveTo = slow_move
    ctl = ExecutionController(executor=MouseExecutor(backend=backend),
                              sleep_fn=lambda s: None)
    ctl.start(_plan(4), _mapper(), stroke_delay=0.05)
    assert _wait_state(ctl, ExecState.RUNNING, timeout=10) == ExecState.RUNNING
    assert ctl.pause() is True
    assert ctl.state == ExecState.PAUSED
    gate.set()
    assert ctl.resume() is True
    assert _wait_state(ctl, ExecState.COMPLETED, timeout=10) == ExecState.COMPLETED


def test_no_double_start_and_invalid_transitions():
    ctl = ExecutionController(executor=MouseExecutor(backend=MockBackend()),
                              sleep_fn=lambda s: time.sleep(0.005))
    assert ctl.pause() is False, "pausar em READY deve falhar"
    assert ctl.resume() is False, "retomar sem pausa deve falhar"
    assert ctl.start(_plan(4), _mapper(), stroke_delay=0.01) is True
    assert ctl.start(_plan(4), _mapper()) is False, "duas execuções simultâneas"
    ctl._thread.join(timeout=10)
    assert ctl.state == ExecState.COMPLETED
    # Nova execução após concluir é permitida
    assert ctl.start(_plan(1), _mapper(), stroke_delay=0) is True
    ctl._thread.join(timeout=10)
    assert ctl.state == ExecState.COMPLETED


def test_cancel_releases_mouse_and_allows_restart():
    backend = MockBackend()
    ctl = ExecutionController(executor=MouseExecutor(backend=backend),
                              sleep_fn=lambda s: time.sleep(0.01))
    ctl.start(_plan(3), _mapper(), stroke_delay=0.02)
    _wait_state(ctl, ExecState.COUNTDOWN, ExecState.RUNNING)
    ctl.cancel()
    assert _wait_state(ctl, ExecState.CANCELLED) == ExecState.CANCELLED
    kinds = [c[0] for c in backend.calls]
    assert "mouseUp" in kinds, "cancelar deve soltar o botão do mouse"
    # Restart não herda o cancelamento (CORREÇÃO 6)
    backend2 = ctl.executor.backend
    assert ctl.start(_plan(1), _mapper(), stroke_delay=0) is True
    ctl._thread.join(timeout=10)
    assert ctl.state == ExecState.COMPLETED


def test_executor_prepare_resets_cancel():
    ex = MouseExecutor(backend=MockBackend())
    ex.cancel()
    assert ex.is_cancelled
    assert ex.draw_stroke([(0, 0), (1, 1)]) is False
    ex.prepare()
    assert not ex.is_cancelled
    assert ex.draw_stroke([(0, 0), (1, 1)]) is True


def test_executor_releases_mouse_on_backend_error():
    class ExplodingBackend(MockBackend):
        def moveTo(self, x, y, duration=0):
            super().moveTo(x, y, duration=duration)
            raise RuntimeError("falha no driver")

    backend = ExplodingBackend()
    ex = MouseExecutor(backend=backend)
    with pytest.raises(RuntimeError):
        ex.draw_stroke([(0, 0), (5, 5)])
    assert backend.calls[-1][0] == "mouseUp"
