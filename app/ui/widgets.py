"""Widgets reutilizáveis da interface (Fase A: controles com feedback)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QWidget


class LabeledSlider(QWidget):
    """Slider horizontal com label de valor formatado ao lado.

    `fmt` recebe o valor int e devolve o texto (ex.: unidade px, %, ×).
    Emite `valueChanged(int)` como um QSlider comum.
    """

    valueChanged = Signal(int)

    def __init__(self, lo: int, hi: int, val: int, tip: str = "",
                 fmt=None, tick_step: int = 0, parent=None):
        super().__init__(parent)
        self._fmt = fmt or str
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(lo, hi)
        self.slider.setValue(val)
        self.slider.setToolTip(tip)
        if tick_step > 0:
            self.slider.setTickPosition(QSlider.TicksBelow)
            self.slider.setTickInterval(tick_step)
        self.label = QLabel()
        self.label.setToolTip(tip)
        self.label.setMinimumWidth(52)
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.label.setObjectName("sliderValue")
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.label)
        self.slider.valueChanged.connect(self._on_changed)
        self._refresh(val)

    def _on_changed(self, v: int):
        self._refresh(v)
        self.valueChanged.emit(v)

    def _refresh(self, v: int):
        self.label.setText(self._fmt(v))

    # API compatível com QSlider
    def value(self) -> int:
        return self.slider.value()

    def setValue(self, v: int):
        self.slider.setValue(v)

    def setRange(self, lo: int, hi: int):
        self.slider.setRange(lo, hi)
