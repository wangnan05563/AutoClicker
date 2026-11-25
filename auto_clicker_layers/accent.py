# -*- coding: utf-8 -*-
"""T06162 / AC-27：强调色合法性、对比度保护与 hover/pressed 派生。

仅作用于 UI 主色；success/danger/warning 等功能色不受影响。
"""
import re

HEX_RE = re.compile(r'^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')


def normalize_hex(value):
    match = HEX_RE.match(str(value or '').strip())
    if not match:
        raise ValueError('颜色需为 #RRGGBB 或 #RGB')
    raw = match.group(1)
    if len(raw) == 3:
        raw = ''.join(ch * 2 for ch in raw)
    return '#' + raw.upper()


def _rgb(color):
    value = normalize_hex(color)[1:]
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return '#%02X%02X%02X' % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def _linear(channel):
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(color):
    r, g, b = _rgb(color)
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def contrast_ratio(fg, bg):
    a, b = relative_luminance(fg), relative_luminance(bg)
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)


def readability_on(color, light='#FFFFFF', dark='#111111'):
    return light if contrast_ratio(color, light) >= contrast_ratio(color, dark) else dark


def _mix(color, target, amount):
    a, b = _rgb(color), _rgb(target)
    return _hex(tuple(a[i] * (1 - amount) + b[i] * amount for i in range(3)))


def derive_states(accent, background):
    """返回 hover/pressed/soft 三档派生色；hover/pressed 向背景反差方向推进。"""
    normalized = normalize_hex(accent)
    background = normalize_hex(background)
    toward = '#FFFFFF' if relative_luminance(background) < 0.5 else '#000000'
    hover = _mix(normalized, toward, 0.10)
    pressed = _mix(normalized, toward, 0.20)
    # L7：同一个 on_primary 要同时覆盖基色/hover/pressed，取三者最小对比度最大者。
    candidates = ('#FFFFFF', '#111111')
    on_primary = max(
        candidates,
        key=lambda c: min(contrast_ratio(c, color) for color in (normalized, hover, pressed)))
    min_ratio = min(contrast_ratio(on_primary, color) for color in (normalized, hover, pressed))
    # 极端中间亮度仍不足 4.5:1 时，把 hover/pressed 拉回基色，优先保证可读性。
    for key in ('hover', 'pressed'):
        color = hover if key == 'hover' else pressed
        if contrast_ratio(on_primary, color) >= 4.5:
            continue
        for step in range(1, 21):
            trial = _mix(color, normalized, step / 20.0)
            if contrast_ratio(on_primary, trial) >= 4.5:
                if key == 'hover':
                    hover = trial
                else:
                    pressed = trial
                break
    return {
        'primary': normalized,
        'primary_hover': hover,
        'primary_pressed': pressed,
        'soft': _mix(normalized, background, 0.12),
        'on_primary': on_primary,
    }


def ensure_accent(candidate, background, min_ratio=4.5):
    """低对比度时自动向背景反差方向调深；调到极限仍不达标则拒绝。

    返回 ``(accent, adjusted, ratio)``；拒绝时抛 ValueError。
    """
    background = normalize_hex(background)
    accent = normalize_hex(candidate)
    ratio = contrast_ratio(accent, background)
    if ratio >= min_ratio:
        return accent, False, ratio
    toward = '#FFFFFF' if relative_luminance(background) < 0.5 else '#000000'
    for step in range(1, 21):
        trial = _mix(accent, toward, step / 20.0)
        trial_ratio = contrast_ratio(trial, background)
        if trial_ratio >= min_ratio:
            return trial, True, trial_ratio
    raise ValueError('颜色 %s 与背景对比度 %.2f:1，自动调整后仍低于 %.1f:1' % (
        accent, ratio, min_ratio))


def apply_to_palette(palette, candidate, min_ratio=4.5):
    """把强调色写入语义调色板副本；失败抛 ValueError，调用方回退原主题。"""
    pal = dict(palette or {})
    bg = pal.get('bg', '#FFFFFF')
    accent, adjusted, ratio = ensure_accent(candidate, bg, min_ratio)
    states = derive_states(accent, bg)
    pal.update({
        'primary': states['primary'],
        'primary_hover': states['primary_hover'],
        'primary_pressed': states['primary_pressed'],
        'soft': states['soft'],
        'on_primary': states['on_primary'],
        'accent_adjusted': adjusted,
        'accent_ratio': ratio,
    })
    return pal
