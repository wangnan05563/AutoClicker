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


class PlatformLayerTests(unittest.TestCase):
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
        pos = plat.get_cursor_pos()
        self.assertEqual(len(pos), 2)

    def test_restore_system_settings_does_not_raise(self):
        plat.restore_system_settings()

    def test_platform_flags_consistent(self):
        self.assertEqual(plat.IS_WINDOWS, sys.platform == 'win32')
        self.assertEqual(plat.IS_LINUX, sys.platform.startswith('linux'))
        self.assertEqual(plat.IS_MACOS, sys.platform == 'darwin')


if __name__ == '__main__':
    unittest.main()
