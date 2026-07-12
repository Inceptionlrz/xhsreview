# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [
    (r'C:/Users/samal/AppData/Local/ms-playwright/chromium-1228', 'ms-playwright/chromium-1228'),
    (r'C:/Users/samal/AppData/Local/ms-playwright/chromium_headless_shell-1228', 'ms-playwright/chromium_headless_shell-1228'),
    (r'C:/Users/samal/AppData/Local/ms-playwright/ffmpeg-1011', 'ms-playwright/ffmpeg-1011'),
    (r'D:/Project/00_workbuddy/xhsreview/config.example.json', '.'),
]
binaries = []
hiddenimports = ['playwright', 'greenlet', 'requests']
tmp_ret = collect_all('playwright')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [r'D:/Project/00_workbuddy/xhsreview/main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='xhsreview',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='xhsreview',
)
