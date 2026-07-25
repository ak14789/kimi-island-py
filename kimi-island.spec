# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# Drop DLLs picked up from third-party software on PATH (Anaconda, ChemScript).
# They shadow the correct System32/PySide6-bundled DLLs inside the onefile
# bundle; notably Anaconda's ICU 58 (icuuc.dll) breaks Qt6Core loading.
a.binaries = [
    b for b in a.binaries
    if 'Anaconda3' not in b[1] and 'ChemScript' not in b[1]
]

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='kimi-island',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
