#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PyInstaller 打包脚本（完全配置驱动）。

所有业务参数来自 scripts/config.build.json；机器相关覆盖来自
scripts/config.build.local.json（gitignore）。本文件不含硬编码业务参数。
"""

import os
import sys
import json
import importlib.util
import subprocess
import shutil

# 脚本位于 scripts/ 下，项目根目录为其父目录，所有相对路径都以此为基准
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_CONFIG = os.path.join(SCRIPT_DIR, 'config.build.json')
LOCAL_CONFIG = os.path.join(SCRIPT_DIR, 'config.build.local.json')


def _bootstrap_encoding():
    """按配置设置 Python 流编码；配置不可读时用 UTF-8 作为结构性兜底。"""
    enc = 'utf-8'
    try:
        with open(MAIN_CONFIG, 'r', encoding='utf-8') as f:
            enc = (json.load(f).get('runtime') or {}).get('python_io_encoding') or enc
    except (OSError, ValueError):
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, 'reconfigure'):
                stream.reconfigure(encoding=enc)
        except Exception:
            pass


def _merge_section(base, override):
    """顶层分段按键合并；两侧同为 dict 时递归，数组/标量以覆盖为准。"""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge_section(out[key], value)
        else:
            out[key] = value
    return out


def load_build_config():
    with open(MAIN_CONFIG, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    if os.path.exists(LOCAL_CONFIG):
        with open(LOCAL_CONFIG, 'r', encoding='utf-8') as f:
            cfg = _merge_section(cfg, json.load(f))
        print(f"✓ 已加载本地配置覆盖: {LOCAL_CONFIG}")
    return cfg


def abs_from_root(rel):
    """配置中的相对路径统一解析为项目根下的绝对路径。"""
    return os.path.normpath(os.path.join(ROOT_DIR, rel))


def clean_build(cfg):
    """按配置清理上一次构建文件。"""
    for rel in (cfg['build'].get('clean_paths') or []):
        path = abs_from_root(rel)
        if os.path.exists(path):
            print(f"删除目录: {path}")
            shutil.rmtree(path, ignore_errors=True)


def _ensure_pyinstaller(pyi):
    """检查 PyInstaller，缺失时按配置安装。"""
    try:
        __import__(pyi['module'])
        print(f"✓ {pyi['module']} 已安装")
    except (ImportError, ValueError):
        pkg = pyi['pip_package']
        print(f"✗ {pyi['module']} 未安装，正在安装 {pkg} ...")
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg])


def _resolve_icon(pyi):
    """解析并校验图标路径；缺失时退回默认图标。"""
    icon_path = abs_from_root(pyi['icon']) if pyi.get('icon') else None
    if icon_path and not os.path.isfile(icon_path):
        print(f"⚠ 未找到图标文件，将使用默认图标: {icon_path}")
        return None
    if icon_path:
        print(f"✓ 使用图标: {icon_path}")
    return icon_path


def _collect_hidden_imports(pyi):
    """合并显式声明的 hidden import 与当前环境实际可用的可选依赖。"""
    hidden = list(pyi.get('hidden_imports', []))
    for opt in pyi.get('optional_hidden_imports', []):
        try:
            if importlib.util.find_spec(opt) is not None:
                hidden.append(opt)
        except (ImportError, ValueError):
            pass
    return hidden


def _build_command(pyi, build, project, icon_path, hidden):
    """按配置组装 PyInstaller 命令行参数。"""
    app_name = os.path.splitext(build['exe_name'])[0]
    cmd = [
        sys.executable, '-m', pyi['module'],
        f"--name={app_name}",
        *pyi.get('flags', []),
        '--distpath', abs_from_root(build['dist_dir']),
        '--workpath', abs_from_root(build['build_dir']),
        '--specpath', abs_from_root(build['spec_dir']),
    ]

    if icon_path:
        cmd.extend(['--icon', icon_path])

    for item in pyi.get('add_data', []):
        source = abs_from_root(item['source'])
        if os.path.exists(source):
            cmd.extend(['--add-data', f"{source}{os.pathsep}{item['target']}"])
        else:
            print(f"⚠ 数据路径不存在，跳过: {source}")

    for imp in hidden:
        cmd.extend(['--hidden-import', imp])

    for mod in pyi.get('exclude_modules', []):
        cmd.extend(['--exclude-module', mod])
        print(f"✓ 排除模块: {mod}")

    cmd.append(project['main_script'])
    return cmd


def build_exe():
    cfg = load_build_config()
    project = cfg['project']
    build = cfg['build']
    pyi = build['pyinstaller']

    # 确保在项目根目录执行，PyInstaller 才能解析主脚本与资源路径
    os.chdir(ROOT_DIR)
    os.makedirs(abs_from_root(build['release_dir']), exist_ok=True)

    print("=" * 60)
    print(f"开始打包 {project['name']}...")
    print("=" * 60)

    clean_build(cfg)

    # PyInstaller 可用性自检（缺失时按配置安装）
    _ensure_pyinstaller(pyi)

    # 图标（绝对路径：spec 落在 scripts/ 时，spec 内相对路径按 spec 目录二次解析）
    icon_path = _resolve_icon(pyi)

    hidden = _collect_hidden_imports(pyi)
    cmd = _build_command(pyi, build, project, icon_path, hidden)

    print("\n执行命令:")
    print(" ".join(cmd))
    print("\n" + "=" * 60)

    try:
        subprocess.check_call(cmd)
        print("\n" + "=" * 60)
        print("✅ 打包成功!")
        print("=" * 60)

        exe_path = os.path.join(abs_from_root(build['dist_dir']), build['exe_name'])
        if os.path.exists(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"\n📦 可执行文件: {exe_path}")
            print(f"📊 文件大小: {size_mb:.2f} MB")
            print("\n💡 提示: 可以直接运行此文件，无需其他依赖")
        return True
    except subprocess.CalledProcessError as e:
        print("\n" + "=" * 60)
        print("❌ 打包失败!")
        print("=" * 60)
        print(f"错误: {e}")
        return False


if __name__ == '__main__':
    _bootstrap_encoding()
    sys.exit(0 if build_exe() else 1)
