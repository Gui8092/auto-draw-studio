"""Regressões da Fase 1: o desenho precisa bater com a imagem.

Cobre os bugs:
- simplificação destruía o fechamento dos contornos (faltava um lado);
- contraste sem pivô virava a página inteira em tinta;
- componente fino era desenhado DUAS vezes (centerline + contorno);
- `order_plan` partia do ponto errado (pen-up ~2x maior);
- espessura via `dist.max()` era fooled por um ponto grosso;
- `thin_px` dependia do espaçamento do preenchimento;
- o próprio contorno do furo contava como "invasão";
- avisos falsos de cobertura em contour/centerline;
- detalhe desenhado aberto;
- cadeia de fill quebrada em curvas;
- poda de esporões invertida.
"""
import cv2
import numpy as np

from app.core.centerline import plan_centerlines, skeletonize, trace_skeleton
from app.core.fill_planner import plan_fill_zigzag
from app.core.path_optimizer import order_plan, pen_up_travel, simplify_plan
from app.core.pipeline import build_plan
from app.core.preprocessing import apply_adjustments
from app.core.quality_checker import check_quality
from app.core.strategy import classify_components
from app.models.drawing_plan import DrawingPlan, Stroke, StrokeType
from app.models.settings import ProcessingSettings


def _u_shape(size=60, thickness=2):
    m = np.zeros((size, size), np.uint8)
    cv2.line(m, (15, 15), (15, 45), 255, thickness)
    cv2.line(m, (15, 45), (45, 45), 255, thickness)
    cv2.line(m, (45, 45), (45, 15), 255, thickness)
    return m


# ----------------------------------------------------------------------
# 1.1 — contornos fechados
# ----------------------------------------------------------------------
def test_outer_contour_is_closed_after_simplification():
    """Todo contorno continua fechado depois da simplificação.

    `approxPolyDP` NUNCA devolve o vértice de fechamento: sem
    restaurá-lo, um quadrado perdia um lado inteiro (59px) e um
    círculo ficava com uma fresta.
    """
    m = np.zeros((80, 80), np.uint8)
    m[20:60, 20:60] = 255
    plan = build_plan(m, ProcessingSettings(strategy="contour"))
    outers = plan.strokes_by_kind(StrokeType.OUTER_CONTOUR)
    assert outers, "contorno externo ausente"
    for s in outers:
        assert s.points[0] == s.points[-1], "contorno ficou aberto"
        # Os 4 lados do quadrado precisam estar presentes.
        xs = [p[0] for p in s.points]
        ys = [p[1] for p in s.points]
        assert min(xs) <= 20 and max(xs) >= 59
        assert min(ys) <= 20 and max(ys) >= 59


def test_simplify_plan_keeps_closed_polylines_closed():
    from app.core.path_optimizer import simplify_polyline

    pts = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
    out = simplify_polyline(pts, 1.0)
    assert out[0] == out[-1], "simplificação abriu o polígono"


def test_fill_scanline_structure_survives_high_epsilon():
    """Epsilon alto não pode transformar as linhas de varredura em diagonais."""
    m = np.zeros((120, 120), np.uint8)
    m[20:100, 20:100] = 255
    plan = build_plan(m, ProcessingSettings(fill_spacing=4, simplify_epsilon=5.0))
    fills = plan.strokes_by_kind(StrokeType.FILL)
    assert fills
    for s in fills:
        rows = {round(p[1]) for p in s.points}
        assert len(rows) >= 2, "cadeia de fill colapsou em uma linha"


# ----------------------------------------------------------------------
# 1.2 — contraste/brilho não invertem a página
# ----------------------------------------------------------------------
def test_low_contrast_keeps_paper_as_paper():
    """Com contraste 0.5 o branco (255) NÃO pode virar tinta.

    Sem pivô em meio-tom, 255 * 0.5 = 127 < 128 (limiar padrão) e a
    página inteira era tratada como tinta.
    """
    g = np.full((40, 40), 255, np.uint8)
    g[10:30, 10:30] = 0
    for contrast in (1.0, 0.75, 0.5):
        a = apply_adjustments(g, brightness=0, contrast=contrast, gamma=1.0)
        ink = int((a < 128).sum())
        assert ink <= 500, f"contraste {contrast}: {ink} px de tinta (papel virou tinta)"


def test_contrast_pivot_keeps_mid_grey():
    g = np.full((10, 10), 128, np.uint8)
    a = apply_adjustments(g, brightness=0, contrast=0.5, gamma=1.0)
    assert abs(int(a.mean()) - 128) <= 2, "o meio-tom deve ficar parado"


def test_brightness_is_symmetric():
    g = np.full((10, 10), 128, np.uint8)
    up = apply_adjustments(g, brightness=20)
    down = apply_adjustments(g, brightness=-20)
    assert int(up.mean()) > int(g.mean()) > int(down.mean())
    assert abs((int(up.mean()) - 128) - (128 - int(down.mean()))) <= 2


def test_adjustments_round_instead_of_truncate():
    """Truncar aplicava viés de -0.5 nível antes da binarização."""
    g = np.array([[127.6]], np.float32)
    out = apply_adjustments(g, brightness=0, contrast=1.0, gamma=1.0)
    assert int(out[0, 0]) == 128


# ----------------------------------------------------------------------
# 1.3 — componente fino desenhado UMA vez
# ----------------------------------------------------------------------
def test_thin_component_not_drawn_twice():
    """Componente fino (não convexo) não pode ter centerline + contorno."""
    m = _u_shape()
    plan = build_plan(m, ProcessingSettings(strategy="auto"))
    assert plan.strokes_by_kind(StrokeType.CENTERLINE)
    assert not plan.strokes_by_kind(StrokeType.OUTER_CONTOUR), \
        "contorno duplicou a linha central do componente fino"


def test_thin_ring_not_drawn_twice():
    m = np.zeros((120, 120), np.uint8)
    cv2.circle(m, (60, 60), 40, 255, 2)
    plan = build_plan(m, ProcessingSettings(strategy="auto"))
    assert plan.strokes_by_kind(StrokeType.CENTERLINE)
    assert not plan.strokes_by_kind(StrokeType.OUTER_CONTOUR)


# ----------------------------------------------------------------------
# 1.4 — order_plan começa no FIM do primeiro traço
# ----------------------------------------------------------------------
def test_order_plan_starts_from_end_of_first_stroke():
    def mk(a, b):
        return Stroke(points=[a, b], kind=StrokeType.FILL)

    plan = DrawingPlan(strokes=[mk((0, 0), (50, 0)),
                                mk((50, 0), (51, 1)),
                                mk((1, 1), (2, 2))])
    order_plan(plan)
    # A ordem ótima é A → B → C (pen-up 49.0); com o cursor no início
    # do 1º traço, a ordem virava A → C → B (pen-up 97.0).
    assert pen_up_travel(plan.strokes) < 60, \
        f"pen-up alto demais: {pen_up_travel(plan.strokes):.1f}"


# ----------------------------------------------------------------------
# 1.5 / 1.6 — espessura robusta e thin_px independente
# ----------------------------------------------------------------------
def test_thin_line_with_blob_stays_centerline():
    """Uma bolinha grossa no fim de uma linha fina não vira 'fill'."""
    m = np.zeros((120, 120), np.uint8)
    cv2.line(m, (20, 60), (80, 60), 255, 2)
    cv2.rectangle(m, (80, 55), (92, 65), 255, -1)
    dec = classify_components(m, thin_px=4.0)
    assert dec.components[0].strategy == "centerline", \
        f"espessura={dec.components[0].max_thickness:.2f}"


def test_crossing_of_thin_lines_stays_centerline():
    m = np.zeros((120, 120), np.uint8)
    cv2.line(m, (20, 60), (100, 60), 255, 2)
    cv2.line(m, (60, 20), (60, 100), 255, 2)
    dec = classify_components(m, thin_px=4.0)
    assert dec.components[0].strategy == "centerline"


def test_solid_region_still_fill():
    m = np.zeros((120, 120), np.uint8)
    m[10:60, 10:60] = 255
    dec = classify_components(m, thin_px=4.0)
    assert dec.components[0].strategy == "fill"


def test_thin_px_independent_of_fill_spacing():
    """Mudar o espaçamento do preenchimento NÃO troca linha↔sólido."""
    thin = np.zeros((120, 120), np.uint8)
    cv2.line(thin, (10, 60), (110, 60), 255, 2)   # banda de 4px = linha
    for spacing in (3, 6, 10):
        plan = build_plan(thin, ProcessingSettings(fill_spacing=spacing,
                                                   strategy="auto"))
        assert plan.strokes_by_kind(StrokeType.CENTERLINE), \
            f"spacing={spacing}: a linha fina deixou de ser centerline"


# ----------------------------------------------------------------------
# 1.7 / 1.8 — qualidade: sem avisos falsos
# ----------------------------------------------------------------------
def test_hole_not_reported_as_invaded_by_its_own_outline():
    """O contorno do furo não conta como 'invasão' do furo."""
    m = np.zeros((100, 100), np.uint8)
    cv2.circle(m, (50, 50), 30, 255, -1)
    cv2.circle(m, (50, 50), 12, 0, -1)
    plan = build_plan(m, ProcessingSettings(strategy="auto"))
    rep = check_quality(plan, m, thickness=2, strategy="auto")
    assert rep.holes_preserved, f"furo dado como invadido: {rep.warnings}"


def test_no_false_coverage_warning_for_contour_strategy():
    m = np.zeros((100, 100), np.uint8)
    m[20:80, 20:80] = 255
    plan = build_plan(m, ProcessingSettings(strategy="contour"))
    rep = check_quality(plan, m, thickness=2, strategy="contour")
    assert not [w for w in rep.warnings if "Cobertura" in w], rep.warnings
    assert not [w for w in rep.warnings if "preenchimento" in w], rep.warnings


def test_no_false_coverage_warning_for_centerline_strategy():
    m = np.zeros((100, 100), np.uint8)
    cv2.line(m, (10, 50), (90, 50), 255, 3)
    plan = build_plan(m, ProcessingSettings(strategy="centerline"))
    rep = check_quality(plan, m, thickness=2, strategy="centerline")
    assert not [w for w in rep.warnings if "Cobertura" in w], rep.warnings


def test_fill_plan_has_no_false_coverage_warning():
    """Um preenchimento por scanline nunca pinta todos os pixels."""
    m = np.zeros((120, 120), np.uint8)
    m[10:110, 10:110] = 255
    plan = build_plan(m, ProcessingSettings(fill_spacing=4, strategy="fill"))
    rep = check_quality(plan, m, thickness=2, strategy="fill")
    assert not [w for w in rep.warnings if "Cobertura" in w], rep.warnings
    assert rep.coverage > 0.9, f"cobertura alcançável baixa: {rep.coverage:.0%}"


def test_centerline_mode_on_solid_region_warns():
    """Região sólida no modo centerline não pode falhar em silêncio."""
    m = np.zeros((100, 100), np.uint8)
    m[20:80, 20:80] = 255
    plan = build_plan(m, ProcessingSettings(strategy="centerline"))
    assert plan.strategy_notes, "deveria avisar que não há linhas centrais"
    rep = check_quality(plan, m, thickness=2, strategy="centerline")
    assert rep.warnings, "plano vazio precisa gerar aviso"


# ----------------------------------------------------------------------
# 1.9 — detalhes fechados
# ----------------------------------------------------------------------
def test_detail_contours_are_closed():
    m = np.zeros((80, 80), np.uint8)
    cv2.circle(m, (40, 40), 4, 255, -1)   # detalhe pequeno
    plan = build_plan(m, ProcessingSettings(strategy="contour",
                                            min_detail_area=100.0))
    details = plan.strokes_by_kind(StrokeType.DETAIL)
    assert details, "detalhe não encontrado"
    for s in details:
        assert s.points[0] == s.points[-1], "detalhe desenhado aberto"


# ----------------------------------------------------------------------
# 1.11 — cadeia de fill contínua em curvas
# ----------------------------------------------------------------------
def test_fill_chain_continuous_on_curves():
    c = np.zeros((200, 200), np.uint8)
    cv2.circle(c, (100, 100), 40, 255, -1)
    chains = plan_fill_zigzag(c, spacing=4, margin=1)
    assert len(chains) == 1, f"círculo partido em {len(chains)} polilinhas"


def test_fill_chain_continuous_on_triangle():
    tri = np.zeros((200, 200), np.uint8)
    cv2.fillPoly(tri, [np.array([[100, 40], [40, 160], [160, 160]])], 255)
    chains = plan_fill_zigzag(tri, spacing=4, margin=1)
    assert len(chains) == 1, f"triângulo partido em {len(chains)} polilinhas"


def test_fill_never_crosses_holes():
    m = np.zeros((120, 120), np.uint8)
    cv2.circle(m, (60, 60), 45, 255, -1)
    cv2.circle(m, (60, 60), 20, 0, -1)
    for chain in plan_fill_zigzag(m, spacing=4, margin=1):
        for x, y in chain:
            assert m[int(round(y)), int(round(x))] == 255, \
                "traço de fill cruzou o furo"


# ----------------------------------------------------------------------
# 1.12 — poda de esporões
# ----------------------------------------------------------------------
def test_short_spur_is_pruned_but_real_stroke_kept():
    m = np.zeros((40, 40), np.uint8)
    m[20, 5:25] = 1
    m[18, 20] = 1        # esporão de 2px
    chains = trace_skeleton(skeletonize(m), prune_len=3)
    assert len(chains) == 1, f"esporão não podado: {len(chains)} cadeias"
    assert len(chains[0]) >= 15
