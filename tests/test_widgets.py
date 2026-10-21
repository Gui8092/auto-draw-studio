"""Fase A: sliders exibem valores formatados e acompanham presets/reset."""
from PySide6.QtWidgets import QApplication


def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_labeled_slider_formats_and_emits():
    _ensure_qapp()
    from app.ui.widgets import LabeledSlider
    got = []
    sl = LabeledSlider(0, 100, 50, fmt=lambda v: f"{v} px")
    sl.valueChanged.connect(got.append)
    assert sl.label.text() == "50 px"
    sl.setValue(75)
    assert sl.label.text() == "75 px"
    assert got == [75]
    assert sl.value() == 75


def test_panel_labels_track_values_presets_and_reset():
    _ensure_qapp()
    from app.ui.settings_panel import SettingsPanel
    p = SettingsPanel()
    assert p.threshold.label.text() == "128"
    assert p.contrast.label.text() == "×1.00"
    assert p.fill_spacing.label.text() == "4 px"
    p.profile.setCurrentText("rapido")
    assert p.fill_spacing.label.text() == "6 px"
    assert p.profile.currentText() == "rapido"
    p.threshold.setValue(200)
    assert p.threshold.label.text() == "200"
    assert p.profile.currentText() == "Personalizado"
    p.reset_defaults()
    assert p.threshold.label.text() == "128"
    assert p.profile.currentText() == "equilibrado"


def test_path_preview_zoom_filters_and_travel():
    _ensure_qapp()
    import numpy as np
    from app.core.pipeline import build_plan
    from app.models.drawing_plan import StrokeType
    from app.models.settings import ProcessingSettings
    from app.ui.path_preview import PathPreview
    m = np.zeros((80, 80), np.uint8)
    m[10:70, 10:70] = 255
    plan = build_plan(m, ProcessingSettings(fill_spacing=4))
    v = PathPreview()
    v.set_plan(plan)
    v.resize(300, 300)
    v.show()
    assert v.grab().isNull() is False
    # zoom altera a escala interna
    s0 = v._view()[0]
    v._zoom = 2.0
    assert v._view()[0] == s0 * 2.0
    assert v.grab().isNull() is False
    # filtro por tipo não quebra a renderização
    v.set_kind_visible(StrokeType.FILL, False)
    assert v.visible[StrokeType.FILL] is False
    assert v.grab().isNull() is False
    v.set_kind_visible(StrokeType.FILL, True)
    v.set_show_travel(False)
    assert v.grab().isNull() is False
    v.reset_view()
    assert v._zoom == 1.0 and v._pan == [0.0, 0.0]
    v.close()


def test_layout_persists_geometry_and_splitter(make_window):
    _ensure_qapp()
    from PySide6.QtWidgets import QApplication
    w = make_window()
    w.show()
    w.resize(1400, 900)
    QApplication.processEvents()
    w.splitter.setSizes([900, 500])
    QApplication.processEvents()
    saved_sizes = list(w.splitter.sizes())  # valor efetivo após layout
    w._save_layout()
    w2 = make_window()
    w2.show()
    w2.resize(1400, 900)
    QApplication.processEvents()
    w2._restore_layout()
    QApplication.processEvents()
    assert list(w2.splitter.sizes()) == saved_sizes or abs(
        w2.splitter.sizes()[0] / max(1, w2.splitter.sizes()[1])
        - saved_sizes[0] / max(1, saved_sizes[1])) < 0.05, \
        "proporção do divisor não foi restaurada"
    assert saved_sizes[0] > saved_sizes[1] > 0  # proporção 900:500 preservada
    # Geometria persistida no QSettings e restaurável
    assert bytes(w._app_settings().value("geometry")) != b""
    assert w._app_settings().value("splitter") is not None
    assert bool(w2.restoreGeometry(w._app_settings().value("geometry")))


def test_window_is_compact_and_resizable(make_window):
    """Janela encolhe (regressão: mínimo travado em ~2020px)."""
    from PySide6.QtWidgets import QApplication
    w = make_window()
    w.show()
    QApplication.processEvents()
    assert w.minimumWidth() < 1500, f"largura mínima gigante: {w.minimumWidth()}"
    w.resize(900, 620)
    QApplication.processEvents()
    assert w.width() < 1500, "redimensionar é ignorado"


def test_fullscreen_survives_completion(make_window):
    """Término não tira o usuário da tela cheia (só restaura se minimizamos)."""
    from PySide6.QtWidgets import QApplication
    w = make_window()
    w.show()
    w.showFullScreen()
    QApplication.processEvents()
    w._on_state("completed")
    QApplication.processEvents()
    assert w.isFullScreen()
    # ...mas restaura quando fomos nós que minimizamos para desenhar
    w.showNormal()
    QApplication.processEvents()
    w.minimize_for_draw()
    QApplication.processEvents()
    w._on_state("completed")
    QApplication.processEvents()
    assert not w._auto_minimized
