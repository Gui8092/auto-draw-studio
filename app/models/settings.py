"""Configurações do aplicativo."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class ProcessingSettings:
    threshold: int = 128
    method: str = "global"  # global | otsu | adaptive
    brightness: int = 0  # -100..100
    contrast: float = 1.0  # 0.5..2.0
    gamma: float = 1.0  # 0.2..3.0
    denoise: int = 0  # 0..5 (força do blur mediano/gaussiano)
    detail_strength: float = 0.5  # RESERVADO (experimental, sem efeito no pipeline)
    invert: bool = False
    morph_op: str = "none"  # none|open|close|erode|dilate
    morph_kernel: int = 3  # 3|5|7
    min_detail_area: float = 20.0
    fill_spacing: int = 4  # px na imagem de trabalho
    # Largura (px) em que um traço deixa de ser "linha" e vira "sólido".
    # ANTES isto era derivado de `fill_spacing`: mudar o espaçamento do
    # preenchimento trocava linha↔sólido em silêncio.
    thin_line_px: float = 4.0
    strategy: str = "auto"  # auto|fill|contour|centerline|sombreado
    # Hachuras (modo "sombreado"): regiões de tom médio viram hachuras.
    hatch_spacing: int = 6      # px entre linhas de hachura
    hatch_angle: float = 45.0   # graus
    hatch_threshold: float = 120.0  # tom médio acima do qual a região é hachurada
    shading_intensity: float = 0.5  # densidade das hachuras (0=ralo, 1=denso)
    simplify_epsilon: float = 1.0
    max_work_size: int = 512

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "ProcessingSettings":
        base = ProcessingSettings()
        for k, v in (data or {}).items():
            if hasattr(base, k):
                setattr(base, k, v)
        return base


@dataclass
class ExecutionSettings:
    move_speed_px_s: float = 1200.0
    stroke_delay_s: float = 0.03
    margin_px: int = 10
    countdown_s: int = 5
    # Espessura do pincel do app de destino (px de tela). 0 = automático
    # (≈ metade do espaçamento do preenchimento). Antes a prévia usava
    # sempre essa heurística, e o traço real depende do pincel escolhido
    # lá fora — a prévia não previa o resultado.
    brush_px: int = 0
    hotkey_start: str = "f9"
    # F10 ALTERNA pausar/retomar (toggle). Antes não havia como retomar
    # pelo teclado — e, como a janela é minimizada para desenhar, a pausa
    # virava uma via sem volta.
    hotkey_pause: str = "f10"
    hotkey_resume: str = "f11"
    hotkey_cancel: str = "esc"

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "ExecutionSettings":
        base = ExecutionSettings()
        for k, v in (data or {}).items():
            if hasattr(base, k):
                setattr(base, k, v)
        # Clamp dos valores: o settings.json é editável à mão (o README
        # convida a isso) e um valor absurdo não pode quebrar o app.
        try:
            base.move_speed_px_s = max(1.0, float(base.move_speed_px_s))
        except (TypeError, ValueError):
            base.move_speed_px_s = ExecutionSettings.move_speed_px_s
        try:
            base.stroke_delay_s = max(0.0, float(base.stroke_delay_s))
        except (TypeError, ValueError):
            base.stroke_delay_s = ExecutionSettings.stroke_delay_s
        try:
            base.countdown_s = max(1, min(30, int(base.countdown_s)))
        except (TypeError, ValueError):
            base.countdown_s = ExecutionSettings.countdown_s
        try:
            base.brush_px = max(0, min(30, int(base.brush_px)))
        except (TypeError, ValueError):
            base.brush_px = ExecutionSettings.brush_px
        return base


@dataclass
class AppSettings:
    processing: ProcessingSettings = field(default_factory=ProcessingSettings)
    execution: ExecutionSettings = field(default_factory=ExecutionSettings)

    def to_dict(self) -> dict:
        return {
            "processing": self.processing.to_dict(),
            "execution": self.execution.to_dict(),
        }

    @staticmethod
    def from_dict(data: dict) -> "AppSettings":
        return AppSettings(
            processing=ProcessingSettings.from_dict(data.get("processing", {})),
            execution=ExecutionSettings.from_dict(data.get("execution", {})),
        )


DEFAULTS = AppSettings()
