# -*- coding: utf-8 -*-
"""FR-13：宏的 JSON schema、录制缓冲与回放计划（纯逻辑，不依赖 Tk）。

宏文件是可读 JSON，允许手工编辑后重新载入。录制只保存离散动作：
``move/click/key/wait``；不记录鼠标连续轨迹，也不执行脚本。
"""
import json
import os
import re
import tempfile
import threading
import time
from datetime import datetime

SCHEMA = 'autoclicker.macro/1'
MAX_STEPS = 2000
MAX_WAIT_MS = 60000
MAX_HOLD_MS = 5000
MAX_LOOP_COUNT = 99
MIN_SPEED = 0.5
MAX_SPEED = 2.0
MIN_GAP_MS = 10
BUTTONS = ('left', 'right', 'middle', 'double')
KEY_ACTIONS = ('press', 'down', 'up')


class MacroError(ValueError):
    """宏格式或文件错误；消息面向用户。"""


def _int(value, field, minimum=None, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise MacroError('%s 必须是整数' % field)
    if minimum is not None and number < minimum:
        raise MacroError('%s 不能小于 %s' % (field, minimum))
    if maximum is not None and number > maximum:
        raise MacroError('%s 不能大于 %s' % (field, maximum))
    return number


def _str(value, field, default=None, max_len=64):
    if value is None:
        if default is not None:
            return default
        raise MacroError('%s 不能为空' % field)
    text = str(value).strip()
    if not text:
        if default is not None:
            return default
        raise MacroError('%s 不能为空' % field)
    if len(text) > max_len:
        raise MacroError('%s 长度超限（最多 %s）' % (field, max_len))
    return text


def _normalize_screen(screen):
    if screen is None:
        return None
    if not isinstance(screen, dict):
        raise MacroError('screen 必须是对象')
    result = {}
    for key in ('left', 'top', 'width', 'height'):
        if key not in screen:
            raise MacroError('screen 缺少 %s' % key)
        result[key] = _int(screen[key], 'screen.%s' % key)
    if result['width'] <= 0 or result['height'] <= 0:
        raise MacroError('screen.width/height 必须大于 0')
    return result


def _normalize_step(raw, index):
    if not isinstance(raw, dict):
        raise MacroError('第 %d 步必须是对象' % index)
    step_type = str(raw.get('type', '')).strip().lower()
    if step_type == 'move':
        return {
            'type': 'move',
            'x': _int(raw.get('x'), 'move.x'),
            'y': _int(raw.get('y'), 'move.y'),
        }
    if step_type == 'click':
        button = str(raw.get('button', 'left')).strip().lower()
        if button not in BUTTONS:
            raise MacroError('click.button 必须是 %s' % '/'.join(BUTTONS))
        return {
            'type': 'click',
            'x': _int(raw.get('x'), 'click.x'),
            'y': _int(raw.get('y'), 'click.y'),
            'button': button,
            'hold_ms': _int(raw.get('hold_ms', 0), 'click.hold_ms', 0, MAX_HOLD_MS),
        }
    if step_type == 'key':
        action = str(raw.get('action', 'press')).strip().lower()
        if action not in KEY_ACTIONS:
            raise MacroError('key.action 必须是 %s' % '/'.join(KEY_ACTIONS))
        return {
            'type': 'key',
            'key': _str(raw.get('key'), 'key.key', max_len=32),
            'action': action,
        }
    if step_type == 'wait':
        return {'type': 'wait', 'ms': _int(raw.get('ms'), 'wait.ms', 1, MAX_WAIT_MS)}
    raise MacroError('第 %d 步类型未知：%s' % (index, step_type or '(空)'))


def validate_macro(data):
    """校验并返回规范化后的宏 dict；失败抛 MacroError。"""
    if not isinstance(data, dict):
        raise MacroError('宏文件必须是 JSON 对象')
    if data.get('schema') != SCHEMA:
        raise MacroError('schema 必须是 %s' % SCHEMA)
    name = _str(data.get('name'), 'name', default='未命名宏', max_len=80)
    steps_raw = data.get('steps')
    if not isinstance(steps_raw, list) or not steps_raw:
        raise MacroError('steps 必须是非空数组')
    if len(steps_raw) > MAX_STEPS:
        raise MacroError('steps 最多 %s 步' % MAX_STEPS)
    steps = []
    for index, raw in enumerate(steps_raw, 1):
        steps.append(_normalize_step(raw, index))
    screen = _normalize_screen(data.get('screen'))
    created_at = str(data.get('created_at') or datetime.now().isoformat(timespec='seconds'))
    return {
        'schema': SCHEMA,
        'name': name,
        'created_at': created_at,
        'screen': screen,
        'steps': steps,
    }


def make_macro(name, steps, screen=None, created_at=None):
    return validate_macro({
        'schema': SCHEMA,
        'name': name,
        'created_at': created_at or datetime.now().isoformat(timespec='seconds'),
        'screen': screen,
        'steps': steps,
    })


def save_macro(path, data):
    """规范化并原子写入宏文件，返回规范化后的 dict。"""
    macro = validate_macro(data)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix='.macro-', suffix='.json', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(macro, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
    return macro


def load_macro(path):
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            data = json.load(handle)
    except FileNotFoundError:
        raise MacroError('宏文件不存在：%s' % path)
    except (OSError, ValueError) as exc:
        raise MacroError('宏文件无法读取：%s' % exc)
    return validate_macro(data)


def _duration_ms(macro):
    total = 0
    for step in macro.get('steps', []):
        if step['type'] == 'wait':
            total += step['ms']
        elif step['type'] == 'click':
            total += step.get('hold_ms', 0)
    return total


def duration_ms(macro):
    """宏的等待与按住时长合计（毫秒），供 UI 与列表展示。"""
    return _duration_ms(macro)


def format_duration(ms):
    try:
        total_ms = max(0, int(ms))
    except (TypeError, ValueError):
        total_ms = 0
    seconds = total_ms // 1000
    minutes = seconds // 60
    seconds %= 60
    if minutes:
        return '%d:%02d' % (minutes, seconds)
    return '%d.%03ds' % (seconds, total_ms % 1000)


def sanitize_macro_name(name, fallback=None):
    text = str(name or '').strip()
    text = re.sub(r'[\\/:*?"<>|\\.]+', '_', text)
    text = re.sub(r'_+', '_', text).strip('._ ')
    if not text:
        text = fallback or ('macro-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    return text[:60]


def unique_macro_path(directory, name):
    stem = sanitize_macro_name(name)
    candidate = os.path.join(directory, stem + '.json')
    if not os.path.exists(candidate):
        return candidate
    index = 2
    while True:
        candidate = os.path.join(directory, '%s-%d.json' % (stem, index))
        if not os.path.exists(candidate):
            return candidate
        index += 1


def list_macros(directory):
    """列出宏文件；坏文件也返回，便于 UI 显示错误而不是静默消失。"""
    if not os.path.isdir(directory):
        return []
    entries = []
    for name in os.listdir(directory):
        if not name.lower().endswith('.json'):
            continue
        path = os.path.join(directory, name)
        try:
            macro = load_macro(path)
            entries.append({
                'name': macro['name'],
                'path': path,
                'steps': len(macro['steps']),
                'duration_ms': _duration_ms(macro),
                'created_at': macro['created_at'],
                'valid': True,
                'error': '',
                'mtime': os.path.getmtime(path),
            })
        except (MacroError, OSError) as exc:
            entries.append({
                'name': os.path.splitext(name)[0],
                'path': path,
                'steps': 0,
                'duration_ms': 0,
                'created_at': '',
                'valid': False,
                'error': str(exc),
                'mtime': 0,
            })
    entries.sort(key=lambda item: (-item.get('mtime', 0), item['name']))
    return entries


def rename_macro(path, new_name, directory):
    """把宏另存为新名称并删除旧文件；返回新路径与宏数据。"""
    data = load_macro(path)
    clean_name = sanitize_macro_name(new_name)
    data = dict(data)
    data['name'] = clean_name
    new_path = unique_macro_path(directory, clean_name)
    saved = save_macro(new_path, data)
    if os.path.abspath(new_path) != os.path.abspath(path):
        try:
            os.remove(path)
        except OSError:
            pass
    return new_path, saved


def delete_macro(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        return False
    return True


def export_macro(path, target_path):
    """导出前重新校验并规范化，目标文件可被再次导入。"""
    return save_macro(target_path, load_macro(path))


def import_macro(source_path, directory):
    """导入 JSON 宏到宏目录；同名时自动追加序号，返回 (路径, 数据)。"""
    data = load_macro(source_path)
    target = unique_macro_path(directory, data.get('name') or '未命名宏')
    return target, save_macro(target, data)


def push_recent(recent, path, used_at=None, limit=5):
    """最近使用列表：同一路径去重并置顶，最多 limit 条。"""
    limit = max(1, int(limit))
    clean = []
    for item in (recent or []):
        if not isinstance(item, dict):
            continue
        item_path = str(item.get('path') or '')
        if not item_path:
            continue
        clean.append({'path': item_path, 'used_at': str(item.get('used_at') or '')})
    entry = {'path': os.path.abspath(path),
             'used_at': str(used_at or datetime.now().isoformat(timespec='seconds'))}
    clean = [item for item in clean if os.path.abspath(item['path']) != entry['path']]
    clean.insert(0, entry)
    return clean[:limit]


def recent_label(recent, directory=None):
    for item in (recent or []):
        try:
            path = item.get('path', '')
            name = os.path.splitext(os.path.basename(path))[0]
            if directory and os.path.abspath(os.path.dirname(path)) != os.path.abspath(directory):
                continue
            return '最近使用：%s · %s' % (name, str(item.get('used_at') or '')[:16].replace('T', ' '))
        except Exception:
            continue
    return '最近使用：暂无'


def preview_lines(macro, limit=12):
    lines = []
    for index, step in enumerate(macro.get('steps', [])[:limit], 1):
        if step['type'] == 'move':
            text = 'move   (%d, %d)' % (step['x'], step['y'])
        elif step['type'] == 'click':
            text = 'click  %s (%d, %d)' % (step['button'], step['x'], step['y'])
        elif step['type'] == 'key':
            text = 'key    %s %s' % (step['key'], step['action'])
        else:
            text = 'wait   %d ms' % step['ms']
        lines.append('%02d  %s' % (index, text))
    if len(macro.get('steps', [])) > limit:
        lines.append('… 共 %d 步' % len(macro['steps']))
    return '\n'.join(lines)


class MacroRecorder:
    """线程安全的录制缓冲：按事件间隔生成 wait，click 前自动补 move。"""

    def __init__(self, name, screen=None, clock=None, max_steps=MAX_STEPS,
                 min_gap_ms=MIN_GAP_MS, created_at=None):
        self.name = sanitize_macro_name(name)
        self.screen = _normalize_screen(screen)
        self.clock = clock or time.monotonic
        self.max_steps = max_steps
        self.min_gap_ms = max(0, int(min_gap_ms))
        self.created_at = created_at or datetime.now().isoformat(timespec='seconds')
        self.steps = []
        self._last_time = None
        self._paused = False
        self._lock = threading.Lock()
        self._started_at = None
        self._stopped = False

    def start(self, now=None):
        with self._lock:
            self.steps = []
            self._started_at = self.clock() if now is None else now
            self._last_time = None
            self._paused = False
            self._stopped = False

    def pause(self):
        with self._lock:
            self._paused = True

    def resume(self, now=None):
        with self._lock:
            self._paused = False
            # 暂停期间不生成 wait；恢复后从下一次动作重新计时。
            self._last_time = self.clock() if now is None else now

    @property
    def paused(self):
        return self._paused

    @property
    def step_count(self):
        with self._lock:
            return len(self.steps)

    @property
    def should_stop(self):
        return self.step_count >= self.max_steps

    def _gap_steps(self, now):
        if self._last_time is None:
            self._last_time = now
            return []
        gap = int(round((now - self._last_time) * 1000))
        if gap < self.min_gap_ms:
            return []
        self._last_time = now
        return [{'type': 'wait', 'ms': min(gap, MAX_WAIT_MS)}]

    def _append_locked(self, step, now):
        gap = self._gap_steps(now)
        extra = 2 if step['type'] == 'click' else 1
        if len(self.steps) + len(gap) + extra > self.max_steps:
            return False
        self.steps.extend(gap)
        if step['type'] == 'click':
            self.steps.append({'type': 'move', 'x': step['x'], 'y': step['y']})
        self.steps.append(step)
        return True

    def add_click(self, x, y, button='left', hold_ms=0, now=None):
        with self._lock:
            if self._paused or self._stopped:
                return False
            now = self.clock() if now is None else now
            button = button if button in BUTTONS else 'left'
            step = {
                'type': 'click', 'x': int(x), 'y': int(y),
                'button': button, 'hold_ms': min(MAX_HOLD_MS, max(0, int(hold_ms))),
            }
            return self._append_locked(step, now)

    def add_key(self, key, action='press', now=None):
        with self._lock:
            if self._paused or self._stopped:
                return False
            now = self.clock() if now is None else now
            action = action if action in KEY_ACTIONS else 'press'
            return self._append_locked({
                'type': 'key', 'key': str(key)[:32], 'action': action,
            }, now)

    def add_wait(self, ms, now=None):
        with self._lock:
            if self._paused or self._stopped:
                return False
            now = self.clock() if now is None else now
            return self._append_locked({
                'type': 'wait', 'ms': _int(ms, 'wait.ms', 1, MAX_WAIT_MS),
            }, now)

    def snapshot(self):
        with self._lock:
            self._stopped = True
            steps = list(self.steps)
            return make_macro(self.name, steps, self.screen, self.created_at)


class MacroPlayer:
    """可暂停/停止的回放计划；``execute`` 由 UI 注入，便于测试。"""

    def __init__(self, macro, execute, speed=1.0, loop_count=1,
                 wait=None, clock=None, on_progress=None):
        self.macro = validate_macro(macro)
        try:
            self.speed = min(MAX_SPEED, max(MIN_SPEED, float(speed)))
        except (TypeError, ValueError):
            self.speed = 1.0
        try:
            self.loop_count = max(1, min(MAX_LOOP_COUNT, int(loop_count)))
        except (TypeError, ValueError):
            self.loop_count = 1
        self.execute = execute
        self.wait = wait or time.sleep
        self.clock = clock or time.monotonic
        self.on_progress = on_progress
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._finished = False
        self._status = 'ready'

    @property
    def paused(self):
        return self._paused.is_set()

    @property
    def status(self):
        return self._status

    def stop(self):
        self._stop.set()
        self._paused.clear()

    def toggle_pause(self):
        if self._stop.is_set():
            return
        if self._paused.is_set():
            self._paused.clear()
        else:
            self._paused.set()

    def _wait_ms(self, ms):
        remaining = max(0.0, float(ms) / 1000.0 / self.speed)
        while remaining > 0:
            if self._stop.is_set():
                return False
            if self._paused.is_set():
                self.wait(0.05)
                continue
            chunk = min(0.05, remaining)
            self.wait(chunk)
            remaining -= chunk
        return not self._stop.is_set()

    def _pause_gate(self):
        while self._paused.is_set() and not self._stop.is_set():
            self.wait(0.05)
        return not self._stop.is_set()

    def run(self):
        try:
            for loop_index in range(self.loop_count):
                for step_index, step in enumerate(self.macro['steps']):
                    if not self._pause_gate():
                        self._status = 'stopped'
                        return self._status
                    if step['type'] == 'wait':
                        if not self._wait_ms(step['ms']):
                            self._status = 'stopped'
                            return self._status
                    else:
                        self.execute(step)
                        if self._stop.is_set():
                            self._status = 'stopped'
                            return self._status
                    if self.on_progress:
                        self.on_progress(loop_index, step_index, len(self.macro['steps']))
            self._status = 'finished'
            return self._status
        finally:
            self._finished = True

    @property
    def finished(self):
        return self._finished
