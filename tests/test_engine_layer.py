# -*- coding: utf-8 -*-
"""引擎层纯逻辑单测（NFR-09：不依赖 tkinter）。"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_clicker_layers import engine


class FakeRng:
    def __init__(self, value):
        self.value = value

    def uniform(self, a, b):
        return self.value


class EngineTests(unittest.TestCase):
    def test_normalize_region(self):
        self.assertEqual(engine.normalize_region(10, 20, 5, 8), (5, 8, 10, 20))
        self.assertEqual(engine.normalize_region(1, 2, 3, 4), (1, 2, 3, 4))

    def test_target_window_match(self):
        self.assertTrue(engine.target_window_matches('', '任意', '任意'))
        self.assertTrue(engine.target_window_matches(' Excel ', '报价 Excel', 'EXCEL.EXE'))
        self.assertTrue(engine.target_window_matches('excel', '无关', 'excel.exe'))
        self.assertFalse(engine.target_window_matches('excel', '记事本', 'notepad.exe'))

    def test_interval_conversion(self):
        self.assertEqual(engine.effective_interval_seconds(10, 's'), 10.0)
        self.assertEqual(engine.effective_interval_seconds(250, 'ms'), 0.25)
        self.assertEqual(engine.effective_interval_seconds('abc', 's'), 1.0)
        self.assertEqual(engine.effective_interval_seconds(-5, 's'), 0.0)

    def test_jittered_wait(self):
        self.assertEqual(engine.jittered_wait(0, 20, FakeRng(0)), 0.0)
        self.assertEqual(engine.jittered_wait(1, 0, FakeRng(0)), 1.0)
        self.assertAlmostEqual(engine.jittered_wait(1, 20, FakeRng(0.1)), 1.1)
        self.assertAlmostEqual(engine.jittered_wait(1, 20, FakeRng(-0.1)), 0.9)
        self.assertEqual(engine.jittered_wait(1, 20, None), 1.0)

    def test_validate_interval(self):
        self.assertEqual(engine.validate_interval('10'), (10, None))
        self.assertEqual(engine.validate_interval('0'), (None, '点击间隔必须 >= 1'))
        self.assertEqual(engine.validate_interval('3601'), (None, '点击间隔必须 <= 3600'))
        self.assertEqual(engine.validate_interval('x'), (None, '点击间隔必须为整数'))

    def test_validate_countdown(self):
        self.assertEqual(engine.validate_countdown('0'), (0, None))
        self.assertEqual(engine.validate_countdown('5'), (5, None))
        self.assertEqual(engine.validate_countdown('6'), (None, '启动倒计时必须在 0-5 秒之间'))
        self.assertEqual(engine.validate_countdown('x'), (None, '启动倒计时必须为整数'))

    def test_validate_limits(self):
        self.assertEqual(engine.validate_click_limit('0'), (0, None))
        self.assertEqual(engine.validate_click_limit('-1'), (None, '点击次数上限不能为负数'))
        self.assertEqual(engine.validate_click_limit('x'), (None, '点击次数上限必须为整数'))
        self.assertEqual(engine.validate_duration_limit('30'), (30, None))
        self.assertEqual(engine.validate_duration_limit('-1'), (None, '运行时长上限不能为负数'))
        self.assertEqual(engine.validate_duration_limit('x'), (None, '运行时长上限必须为整数'))

    def test_validate_jitter_and_hold(self):
        self.assertEqual(engine.validate_jitter('0'), (0, None))
        self.assertEqual(engine.validate_jitter('101'), (None, '随机抖动必须在 0-100 之间'))
        self.assertEqual(engine.validate_jitter('x'), (None, '随机抖动必须为整数'))
        self.assertEqual(engine.validate_hold_ms('10'), (10, None))
        self.assertEqual(engine.validate_hold_ms('-1'), (None, '按住时长不能为负数'))
        self.assertEqual(engine.validate_hold_ms('x'), (None, '按住时长必须为整数'))

    def test_parse_schedule_start(self):
        self.assertEqual(engine.parse_schedule_start('09:05'), (9, 5))
        self.assertEqual(engine.parse_schedule_start(' 9：05 '), (9, 5))
        with self.assertRaises(ValueError):
            engine.parse_schedule_start('9')
        with self.assertRaises(ValueError):
            engine.parse_schedule_start('aa:bb')
        with self.assertRaises(ValueError):
            engine.parse_schedule_start('24:00')

    def test_weekday_labels(self):
        self.assertEqual(engine.weekdays_to_label([1, 2, 3, 4, 5, 6, 7]), '每天')
        self.assertEqual(engine.weekdays_to_label([1, 2, 3, 4, 5]), '工作日')
        self.assertEqual(engine.weekdays_to_label([6, 7]), '周末')
        self.assertEqual(engine.weekdays_to_label('bad'), '工作日')
        self.assertEqual(engine.weekdays_to_label([8]), '工作日')
        self.assertEqual(engine.label_to_weekdays('每天'), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(engine.label_to_weekdays('周末'), [6, 7])
        self.assertEqual(engine.label_to_weekdays('未知'), [1, 2, 3, 4, 5])

    def test_schedule_occurrence(self):
        now = datetime(2026, 11, 16, 9, 0)  # Monday
        self.assertEqual(engine.schedule_occurrence(now, (9, 0), [1, 2, 3, 4, 5]),
                         datetime(2026, 11, 16, 9, 0))
        self.assertEqual(engine.schedule_occurrence(datetime(2026, 11, 17, 0, 10), (23, 0), [1]),
                         datetime(2026, 11, 16, 23, 0))
        self.assertIsNone(engine.schedule_occurrence(datetime(2026, 11, 17, 9, 0), (9, 0), [6, 7]))
        self.assertIsNone(engine.schedule_occurrence(now, (10, 0), [1, 2, 3, 4, 5]))

    def test_schedule_grace_and_next(self):
        occ = datetime(2026, 11, 16, 9, 0)
        self.assertEqual(engine.schedule_grace_end(occ, 0), datetime(2026, 11, 16, 9, 5))
        self.assertEqual(engine.schedule_grace_end(occ, 30), datetime(2026, 11, 16, 9, 30))
        self.assertEqual(engine.schedule_next_text(occ, (10, 0), [1]), '11-16 10:00')
        self.assertEqual(engine.schedule_next_text(datetime(2026, 11, 21, 10, 0), (9, 0), [1, 2, 3, 4, 5]),
                         '11-23 09:00')
        self.assertEqual(engine.schedule_next_text(datetime(2026, 11, 16, 9, 0), (9, 0), []), '--')


if __name__ == '__main__':
    unittest.main(verbosity=2)
