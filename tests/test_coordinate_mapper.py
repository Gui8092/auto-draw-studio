"""Testes de mapeamento isolados (coordenadas)."""
from app.automation.coordinate_mapper import CoordinateMapper
from app.automation.screen_calibration import ScreenArea


def test_map_corners_and_middle():
    mp = CoordinateMapper(200, 100, ScreenArea(0, 0, 400, 200))
    assert mp.to_screen(0, 0) == (mp.area.x, mp.area.y)
    assert mp.to_screen(200, 100) == (mp.area.x + mp.area.width, mp.area.y + mp.area.height)
    mx, my = mp.to_screen(100, 50)
    assert mp.area.x < mx < mp.area.x + mp.area.width
