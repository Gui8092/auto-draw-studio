"""Seleção de estratégia de desenho por região + perfis de utilização.

Cada componente conexo de tinta é classificado por área, espessura local
(máximo da transformada de distância) e presença de furos, e recebe uma
estratégia explícita:

- "centerline": traços finos (espessura <= limiar) — o mouse segue o MEIO
  da linha em vez de preencher ambos os lados.
- "fill": regiões sólidas amplas — zigue-zague contínuo.
- "contour": componentes pequenos ou bordas relevantes — só o contorno.

Critérios determinísticos e explicáveis (`explain()`); o usuário pode
forçar uma estratégia global pelo modo avançado (`strategy`).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from app.core.centerline import skeletonize
from app.models.settings import ProcessingSettings


@dataclass
class ComponentInfo:
    label: int
    area: float
    bbox: tuple[int, int, int, int]  # x, y, w, h
    max_thickness: float  # largura local máxima (px, via distanceTransform)
    has_hole: bool
    strategy: str = "fill"
    reason: str = ""


@dataclass
class StrategyDecision:
    components: list[ComponentInfo] = field(default_factory=list)
    thin_labels: set[int] = field(default_factory=set)

    def explain(self) -> list[str]:
        lines = []
        for c in self.components:
            lines.append(f"região #{c.label}: área={c.area:.0f}px "
                         f"espessura≈{c.max_thickness:.1f}px → {c.strategy} ({c.reason})")
        return lines


def _component_thickness(comp: np.ndarray, dist_all: np.ndarray,
                         thin_px: float) -> float:
    """Espessura local TÍPICA do componente (px).

    Antes usava `dist.max() * 2` (o maior círculo inscrito): UM ponto
    grosso — um cruzamento, uma quina, uma bolinha no fim de uma linha
    — promovia o componente inteiro a "fill".

    Agora:
    - `max_thick` (círculo inscrito) é suficiente quando está longe do
      limiar: fino demais → centerline; largo demais → fill;
    - na ZONA DE DECISÃO (perto do limiar) mede a mediana da largura
      sobre o EIXO MEDIAL (os pixels do esqueleto), que é a medida de
      espessura padrão (equivalente ao `medial_axis(return_distance=True)`
      do scikit-image).

    O esqueleto é calculado só quando necessário e só sobre a bounding
    box do componente: esqueleto global de uma imagem 512² custava
    ~2.5 s por repaginação.
    """
    inside = dist_all[comp]
    if inside.size == 0:
        return 0.0
    max_thick = float(inside.max() * 2.0)
    if max_thick <= thin_px:
        return max_thick            # fino demais: com certeza é centerline
    if max_thick > thin_px * 3.0:
        return max_thick            # largo demais: com certeza é fill

    # Zona de decisão: eixo medial do componente (bbox recortado).
    ys, xs = np.nonzero(comp)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    sub = comp[y0:y1, x0:x1].astype(np.uint8)
    # 1px de fundo em volta: o afinamento não consegue remover pixels
    # da borda da imagem, então sem o padding a borda do recorte
    # ficaria "grossa" e falsearia a medição.
    skel = skeletonize(np.pad(sub, 1))[1:-1, 1:-1]
    vals = 2.0 * dist_all[y0:y1, x0:x1][skel > 0]
    if vals.size:
        return float(np.median(vals))
    return max_thick


def classify_components(mask: np.ndarray, thin_px: float = 4.0,
                        min_area: float = 20.0,
                        cancel_check=None) -> StrategyDecision:
    """Classifica cada componente conexo de tinta (255=tinta).

    `cancel_check` (opcional): callback consultado a cada componente; se
    retornar True, levanta `app.core.pipeline.ProcessingCancelled`.
    """
    ink = (np.asarray(mask) > 127).astype(np.uint8)
    h, w = ink.shape[:2]
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink * 255, 8)
    # Transformada de distância calculada UMA vez para a imagem inteira
    # (antes era por componente: O(n_componentes x H x W)).
    # DIST_MASK_PRECISE: a aproximação de máscara 3x3 superestimava a
    # distância (uma banda de 4px media 4.24px em vez de 4.00) e jogava
    # linhas finas para "fill".
    dist_all = cv2.distanceTransform(ink, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    # Furos: componentes de fundo cercados de tinta
    inv = (1 - ink).astype(np.uint8) * 255
    nh, hlabels, hstats, _ = cv2.connectedComponentsWithStats(inv, 8)
    border = set(np.unique(hlabels[0, :])) | set(np.unique(hlabels[-1, :])) | set(
        np.unique(hlabels[:, 0])) | set(np.unique(hlabels[:, -1]))
    hole_map: dict[int, bool] = {}
    for i in range(1, nh):
        if i in border:
            continue
        # A qual componente de tinta este furo pertence? Procura a tinta
        # no anel de 1px em volta da bounding box do furo. Antes fazia
        # `np.nonzero(hlabels == i)` — uma varredura da imagem INTEIRA por
        # furo (caríssimo) — e olhava só o vizinho de baixo.
        hx = int(hstats[i, cv2.CC_STAT_LEFT])
        hy = int(hstats[i, cv2.CC_STAT_TOP])
        hw = int(hstats[i, cv2.CC_STAT_WIDTH])
        hh = int(hstats[i, cv2.CC_STAT_HEIGHT])
        x0, x1 = max(0, hx - 1), min(w, hx + hw + 1)
        y0, y1 = max(0, hy - 1), min(h, hy + hh + 1)
        ring = labels[y0:y1, x0:x1]
        vals = ring[ring > 0]
        if vals.size:
            hole_map[int(np.bincount(vals).argmax())] = True
    dec = StrategyDecision()
    for i in range(1, n):
        if cancel_check is not None and cancel_check():
            from app.core.pipeline import ProcessingCancelled

            raise ProcessingCancelled("Classificação cancelada.")
        area = float(stats[i, cv2.CC_STAT_AREA])
        x, y, bw, bh = (int(stats[i, cv2.CC_STAT_LEFT]),
                        int(stats[i, cv2.CC_STAT_TOP]),
                        int(stats[i, cv2.CC_STAT_WIDTH]),
                        int(stats[i, cv2.CC_STAT_HEIGHT]))
        comp = (labels == i)
        thick = _component_thickness(comp, dist_all, float(thin_px))
        has_hole = hole_map.get(i, False)
        if thick <= float(thin_px):
            strat, reason = "centerline", f"traço fino (≤{thin_px:.0f}px)"
        elif area < float(min_area):
            strat, reason = "contour", f"detalhe pequeno ({area:.0f}px)"
        else:
            strat, reason = "fill", "região sólida ampla"
        info = ComponentInfo(label=i, area=area, bbox=(x, y, bw, bh),
                             max_thickness=thick, has_hole=has_hole,
                             strategy=strat, reason=reason)
        dec.components.append(info)
        if strat == "centerline":
            dec.thin_labels.add(i)
    return dec


STRATEGIES = ("auto", "fill", "contour", "centerline")

# Campos que os perfis controlam (os mesmos do painel de ajustes).
_PROFILE_FIELDS = (
    "threshold", "method", "brightness", "contrast", "gamma", "denoise",
    "morph_op", "morph_kernel", "min_detail_area", "fill_spacing",
    "thin_line_px", "simplify_epsilon", "strategy", "invert",
)


def _defaults_profile() -> dict:
    """Perfil 'equilibrado' = os padrões reais.

    Antes era um dict VAZIO: escolher "equilibrado" não restaurava
    nada, mas o rótulo dizia que sim — o preset era uma mentira.
    """
    d = ProcessingSettings()
    return {k: getattr(d, k) for k in _PROFILE_FIELDS}


PROFILES: dict[str, dict] = {
    # Nome: ajustes sobre os parâmetros existentes (sem controles novos).
    "equilibrado": _defaults_profile(),
    "rapido": {"fill_spacing": 6, "simplify_epsilon": 2.0,
               "min_detail_area": 60.0, "denoise": 1, "morph_op": "open"},
    "fidelidade": {"fill_spacing": 3, "simplify_epsilon": 0.5,
                   "min_detail_area": 8.0, "denoise": 0, "morph_op": "none"},
    "linha_fina": {"fill_spacing": 3, "simplify_epsilon": 0.5,
                   "min_detail_area": 4.0, "denoise": 0, "morph_op": "none",
                   "strategy": "centerline"},
    "logo": {"fill_spacing": 4, "simplify_epsilon": 1.0,
             "min_detail_area": 20.0, "denoise": 1, "morph_op": "close",
             "strategy": "auto"},
}

PROFILE_NAMES = tuple(PROFILES)


def apply_profile(settings, name: str):
    """Aplica um perfil sobre ProcessingSettings (retorna novo objeto)."""
    from dataclasses import replace
    updates = PROFILES.get(name, {})
    valid = {k: v for k, v in updates.items() if hasattr(settings, k)}
    return replace(settings, **valid)
