"""FR-26 运行台：今日统计的纯逻辑、日期滚动与安全落盘。

UI 只负责把当前会话计数传进来；本模块不依赖 tkinter，便于单测。
统计文件只包含聚合计数，不含点击坐标、窗口标题或任何用户目标信息。
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date

SCHEMA = "autoclicker.daily-stats/1"
DAILY_FILE_NAME = ".auto_clicker_daily_stats.json"


def today_key(now=None):
    """返回 YYYY-MM-DD；now 仅接受 date/datetime 或 ISO 字符串。"""
    if now is None:
        return date.today().isoformat()
    if isinstance(now, str):
        return now[:10]
    if hasattr(now, "isoformat"):
        return now.isoformat()[:10]
    return date.today().isoformat()


def empty_daily_stats(now=None):
    return {
        "schema": SCHEMA,
        "date": today_key(now),
        "click_count": 0,
        "success_count": 0,
        "fail_count": 0,
        "exception_count": 0,
        "run_count": 0,
        "runtime_seconds": 0.0,
    }


def _non_negative_int(value, default=0):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _non_negative_float(value, default=0.0):
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def normalize(stats, now=None):
    """整形统计；日期变化时从零开始，避免把昨天的数据算进今天。"""
    today = today_key(now)
    if not isinstance(stats, dict) or str(stats.get("date", "")) != today:
        return empty_daily_stats(now=today)
    result = empty_daily_stats(now=today)
    result["click_count"] = _non_negative_int(stats.get("click_count"))
    result["success_count"] = _non_negative_int(stats.get("success_count"))
    result["fail_count"] = _non_negative_int(stats.get("fail_count"))
    result["exception_count"] = _non_negative_int(stats.get("exception_count"))
    result["run_count"] = _non_negative_int(stats.get("run_count"))
    result["runtime_seconds"] = _non_negative_float(stats.get("runtime_seconds"))
    # 成功数不应超过点击数，失败同理；损坏文件不能把成功率算成 >100%。
    result["success_count"] = min(result["success_count"], result["click_count"])
    result["fail_count"] = min(result["fail_count"], result["click_count"])
    return result


def load(path, now=None):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return normalize(data, now=now)
    except (OSError, ValueError, TypeError):
        return empty_daily_stats(now=now)


def save(path, stats, now=None):
    """原子写入：先写同目录临时文件，再 os.replace。"""
    clean = normalize(stats, now=now)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".daily-stats-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(clean, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
        os.replace(temp_path, path)
    except Exception:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        raise
    return clean


def record_run(stats, run, now=None):
    """把一次运行会话累加到今日统计；run 的字段与 last_run_stats 对齐。"""
    clean = normalize(stats, now=now)
    if not isinstance(run, dict):
        return clean
    clean["click_count"] += _non_negative_int(run.get("click_count"))
    clean["success_count"] += _non_negative_int(run.get("success_count"))
    clean["fail_count"] += _non_negative_int(run.get("fail_count"))
    clean["exception_count"] += _non_negative_int(run.get("exception_count"))
    clean["runtime_seconds"] += _non_negative_float(run.get("runtime_seconds"))
    clean["run_count"] += 1
    clean["success_count"] = min(clean["success_count"], clean["click_count"])
    clean["fail_count"] = min(clean["fail_count"], clean["click_count"])
    return clean


def merge_session(stats, click_count=0, success_count=0, fail_count=0,
                  exception_count=0, runtime_seconds=0.0, running=False, now=None):
    """把正在运行的会话叠加到今日统计上，仅用于展示，不落盘。"""
    clean = normalize(stats, now=now)
    if not running:
        return clean
    view = dict(clean)
    view["click_count"] += _non_negative_int(click_count)
    view["success_count"] += _non_negative_int(success_count)
    view["fail_count"] += _non_negative_int(fail_count)
    view["exception_count"] += _non_negative_int(exception_count)
    view["runtime_seconds"] += _non_negative_float(runtime_seconds)
    view["run_count"] += 1
    view["success_count"] = min(view["success_count"], view["click_count"])
    view["fail_count"] = min(view["fail_count"], view["click_count"])
    return view


def success_rate(stats):
    clicks = _non_negative_int((stats or {}).get("click_count"))
    if clicks <= 0:
        return None
    success = _non_negative_int((stats or {}).get("success_count"))
    return min(1.0, success / clicks) * 100.0


def success_rate_text(stats):
    rate = success_rate(stats)
    return "--" if rate is None else "%.1f%%" % rate


def last_run_text(stats):
    """运行台“上次运行”一句摘要；没有记录时返回固定占位。"""
    if not isinstance(stats, dict) or not stats.get("timestamp"):
        return "上次运行：暂无"
    clicks = _non_negative_int(stats.get("click_count"))
    success = min(_non_negative_int(stats.get("success_count")), clicks)
    runtime = _non_negative_float(stats.get("runtime_seconds"))
    mm, ss = int(runtime) // 60, int(runtime) % 60
    rate = "--" if clicks <= 0 else "%.1f%%" % (min(1.0, success / clicks) * 100.0)
    return "上次运行：点击 %d 次 · 成功率 %s · %02d:%02d" % (clicks, rate, mm, ss)
