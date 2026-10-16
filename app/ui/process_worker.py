"""Processamento fora da thread da interface (Fase 5.3).

Imagens complexas podem gerar milhares de traços (ordenação O(n²));
rodar isso no clique do slider congelaria a UI por segundos. O worker
executa `process_to_plan` + `check_quality` numa QThread dedicada.

Protocolo: a MainWindow envia (gen, gray_copia, settings) pelo sinal
`_Signals.process`; o worker responde `done`/`failed` com o mesmo `gen`.
Gerações antigas são descartadas pela janela (nunca substituem o
resultado mais recente). Entradas são cópias — o worker nunca toca em
estado da UI.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, Signal, Slot

from app.core.pipeline import process_to_plan
from app.core.quality_checker import check_quality
from app.models.settings import ProcessingSettings


class ProcessWorker(QObject):
    done = Signal(int, object, object, object)  # gen, mask, plan, report
    failed = Signal(int, str)  # gen, mensagem
    progress_ms = Signal(int, float)  # gen, tempo de processamento em ms

    @Slot(int, object, object)
    def request(self, gen: int, gray, settings: ProcessingSettings):
        t0 = time.perf_counter()
        try:
            mask, plan = process_to_plan(gray, settings)
            # Espessura da verificação acompanha o espaçamento (mesma regra
            # da prévia de simulação): spacing 4 → espessura 2.
            thickness = max(1, int(round(max(1, settings.fill_spacing) / 2)))
            rep = check_quality(plan, mask, thickness=thickness, gray=gray)
        except Exception as e:
            self.failed.emit(gen, str(e))
            return
        ms = (time.perf_counter() - t0) * 1000.0
        self.progress_ms.emit(gen, ms)
        self.done.emit(gen, mask, plan, rep)
