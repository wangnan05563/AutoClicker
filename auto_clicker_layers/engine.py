# -*- coding: utf-8 -*-
"""引擎层纯逻辑（NFR-09 第一层：不依赖 tkinter，可独立单元测试）。

包含区域归一化、目标窗口匹配、间隔/抖动计算、输入参数校验、定时计划判定。
UI 层只做取值、错误展示与状态机编排。
"""
from datetime import datetime, timedelta


MAX_INTERVAL = 3600
WEEKDAY_LABELS = {'每天': [1, 2, 3, 4, 5, 6, 7], '工作日': [1, 2, 3, 4, 5], '周末': [6, 7]}


def normalize_region(x1, y1, x2, y2):
    """把任意方向拖拽的矩形归一化为 (left, top, right, bottom)。"""
    left, right = sorted((int(x1), int(x2)))
    top, bottom = sorted((int(y1), int(y2)))
    return left, top, right, bottom


def target_window_matches(keyword, title, process_name=''):
    """FR-E03：目标窗口关键字匹配（标题或进程名，大小写不敏感）。空关键字=不校验。"""
    key = (keyword or '').strip().lower()
    if not key:
        return True
    return key in (title or '').lower() or key in (process_name or '').lower()


def effective_interval_seconds(value, unit):
    """按间隔单位换算为秒；非法值回退 1 秒，负数归零。"""
    try:
        val = float(value)
    except (TypeError, ValueError):
        val = 1.0
    if val < 0:
        val = 0.0
    if unit == 'ms':
        return val / 1000.0
    return val


def jittered_wait(base_seconds, jitter_pct, rng=None):
    """返回叠加 jitter 后的等待秒数；rng 需提供 uniform(a,b)，默认不抖动。"""
    if base_seconds <= 0:
        return 0.0
    if jitter_pct and jitter_pct > 0 and rng is not None:
        factor = 1.0 + rng.uniform(-jitter_pct / 100.0, jitter_pct / 100.0)
        return max(0.0, base_seconds * factor)
    return base_seconds


def _int_value(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def validate_interval(raw):
    value = _int_value(raw)
    if value is None:
        return None, '点击间隔必须为整数'
    if value < 1:
        return None, '点击间隔必须 >= 1'
    if value > MAX_INTERVAL:
        return None, '点击间隔必须 <= %d' % MAX_INTERVAL
    return value, None


def validate_countdown(raw):
    value = _int_value(raw)
    if value is None:
        return None, '启动倒计时必须为整数'
    if value < 0 or value > 5:
        return None, '启动倒计时必须在 0-5 秒之间'
    return value, None


def validate_click_limit(raw):
    value = _int_value(raw)
    if value is None:
        return None, '点击次数上限必须为整数'
    if value < 0:
        return None, '点击次数上限不能为负数'
    return value, None


def validate_duration_limit(raw):
    value = _int_value(raw)
    if value is None:
        return None, '运行时长上限必须为整数'
    if value < 0:
        return None, '运行时长上限不能为负数'
    return value, None


def validate_jitter(raw):
    value = _int_value(raw)
    if value is None:
        return None, '随机抖动必须为整数'
    if value < 0 or value > 100:
        return None, '随机抖动必须在 0-100 之间'
    return value, None


def validate_hold_ms(raw):
    value = _int_value(raw)
    if value is None:
        return None, '按住时长必须为整数'
    if value < 0:
        return None, '按住时长不能为负数'
    return value, None


def parse_schedule_start(value):
    parts = str(value or '').strip().replace('：', ':').split(':')
    if len(parts) != 2:
        raise ValueError('时间格式需为 HH:MM')
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError('时间格式需为 HH:MM')
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError('时间需在 00:00–23:59')
    return hour, minute


def weekdays_to_label(weekdays):
    try:
        days = sorted(set(int(d) for d in weekdays))
    except (TypeError, ValueError):
        days = [1, 2, 3, 4, 5]
    if days == [1, 2, 3, 4, 5, 6, 7]:
        return '每天'
    if days == [1, 2, 3, 4, 5]:
        return '工作日'
    if days == [6, 7]:
        return '周末'
    return '工作日'


def label_to_weekdays(label):
    return list(WEEKDAY_LABELS.get(label or '工作日', WEEKDAY_LABELS['工作日']))


def schedule_occurrence(now, start, days):
    """返回 <= now 的最近一次生效计划（含跨零点前一天）。"""
    hh, mm = start
    base = datetime.combine(now.date(), datetime.min.time()).replace(hour=hh, minute=mm)
    candidates = []
    for delta in (-1, 0):
        occ = base + timedelta(days=delta)
        if occ.isoweekday() in days and occ <= now:
            candidates.append(occ)
    return max(candidates) if candidates else None


def schedule_grace_end(occurrence, stop_after_min):
    """计划可触发/运行窗口的结束时刻：不限时长给 5 分钟补算宽限。"""
    return occurrence + timedelta(minutes=stop_after_min if stop_after_min > 0 else 5)


def schedule_next_text(now, start, days):
    hh, mm = start
    base = datetime.combine(now.date(), datetime.min.time()).replace(hour=hh, minute=mm)
    for delta in range(0, 8):
        occ = base + timedelta(days=delta)
        if occ.isoweekday() in days and occ > now:
            return occ.strftime('%m-%d %H:%M')
    return '--'
