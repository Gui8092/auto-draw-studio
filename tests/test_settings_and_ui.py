"""Regressões da Fase 2: configuração e consistência da interface.

Cobre os bugs:
- o config de processamento salvo nunca voltava ao painel (e era
  sobrescrito pelos padrões no "Salvar cfg");
- `values()` descartava `max_work_size`/`morph_kernel`;
- o perfil "equilibrado" era um no-op (mentia no rótulo);
- o rótulo do perfil nunca detectava "bate com um preset conhecido";
- os botões de pausa/retomar/cancelar nunca eram habilitados por estado;
- sem PyAutoGUI o app "desenhava" com um backend inerte e reportava
  sucesso (e o aviso era engolido);
- o overlay do seletor não cobria os outros monitores;
- o log crescia sem limite;
- a ETA era calculada em px de imagem (executor anda em px de tela);
- um erro no traço gerava dois `mouseUp`.
"""
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from app.models.drawing_plan import DrawingPlan, Stroke, StrokeType
from app.models.settings import AppSettings, ProcessingSettings
from app.automation.mouse_executor import MockBackend, MouseExecutor


def _plan(n=2):
    return DrawingPlan(
        strokes=[Stroke(points=[(float(i * 10), 0.0), (float(i * 10 + 5), 0.0)],
                        kind=StrokeType.FILL) for i in range(n)],
        image_width=100, image_height=100)


def _mapper():
    from app.automation.coordinate_mapper import CoordinateMapper
    from app.automation.screen_calibration import ScreenArea

    return CoordinateMapper(100, 100, ScreenArea(0, 0, 200, 200))


def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ----------------------------------------------------------------------
# 2.1 / 2.2 — round-trip da configuração
# ----------------------------------------------------------------------
def test_saved_processing_settings_are_restored_to_panel(make_window,
                                                          monkeypatch):
    """O config salvo tem que VOLTAR para o painel."""
    _ensure_qapp()
    import app.ui.main_window as mw_mod

    saved = AppSettings()
    saved.processing.threshold = 200
    saved.processing.method = "otsu"
    saved.processing.invert = True
    saved.processing.fill_spacing = 7
    saved.processing.max_work_size = 1024
    saved.processing.morph_kernel = 5
    saved.processing.thin_line_px = 6.0
    monkeypatch.setattr(mw_mod, "load_settings", lambda: saved)

    w = make_window()
    vals = w.panel.values()
    assert vals.threshold == 200
    assert vals.method == "otsu"
    assert vals.invert is True
    assert vals.fill_spacing == 7
    assert vals.max_work_size == 1024
    assert vals.morph_kernel == 5
    assert vals.thin_line_px == 6.0


def test_save_cfg_keeps_processing_values(make_window, monkeypatch):
    """'Salvar cfg' não pode sobrescrever o config com os padrões."""
    _ensure_qapp()
    import app.ui.main_window as mw_mod

    saved = []
    monkeypatch.setattr(mw_mod, "save_settings", lambda s: saved.append(s))
    w = make_window()
    w.panel.threshold.setValue(210)
    w.save_cfg()
    assert saved, "config não foi salvo"
    assert saved[-1].processing.threshold == 210
    assert saved[-1].processing.method == w.panel.values().method


def test_values_keeps_every_controlled_field():
    """`values()` não pode descartar campos do ProcessingSettings."""
    _ensure_qapp()
    from app.ui.settings_panel import SettingsPanel

    p = SettingsPanel()
    vals = p.values()
    for field in ("threshold", "method", "brightness", "contrast", "gamma",
                  "denoise", "invert", "morph_op", "morph_kernel",
                  "min_detail_area", "fill_spacing", "thin_line_px",
                  "simplify_epsilon", "strategy", "max_work_size"):
        assert hasattr(vals, field), f"campo {field} ausente"
    assert vals.max_work_size == 512
    assert vals.morph_kernel == 3


def test_work_size_control_reaches_the_loader():
    """A resolução de trabalho configurada é usada ao carregar a imagem."""
    _ensure_qapp()
    from app.ui.settings_panel import SettingsPanel

    p = SettingsPanel()
    p.work_size.setCurrentText("1024")
    assert p.values().max_work_size == 1024


# ----------------------------------------------------------------------
# 2.3 / 2.4 / 2.5 — perfil
# ----------------------------------------------------------------------
def test_equilibrado_profile_restores_defaults():
    """'equilibrado' era um dict VAZIO: não restaurava nada."""
    _ensure_qapp()
    from app.ui.settings_panel import SettingsPanel

    p = SettingsPanel()
    p.threshold.setValue(30)
    p.fill_spacing.setValue(9)
    p.profile.setCurrentText("equilibrado")
    assert p.values().threshold == ProcessingSettings().threshold
    assert p.values().fill_spacing == ProcessingSettings().fill_spacing
    assert p.profile.currentText() == "equilibrado"


def test_profile_label_detects_matching_preset():
    """Os valores que batem com um preset conhecido mostram o nome dele."""
    _ensure_qapp()
    from app.core.strategy import apply_profile
    from app.ui.settings_panel import SettingsPanel

    p = SettingsPanel()
    rapido = apply_profile(ProcessingSettings(), "rapido")
    p.set_values(rapido)
    assert p.profile.currentText() == "rapido", \
        f"rótulo={p.profile.currentText()} (esperado 'rapido')"


def test_profile_label_custom_when_values_differ():
    _ensure_qapp()
    from app.ui.settings_panel import SettingsPanel

    p = SettingsPanel()
    p.threshold.setValue(200)
    assert p.profile.currentText() == "Personalizado"


def test_reset_defaults_unlocks_panel():
    """`_lock` não pode ficar preso: o painel pararia de reprocessar."""
    _ensure_qapp()
    from app.ui.settings_panel import SettingsPanel

    p = SettingsPanel()
    p.reset_defaults()
    assert p._lock is False
    changed = []
    p.settings_changed.connect(lambda: changed.append(1))
    p.threshold.setValue(77)
    assert changed, "painel não emitiu settings_changed (lock preso?)"
    assert p.values().threshold == 77


def test_set_values_does_not_emit_change():
    _ensure_qapp()
    from app.ui.settings_panel import SettingsPanel

    p = SettingsPanel()
    changed = []
    p.settings_changed.connect(lambda: changed.append(1))
    p.set_values(ProcessingSettings())
    assert changed == [], "set_values não deve disparar reprocessamento"


# ----------------------------------------------------------------------
# 2.6 — botões refletem o estado
# ----------------------------------------------------------------------
def test_execution_buttons_follow_state(make_window):
    _ensure_qapp()
    from app.automation.execution_controller import ExecState

    w = make_window()
    w._refresh_ready()
    assert not w.btn_pause.isEnabled(), "pausar deve ficar desabilitado em READY"
    assert not w.btn_resume.isEnabled()
    assert not w.btn_cancel.isEnabled()

    w._on_state("running")
    assert w.btn_pause.isEnabled()
    assert not w.btn_resume.isEnabled()
    assert w.btn_cancel.isEnabled()

    w._on_state("paused")
    assert not w.btn_pause.isEnabled()
    assert w.btn_resume.isEnabled()
    assert w.btn_cancel.isEnabled()

    w._on_state("completed")
    assert not w.btn_pause.isEnabled()
    assert not w.btn_resume.isEnabled()
    assert not w.btn_cancel.isEnabled()


# ----------------------------------------------------------------------
# 2.7 — backend real
# ----------------------------------------------------------------------
def test_mock_backend_does_not_report_success(make_window, monkeypatch):
    """Sem PyAutoGUI, o app avisa em vez de 'desenhar' e dizer que ok."""
    _ensure_qapp()
    import app.ui.main_window as mw_mod

    class NoBackend:
        def __init__(self):
            raise RuntimeError("sem pyautogui")

    monkeypatch.setattr(mw_mod, "PyAutoGuiBackend", NoBackend)
    w = make_window()
    assert w._real_backend is False
    log_text = w.log_view.toPlainText()
    assert "PyAutoGUI" in log_text, \
        f"aviso de PyAutoGUI ausente no log: {log_text[-200:]!r}"


# ----------------------------------------------------------------------
# 2.8 — overlay multi-monitor
# ----------------------------------------------------------------------
def test_canvas_selector_covers_union_of_screens():
    """O overlay precisa cobrir TODOS os monitores."""
    _ensure_qapp()
    from PySide6.QtWidgets import QApplication as _A

    from app.ui.canvas_selector import CanvasSelector

    sel = CanvasSelector()
    sel.start()
    union = None
    for scr in _A.screens():
        g = scr.geometry()
        union = g if union is None else union.united(g)
    assert sel.geometry() == union, \
        f"overlay={sel.geometry()} esperado={union}"
    sel.close()


# ----------------------------------------------------------------------
# 2.9 — log limitado
# ----------------------------------------------------------------------
def test_log_view_has_block_limit(make_window):
    _ensure_qapp()
    w = make_window()
    assert w.log_view.document().maximumBlockCount() > 0, \
        "log sem teto de blocos"


# ----------------------------------------------------------------------
# 2.10 — ETA em px de tela
# ----------------------------------------------------------------------
def test_estimate_duration_scales_to_screen():
    """A ETA é em px de TELA: sem o fator de escala, errava por ~2x."""
    plan = DrawingPlan(strokes=[Stroke(points=[(0.0, 0.0), (200.0, 0.0)],
                                        kind=StrokeType.FILL)])
    d1 = plan.estimate_duration(1000.0, 0.0, scale=1.0)
    d2 = plan.estimate_duration(1000.0, 0.0, scale=2.0)
    assert d1 == pytest.approx(0.2, abs=1e-6)
    assert d2 == pytest.approx(0.4, abs=1e-6)


def test_fit_scale_matches_mapper():
    from app.automation.coordinate_mapper import CoordinateMapper
    from app.automation.screen_calibration import ScreenArea, fit_scale

    area = ScreenArea(0, 0, 1080, 1080)
    m = CoordinateMapper(512, 512, area)
    assert fit_scale(area, 512, 512) == pytest.approx(m.sx)


# ----------------------------------------------------------------------
# 2.11 — um único mouseUp
# ----------------------------------------------------------------------
def test_single_mouse_up_on_backend_error():
    """Erro depois do mouseDown não pode soltar o botão duas vezes."""
    from app.automation.mouse_executor import MockBackend, MouseExecutor

    class ExplodingBackend(MockBackend):
        def moveTo(self, x, y, duration=0):
            super().moveTo(x, y, duration=duration)
            if len(self.calls) > 2:
                raise RuntimeError("falha no driver")

    backend = ExplodingBackend()
    ex = MouseExecutor(backend=backend)
    with pytest.raises(RuntimeError):
        ex.draw_stroke([(0, 0), (5, 5), (10, 10)])
    ups = [c for c in backend.calls if c[0] == "mouseUp"]
    assert len(ups) == 1, f"mouseUp chamado {len(ups)}x (deveria ser 1x)"


# ----------------------------------------------------------------------
# Regressões da revisão
# ----------------------------------------------------------------------
def test_brush_control_takes_effect_immediately(make_window):
    """O controle do pincel vale na hora (antes só depois de salvar)."""
    _ensure_qapp()
    from app.models.drawing_plan import DrawingPlan

    w = make_window()
    plan = DrawingPlan(strokes=[], image_width=10, image_height=10,
                       spacing_px=4.0)
    assert w._effective_brush_px(plan) == 2      # heurística (4/2)
    w.spin_brush.setValue(7)
    assert w._effective_brush_px(plan) == 7, \
        "o controle do pincel só valia depois de 'Salvar cfg'"


def test_simplify_with_zero_epsilon_keeps_valid_strokes():
    """Com epsilon 0, traços inválidos ainda são removidos.

    Sem o filtro antes do retorno, um traço com 1 ponto sobrevivia e o
    `order_plan` levantava IndexError (o slider chega a 0).
    """
    from app.core.path_optimizer import order_plan, simplify_plan
    from app.models.drawing_plan import DrawingPlan, Stroke

    plan = DrawingPlan(strokes=[Stroke(points=[(0.0, 0.0), (5.0, 5.0)]),
                                Stroke(points=[(1.0, 1.0)])])
    simplify_plan(plan, 0.0)
    assert all(len(s.points) >= 2 for s in plan.strokes)
    order_plan(plan)   # não pode levantar IndexError


def test_set_values_clamps_unknown_combo_values():
    """Valor fora das opções do combo é aproximado, não perdido."""
    _ensure_qapp()
    from app.ui.settings_panel import SettingsPanel

    p = SettingsPanel()
    s = ProcessingSettings()
    s.max_work_size = 1000          # não existe no combo
    p.set_values(s)
    assert p.values().max_work_size in (256, 512, 1024, 1536, 2048)
    # e o valor continua utilizável (não volta ao padrão sem querer)
    assert p.values().max_work_size == 1024


def test_pause_does_not_move_phase_backwards():
    """`pause()` não pode reescrever a fase (ex.: voltar a COUNTDOWN)."""
    import time as _time

    from app.automation.execution_controller import (ExecState,
                                                     ExecutionController)

    ctl = ExecutionController(executor=MouseExecutor(backend=MockBackend()),
                              sleep_fn=lambda s: _time.sleep(0.02))
    ctl.countdown_seconds = 1
    ctl.start(_plan(2), _mapper(), stroke_delay=0)
    assert ctl.state == ExecState.COUNTDOWN
    # A thread avançou para RUNNING.
    ctl._set(ExecState.RUNNING, "Desenhando…", ctl._active_run)
    ctl.pause()
    assert ctl.state == ExecState.PAUSED
    # A fase interna continua RUNNING (não voltou a COUNTDOWN).
    assert ctl._phase == ExecState.RUNNING
    assert ctl.resume() is True
    assert ctl.state == ExecState.RUNNING
    ctl.cancel()
    ctl.wait_finished(timeout=10)
