"""Atalhos globais via pynput (com fallback se ausente).

Segurança de threads: o listener do pynput executa em uma thread própria
e NUNCA chama handlers da interface diretamente. Ele apenas traduz a tecla
para uma ação (`_key_to_action`) e emite `HotkeyBridge.action` (Qt Signal,
thread-safe). O slot `_dispatch`, que vive na thread que criou o
GlobalHotkeys (thread principal da UI), executa os handlers via conexão
enfileirada automática do Qt.
"""
from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger("auto_draw_studio.hotkeys")

# Modificadores reconhecidos (normalizados: "ctrl_l" → "ctrl").
_MODIFIER_KEYS = ("ctrl", "alt", "shift", "cmd")

_MODIFIER_ALIASES = {
    "ctrl_l": "ctrl", "ctrl_r": "ctrl", "control": "ctrl", "control_l": "ctrl",
    "control_r": "ctrl",
    "alt_l": "alt", "alt_r": "alt", "option": "alt",
    "shift_l": "shift", "shift_r": "shift",
    "cmd_l": "cmd", "cmd_r": "cmd", "win": "cmd", "super": "cmd",
    "meta": "cmd",
}


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
        # Teclas/modificadores atualmente pressionados (para detectar
        # auto-repeat e montar combinações como "ctrl+f9").
        self._pressed_keys: set[str] = set()
        self._pressed_mods: set[str] = set()

    # -- tradução tecla → ação (pura, testável sem Qt/OS) --
    def _normalize_key(self, key_name: str | None) -> str:
        """Normaliza nomes de tecla ('key.f9', 'F9', 'ctrl_l' → 'f9', 'ctrl')."""
        if key_name is None:
            return ""
        s = str(key_name).lower().replace("key.", "").strip()
        return _MODIFIER_ALIASES.get(s, s)

    def _key_to_action(self, key_name: str | None,
                       modifiers=None) -> str | None:
        """Traduz tecla (+ modificadores) para uma ação.

        Aceita atalhos simples ("f9") e combinações ("ctrl+f9").
        A combinação exata tem prioridade sobre a tecla simples.
        """
        name = self._normalize_key(key_name)
        if not name:
            return None
        mods = {self._normalize_key(m) for m in (modifiers or ())}
        mods = {m for m in mods if m in _MODIFIER_KEYS}
        # 1) combinação exata (ex.: "ctrl+f9")
        for action, hotkey in self.bindings.items():
            h = self._normalize_key(hotkey)
            if "+" not in h:
                continue
            parts = [p for p in h.split("+") if p]
            if not parts:
                continue
            if parts[-1] == name and set(parts[:-1]) == mods:
                return action
        # 2) tecla simples
        for action, hotkey in self.bindings.items():
            h = self._normalize_key(hotkey)
            if "+" in h:
                continue
            if h == name:
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
            # Antes a exceção era engolida em silêncio: o usuário apertava
            # F9 e nada acontecia, sem nenhum registro no log.
            log.exception("Falha no handler de atalho '%s'", action)
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
        self._pressed_keys.clear()
        self._pressed_mods.clear()
        try:
            from pynput import keyboard
        except Exception:
            return False
        bridge = self._get_bridge()

        def on_press(key):
            try:
                name = (getattr(key, "name", None) or getattr(key, "char", None)
                        or str(key))
            except Exception:
                return
            norm = self._normalize_key(name)
            if not norm:
                return
            if norm in _MODIFIER_KEYS:
                self._pressed_mods.add(norm)
                return
            # Ignora auto-repeat: segurar a tecla não deve re-disparar a
            # ação (antes, F9 segurado reiniciava o desenho várias vezes).
            if norm in self._pressed_keys:
                return
            self._pressed_keys.add(norm)
            action = self._key_to_action(norm, self._pressed_mods)
            if action is not None:
                try:
                    bridge.action.emit(action)  # thread-safe; handlers rodam na UI
                except Exception:
                    pass

        def on_release(key):
            try:
                name = (getattr(key, "name", None) or getattr(key, "char", None)
                        or str(key))
            except Exception:
                return
            norm = self._normalize_key(name)
            if norm in _MODIFIER_KEYS:
                self._pressed_mods.discard(norm)
            else:
                self._pressed_keys.discard(norm)

        try:
            try:
                self._listener = keyboard.Listener(on_press=on_press,
                                                   on_release=on_release)
            except TypeError:
                # Listener sem suporte a on_release (versões antigas / mocks).
                self._listener = keyboard.Listener(on_press=on_press)
            self._listener.start()
            return True
        except Exception:
            self._listener = None
            return False

    def stop(self):
        listener = self._listener
        self._listener = None
        if listener is None:
            return
        try:
            listener.stop()
        except Exception:
            pass
        # Libera o hook do SO de forma síncrona (senão o listener fica
        # vivo até o fim do interpretador).
        try:
            join = getattr(listener, "join", None)
            if callable(join):
                join(timeout=1)
        except Exception:
            pass

    @property
    def is_running(self) -> bool:
        return self._listener is not None
