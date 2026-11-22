# -*- coding: utf-8 -*-
"""FR-26 运行台今日统计纯逻辑测试。"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_clicker_layers import dashboard


DAY1 = '2026-11-23'
DAY2 = '2026-11-24'


class NormalizeTests(unittest.TestCase):
    def test_empty_stats_has_today_and_zero_counts(self):
        stats = dashboard.empty_daily_stats(now=DAY1)
        self.assertEqual(stats['schema'], dashboard.SCHEMA)
        self.assertEqual(stats['date'], DAY1)
        self.assertEqual(stats['click_count'], 0)
        self.assertEqual(stats['run_count'], 0)

    def test_date_rollover_resets_yesterday(self):
        stats = dashboard.normalize({
            'date': DAY1, 'click_count': 30, 'success_count': 20,
            'fail_count': 10, 'run_count': 2,
        }, now=DAY2)
        self.assertEqual(stats['date'], DAY2)
        self.assertEqual(stats['click_count'], 0)
        self.assertEqual(stats['run_count'], 0)

    def test_invalid_values_are_clamped(self):
        stats = dashboard.normalize({
            'date': DAY1, 'click_count': '9', 'success_count': -3,
            'fail_count': 20, 'run_count': 'x', 'runtime_seconds': '-2',
        }, now=DAY1)
        self.assertEqual(stats['click_count'], 9)
        self.assertEqual(stats['success_count'], 0)
        self.assertEqual(stats['fail_count'], 9)
        self.assertEqual(stats['run_count'], 0)
        self.assertEqual(stats['runtime_seconds'], 0.0)


class RecordTests(unittest.TestCase):
    def test_record_run_accumulates_counts_and_runtime(self):
        base = dashboard.empty_daily_stats(now=DAY1)
        run = {
            'click_count': 5, 'success_count': 4, 'fail_count': 1,
            'exception_count': 1, 'runtime_seconds': 12.5,
        }
        stats = dashboard.record_run(base, run, now=DAY1)
        self.assertEqual(stats['click_count'], 5)
        self.assertEqual(stats['success_count'], 4)
        self.assertEqual(stats['fail_count'], 1)
        self.assertEqual(stats['exception_count'], 1)
        self.assertEqual(stats['run_count'], 1)
        self.assertAlmostEqual(stats['runtime_seconds'], 12.5)

    def test_record_run_ignores_negative_and_non_dict(self):
        base = dashboard.empty_daily_stats(now=DAY1)
        stats = dashboard.record_run(base, {'click_count': -1, 'runtime_seconds': -5}, now=DAY1)
        self.assertEqual(stats['click_count'], 0)
        self.assertEqual(stats['runtime_seconds'], 0.0)
        self.assertEqual(stats['run_count'], 1)
        self.assertEqual(dashboard.record_run(stats, None, now=DAY1), stats)

    def test_merge_session_is_display_only(self):
        base = dashboard.empty_daily_stats(now=DAY1)
        base['click_count'] = 10
        base['success_count'] = 8
        view = dashboard.merge_session(
            base, click_count=3, success_count=3, running=True, now=DAY1)
        self.assertEqual(view['click_count'], 13)
        self.assertEqual(view['success_count'], 11)
        self.assertEqual(view['run_count'], 1)
        self.assertEqual(base['click_count'], 10)
        stopped = dashboard.merge_session(
            base, click_count=3, success_count=3, running=False, now=DAY1)
        self.assertEqual(stopped['click_count'], 10)


class TextTests(unittest.TestCase):
    def test_success_rate_text(self):
        self.assertEqual(dashboard.success_rate_text({'click_count': 0}), '--')
        self.assertEqual(dashboard.success_rate_text(
            {'click_count': 3, 'success_count': 3}), '100.0%')
        self.assertEqual(dashboard.success_rate_text(
            {'click_count': 7, 'success_count': 2}), '28.6%')

    def test_last_run_text_empty_and_filled(self):
        self.assertEqual(dashboard.last_run_text({}), '上次运行：暂无')
        text = dashboard.last_run_text({
            'timestamp': '2026-11-23T10:00:00', 'click_count': 8,
            'success_count': 7, 'runtime_seconds': 65.4,
        })
        self.assertIn('点击 8 次', text)
        self.assertIn('87.5%', text)
        self.assertIn('01:05', text)


class FileTests(unittest.TestCase):
    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, dashboard.DAILY_FILE_NAME)
            base = dashboard.empty_daily_stats(now=DAY1)
            base['click_count'] = 12
            base['success_count'] = 9
            base['run_count'] = 2
            dashboard.save(path, base, now=DAY1)
            loaded = dashboard.load(path, now=DAY1)
            self.assertEqual(loaded['click_count'], 12)
            self.assertEqual(loaded['success_count'], 9)
            self.assertEqual(loaded['run_count'], 2)

    def test_invalid_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, dashboard.DAILY_FILE_NAME)
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write('{bad')
            stats = dashboard.load(path, now=DAY1)
            self.assertEqual(stats['date'], DAY1)
            self.assertEqual(stats['click_count'], 0)

    def test_saved_file_has_no_target_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, dashboard.DAILY_FILE_NAME)
            stats = dashboard.empty_daily_stats(now=DAY1)
            dashboard.save(path, stats, now=DAY1)
            with open(path, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
            self.assertEqual(set(data), {
                'schema', 'date', 'click_count', 'success_count', 'fail_count',
                'exception_count', 'run_count', 'runtime_seconds',
            })


if __name__ == '__main__':
    unittest.main(verbosity=2)
