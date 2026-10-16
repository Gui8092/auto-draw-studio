"""Atalhos globais via pynput (com fallback se ausente).

Segurança de threads: o listener do pynput executa em uma thread própria
e NUNCA chama handlers da interface diretamente. Ele apenas traduz a tecla
para uma ação (`_key_to_action`) e emite `HotkeyBridge.action` (Qt Signal,
thread-safe). O slot `_dispatch`, que vive na thread que criou o
GlobalHotkeys (thread principal da UI), executa os handlers via conexão
enfileirada automática do Qt.
"""
from __future__ import annotations

from typing import Callable


class GlobalHotkeys:
    """Registra atalhos de teclado globais. Requer pynput instalado."""

    def __init__(self, on_start=None, on_pause=None, on_resume=None, on_cancel=None):
        self.handlers: dict[str, Callable] = {}
        if on_start:
            self.handlers["start"] = on_start
        if on_pause:
            self.handlers["pause"] = on_pause
        if on_resume:
            self.handlers["resume"] = on_resume
        if on_cancel:
            self.handlers["cancel"] = on_cancel
        self._listener = None
        self.bindings: dict[str, str] = {}
        self._bridge = None

    # -- tradução tecla → ação (pura, testável sem Qt/OS) --
    def _key_to_action(self, key_name: str | None) -> str | None:
        if not key_name:
            return None
        name = str(key_name).lower().replace("key.", "")
        for action, hotkey in self.bindings.items():
            if str(hotkey).lower() == name and action in self.handlers:
                return action
        return None

    def _dispatch(self, action: str):
        """Executa o handler na thread do receptor (slot Qt / chamada direta)."""
        handler = self.handlers.get(action)
        if handler is None:
            return False
        try:
            handler()
        except Exception:
            pass
        return True

    def _get_bridge(self):
        """Cria sob demanda o bridge Qt (evita importar PySide6 fora da UI)."""
        if self._bridge is None:
            from PySide6.QtCore import QObject, Signal

            class _Bridge(QObject):
                action = Signal(str)

            bridge = _Bridge()
            # Conexão Auto: vinda da thread do listener, o Qt enfileira
            # para a thread do bridge (principal). Sem event loop (testes),
            # o teste pode chamar _dispatch diretamente.
            bridge.action.connect(self._dispatch)
            self._bridge = bridge
        return self._bridge

    def start(self, bindings: dict[str, str] | None = None):
        # Evita listeners duplicados após reinicializações.
        self.stop()
        self.bindings = dict(bindings or {})
        try:
            from pynput import keyboard
        except Exception:
            return False
        bridge = self._get_bridge()

        def on_press(key):
            try:
                name = getattr(key, "name", None) or getattr(key, "char", None) or str(key)
            except Exception:
                return
            action = self._key_to_action(name)
            if action is not None:
                try:
                    bridge.action.emit(action)  # thread-safe; handlers rodam na UI
                except Exception:
                    pass

        try:
            self._listener = keyboard.Listener(on_press=on_press)
            self._listener.start()
            return True
        except Exception:
            self._listener = None
            return False

    def stop(self):
        try:
            if self._listener is not None:
                self._listener.stop()
        except Exception:
            pass
        self._listener = None

    @property
    def is_running(self) -> bool:
        return self._listener is not None
