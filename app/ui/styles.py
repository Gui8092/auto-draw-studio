"""QSS escuro completo para o Auto Draw Studio (Fase B).

Paleta centralizada:
  fundo app #141417 · cards #1d1d21 · bordas #2e2e35 · texto #e8e8ea
  muted #a1a1aa · acento verde #22c55e · perigo #7f1d1d
Cobre todos os widgets usados no fluxo importar → executar, incluindo
diálogos/tooltips nativos que antes vazavam o tema claro.
"""
DARK_QSS = """
* { font-family: 'Segoe UI', sans-serif; }
QMainWindow, QWidget#central { background: #141417; color: #e8e8ea; }
QLabel#appTitle { font-size: 20px; font-weight: 800; color: #ffffff; }
QLabel#subtitle { font-size: 12px; color: #a1a1aa; }
QLabel#sliderValue { font-size: 12px; color: #e4e4e7; font-weight: 600; }
QLabel#stepActive { font-size: 12px; color: #18181b; background: #22c55e;
  border-radius: 9px; padding: 2px 10px; font-weight: 700; }
QLabel#stepTodo { font-size: 12px; color: #71717a; }
QLabel#stepDone { font-size: 12px; color: #4ade80; }
QFrame#card { background: #1d1d21; border: 1px solid #2e2e35; border-radius: 12px; }
QGroupBox { color: #e8e8ea; font-weight: 600; border: 1px solid #2e2e35;
  border-radius: 8px; margin-top: 14px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 6px;
  color: #a1a1aa; }
QPushButton { background: #2a2a30; color: #f4f4f5; border: 1px solid #3f3f46;
  border-radius: 8px; padding: 8px 14px; font-size: 13px; }
QPushButton:hover { background: #34343c; border-color: #52525b; }
QPushButton:pressed { background: #232328; border-color: #52525b; }
QPushButton:disabled { color: #71717a; background: #232328; }
QPushButton:focus { border-color: #22c55e; outline: none; }
QPushButton#primary { background: #f4f4f5; color: #18181b; font-weight: 700; border: none; }
QPushButton#primary:hover { background: #ffffff; }
QPushButton#primary:pressed { background: #d4d4d8; }
QPushButton#primary:disabled { color: #71717a; background: #3f3f46; }
QPushButton#danger { background: #3f1d1d; border-color: #7f1d1d; color: #fecaca; }
QPushButton#danger:hover { background: #4c2323; }
QPushButton#danger:pressed { background: #331414; }
QPushButton:checked { border-color: #22c55e; color: #4ade80; }
QTabWidget::pane { border: 1px solid #2e2e35; border-radius: 8px; background: #1d1d21; }
QTabBar::tab { background: #232328; color: #a1a1aa; padding: 6px 14px;
  border-top-left-radius: 8px; border-top-right-radius: 8px; }
QTabBar::tab:selected { background: #2e2e35; color: #ffffff; }
QTabBar::tab:hover:!selected { color: #e4e4e7; }
QSlider::groove:horizontal { height: 6px; background: #2e2e35; border-radius: 3px; }
QSlider::handle:horizontal { width: 16px; margin: -6px 0; border-radius: 8px; background: #e4e4e7; }
QSlider::handle:horizontal:hover { background: #ffffff; }
QSlider::handle:horizontal:pressed { background: #22c55e; }
QSlider::sub-page:horizontal { background: #3f6212; border-radius: 3px; }
QSlider::tick { background: #52525b; }
QProgressBar { background: #232328; border: 1px solid #2e2e35; border-radius: 6px;
  text-align: center; color: #e4e4e7; height: 16px; }
QProgressBar::chunk { background: #22c55e; border-radius: 5px; }
QTextEdit, QPlainTextEdit { background: #18181b; border: 1px solid #2e2e35;
  border-radius: 8px; color: #e4e4e7; selection-background-color: #3f6212; }
QComboBox, QSpinBox, QDoubleSpinBox { background: #232328; border: 1px solid #3f3f46;
  border-radius: 6px; padding: 4px; color: #f4f4f5; }
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color: #52525b; }
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #22c55e; }
QComboBox QAbstractItemView { background: #232328; color: #f4f4f5;
  selection-background-color: #3f6212; border: 1px solid #3f3f46; }
QToolTip { background: #2a2a30; color: #f4f4f5; border: 1px solid #3f3f46;
  padding: 4px 8px; border-radius: 6px; }
QMessageBox { background: #1d1d21; }
QMessageBox QLabel { color: #e8e8ea; }
QFileDialog { background: #1d1d21; color: #e8e8ea; }
QStatusBar { color: #a1a1aa; }
QStatusBar::item { border: none; }
QScrollBar:vertical, QScrollBar:horizontal { background: #1d1d21; border: none;
  border-radius: 4px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: #3f3f46;
  border-radius: 4px; min-height: 24px; min-width: 24px; }
QScrollBar::handle:hover { background: #52525b; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QScrollArea, QScrollArea > QWidget > QWidget { background: #141417; }
"""
