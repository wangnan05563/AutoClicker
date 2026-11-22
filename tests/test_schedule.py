# -*- coding: utf-8 -*-
"""FR-D01 定时计划：纯逻辑单测（不启动 Tk / 不产生真实点击）。"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auto_clicker_py3 as m


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.app = object.__new__(m.AutoClicker)
        self.app.config = {'schedule': {'enabled': True, 'start_at': '09:00',
                                        'stop_after_min': 30, 'weekdays': [1, 2, 3, 4, 5]}}
        self.app.is_running = False
        self.app._schedule_last_occurrence = None
        self.app._schedule_active_occurrence = None
        self.app.logs = []
        self.app.log_message = lambda text: self.app.logs.append(str(text))
        self.app.start_clicking = lambda source='manual': setattr(self.app, 'is_running', True)
        self.app.stop_clicking = lambda reason='': setattr(self.app, 'is_running', False)

    def test_workday_start_and_stop(self):
        self.assertEqual(self.app._schedule_check(datetime(2026, 11, 16, 9, 0), False), 'started')
        self.assertTrue(self.app.is_running)
        self.assertEqual(self.app._schedule_check(datetime(2026, 11, 16, 9, 1), True), 'noop')
        self.assertEqual(self.app._schedule_check(datetime(2026, 11, 16, 9, 30), True), 'stopped')
        self.assertFalse(self.app.is_running)
        self.assertEqual(self.app._schedule_check(datetime(2026, 11, 16, 9, 31), False), 'noop')

    def test_weekend_skip(self):
        self.assertEqual(self.app._schedule_check(datetime(2026, 11, 21, 9, 0), False), 'noop')
        self.assertFalse(self.app.is_running)

    def test_cross_midnight(self):
        self.app.config['schedule'] = {'enabled': True, 'start_at': '23:00',
                                       'stop_after_min': 120, 'weekdays': [1]}
        self.assertEqual(self.app._schedule_check(datetime(2026, 11, 17, 0, 10), False), 'started')
        self.assertEqual(self.app._schedule_check(datetime(2026, 11, 17, 1, 0), True), 'stopped')

    def test_sleep_catchup_and_grace(self):
        self.app.config['schedule'] = {'enabled': True, 'start_at': '09:00',
                                       'stop_after_min': 0, 'weekdays': [1, 2, 3, 4, 5]}
        self.assertEqual(self.app._schedule_check(datetime(2026, 11, 16, 9, 3), False), 'started')
        self.app._schedule_last_occurrence = None
        self.app._schedule_active_occurrence = None
        self.app.is_running = False
        self.assertEqual(self.app._schedule_check(datetime(2026, 11, 16, 9, 10), False), 'noop')

    def test_weekday_labels(self):
        self.assertEqual(m.AutoClicker._label_to_weekdays('每天'), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(m.AutoClicker._label_to_weekdays('工作日'), [1, 2, 3, 4, 5])
        self.assertEqual(m.AutoClicker._label_to_weekdays('周末'), [6, 7])
        self.assertEqual(m.AutoClicker._weekdays_to_label([1, 2, 3, 4, 5]), '工作日')


if __name__ == '__main__':
    unittest.main(verbosity=2)
