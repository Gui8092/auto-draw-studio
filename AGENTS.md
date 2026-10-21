# Auto Draw Studio — AGENTS.md

## Run commands
```bash
# Testes (offscreen Qt)
$env:PYTHONPATH='C:\Users\User\Documents\.projetos\AUTO_DRAW_STUDIO'; $env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/ -q

# Um teste específico
$env:PYTHONPATH='C:\Users\User\Documents\.projetos\AUTO_DRAW_STUDIO'; $env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/test_mouse_executor.py -q

# App
python main.py

# Build PyInstaller (Windows)
cd packaging && pyinstaller auto_draw_studio.spec
```

## Architecture (4 camadas)
```
main.py → app/ui/main_window.py           # UI + orquestração
      → app/automation/*                   # Execução real (PyAutoGUI) + mock
      → app/core/pipeline.py               # process_to_plan(gray, settings) → (mask, DrawingPlan)
      → app/core/*                         # fill, contorno, centerline, strategy, hachura, otimização
      → app/models/drawing_plan.py         # Stroke, DrawingPlan, estimate_duration
      → app/models/settings.py             # ProcessingSettings, ExecutionSettings
      → app/utils/persistence.py           # load/save settings + projetos (JSON)
```

## Entry points
- `main.py` → `run_app(argv)` → `MainWindow` + `QApplication`
- Worker thread: `ProcessWorker` (QThread) roda `process_to_plan` + `check_quality` fora da UI

## Testes
- 206 testes, `QT_QPA_PLATFORM=offscreen`, fixtures em `conftest.py` (`qapp`, `make_window`)
- **Não roda** sem `QT_QPA_PLATFORM` (precisa display)
- `tests/` é versionado: a suíte é a rede de segurança contra regressão
- `tests/baseline_quality.json`: trava as métricas por caso. Regenerar com
  `$env:UPDATE_QUALITY_BASELINE='1'` — só depois de uma mudança intencional

## Gotchas verificados
- `countdown_s` nas configurações **vale de verdade** — antes era hardcodado 5s
- Pausa **não solta o mouse** — executor congela com botão pressionado (`pause_drawing`/`resume_drawing`)
- O estado público do controller é **derivado** (`_phase` + `_paused`): a fase
  interna pode virar RUNNING com o estado público ainda PAUSED
- `start()` publica o estado **antes** de spawnar a thread (duas execuções
  simultâneas = dois threads movendo o mouse)
- F10 é **toggle** (pausar/retomar); F11 retoma. Antes não havia como
  retomar pelo teclado e a janela fica minimizada durante o desenho
- `closeEvent` usa cancelamento **cooperativo** (`ProcessWorker.request_stop`
  + `QThread.requestInterruption`) e **nunca** `terminate()` — `terminate()`
  em thread Python/OpenCV aborta o processo (0xC0000409)
- `estimate_duration(scale=...)` converte de px de **imagem** para px de
  **tela** (o executor anda na tela)
- Ordem dos traços: fills → hachuras → detalhes → internos → externos
- Simplificação **reinsere** o vértice de fechamento do contorno
  (`approxPolyDP` nunca devolve o vértice duplicado)
- O epsilon do FILL é limitado a ~metade do espaçamento (senão o zigue-zague
  vira diagonal)
- Espessura do componente = mediana da largura no **eixo medial**
  (`dist.max()` é fooled por um ponto grosso); esqueleto só na zona de decisão
- `thin_line_px` decide linha×sólido — **não** depende de `fill_spacing`
- Settings/logs salvos em `~/.auto_draw_studio` (não CWD); migra `settings.json` legado
- `opencv-python-headless` nas deps (sem GUI); build spec usa caminhos `../` (Linux/Mac compatíveis)
- `make_icon.py` tem `main()` guardado — import não reescreve ícones
- Order plan vetorizado (NumPy) — 600 traços em ~0.06s; guloso parte do **fim**
  do 1º traço
- Preview de trajetórias faz culling por viewport (bbox por traço); não redesenha tudo no pan/zoom
- Hachuras: uma chamada de `plan_hatch` por componente, **restrita à bbox**
  (sem isso o sombreado era ~10x mais lento que o auto)

## Não mexer (comportamento coberto por teste)
- Seletor de área: `+1` na largura/altura (`normalize_points`) — correspondência exata visual↔coordenada
- Junções da centerline: hoje atravessa reto (cruz 4→3 traços); mudar quebraria `test_cross_junction_covered_without_overlap`
- Pausa **não** solta o mouse (traço íntegro ao retomar)
- Furo preservado: o `INNER_CONTOUR` do furo é esperado; a medição de
  "invasão" do furo usa só FILL/CENTERLINE/HATCH

## Flags de compilação
- Python ≥3.10 (match/structural pattern não usado, mas f-strings `=` e union types)
- PySide6, OpenCV, NumPy, Pillow, PyAutoGUI, pynput
- OpenCV 5.x: `connectedComponents` devolve `(count, labels)`;
  `connectedComponentsWithStats` devolve `(count, labels, stats, centroids)`
