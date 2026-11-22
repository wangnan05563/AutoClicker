# -*- coding: utf-8 -*-
"""新增分层（config / theme / platform）单测（NFR-09）。"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_clicker_layers import config as cfg
from auto_clicker_layers import theme
from auto_clicker_layers import platform_io as plat


class ConfigLayerTests(unittest.TestCase):
    def test_clone_defaults_is_deep_copy(self):
        a = cfg.clone_defaults()
        b = cfg.clone_defaults()
        a['click_area']['x'] = 999
        a['multi_points'].append({'x': 1, 'y': 2})
        self.assertEqual(b['click_area']['x'], 0)
        self.assertEqual(b['multi_points'], [])

    def test_normalize_fills_missing_fields(self):
        data = {'interval_seconds': 3,
                'click_area': {'x': 1, 'y': 2, 'width': 3, 'height': 4},
                'schedule': {'enabled': True}}
        out = cfg.normalize_config(data)
        for key in cfg.DEFAULT_CONFIG:
            self.assertIn(key, out)
        self.assertEqual(out['interval_seconds'], 3)
        self.assertEqual(out['click_area'], {'x': 1, 'y': 2, 'width': 3, 'height': 4})
        self.assertEqual(out['schedule']['start_at'], '09:00')
        self.assertEqual(out['schedule']['stop_after_min'], 0)
        self.assertEqual(out['schedule']['weekdays'], [1, 2, 3, 4, 5])
        self.assertEqual(out['profiles'], {})
        self.assertIsNone(out['current_profile'])
        self.assertEqual(out['config_version'], 2)

    def test_normalize_handles_non_dict(self):
        out = cfg.normalize_config(None)
        self.assertEqual(out['interval_seconds'], 10)
        self.assertEqual(out['config_version'], 2)
        self.assertEqual(out['schedule']['weekdays'], [1, 2, 3, 4, 5])
        self.assertEqual(cfg.normalize_config({'schedule': 'bad'})['schedule']['start_at'], '09:00')

    def test_config_version(self):
        self.assertEqual(cfg.config_version({'config_version': 2}), 2)
        self.assertEqual(cfg.config_version({'config_version': '3'}), 3)
        self.assertEqual(cfg.config_version({'config_version': 'x'}), 0)
        self.assertEqual(cfg.config_version(None), 0)

    def test_read_write_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'config.json')
            self.assertIsNone(cfg.read_config(path))
            cfg.write_config(path, {'a': 1})
            self.assertEqual(cfg.read_config(path), {'a': 1})
            with open(path, 'w', encoding='utf-8') as f:
                f.write('[]')
            with self.assertRaises(ValueError):
                cfg.read_config(path)
            with open(path, 'w', encoding='utf-8') as f:
                f.write('{bad json')
            with self.assertRaises(ValueError):
                cfg.read_config(path)

    def test_backup_config(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'config.json')
            self.assertIsNone(cfg.backup_config(path))
            cfg.write_config(path, {'a': 1})
            backup = cfg.backup_config(path)
            self.assertTrue(backup and os.path.exists(backup))
            self.assertEqual(cfg.read_config(backup), {'a': 1})
            self.assertIn('.v1-backup-', backup)


class ThemeLayerTests(unittest.TestCase):
    def test_shade_color(self):
        self.assertEqual(theme.shade_color('#ffffff'), '#d8d8d8')
        self.assertEqual(theme.shade_color('not-a-color'), 'not-a-color')
        self.assertEqual(theme.shade_color('#000000'), '#000000')

    def test_resolve_palette(self):
        self.assertEqual(theme.resolve_palette('light')['bg'], '#ffffff')
        self.assertEqual(theme.resolve_palette('dark')['bg'], '#212529')
        self.assertEqual(theme.resolve_palette('unknown')['bg'], '#ffffff')
        self.assertEqual(theme.resolve_palette('system', dark_detector=lambda: True)['bg'], '#212529')
        self.assertEqual(theme.resolve_palette('system', dark_detector=lambda: False)['bg'], '#ffffff')

    def test_resolve_palette_custom_themes(self):
        custom = {'light': {'bg': '#010101'}, 'dark': {'bg': '#020202'}}
        self.assertEqual(theme.resolve_palette('light', custom)['bg'], '#010101')
        self.assertEqual(theme.resolve_palette('dark', custom)['bg'], '#020202')

    def test_system_is_dark_returns_bool(self):
        self.assertIsInstance(theme.system_is_dark(), bool)


    def test_theme_pack_migration_from_theme_mode(self):
        legacy = cfg.normalize_config({'theme_mode': 'dark'})
        self.assertEqual(legacy['theme_pack'], 'dark')
        fresh = cfg.normalize_config({'theme_pack': 'ocean'})
        self.assertEqual(fresh['theme_pack'], 'ocean')
        self.assertEqual(fresh['theme_mode'], 'light')


class ThemePackTests(unittest.TestCase):
    """FR-33/34/35：5 套内置主题与用户 JSON 主题包。"""

    def test_five_builtin_themes_and_tokens(self):
        self.assertEqual(set(theme.THEMES), {'light', 'dark', 'high_contrast', 'ocean', 'sand'})
        for key, pal in theme.THEMES.items():
            for token in theme.REQUIRED_COLOR_KEYS:
                self.assertIn(token, pal, '%s missing %s' % (key, token))
                self.assertRegex(pal[token], r'^#[0-9a-fA-F]{6}$')
            self.assertEqual(pal['id'], key)
            self.assertTrue(pal['name'])
            self.assertIsInstance(pal['is_dark'], bool)

    def test_builtin_contrast_meets_wcag_aa(self):
        pairs = {'text': 'bg', 'muted': 'bg', 'on_primary': 'primary',
                 'on_success': 'success', 'on_danger': 'danger', 'on_warning': 'warning'}
        for key, pal in theme.THEMES.items():
            for fg, bg in pairs.items():
                self.assertGreaterEqual(theme.contrast_ratio(pal[fg], pal[bg]), 4.5,
                                        '%s %s/%s' % (key, fg, bg))

    def test_theme_display_map_has_system_and_each_theme(self):
        mapping = theme.theme_display_map()
        self.assertEqual(mapping[theme.SYSTEM_THEME_NAME], 'system')
        for key, pal in theme.THEMES.items():
            self.assertEqual(mapping[pal['name']], key)

    def test_validate_theme_pack_accepts_valid_pack(self):
        colors = {k: theme.THEMES['light'][k] for k in theme.REQUIRED_COLOR_KEYS}
        data = {'schema': theme.THEME_SCHEMA, 'id': 'my_theme_1', 'name': '我的主题',
                'mode': 'light', 'colors': colors}
        pal, errors = theme.validate_theme_pack(data)
        self.assertEqual(errors, [])
        self.assertEqual(pal['id'], 'my_theme_1')
        self.assertFalse(pal['is_dark'])
        self.assertEqual(pal['text'], colors['text'])

    def test_validate_theme_pack_rejects_bad_payload(self):
        colors = {k: theme.THEMES['light'][k] for k in theme.REQUIRED_COLOR_KEYS}
        base = {'schema': theme.THEME_SCHEMA, 'id': 'ok_theme', 'mode': 'light', 'colors': colors}
        cases = [
            dict(base, schema='bad'),
            dict(base, id='light'),
            dict(base, id='A'),
            dict(base, mode='blue'),
            dict(base, colors={k: v for k, v in colors.items() if k != 'focus'}),
            dict(base, colors=dict(colors, focus='red')),
            dict(base, colors=dict(colors, extra='#ffffff')),
            dict(base, script='calc'),
            dict(base, meta={'url': 'https://example.com'}),
        ]
        for data in cases:
            pal, errors = theme.validate_theme_pack(data)
            self.assertIsNone(pal)
            self.assertTrue(errors, data)

    def test_load_user_themes_skips_invalid_json(self):
        colors = {k: theme.THEMES['sand'][k] for k in theme.REQUIRED_COLOR_KEYS}
        valid = {'schema': theme.THEME_SCHEMA, 'id': 'user_sand', 'name': '用户暖沙',
                 'mode': 'light', 'colors': colors}
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, 'good.json'), 'w', encoding='utf-8') as f:
                json.dump(valid, f)
            with open(os.path.join(d, 'bad.json'), 'w', encoding='utf-8') as f:
                f.write('{bad')
            themes, errors = theme.load_user_themes(d)
            self.assertIn('user_sand', themes)
            self.assertEqual(themes['user_sand']['name'], '用户暖沙')
            self.assertTrue(errors)
            self.assertEqual(len(errors), 1)

    def test_resolve_palette_for_each_theme(self):
        for key in theme.THEMES:
            self.assertEqual(theme.resolve_palette(key)['id'], key)


    def test_detect_input_backend_non_linux(self):
        ok, backend, message = plat.detect_input_backend()
        if not plat.IS_LINUX:
            self.assertTrue(ok)
            self.assertTrue(backend)
            self.assertEqual(message, '')
        else:
            self.assertIsInstance(ok, bool)

    def test_is_wayland_session_non_linux(self):
        if not plat.IS_LINUX:
            self.assertFalse(plat._is_wayland_session())

    def test_ydotool_move_falls_back_between_flags(self):
        calls = []

        def fake_run(args, timeout=2):
            calls.append(args)
            return len(calls) == 2
        original = plat._ydotool_run
        plat._ydotool_run = fake_run
        try:
            self.assertTrue(plat._ydotool_move(10, 20))
            self.assertEqual(calls[0][0], 'mousemove')
            self.assertIn('-x', calls[0])
            self.assertIn(str(10), calls[0])
        finally:
            plat._ydotool_run = original

    def test_ydotool_click_modes(self):
        runs = []
        original_run = plat._ydotool_run
        original_move = plat._ydotool_move
        plat._ydotool_run = lambda args, timeout=2: runs.append(args) or True
        plat._ydotool_move = lambda x, y: True
        try:
            self.assertTrue(plat._ydotool_click(1, 2, 'left'))
            self.assertEqual(runs[-1][0], 'click')
            runs.clear()
            self.assertTrue(plat._ydotool_click(1, 2, 'double'))
            self.assertEqual(len(runs), 2)
            runs.clear()
            self.assertTrue(plat._ydotool_click(1, 2, 'right', hold_ms=5))
            self.assertEqual(runs[0][0], 'mousedown')
            self.assertEqual(runs[-1][0], 'mouseup')
        finally:
            plat._ydotool_run = original_run
            plat._ydotool_move = original_move

    def test_get_cursor_pos_returns_pair(self):
        try:
            pos = plat.get_cursor_pos()
        except Exception as e:
            # 远程桌面/锁屏等无桌面访问权限环境无法读取光标位置
            self.skipTest('当前桌面会话不可读取光标位置: %s' % e)
        self.assertEqual(len(pos), 2)

    def test_restore_system_settings_does_not_raise(self):
        plat.restore_system_settings()

    def test_platform_flags_consistent(self):
        self.assertEqual(plat.IS_WINDOWS, sys.platform == 'win32')
        self.assertEqual(plat.IS_LINUX, sys.platform.startswith('linux'))
        self.assertEqual(plat.IS_MACOS, sys.platform == 'darwin')


if __name__ == '__main__':
    unittest.main()
