"""
小红书智能回复助手 —— EXE 打包脚本（Windows）

用法：
    python scripts/build_exe.py

依赖（需在本机 Python 3.12 中已安装）：
    pip install pyinstaller
    # playwright / greenlet / requests 也需在同一个 Python 中可用（已装即可）

说明：
    - 采用 onedir 模式（dist/xhsreview/ 目录），启动快、对 Playwright/浏览器兼容最好。
    - 将本机已安装的 Playwright Chromium 浏览器一起打进包，使生成的 exe
      在「未安装 Python / Playwright / Chrome」的机器上也能直接运行。
    - main.py 已做自包含处理：若 exe 同目录存在 ms-playwright/，则优先用内置浏览器。
    - 绝不打包真实 config/config.json（含 API Key），仅附带 config.example.json 作模板。
"""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- 自动定位本机 Playwright 浏览器目录 ----
LOCAL = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
MSPW = os.path.join(LOCAL, "ms-playwright")

# 需要随包携带的浏览器组件（与 playwright 版本对应的 revision 目录）
BROWSER_DIRS = [
    "chromium-1228",
    "chromium_headless_shell-1228",
    "ffmpeg-1011",
]


def find_python():
    """优先用与 playwright 同版本的 Python（通常就是当前解释器）。"""
    return sys.executable


def main():
    py = find_python()
    print(f"[build] Python: {py}")
    print(f"[build] 项目根目录: {ROOT}")
    print(f"[build] 浏览器源目录: {MSPW}")

    if not os.path.isdir(MSPW):
        print(f"[build][ERROR] 未找到 {MSPW}，请先在本机执行 `playwright install chromium`")
        sys.exit(1)

    # 构造 --add-data：把浏览器目录整体打进 <exe>/ms-playwright/<name>
    add_data = []
    for name in BROWSER_DIRS:
        src = os.path.join(MSPW, name)
        if os.path.isdir(src):
            # Windows 上 --add-data 用 `;` 分隔源与目标
            add_data.append(f"{src};ms-playwright/{name}")
            print(f"[build] 打包浏览器: {name}")
        else:
            print(f"[build][WARN] 跳过不存在的浏览器目录: {name}")

    # 附带配置模板
    example = os.path.join(ROOT, "config.example.json")
    if os.path.isfile(example):
        add_data.append(f"{example};config.example.json")

    cmd = [
        py, "-m", "PyInstaller",
        "--noconfirm",
        "--name", "xhsreview",
        "--onedir",
        "--noconsole",
        "--hidden-import", "playwright",
        "--hidden-import", "greenlet",
        "--hidden-import", "requests",
        "--collect-all", "playwright",
    ]
    for ad in add_data:
        cmd += ["--add-data", ad]
    cmd.append(os.path.join(ROOT, "main.py"))

    print("\n[build] 执行命令：")
    print("  " + " ".join(cmd))
    print("")

    # 用本机 Python 直接执行（其 site-packages 含 playwright，版本与浏览器匹配）
    ret = subprocess.call(cmd)
    if ret != 0:
        print(f"[build][ERROR] PyInstaller 返回 {ret}")
        sys.exit(ret)

    dist = os.path.join(ROOT, "dist", "xhsreview")
    print(f"\n[build] 完成 ✅ 产物在: {dist}")
    print(f"[build] 直接双击 {dist}\\xhsreview.exe 即可运行（首次需扫码登录小红书）。")


if __name__ == "__main__":
    main()
