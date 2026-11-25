# -*- coding: utf-8 -*-
"""引擎层纯逻辑（NFR-09 第一层：不依赖 tkinter，可独立单元测试）。

包含区域归一化、目标窗口匹配、间隔/抖动计算、输入参数校验、定时计划判定。
UI 层只做取值、错误展示与状态机编排。
"""
from datetime import datetime, timedelta
import threading


MAX_INTERVAL = 3600
MAX_INTERVAL_BY_UNIT = {'ms': 86_400_000, 's': 86_400, 'min': 1_440, 'h': 24}
INTERVAL_UNITS = ('ms', 's', 'min', 'h')
MAX_CPS = 200
MAX_HOLD_MS = 5000
WEEKDAY_LABELS = {'每天': [1, 2, 3, 4, 5, 6, 7], '工作日': [1, 2, 3, 4, 5], '周末': [6, 7]}


class PauseGate:
    """可复用暂停闸门：暂停期间不消耗点击计数，继续后重新排下一周期。"""

    def __init__(self):
        self._paused = threading.Event()

    def pause(self):
        self._paused.set()

    def resume(self):
        self._paused.clear()

    def toggle(self):
        if self._paused.is_set():
            self.resume()
        else:
            self.pause()
        return self._paused.is_set()

    def paused(self):
        return self._paused.is_set()

    def wait_until_resumed(self, should_continue, poll_seconds=0.02):
        """暂停时短轮询等待；返回 False 表示外部已要求停止。"""
        while self._paused.is_set():
            if not should_continue():
                return False
            self._paused.wait(poll_seconds)
        return should_continue()


def normalize_region(x1, y1, x2, y2):
    """把任意方向拖拽的矩形归一化为 (left, top, right, bottom)。"""
    left, right = sorted((int(x1), int(x2)))
    top, bottom = sorted((int(y1), int(y2)))
    return left, top, right, bottom


def target_window_matches(keyword, title, process_name='', class_name=''):
    """FR-E03/T06158：目标窗口关键字匹配（标题/进程/类名，大小写不敏感）。

    ``|`` 分隔多个候选关键字，任一命中即可；空关键字=不校验。
    """
    key = (keyword or '').strip().lower()
    if not key:
        return True
    fields = ((title or '').lower(), (process_name or '').lower(),
              (class_name or '').lower())
    return any(part and any(part in field for field in fields)
               for part in (item.strip() for item in key.split('|')))


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
    if unit == 'min':
        return val * 60.0
    if unit == 'h':
        return val * 3600.0
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


def validate_interval_for_unit(raw, unit):
    """按单位校验间隔，允许 1ms–24h；保留旧 validate_interval 的秒级口径。"""
    if unit not in INTERVAL_UNITS:
        return None, '间隔单位必须为 ms/s/min/h'
    value = _int_value(raw)
    if value is None:
        return None, '点击间隔必须为整数'
    max_value = MAX_INTERVAL_BY_UNIT[unit]
    if value < 1:
        return None, '点击间隔必须 >= 1'
    if value > max_value:
        return None, '点击间隔必须 <= %d %s' % (max_value, unit)
    return value, None


def validate_cps(raw):
    """单点 CPS 校验：1–200。"""
    value = _int_value(raw)
    if value is None:
        return None, 'CPS 必须为整数'
    if value < 1 or value > MAX_CPS:
        return None, 'CPS 必须在 1-%d 之间' % MAX_CPS
    return value, None


def validate_cps_range(min_raw, max_raw):
    """随机 CPS 范围校验：1 ≤ min ≤ max ≤ 200。"""
    lo, err = validate_cps(min_raw)
    if err:
        return None, err
    hi, err = validate_cps(max_raw)
    if err:
        return None, err
    if lo > hi:
        return None, '最小 CPS 不能大于最大 CPS'
    return (lo, hi), None


def cps_interval_seconds(min_cps, max_cps, rng=None):
    """按 [min,max] CPS 取一次间隔秒数；非法范围回退 1 CPS。"""
    try:
        lo = max(1, int(min_cps))
        hi = max(lo, int(max_cps))
    except (TypeError, ValueError):
        lo = hi = 1
    if rng is not None and hi > lo:
        cps = rng.uniform(lo, hi)
    else:
        cps = (lo + hi) / 2.0
    return 1.0 / max(1.0, float(cps))


def validate_duty(raw):
    """占空比校验：0 表示不启用；启用时必须在 10–90%。"""
    value = _int_value(raw)
    if value is None:
        return None, '占空比必须为整数'
    if value == 0:
        return 0, None
    if value < 10 or value > 90:
        return None, '占空比必须为 0（关闭）或 10-90%'
    return value, None


def duty_hold_ms(interval_seconds, duty_pct):
    """按占空比换算按住毫秒数；未启用返回 None，最短 1ms、最长 5000ms。"""
    if not duty_pct or duty_pct <= 0 or interval_seconds <= 0:
        return None
    hold = interval_seconds * 1000.0 * duty_pct / 100.0
    return int(max(1, min(5000, round(hold))))


def validate_countdown(raw):
    value = _int_value(raw)
    if value is None:
        return None, '启动倒计时必须为整数'
    if value < 0 or value > 5:
        return None, '启动倒计时必须在 0-5 秒之间'
    return value, None


def validate_double_gap(raw):
    """双击间隔（两次按下之间）校验：1–500ms。"""
    value = _int_value(raw)
    if value is None:
        return None, '双击间隔必须为整数'
    if value < 1 or value > 500:
        return None, '双击间隔必须在 1-500ms 之间'
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
    if value > MAX_HOLD_MS:
        return None, '按住时长不能超过 %d ms' % MAX_HOLD_MS
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


# ==================== 周计划多时段（T06157） ====================
MAX_SCHEDULE_PERIODS = 8


def periods_from_text(text, default_days=None):
    """把 ``09:00-30;13:00-45`` 解析为多时段列表；空串返回 []。"""
    raw = str(text or '').replace('；', ';').replace('，', ';').strip()
    if not raw:
        return []
    periods = []
    for token in raw.split(';'):
        token = token.strip()
        if not token:
            continue
        if '-' not in token:
            raise ValueError('时段格式需为 HH:MM-分钟，收到：%s' % token)
        start_text, stop_text = token.split('-', 1)
        start = parse_schedule_start(start_text)
        try:
            stop_min = int(str(stop_text).strip() or 0)
        except ValueError:
            raise ValueError('运行分钟需为整数，收到：%s' % token)
        if stop_min < 0 or stop_min > 1440:
            raise ValueError('运行分钟需在 0–1440，收到：%s' % token)
        periods.append({'start_at': '%02d:%02d' % start,
                        'stop_after_min': stop_min,
                        'weekdays': list(default_days or [1, 2, 3, 4, 5])})
    return normalize_schedule_periods(periods)


def periods_to_text(periods):
    parts = []
    for item in normalize_schedule_periods(periods):
        start = item['start']
        parts.append('%02d:%02d-%d' % (start[0], start[1], item['stop_after_min']))
    return ';'.join(parts)


def normalize_schedule_periods(periods, fallback=None):
    """规范化多时段；无效项抛 ValueError，全部无效时回落到 fallback/单时段。"""
    if periods is None:
        periods = []
    if isinstance(periods, dict):
        periods = [periods]
    if not isinstance(periods, (list, tuple)):
        raise ValueError('多时段需为列表')
    normalized = []
    for item in periods:
        if not isinstance(item, dict):
            raise ValueError('多时段项需为对象')
        raw_start = item.get('start_at', item.get('start', '09:00'))
        if isinstance(raw_start, (list, tuple)) and len(raw_start) == 2:
            start = (int(raw_start[0]), int(raw_start[1]))
            if not (0 <= start[0] <= 23 and 0 <= start[1] <= 59):
                raise ValueError('时间需在 00:00–23:59')
        else:
            start = parse_schedule_start(raw_start)
        try:
            stop_min = int(item.get('stop_after_min', item.get('stop', 0)) or 0)
        except (TypeError, ValueError):
            raise ValueError('运行分钟需为整数')
        if stop_min < 0 or stop_min > 1440:
            raise ValueError('运行分钟需在 0–1440')
        days = item.get('weekdays', (fallback or {}).get('weekdays') if isinstance(fallback, dict) else None)
        if days is None:
            days = (fallback or {}).get('weekdays') if isinstance(fallback, dict) else [1, 2, 3, 4, 5]
        try:
            days = sorted(set(int(d) for d in days if 1 <= int(d) <= 7))
        except (TypeError, ValueError):
            days = [1, 2, 3, 4, 5]
        if not days:
            days = [1, 2, 3, 4, 5]
        normalized.append({'start': start, 'stop_after_min': stop_min, 'weekdays': days})
    if not normalized and isinstance(fallback, dict):
        raw_start = fallback.get('start', (9, 0))
        if isinstance(raw_start, (list, tuple)) and len(raw_start) == 2:
            start = (int(raw_start[0]), int(raw_start[1]))
            if not (0 <= start[0] <= 23 and 0 <= start[1] <= 59):
                raise ValueError('时间需在 00:00–23:59')
        else:
            try:
                start = parse_schedule_start(raw_start)
            except (TypeError, ValueError) as exc:
                raise ValueError('单时段开始时间无效：%s' % exc)
        try:
            stop_min = max(0, int(fallback.get('stop_after_min', 0) or 0))
        except (TypeError, ValueError):
            raise ValueError('单时段运行分钟需为整数')
        try:
            legacy_days = sorted(set(
                int(d) for d in fallback.get('weekdays', [1, 2, 3, 4, 5])
                if 1 <= int(d) <= 7))
        except (TypeError, ValueError):
            legacy_days = [1, 2, 3, 4, 5]
        normalized = [{
            'start': start,
            'stop_after_min': stop_min,
            'weekdays': legacy_days or [1, 2, 3, 4, 5],
        }]
    if len(normalized) > MAX_SCHEDULE_PERIODS:
        raise ValueError('多时段最多 %d 段' % MAX_SCHEDULE_PERIODS)
    return sorted(normalized, key=lambda p: p['start'])


def validate_schedule_no_overlap(periods):
    """M9：拒绝同一天重复开始或执行区间重叠的时段。

    时段按周循环展开为分钟区间；跨零点通过相邻周平移比较。
    stop_after_min=0 视为瞬时开始，只参与重复开始校验。
    """
    normalized = normalize_schedule_periods(periods)
    def _hm(start):
        return '%02d:%02d' % start

    for i, first in enumerate(normalized):
        for second in normalized[i + 1:]:
            common = set(first['weekdays']) & set(second['weekdays'])
            if not common:
                continue
            if first['start'] == second['start']:
                raise ValueError('时段开始时间重复：%s' % _hm(first['start']))
            dur1 = max(0, int(first['stop_after_min']))
            dur2 = max(0, int(second['stop_after_min']))
            if dur1 <= 0 and dur2 <= 0:
                continue
            for day1 in first['weekdays']:
                for day2 in second['weekdays']:
                    start1 = (day1 - 1) * 1440 + first['start'][0] * 60 + first['start'][1]
                    start2 = (day2 - 1) * 1440 + second['start'][0] * 60 + second['start'][1]
                    for shift in (-10080, 0, 10080):
                        s2 = start2 + shift
                        if start1 < s2 + dur2 and s2 < start1 + dur1:
                            raise ValueError(
                                '时段重叠：%s-%d 与 %s-%d' % (
                                    _hm(first['start']), dur1,
                                    _hm(second['start']), dur2))
    return normalized


def schedule_latest_period(now, periods):
    """返回 <= now 的最近一个时段 {occurrence, stop_after_min}；跨零点看前一天。"""
    latest = None
    for period in normalize_schedule_periods(periods):
        hh, mm = period['start']
        base = datetime.combine(now.date(), datetime.min.time()).replace(hour=hh, minute=mm)
        for delta in (-1, 0):
            occ = base + timedelta(days=delta)
            if occ.isoweekday() in period['weekdays'] and occ <= now:
                if latest is None or occ > latest['occurrence']:
                    latest = dict(occurrence=occ, stop_after_min=period['stop_after_min'])
    return latest


def schedule_next_period_text(now, periods):
    """返回下一段生效时段的 ``MM-dd HH:MM``；8 天内无则 ``--``。"""
    best = None
    for period in normalize_schedule_periods(periods):
        hh, mm = period['start']
        base = datetime.combine(now.date(), datetime.min.time()).replace(hour=hh, minute=mm)
        for delta in range(0, 8):
            occ = base + timedelta(days=delta)
            if occ.isoweekday() in period['weekdays'] and occ > now:
                if best is None or occ < best:
                    best = occ
                break
    return best.strftime('%m-%d %H:%M') if best else '--'
