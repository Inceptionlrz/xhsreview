"""
小红书智能回复助手 - 主启动器
仿 Linux.do 刷帖助手 v8.5.0 风格
"""

import os
import sys
import argparse

# 让脚本模式也能 import src
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.app import main

if __name__ == "__main__":
    main()
