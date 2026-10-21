"""Hotfix: rótulo do perfil acompanha os controles (nunca desatualizado)."""
from PySide6.QtWidgets import QApplication


def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _panel():
    _ensure_qapp()
    from app.ui.settings_panel import SettingsPanel
    return SettingsPanel()


def test_apply_preset_shows_name_and_values():
    p = _panel()
    p.profile.setCurrentText("rapido")
    assert p.profile.currentText() == "rapido"
    assert p.fill_spacing.value() == 6
    assert p.values().fill_spacing == 6


def test_manual_change_marks_custom():
    p = _panel()
    assert p.profile.currentText() == "equilibrado"
    p.threshold.setValue(200)
    assert p.profile.currentText() == "Personalizado"
    # A lógica usa os controles, não o nome antigo
    assert p.values().threshold == 200


def test_manual_strategy_change_marks_custom():
    p = _panel()
    p.strategy.setCurrentText("contour")
    assert p.profile.currentText() == "Personalizado"
    assert p.values().strategy == "contour"


def test_reset_restores_coherent_label():
    p = _panel()
    p.profile.setCurrentText("rapido")
    p.threshold.setValue(10)
    assert p.profile.currentText() == "Personalizado"
    p.reset_defaults()
    assert p.profile.currentText() == "equilibrado"
    assert p.values().fill_spacing == 4


def test_selecting_custom_label_changes_nothing():
    p = _panel()
    p.profile.setCurrentText("rapido")
    before = (p.fill_spacing.value(), p.threshold.value(), p.method.currentText())
    p.profile.setCurrentText("Personalizado")  # seleção manual do neutro
    after = (p.fill_spacing.value(), p.threshold.value(), p.method.currentText())
    assert before == after, "rótulo neutro não pode reconfigurar controles"
