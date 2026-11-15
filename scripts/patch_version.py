#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""构建版本号生成器：YYYYMMDD-序号（如 20261115-001），写回项目根 package.json 的 version 字段。

- 每次执行（即每次构建）分配一个新的序号，保证同一天内全局唯一；
- 序号持久化在 scripts/.build-version-state.json（gitignore），跨进程/多次构建连续；
- 跨天自动重置为 001；若状态文件丢失，会以 package.json 里当天已有的最大序号为基线继续递增；
- 文件锁（state.lock）防止并发构建拿到重复版本号；写入采用临时文件 + 原子替换；
- package.json 不存在时创建最小合法 JSON（name/version/private/description），已存在时保留其余字段与缩进风格。

用法：
    python scripts/patch_version.py                 # 分配版本号并写回根 package.json
    python scripts/patch_version.py --dry-run       # 只计算并打印下一个版本号，不落盘、不推进序号
    python scripts/patch_version.py --root <dir>    # 指定项目根（默认脚本所在目录的父目录）
"""

import argparse
import datetime
import json
import os
import re
import sys
import tempfile
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(SCRIPT_DIR)
STATE_REL = os.path.join("scripts", ".build-version-state.json")
STATE_LOCK_SUFFIX = ".lock"
LOCK_TIMEOUT_SECONDS = 10.0
LOCK_STALE_SECONDS = 60.0


def _reconfigure_stdio():
    """Windows 控制台默认非 UTF-8；统一为 UTF-8，避免中文输出乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _read_json(path):
    """读取 JSON；文件不存在返回 None，格式非法抛 ValueError。"""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8-sig") as f:
        try:
            return json.load(f)
        except ValueError as exc:
            raise ValueError("JSON 格式非法: %s (%s)" % (path, exc))


def _atomic_write_text(path, text):
    """同目录临时文件 + os.replace，避免写到一半留下损坏文件。"""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _acquire_lock(lock_path, timeout=LOCK_TIMEOUT_SECONDS, stale=LOCK_STALE_SECONDS):
    """O_EXCL 原子建锁；超时或残留锁（默认 60s）按失败处理/清理。"""
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, str(os.getpid()).encode("ascii", "ignore"))
            finally:
                os.close(fd)
            return True
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock_path) > stale:
                    os.remove(lock_path)
                    continue
            except OSError:
                pass
            if time.time() >= deadline:
                return False
            time.sleep(0.1)


def _release_lock(lock_path):
    try:
        os.remove(lock_path)
    except OSError:
        pass


def _detect_indent(text, default=2):
    """从已有 package.json 猜缩进：优先制表符，其次空格宽度。"""
    match = re.search(r'\n([ \t]+)"', text)
    if not match:
        return default
    whitespace = match.group(1)
    if "\t" in whitespace:
        return "\t"
    return max(1, len(whitespace))


def _read_text(path):
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def _today_str(today=None):
    if today:
        return today
    return datetime.date.today().strftime("%Y%m%d")


def _state_date_seq(state):
    if not isinstance(state, dict):
        return "", 0
    date = str(state.get("date") or "")
    try:
        seq = int(state.get("seq") or 0)
    except (TypeError, ValueError):
        seq = 0
    return date, max(0, seq)


def _package_seq(package, today):
    """package.json 里当天已用的最大序号（状态丢失时的兜底基线）。"""
    if not isinstance(package, dict):
        return 0
    version = str(package.get("version") or "")
    match = re.fullmatch(re.escape(today) + r"-(\d+)", version)
    return int(match.group(1)) if match else 0


def _default_package(root, version):
    """项目原本没有 package.json 时创建最小合法载体。"""
    name = os.path.basename(os.path.abspath(root)).strip().lower()
    name = re.sub(r"[^a-z0-9._-]+", "-", name) or "project"
    return {
        "name": name,
        "version": version,
        "private": True,
        "description": "构建版本号载体：由 scripts/patch_version.py 在每次构建前更新为 YYYYMMDD-序号。",
    }


def _format_version(today, seq):
    return "%s-%03d" % (today, seq)


def allocate_version(root=DEFAULT_ROOT, today=None, dry_run=False):
    """分配并（非 dry-run 时）写回版本号；返回 {version, seq, package_path, created}。"""
    today = _today_str(today)
    package_path = os.path.join(root, "package.json")
    state_path = os.path.join(root, STATE_REL)
    lock_path = state_path + STATE_LOCK_SUFFIX

    package_text = _read_text(package_path)
    package = _read_json(package_path)
    if package is not None and not isinstance(package, dict):
        raise ValueError("package.json 顶层必须是 JSON 对象: %s" % package_path)

    if dry_run:
        state = _read_json(state_path)
        state_date, state_seq = _state_date_seq(state)
        base = state_seq if state_date == today else 0
        seq = max(base, _package_seq(package, today)) + 1
        return {
            "version": _format_version(today, seq),
            "seq": seq,
            "package_path": package_path,
            "created": package is None,
        }

    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    if not _acquire_lock(lock_path):
        raise TimeoutError("获取版本号文件锁超时（%s），可能有并发构建正在占用。" % lock_path)
    try:
        state = _read_json(state_path)
        state_date, state_seq = _state_date_seq(state)
        base = state_seq if state_date == today else 0
        seq = max(base, _package_seq(package, today)) + 1
        version = _format_version(today, seq)
        created = package is None

        # 先落 package.json 再落序号：万一后一步失败，下次会以 package.json
        # 里的当天最大序号为基线继续递增，最多跳号，绝不重复发号。
        if package is None:
            package = _default_package(root, version)
            indent = 2
        else:
            package["version"] = version
            indent = _detect_indent(package_text, 2)
        _atomic_write_text(
            package_path,
            json.dumps(package, ensure_ascii=False, indent=indent, sort_keys=False) + "\n",
        )
        _atomic_write_text(
            state_path,
            json.dumps({"date": today, "seq": seq}, ensure_ascii=False, indent=1) + "\n",
        )
        return {
            "version": version,
            "seq": seq,
            "package_path": package_path,
            "created": created,
        }
    finally:
        _release_lock(lock_path)


def main(argv=None):
    _reconfigure_stdio()
    parser = argparse.ArgumentParser(description="生成 YYYYMMDD-序号 构建版本号并写回根 package.json")
    parser.add_argument("--root", default=DEFAULT_ROOT, help="项目根目录（默认脚本父目录）")
    parser.add_argument("--dry-run", action="store_true", help="只打印下一个版本号，不写文件、不推进序号")
    args = parser.parse_args(argv)

    try:
        result = allocate_version(args.root, dry_run=args.dry_run)
    except (ValueError, TimeoutError, OSError) as exc:
        print("[ERROR] 生成构建版本号失败: %s" % exc, file=sys.stderr)
        return 1

    package = _read_json(result["package_path"]) if not args.dry_run else None
    print("PATCH_VERSION=%s" % result["version"])
    print("[PACKAGE_JSON] %s%s" % (result["package_path"], "（新建）" if result["created"] else ""))
    if args.dry_run:
        print("[DRY-RUN] 未写入 package.json、未推进序号。")
    elif isinstance(package, dict):
        print("[VERIFY] JSON 合法 | version=%s | 顶层字段=%d | 序号=%03d"
              % (package.get("version"), len(package), result["seq"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
