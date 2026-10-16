# -*- mode: python ; coding: utf-8 -*-
"""Build Windows (pasta):  pyinstaller packaging/auto_draw_studio.spec
Depois de validar a pasta, gerar onefile:
  pyinstaller --windowed --onefile --name AutoDrawStudio --icon assets/icon.ico
    --add-data "assets;assets" main.py
Armadilha clássica: plugin de plataforma Qt ("windows") ausente — o
collect_all('PySide6') abaixo + teste do .exe resolvem.
"""
import os

block_cipher = None

datas = [("assets", "assets")]
binaries = []
hiddenimports = []

try:
    from PyInstaller.utils.hooks import collect_all
    for pkg in ("PySide6", "cv2", "numpy", "PIL"):
        try:
            d, b, h = collect_all(pkg)
            datas += d
            binaries += b
            hiddenimports += h
        except Exception:
            pass
except ImportError:
    pass

a = Analysis(
    ["..\\main.py"],
    pathex=[os.path.abspath("..")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AutoDrawStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="..\\assets\\icon.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="AutoDrawStudio",
)
