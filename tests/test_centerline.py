"""Fase B: centerlines preservam topologia e seguem o meio dos traços."""
import cv2
import numpy as np

from app.core.centerline import (plan_centerlines, skeletonize,
                                 trace_skeleton)


def test_skeleton_is_1px_and_connected():
    m = np.zeros((50, 50), np.uint8)
    m[20:30, 5:45] = 1  # barra 10px de espessura
    sk = skeletonize(m)
    assert sk.max() <= 1
    # Linha central única e conexa no meio da barra
    rows = np.nonzero(sk.sum(axis=1))[0]
    assert len(rows) == 1 and rows[0] in (24, 25)
    assert sk.sum() >= 25, "encurtamento excessivo das pontas"
    cols = np.nonzero(sk[rows[0]])[0]
    assert (np.diff(cols) == 1).all(), "linha central deve ser contínua"


def test_diagonal_trace_single_chain():
    m = np.zeros((60, 60), np.uint8)
    cv2.line(m, (5, 5), (55, 55), 1, 2)
    chains = trace_skeleton(skeletonize(m))
    assert len(chains) == 1
    assert len(chains[0]) > 40


def test_cross_junction_covered_without_overlap():
    m = np.zeros((40, 40), np.uint8)
    m[20, :] = 1
    m[:, 20] = 1
    chains = trace_skeleton(skeletonize(m))
    assert 2 <= len(chains) <= 4
    pts = [p for c in chains for p in c]
    assert len(pts) == len(set(pts)), "pixel do esqueleto em 2 cadeias"
    assert len(pts) >= 70, "braços não podem ser descartados"


def test_empty_and_noise_pruned():
    assert trace_skeleton(np.zeros((20, 20), np.uint8)) == []
    m = np.zeros((30, 30), np.uint8)
    m[15, 5:25] = 1
    m[3, 3] = 1  # pixel isolado
    chains = trace_skeleton(skeletonize(m))
    assert len(chains) == 1 and len(chains[0]) >= 15


def test_plan_centerlines_bounds_and_lengths():
    m = np.zeros((60, 60), np.uint8)
    cv2.line(m, (5, 30), (55, 30), 255, 3)
    strokes = plan_centerlines(m)
    assert strokes, "linha fina precisa de centerline"
    n_old = sum(1 for _ in strokes)
    assert n_old >= 1
    for seg in strokes:
        for x, y in seg:
            assert 0 <= x <= 59 and 0 <= y <= 59
            assert m[int(y), int(x)] == 255
    assert plan_centerlines(np.zeros((20, 20), np.uint8)) == []
