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

# Campos do ProcessingSettings controlados pelo painel (o resto é fixo).
_PANEL_FIELDS = (
    "threshold", "method", "brightness", "contrast", "gamma", "denoise",
    "morph_op", "morph_kernel", "min_detail_area", "fill_spacing",
    "thin_line_px", "simplify_epsilon", "strategy", "invert",
)


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
        self.contrast = self._slider(50, 200, 100, "Contraste ×0.5…×2.0 (pivô no meio-tom).",
                                     fmt=lambda v: f"×{v / 100:.2f}")
        self.gamma = self._slider(20, 300, 100, "Gama ×0.2…×3.0 (/100).",
                                  fmt=lambda v: f"×{v / 100:.2f}")
        self.denoise = self._slider(0, 5, 0, "Redução de ruído.",
                                    fmt=lambda v: f"{v}")
        self.morph = QComboBox()
        self.morph.addItems(["none", "open", "close", "erode", "dilate"])
        self.morph.setToolTip("open: remove pontos · close: conecta falhas pequenas")
        self.morph.currentTextChanged.connect(self._emit)
        self.morph_kernel = QComboBox()
        self.morph_kernel.addItems(["3", "5", "7"])
        self.morph_kernel.setToolTip("Tamanho do elemento estrutural da morfologia.")
        self.morph_kernel.currentTextChanged.connect(self._emit)
        self.fill_spacing = self._slider(2, 10, self.s.fill_spacing, "Espaçamento das linhas de preenchimento (px).",
                                         fmt=lambda v: f"{v} px")
        self.thin_line = self._slider(2, 12, int(self.s.thin_line_px),
                                      "Largura (px) em que um traço vira 'sólido'.",
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
        self.work_size = QComboBox()
        self.work_size.addItems(["256", "512", "1024", "1536", "2048"])
        self.work_size.setToolTip("Resolução de trabalho: a imagem é reduzida "
                                   "para este tamanho antes do processamento.")
        self.work_size.setCurrentText(str(int(self.s.max_work_size)))
        self.work_size.currentTextChanged.connect(self._emit)
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
        form.addRow("Elem. estrut.", self.morph_kernel)
        form.addRow("Espaç. preench.", self.fill_spacing)
        form.addRow("Linha ≤", self.thin_line)
        form.addRow("Detalhe mín.", self.min_detail)
        form.addRow("Simplificação", self.simplify)
        form.addRow("Estratégia", self.strategy)
        form.addRow("Resolução", self.work_size)
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

    # ------------------------------------------------------------------
    # Perfil: o rótulo DESCREVE o estado (não só detecta mudança)
    # ------------------------------------------------------------------
    def _matching_profile(self) -> str:
        """Nome do preset que bate exatamente com os controles.

        Compara com o preset aplicado sobre os PADRÕES (e não sobre os
        valores atuais): um preset define só alguns campos, então
        comparar sobre os valores atuais dava falsos positivos.
        """
        vals = self.values()
        for name in PROFILE_NAMES:
            if vals == apply_profile(ProcessingSettings(), name):
                return name
        return CUSTOM_PROFILE

    def _mark_custom(self):
        """Atualiza o rótulo do perfil para refletir os controles.

        Chamado por mudanças manuais (`_emit` sem `_lock`).
        `blockSignals` evita loop com `currentTextChanged`.
        """
        match = self._matching_profile()
        if self.profile.currentText() == match:
            return
        self.profile.blockSignals(True)
        try:
            self.profile.setCurrentText(match)
        finally:
            self.profile.blockSignals(False)

    def _apply_profile(self, name: str):
        if self._lock:
            return
        if name == CUSTOM_PROFILE:
            return  # rótulo neutro selecionado manualmente: não reconfigura nada
        # Aplica o preset sobre os PADRÕES (e não sobre os valores
        # atuais): assim cada preset é uma configuração COMPLETA e
        # "equilibrado" restaura de fato os padrões.
        vals = apply_profile(ProcessingSettings(), name)
        self.set_values(vals)
        self.settings_changed.emit()

    # ------------------------------------------------------------------
    # Valores
    # ------------------------------------------------------------------
    def values(self) -> ProcessingSettings:
        """Configuração atual dos controles (round-trip completo)."""
        return ProcessingSettings(
            threshold=self.threshold.value(),
            method=self.method.currentText(),
            brightness=self.brightness.value(),
            contrast=self.contrast.value() / 100.0,
            gamma=self.gamma.value() / 100.0,
            denoise=self.denoise.value(),
            invert=self.invert_btn.isChecked(),
            morph_op=self.morph.currentText(),
            morph_kernel=int(self.morph_kernel.currentText() or 3),
            min_detail_area=float(self.min_detail.value()),
            fill_spacing=self.fill_spacing.value(),
            thin_line_px=float(self.thin_line.value()),
            simplify_epsilon=self.simplify.value() / 10.0,
            strategy=self.strategy.currentText(),
            max_work_size=int(self.work_size.currentText() or 512),
        )

    def set_values(self, s: ProcessingSettings):
        """Aplica uma configuração nos controles (sem emitir sinais)."""
        self._lock = True
        try:
            self.method.setCurrentText(s.method)
            self.threshold.setValue(int(s.threshold))
            self.brightness.setValue(int(s.brightness))
            self.contrast.setValue(int(round(s.contrast * 100)))
            self.gamma.setValue(int(round(s.gamma * 100)))
            self.denoise.setValue(int(s.denoise))
            self.morph.setCurrentText(s.morph_op)
            self.morph_kernel.setCurrentText(str(int(s.morph_kernel)))
            self.fill_spacing.setValue(int(s.fill_spacing))
            self.thin_line.setValue(int(round(s.thin_line_px)))
            self.min_detail.setValue(int(s.min_detail_area))
            self.simplify.setValue(int(round(s.simplify_epsilon * 10)))
            self.strategy.setCurrentText(s.strategy)
            self.work_size.setCurrentText(str(int(s.max_work_size)))
            self.invert_btn.setChecked(bool(s.invert))
            # O rótulo do perfil reflete o que foi aplicado.
            self.profile.blockSignals(True)
            try:
                self.profile.setCurrentText(self._matching_profile())
            finally:
                self.profile.blockSignals(False)
        finally:
            self._lock = False

    def reset_defaults(self):
        """Restaura os padrões (e o rótulo do perfil coerente)."""
        self.set_values(ProcessingSettings())
        self.settings_changed.emit()
