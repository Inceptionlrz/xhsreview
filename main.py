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
    则让 Playwright 从该目录加载浏览器，而非依赖目标机已装的 Playwright。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    bundled = os.path.join(base, "ms-playwright")
    if os.path.isdir(bundled):
        # 指向内置浏览器目录的绝对路径，避免受启动 cwd 影响
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = bundled


_maybe_use_bundled_browsers()

from src.app import main

if __name__ == "__main__":
    main()
