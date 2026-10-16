"""Suíte de 12 casos: legado (fill) vs híbrido auto. Métricas + PNGs.

Uso:  python benchmarks/bench_suite.py
Saída: tabela + benchmarks/out/suite_*.png (máscara | antes | depois).
"""
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.bench_zigzag import legacy_plan, oob_points  # noqa: E402

from app.core.pipeline import build_plan  # noqa: E402
from app.core.path_optimizer import stroke_metrics  # noqa: E402
from app.core.quality_checker import (check_quality, contour_chamfer,  # noqa: E402
                                      mask_iou, rasterize_plan)
from app.models.settings import ProcessingSettings  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(parents=True, exist_ok=True)
SPEED, DELAY = 1200.0, 0.03


def gray_cases():
    """Tons de cinza (pipeline completo: limiar entra em jogo)."""
    g = {}
    c = np.full((200, 200), 255, np.uint8)
    cv2.rectangle(c, (40, 40), (160, 160), 0, -1); g["1_quadrado"] = c
    c = np.full((200, 200), 255, np.uint8)
    cv2.circle(c, (100, 100), 70, 0, -1)
    cv2.ellipse(c, (100, 100), (90, 50), 0, 0, 360, 0, -1)
    g["2_circulo_elipse"] = c
    c = np.full((200, 200), 255, np.uint8)
    cv2.circle(c, (100, 100), 70, 0, -1); cv2.circle(c, (100, 100), 35, 255, -1)
    g["3_anel"] = c
    c = np.full((200, 200), 255, np.uint8)
    cv2.fillPoly(c, [np.array([[100, 20], [20, 170], [180, 170]])], 0)
    cv2.line(c, (20, 20), (180, 180), 0, 2); g["4_triang_diag"] = c
    c = np.full((200, 200), 255, np.uint8)
    cv2.rectangle(c, (15, 15), (85, 85), 0, -1)
    cv2.circle(c, (145, 50), 35, 0, -1)
    cv2.rectangle(c, (110, 110), (185, 185), 0, -1); g["5_logo"] = c
    c = np.full((200, 200), 255, np.uint8)  # contorno fino (line art)
    cv2.rectangle(c, (30, 30), (170, 170), 0, 2)
    cv2.circle(c, (100, 100), 40, 0, 2)
    cv2.line(c, (30, 170), (170, 30), 0, 2); g["6_lineart"] = c
    c = np.full((200, 200), 255, np.uint8)  # diagonais estreitas
    for i in range(5):
        cv2.line(c, (10, 20 + i * 30), (190, 40 + i * 30), 0, 1)
    g["7_diagonais"] = c
    c = np.full((200, 200), 255, np.uint8)  # texto com espaços internos
    cv2.putText(c, "AaBb", (15, 140), cv2.FONT_HERSHEY_SIMPLEX, 2.5, 0, 5)
    g["8_texto"] = c
    c = np.full((200, 200), 255, np.uint8)  # fill + detalhes finos
    cv2.rectangle(c, (20, 20), (120, 120), 0, -1)
    cv2.circle(c, (150, 150), 30, 0, -1)
    cv2.line(c, (130, 30), (190, 90), 0, 2)
    cv2.line(c, (10, 180), (90, 180), 0, 1); g["9_ilustracao"] = c
    c = np.full((200, 200), 255, np.uint8)  # tonal: círculo com gradiente
    for r in range(70, 0, -1):
        cv2.circle(c, (100, 100), r, int(255 - r * 2.2), -1)
    g["10_tonal"] = c
    rng = np.random.default_rng(7)  # ruído + iluminação irregular
    c = np.full((200, 200), 255, np.uint8)
    cv2.circle(c, (100, 100), 60, 100, -1)
    c = np.clip(c.astype(int) + rng.integers(-40, 40, (200, 200)), 0, 255).astype(np.uint8)
    yy, xx = np.mgrid[0:200, 0:200]
    c = np.clip(c.astype(int) - (xx // 4), 0, 255).astype(np.uint8)
    g["11_ruido"] = c
    c = np.full((200, 200), 255, np.uint8)  # regiões pequenas próximas
    for i, (cx, cy) in enumerate([(40, 40), (70, 45), (45, 75), (150, 150), (165, 140)]):
        cv2.circle(c, (cx, cy), 8 + i, 0, -1)
    g["12_regioes_prox"] = c
    return g


def main():
    from app.core.pipeline import process_to_plan
    s = ProcessingSettings(fill_spacing=4)
    print(f"{'caso':<15}{'ms':>14}{'tracos':>12}{'penUp':>12}{'eta':>10}{'iou':>9}{'chamf':>8}")
    for name, gray in gray_cases().items():
        t0 = time.perf_counter()
        mask, _ = process_to_plan(gray, s)
        ms = (time.perf_counter() - t0) * 1000
        old, new = legacy_plan(mask, s), build_plan(mask, s)
        mo, mn = stroke_metrics(old), stroke_metrics(new)
        ro = check_quality(old, mask, thickness=2)
        rn = check_quality(new, mask, thickness=2)
        so, sn = rasterize_plan(old, 2), rasterize_plan(new, 2)
        tgt = (mask > 127).astype(np.uint8) * 255
        io = (mask_iou(so, tgt), mask_iou(sn, tgt))
        ch = (contour_chamfer(so, tgt), contour_chamfer(sn, tgt))
        eo = old.estimate_duration(SPEED, DELAY)
        en = new.estimate_duration(SPEED, DELAY)
        print(f"{name:<15}{ms:>7.0f}ms   {mo['total_strokes']:>4}>{mn['total_strokes']:<5}"
              f"{mo['pen_up']:>6.0f}>{mn['pen_up']:<5.0f}{eo:>5.1f}>{en:<4.1f}"
              f"{io[0]:>4.2f}>{io[1]:<4.2f}{ch[0]:>4.1f}>{ch[1]:<4.1f}  "
              f"cob {ro.coverage:.0%}>{rn.coverage:.0%} furo {ro.holes_preserved}>{rn.holes_preserved} "
              f"oob {oob_points(old)}>{oob_points(new)}")
        h, w = mask.shape[:2]
        canvas = np.full((h, w * 3 + 20), 255, np.uint8)
        canvas[:, :w] = 255 - mask
        canvas[:, w + 10:2 * w + 10] = 255 - so
        canvas[:, 2 * w + 20:3 * w + 20] = 255 - sn
        cv2.imwrite(str(OUT / f"suite_{name}.png"), canvas)
    print(f"\nPNGs em {OUT} (máscara | antes=fill | depois=híbrido).")


if __name__ == "__main__":
    main()
