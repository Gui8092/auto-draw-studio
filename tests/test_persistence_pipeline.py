"""Pontos secundários: JSON corrompido + pipeline sem parâmetro morto."""
import logging

from app.core.pipeline import build_plan, process_to_plan
from app.models.drawing_plan import StrokeType
from app.models.settings import ProcessingSettings
from app.utils.persistence import load_settings, save_settings


def test_corrupt_json_returns_defaults_and_logs(tmp_path, caplog):
    import numpy as np
    p = tmp_path / "settings.json"
    p.write_text("{ json quebrado [[[", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="auto_draw_studio.persistence"):
        s = load_settings(p)
    assert s.processing.threshold == ProcessingSettings().threshold
    assert any("corrompida" in r.message for r in caplog.records), \
        "JSON corrompido deve gerar log de aviso"


def test_settings_roundtrip(tmp_path):
    p = tmp_path / "settings.json"
    s = ProcessingSettings(threshold=200)
    from app.models.settings import AppSettings
    save_settings(AppSettings(processing=s), p)
    back = load_settings(p)
    assert back.processing.threshold == 200


def test_build_plan_signature_has_no_gray():
    import inspect
    sig = inspect.signature(build_plan)
    assert "gray" not in sig.parameters, "parâmetro morto `gray` deve ser removido"
    # `cancel_check` é opcional (cancelamento cooperativo).
    assert list(sig.parameters) == ["mask", "settings", "cancel_check"]
    assert sig.parameters["cancel_check"].default is None


def test_pipeline_still_fills_and_exports_svg():
    import numpy as np
    gray = np.full((60, 60), 255, np.uint8)
    gray[10:50, 10:50] = 0
    mask, plan = process_to_plan(gray, ProcessingSettings(fill_spacing=4))
    fills = plan.strokes_by_kind(StrokeType.FILL)
    assert fills, "pipeline deve continuar gerando preenchimento"
    assert sum(len(s) for s in fills) > 5, "fill deve cobrir o interior"
    svg = plan.to_svg()
    assert "<svg" in svg and "<path" in svg
    d = plan.to_dict()
    from app.models.drawing_plan import DrawingPlan
    back = DrawingPlan.from_dict(d)
    assert back.total_strokes == plan.total_strokes
