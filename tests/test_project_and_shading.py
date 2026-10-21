"""Fase 3: projeto (salvar/abrir), exportação SVG e sombreamento.

Cobre:
- `save_project`/`load_project` e `DrawingPlan.to_svg` existiam e eram
  testados, mas NUNCA foram ligados na interface;
- o perfil "equilibrado" precisa round-tripar com os campos novos;
- sombreamento (hachuras) integrado ao pipeline.
"""
import json
import os

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from app.core.pipeline import build_shaded_plan, process_to_plan
from app.core.quality_checker import rasterize_plan
from app.core.shading_planner import hatch_spacing_for, plan_hatch
from app.models.drawing_plan import DrawingPlan, Stroke, StrokeType
from app.models.settings import AppSettings, ProcessingSettings
from app.utils.persistence import load_project, save_project


def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _gradient(size=200, radius=70):
    g = np.full((size, size), 255, np.uint8)
    for r in range(radius, 0, -1):
        cv2.circle(g, (size // 2, size // 2), r, int(255 - r * 2.2), -1)
    return g


# ----------------------------------------------------------------------
# Sombreamento
# ----------------------------------------------------------------------
def test_mid_tone_region_becomes_hatch():
    """Região de tom médio → hachuras (não preenchimento chapado)."""
    s = ProcessingSettings(strategy="sombreado", threshold=180,
                           hatch_spacing=6, hatch_angle=45.0)
    mask, plan = process_to_plan(_gradient(), s)
    assert plan.strokes_by_kind(StrokeType.HATCH), \
        f"sem hachuras: {[st.kind.value for st in plan.strokes]}"
    assert not plan.strokes_by_kind(StrokeType.FILL)


def test_dark_region_becomes_fill():
    """Região escura → preenchimento sólido."""
    g = np.full((160, 160), 255, np.uint8)
    cv2.circle(g, (80, 80), 50, 40, -1)
    s = ProcessingSettings(strategy="sombreado", threshold=180)
    mask, plan = process_to_plan(g, s)
    assert plan.strokes_by_kind(StrokeType.FILL)
    assert not plan.strokes_by_kind(StrokeType.HATCH)


def test_thin_line_stays_centerline_in_shaded_mode():
    g = np.full((160, 160), 255, np.uint8)
    cv2.line(g, (20, 80), (140, 80), 60, 2)
    s = ProcessingSettings(strategy="sombreado", threshold=180)
    mask, plan = process_to_plan(g, s)
    assert plan.strokes_by_kind(StrokeType.CENTERLINE)


def test_hatch_stays_inside_the_region():
    """A hachura não pode vazar para fora da região."""
    g = np.full((160, 160), 255, np.uint8)
    cv2.circle(g, (80, 80), 50, 150, -1)   # tom médio
    s = ProcessingSettings(strategy="sombreado", threshold=180)
    mask, plan = process_to_plan(g, s)
    hatches = plan.strokes_by_kind(StrokeType.HATCH)
    assert hatches
    for st in hatches:
        for x, y in st.points:
            xi, yi = int(round(x)), int(round(y))
            if 0 <= xi < mask.shape[1] and 0 <= yi < mask.shape[0]:
                assert mask[yi, xi] == 255, "hachura fora da região"


def test_shaded_plan_warns_when_no_hatch_generated():
    """Limiar baixo → sem tons médios: o app avisa em vez de calar."""
    g = np.full((160, 160), 255, np.uint8)
    cv2.circle(g, (80, 80), 50, 30, -1)   # bem escuro
    s = ProcessingSettings(strategy="sombreado", threshold=128,
                           hatch_threshold=120)
    mask, plan = process_to_plan(g, s)
    assert not plan.strokes_by_kind(StrokeType.HATCH)
    assert any("hachura" in n.lower() for n in plan.strategy_notes), \
        f"faltou aviso: {plan.strategy_notes}"


def test_hatch_spacing_varies_with_tone():
    """Tom mais claro → hachura mais rala."""
    dark = hatch_spacing_for(40, 6, 0.5)
    light = hatch_spacing_for(220, 6, 0.5)
    assert light > dark, f"claro={light} escuro={dark}"
    assert hatch_spacing_for(220, 6, 1.0) < light, "densidade não afeta o tom"


def test_plan_hatch_respects_mask():
    g = np.full((80, 80), 255, np.uint8)
    cv2.circle(g, (40, 40), 25, 100, -1)
    mask = np.zeros((80, 80), np.uint8)
    cv2.circle(mask, (40, 40), 25, 255, -1)
    strokes = plan_hatch(g, mask, angle_deg=0.0, spacing=6, dark_thr=200)
    assert strokes
    for s in strokes:
        for x, y in s:
            assert mask[int(round(y)), int(round(x))] == 255


def test_shaded_mode_is_in_strategies():
    from app.core.strategy import STRATEGIES

    assert "sombreado" in STRATEGIES


def test_build_plan_without_tones_falls_back_to_auto():
    """`build_plan` não recebe tons: 'sombreado' cai no 'auto'."""
    from app.core.pipeline import build_plan

    m = np.zeros((80, 80), np.uint8)
    m[20:60, 20:60] = 255
    plan = build_plan(m, ProcessingSettings(strategy="sombreado"))
    assert plan.strokes_by_kind(StrokeType.FILL)


# ----------------------------------------------------------------------
# Projeto
# ----------------------------------------------------------------------
def test_save_and_load_project_round_trip(tmp_path):
    p = tmp_path / "projeto.ads.json"
    settings = AppSettings()
    settings.processing.threshold = 210
    plan = DrawingPlan(strokes=[Stroke(points=[(0.0, 0.0), (5.0, 5.0)],
                                        kind=StrokeType.FILL)],
                       image_width=10, image_height=10,
                       strategy_notes=["nota de teste"])
    save_project(p, "C:/imagens/foto.png", settings, plan.to_dict())

    data = load_project(p)
    assert data["image_path"] == "C:/imagens/foto.png"
    back = AppSettings.from_dict(data["settings"])
    assert back.processing.threshold == 210
    restored = DrawingPlan.from_dict(data["plan"])
    assert restored.total_strokes == 1
    assert restored.strategy_notes == ["nota de teste"]


def test_load_project_rejects_invalid_file(tmp_path):
    p = tmp_path / "ruim.ads.json"
    p.write_text("{ nao é json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_project(p)
    p.write_text(json.dumps({"sem": "image_path"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_project(p)


def test_main_window_can_save_and_open_project(make_window, tmp_path,
                                                monkeypatch):
    """A interface realmente usa salvar/abrir projeto."""
    _ensure_qapp()
    import app.ui.main_window as mw_mod

    # Imagem real em disco: o projeto guarda o caminho, e ao reabrir o
    # plano só é restaurado se a imagem bater (dimensões).
    img_file = tmp_path / "origem.png"
    g = np.full((80, 80), 255, np.uint8)
    g[20:60, 20:60] = 0
    cv2.imwrite(str(img_file), g)

    w = make_window()
    w.gray = g
    w.rgb = np.stack([g] * 3, -1)
    w.image_path = str(img_file)
    w.reprocess()
    import time as _t
    deadline = _t.time() + 10
    while w.plan is None and _t.time() < deadline:
        QApplication.processEvents()
        _t.sleep(0.02)
    assert w.plan is not None and w.plan.total_strokes

    target = tmp_path / "p.ads.json"
    monkeypatch.setattr(mw_mod.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "")))
    w.save_project()
    assert target.exists(), "projeto não foi salvo"

    # Abre de volta: o plano deve ser restaurado.
    w2 = make_window()
    monkeypatch.setattr(mw_mod.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(target), "")))
    w2.open_project()
    assert w2.plan is not None and w2.plan.total_strokes, \
        "trajetórias não foram restauradas"


def test_saved_project_records_current_settings(make_window, tmp_path,
                                                 monkeypatch):
    """O projeto grava os ajustes ATUAIS (não os padrões)."""
    _ensure_qapp()
    import app.ui.main_window as mw_mod

    w = make_window()
    m = np.zeros((60, 60), np.uint8)
    m[15:45, 15:45] = 255
    from app.core.pipeline import build_plan

    w.plan = build_plan(m, ProcessingSettings(strategy="contour"))
    w.panel.threshold.setValue(210)
    target = tmp_path / "p.ads.json"
    monkeypatch.setattr(mw_mod.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "")))
    w.save_project()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["settings"]["processing"]["threshold"] == 210


def test_export_svg_writes_file(make_window, tmp_path, monkeypatch):
    _ensure_qapp()
    import app.ui.main_window as mw_mod

    w = make_window()
    m = np.zeros((60, 60), np.uint8)
    m[15:45, 15:45] = 255
    from app.core.pipeline import build_plan

    w.plan = build_plan(m, ProcessingSettings(strategy="contour"))
    target = tmp_path / "traj.svg"
    monkeypatch.setattr(mw_mod.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "")))
    w.export_svg()
    assert target.exists()
    svg = target.read_text(encoding="utf-8")
    assert "<svg" in svg and "<path" in svg


# ----------------------------------------------------------------------
# Perfis com os campos novos
# ----------------------------------------------------------------------
def test_equilibrado_profile_covers_new_fields():
    from app.core.strategy import apply_profile

    base = ProcessingSettings()
    eq = apply_profile(base, "equilibrado")
    assert eq == base, "perfil 'equilibrado' não cobre todos os campos"
    assert eq.hatch_spacing == base.hatch_spacing
    assert eq.shading_intensity == base.shading_intensity


def test_panel_round_trips_new_fields():
    _ensure_qapp()
    from app.ui.settings_panel import SettingsPanel

    p = SettingsPanel()
    p.hatch_spacing.setValue(9)
    p.hatch_angle.setValue(30)
    p.hatch_threshold.setValue(150)
    p.shading_intensity.setValue(70)
    vals = p.values()
    assert vals.hatch_spacing == 9
    assert vals.hatch_angle == 30
    assert vals.hatch_threshold == 150
    assert vals.shading_intensity == pytest.approx(0.7)
