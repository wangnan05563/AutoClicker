#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AutoClicker 打包脚本
使用 PyInstaller 打包为独立可执行文件
"""

import os
import sys
import subprocess
import shutil

# 强制 stdout/stderr 为 UTF-8，避免中文 Windows 默认 GBK 控制台下打印 ✓/✅/📦 等
# Unicode 字符时触发 UnicodeEncodeError 而中断打包。
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


# 脚本位于 scripts/ 下，项目根目录为其父目录，所有路径都以此为基准
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELEASE_DIR = os.path.join(ROOT_DIR, 'release')


def clean_build():
    """清理之前的构建文件"""
    dirs_to_remove = [
        os.path.join(RELEASE_DIR, 'build'),
        os.path.join(RELEASE_DIR, 'dist'),
        os.path.join(ROOT_DIR, '__pycache__'),
        os.path.join(ROOT_DIR, '.pytest_cache'),
    ]

    for dir_name in dirs_to_remove:
        if os.path.exists(dir_name):
            print(f"删除目录: {dir_name}")
            shutil.rmtree(dir_name, ignore_errors=True)


def build_exe():
    """使用 PyInstaller 打包"""

    # 确保在项目根目录执行，PyInstaller 才能找到主脚本和 icons
    os.chdir(ROOT_DIR)
    os.makedirs(RELEASE_DIR, exist_ok=True)

    print("=" * 60)
    print("开始打包 AutoClicker...")
    print("=" * 60)

    # 清理旧文件
    clean_build()

    # 检查 PyInstaller
    try:
        import PyInstaller
        print("✓ PyInstaller 已安装")
    except ImportError:
        print("✗ PyInstaller 未安装，正在安装...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # 图标路径
    icon_path = os.path.join("icons", "autoclicker.ico")
    if not os.path.exists(icon_path):
        icon_path = None
        print("⚠ 未找到图标文件，将使用默认图标")
    else:
        print(f"✓ 使用图标: {icon_path}")

    # 构建命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=AutoClicker",
        "--onefile",  # 打包为单个文件
        "--windowed",  # Windows GUI 程序（不显示控制台）
        "--noconfirm",  # 不询问确认
        "--clean",  # 清理临时文件
        "--distpath", os.path.join(RELEASE_DIR, "dist"),  # 产物统一输出到 release/
        "--workpath", os.path.join(RELEASE_DIR, "build"),
        "--specpath", ROOT_DIR,
    ]

    # 添加图标
    if icon_path:
        cmd.extend(["--icon", icon_path])

    # 添加数据文件（图标目录）
    if os.path.exists("icons"):
        cmd.extend(["--add-data", f"icons{os.pathsep}icons"])

    # 隐藏导入（解决某些模块找不到的问题）
    hidden_imports = [
        "pyautogui",
        "keyboard",
        "PIL",
        "PIL.Image",
        "PIL.ImageTk",
        "tkinter",
        "tkinter.ttk",
    ]
    # 可选主题依赖（P2 主题系统 TH-01/TH-03）：ttkbootstrap 尚未纳入依赖且功能未实现，
    # 仅当模块可导入时才作为隐藏导入，避免 PyInstaller 报 "Hidden import not found" 误导。
    import importlib.util
    for opt in ["ttkbootstrap", "ttkbootstrap.style", "ttkbootstrap.widgets"]:
        try:
            if importlib.util.find_spec(opt) is not None:
                hidden_imports.append(opt)
        except (ImportError, ValueError):
            pass

    for imp in hidden_imports:
        cmd.extend(["--hidden-import", imp])

    # 主脚本
    cmd.append("auto_clicker_py3.py")

    print("\n执行命令:")
    print(" ".join(cmd))
    print("\n" + "=" * 60)

    # 执行打包
    try:
        subprocess.check_call(cmd)
        print("\n" + "=" * 60)
        print("✅ 打包成功!")
        print("=" * 60)

        # 显示输出路径
        exe_path = os.path.join(RELEASE_DIR, "dist", "AutoClicker.exe")
        if os.path.exists(exe_path):
            file_size = os.path.getsize(exe_path) / (1024 * 1024)  # MB
            print(f"\n📦 可执行文件: {exe_path}")
            print(f"📊 文件大小: {file_size:.2f} MB")
            print("\n💡 提示: 可以直接运行此文件，无需其他依赖")

        return True

    except subprocess.CalledProcessError as e:
        print("\n" + "=" * 60)
        print("❌ 打包失败!")
        print("=" * 60)
        print(f"错误: {e}")
        return False


if __name__ == "__main__":
    success = build_exe()
    sys.exit(0 if success else 1)
