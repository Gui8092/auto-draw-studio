"""Processamento fora da thread da interface (Fase 5.3).

Imagens complexas podem gerar milhares de traços (ordenação O(n²));
rodar isso no clique do slider congelaria a UI por segundos. O worker
executa `process_to_plan` + `check_quality` numa QThread dedicada.

Protocolo: a MainWindow envia (gen, gray_copia, settings) pelo sinal
`_Signals.process`; o worker responde `done`/`failed` com o mesmo `gen`.
Gerações antigas são descartadas pela janela (nunca substituem o
resultado mais recente). Entradas são cópias — o worker nunca toca em
estado da UI.

Cancelamento cooperativo: `request_stop()` marca a interrupção; o
pipeline consulta `cancel_check` entre as etapas e dentro dos laços
longos e levanta `ProcessingCancelled`. Isso permite um encerramento
SEGURO (sem `QThread.terminate()`, que aborta o processo).
"""
from __future__ import annotations

import threading
import time

from PySide6.QtCore import QObject, Signal, Slot

from app.core.pipeline import ProcessingCancelled, process_to_plan
from app.core.quality_checker import check_quality
from app.models.settings import ProcessingSettings


class ProcessWorker(QObject):
    done = Signal(int, object, object, object)  # gen, mask, plan, report
    failed = Signal(int, str)  # gen, mensagem
    progress_ms = Signal(int, float)  # gen, tempo de processamento em ms
    cancelled = Signal(int)  # gen, cancelado cooperativamente

    def __init__(self, parent=None):
        super().__init__(parent)
        # Evento (não bool) para leitura segura entre threads.
        self._stop = threading.Event()

    def request_stop(self):
        """Pede o cancelamento cooperativo da tarefa em andamento."""
        self._stop.set()

    def clear_stop(self):
        """Libera o cancelamento (nova tarefa)."""
        self._stop.clear()

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()

    @Slot(int, object, object)
    def request(self, gen: int, gray, settings: ProcessingSettings):
        t0 = time.perf_counter()
        try:
            mask, plan = process_to_plan(gray, settings,
                                         cancel_check=self._stop.is_set)
        except ProcessingCancelled:
            self.cancelled.emit(gen)
            return
        except Exception as e:
            self.failed.emit(gen, str(e))
            return
        try:
            # Espessura da verificação acompanha o espaçamento (mesma regra
            # da prévia de simulação): spacing 4 → espessura 2.
            thickness = max(1, int(round(max(1, settings.fill_spacing) / 2)))
            rep = check_quality(plan, mask, thickness=thickness, gray=gray,
                                strategy=getattr(settings, "strategy", None))
        except Exception as e:
            self.failed.emit(gen, str(e))
            return
        ms = (time.perf_counter() - t0) * 1000.0
        self.progress_ms.emit(gen, ms)
        self.done.emit(gen, mask, plan, rep)
