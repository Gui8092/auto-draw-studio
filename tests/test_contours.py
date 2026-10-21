"""Testes de contornos: quadrado, círculo, anel, diagonal, desconectadas, composta."""
import cv2
import numpy as np

from app.core.contour_extractor import contours_to_polylines, extract_contours


def square(size=100, sq=60):
    m = np.zeros((size, size), np.uint8)
    m[(size - sq) // 2:(size + sq) // 2, (size - sq) // 2:(size + sq) // 2] = 255
    return m


def test_square_contour_found():
    m = square()
    mains, _ = extract_contours(m, min_area=20)
    assert len([c for c in mains if not c.is_hole]) >= 1


def test_circle_contour():
    m = np.zeros((100, 100), np.uint8)
    cv2.circle(m, (50, 50), 30, 255, -1)
    mains, _ = extract_contours(m, min_area=20)
    assert any(c.area > 2000 for c in mains)


def test_ring_hole_detected():
    m = np.zeros((100, 100), np.uint8)
    cv2.circle(m, (50, 50), 35, 255, -1)
    cv2.circle(m, (50, 50), 15, 0, -1)
    mains, _ = extract_contours(m, min_area=20)
    holes = [c for c in mains if c.is_hole]
    assert len(holes) >= 1, "anel deve ter buraco detectado"


def test_diagonal_thin_line():
    m = np.zeros((100, 100), np.uint8)
    cv2.line(m, (10, 10), (90, 90), 255, 1)
    mains, details = extract_contours(m, min_area=20)
    assert len(mains) + len(details) >= 1


def test_two_disconnected_regions():
    m = np.zeros((100, 100), np.uint8)
    cv2.rectangle(m, (5, 5), (30, 30), 255, -1)
    cv2.rectangle(m, (60, 60), (90, 90), 255, -1)
    mains, _ = extract_contours(m, min_area=20)
    solids = [c for c in mains if not c.is_hole]
    assert len(solids) >= 2, f"esperava 2 componentes, achou {len(solids)}"


def test_composite_with_inner_regions():
    m = np.zeros((120, 120), np.uint8)
    cv2.rectangle(m, (10, 10), (110, 110), 255, -1)
    cv2.rectangle(m, (30, 30), (50, 50), 0, -1)
    cv2.rectangle(m, (70, 70), (90, 90), 0, -1)
    mains, _ = extract_contours(m, min_area=20)
    holes = [c for c in mains if c.is_hole]
    assert len(holes) >= 2


def test_empty_and_invalid_params():
    m = np.zeros((50, 50), np.uint8)
    mains, details = extract_contours(m)
    assert mains == [] and details == []
    polys = contours_to_polylines([], close=True)
    assert polys == []
