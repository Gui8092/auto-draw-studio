"""Janela principal do Auto Draw Studio."""
from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QSettings, QThread, QTimer, Signal, QObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QCheckBox, QDoubleSpinBox, QFileDialog, QFrame,
                               QGroupBox, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QProgressBar, QPushButton, QScrollArea, QSpinBox, QSplitter,
                               QStatusBar, QTabWidget, QTextEdit, QVBoxLayout,
                               QWidget)

from app.automation.coordinate_mapper import CoordinateMapper
from app.automation.execution_controller import ExecState, ExecutionController
from app.automation.hotkeys import GlobalHotkeys
from app.automation.mouse_executor import MouseExecutor, PyAutoGuiBackend
from app.automation.screen_calibration import (ScreenArea, fit_scale,
                                            validate_area)
from app.core.image_loader import load_image
from app.core.quality_checker import rasterize_plan
from app.models.drawing_plan import DrawingPlan, StrokeType
from app.models.settings import AppSettings
from app.ui.canvas_selector import CanvasSelector
from app.ui.image_preview import ImagePreview
from app.ui.path_preview import PathPreview
from app.ui.process_worker import ProcessWorker
from app.ui.settings_panel import SettingsPanel
from app.ui.styles import DARK_QSS
from app.utils.logging_setup import setup_logging
from app.utils.persistence import (load_project, load_settings,
                                   save_project as save_project_file,
                                   save_settings)

log = setup_logging()

# Threads de processamento que não puderam ser encerradas a tempo.
# Mantidas vivas aqui para que o COLLECT do Python não destrua uma
# QThread em execução (o Qt aborta o processo: 0xC0000409).
_ORPHAN_THREADS: list = []


def clamp_countdown(seconds: int | float) -> int:
    """Contagem regressiva válida em 1..30s (campo antes ignorado)."""
    try:
        return max(1, min(30, int(seconds)))
    except (TypeError, ValueError):
        return 5


def app_icon() -> QIcon:
    """Ícone do app (funciona em dev e no bundle PyInstaller)."""
    import sys
    base = getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])
    for name in ("assets/icon.ico", "assets/icon.png"):
        p = Path(base) / name
        if p.exists():
            return QIcon(str(p))
    return QIcon()


class _Signals(QObject):
    state = Signal(str)
    progress = Signal(int, int)
    message = Signal(str)
    process = Signal(int, object, object)  # gen, gray (cópia), settings


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Auto Draw Studio")
        self.setWindowIcon(app_icon())
        # Tamanho inicial confortável, limitado à tela disponível (antes:
        # 1280×800 fixos, grande demais em telas menores).
        try:
            avail = QApplication.primaryScreen().availableGeometry()
            self.resize(min(1180, max(900, avail.width() - 120)),
                        min(760, max(600, avail.height() - 120)))
        except Exception:
            self.resize(1180, 760)
        self._auto_minimized = False  # showNormal só se nós minimizamos
        self.settings = load_settings()
        self.image_path: str | None = None
        self.gray: np.ndarray | None = None
        self.rgb: np.ndarray | None = None
        self.mask: np.ndarray | None = None
        self.plan: DrawingPlan | None = None
        self.area: ScreenArea | None = None
        self._selector: CanvasSelector | None = None
        # Durante o encerramento, callbacks tardios do worker não devem
        # tocar nos widgets. Verificado em `_on_processed`/`_on_process_failed`.
        self._closing = False
        # Guarda de reentrância do closeEvent (o loop de espera processa
        # eventos Qt; um segundo closeEvent não pode entrar de novo).
        self._in_close = False

        self.signals = _Signals()
        self.signals.state.connect(self._on_state)
        self.signals.progress.connect(self._on_progress)
        self.signals.message.connect(self._log)
        # Processamento fora da thread da UI (resultados obsoletos descartados).
        self._proc_gen = 0
        self._proc_thread = QThread(self)
        self._worker = ProcessWorker()
        self._worker.moveToThread(self._proc_thread)
        self.signals.process.connect(self._worker.request)
        self._worker.done.connect(self._on_processed)
        self._worker.failed.connect(self._on_process_failed)
        self._worker.cancelled.connect(self._on_process_cancelled)
        self._worker.progress_ms.connect(self._on_proc_time)
        self._proc_thread.start()
        self._exec_t0: float | None = None
        self._last_prog_t: float = 0.0

        try:
            backend = PyAutoGuiBackend()
        except Exception:
            backend = None
        # Sem PyAutoGUI o app não consegue desenhar: usa um backend
        # inerte e AVISA o usuário. Antes, o aviso era logado antes de
        # `_build_ui()` (o `log_view` ainda não existia → o erro era
        # engolido) e a execução "concluía" sem desenhar nada.
        self._real_backend = backend is not None
        from app.automation.mouse_executor import MockBackend
        self.controller = ExecutionController(
            executor=MouseExecutor(backend=backend or MockBackend()),
            on_state=lambda s: self.signals.state.emit(s.value),
            on_progress=lambda d, t: self.signals.progress.emit(d, t),
            on_message=lambda m: self.signals.message.emit(m),
        )
        # countdown_s do settings agora vale de verdade (antes: o campo
        # existia mas o controller usava 5 fixos).
        self.controller.countdown_seconds = clamp_countdown(
            self.settings.execution.countdown_s)
        self.hotkeys = GlobalHotkeys(
            on_start=self.ui_start, on_pause=self.controller.toggle_pause,
            on_resume=self.controller.resume, on_cancel=self.controller.cancel,
        )
        self._build_ui()
        if not self._real_backend:
            self._log0("PyAutoGUI indisponível — execução real desativada.")
        self._apply_settings_to_ui()
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self.reprocess)
        self._restore_layout()
        self._refresh_ready()

    def _app_settings(self) -> QSettings:
        return QSettings("AutoDrawStudio", "AutoDrawStudio")

    def _restore_layout(self):
        """Devolve geometria e divisor da última sessão (Fase E)."""
        try:
            s = self._app_settings()
            g = s.value("geometry")
            if g is not None:
                self.restoreGeometry(g)
            # Se a geometria salva caiu fora de todos os monitores atuais
            # (monitor desplugado, RDP com outra resolução), centraliza na
            # tela primária em vez de "abrir invisível".
            if not any(scr.availableGeometry().intersects(self.frameGeometry())
                       for scr in QApplication.screens()):
                qr = QApplication.primaryScreen().availableGeometry()
                self.move(qr.center() - self.frameGeometry().center())
            sizes = s.value("splitter")
            if sizes is not None:
                self.splitter.setSizes([int(x) for x in sizes])
        except Exception:
            pass

    def _save_layout(self):
        try:
            s = self._app_settings()
            s.setValue("geometry", self.saveGeometry())
            s.setValue("splitter", self.splitter.sizes())
        except Exception:
            pass

    # ---- UI ----
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Cabeçalho: linha 1 identidade + ações; linha 2 etapas do fluxo
        header = QFrame()
        header.setObjectName("card")
        hroot = QVBoxLayout(header)
        hroot.setSpacing(4)
        hl = QHBoxLayout()
        title = QLabel("✏️ Auto Draw Studio")
        title.setObjectName("appTitle")
        sub = QLabel("imagem → traços → mouse")
        sub.setObjectName("subtitle")
        hl.addWidget(title)
        hl.addWidget(sub)
        hl.addStretch(1)
        self.status_dot = QLabel("● pronto")
        hl.addWidget(self.status_dot)
        self.btn_import = QPushButton("⤓ Importar imagem")
        self.btn_import.setObjectName("primary")
        self.btn_import.clicked.connect(self.import_image)
        hl.addWidget(self.btn_import)
        self.btn_save_cfg = QPushButton("💾 Salvar cfg")
        self.btn_save_cfg.clicked.connect(self.save_cfg)
        hl.addWidget(self.btn_save_cfg)
        self.btn_open_proj = QPushButton("📂 Abrir")
        self.btn_open_proj.setToolTip("Abre um projeto salvo (.ads.json): "
                                      "imagem + ajustes + trajetórias.")
        self.btn_open_proj.clicked.connect(self.open_project)
        hl.addWidget(self.btn_open_proj)
        self.btn_save_proj = QPushButton("📁 Projeto")
        self.btn_save_proj.setToolTip("Salva o projeto (imagem + ajustes + "
                                      "trajetórias) em .ads.json.")
        self.btn_save_proj.clicked.connect(self.save_project)
        hl.addWidget(self.btn_save_proj)
        self.btn_export_svg = QPushButton("↗ SVG")
        self.btn_export_svg.setToolTip("Exporta as trajetórias em SVG "
                                       "(revisar/editar fora do app).")
        self.btn_export_svg.clicked.connect(self.export_svg)
        hl.addWidget(self.btn_export_svg)
        hroot.addLayout(hl)
        steps_row = QHBoxLayout()
        self.step_badges: list = []
        for s in ["1 · Importar", "2 · Ajustar", "3 · Conferir", "4 · Área", "5 · Executar"]:
            b = QLabel(s)
            b.setObjectName("stepTodo")
            steps_row.addWidget(b)
            self.step_badges.append(b)
        steps_row.addStretch(1)
        hroot.addLayout(steps_row)
        root.addWidget(header)

        self.splitter = QSplitter(Qt.Horizontal)
        root.addWidget(self.splitter, 1)

        # Prévias
        self.tabs = QTabWidget()
        self.prev_original = ImagePreview()
        self.prev_bw = ImagePreview()
        self.prev_paths = PathPreview()
        self.prev_sim = ImagePreview()
        self.tabs.addTab(self.prev_original, "Original")
        self.tabs.addTab(self.prev_bw, "Preto e branco")
        self.tabs.addTab(self.prev_paths, "Trajetórias")
        self.tabs.addTab(self.prev_sim, "Simulação")
        self.legend = QLabel("")
        self.legend.setWordWrap(True)
        left = QFrame()
        left.setObjectName("card")
        ll = QVBoxLayout(left)
        ll.addWidget(self.tabs, 1)
        filt = QHBoxLayout()
        filt.setSpacing(4)
        self._kind_boxes = {}
        for kind, text, tip in [(StrokeType.FILL, "fill", "Preenchimento"),
                                (StrokeType.OUTER_CONTOUR, "cont.", "Contornos"),
                                (StrokeType.CENTERLINE, "centro", "Linhas centrais"),
                                (StrokeType.DETAIL, "det.", "Detalhes")]:
            cb = QCheckBox(text)
            cb.setChecked(True)
            cb.setToolTip(f"{tip}: mostra/oculta na prévia.")
            cb.toggled.connect(lambda on, k=kind: self._toggle_kind(k, on))
            filt.addWidget(cb)
            self._kind_boxes[kind] = cb
        self._travel_box = QCheckBox("mov.")
        self._travel_box.setChecked(True)
        self._travel_box.setToolTip("Deslocamentos com o botão solto (tracejado).")
        self._travel_box.toggled.connect(self.prev_paths.set_show_travel)
        filt.addWidget(self._travel_box)
        fit_btn = QPushButton("Ajustar")
        fit_btn.setToolTip("Restaura zoom/pan da prévia de trajetórias.")
        fit_btn.clicked.connect(self.prev_paths.reset_view)
        filt.addWidget(fit_btn)
        filt.addStretch(1)
        ll.addLayout(filt)
        self.prev_paths.setToolTip(
            "Scroll: zoom · botão direito arrastado: pan · duplo-clique: ajustar")
        ll.addWidget(self.legend)
        self.splitter.addWidget(left)

        # Painéis (com rolagem: a janela pode encolher sem cortar conteúdo)
        right = QFrame()
        right.setObjectName("card")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 6, 6, 6)
        self.panel = SettingsPanel()
        self.panel.settings_changed.connect(lambda: self._debounce.start())
        rl.addWidget(self.panel)

        dest_box = QGroupBox("Área de desenho")
        dest_lay = QVBoxLayout(dest_box)
        row1 = QHBoxLayout()
        self.btn_area = QPushButton("◉ Selecionar área")
        self.btn_area.setToolTip("Arraste o retângulo sobre o aplicativo de destino.")
        self.btn_area.clicked.connect(self.select_area)
        row1.addWidget(self.btn_area)
        self.lbl_area = QLabel("área: —")
        row1.addWidget(self.lbl_area, 1)
        dest_lay.addLayout(row1)
        rl.addWidget(dest_box)

        exec_box = QGroupBox("Execução")
        exec_lay = QVBoxLayout(exec_box)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Velocidade px/s:"))
        self.spin_speed = QSpinBox()
        self.spin_speed.setRange(100, 8000)
        self.spin_speed.setToolTip("Velocidade real dos traços. Valores muito altos "
                                     "esbarram no mínimo do sistema por chamada.")
        self.spin_speed.setValue(int(self.settings.execution.move_speed_px_s))
        row2.addWidget(self.spin_speed)
        row2.addWidget(QLabel("Atraso s:"))
        self.spin_delay = QDoubleSpinBox()
        self.spin_delay.setRange(0.0, 1.0)
        self.spin_delay.setSingleStep(0.01)
        self.spin_delay.setToolTip("Pausa entre traços (levantar/pressionar o mouse).")
        self.spin_delay.setValue(float(self.settings.execution.stroke_delay_s))
        row2.addWidget(self.spin_delay)
        row2.addWidget(QLabel("Pincel px:"))
        self.spin_brush = QSpinBox()
        self.spin_brush.setRange(0, 30)
        self.spin_brush.setToolTip("Espessura do pincel do app de destino "
                                   "(0 = automático). A prévia de simulação "
                                   "passa a prever o traço real.")
        self.spin_brush.setValue(int(self.settings.execution.brush_px))
        row2.addWidget(self.spin_brush)
        exec_lay.addLayout(row2)

        self.lbl_stats = QLabel("traços: — · tempo est.: —")
        exec_lay.addWidget(self.lbl_stats)

        row3 = QHBoxLayout()
        self.btn_start = QPushButton("▶ Iniciar (F9)")
        self.btn_start.setObjectName("primary")
        self.btn_start.setToolTip(
            f"Começa após {self.controller.countdown_seconds} s de "
            "contagem regressiva (F9).")
        self.btn_start.clicked.connect(self.ui_start)
        self.btn_pause = QPushButton("⏸ Pausar")
        self.btn_pause.setToolTip("Pausa contagem ou desenho (F10 alterna "
                                  "pausar/retomar).")
        self.btn_pause.clicked.connect(self.controller.pause)
        self.btn_resume = QPushButton("▶ Retomar")
        self.btn_resume.setToolTip("Continua de onde parou (F11).")
        self.btn_resume.clicked.connect(self.controller.resume)
        self.btn_cancel = QPushButton("✖ Cancelar")
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.setToolTip("Interrompe imediatamente e solta o mouse (Esc).")
        self.btn_cancel.clicked.connect(self.controller.cancel)
        for b in (self.btn_start, self.btn_pause, self.btn_resume, self.btn_cancel):
            row3.addWidget(b)
        exec_lay.addLayout(row3)

        self.progress = QProgressBar()
        exec_lay.addWidget(self.progress)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(110)
        # Sem teto, o log crescia sem limite: cada reprocessamento
        # re-appendava os avisos (4x por segundo ao mexer no slider).
        self.log_view.document().setMaximumBlockCount(500)
        exec_lay.addWidget(self.log_view)
        rl.addWidget(exec_box)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(right)
        scroll.setMinimumWidth(300)
        self.splitter.addWidget(scroll)
        self.splitter.setSizes([800, 480])
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setChildrenCollapsible(False)

        self.setStatusBar(QStatusBar())

    def _apply_settings_to_ui(self):
        ex = self.settings.execution
        self.spin_speed.setValue(int(ex.move_speed_px_s))
        self.spin_delay.setValue(float(ex.stroke_delay_s))
        self.spin_brush.setValue(int(ex.brush_px))
        # A configuração de PROCESSAMENTO salva também precisa voltar
        # para o painel. Antes, o painel nascia sempre nos padrões e o
        # "Salvar cfg" sobrescrevia o arquivo com os padrões — o
        # config de processamento era inútil.
        try:
            self.panel.set_values(self.settings.processing)
        except Exception as e:
            self._log0(f"Não foi possível aplicar as configurações salvas: {e}")

    # ---- Fluxo ----
    def import_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar imagem", "",
            "Imagens (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        try:
            loaded = load_image(path, max_size=self.panel.values().max_work_size)
        except Exception as e:
            QMessageBox.warning(self, "Erro", str(e))
            return
        self.image_path = path
        self.rgb = loaded.rgb
        self.gray = loaded.gray
        self.prev_original.set_image(self.rgb)
        self._log(f"Imagem carregada: {Path(path).name} ({loaded.width}×{loaded.height})")
        self.reprocess()

    def reprocess(self):
        """Enfileira o processamento no worker (não bloqueia a interface)."""
        if self.gray is None or self._closing:
            return
        self._proc_gen += 1
        self.status_dot.setText("● processando…")
        try:
            self.signals.process.emit(self._proc_gen, self.gray.copy(),
                                      self.panel.values())
        except Exception as e:
            self._log(f"Erro no processamento: {e}")

    def _on_process_failed(self, gen: int, msg: str):
        if self._closing or gen != self._proc_gen:
            return  # encerrando ou obsoleto
        self.status_dot.setText("● erro")
        self._log(f"Erro no processamento: {msg}")
        self._refresh_ready()

    def _on_process_cancelled(self, gen: int):
        """Processamento cancelado cooperativamente (ex.: fim do app)."""
        if self._closing or gen != self._proc_gen:
            return
        self.status_dot.setText("● cancelado")
        self._log("Processamento cancelado.")
        self._refresh_ready()

    def _on_processed(self, gen, mask, plan, rep):
        if self._closing or gen != self._proc_gen:
            return  # encerrando ou resultado obsoleto: descarta sem tocar na UI
        self.mask = mask
        self.plan = plan
        self.prev_bw.set_image((mask))
        self.prev_paths.set_plan(plan)
        self.legend.setText(self.prev_paths.legend())
        # Espessura da simulação: o pincel do app de destino quando
        # informado; senão, a heurística (≈ metade do espaçamento:
        # linhas próximas com traço fino deixam sulcos, linhas afastadas
        # com traço grosso cobrem mais).
        sim_thickness = self._effective_brush_px(plan)
        sim = rasterize_plan(plan, thickness=sim_thickness)
        # Simulação: fundo branco + traços pretos
        sim_rgb = np.stack([(255 - sim)] * 3, axis=-1).astype(np.uint8)
        self.prev_sim.set_image(sim_rgb)
        for w in rep.warnings:
            self._log(f"⚠ {w}")
        for note in getattr(plan, "strategy_notes", [])[:6]:
            self._log(f"· {note}")
        from app.models.drawing_plan import StrokeType as _ST
        nfill = len(plan.strokes_by_kind(_ST.FILL))
        ncen = len(plan.strokes_by_kind(_ST.CENTERLINE))
        ncon = (len(plan.strokes_by_kind(_ST.OUTER_CONTOUR))
                + len(plan.strokes_by_kind(_ST.INNER_CONTOUR)))
        dur = plan.estimate_duration(self.spin_speed.value(), self.spin_delay.value(),
                                    scale=fit_scale(self.area, plan.image_width,
                                                    plan.image_height))
        area_txt = (f"{self.area.width}×{self.area.height}"
                    if self.area is not None else "—")
        self.lbl_stats.setText(
            f"traços: {plan.total_strokes} (fill {nfill} · centro {ncen} · "
            f"contorno {ncon}) · cobertura: {rep.coverage:.0%} · "
            f"tempo est.: {dur:.0f}s · área: {area_txt}")
        self.progress.setMaximum(max(1, plan.total_strokes))
        self.progress.setValue(0)
        self.status_dot.setText("● pronto")
        self._refresh_ready()

    def _refresh_ready(self, state: str | None = None):
        """Habilita Iniciar só com plano válido + área calibrada (Fase 6.4)."""
        ok, _ = validate_area(self.area, self.plan is not None
                              and self.plan.total_strokes > 0)
        self.btn_start.setEnabled(bool(ok) and not self.controller.is_busy)
        self._update_buttons(state if state is not None
                             else self.controller.state.value)
        self._update_steps()

    def _update_buttons(self, state: str):
        """Botões de execução refletem o estado.

        Antes, "Pausar", "Retomar" e "Cancelar" ficavam clicáveis
        sempre e o clique não fazia nada (sem qualquer indicação).
        """
        self.btn_pause.setEnabled(state in ("countdown", "running"))
        self.btn_resume.setEnabled(state == "paused")
        self.btn_cancel.setEnabled(state in ("countdown", "running", "paused"))

    def _update_steps(self):
        """Badges de etapa 1–5 (importar → ajustar → conferir → área → executar)."""
        cur = 0
        if self.gray is not None:
            cur = 1
        if self.plan is not None and self.plan.total_strokes > 0:
            cur = 2
        ok_area, _ = validate_area(self.area, True)
        if ok_area:
            cur = 3
        if self.controller.is_busy:
            cur = 4
        for i, b in enumerate(self.step_badges):
            b.setObjectName("stepActive" if i == cur
                            else "stepDone" if i < cur else "stepTodo")
            b.style().unpolish(b)
            b.style().polish(b)

    def select_area(self):
        """Abre o seletor de forma assíncrona (sem loop de espera ativa).

        O resultado chega via `CanvasSelector.selection_done` em
        `_on_area_selected`. Seleções simultâneas são ignoradas.
        A referência ativa só é registrada após a conexão do sinal;
        falhas na configuração são registradas e não prendem o estado.
        """
        if self._selector is not None:
            self._log("Seleção de área já em andamento.")
            return
        sel = CanvasSelector()
        try:
            sel.selection_done.connect(self._on_area_selected)
        except Exception as e:
            self._log(f"Falha ao iniciar seleção de área: {e}")
            try:
                sel.deleteLater()
            except Exception:
                pass
            return
        self._selector = sel
        self.hide()
        try:
            sel.start()
        except Exception as e:
            self._selector = None
            try:
                sel.deleteLater()
            except Exception:
                pass
            self.show()
            self._log(f"Falha ao abrir seletor de área: {e}")

    def _toggle_kind(self, kind, on: bool):
        self.prev_paths.set_kind_visible(kind, on)

    def _on_area_selected(self, area):
        self._selector = None
        self.show()
        self.raise_()
        if area is not None and area.is_valid:
            self.area = area
            self.lbl_area.setText(
                f"área: {self.area.width}×{self.area.height} @({self.area.x},{self.area.y})")
            self._log(f"Área calibrada: {self.area}")
        else:
            self._log("Seleção de área cancelada.")
        self._refresh_ready()

    def ui_start(self):
        ok, msg = validate_area(self.area, self.plan is not None and self.plan.total_strokes > 0)
        if not ok:
            QMessageBox.warning(self, "Não pronto", msg)
            self._log(f"⛔ {msg}")
            return
        if self.plan is None or self.area is None:
            QMessageBox.warning(self, "Não pronto", "Plano ou área ausente.")
            return
        if not self._real_backend:
            # Sem PyAutoGUI não há como mover o mouse: avisar em vez de
            # "desenhar" com um backend inerte e reportar sucesso.
            QMessageBox.warning(
                self, "Execução indisponível",
                "PyAutoGUI não está disponível neste ambiente.\n"
                "A execução real do mouse está desativada.")
            self._log("⛔ PyAutoGUI indisponível — nada será desenhado.")
            return
        mapper = CoordinateMapper(self.plan.image_width, self.plan.image_height, self.area)
        self.minimize_for_draw()
        started = self.controller.start(
            self.plan, mapper, stroke_delay=self.spin_delay.value(),
            move_speed_px_s=self.spin_speed.value())
        if not started:
            # start() recusou (execução em andamento): desfaz o minimize
            # em vez de largar o usuário sem janela e sem aviso.
            self._auto_minimized = False
            try:
                self.showNormal()
            except Exception:
                pass
            self._log("⛔ Já há um desenho em andamento.")
            self._refresh_ready()

    def minimize_for_draw(self):
        try:
            self._auto_minimized = True
            self.showMinimized()
        except Exception:
            pass

    def restart_hotkeys(self) -> bool:
        """(Re)registra os atalhos globais conforme a configuração atual.

        O listener do pynput é registrado UMA vez no start do app; abrir
        um projeto com atalhos diferentes exigia re-registrar (e sem
        isso a interface mostrava um atalho que não existia).
        """
        bindings = {
            "start": self.settings.execution.hotkey_start,
            "pause": self.settings.execution.hotkey_pause,
            "cancel": self.settings.execution.hotkey_cancel,
        }
        resume_key = (self.settings.execution.hotkey_resume or "").strip()
        if resume_key:
            bindings["resume"] = resume_key
        return self.hotkeys.start(bindings)

    def save_cfg(self):
        self._collect_settings_from_ui()
        save_settings(self.settings)
        self._log("Configurações salvas.")

    def _collect_settings_from_ui(self) -> AppSettings:
        """Configuração EFETIVA (painel + execução).

        Chamado antes de salvar config OU projeto: sem isso o arquivo
        guardava os padrões, não o que o usuário viu na tela (o plano
        do projeto ficava inconsistente com os ajustes gravados).
        """
        self.settings.processing = self.panel.values()
        self.settings.execution.move_speed_px_s = float(self.spin_speed.value())
        self.settings.execution.stroke_delay_s = float(self.spin_delay.value())
        self.settings.execution.brush_px = int(self.spin_brush.value())
        return self.settings

    def _effective_brush_px(self, plan: DrawingPlan) -> int:
        """Espessura usada na prévia de simulação.

        Lê o CONTROLE (e não a config salva): antes, o valor só valia
        depois de "Salvar cfg" — o controle parecia não funcionar.
        """
        brush = int(self.spin_brush.value() or 0)
        if brush > 0:
            return max(1, brush)
        return max(1, int(round(plan.spacing_px / 2)))

    # ---- Projeto / exportação ----
    def save_project(self):
        """Salva imagem + ajustes + trajetórias em um arquivo .ads.json."""
        if self.plan is None or not self.plan.total_strokes:
            QMessageBox.warning(self, "Nada para salvar",
                                "Processe uma imagem antes de salvar o projeto.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Salvar projeto", "", "Projeto Auto Draw (*.ads.json)")
        if not path:
            return
        try:
            # Grava os ajustes ATUAIS (não os salvos antes): o projeto
            # precisa ser internamente consistente (plano + ajustes).
            self._collect_settings_from_ui()
            save_project_file(path, self.image_path or "", self.settings,
                              self.plan.to_dict())
        except Exception as e:
            QMessageBox.warning(self, "Erro ao salvar", str(e))
            self._log(f"⛔ Erro ao salvar projeto: {e}")
            return
        self._log(f"Projeto salvo: {Path(path).name}")

    def open_project(self):
        """Abre um projeto salvo (imagem + ajustes + trajetórias)."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Abrir projeto", "", "Projeto Auto Draw (*.ads.json)")
        if not path:
            return
        try:
            data = load_project(path)
        except Exception as e:
            QMessageBox.warning(self, "Erro ao abrir", str(e))
            self._log(f"⛔ Erro ao abrir projeto: {e}")
            return
        # 1) Ajustes do projeto (processamento + execução).
        try:
            proj_settings = AppSettings.from_dict(data.get("settings", {}))
        except Exception:
            proj_settings = AppSettings()
        self.settings.processing = proj_settings.processing
        self.settings.execution = proj_settings.execution
        try:
            self._apply_settings_to_ui()
            self.controller.countdown_seconds = clamp_countdown(
                self.settings.execution.countdown_s)
        except Exception as e:
            self._log(f"Ajustes do projeto parcialmente aplicados: {e}")
        # Os atalhos globais foram registrados com a configuração
        # ANTERIOR: re-registra (e persiste) para o projeto atual.
        try:
            self.restart_hotkeys()
            save_settings(self.settings)
        except Exception as e:
            self._log(f"⚠ Não foi possível re-registrar os atalhos: {e}")
        # 2) Imagem original.
        img_path = data.get("image_path") or ""
        image_ok = False
        if img_path and Path(img_path).exists():
            try:
                loaded = load_image(img_path,
                                    max_size=self.panel.values().max_work_size)
                self.image_path = img_path
                self.rgb = loaded.rgb
                self.gray = loaded.gray
                self.prev_original.set_image(self.rgb)
                image_ok = True
                self._log(f"Imagem do projeto: {Path(img_path).name} "
                          f"({loaded.width}×{loaded.height})")
            except Exception as e:
                self._log(f"⚠ Não foi possível carregar a imagem do projeto: {e}")
        if not image_ok:
            # Sem a imagem do projeto, a imagem ANTERIOR não pode ficar
            # na tela: o plano do projeto seria desenhado por cima dela
            # (e um "Salvar projeto" gravaria a imagem antiga com o
            # plano novo).
            self.image_path = None
            self.gray = None
            self.rgb = None
            self.mask = None
            self.prev_original.set_image(None)
            self._log("⚠ Imagem do projeto não encontrada — "
                      "apenas as trajetórias serão carregadas.")
        # 3) Trajetórias salvas (evita reprocessar e preserva o que foi
        #    realmente desenhado). Se não baterem com a imagem, reprocessa.
        restored = False
        raw_plan = data.get("plan")
        if isinstance(raw_plan, dict):
            try:
                plan = DrawingPlan.from_dict(raw_plan)
                same_size = (self.gray is not None
                             and plan.image_width == self.gray.shape[1]
                             and plan.image_height == self.gray.shape[0])
                if plan.total_strokes and same_size:
                    self.plan = plan
                    self.prev_paths.set_plan(plan)
                    self.legend.setText(self.prev_paths.legend())
                    self._log(f"Trajetórias restauradas: {plan.total_strokes}")
                    restored = True
                elif plan.total_strokes:
                    self._log("⚠ Trajetórias do projeto não combinam com a "
                              "imagem — serão recalculadas.")
            except Exception as e:
                self._log(f"⚠ Trajetórias do projeto ilegíveis: {e}")
        if not restored and self.gray is not None:
            self.reprocess()
        self._refresh_ready()

    def export_svg(self):
        """Exporta as trajetórias em SVG."""
        if self.plan is None or not self.plan.total_strokes:
            QMessageBox.warning(self, "Nada para exportar",
                                "Processe uma imagem antes de exportar.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar SVG", "", "SVG (*.svg);;Todos (*)")
        if not path:
            return
        try:
            Path(path).write_text(self.plan.to_svg(), encoding="utf-8")
        except Exception as e:
            QMessageBox.warning(self, "Erro ao exportar", str(e))
            self._log(f"⛔ Erro ao exportar SVG: {e}")
            return
        self._log(f"SVG exportado: {Path(path).name}")

    # ---- Slots de execução ----
    def _on_state(self, s: str):
        self.status_dot.setText(f"● {s}")
        if s == "running":
            self._exec_t0 = time.perf_counter()
        if s in ("completed", "cancelled", "error"):
            self._exec_t0 = None
            # Restaura a janela SÓ se fomos nós que minimizamos para desenhar.
            # Antes: qualquer conclusão chamava showNormal() e tirava o
            # usuário da tela cheia/maximizada "do nada".
            if self._auto_minimized:
                self._auto_minimized = False
                try:
                    self.showNormal()
                except Exception:
                    pass
        self._refresh_ready(s)

    def _on_proc_time(self, gen: int, ms: float):
        if self._closing or gen != self._proc_gen:
            return
        try:
            self.statusBar().showMessage(f"Processado em {ms:.0f} ms")
        except Exception:
            pass

    def _on_progress(self, done: int, total: int):
        self.progress.setMaximum(max(1, total))
        self.progress.setValue(done)
        # Throttle do rótulo: sinal chega 1× por traço (centenas/s) e
        # setText a cada evento inundava a UI. Barra atualiza sempre;
        # texto, no máximo a 10 Hz (+ primeiro e último).
        now = time.perf_counter()
        if not (done >= total or done <= 1 or now - self._last_prog_t >= 0.1):
            return
        self._last_prog_t = now
        if self._exec_t0 is not None and done > 0 and total > 0:
            el = time.perf_counter() - self._exec_t0
            # Estimativa restante honesta: ritmo medido, não velocidade nominal.
            # A velocidade real depende da máquina e do app de destino.
            rest = el / done * (total - done) if done < total else 0.0
            base = self.lbl_stats.text().split("· decorrido")[0].rstrip()
            self.lbl_stats.setText(f"{base} · decorrido {el:.0f}s · restam ~{rest:.0f}s")

    def _log(self, msg: str):
        # Contagem regressiva e avisos de execução ficam visíveis também
        # na barra de status (Fase 6.5).
        try:
            if msg.startswith(("Começando em", "Contagem regressiva")):
                self.statusBar().showMessage(msg)
        except Exception:
            pass
        self._log0(msg)

    def _log0(self, msg: str):
        try:
            self.log_view.append(msg)
        except Exception:
            pass
        log.info(msg)

    def closeEvent(self, e):
        if self._in_close:
            # Reentrância: o loop de espera processa eventos Qt; um
            # segundo closeEvent não pode reentrar (aceitar aqui
            # destruiria a janela com as threads vivas).
            e.ignore()
            return
        self._in_close = True
        try:
            self.controller.cancel()
            self.hotkeys.stop()
        except Exception:
            pass
        self._save_layout()
        # Finalização segura: `quit()` não interrompe um slot em execução,
        # então pedimos o cancelamento COOPERATIVO da tarefa e aguardamos
        # o término REAL da thread (sem `terminate()`).
        #
        # Antes: `wait(30000)` na thread da UI (janela "não está
        # respondendo") e, no timeout, `terminate()` — que mata a thread
        # no meio de código Python/OpenCV e aborta o processo
        # (0xC0000409). Agora: o worker consulta a flag de cancelamento
        # entre as etapas e dentro dos laços longos.
        self._closing = True
        try:
            self._worker.request_stop()
            self._proc_thread.requestInterruption()
            self._proc_thread.quit()
            # Espera em fatias curtas, mantendo a interface viva.
            deadline = time.monotonic() + 30.0
            while self._proc_thread.isRunning() and time.monotonic() < deadline:
                QApplication.processEvents()
                self._proc_thread.wait(50)
            if self._proc_thread.isRunning():
                # NÃO destrói uma thread em execução (abort do processo
                # 0xC0000409) e NÃO usa terminate(). Desacopla do pai e
                # guarda a referência num módulo vivo: se o objeto fosse
                # coletado, o Python destruiria a QThread em execução.
                self._log0("Processamento não encerrou em 30s: thread "
                           "desacoplada (encerra com o processo).")
                try:
                    self._proc_thread.setParent(None)
                    _ORPHAN_THREADS.append(self._proc_thread)
                except Exception:
                    pass
        except Exception:
            pass
        # Aguarda o fim REAL do desenho: sem isso o mouse pode continuar
        # se movendo (ou ficar pressionado) depois do app fechar.
        try:
            self.controller.wait_finished(timeout=5.0)
        except Exception:
            pass
        super().closeEvent(e)


def run_app(argv) -> int:
    # Texto nítido em escalas fracionárias do Windows (125%/150%).
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass
    app = QApplication(argv)
    app.setApplicationName("Auto Draw Studio")
    app.setOrganizationName("AutoDrawStudio")
    app.setWindowIcon(app_icon())
    app.setStyleSheet(DARK_QSS)
    w = MainWindow()
    w.show()
    # Atalhos globais (melhor esforço).
    # "pause" é um TOGGLE (pausar/retomar): antes não existia forma de
    # retomar pelo teclado e, com a janela minimizada para desenhar, a
    # pausa virava uma via sem volta.
    try:
        if not w.restart_hotkeys():
            # Antes o resultado era ignorado e os botões continuavam
            # anunciando F9/F10/Esc que nunca funcionariam.
            w._log("⚠ Atalhos globais indisponíveis (pynput ausente ou "
                   "sem permissão). Use os botões.")
    except Exception as e:
        w._log(f"⚠ Atalhos globais indisponíveis: {e}")
    # Garante que o listener do pynput seja parado em qualquer caminho
    # de saída do app (não só quando a janela é fechada).
    try:
        app.aboutToQuit.connect(w.hotkeys.stop)
    except Exception:
        pass
    code = app.exec()
    if any(t.isRunning() for t in _ORPHAN_THREADS):
        # Uma thread de processamento ficou viva: sair SEM o teardown do
        # interpretador. Destruir uma QThread em execução aborta o
        # processo (0xC0000409).
        import os
        import sys

        try:
            sys.stdout.flush()
            sys.stderr.flush()
            for h in list(logging.getLogger().handlers):
                try:
                    h.flush()
                except Exception:
                    pass
        except Exception:
            pass
        os._exit(code)
    return code
