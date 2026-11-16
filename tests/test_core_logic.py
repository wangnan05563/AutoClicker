# -*- coding: utf-8 -*-
"""核心纯逻辑单元测试（不创建 Tk 窗口）。"""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_clicker_py3 as app_module
from auto_clicker_py3 import AutoClicker


class FakeVar:
    """模拟 tkinter Variable 的 get()。"""

    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeLabel:
    def __init__(self):
        self.text = ''

    def config(self, **kwargs):
        if 'text' in kwargs:
            self.text = kwargs['text']


def make_clicker():
    """创建不经过 __init__/Tk 的实例，用于测试纯方法。"""
    return object.__new__(AutoClicker)


class IntervalTests(unittest.TestCase):
    def test_seconds_unit(self):
        obj = make_clicker()
        obj.interval_var = FakeVar('10')
        obj.interval_unit = 's'
        self.assertEqual(obj._effective_interval_seconds(), 10.0)

    def test_milliseconds_unit(self):
        obj = make_clicker()
        obj.interval_var = FakeVar('250')
        obj.interval_unit = 'ms'
        self.assertEqual(obj._effective_interval_seconds(), 0.25)

    def test_invalid_value_defaults_to_one(self):
        obj = make_clicker()
        obj.interval_var = FakeVar('abc')
        obj.interval_unit = 's'
        self.assertEqual(obj._effective_interval_seconds(), 1.0)

    def test_negative_value_clamped_to_zero(self):
        obj = make_clicker()
        obj.interval_var = FakeVar('-5')
        obj.interval_unit = 's'
        self.assertEqual(obj._effective_interval_seconds(), 0.0)


class ThemeTests(unittest.TestCase):
    def test_shade_darkens_color(self):
        obj = make_clicker()
        self.assertEqual(obj._shade('#ffffff', 0.5), '#7f7f7f')

    def test_shade_invalid_color_returns_input(self):
        obj = make_clicker()
        self.assertEqual(obj._shade('not-a-color'), 'not-a-color')

    def test_resolve_light_and_dark(self):
        obj = make_clicker()
        obj.THEMES = {'light': {'bg': '#fff'}, 'dark': {'bg': '#000'}}
        obj.theme_mode = 'light'
        self.assertEqual(obj._resolve_palette()['bg'], '#fff')
        obj.theme_mode = 'dark'
        self.assertEqual(obj._resolve_palette()['bg'], '#000')

    def test_resolve_system_uses_detection(self):
        obj = make_clicker()
        obj.THEMES = {'light': {'bg': '#fff'}, 'dark': {'bg': '#000'}}
        obj.theme_mode = 'system'
        with mock.patch.object(obj, '_system_is_dark', return_value=True):
            self.assertEqual(obj._resolve_palette()['bg'], '#000')
        with mock.patch.object(obj, '_system_is_dark', return_value=False):
            self.assertEqual(obj._resolve_palette()['bg'], '#fff')

    def test_log_tag(self):
        self.assertEqual(AutoClicker._log_tag('err'), 'lvl_err')
        self.assertEqual(AutoClicker._log_tag('warn'), 'lvl_warn')
        self.assertEqual(AutoClicker._log_tag(''), '')


class RegionTests(unittest.TestCase):
    def test_normalize_drag_reversed(self):
        region = app_module.normalize_region(300, 200, 100, 50)
        self.assertEqual(region, {'x': 100, 'y': 50, 'width': 201, 'height': 151})

    def test_normalize_click_point(self):
        region = app_module.normalize_region(50, 60, 50, 60)
        self.assertTrue(region['point'])
        self.assertEqual((region['x'], region['y'], region['width'], region['height']),
                         (50, 60, 1, 1))

    def test_random_click_position_in_closed_bounds(self):
        obj = make_clicker()
        obj.config = {'click_area': {'x': 10, 'y': 20, 'width': 5, 'height': 4}}
        obj.click_mode_cache = 'random'
        obj.mode_var = FakeVar('random')
        for _ in range(1000):
            x, y = obj.get_click_position()
            self.assertGreaterEqual(x, 10)
            self.assertLessEqual(x, 14)
            self.assertGreaterEqual(y, 20)
            self.assertLessEqual(y, 23)

    def test_center_click_position(self):
        obj = make_clicker()
        obj.config = {'click_area': {'x': 10, 'y': 20, 'width': 5, 'height': 4}}
        obj.click_mode_cache = 'center'
        obj.mode_var = FakeVar('center')
        self.assertEqual(obj.get_click_position(), (12, 22))


class ClickPointTests(unittest.TestCase):
    def test_multi_points_cycle(self):
        obj = make_clicker()
        points = [{'x': '1', 'y': '2'}, {'x': 3, 'y': 4}]
        self.assertEqual(obj._next_click_point(points, 0), (1, 2, 1))
        self.assertEqual(obj._next_click_point(points, 1), (3, 4, 2))
        self.assertEqual(obj._next_click_point(points, 2), (1, 2, 3))

    def test_single_mode_uses_current_position(self):
        obj = make_clicker()
        obj.get_click_position = lambda: (100, 200)
        self.assertEqual(obj._next_click_point(None, 5), (100, 200, 5))

    def test_failsafe_threshold(self):
        obj = make_clicker()
        with mock.patch.object(app_module, 'get_cursor_pos', return_value=(0, 0)):
            self.assertFalse(obj._failsafe_triggered(None))
            self.assertFalse(obj._failsafe_triggered((0, 0)))
        with mock.patch.object(app_module, 'get_cursor_pos', return_value=(21, 0)):
            self.assertTrue(obj._failsafe_triggered((0, 0)))
        with mock.patch.object(app_module, 'get_cursor_pos', return_value=(0, 21)):
            self.assertTrue(obj._failsafe_triggered((0, 0)))

    def test_limit_reached_click_limit(self):
        obj = make_clicker()
        obj.click_limit = 5
        obj.duration_limit = 0
        obj.click_count = 5
        obj.stop_clicking = mock.Mock()
        self.assertTrue(obj._limit_reached())
        obj.stop_clicking.assert_called_once()

    def test_limit_reached_duration(self):
        obj = make_clicker()
        obj.click_limit = 0
        obj.duration_limit = 1
        obj.start_time = time.time() - 120
        obj.stop_clicking = mock.Mock()
        self.assertTrue(obj._limit_reached())

    def test_limit_not_reached(self):
        obj = make_clicker()
        obj.click_limit = 0
        obj.duration_limit = 0
        obj.click_count = 0
        self.assertFalse(obj._limit_reached())


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.obj = make_clicker()

    @mock.patch('auto_clicker_py3.messagebox.showerror')
    def test_read_interval_valid(self, _):
        self.obj.interval_var = FakeVar('10')
        self.assertEqual(self.obj._read_interval(), 10)

    def test_read_interval_too_small(self):
        self.obj.interval_var = FakeVar('0')
        self.obj.show_field_error = mock.Mock()
        self.assertIsNone(self.obj._read_interval())
        self.obj.show_field_error.assert_called_once()

    def test_read_interval_too_large(self):
        self.obj.interval_var = FakeVar('3601')
        self.obj.show_field_error = mock.Mock()
        self.assertIsNone(self.obj._read_interval())
        self.obj.show_field_error.assert_called_once()

    def test_read_interval_not_integer(self):
        self.obj.interval_var = FakeVar('x')
        self.obj.show_field_error = mock.Mock()
        self.assertIsNone(self.obj._read_interval())
        self.obj.show_field_error.assert_called_once()

    def test_read_countdown_out_of_range(self):
        self.obj.countdown_var = FakeVar('6')
        self.obj.show_field_error = mock.Mock()
        self.assertIsNone(self.obj._read_countdown())
        self.obj.show_field_error.assert_called_once()

    @mock.patch('auto_clicker_py3.messagebox.showerror')
    def test_read_countdown_valid(self, _):
        self.obj.countdown_var = FakeVar('3')
        self.assertEqual(self.obj._read_countdown(), 3)

    def test_read_click_limit_negative(self):
        self.obj.click_limit_var = FakeVar('-1')
        self.obj.show_field_error = mock.Mock()
        self.assertIsNone(self.obj._read_click_limit())
        self.obj.show_field_error.assert_called_once()

    def test_read_duration_limit_negative(self):
        self.obj.duration_limit_var = FakeVar('-2')
        self.obj.show_field_error = mock.Mock()
        self.assertIsNone(self.obj._read_duration_limit())
        self.obj.show_field_error.assert_called_once()

    def test_read_jitter_out_of_range(self):
        self.obj.jitter_var = FakeVar('101')
        self.obj.show_field_error = mock.Mock()
        self.assertIsNone(self.obj._read_jitter())
        self.obj.show_field_error.assert_called_once()

    @mock.patch('auto_clicker_py3.messagebox.showerror')
    def test_read_hold_ms_valid(self, _):
        self.obj.hold_ms_var = FakeVar('10')
        self.assertEqual(self.obj._read_hold_ms(), 10)

    def test_read_hold_ms_negative(self):
        self.obj.hold_ms_var = FakeVar('-3')
        self.obj.show_field_error = mock.Mock()
        self.assertIsNone(self.obj._read_hold_ms())
        self.obj.show_field_error.assert_called_once()


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='autoclicker_cfg_')
        self.path = os.path.join(self.tmp, 'config.json')
        self.obj = make_clicker()
        self.obj.config_file = self.path

    def test_defaults_when_file_missing(self):
        self.obj.load_config()
        self.assertEqual(self.obj.config['interval_seconds'], 10)
        self.assertEqual(self.obj.config['config_version'], 2)
        self.assertIsInstance(self.obj.config['profiles'], dict)

    def test_partial_config_is_merged_with_defaults(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('{"interval_seconds": 5}')
        self.obj.load_config()
        self.assertEqual(self.obj.config['interval_seconds'], 5)
        self.assertEqual(self.obj.config['click_mode'], 'random')

    def test_v1_config_is_backed_up_before_migration(self):
        content = '{"interval_seconds": 5, "click_mode": "center"}'
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write(content)
        self.obj.load_config()
        backup = getattr(self.obj, '_migration_backup_path', None)
        self.assertTrue(backup and os.path.exists(backup))
        with open(backup, encoding='utf-8') as f:
            self.assertEqual(f.read(), content)
        self.assertEqual(self.obj.config['config_version'], 2)
        self.assertIsInstance(self.obj.config['profiles'], dict)

    def test_invalid_json_falls_back_to_defaults(self):
        with open(self.path, 'w', encoding='utf-8') as f:
            f.write('{invalid')
        self.obj.load_config()
        self.assertEqual(self.obj.config['interval_seconds'], 10)

    def test_save_config_roundtrip(self):
        self.obj.config = {'interval_seconds': 7, 'click_mode': 'center'}
        self.obj.save_config()
        self.obj.load_config()
        self.assertEqual(self.obj.config['interval_seconds'], 7)

    def test_autostart_executable_is_absolute(self):
        self.assertTrue(os.path.isabs(AutoClicker._autostart_executable()))


class ClickLoopTests(unittest.TestCase):
    def _base_obj(self):
        obj = make_clicker()
        obj.is_running = True
        obj.use_multi_points = False
        obj.multi_points = []
        obj.prevent_sleep_var = FakeVar(False)
        obj.mouse_follow_var = FakeVar(False)
        obj.mouse_move_only_var = FakeVar(False)
        obj.interval_var = FakeVar('0')
        obj.interval_unit = 's'
        obj.jitter_pct = 0
        obj.failsafe_enabled = False
        obj.click_limit = 1
        obj.duration_limit = 0
        obj.click_count = 0
        obj.success_count = 0
        obj.fail_count = 0
        obj.click_button = 'left'
        obj.hold_ms = 10
        obj.start_time = time.time()
        obj.click_count_label = FakeLabel()
        obj.get_click_position = lambda: (10, 20)
        obj.log_message = mock.Mock()
        obj._ui = mock.Mock()
        obj._set_sb_counts = mock.Mock()
        obj.stop_clicking = mock.Mock(side_effect=lambda reason='': setattr(obj, 'is_running', False))
        return obj

    def test_single_click_stops_at_limit(self):
        obj = self._base_obj()
        with mock.patch.object(app_module, 'click_mouse', return_value=True):
            obj.click_loop()
        self.assertEqual(obj.click_count, 1)
        self.assertFalse(obj.is_running)
        obj.stop_clicking.assert_called_once()

    def test_failsafe_stops_before_click(self):
        obj = self._base_obj()
        obj.failsafe_enabled = True
        with mock.patch.object(app_module, 'get_cursor_pos', side_effect=[(0, 0), (100, 100)]):
            obj.click_loop()
        self.assertFalse(obj.is_running)
        obj.stop_clicking.assert_called_once()
        self.assertIn('failsafe', obj.stop_clicking.call_args.kwargs['reason'])


class KeepaliveTests(unittest.TestCase):
    def test_keepalive_does_not_busy_loop(self):
        obj = make_clicker()
        obj.keepalive_running = app_module.threading.Event()
        obj.keepalive_stop_event = app_module.threading.Event()
        obj.keepalive_running.set()
        calls = []
        obj.prevent_system_sleep = lambda: calls.append(1)
        thread = app_module.threading.Thread(target=obj._keepalive_loop, daemon=True)
        thread.start()
        time.sleep(0.3)
        self.assertEqual(len(calls), 1, 'keepalive 在等待期间不应重复调用')
        obj.keepalive_stop_event.set()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())


if __name__ == '__main__':
    unittest.main(verbosity=2)
