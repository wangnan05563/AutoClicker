# -*- coding: utf-8 -*-
"""主题层（NFR-09 / FR-33~35）：语义调色板、5 套内置主题、用户 JSON 主题包。

设计约束：
- 不依赖 tkinter；
- 用户主题只允许 JSON 数据，不执行脚本、不读取 URL/路径；
- 内置主题保留旧键 `fg` 等别名，避免现有 UI 大面积改动。
"""
import json
import os
import re
import sys

# FR-33：14 个标准颜色令牌（PRD 10.3）
REQUIRED_COLOR_KEYS = (
    'bg', 'surface', 'surface_alt', 'text', 'muted',
    'primary', 'primary_hover', 'primary_pressed', 'on_primary',
    'success', 'danger', 'warning', 'border', 'focus',
)
COLOR_KEY_RE = re.compile(r'^#[0-9a-fA-F]{6}$')
THEME_ID_RE = re.compile(r'^[a-z][a-z0-9_-]{2,31}$')
THEME_SCHEMA = 'autoclicker.theme/1'


def _palette(colors, *, is_dark=False, name='', typography=None, theme_id=''):
    """补齐 UI 兼容别名（fg/on_success/...），并挂载元信息。"""
    pal = dict(colors)
    pal.setdefault('fg', pal.get('text', '#000000'))
    pal.setdefault('on_success', pal.get('on_primary', '#ffffff'))
    pal.setdefault('on_danger', pal.get('on_primary', '#ffffff'))
    pal.setdefault('on_warning', pal.get('on_primary', '#ffffff'))
    pal.setdefault('on_muted', pal.get('on_primary', '#ffffff'))
    pal['is_dark'] = bool(is_dark)
    pal['name'] = name
    pal['id'] = theme_id
    pal['typography'] = dict(typography or {
        'font_family': '微软雅黑',
        'mono_family': 'Consolas',
        'scale': 1.0,
    })
    return pal


THEMES = {
    'light': _palette({
        'bg': '#ffffff', 'surface': '#f8f9fa', 'surface_alt': '#eef1f4',
        'text': '#212529', 'muted': '#6c757d',
        'primary': '#0056b3', 'primary_hover': '#004a99', 'primary_pressed': '#003d80',
        'on_primary': '#ffffff', 'success': '#1e7e34', 'danger': '#b02a37',
        'warning': '#8a4b00', 'border': '#868e96', 'focus': '#0056b3',
    }, is_dark=False, name='晨曦（浅色）', theme_id='light'),
    'dark': _palette({
        'bg': '#212529', 'surface': '#2b3035', 'surface_alt': '#343a40',
        'text': '#e9ecef', 'muted': '#adb5bd',
        'primary': '#4a90d9', 'primary_hover': '#3d7ab8', 'primary_pressed': '#326596',
        'on_primary': '#0b0f14', 'success': '#2ecc71', 'danger': '#f16c6c',
        'warning': '#e67e22', 'border': '#6c757d', 'focus': '#4a90d9',
    }, is_dark=True, name='深空（深色）', theme_id='dark'),
    'high_contrast': _palette({
        'bg': '#000000', 'surface': '#111111', 'surface_alt': '#1a1a1a',
        'text': '#ffffff', 'muted': '#d0d0d0',
        'primary': '#00ffff', 'primary_hover': '#00d9d9', 'primary_pressed': '#00b3b3',
        'on_primary': '#000000', 'success': '#00ff00', 'danger': '#ff5555',
        'warning': '#ffcc00', 'border': '#ffffff', 'focus': '#ffff00',
    }, is_dark=True, name='高对比', theme_id='high_contrast'),
    'ocean': _palette({
        'bg': '#071b26', 'surface': '#0d2b3a', 'surface_alt': '#12394a',
        'text': '#e6f4fa', 'muted': '#9fc3d3',
        'primary': '#2f9ed1', 'primary_hover': '#2787b4', 'primary_pressed': '#206f96',
        'on_primary': '#04121a', 'success': '#2ecc71', 'danger': '#ff6b6b',
        'warning': '#f0a500', 'border': '#3c6b7a', 'focus': '#2f9ed1',
    }, is_dark=True, name='海洋蓝', theme_id='ocean'),
    'sand': _palette({
        'bg': '#f6efe4', 'surface': '#fffaf2', 'surface_alt': '#efe3d2',
        'text': '#3a322a', 'muted': '#7a6a57',
        'primary': '#9e5718', 'primary_hover': '#854912', 'primary_pressed': '#6f3d0f',
        'on_primary': '#ffffff', 'success': '#3e7d3e', 'danger': '#b23a3a',
        'warning': '#8a5a00', 'border': '#c9b8a2', 'focus': '#b5651d',
    }, is_dark=False, name='暖沙', theme_id='sand'),
}

SYSTEM_THEME_NAME = '跟随系统'
THEME_DISPLAY = {key: pal['name'] for key, pal in THEMES.items()}
THEME_DISPLAY['system'] = SYSTEM_THEME_NAME


def shade_color(hex_color, factor=0.85):
    """按比例调暗十六进制色；非法输入原样返回（用于 activebackground）。"""
    try:
        h = hex_color.lstrip('#')
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        r = max(0, int(r * factor))
        g = max(0, int(g * factor))
        b = max(0, int(b * factor))
        return '#%02x%02x%02x' % (r, g, b)
    except Exception:
        return hex_color


def system_is_dark():
    """Windows 注册表检测应用深浅色；其他平台默认浅色。"""
    if sys.platform != 'win32':
        return False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        val = winreg.QueryValueEx(key, "AppsUseLightTheme")[0]
        return val == 0
    except Exception:
        return False


def resolve_palette(theme_mode, themes=None, dark_detector=None):
    """按主题 ID 解析调色板；system 用平台检测结果。未知 ID 回退 light。"""
    themes = themes or THEMES
    mode = theme_mode or 'light'
    if mode == 'system':
        detector = dark_detector or system_is_dark
        mode = 'dark' if detector() else 'light'
    return themes.get(mode, themes.get('light', next(iter(themes.values()))))


def _is_hex_color(value):
    return isinstance(value, str) and bool(COLOR_KEY_RE.match(value))


def _relative_luminance(hex_color):
    try:
        h = hex_color.lstrip('#')
        vals = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
        vals = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in vals]
        return 0.2126 * vals[0] + 0.7152 * vals[1] + 0.0722 * vals[2]
    except Exception:
        return 0.0


def contrast_ratio(fg, bg):
    """WCAG 相对对比度；非法颜色返回 0。"""
    if not (_is_hex_color(fg) and _is_hex_color(bg)):
        return 0.0
    l1, l2 = _relative_luminance(fg), _relative_luminance(bg)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


def contrast_text(background, light='#ffffff', dark='#000000'):
    """给背景色选对比度更高的文字色。"""
    return light if contrast_ratio(light, background) >= contrast_ratio(dark, background) else dark


def validate_theme_pack(data, existing_ids=None):
    """校验用户主题包；返回 (palette, errors)。错误为空表示通过。"""
    errors = []
    existing_ids = set(existing_ids or THEMES.keys())
    if not isinstance(data, dict):
        return None, ['主题包必须是 JSON 对象']
    unknown = set(data.keys()) - {'schema', 'id', 'name', 'mode', 'colors', 'typography', 'meta'}
    if unknown:
        errors.append('不允许的字段: ' + ', '.join(sorted(unknown)))
    if data.get('schema') != THEME_SCHEMA:
        errors.append('schema 必须为 %s' % THEME_SCHEMA)
    theme_id = str(data.get('id') or '').strip().lower()
    if not THEME_ID_RE.match(theme_id):
        errors.append('id 必须为 3-32 位小写字母/数字/下划线/短横线，且以字母开头')
    elif theme_id in existing_ids:
        errors.append('id 与内置主题冲突: ' + theme_id)
    mode = data.get('mode', 'light')
    if mode not in ('light', 'dark', 'high_contrast'):
        errors.append('mode 必须为 light/dark/high_contrast')
    colors = data.get('colors')
    if not isinstance(colors, dict):
        return None, errors + ['colors 必须是对象']
    missing = [k for k in REQUIRED_COLOR_KEYS if k not in colors]
    if missing:
        errors.append('缺少颜色令牌: ' + ', '.join(missing))
    for key, value in colors.items():
        if key not in REQUIRED_COLOR_KEYS:
            errors.append('未知颜色令牌: ' + key)
        elif not _is_hex_color(value):
            errors.append('颜色格式错误(%s): %s' % (key, value))
    typography = data.get('typography') or {}
    if not isinstance(typography, dict):
        errors.append('typography 必须是对象')
        typography = {}
    meta = data.get('meta') or {}
    if not isinstance(meta, dict):
        errors.append('meta 必须是对象')
    # 明确拒绝脚本/URL/路径类键，避免主题包变成执行载体
    forbidden = ('script', 'url', 'path', 'command', 'exec', 'shell')
    for section in (data, colors, typography, meta):
        if isinstance(section, dict):
            for key in section:
                if any(token in str(key).lower() for token in forbidden):
                    errors.append('禁止的字段: ' + str(key))
    if errors:
        return None, errors
    return _palette(colors, is_dark=(mode != 'light'), name=str(data.get('name') or theme_id),
                    typography=typography, theme_id=theme_id), []


def load_theme_pack(path):
    """读取单个用户主题文件；返回 (palette, errors)。"""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        return None, ['读取 JSON 失败: ' + str(e)]
    return validate_theme_pack(data)


def load_user_themes(directory):
    """扫描用户主题目录；返回 (themes, errors)。"""
    themes, errors = {}, []
    try:
        if not os.path.isdir(directory):
            return themes, errors
        for name in sorted(os.listdir(directory)):
            if not name.lower().endswith('.json'):
                continue
            path = os.path.join(directory, name)
            pal, errs = load_theme_pack(path)
            if pal:
                themes[pal['id']] = pal
            else:
                errors.append((name, '; '.join(errs)))
    except Exception as e:
        errors.append(('theme-dir', str(e)))
    return themes, errors


def theme_display_map(themes=None):
    """显示名 -> 主题 ID，供下拉框使用。"""
    themes = themes or THEMES
    mapping = {SYSTEM_THEME_NAME: 'system'}
    for key, pal in themes.items():
        mapping[pal.get('name') or key] = key
    return mapping
