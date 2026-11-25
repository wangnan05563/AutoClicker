# -*- coding: utf-8 -*-
"""全局热键解析与 Windows 占用探测（T06151）。

纯解析逻辑可单测；``probe_windows_hotkey`` 仅在 Windows 调用
``RegisterHotKey`` 做一次临时注册探测，不抢占其他程序热键。
"""
import ctypes
import os
import random
import sys

MOD_ALT = 0x0001
MOD_CTRL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
_MOD_ALIASES = {
    'ctrl': ('ctrl', MOD_CTRL), 'control': ('ctrl', MOD_CTRL),
    'alt': ('alt', MOD_ALT), 'shift': ('shift', MOD_SHIFT),
    'win': ('win', MOD_WIN), 'windows': ('win', MOD_WIN),
    'cmd': ('win', MOD_WIN), 'super': ('win', MOD_WIN),
}
_VK_NAMES = {
    'esc': 0x1B, 'escape': 0x1B, 'enter': 0x0D, 'return': 0x0D,
    'space': 0x20, 'tab': 0x09, 'backspace': 0x08, 'delete': 0x2E,
    'del': 0x2E, 'insert': 0x2D, 'ins': 0x2D, 'home': 0x24, 'end': 0x23,
    'pageup': 0x21, 'pgup': 0x21, 'pagedown': 0x22, 'pgdn': 0x22,
    'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
    'comma': 0xBC, ',': 0xBC, 'period': 0xBE, '.': 0xBE, 'semicolon': 0xBA,
    'colon': 0xBA, ':': 0xBA, 'slash': 0xBF, '/': 0xBF, 'backslash': 0x5C, '\\': 0x5C,
    'minus': 0xBD, '-': 0xBD, 'plus': 0xBB, '+': 0xBB,
}


def normalize_hotkey(text):
    return str(text or '').strip().lower().replace(' ', '')


def parse_hotkey(text):
    """返回 (modifiers, vk, normalized, error)。"""
    normalized = normalize_hotkey(text)
    if not normalized:
        return 0, 0, normalized, '热键不能为空'
    # L2：Ctrl++ 的尾缀加号会被 split 过滤掉，先归一成 plus
    if normalized.endswith('++'):
        normalized = normalized[:-2] + '+plus'
    elif normalized in ('+', ':'):
        normalized = 'plus' if normalized == '+' else 'colon'
    parts = [p for p in normalized.replace('-', '+').split('+') if p]
    if not parts:
        return 0, 0, normalized, '热键格式无效'
    modifiers = 0
    base = None
    for part in parts:
        if part in _MOD_ALIASES:
            modifiers |= _MOD_ALIASES[part][1]
        elif base is None:
            base = part
        else:
            return 0, 0, normalized, '热键只能包含一个主键'
    if base is None:
        return 0, 0, normalized, '热键缺少主键'
    vk = _vk_for(base)
    if vk is None:
        return 0, 0, normalized, '不支持的按键：%s' % base
    # L2：plus/colon 在美式键盘上是 Shift 组合，缺少 MOD_SHIFT 会注册成 =/;
    if base in ('plus', '+', 'colon', ':'):
        modifiers |= MOD_SHIFT
    return modifiers, vk, normalized, ''


def _vk_for(name):
    if name in _VK_NAMES:
        return _VK_NAMES[name]
    if len(name) == 1:
        ch = name.upper()
        if 'A' <= ch <= 'Z' or '0' <= ch <= '9':
            return ord(ch)
    if name.startswith('f') and name[1:].isdigit():
        number = int(name[1:])
        if 1 <= number <= 24:
            return 0x70 + number - 1
    return None


def probe_windows_hotkey(text):
    """临时注册探测 Windows 热键是否被其他程序占用。

    返回 (occupied, reason)。非 Windows/API 不可用时 occupied=False，
    不阻断用户应用热键，只在 reason 说明检测不可用。
    """
    if os.name != 'nt' or not sys.platform.startswith('win'):
        return False, '当前平台不支持系统级热键占用检测'
    mods, vk, _, error = parse_hotkey(text)
    if error:
        return False, error
    probe_id = random.randint(0x4000, 0x7FFF)
    user32 = ctypes.windll.user32
    try:
        if user32.RegisterHotKey(0, probe_id, mods, vk):
            try:
                user32.UnregisterHotKey(0, probe_id)
            except Exception:
                pass
            return False, ''
        code = ctypes.windll.kernel32.GetLastError()
        if code == 1409:
            return True, '组合键已被其他程序占用（WinError 1409）'
        return False, '无法确认占用状态（WinError %s）' % (code or 'unknown')
    except Exception as exc:
        return False, '热键检测不可用：%s' % exc
