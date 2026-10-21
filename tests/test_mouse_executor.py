"""Testes do executor (mock) e do controlador (sem mover o mouse)."""
import threading
import time

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


def test_draw_stroke_press_release_order():
    backend = MockBackend()
    ex = MouseExecutor(backend=backend)
    ok = ex.draw_stroke([(10, 10), (20, 10), (30, 10)])
    assert ok
    kinds = [c[0] for c in backend.calls]
    assert kinds[0] == "moveTo"
    assert "mouseDown" in kinds and "mouseUp" in kinds
    assert kinds.index("mouseDown") < kinds.index("mouseUp")
    # mouseUp acontece mesmo com 1 ponto
    b2 = MockBackend()
    MouseExecutor(backend=b2).draw_stroke([(5, 5)])
    assert "mouseUp" in [c[0] for c in b2.calls]


def test_cancel_stops_execution():
    backend = MockBackend()
    ex = MouseExecutor(backend=backend)
    ex.cancel()
    assert ex.draw_stroke([(0, 0), (10, 10)]) is False


def test_controller_full_run_with_mock_sleep():
    backend = MockBackend()
    ctl = ExecutionController(executor=MouseExecutor(backend=backend),
                              sleep_fn=lambda s: None)
    assert ctl.start(_plan(3), _mapper(), stroke_delay=0) is True
    ctl._thread.join(timeout=5)
    assert ctl.state == ExecState.COMPLETED, f"estado={ctl.state}"
    assert ctl.done_count == 3
    assert backend.calls, "executor deveria ter sido chamado"


def test_controller_countdown_is_5s():
    assert ExecutionController.COUNTDOWN_SECONDS == 5


def test_move_speed_changes_segment_duration():
    backend = MockBackend()
    ex = MouseExecutor(backend=backend)
    ex.set_move_speed(100.0)
    assert ex.draw_stroke([(0, 0), (200, 0)]) is True
    durations = [c[3] for c in backend.calls if c[0] == "moveTo"]
    assert durations[1] == 2.0, f"200px a 100px/s deveria durar 2s, deu {durations[1]}"


def test_move_speed_faster_means_shorter_duration():
    slow, fast = MockBackend(), MockBackend()
    MouseExecutor(backend=slow, move_speed_px_s=100.0).draw_stroke([(0, 0), (200, 0)])
    MouseExecutor(backend=fast, move_speed_px_s=800.0).draw_stroke([(0, 0), (200, 0)])
    d_slow = [c[3] for c in slow.calls if c[0] == "moveTo"][1]
    d_fast = [c[3] for c in fast.calls if c[0] == "moveTo"][1]
    assert d_fast < d_slow


def test_no_speed_keeps_fixed_duration_for_compat():
    backend = MockBackend()
    MouseExecutor(backend=backend, move_duration=0.0).draw_stroke([(0, 0), (50, 30)])
    durations = [c[3] for c in backend.calls if c[0] == "moveTo"]
    assert durations == [0.0, 0.0]


def test_controller_propagates_speed_to_executor():
    backend = MockBackend()
    ex = MouseExecutor(backend=backend)
    ctl = ExecutionController(executor=ex, sleep_fn=lambda s: None)
    assert ctl.start(_plan(2), _mapper(), stroke_delay=0,
                     move_speed_px_s=400.0) is True
    assert ex.move_speed_px_s == 400.0
    ctl._thread.join(timeout=5)
    assert ctl.state == ExecState.COMPLETED
    durations = [c[3] for c in backend.calls if c[0] == "moveTo"]
    assert any(d > 0 for d in durations), "velocidade não chegou ao mouse"


def test_controller_rejects_double_start_and_empty():
    backend = MockBackend()
    states = []
    ctl = ExecutionController(executor=MouseExecutor(backend=backend),
                              sleep_fn=lambda s: time.sleep(0.01))
    assert ctl.start(_plan(5), _mapper(), stroke_delay=0.01) is True
    assert ctl.start(_plan(5), _mapper()) is False  # ocupado
    ctl._thread.join(timeout=5)
    # plano vazio
    ctl2 = ExecutionController(executor=MouseExecutor(backend=MockBackend()))
    assert ctl2.start(_plan(0), _mapper()) is False
    assert ctl2.state == ExecState.ERROR
