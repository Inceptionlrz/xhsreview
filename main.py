"""
小红书智能回复助手 - 主启动器
仿 Linux.do 刷帖助手 v8.5.0 风格
"""

import os
import sys
import argparse

# 让脚本模式也能 import src
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _maybe_use_bundled_browsers():
    """自包含打包支持：若 exe 同目录携带了 ms-playwright（PyInstaller onedir 内置浏览器），
    则让 Playwright 从该目录加载浏览器，而非依赖目标机已装的 Playwright。

    PyInstaller 6+ onedir 默认把资源放在 exe 同目录的 _internal/ 下，因此同时检查：
      - <exe_dir>/ms-playwright
      - <exe_dir>/_internal/ms-playwright
    """
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))

    candidates = [
        os.path.join(base, "ms-playwright"),
        os.path.join(base, "_internal", "ms-playwright"),
    ]
    for bundled in candidates:
        if os.path.isdir(bundled):
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bundled
            return


_maybe_use_bundled_browsers()

from src.app import main

if __name__ == "__main__":
    main()
