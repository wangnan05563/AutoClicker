# -*- coding: utf-8 -*-
"""FR-01 首启模板纯逻辑测试。"""
import unittest

from auto_clicker_layers import onboarding


class TemplateCatalogTests(unittest.TestCase):
    def test_visible_templates_are_four(self):
        self.assertEqual(onboarding.template_ids(),
                         ['keep_online', 'checkin', 'button_repeat', 'custom'])
        for template_id in onboarding.template_ids():
            self.assertIsNotNone(onboarding.get_template(template_id))

    def test_summary_contains_target_and_stop(self):
        cfg = {'click_area': {'x': 10, 'y': 20, 'width': 1, 'height': 1}}
        lines = onboarding.summary_lines('checkin', cfg)
        self.assertIn('目标：点 (10, 20)', '\n'.join(lines))
        self.assertIn('停止：点击 1 次', '\n'.join(lines))

    def test_normalize_hotkeys_rejects_conflict(self):
        self.assertEqual(onboarding.normalize_hotkeys('F6', 'F8'), ('f6', 'f8'))
        with self.assertRaises(ValueError):
            onboarding.normalize_hotkeys('f6', 'f6')
        with self.assertRaises(ValueError):
            onboarding.normalize_hotkeys('ctrl+a', 'f8')

    def test_real_click_templates_require_explicit_target(self):
        for template_id in ('checkin', 'button_repeat'):
            self.assertTrue(onboarding.template_requires_explicit_target(template_id))
        for template_id in ('keep_online', 'custom', 'safe'):
            self.assertFalse(onboarding.template_requires_explicit_target(template_id))


class ApplyTemplateTests(unittest.TestCase):
    def test_keep_online_only_moves_and_prevents_sleep(self):
        cfg = {'interval_seconds': 99, 'custom_key': 'keep-me',
               'click_area': {'x': 100, 'y': 200, 'width': 300, 'height': 400}}
        out = onboarding.apply_template(cfg, 'keep_online')
        self.assertEqual(out['interval_seconds'], 60)
        self.assertTrue(out['mouse_move_only'])
        self.assertTrue(out['mouse_follow_enabled'])
        self.assertTrue(out['prevent_sleep'])
        self.assertEqual(out['click_mode'], 'center')
        self.assertEqual(out['ui_mode'], 'simple')
        self.assertTrue(out['onboarding_done'])
        self.assertEqual(out['onboarding_template'], 'keep_online')
        self.assertEqual(out['custom_key'], 'keep-me')
        self.assertEqual(cfg['interval_seconds'], 99)  # 不修改入参

    def test_checkin_clicks_once_at_point(self):
        out = onboarding.apply_template(
            {}, 'checkin', click_area={'x': 7, 'y': 8, 'width': 1, 'height': 1},
            hotkey_start='F9', hotkey_emergency='ESC')
        self.assertEqual(out['click_limit'], 1)
        self.assertFalse(out['mouse_move_only'])
        self.assertEqual(out['click_area'], {'x': 7, 'y': 8, 'width': 1, 'height': 1})
        self.assertEqual(out['hotkey_start'], 'f9')
        self.assertEqual(out['hotkey_emergency'], 'esc')
        self.assertFalse(out['schedule']['enabled'])

    def test_button_repeat_is_one_second_unlimited(self):
        out = onboarding.apply_template(
            {'click_area': {'x': 0, 'y': 0, 'width': 1920, 'height': 1080}},
            'button_repeat')
        self.assertEqual(out['interval_seconds'], 1)
        self.assertEqual(out['click_limit'], 0)
        self.assertFalse(out['prevent_sleep'])
        self.assertEqual(out['click_area'],
                         {'x': 960, 'y': 540, 'width': 1, 'height': 1})

    def test_custom_keeps_existing_target(self):
        area = {'x': 5, 'y': 6, 'width': 20, 'height': 30}
        cfg = {
            'click_area': area, 'click_mode': 'center', 'interval_seconds': 7,
            'hold_ms': 250, 'autostart': True, 'close_to_tray': False,
            'use_multi_points': True,
            'multi_points': [{'x': 1, 'y': 2}],
            'schedule': {'enabled': True, 'start_at': '10:00'},
        }
        out = onboarding.apply_template(cfg, 'custom')
        self.assertEqual(out['click_area'], area)
        self.assertEqual(out['click_mode'], 'center')
        self.assertEqual(out['interval_seconds'], 7)
        self.assertEqual(out['hold_ms'], 250)
        self.assertTrue(out['autostart'])
        self.assertFalse(out['close_to_tray'])
        self.assertTrue(out['use_multi_points'])
        self.assertEqual(out['multi_points'], [{'x': 1, 'y': 2}])
        self.assertTrue(out['schedule']['enabled'])
        self.assertEqual(out['onboarding_template'], 'custom')
        self.assertEqual(out['ui_mode'], 'simple')

    def test_start_hotkey_cannot_be_esc(self):
        with self.assertRaises(ValueError):
            onboarding.normalize_hotkeys('esc', 'f8')

    def test_safe_config_marks_done_and_centers_point(self):
        out = onboarding.safe_config(
            {'click_area': {'x': 0, 'y': 0, 'width': 100, 'height': 80}})
        self.assertTrue(out['onboarding_done'])
        self.assertEqual(out['onboarding_template'], 'safe')
        self.assertEqual(out['startup_countdown'], 3)
        self.assertTrue(out['mouse_move_only'])
        self.assertEqual(out['click_area'],
                         {'x': 50, 'y': 40, 'width': 1, 'height': 1})
        self.assertTrue(onboarding.SAFE_TEMPLATE['patch']['mouse_move_only'])
        summary = '\n'.join(onboarding.summary_lines('safe', out))
        self.assertIn('只移动不点击', summary)

    def test_unknown_template_raises(self):
        with self.assertRaises(ValueError):
            onboarding.apply_template({}, 'nope')


if __name__ == '__main__':
    unittest.main()
