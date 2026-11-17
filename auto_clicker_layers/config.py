# -*- coding: utf-8 -*-
"""配置层（NFR-09）：默认配置、JSON 读写、schema 补齐与迁移备份。不依赖 tkinter。"""
import datetime
import json
import os
import shutil

DEFAULT_CONFIG = {
    'interval_seconds': 10,
    'click_mode': 'random',
    'click_area': {'x': 0, 'y': 0, 'width': 1920, 'height': 1080},
    'prevent_sleep': True,
    'mouse_follow_enabled': True,
    'mouse_move_speed': 0.1,
    'mouse_move_only': False,
    'startup_countdown': 3,
    'click_limit': 0,
    'duration_limit': 0,
    'failsafe_enabled': False,
    'target_window_keyword': '',
    'close_to_tray': True,
    'click_button': 'left',
    'hold_ms': 10,
    'interval_unit': 's',
    'jitter_pct': 0,
    'hotkey_start': 'f6',
    'hotkey_emergency': 'f8',
    'autostart': False,
    'use_multi_points': False,
    'multi_points': [],
    'theme_mode': 'light',
    'schedule': {'enabled': False, 'start_at': '09:00',
                 'stop_after_min': 0, 'weekdays': [1, 2, 3, 4, 5]},
    'config_version': 2,
}


def clone_defaults():
    """返回默认配置的深拷贝（避免调用方修改共享字典）。"""
    return json.loads(json.dumps(DEFAULT_CONFIG))


def read_config(path):
    """读取 JSON 配置；文件不存在返回 None，格式非法抛 ValueError。"""
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8-sig') as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise ValueError('配置根节点必须是对象')
    return value


def normalize_config(config):
    """补齐默认字段、profiles/current_profile、config_version 与 schedule 子字段。"""
    if not isinstance(config, dict):
        config = {}
    for key, value in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = json.loads(json.dumps(value))
    try:
        if int(config.get('config_version', 0) or 0) < 2:
            config['config_version'] = 2
    except (TypeError, ValueError):
        config['config_version'] = 2
    if not isinstance(config.get('profiles'), dict):
        config['profiles'] = {}
    if 'current_profile' not in config:
        config['current_profile'] = None
    sched = config.get('schedule')
    if not isinstance(sched, dict):
        sched = {}
    sched.setdefault('enabled', False)
    sched.setdefault('start_at', '09:00')
    sched.setdefault('stop_after_min', 0)
    sched.setdefault('weekdays', [1, 2, 3, 4, 5])
    config['schedule'] = sched
    return config


def config_version(config):
    try:
        return int((config or {}).get('config_version', 0) or 0)
    except (TypeError, ValueError, AttributeError):
        return 0


def backup_config(path):
    """复制原配置为 v1-backup-时间戳；不存在返回 None。"""
    try:
        if not os.path.exists(path):
            return None
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        backup = path + '.v1-backup-' + stamp
        shutil.copy2(path, backup)
        return backup
    except Exception as e:
        print('配置迁移备份失败: ' + str(e))
        return None


def write_config(path, config):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
