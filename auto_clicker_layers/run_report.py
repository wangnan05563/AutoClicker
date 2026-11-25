# -*- coding: utf-8 -*-
"""FR-02 启动确认与运行结束摘要（纯逻辑，不依赖 tkinter）。"""
import csv
import json
import os

SCHEMA = 'autoclicker.run_report/1'

_MODE_LABELS = {
    'random': '随机位置',
    'center': '中心点',
    'custom': '自定义区域',
}
_BUTTON_LABELS = {
    'left': '左键',
    'right': '右键',
    'middle': '中键',
}


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _area(value):
    if not isinstance(value, dict):
        return None
    try:
        return {
            'x': int(value.get('x', 0)),
            'y': int(value.get('y', 0)),
            'width': max(1, int(value.get('width', 1))),
            'height': max(1, int(value.get('height', 1))),
        }
    except (TypeError, ValueError):
        return None


_UNIT_LABELS = {'ms': '毫秒', 's': '秒', 'min': '分钟', 'h': '小时'}


def interval_label(config):
    config = config or {}
    if 'interval_value' not in config and 'interval_unit' not in config:
        return '%g 秒' % _float(config.get('interval_seconds', 0))
    unit = str(config.get('interval_unit') or 's')
    if 'interval_value' in config:
        value = _int(config.get('interval_value'), 0)
    else:
        value = _int(config.get('interval_seconds', 10), 10)
    return '%d %s' % (value, _UNIT_LABELS.get(unit, '秒'))


def target_label(config):
    config = config or {}
    area = _area(config.get('click_area'))
    points = config.get('multi_points') or []
    mode = config.get('click_mode', 'random')
    if config.get('use_multi_points') and points:
        first = points[0] if isinstance(points[0], dict) else {}
        target = '多点位 %d 个（首个 (%s, %s)）' % (
            len(points), first.get('x', '?'), first.get('y', '?'))
    elif not area:
        target = '当前鼠标位置'
    elif area['width'] <= 1 and area['height'] <= 1:
        target = '点 (%d, %d)' % (area['x'], area['y'])
    else:
        target = '%s %dx%d @ (%d, %d)' % (
            _MODE_LABELS.get(mode, mode), area['width'], area['height'],
            area['x'], area['y'])
    if config.get('mouse_move_only'):
        target += '，只移动不点击（不会产生真实点击）'
    else:
        target += '，将真实点击'
    keyword = str(config.get('target_window_keyword') or '').strip()
    if keyword:
        target += '；前台窗口含“%s”' % keyword
    return target


def stop_conditions(config):
    config = config or {}
    parts = []
    click_limit = _int(config.get('click_limit', 0))
    duration_limit = _int(config.get('duration_limit', 0))
    if click_limit > 0:
        parts.append('点击 %d 次后停止' % click_limit)
    if duration_limit > 0:
        parts.append('运行 %d 分钟后停止' % duration_limit)
    if config.get('failsafe_enabled'):
        parts.append('鼠标位移 >20px 急停')
    if not parts:
        parts.append('手动停止')
    return '；'.join(parts)


def hotkey_label(config):
    config = config or {}
    start = str(config.get('hotkey_start', 'f6') or 'f6').upper()
    emergency = str(config.get('hotkey_emergency', 'f8') or 'f8').upper()
    if emergency == 'ESC':
        return '%s 启动/停止；Esc 急停' % start
    return '%s 启动/停止；%s / Esc 急停' % (start, emergency)


def build_start_lines(config):
    """启动确认框展示：间隔 / 目标 / 停止条件 / 热键。"""
    config = config or {}
    button = _BUTTON_LABELS.get(config.get('click_button', 'left'), '左键')
    hold = _int(config.get('hold_ms', 10), 10)
    jitter = _int(config.get('jitter_pct', 0))
    lines = [
        '间隔：%s（%s，按住 %dms，抖动 %d%%）' % (
            interval_label(config), button, hold, jitter),
        '目标：%s' % target_label(config),
        '停止条件：%s；防锁屏：%s' % (
            stop_conditions(config),
            '开' if config.get('prevent_sleep') else '关'),
        '热键：%s；启动倒计时 %d 秒' % (
            hotkey_label(config), _int(config.get('startup_countdown', 0))),
    ]
    return lines


def should_confirm_start(config, source='manual'):
    """定时任务不弹确认，避免无人值守时卡住；其余手动入口按设置决定。"""
    if source == 'schedule':
        return False
    return bool((config or {}).get('start_confirm_enabled', True))


def runtime_label(seconds):
    seconds = max(0.0, _float(seconds))
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    clock = ('%02d:%02d:%02d' if hours else '%02d:%02d') % (
        (hours, minutes, secs) if hours else (minutes, secs))
    return '%s（%.1f 秒）' % (clock, seconds)


def build_end_lines(stats):
    """结束摘要：点击 / 成功 / 失败 / 异常 / 时长 / 停止原因。"""
    stats = stats or {}
    reason = str(stats.get('stop_reason') or '').strip() or '手动停止'
    clicks = _int(stats.get('click_count', 0))
    success = _int(stats.get('success_count', 0))
    failed = _int(stats.get('fail_count', 0))
    abnormal = _int(stats.get('exception_count', 0))
    mode = _MODE_LABELS.get(stats.get('mode', ''), stats.get('mode', '') or '--')
    button = _BUTTON_LABELS.get(stats.get('button', ''), stats.get('button', '') or '--')
    return [
        '停止原因：%s' % reason,
        '点击：%d 次    成功：%d 次    失败：%d 次    异常：%d 次' % (
            clicks, success, failed, abnormal),
        '运行时长：%s' % runtime_label(stats.get('runtime_seconds', 0)),
        '间隔：%s · 模式：%s · 按键：%s' % (
            interval_label(stats), mode, button),
        '结束时间：%s' % (str(stats.get('timestamp') or '--').replace('T', ' ')),
    ]


def log_summary_line(stats):
    stats = stats or {}
    return '运行摘要 | 点击=%d 成功=%d 失败=%d 异常=%d 时长=%.1fs 原因=%s' % (
        _int(stats.get('click_count', 0)),
        _int(stats.get('success_count', 0)),
        _int(stats.get('fail_count', 0)),
        _int(stats.get('exception_count', 0)),
        max(0.0, _float(stats.get('runtime_seconds', 0))),
        str(stats.get('stop_reason') or '').strip() or '手动停止',
    )


def normalized_stats(stats):
    stats = stats or {}
    return {
        'schema': SCHEMA,
        'timestamp': str(stats.get('timestamp') or ''),
        'click_count': max(0, _int(stats.get('click_count', 0))),
        'success_count': max(0, _int(stats.get('success_count', 0))),
        'fail_count': max(0, _int(stats.get('fail_count', 0))),
        'exception_count': max(0, _int(stats.get('exception_count', 0))),
        'runtime_seconds': round(max(0.0, _float(stats.get('runtime_seconds', 0))), 1),
        'interval_seconds': max(0.0, _float(stats.get('interval_seconds', 0))),
        'interval_value': max(0, _int(stats.get('interval_value', 0))),
        'interval_unit': str(stats.get('interval_unit') or 's'),
        'mode': str(stats.get('mode') or ''),
        'button': str(stats.get('button') or ''),
        'stop_reason': str(stats.get('stop_reason') or '').strip() or '手动停止',
    }


def summary_rows(stats):
    data = normalized_stats(stats)
    return [
        ('停止时间', data['timestamp']),
        ('点击次数', data['click_count']),
        ('成功次数', data['success_count']),
        ('失败次数', data['fail_count']),
        ('异常次数', data['exception_count']),
        ('运行时长（秒）', data['runtime_seconds']),
        ('间隔', interval_label(data)),
        ('模式', _MODE_LABELS.get(data['mode'], data['mode'])),
        ('按键', _BUTTON_LABELS.get(data['button'], data['button'])),
        ('停止原因', data['stop_reason']),
    ]


def write_stats(path, stats, fmt=None):
    """导出统计；fmt 省略时按扩展名判断，返回实际写入路径。"""
    fmt = (fmt or os.path.splitext(path)[1].lstrip('.')).lower()
    if fmt not in ('json', 'csv'):
        raise ValueError('不支持的导出格式: %s' % fmt)
    data = normalized_stats(stats)
    if fmt == 'json':
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    else:
        with open(path, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['项目', '数值'])
            writer.writerows(summary_rows(data))
    return path
