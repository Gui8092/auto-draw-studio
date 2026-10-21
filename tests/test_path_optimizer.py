"""Testes do otimizador e do mapeamento de coordenadas."""
import numpy as np

from app.automation.coordinate_mapper import CoordinateMapper
from app.automation.screen_calibration import ScreenArea, validate_area
from app.core.path_optimizer import order_plan, simplify_plan
from app.models.drawing_plan import DrawingPlan, Stroke, StrokeType


def _plan():
    return DrawingPlan(
        strokes=[
            Stroke(points=[(0.0, 0.0), (10.0, 0.0)], kind=StrokeType.FILL),
            Stroke(points=[(0.0, 0.0), (5.0, 5.0), (5.0, 5.0), (10.0, 10.0)], kind=StrokeType.DETAIL),
            Stroke(points=[(90.0, 90.0), (95.0, 95.0)], kind=StrokeType.OUTER_CONTOUR),
        ],
        image_width=100, image_height=100,
    )


def test_simplify_removes_redundant():
    p = _plan()
    simplify_plan(p, 1.5)
    detail = p.strokes_by_kind(StrokeType.DETAIL)[0]
    assert len(detail.points) < 4
    # fills de 2 pontos preservados
    assert len(p.strokes_by_kind(StrokeType.FILL)[0].points) == 2


def test_order_fills_first_contours_last():
    p = _plan()
    order_plan(p)
    kinds = [s.kind for s in p.strokes]
    assert kinds[0] == StrokeType.FILL
    assert kinds[-1] == StrokeType.OUTER_CONTOUR


def test_mapper_scales_and_centers():
    area = ScreenArea(100, 100, 400, 400)
    mp = CoordinateMapper(100, 100, area)
    x0, y0 = mp.to_screen(0, 0)
    x1, y1 = mp.to_screen(100, 100)
    assert (x1 - x0) == 400 and (y1 - y0) == 400
    # proporção preservada em área não quadrada
    area2 = ScreenArea(0, 0, 400, 200)
    mp2 = CoordinateMapper(100, 100, area2)
    assert mp2.area.width == mp2.area.height == 200


def test_mapper_rejects_invalid():
    try:
        CoordinateMapper(0, 100, ScreenArea(0, 0, 100, 100))
        assert False, "deveria rejeitar largura 0"
    except ValueError:
        pass


def test_validate_area():
    ok, _ = validate_area(ScreenArea(0, 0, 200, 200), True)
    assert ok
    ok, msg = validate_area(None, True)
    assert not ok
    ok, msg = validate_area(ScreenArea(0, 0, 5, 5), True)
    assert not ok
    ok, msg = validate_area(ScreenArea(0, 0, 200, 200), False)
    assert not ok
