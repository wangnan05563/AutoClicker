# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 配置文件 - Linux/银河麒麟版本
用于打包自动点击工具
"""

import os
import sys

# 获取当前目录
block_cipher = None

# 图标路径（Linux 使用 PNG 格式）
icon_path = None
if os.path.exists('icons/tray.png'):
    icon_path = 'icons/tray.png'
elif os.path.exists('icons/autoclicker.png'):
    icon_path = 'icons/autoclicker.png'

a = Analysis(
    ['auto_clicker_py3.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('icons', 'icons'),
    ],
    hiddenimports=[
        'PIL._tkinter_finder',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AutoClicker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

