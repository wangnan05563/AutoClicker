# -*- coding: utf-8 -*-
"""FR-01 首启向导模板（纯逻辑，不依赖 tkinter）。

三套场景模板 + 自定义 + 跳过用的「推荐安全」：
- keep_online  保持在线：只移动不点击，60 秒一次，防锁屏
- checkin      挂机签到：点击 1 次后自动停止，防锁屏
- button_repeat 固定按钮连点：1 秒一次，不限次数
- custom       自定义：保留现有参数，仅切到简单模式
- safe         推荐安全：10 秒一次、3 秒倒计时、鼠标位移急停、防锁屏
"""
import copy

SCHEMA = 'autoclicker.onboarding/1'

TEMPLATES = (
    {
        'id': 'keep_online',
        'name': '保持在线',
        'icon': 'laptop',
        'description': '每 60 秒轻微移动鼠标，不执行点击；适合远程会话/在线状态保持。',
        'patch': {
            'interval_seconds': 60,
            'interval_unit': 's',
            'click_mode': 'center',
            'prevent_sleep': True,
            'mouse_follow_enabled': True,
            'mouse_move_only': True,
            'click_limit': 0,
            'duration_limit': 0,
            'failsafe_enabled': True,
        },
    },
    {
        'id': 'checkin',
        'name': '挂机签到',
        'icon': 'check',
        'description': '启动后点击目标 1 次即停止；适合每日签到、领奖、打卡按钮。',
        'patch': {
            'interval_seconds': 300,
            'interval_unit': 's',
            'click_mode': 'center',
            'prevent_sleep': True,
            'mouse_follow_enabled': True,
            'mouse_move_only': False,
            'click_limit': 1,
            'duration_limit': 0,
            'failsafe_enabled': True,
        },
    },
    {
        'id': 'button_repeat',
        'name': '固定按钮连点',
        'icon': 'repeat',
        'description': '每 1 秒点击同一目标，不设次数上限；适合游戏/工具按钮连续操作。',
        'patch': {
            'interval_seconds': 1,
            'interval_unit': 's',
            'click_mode': 'center',
            'prevent_sleep': False,
            'mouse_follow_enabled': True,
            'mouse_move_only': False,
            'click_limit': 0,
            'duration_limit': 0,
            'failsafe_enabled': True,
        },
    },
    {
        'id': 'custom',
        'name': '自定义',
        'icon': 'gear',
        'description': '保留当前参数，只把界面切到简单模式，稍后可在规则页调整。',
        'patch': {
            'interval_seconds': 10,
            'interval_unit': 's',
            'click_mode': 'random',
            'prevent_sleep': False,
            'mouse_follow_enabled': True,
            'mouse_move_only': False,
            'click_limit': 0,
            'duration_limit': 0,
            'failsafe_enabled': True,
        },
    },
)

SAFE_ID = 'safe'
SAFE_TEMPLATE = {
    'id': SAFE_ID,
    'name': '安全试运行（只移动）',
    'icon': 'shield',
    'description': '每 10 秒轻微移动鼠标，不点击；3 秒倒计时 + 位移急停 + 防锁屏，适合第一次试用。',
    'patch': {
        'interval_seconds': 10,
        'interval_unit': 's',
        'click_mode': 'center',
        'prevent_sleep': True,
        'mouse_follow_enabled': True,
        'mouse_move_only': True,
        'click_limit': 0,
        'duration_limit': 0,
        'failsafe_enabled': True,
        'startup_countdown': 3,
    },
}

_TEMPLATE_MAP = {t['id']: t for t in TEMPLATES}
_TEMPLATE_MAP[SAFE_ID] = SAFE_TEMPLATE

_HOTKEY_WHITELIST = ('f6', 'f7', 'f8', 'f9', 'f10', 'f11', 'f12', 'esc')
# H6：这些模板会产生真实点击，向导里必须由用户显式选择目标区域。
REAL_CLICK_TEMPLATE_IDS = ('checkin', 'button_repeat')


def template_requires_explicit_target(template_id):
    return template_id in REAL_CLICK_TEMPLATE_IDS


def template_ids():
    return [t['id'] for t in TEMPLATES]


def get_template(template_id):
    return _TEMPLATE_MAP.get(template_id)


def _normalize_area(click_area):
    if not isinstance(click_area, dict):
        return None
    try:
        x = int(click_area.get('x', 0))
        y = int(click_area.get('y', 0))
        width = max(1, int(click_area.get('width', 1)))
        height = max(1, int(click_area.get('height', 1)))
    except (TypeError, ValueError):
        return None
    return {'x': x, 'y': y, 'width': width, 'height': height}


def area_center(config):
    """取当前区域的中心点；无有效区域时返回 None。"""
    area = _normalize_area((config or {}).get('click_area'))
    if not area:
        return None
    return {
        'x': area['x'] + area['width'] // 2,
        'y': area['y'] + area['height'] // 2,
        'width': 1,
        'height': 1,
    }


def point_area(x, y):
    return {'x': int(x), 'y': int(y), 'width': 1, 'height': 1}


def normalize_hotkeys(start, emergency):
    start = str(start or 'f6').strip().lower()
    emergency = str(emergency or 'f8').strip().lower()
    if start not in _HOTKEY_WHITELIST:
        raise ValueError('启动热键不在允许列表: %s' % start)
    if start == 'esc':
        raise ValueError('Esc 固定为急停，不能作为启动热键')
    if emergency not in _HOTKEY_WHITELIST:
        raise ValueError('急停热键不在允许列表: %s' % emergency)
    if start == emergency:
        raise ValueError('启动热键与急停热键不能相同')
    return start, emergency


def apply_template(config, template_id, click_area=None, hotkey_start='f6',
                   hotkey_emergency='f8', mark_done=True):
    """返回应用模板后的配置副本；不修改传入对象。"""
    template = get_template(template_id)
    if template is None:
        raise ValueError('未知首启模板: %s' % template_id)
    result = copy.deepcopy(config) if isinstance(config, dict) else {}
    is_custom = template_id == 'custom'
    # M8：自定义模板的描述是“保留当前参数”，不得套用 patch 重置。
    if not is_custom:
        result.update(copy.deepcopy(template['patch']))
    result['ui_mode'] = 'simple'
    if not is_custom:
        result['click_button'] = 'left'
        result['hold_ms'] = 10
        result['jitter_pct'] = 0
        result['use_multi_points'] = False
        result['multi_points'] = []
        result['target_window_keyword'] = ''
        result['startup_countdown'] = int(
            template['patch'].get('startup_countdown', 3))
    start, emergency = normalize_hotkeys(hotkey_start, hotkey_emergency)
    result['hotkey_start'] = start
    result['hotkey_emergency'] = emergency
    if is_custom and click_area is None:
        area = _normalize_area(result.get('click_area'))
    else:
        area = _normalize_area(click_area) or area_center(result)
    if area:
        result['click_area'] = area
    if not is_custom:
        schedule = dict(result.get('schedule') or {})
        schedule['enabled'] = False
        result['schedule'] = schedule
    if mark_done:
        result['onboarding_done'] = True
        result['onboarding_template'] = template_id
    return result


def safe_config(config, click_area=None, hotkey_start='f6', hotkey_emergency='f8'):
    """跳过向导时使用的推荐安全配置（仍可选择是否写入当前配置）。"""
    return apply_template(config, SAFE_ID, click_area=click_area,
                          hotkey_start=hotkey_start,
                          hotkey_emergency=hotkey_emergency,
                          mark_done=True)


def summary_lines(template_id, config, click_area=None):
    """返回 UI 摘要行，供向导右侧预览与测试断言。"""
    tpl = get_template(template_id)
    if tpl is None:
        tpl = SAFE_TEMPLATE
    patch = tpl['patch']
    interval = patch.get('interval_seconds', 10)
    unit = patch.get('interval_unit', 's')
    area = _normalize_area(click_area) or area_center(config)
    if area and area['width'] <= 1 and area['height'] <= 1:
        target = '点 (%d, %d)' % (area['x'], area['y'])
    elif area:
        target = '区域 %dx%d @ (%d, %d)' % (
            area['width'], area['height'], area['x'], area['y'])
    else:
        target = '当前区域'
    limit = patch.get('click_limit', 0)
    duration = patch.get('duration_limit', 0)
    stop_parts = []
    if limit:
        stop_parts.append('点击 %d 次' % limit)
    if duration:
        stop_parts.append('%d 分钟' % duration)
    stop = ' + '.join(stop_parts) if stop_parts else '手动停止'
    move_only = '只移动不点击' if patch.get('mouse_move_only') else '执行点击'
    sleep = '开' if patch.get('prevent_sleep') else '关'
    return [
        '间隔：%s %s · %s' % (interval, unit, move_only),
        '目标：%s' % target,
        '停止：%s · 防锁屏：%s' % (stop, sleep),
        '安全：3 秒倒计时 + F8/Esc 急停',
    ]
