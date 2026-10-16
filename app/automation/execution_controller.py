"""Controlador de execução: máquina de estados + thread + countdown 5s."""
from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Callable

from app.automation.coordinate_mapper import CoordinateMapper
from app.automation.mouse_executor import MouseExecutor
from app.models.drawing_plan import DrawingPlan


class ExecState(str, Enum):
    READY = "ready"
    COUNTDOWN = "countdown"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


class ExecutionController:
    COUNTDOWN_SECONDS = 5

    def __init__(
        self,
        executor: MouseExecutor | None = None,
        on_state: Callable[[ExecState], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        on_message: Callable[[str], None] | None = None,
        sleep_fn=None,
    ):
        self.executor = executor or MouseExecutor()
        self.on_state = on_state
        self.on_progress = on_progress
        self.on_message = on_message
        self._sleep = sleep_fn or time.sleep
        self.state = ExecState.READY
        self._thread: threading.Thread | None = None
        self._pause = threading.Event()
        self._pause.set()
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self.done_count = 0
        self.total_count = 0
        # De onde a pausa partiu (COUNTDOWN ou RUNNING); usado pelo resume().
        self._paused_from: ExecState | None = None

    def _set(self, s: ExecState, msg: str = ""):
        with self._lock:
            self.state = s
        if self.on_state:
            try:
                self.on_state(s)
            except Exception:
                pass
        if msg and self.on_message:
            try:
                self.on_message(msg)
            except Exception:
                pass

    @property
    def is_busy(self) -> bool:
        return self.state in (ExecState.COUNTDOWN, ExecState.RUNNING, ExecState.PAUSED)

    def start(self, plan: DrawingPlan, mapper: CoordinateMapper,
              stroke_delay: float = 0.03,
              move_speed_px_s: float | None = None) -> bool:
        if self.is_busy:
            return False
        if plan.total_strokes == 0:
            self._set(ExecState.ERROR, "Plano vazio: nada para desenhar.")
            return False
        self._cancel.clear()
        self._pause.set()
        self._paused_from = None
        self.done_count = 0
        self.total_count = plan.total_strokes
        self.executor.prepare()
        self.executor.set_move_speed(move_speed_px_s)
        self._thread = threading.Thread(
            target=self._run, args=(plan, mapper, stroke_delay), daemon=True)
        self._thread.start()
        return True

    def _run(self, plan, mapper, stroke_delay):
        try:
            self._set(ExecState.COUNTDOWN, "Contagem regressiva: 5 s…")
            # Contagem em ticks curtos para que pause/cancel respondam
            # durante o countdown (pausa congela via _pause.wait()).
            for i in range(self.COUNTDOWN_SECONDS, 0, -1):
                if self._cancel.is_set():
                    self._set(ExecState.CANCELLED, "Cancelado na contagem regressiva.")
                    return
                if self.on_message:
                    try:
                        self.on_message(f"Começando em {i}…")
                    except Exception:
                        pass
                ticks = max(1, int(1.0 / 0.05))
                for _ in range(ticks):
                    if self._cancel.is_set():
                        self._set(ExecState.CANCELLED, "Cancelado na contagem regressiva.")
                        return
                    self._pause.wait()  # congela aqui enquanto pausado
                    if self._cancel.is_set():
                        self._set(ExecState.CANCELLED, "Cancelado na contagem regressiva.")
                        return
                    self._sleep(0.05)
            self._set(ExecState.RUNNING, "Desenhando…")
            for idx, stroke in enumerate(plan.strokes):
                if self._cancel.is_set():
                    self._set(ExecState.CANCELLED, "Execução cancelada.")
                    return
                self._pause.wait()  # bloqueia enquanto pausado
                if self._cancel.is_set():
                    self._set(ExecState.CANCELLED, "Execução cancelada.")
                    return
                pts = mapper.map_stroke(stroke.points)
                ok = self.executor.draw_stroke(pts)
                self.done_count = idx + 1
                if self.on_progress:
                    try:
                        self.on_progress(self.done_count, self.total_count)
                    except Exception:
                        pass
                if not ok or self._cancel.is_set():
                    self._set(ExecState.CANCELLED, "Execução cancelada.")
                    return
                if stroke_delay > 0:
                    self._sleep(stroke_delay)
            self._set(ExecState.COMPLETED, "Desenho concluído.")
        except Exception as e:
            self._set(ExecState.ERROR, f"Erro na execução: {e}")

    def pause(self) -> bool:
        """Pausa a contagem regressiva ou o desenho. Retorna se pausou."""
        if self.state in (ExecState.RUNNING, ExecState.COUNTDOWN):
            self._paused_from = self.state
            self._pause.clear()
            try:
                self.executor.backend.mouseUp(button="left")
            except Exception:
                pass
            self._set(ExecState.PAUSED, "Pausado.")
            return True
        return False

    def resume(self) -> bool:
        """Retoma de onde pausou (countdown continua, desenho continua)."""
        if self.state == ExecState.PAUSED:
            origin = self._paused_from or ExecState.RUNNING
            self._paused_from = None
            self._pause.set()
            self._set(origin, "Retomado.")
            return True
        return False

    def cancel(self):
        if self.is_busy:
            self._cancel.set()
            self._pause.set()
            self.executor.cancel()
            try:
                self.executor.backend.mouseUp(button="left")
            except Exception:
                pass
