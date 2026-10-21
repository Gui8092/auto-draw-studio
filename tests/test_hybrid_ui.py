"""Fases C/D/E: perda de detalhes, métricas, worker, gating e travel."""
import logging
import time

import cv2
import numpy as np
from PySide6.QtWidgets import QApplication

from app.core.pipeline import build_plan
from app.core.quality_checker import (check_quality, contour_chamfer,
                                      detect_detail_loss, mask_iou,
                                      rasterize_plan)
from app.models.drawing_plan import DrawingPlan, Stroke, StrokeType
from app.models.settings import ProcessingSettings


def _ensure_qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_detail_loss_warns_and_quiet_when_ok():
    gray = np.full((60, 60), 255, np.uint8)
    gray[30, 5:55] = 20  # linha escura fina
    mask = np.full((60, 60), 0, np.uint8)  # binarização apagou tudo
    warns = detect_detail_loss(gray, mask)
    assert warns and "limiar" in warns[0]
    mask2 = np.full((60, 60), 0, np.uint8)
    mask2[29:32, 5:55] = 255  # detalhe preservado
    assert detect_detail_loss(gray, mask2) == []
    assert detect_detail_loss(np.full((10, 10), 255, np.uint8),
                              np.zeros((10, 10), np.uint8)) == []


def test_quality_includes_detail_warnings():
    gray = np.full((60, 60), 255, np.uint8)
    gray[30, 5:55] = 20
    mask = np.zeros((60, 60), np.uint8)
    mask[10:20, 10:20] = 255
    plan = build_plan(mask, ProcessingSettings(fill_spacing=4))
    rep = check_quality(plan, mask, gray=gray)
    assert any("finos" in w for w in rep.warnings)


def test_iou_and_chamfer_sanity():
    a = np.zeros((40, 40), np.uint8)
    a[10:30, 10:30] = 255
    assert mask_iou(a, a) == 1.0
    assert contour_chamfer(a, a) == 0.0
    b = np.zeros((40, 40), np.uint8)
    b[12:30, 10:30] = 255  # deslocada 2px
    assert 0.7 < mask_iou(a, b) < 1.0
    assert 0.0 < contour_chamfer(a, b) < 3.0


def _wait(cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def test_worker_processes_async_and_discards_stale(make_window):
    _ensure_qapp()
    w = make_window()
    assert not w.btn_start.isEnabled(), "iniciar deve nascer desabilitado"
    w.gray = (np.random.default_rng(0).integers(0, 255, (80, 80))).astype(np.uint8)
    w.reprocess()
    ok = _wait(lambda: w.plan is not None, timeout=15.0)
    assert ok, "worker não entregou o plano"
    assert w.mask is not None
    # Geração obsoleta é descartada sem tocar na UI
    old_plan, old_mask = w.plan, w.mask
    w._proc_gen += 1  # simula pedido mais novo em voo
    w._on_processed(w._proc_gen - 1, np.zeros((5, 5), np.uint8),
                    DrawingPlan(strokes=[], image_width=5, image_height=5),
                    type("R", (), {"warnings": [], "coverage": 0.0})())
    assert w.plan is old_plan and w.mask is old_mask


def test_start_gating_with_area_and_plan(make_window):
    _ensure_qapp()
    from app.automation.screen_calibration import ScreenArea
    w = make_window()
    gray = np.full((60, 60), 200, np.uint8)
    gray[10:50, 10:50] = 30  # região escura → máscara com tinta
    w.gray = gray
    w.reprocess()
    assert _wait(lambda: w.plan is not None, timeout=15.0)
    assert not w.btn_start.isEnabled(), "sem área, iniciar continua desabilitado"
    w._on_area_selected(ScreenArea(0, 0, 300, 300))
    assert w.btn_start.isEnabled(), "plano+área devem habilitar iniciar"
    assert w.step_badges[3].objectName() == "stepActive"
    assert len(w.step_badges) == 5


def test_travel_overlay_renders():
    _ensure_qapp()
    from app.ui.path_preview import PathPreview
    v = PathPreview()
    assert v.show_travel is True
    m = np.zeros((60, 60), np.uint8)
    m[10:50, 10:50] = 255
    plan = build_plan(m, ProcessingSettings(fill_spacing=4))
    v.set_plan(plan)
    v.resize(300, 300)
    v.show()
    QApplication.processEvents()
    px = v.grab()
    assert not px.isNull()
    v.show_travel = False
    v.update()
    QApplication.processEvents()
    v.close()
