# -*- coding: utf-8 -*-
"""主题层（NFR-09）：语义调色板、颜色变换与系统深浅色检测。不依赖 tkinter。"""
import sys

THEMES = {
    'light': {
        'bg': '#ffffff', 'fg': '#212529', 'muted': '#6c757d',
        'primary': '#0056b3', 'success': '#1e7e34', 'danger': '#b02a37',
        'warning': '#8a4b00', 'surface': '#f8f9fa', 'border': '#868e96',
        'on_primary': '#ffffff', 'on_success': '#ffffff',
        'on_danger': '#ffffff', 'on_warning': '#ffffff', 'on_muted': '#ffffff',
    },
    'dark': {
        'bg': '#212529', 'fg': '#e9ecef', 'muted': '#adb5bd',
        'primary': '#4a90d9', 'success': '#2ecc71', 'danger': '#f16c6c',
        'warning': '#e67e22', 'surface': '#2b3035', 'border': '#6c757d',
        'on_primary': '#0b0f14', 'on_success': '#0b0f14',
        'on_danger': '#0b0f14', 'on_warning': '#0b0f14', 'on_muted': '#0b0f14',
    },
}


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
    """按 light/dark/system 解析调色板；system 用平台检测结果。"""
    themes = themes or THEMES
    mode = theme_mode
    if mode == 'system':
        detector = dark_detector or system_is_dark
        mode = 'dark' if detector() else 'light'
    return themes.get(mode, themes['light'])
