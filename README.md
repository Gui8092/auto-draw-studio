# Auto Draw Studio

Desktop em Python (PySide6) que converte imagens em desenhos e reproduz os traços
automaticamente com o mouse. Motor híbrido por região: sólidos amplos viram
**zigue-zague contínuo**, traços finos viram **linhas centrais**, furos preservados.

![Janela principal](docs/screenshot_main.png)

## Convenção de máscara (importante)

Em todo o projeto a máscara binária é `uint8` onde
**255 = precisa de tinta (preto)** e **0 = papel (branco)**.
`thresholding.binarize` já entrega nesse formato; todos os módulos
consomem sem inverter.

## Instalação (Windows 10/11)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Execução

```powershell
python main.py
```

Fluxo: Importar imagem → ajustar limiar/brilho/contraste/gama →
conferir abas (Original / P&B / Trajetórias / Simulação) →
Selecionar área → Iniciar (F9) → contagem 5 s → desenho.
Pausar (F10), Cancelar (Esc). O FAILSAFE do PyAutoGUI permanece ligado:
arrastar o mouse ao canto superior-esquerdo aborta.

## Calibração e preparação

1. Clique em **Selecionar área** e arraste o retângulo sobre o app de destino
   (Paint, Krita, etc.).
2. No app de destino, selecione pincel/cor/espessura antes de iniciar.
3. A proporção da imagem é preservada (`fit_aspect` + margens).
4. DPI/escala do Windows: maximize o app de destino sempre na mesma
   resolução da calibração; se mudar de monitor, calibre de novo.

## Testes

```powershell
python -m pytest tests/ -q
```

122+ testes (núcleo, automação com mocks, UI offscreen). Nenhum teste move
o mouse real (backend mock).

## Interface

- Controles com valor visível, tooltips, presets (perfis) e "Restaurar padrões".
- Abas Original / P&B / **Trajetórias** (zoom com scroll, pan com botão direito,
  filtros por tipo, deslocamentos tracejados) / Simulação.
- Etapas 1→5 no cabeçalho, botão Iniciar habilitado só quando pronto,
  cronometria de decorrido/restante pelo ritmo medido.
- Geometria da janela e divisor persistidos (QSettings).

## Empacotamento Windows

```powershell
pip install pyinstaller
pyinstaller packaging/auto_draw_studio.spec   # pasta (validar primeiro)
# depois, se ok:
pyinstaller --windowed --onefile --name AutoDrawStudio --icon assets/icon.ico --add-data "assets;assets" main.py
```

Valide o `.exe` abrindo sem console e rodando o fluxo completo. Se faltar o
plugin de plataforma Qt ("windows"), confira o `collect_all('PySide6')` no `.spec`.

## Atalhos

| Ação | Padrão |
|---|---|
| Iniciar | F9 |
| Pausar | F10 |
| Cancelar/emergência | Esc |

Configuráveis em `settings.json` (execução). Podem ser alterados no código
via `GlobalHotkeys.start({...})`.

## Estrutura

```
app/core/        image_loader, preprocessing, thresholding, morphology,
                 contour_extractor, region_analyzer, fill_planner (zigue-zague),
                 centerline, strategy (seletor+perfis), shading_planner (exp.),
                 path_optimizer, quality_checker, pipeline
app/automation/  screen_calibration, coordinate_mapper, mouse_executor,
                 hotkeys (pynput), execution_controller (estados + thread)
app/models/      drawing_plan (Stroke/StrokeType/DrawingPlan+SVG), settings
app/ui/          main_window, image_preview, settings_panel, widgets,
                 path_preview (zoom/pan/filtros/travel), canvas_selector,
                 process_worker (QThread), styles
app/utils/       logging_setup, persistence (JSON versionado)
tests/           suíte de UI offscreen + núcleo (ver `pytest --collect-only`)
benchmarks/      bench_zigzag.py, bench_suite.py + PNGs em `benchmarks/out/`
packaging/       auto_draw_studio.spec (PyInstaller, Windows)
assets/          icon.png/ico + gerador | docs/ screenshot
```

Ordem dos traços: fills → hachuras → detalhes → internos → externos,
com vizinho-mais-próximo dentro de cada etapa (sem conectar formas
independentes).

## Limitações conhecidas

- Fotografias complexas são simplificadas (aviso de cobertura baixa);
  o programa informa em vez de fingir fidelidade.
- A espessura da simulação acompanha o espaçamento (`≈ spacing/2`); o traço
  físico depende do pincel do app de destino.
## Estratégia de desenho

- **auto (padrão):** por região — traço fino vira linha central, sólido amplo
  vira zigue-zague, furos preservados; o log registra a escolha por região.
- **fill / contour / centerline:** modos manuais avançados.
- **Perfis:** equilibrado, rapido, fidelidade, linha_fina, logo (Combinam
  parâmetros existentes; `linha_fina` força centerline).
- Hachura/pontilhismo (`shading_planner`) seguem EXPERIMENTAIS e fora do
  pipeline.
- Pausar (F10) funciona na contagem regressiva e no desenho; retomar
  continua de onde parou sem pular a contagem. Cancelar funciona em ambos.
- Seleção de área cobre o monitor primário virtual; multi-monitor com DPIs
  muito diferentes exige recalibração.
