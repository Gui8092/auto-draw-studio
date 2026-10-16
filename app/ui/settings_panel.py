"""Painel de processamento com controles interativos."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QFormLayout, QGroupBox,
                               QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from app.core.strategy import PROFILE_NAMES, STRATEGIES, apply_profile
from app.models.settings import ProcessingSettings
from app.ui.widgets import LabeledSlider

CUSTOM_PROFILE = "Personalizado"


class SettingsPanel(QWidget):
    settings_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lock = False
        self.s = ProcessingSettings()
        lay = QVBoxLayout(self)
        box = QGroupBox("Processamento")
        form = QFormLayout(box)

        self.method = QComboBox()
        self.method.addItems(["global", "otsu", "adaptive"])
        self.method.setToolTip("global: limiar fixo · otsu: automático · adaptive: local")
        self.method.currentTextChanged.connect(self._emit)

        self.threshold = self._slider(0, 255, self.s.threshold, "Pixels mais escuros que o limiar viram tinta.",
                                          fmt=lambda v: f"{v}", tick_step=25)
        self.brightness = self._slider(-100, 100, 0, "Ajuste de brilho antes da binarização.",
                                       fmt=lambda v: f"{v:+d}", tick_step=25)
        self.contrast = self._slider(50, 200, 100, "Contraste ×0.5…×2.0.",
                                     fmt=lambda v: f"×{v / 100:.2f}")
        self.gamma = self._slider(20, 300, 100, "Gama ×0.2…×3.0 (/100).",
                                  fmt=lambda v: f"×{v / 100:.2f}")
        self.denoise = self._slider(0, 5, 0, "Redução de ruído.",
                                    fmt=lambda v: f"{v}")
        self.morph = QComboBox()
        self.morph.addItems(["none", "open", "close", "erode", "dilate"])
        self.morph.setToolTip("open: remove pontos · close: conecta falhas pequenas")
        self.morph.currentTextChanged.connect(self._emit)
        self.fill_spacing = self._slider(2, 10, self.s.fill_spacing, "Espaçamento das linhas de preenchimento (px).",
                                         fmt=lambda v: f"{v} px")
        self.min_detail = self._slider(0, 500, int(self.s.min_detail_area), "Área mínima p/ detalhe (remove fiapos).",
                                        fmt=lambda v: f"{v} px", tick_step=100)
        self.simplify = self._slider(0, 50, 10, "Simplificação das trajetórias (÷10).",
                                     fmt=lambda v: f"÷{v / 10:.1f}")
        self.strategy = QComboBox()
        self.strategy.addItems(list(STRATEGIES))
        self.strategy.setToolTip(
            "auto: por região (fino→linha central, sólido→zigue-zague) · "
            "fill: só preenchimento · contour: só contornos · "
            "centerline: só linhas centrais")
        self.strategy.currentTextChanged.connect(self._emit)
        self.profile = QComboBox()
        self.profile.addItems([CUSTOM_PROFILE] + list(PROFILE_NAMES))
        self.profile.setToolTip("Perfil: ajusta os parâmetros acima de uma vez.")
        # Estado inicial = padrões = preset "equilibrado" (vazio por construção).
        # Definido ANTES de conectar o sinal: evita aplicar preset com
        # controles ainda em construção (ex.: invert_btn inexistente).
        self.profile.setCurrentText("equilibrado")
        self.profile.currentTextChanged.connect(self._apply_profile)
        self.invert_btn = QPushButton("Inverter P/B")
        self.invert_btn.setCheckable(True)
        self.invert_btn.clicked.connect(self._emit)
        self.reset_btn = QPushButton("Restaurar padrões")
        self.reset_btn.clicked.connect(self.reset_defaults)

        form.addRow("Método", self.method)
        form.addRow("Limiar", self.threshold)
        form.addRow("Brilho", self.brightness)
        form.addRow("Contraste", self.contrast)
        form.addRow("Gama", self.gamma)
        form.addRow("Ruído", self.denoise)
        form.addRow("Morfologia", self.morph)
        form.addRow("Espaç. preench.", self.fill_spacing)
        form.addRow("Detalhe mín.", self.min_detail)
        form.addRow("Simplificação", self.simplify)
        form.addRow("Estratégia", self.strategy)
        form.addRow("Perfil", self.profile)
        form.addRow(self.invert_btn)
        form.addRow(self.reset_btn)
        lay.addWidget(box)
        lay.addStretch(1)

    def _slider(self, lo, hi, val, tip, fmt=None, tick_step=0):
        sl = LabeledSlider(lo, hi, val, tip, fmt=fmt, tick_step=tick_step)
        sl.valueChanged.connect(self._emit)
        return sl

    def _emit(self, *a):
        if not self._lock:
            self._mark_custom()
            self.settings_changed.emit()

    def _mark_custom(self):
        """Indica que os controles divergiram de qualquer preset.

        Chamado apenas por mudanças manuais (`_emit` sem `_lock`).
        `blockSignals` evita loop com `currentTextChanged`.
        """
        if self.profile.currentText() == CUSTOM_PROFILE:
            return
        self.profile.blockSignals(True)
        try:
            self.profile.setCurrentText(CUSTOM_PROFILE)
        finally:
            self.profile.blockSignals(False)

    def _apply_profile(self, name: str):
        if self._lock:
            return
        if name == CUSTOM_PROFILE:
            return  # rótulo neutro selecionado manualmente: não reconfigura nada
        vals = apply_profile(self.values(), name)
        self._lock = True
        try:
            self.method.setCurrentText(vals.method)
            self.threshold.setValue(int(vals.threshold))
            self.brightness.setValue(int(vals.brightness))
            self.contrast.setValue(int(round(vals.contrast * 100)))
            self.gamma.setValue(int(round(vals.gamma * 100)))
            self.denoise.setValue(int(vals.denoise))
            self.morph.setCurrentText(vals.morph_op)
            self.fill_spacing.setValue(int(vals.fill_spacing))
            self.min_detail.setValue(int(vals.min_detail_area))
            self.simplify.setValue(int(round(vals.simplify_epsilon * 10)))
            if hasattr(vals, "strategy"):
                self.strategy.setCurrentText(vals.strategy)
        finally:
            self._lock = False
        self.settings_changed.emit()

    def values(self) -> ProcessingSettings:
        return ProcessingSettings(
            threshold=self.threshold.value(),
            method=self.method.currentText(),
            brightness=self.brightness.value(),
            contrast=self.contrast.value() / 100.0,
            gamma=self.gamma.value() / 100.0,
            denoise=self.denoise.value(),
            invert=self.invert_btn.isChecked(),
            morph_op=self.morph.currentText(),
            fill_spacing=self.fill_spacing.value(),
            min_detail_area=float(self.min_detail.value()),
            simplify_epsilon=self.simplify.value() / 10.0,
            strategy=self.strategy.currentText(),
        )

    def reset_defaults(self):
        self._lock = True
        d = ProcessingSettings()
        self.method.setCurrentText(d.method)
        self.threshold.setValue(d.threshold)
        self.brightness.setValue(0)
        self.contrast.setValue(100)
        self.gamma.setValue(100)
        self.denoise.setValue(0)
        self.morph.setCurrentText("none")
        self.fill_spacing.setValue(d.fill_spacing)
        self.min_detail.setValue(int(d.min_detail_area))
        self.simplify.setValue(10)
        self.strategy.setCurrentText("auto")
        self.invert_btn.setChecked(False)
        # Padrões == preset "equilibrado" (vazio por construção).
        self.profile.setCurrentText("equilibrado")
        self._lock = False
        self.settings_changed.emit()
