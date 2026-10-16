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
    strategy: str = "auto"  # auto|fill|contour|centerline (modo avançado)
    shading_intensity: float = 0.5  # RESERVADO (experimental, sem efeito no pipeline)
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
    hotkey_start: str = "f9"
    hotkey_pause: str = "f10"
    hotkey_cancel: str = "esc"

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "ExecutionSettings":
        base = ExecutionSettings()
        for k, v in (data or {}).items():
            if hasattr(base, k):
                setattr(base, k, v)
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
