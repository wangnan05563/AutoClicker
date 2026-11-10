# -*- coding: utf-8 -*-
"""
Setup script for cx_Freeze - Python 3.14 (GUI mode - no console)
"""

import sys
import os
from cx_Freeze import setup, Executable

# 获取图标路径
icon_path = os.path.join('icons', 'autoclicker.ico')

build_exe_options = {
    "packages": ["tkinter"],
    "includes": ["pyautogui"],
    "excludes": [],
    "include_files": [
        ('icons', 'icons'),  # 包含图标目录
    ],
    "build_exe": "build/AutoClicker"  # 输出到 build/AutoClicker 目录
}

# 设置base为gui，隐藏控制台窗口
base = "gui" if sys.platform == "win32" else None

setup(
    name = "AutoClicker",
    version = "2.0",
    description = "Auto Clicker Tool - Python 3.14",
    options = {"build_exe": build_exe_options},
    executables = [
        Executable(
            "auto_clicker_py3.py",
            base=base,
            target_name="AutoClicker.exe",
            icon=icon_path if os.path.exists(icon_path) else None
        )
    ]
)
