"""Preview de imagem com zoom e ajuste à tela."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


def numpy_to_pixmap(arr: np.ndarray) -> QPixmap:
    if arr.ndim == 2:
        h, w = arr.shape
        qimg = QImage(arr.data, w, h, w, QImage.Format_Grayscale8).copy()
    else:
        h, w, _ = arr.shape
        data = np.ascontiguousarray(arr)
        qimg = QImage(data.data, w, h, 3 * w, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


class ImagePreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._base: QPixmap | None = None
        self._zoom = 1.0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel("Nenhuma imagem")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setMinimumSize(200, 200)
        self.label.setStyleSheet("background:#101013; border-radius:8px;")
        layout.addWidget(self.label, 1)
        bar = QHBoxLayout()
        for text, slot in [("−", self.zoom_out), ("Ajustar", self.fit),
                           ("100%", self.zoom_reset), ("+", self.zoom_in)]:
            b = QPushButton(text)
            b.setFixedWidth(70)
            b.clicked.connect(slot)
            bar.addWidget(b)
        bar.addStretch(1)
        wrap = QFrame()
        wrap.setLayout(bar)
        layout.addWidget(wrap)

    def set_image(self, arr: np.ndarray | None):
        if arr is None:
            self._base = None
            self.label.setText("Nenhuma imagem")
            self.label.setPixmap(QPixmap())
            return
        self._base = numpy_to_pixmap(arr)
        self._zoom = 1.0
        self.fit()

    def _apply(self):
        if self._base is None:
            return
        target = self.label.size()
        pm = self._base.scaled(
            int(target.width() * self._zoom), int(target.height() * self._zoom),
            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.label.setPixmap(pm)

    def fit(self):
        self._zoom = 1.0
        if self._base is None:
            return
        t, b = self.label.size(), self._base.size()
        if t.width() <= 0 or b.width() <= 0:
            return
        s = min(t.width() / b.width(), t.height() / b.height())
        self._zoom = max(0.05, min(s, 4.0))
        self._apply()

    def zoom_in(self):
        self._zoom = min(8.0, self._zoom * 1.25)
        self._apply()

    def zoom_out(self):
        self._zoom = max(0.05, self._zoom / 1.25)
        self._apply()

    def zoom_reset(self):
        self._zoom = 1.0
        self._apply()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply()
