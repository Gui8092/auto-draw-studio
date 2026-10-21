"""Regressão CORREÇÃO 2: hotkeys fora da thread da UI (Qt Signal)."""
import sys
import threading
import types

import pytest


def _install_fake_pynput(monkeypatch):
    """Listener falso que captura on_press sem tocar no SO."""
    created = []

    class FakeListener:
        def __init__(self, on_press=None):
            self.on_press = on_press
            self.started = False
            self.stopped = False
            created.append(self)

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    fake_keyboard = types.SimpleNamespace(Listener=FakeListener)
    fake_pynput = types.SimpleNamespace(keyboard=fake_keyboard)
    monkeypatch.setitem(sys.modules, "pynput", fake_pynput)
    monkeypatch.setitem(sys.modules, "pynput.keyboard", fake_keyboard)
    return created


def test_key_mapping_and_dispatch():
    from app.automation.hotkeys import GlobalHotkeys
    calls = []
    h = GlobalHotkeys(on_start=lambda: calls.append("start"),
                      on_cancel=lambda: calls.append("cancel"))
    h.bindings = {"start": "f9", "cancel": "esc"}
    assert h._key_to_action("f9") == "start"
    assert h._key_to_action("key.f9") == "start"
    assert h._key_to_action("F9") == "start"
    assert h._key_to_action("esc") == "cancel"
    assert h._key_to_action("x") is None
    assert h._key_to_action(None) is None
    assert h._dispatch("start") is True
    assert calls == ["start"]
    assert h._dispatch("pause") is False  # sem handler registrado


def test_start_stop_no_duplicates(monkeypatch):
    from app.automation.hotkeys import GlobalHotkeys
    created = _install_fake_pynput(monkeypatch)
    h = GlobalHotkeys(on_start=lambda: None)
    assert h.start({"start": "f9"}) is True
    assert h.is_running
    first = h._listener
    assert h.start({"start": "f9"}) is True  # reinicia: para o anterior
    assert first.stopped, "listener anterior deve ser parado ao reiniciar"
    assert len(created) == 2
    assert sum(1 for c in created if c.started and not c.stopped) == 1
    h.stop()
    assert not h.is_running
    h.stop()  # idempotente
    assert not h.is_running


def test_start_without_pynput(monkeypatch):
    from app.automation.hotkeys import GlobalHotkeys
    monkeypatch.setitem(sys.modules, "pynput", None)
    # força ImportError no `from pynput import keyboard`
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pynput":
            raise ImportError("sem pynput")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    h = GlobalHotkeys(on_start=lambda: None)
    assert h.start({"start": "f9"}) is False


def _ensure_qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_listener_thread_only_emits(monkeypatch):
    """on_press vindo de outra thread só emite o Signal, sem chamar handler."""
    _ensure_qapp()
    from PySide6.QtWidgets import QApplication
    from app.automation.hotkeys import GlobalHotkeys
    created = _install_fake_pynput(monkeypatch)
    calls = []
    h = GlobalHotkeys(on_start=lambda: calls.append("start"))
    h.start({"start": "f9"})
    listener = created[-1]

    bridge = h._get_bridge()
    # Desconecta o dispatch real: o teste observa apenas o que o listener
    # emite; a entrega ao handler já é coberta por test_key_mapping.
    try:
        bridge.action.disconnect(h._dispatch)
    except Exception:
        pass
    emitted = []
    bridge.action.connect(lambda a: emitted.append(a))

    class FakeKey:
        name = "f9"

    t = threading.Thread(target=lambda: listener.on_press(FakeKey()))
    t.start()
    t.join(timeout=5)
    # Loop local processa a entrega enfileirada vinda da outra thread.
    import time as _t
    deadline = _t.time() + 5
    while not emitted and _t.time() < deadline:
        QApplication.processEvents()
        _t.sleep(0.02)
    assert emitted == ["start"], "listener deve apenas emitir a ação"
    assert calls == [], "handler NÃO pode rodar na thread do listener"
    # Entrega na thread principal executa o handler
    h._dispatch(emitted[0])
    assert calls == ["start"]
