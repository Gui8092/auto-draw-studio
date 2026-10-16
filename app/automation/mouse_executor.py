"""Executor do mouse com backend injetável (testável com mock)."""
from __future__ import annotations

from typing import Protocol


class MouseBackend(Protocol):
    def moveTo(self, x: int, y: int, duration: float = 0): ...
    def mouseDown(self, button: str = "left"): ...
    def mouseUp(self, button: str = "left"): ...


class PyAutoGuiBackend:
    """Backend real. FAILSAFE do PyAutoGUI permanece habilitado."""

    def __init__(self):
        import pyautogui

        pyautogui.FAILSAFE = True
        # PAUSE global (0,1 s após CADA chamada) impediria qualquer controle
        # de velocidade: o ritmo passaria a ser ditado por essa pausa fixa.
        # Zerar é seguro aqui porque o ritmo é governado por `duration` +
        # `stroke_delay`, e o mecanismo de emergência (failsafe) continua ativo.
        pyautogui.PAUSE = 0
        self._pg = pyautogui

    def moveTo(self, x: int, y: int, duration: float = 0):
        self._pg.moveTo(x, y, duration=duration)

    def mouseDown(self, button: str = "left"):
        self._pg.mouseDown(button=button)

    def mouseUp(self, button: str = "left"):
        self._pg.mouseUp(button=button)


class MockBackend:
    """Backend de teste: registra chamadas sem mover o mouse."""

    def __init__(self):
        self.calls: list[tuple] = []

    def moveTo(self, x: int, y: int, duration: float = 0):
        self.calls.append(("moveTo", x, y, duration))

    def mouseDown(self, button: str = "left"):
        self.calls.append(("mouseDown", button))

    def mouseUp(self, button: str = "left"):
        self.calls.append(("mouseUp", button))


class MouseExecutor:
    def __init__(self, backend: MouseBackend | None = None,
                 move_duration: float = 0.0,
                 move_speed_px_s: float | None = None):
        self.backend = backend or MockBackend()
        self.move_duration = move_duration
        self.move_speed_px_s = move_speed_px_s
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def prepare(self):
        """Prepara para uma nova execução (limpa um cancelamento anterior)."""
        self._cancelled = False

    def set_move_speed(self, px_per_s: float | None):
        """Define a velocidade de desenho (px/s). None/<=0 = duration fixo."""
        self.move_speed_px_s = px_per_s

    def _segment_duration(self, x0: int, y0: int, x1: int, y1: int) -> float:
        import math
        if self.move_speed_px_s and self.move_speed_px_s > 0:
            return math.hypot(x1 - x0, y1 - y0) / self.move_speed_px_s
        return self.move_duration

    def draw_stroke(self, screen_points: list[tuple[int, int]]) -> bool:
        """Desenha um traço: move→down→percorre→up. Retorna False se cancelado."""
        if not screen_points:
            return True
        if self._cancelled:
            return False
        try:
            x0, y0 = screen_points[0]
            self.backend.moveTo(x0, y0, duration=self.move_duration)
            if self._cancelled:
                return False
            self.backend.mouseDown(button="left")
            try:
                px, py = x0, y0
                for x, y in screen_points[1:]:
                    if self._cancelled:
                        break
                    self.backend.moveTo(
                        x, y,
                        duration=self._segment_duration(px, py, x, y))
                    px, py = x, y
            finally:
                self.backend.mouseUp(button="left")
        except Exception:
            try:
                self.backend.mouseUp(button="left")
            except Exception:
                pass
            raise
        return not self._cancelled
