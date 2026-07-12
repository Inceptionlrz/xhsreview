#!/usr/bin/env python3
"""一键打包脚本：自动生成 PyInstaller spec 并构建 xhsreview.exe。

设计目标：
- 自动定位本机 ms-playwright（支持 PLAYWRIGHT_BROWSERS_PATH 环境变量覆盖）
- 把 chromium-1228、chromium_headless_shell-1228、ffmpeg-1011 随包携带
- onedir + noconsole，目标机无需安装 Python / Playwright / Chrome
- 绝不把真实 config/config.json（含 API Key）打进包，只带 config.example.json

用法：
    python scripts/build_exe.py

输出：
    dist/xhsreview/xhsreview.exe
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = PROJECT_ROOT / "xhsreview.spec"


def find_ms_playwright() -> Path:
    """定位本地 ms-playwright 浏览器目录。"""
    # 1) 环境变量显式指定
    env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env:
        p = Path(env)
        if p.is_dir():
            return p

    # 2) Playwright 默认安装路径
    candidates = [
        Path.home() / "AppData" / "Local" / "ms-playwright",
        Path.home() / ".cache" / "ms-playwright",
        Path.home() / "Library" / "Caches" / "ms-playwright",
    ]
    for c in candidates:
        if c.is_dir():
            return c

    raise FileNotFoundError(
        "找不到 ms-playwright 浏览器目录。请确保已运行：\n"
        "    playwright install chromium\n"
        "或设置环境变量 PLAYWRIGHT_BROWSERS_PATH"
    )


def generate_spec(ms_playwright: Path, project_root: Path) -> str:
    """生成 PyInstaller spec 文本（使用 Windows 绝对路径）。"""
    chromium = ms_playwright / "chromium-1228"
    headless = ms_playwright / "chromium_headless_shell-1228"
    ffmpeg = ms_playwright / "ffmpeg-1011"
    example_cfg = project_root / "config.example.json"

    for p in (chromium, headless, ffmpeg):
        if not p.is_dir():
            raise FileNotFoundError(f"缺少浏览器组件: {p}")
    if not example_cfg.is_file():
        raise FileNotFoundError(f"缺少配置模板: {example_cfg}")

    # 把 Path 转成 Windows 反斜杠字符串，供 spec 使用
    def win_str(p: Path) -> str:
        return str(p.resolve()).replace("\\", "/")

    return f'''# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [
    (r'{win_str(chromium)}', 'ms-playwright/chromium-1228'),
    (r'{win_str(headless)}', 'ms-playwright/chromium_headless_shell-1228'),
    (r'{win_str(ffmpeg)}', 'ms-playwright/ffmpeg-1011'),
    (r'{win_str(example_cfg)}', '.'),
]
binaries = []
hiddenimports = ['playwright', 'greenlet', 'requests']
tmp_ret = collect_all('playwright')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [r'{win_str(project_root / "main.py")}'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={{}},
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
'''


def main():
    print("=" * 50)
    print("XHS Review 一键打包")
    print("=" * 50)

    ms = find_ms_playwright()
    print(f"[INFO] 使用浏览器目录: {ms}")

    print(f"[INFO] 生成 spec: {SPEC_PATH}")
    spec_text = generate_spec(ms, PROJECT_ROOT)
    SPEC_PATH.write_text(spec_text, encoding="utf-8")

    # 清理旧产物(可选)：如果当前环境的 shutil 被拦截，只跳过不报错
    for old in (PROJECT_ROOT / "build", PROJECT_ROOT / "dist"):
        if old.exists():
            print(f"[INFO] 清理旧目录: {old}")
            try:
                shutil.rmtree(old)
            except Exception as e:
                print(f"[WARN] 自动清理失败({e})，将由 PyInstaller 覆盖/保留")

    # 执行 PyInstaller
    cmd = [sys.executable, "-m", "PyInstaller", str(SPEC_PATH), "--noconfirm"]
    print(f"[INFO] 执行: {' '.join(cmd)}")
    print("-" * 50)
    result = subprocess.run(cmd, cwd=PROJECT_ROOT)

    if result.returncode != 0:
        print("[ERROR] PyInstaller 构建失败")
        sys.exit(result.returncode)

    exe = PROJECT_ROOT / "dist" / "xhsreview" / "xhsreview.exe"
    if not exe.exists():
        print(f"[ERROR] 未找到产物: {exe}")
        sys.exit(1)

    print("-" * 50)
    print(f"[OK] 构建成功: {exe}")
    print(f"[OK] 产物大小: {exe.stat().st_size / 1024 / 1024:.1f} MB")
    print("[REMINDER] 请确认 dist/xhsreview/ 目录下没有 config/config.json 再分发！")


if __name__ == "__main__":
    main()
