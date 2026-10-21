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


# Fases em que a thread de desenho está ativa (aceita pausa/cancelamento).
_ACTIVE_PHASES = (ExecState.COUNTDOWN, ExecState.RUNNING)


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
        # FASE real da execução. O estado PÚBLICO é DERIVADO: enquanto a
        # execução está pausada, `state` devolve PAUSED, mas `_phase`
        # continua sendo COUNTDOWN/RUNNING.
        #
        # Antes, fase e estado público eram o mesmo atributo e uma pausa
        # podia ser sobrescrita por um `_set(RUNNING)`: o estado passava
        # a mentir "running" enquanto a thread ficava congelada em
        # `_pause.wait()`, e `resume()` recusava (state != PAUSED) —
        # o desenho ficava travado para sempre.
        self._phase = ExecState.READY
        self._paused = False
        self._thread: threading.Thread | None = None
        self._pause = threading.Event()
        self._pause.set()
        self._cancel = threading.Event()
        self._lock = threading.RLock()
        self.done_count = 0
        self.total_count = 0
        # Duração da contagem regressiva (s). Padrão = classe (5); a UI
        # sobrescreve com o countdown_s das configurações salvas.
        self.countdown_seconds: int = int(self.COUNTDOWN_SECONDS)
        # Geração da execução: uma thread antiga (ex.: cancelada, mas
        # ainda se encerrando) não pode publicar estado por cima da
        # execução atual.
        self._run_seq = 0
        self._active_run = 0

    # ------------------------------------------------------------------
    # Estado
    # ------------------------------------------------------------------
    @property
    def state(self) -> ExecState:
        """Estado público (PAUSED tem prioridade sobre a fase interna)."""
        with self._lock:
            return self._public_state_locked()

    def _public_state_locked(self) -> ExecState:
        if self._paused and self._phase in _ACTIVE_PHASES:
            return ExecState.PAUSED
        return self._phase

    def _set(self, s: ExecState, msg: str = "", run_id: int | None = None):
        """Publica uma mudança de estado.

        `run_id` opcional: quando informado e diferente da execução
        ativa, a atualização é descartada (thread obsoleta).
        """
        if run_id is not None and run_id != self._active_run:
            return
        with self._lock:
            self._phase = s
            public = self._public_state_locked()
        self._notify(public, msg)

    def _publish(self, msg: str = ""):
        """Republica o estado ATUAL sem alterar a fase.

        Usado por `pause()`/`resume()`: escrever a fase de novo poderia
        movê-la para trás (ex.: COUNTDOWN depois de RUNNING) se a thread
        tivesse avançado nesse intervalo.
        """
        with self._lock:
            public = self._public_state_locked()
        self._notify(public, msg)

    def _notify(self, public: ExecState, msg: str):
        if self.on_state:
            try:
                self.on_state(public)
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

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------
    def _join_previous(self, timeout: float = 2.0) -> None:
        """Aguarda o fim REAL da execução anterior (se ainda existir).

        O executor é compartilhado entre execuções: se a thread antiga
        ainda estivesse viva quando `prepare()` zerasse o cancelamento,
        ela voltaria a desenhar por cima da nova execução.
        """
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout)

    def start(self, plan: DrawingPlan, mapper: CoordinateMapper,
              stroke_delay: float = 0.03,
              move_speed_px_s: float | None = None) -> bool:
        if self.is_busy:
            return False
        if plan.total_strokes == 0:
            self._set(ExecState.ERROR, "Plano vazio: nada para desenhar.")
            return False
        self._join_previous()
        self._run_seq += 1
        run_id = self._run_seq
        with self._lock:
            self._cancel.clear()
            self._pause.set()
            self._paused = False
            self.done_count = 0
            self.total_count = plan.total_strokes
            self._active_run = run_id
            # Publica o estado ANTES de spawnar a thread. Antes, o estado
            # só era publicado DENTRO da thread: na janela entre
            # `thread.start()` e o primeiro `_set`, `is_busy` era False e
            # um segundo `start()` era ACEITO — duas threads movendo o
            # mouse ao mesmo tempo.
            self._phase = ExecState.COUNTDOWN
        self.executor.prepare()
        self.executor.set_move_speed(move_speed_px_s)
        self._thread = threading.Thread(
            target=self._run, args=(run_id, plan, mapper, stroke_delay), daemon=True)
        self._thread.start()
        return True

    def wait_finished(self, timeout: float = 5.0) -> bool:
        """Aguarda o término real da thread de desenho.

        Sem isso, o app pode encerrar com o mouse ainda se movendo
        (a thread é daemon e seria morta no fim do interpretador).
        """
        t = self._thread
        if t is None:
            return True
        t.join(timeout)
        return not t.is_alive()

    def _rest(self, seconds: float) -> bool:
        """Descansa de forma interrompível (pausa congela, cancel aborta).

        Retorna False se cancelado no meio (o chamador encerra como
        CANCELLED em vez de cair no próximo estado/encerrar como concluído).
        """
        if seconds <= 0:
            return not self._cancel.is_set()
        remaining = float(seconds)
        while remaining > 0:
            if self._cancel.is_set():
                return False
            self._pause.wait()  # congela aqui enquanto pausado
            if self._cancel.is_set():
                return False
            chunk = min(0.05, remaining)
            self._sleep(chunk)
            remaining -= chunk
        return not self._cancel.is_set()

    def _run(self, run_id, plan, mapper, stroke_delay):
        try:
            total_wait = max(1, int(self.countdown_seconds))
            self._set(ExecState.COUNTDOWN, f"Contagem regressiva: {total_wait} s…", run_id)
            # Contagem em ticks curtos para que pause/cancel respondam
            # durante o countdown (pausa congela via _pause.wait()).
            for i in range(total_wait, 0, -1):
                if self._cancel.is_set():
                    self._set(ExecState.CANCELLED, "Cancelado na contagem regressiva.", run_id)
                    return
                if self.on_message:
                    try:
                        self.on_message(f"Começando em {i}…")
                    except Exception:
                        pass
                ticks = max(1, int(1.0 / 0.05))
                for _ in range(ticks):
                    if self._cancel.is_set():
                        self._set(ExecState.CANCELLED, "Cancelado na contagem regressiva.", run_id)
                        return
                    self._pause.wait()  # congela aqui enquanto pausado
                    if self._cancel.is_set():
                        self._set(ExecState.CANCELLED, "Cancelado na contagem regressiva.", run_id)
                        return
                    self._sleep(0.05)
            # Publica RUNNING: com o estado derivado, uma pausa que tenha
            # chegado exatamente na virada do countdown NÃO é perdida —
            # `_phase` vira RUNNING, mas o estado público continua PAUSED
            # e a thread segue congelada em `_pause.wait()`.
            self._set(ExecState.RUNNING, "Desenhando…", run_id)
            for idx, stroke in enumerate(plan.strokes):
                if self._cancel.is_set():
                    self._set(ExecState.CANCELLED, "Execução cancelada.", run_id)
                    return
                self._pause.wait()  # bloqueia enquanto pausado
                if self._cancel.is_set():
                    self._set(ExecState.CANCELLED, "Execução cancelada.", run_id)
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
                    self._set(ExecState.CANCELLED, "Execução cancelada.", run_id)
                    return
                if stroke_delay > 0:
                    if not self._rest(stroke_delay):
                        self._set(ExecState.CANCELLED, "Execução cancelada.", run_id)
                        return
            self._set(ExecState.COMPLETED, "Desenho concluído.", run_id)
        except Exception as e:
            self._set(ExecState.ERROR, f"Erro na execução: {e}", run_id)

    # ------------------------------------------------------------------
    # Pausa / retomada / cancelamento
    # ------------------------------------------------------------------
    def pause(self) -> bool:
        """Pausa a contagem regressiva ou o desenho. Retorna se pausou.

        Não solta o botão do mouse: o executor congela entre segmentos
        com o botão pressionado, então o traço continua íntegro ao
        retomar (antes, o mouseUp aqui furava o traço em andamento).
        """
        with self._lock:
            if self._phase not in _ACTIVE_PHASES or self._paused:
                return False
            self._paused = True
        self._pause.clear()
        try:
            self.executor.pause_drawing()
        except Exception:
            pass
        # Republica (sem reescrever a fase): se a thread avançou para
        # RUNNING entre a checagem e aqui, reescrever a fase a faria
        # voltar para COUNTDOWN.
        self._publish("Pausado.")
        return True

    def resume(self) -> bool:
        """Retoma de onde pausou (countdown continua, desenho continua)."""
        with self._lock:
            if not self._paused:
                return False
            self._paused = False
        # Republica ANTES de liberar a pausa: liberando primeiro, a
        # thread pode acordar e publicar outro estado por cima deste.
        self._publish("Retomado.")
        self._pause.set()
        try:
            self.executor.resume_drawing()
        except Exception:
            pass
        return True

    def toggle_pause(self) -> bool:
        """Alterna pausa/retomada (usado pelo atalho de teclado).

        Sem isto, F10 pausava e não havia como retomar pelo teclado —
        e como a janela é minimizada para desenhar, a pausa virava uma
        via sem volta.
        """
        if self.state == ExecState.PAUSED:
            return self.resume()
        return self.pause()

    def cancel(self):
        with self._lock:
            busy = self._phase in _ACTIVE_PHASES
            self._paused = False
        if busy:
            self._cancel.set()
            self._pause.set()
            try:
                self.executor.resume_drawing()  # desbloqueia wait de pausa
            except Exception:
                pass
            self.executor.cancel()
            try:
                self.executor.backend.mouseUp(button="left")
            except Exception:
                pass
