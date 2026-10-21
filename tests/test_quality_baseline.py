"""Baseline de qualidade: qualquer piora no algoritmo quebra o build.

Compara as métricas do plano (traços, deslocamento, cobertura, furos)
contra uma baseline versionada, com tolerância. Se um ajuste de
algoritmo piorar o desenho, o teste falha e aponta o caso.

Para regenerar a baseline (depois de uma mudança INTENCIONAL):
    $env:UPDATE_QUALITY_BASELINE='1'; python -m pytest tests/test_quality_baseline.py
"""
import json
import os
from pathlib import Path

import cv2
import numpy as np

from app.core.path_optimizer import stroke_metrics
from app.core.pipeline import process_to_plan
from app.core.quality_checker import check_quality
from app.models.settings import ProcessingSettings

BASELINE_PATH = Path(__file__).resolve().parent / "baseline_quality.json"

# Tolerâncias (o algoritmo pode mudar; a QUALIDADE não pode piorar).
TOL_STROKES = 0.20      # ±20% no número de traços
TOL_PEN_UP = 0.20       # ±20% no deslocamento com o botão solto
TOL_COVERAGE = 0.08     # ±8 pontos percentuais de cobertura


def _cases():
    """Casos de referência (mesmos do bench_suite)."""
    out = {}
    c = np.full((200, 200), 255, np.uint8)
    cv2.rectangle(c, (40, 40), (160, 160), 0, -1); out["1_quadrado"] = c
    c = np.full((200, 200), 255, np.uint8)
    cv2.circle(c, (100, 100), 70, 0, -1); out["2_circulo"] = c
    c = np.full((200, 200), 255, np.uint8)
    cv2.circle(c, (100, 100), 70, 0, -1); cv2.circle(c, (100, 100), 35, 255, -1)
    out["3_anel"] = c
    c = np.full((200, 200), 255, np.uint8)
    cv2.fillPoly(c, [np.array([[100, 20], [20, 170], [180, 170]])], 0)
    cv2.line(c, (20, 20), (180, 180), 0, 2); out["4_triangulo"] = c
    c = np.full((200, 200), 255, np.uint8)
    cv2.rectangle(c, (15, 15), (85, 85), 0, -1)
    cv2.circle(c, (145, 50), 35, 0, -1)
    cv2.rectangle(c, (110, 110), (185, 185), 0, -1); out["5_logo"] = c
    c = np.full((200, 200), 255, np.uint8)
    cv2.rectangle(c, (30, 30), (170, 170), 0, 2)
    cv2.circle(c, (100, 100), 40, 0, 2); out["6_lineart"] = c
    c = np.full((200, 200), 255, np.uint8)
    for i in range(5):
        cv2.line(c, (10, 20 + i * 30), (190, 40 + i * 30), 0, 1)
    out["7_diagonais"] = c
    c = np.full((200, 200), 255, np.uint8)
    cv2.putText(c, "AaBb", (15, 140), cv2.FONT_HERSHEY_SIMPLEX, 2.5, 0, 5)
    out["8_texto"] = c
    c = np.full((200, 200), 255, np.uint8)
    cv2.circle(c, (100, 100), 60, 100, -1)
    rng = np.random.default_rng(7)
    c = np.clip(c.astype(int) + rng.integers(-40, 40, (200, 200)), 0, 255).astype(np.uint8)
    out["9_ruido"] = c
    c = np.full((200, 200), 255, np.uint8)
    for i, (cx, cy) in enumerate([(40, 40), (70, 45), (45, 75), (150, 150), (165, 140)]):
        cv2.circle(c, (cx, cy), 8 + i, 0, -1)
    out["10_regioes"] = c
    # Caso TONAL (gradiente): é o único que exercita o caminho de
    # hachuras — sem ele a baseline não cobriria o modo "sombreado".
    c = np.full((200, 200), 255, np.uint8)
    for r in range(70, 0, -1):
        cv2.circle(c, (100, 100), r, int(255 - r * 2.2), -1)
    out["11_tonal"] = c
    return out


def _metrics(name, gray, settings):
    mask, plan = process_to_plan(gray, settings)
    m = stroke_metrics(plan)
    rep = check_quality(plan, mask, thickness=2, strategy=settings.strategy)
    oob = 0
    for s in plan.strokes:
        for x, y in s.points:
            if not (0 <= x <= plan.image_width - 1 and 0 <= y <= plan.image_height - 1):
                oob += 1
    kinds = {}
    for s in plan.strokes:
        kinds[s.kind.value] = kinds.get(s.kind.value, 0) + 1
    return {
        "strokes": int(m["total_strokes"]),
        "pen_up": round(float(m["pen_up"]), 1),
        "coverage": round(float(rep.coverage), 4),
        "holes_preserved": bool(rep.holes_preserved),
        "oob": oob,
        "kinds": kinds,
    }


def _current_baseline():
    base = {}
    # Limiar 180 em ambos os modos: inclui os tons médios (o caso tonal
    # vira hachura no modo "sombreado") e mantém a comparação justa.
    for strategy in ("auto", "sombreado"):
        settings = ProcessingSettings(strategy=strategy, fill_spacing=4,
                                      threshold=180)
        for name, gray in _cases().items():
            base[f"{strategy}:{name}"] = _metrics(name, gray, settings)
    return base


def test_quality_baseline_not_worse():
    current = _current_baseline()
    if os.environ.get("UPDATE_QUALITY_BASELINE"):
        BASELINE_PATH.write_text(json.dumps(current, indent=2, sort_keys=True),
                                 encoding="utf-8")
        return
    assert BASELINE_PATH.exists(), (
        "baseline ausente — gere com UPDATE_QUALITY_BASELINE=1")
    expected = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    problems = []
    # Casos novos sem baseline: falha (um modo novo precisa de
    # referência, senão a baseline não protege nada).
    for key in current:
        if key not in expected:
            problems.append(f"{key}: caso novo sem baseline")
    for key, exp in expected.items():
        cur = current.get(key)
        if cur is None:
            problems.append(f"{key}: caso sumiu da baseline")
            continue
        if cur["oob"] > exp["oob"]:
            problems.append(
                f"{key}: pontos fora da área {cur['oob']} (antes {exp['oob']})")
        if not cur["holes_preserved"] and exp["holes_preserved"]:
            problems.append(f"{key}: furo deixou de ser preservado")
        if cur["coverage"] < exp["coverage"] - TOL_COVERAGE:
            problems.append(
                f"{key}: cobertura caiu de {exp['coverage']:.0%} "
                f"para {cur['coverage']:.0%}")
        if cur["strokes"] > exp["strokes"] * (1 + TOL_STROKES):
            problems.append(
                f"{key}: traços subiu de {exp['strokes']} para {cur['strokes']}")
        if cur["pen_up"] > exp["pen_up"] * (1 + TOL_PEN_UP) + 1:
            problems.append(
                f"{key}: deslocamento subiu de {exp['pen_up']} "
                f"para {cur['pen_up']}")
    assert not problems, "qualidade regrediu:\n  " + "\n  ".join(problems)
