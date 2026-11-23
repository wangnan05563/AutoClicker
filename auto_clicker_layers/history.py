# -*- coding: utf-8 -*-
"""T06155：运行历史（最近 30 次）纯逻辑。

只保存聚合摘要，不保存点击坐标或窗口标题；文件损坏时退回空历史，
不删除既有文件内容，写入使用同目录临时文件 + os.replace。
"""
import csv
import json
import os
import tempfile
from datetime import datetime

SCHEMA = 'autoclicker.run-history/1'
DEFAULT_LIMIT = 30
HISTORY_FILE_NAME = '.auto_clicker_run_history.json'


def empty_history():
    return {'schema': SCHEMA, 'runs': []}


def _int(value, default=0):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _float(value, default=0.0):
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def normalize_run(run):
    """整形一次运行摘要；未知字段丢弃，避免历史文件被污染。"""
    if not isinstance(run, dict):
        return None
    clicks = _int(run.get('click_count'))
    success = min(_int(run.get('success_count')), clicks)
    fail = min(_int(run.get('fail_count')), clicks)
    return {
        'timestamp': str(run.get('timestamp') or '')[:32],
        'click_count': clicks,
        'success_count': success,
        'fail_count': fail,
        'exception_count': _int(run.get('exception_count')),
        'runtime_seconds': round(_float(run.get('runtime_seconds')), 1),
        'interval_seconds': _float(run.get('interval_seconds')),
        'mode': str(run.get('mode') or '')[:32],
        'button': str(run.get('button') or '')[:16],
        'stop_reason': str(run.get('stop_reason') or '')[:120],
    }


def normalize(history, limit=DEFAULT_LIMIT):
    limit = max(1, _int(limit, DEFAULT_LIMIT))
    if not isinstance(history, dict):
        return empty_history()
    runs_raw = history.get('runs')
    if not isinstance(runs_raw, list):
        return empty_history()
    runs = []
    for raw in runs_raw:
        clean = normalize_run(raw)
        if clean is not None:
            runs.append(clean)
    # 仅保留最近 limit 条；不删除文件本身，滚动裁剪由 append/save 完成。
    runs = runs[-limit:]
    return {'schema': SCHEMA, 'runs': runs}


def load(path, limit=DEFAULT_LIMIT):
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            return normalize(json.load(handle), limit=limit)
    except (OSError, ValueError, TypeError):
        return empty_history()


def save(path, history, limit=DEFAULT_LIMIT):
    clean = normalize(history, limit=limit)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix='.run-history-', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(clean, handle, ensure_ascii=False, indent=1)
            handle.write('\n')
        os.replace(temp_path, path)
    except Exception:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass
        raise
    return clean


def append_run(history, run, limit=DEFAULT_LIMIT):
    clean = normalize(history, limit=limit)
    item = normalize_run(run)
    if item is None:
        return clean
    clean['runs'].append(item)
    clean['runs'] = clean['runs'][-max(1, _int(limit, DEFAULT_LIMIT)):]
    return clean


def summarize(history):
    runs = normalize(history)['runs']
    clicks = sum(r['click_count'] for r in runs)
    success = sum(r['success_count'] for r in runs)
    exceptions = sum(1 for r in runs if r['exception_count'] > 0)
    failed = sum(1 for r in runs if r['fail_count'] > 0 or r['exception_count'] > 0)
    total_runtime = sum(r['runtime_seconds'] for r in runs)
    return {
        'count': len(runs),
        'clicks': clicks,
        'success_rate': (min(1.0, success / clicks) * 100.0) if clicks else None,
        'avg_runtime_seconds': (total_runtime / len(runs)) if runs else 0.0,
        'exception_runs': exceptions,
        'failed_runs': failed,
        'total_runtime_seconds': total_runtime,
    }


def summary_text(history):
    summary = summarize(history)
    if not summary['count']:
        return '运行历史：暂无（完成一次运行后自动记录，最多保留 30 次）'
    rate = '--' if summary['success_rate'] is None else '%.1f%%' % summary['success_rate']
    mm, ss = int(summary['avg_runtime_seconds']) // 60, int(summary['avg_runtime_seconds']) % 60
    return '最近 %d 次 · 成功率 %s · 平均时长 %02d:%02d · 异常 %d 次' % (
        summary['count'], rate, mm, ss, summary['failed_runs'])


def trend_points(history):
    """返回每次运行的 (成功率%, 时长秒, 是否异常)；缺失点击数时成功率为 0。"""
    runs = normalize(history)['runs']
    points = []
    for run in runs:
        clicks = run['click_count']
        rate = (min(1.0, run['success_count'] / clicks) * 100.0) if clicks else 0.0
        points.append({
            'rate': rate,
            'runtime': run['runtime_seconds'],
            'abnormal': bool(run['fail_count'] or run['exception_count']),
        })
    return points


def write_csv(path, history):
    """导出最近记录为 UTF-8 BOM CSV，Excel 直接打开不乱码。"""
    runs = normalize(history)['runs']
    with open(path, 'w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow([
            'timestamp', 'click_count', 'success_count', 'fail_count',
            'exception_count', 'runtime_seconds', 'success_rate_pct',
            'interval_seconds', 'mode', 'button', 'stop_reason',
        ])
        for run in runs:
            clicks = run['click_count']
            rate = (min(1.0, run['success_count'] / clicks) * 100.0) if clicks else 0.0
            writer.writerow([
                run['timestamp'], clicks, run['success_count'], run['fail_count'],
                run['exception_count'], run['runtime_seconds'], '%.1f' % rate,
                run['interval_seconds'], run['mode'], run['button'], run['stop_reason'],
            ])
        if not runs:
            writer.writerow(['', 0, 0, 0, 0, 0.0, '', '', '', '', ''])
    return path


def default_csv_name(now=None):
    stamp = (now or datetime.now()).strftime('%Y%m%d-%H%M%S')
    return 'AutoClicker-history-%s.csv' % stamp
