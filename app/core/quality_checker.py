"""Verificação de qualidade: rasteriza traços e compara com a máscara."""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from app.models.drawing_plan import DrawingPlan, StrokeType


@dataclass
class QualityReport:
    coverage: float  # 0..1 fração da tinta coberta
    overflow: float  # fração de tinta simulada fora da máscara
    holes_preserved: bool
    missing_fill: bool  # True se há região sólida sem nenhum fill
    warnings: list[str] = field(default_factory=list)
    simulated_ink_px: int = 0
    target_ink_px: int = 0

    @property
    def ok(self) -> bool:
        return not self.warnings


def rasterize_plan(plan: DrawingPlan, thickness: int = 1) -> np.ndarray:
    canvas = np.zeros((max(1, plan.image_height), max(1, plan.image_width)), dtype=np.uint8)
    for s in plan.strokes:
        if len(s.points) < 2:
            if len(s.points) == 1:
                x, y = int(round(s.points[0][0])), int(round(s.points[0][1]))
                if 0 <= x < canvas.shape[1] and 0 <= y < canvas.shape[0]:
                    canvas[y, x] = 255
            continue
        pts = np.array([(int(round(x)), int(round(y))) for x, y in s.points], dtype=np.int32)
        cv2.polylines(canvas, [pts], False, 255, max(1, int(thickness)), cv2.LINE_8)
    _, canvas = cv2.threshold(canvas, 127, 255, cv2.THRESH_BINARY)
    return canvas


def detect_detail_loss(gray: np.ndarray, mask: np.ndarray,
                        dark_thr: int = 100) -> list[str]:
    """Alerta sobre detalhes escuros finos que a binarização apagou.

    Compara componentes escuros do cinza original com a máscara final:
    componentes pequenos (<4× min_detail típico) com sobreposição mínima
    foram provavelmente perdidos no limiar/morfologia. Não promete
    recuperação — apenas informa para o usuário ajustar o limiar.
    """
    g = np.asarray(gray)
    if g.size == 0:
        return []
    dark = (g < int(dark_thr)).astype(np.uint8)
    ink = (np.asarray(mask) > 127).astype(np.uint8)
    if dark.sum() == 0 or ink.shape[:2] != g.shape[:2]:
        return []
    n, labels, stats, _ = cv2.connectedComponentsWithStats(dark * 255, 8)
    lost = 0
    lost_px = 0
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area >= 400:
            continue  # só detalhes pequenos
        comp = (labels == i)
        overlap = float((comp & (ink == 1)).sum()) / max(1, area)
        if overlap < 0.3:
            lost += 1
            lost_px += area
    if lost == 0:
        return []
    return [f"Detalhes finos possivelmente perdidos: {lost} componente(s) "
            f"escuro(s) ({lost_px}px) sumiram na binarização — "
            f"tente baixar o limiar ou o denoise."]


def mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    """IoU entre duas máscaras binárias (fidelidade de preenchimento)."""
    ab = ((np.asarray(a) > 127) & (np.asarray(b) > 127)).sum()
    union = ((np.asarray(a) > 127) | (np.asarray(b) > 127)).sum()
    return float(ab / union) if union else 1.0


def _edges(mask: np.ndarray) -> np.ndarray:
    ink = (np.asarray(mask) > 127).astype(np.uint8) * 255
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    return cv2.morphologyEx(ink, cv2.MORPH_GRADIENT, k)


def contour_chamfer(a: np.ndarray, b: np.ndarray) -> float:
    """Distância de Chamfer simétrica entre bordas (px). Menor = mais fiel."""
    ea = _edges(a) > 0
    eb = _edges(b) > 0
    if not ea.any() or not eb.any():
        return 0.0 if not ea.any() and not eb.any() else float("inf")
    da = cv2.distanceTransform((1 - eb.astype(np.uint8)) * 255, cv2.DIST_L2, 3)
    db = cv2.distanceTransform((1 - ea.astype(np.uint8)) * 255, cv2.DIST_L2, 3)
    return float((da[ea].mean() + db[eb].mean()) / 2.0)


def check_quality(
    plan: DrawingPlan,
    target_mask: np.ndarray,
    thickness: int = 2,
    min_coverage: float = 0.85,
    max_overflow: float = 0.15,
    gray: np.ndarray | None = None,
) -> QualityReport:
    target = (target_mask > 127).astype(np.uint8) * 255
    sim = rasterize_plan(plan, thickness=max(1, int(thickness)))
    sim_b = (sim > 127).astype(np.uint8)
    tgt_b = (target > 127).astype(np.uint8)
    target_px = int(tgt_b.sum())
    sim_px = int(sim_b.sum())
    inter = int(((sim_b == 1) & (tgt_b == 1)).sum())
    outside = int(((sim_b == 1) & (tgt_b == 0)).sum())
    coverage = (inter / target_px) if target_px else (1.0 if sim_px == 0 else 0.0)
    overflow = (outside / sim_px) if sim_px else 0.0
    warnings: list[str] = []
    if target_px == 0 and sim_px > 0:
        warnings.append("Máscara-alvo vazia, mas o plano contém traços.")
    if target_px > 0 and sim_px == 0:
        warnings.append("Plano vazio: nenhum traço rasterizado.")
    if coverage < min_coverage and target_px > 0:
        warnings.append(f"Cobertura baixa: {coverage:.0%} < {min_coverage:.0%}.")
    if overflow > max_overflow and sim_px > 0:
        warnings.append(f"Vazamento alto: {overflow:.0%} dos traços fora da máscara.")
    # Buracos: componentes de fundo cercados de tinta não devem ser pintados
    holes_ok = True
    inv = (1 - tgt_b).astype(np.uint8) * 255
    n, labels, _, _ = cv2.connectedComponentsWithStats(inv, 8) if inv.size else (1, inv, None, None)
    if n is not None and n > 1:
        h, w = labels.shape
        border = set(np.unique(labels[0, :])) | set(np.unique(labels[-1, :])) | set(
            np.unique(labels[:, 0])) | set(np.unique(labels[:, -1]))
        for i in range(1, n):
            if i in border:
                continue
            hole_area = int((labels == i).sum())
            if hole_area < 4:
                continue
            painted = int(((labels == i) & (sim_b == 1)).sum())
            if painted > hole_area * 0.35:
                holes_ok = False
                warnings.append("Buraco/área branca interna foi invadida pelo preenchimento.")
                break
    fills = [s for s in plan.strokes if s.kind in (StrokeType.FILL, StrokeType.CENTERLINE)]
    missing_fill = bool(target_px > 200 and not fills)
    if missing_fill:
        warnings.append("Sem traços de preenchimento: interiores ficarão vazios.")
    if gray is not None:
        for loss in detect_detail_loss(gray, target_mask):
            warnings.append(loss)
    return QualityReport(
        coverage=coverage, overflow=overflow, holes_preserved=holes_ok,
        missing_fill=missing_fill, warnings=warnings,
        simulated_ink_px=sim_px, target_ink_px=target_px,
    )
