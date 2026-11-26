# -*- coding: utf-8 -*-
"""T06155 运行历史：上限 30、趋势、CSV、损坏文件容错。"""
import csv
import os
import tempfile
import unittest
from datetime import datetime

from auto_clicker_layers import history


def run(clicks=10, success=9, fail=1, runtime=3.0, ts='2026-11-23T12:00:00'):
    return {
        'timestamp': ts, 'click_count': clicks, 'success_count': success,
        'fail_count': fail, 'exception_count': 0, 'runtime_seconds': runtime,
        'interval_seconds': 1.0, 'mode': 'single', 'button': 'left',
        'stop_reason': '手动停止',
    }


class HistoryTests(unittest.TestCase):
    def test_append_caps_at_thirty_and_keeps_newest(self):
        hist = history.empty_history()
        for i in range(35):
            hist = history.append_run(hist, run(ts='2026-11-23T12:%02d:00' % i))
        self.assertEqual(len(hist['runs']), 30)
        self.assertTrue(hist['runs'][-1]['timestamp'].endswith('34:00'))
        self.assertFalse(hist['runs'][0]['timestamp'].endswith('00:00'))

    def test_summary_rate_and_average(self):
        hist = history.empty_history()
        hist = history.append_run(hist, run(clicks=100, success=98, fail=2, runtime=10))
        hist = history.append_run(hist, run(clicks=100, success=100, fail=0, runtime=20))
        summary = history.summarize(hist)
        self.assertEqual(summary['count'], 2)
        self.assertAlmostEqual(summary['success_rate'], 99.0)
        self.assertAlmostEqual(summary['avg_runtime_seconds'], 15.0)
        self.assertEqual(summary['failed_runs'], 1)

    def test_trend_and_csv(self):
        hist = history.empty_history()
        for record in (run(clicks=10, success=8, fail=2, runtime=2),
                       run(clicks=20, success=20, fail=0, runtime=6)):
            hist = history.append_run(hist, record)
        points = history.trend_points(hist)
        self.assertEqual(points[0]['rate'], 80.0)
        self.assertEqual(points[1]['rate'], 100.0)
        self.assertTrue(points[0]['abnormal'])
        path = os.path.join(tempfile.mkdtemp(prefix='ac-history-'), 'history.csv')
        history.write_csv(path, hist)
        with open(path, 'r', encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.reader(handle))
        self.assertIn('success_rate_pct', rows[0])
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][6], '80.0')

    def test_normalize_clamps_success_and_fail_to_total(self):
        clean = history.normalize_run(
            run(clicks=10, success=12, fail=8, ts='2026-11-23T12:00:00'))
        self.assertEqual(clean['success_count'], 10)
        self.assertEqual(clean['fail_count'], 0)

    def test_csv_escapes_formula_injection(self):
        hist = history.append_run(
            history.empty_history(),
            run(ts='2026-11-23T12:00:00', success=9, fail=1))
        hist['runs'][0]['stop_reason'] = '=HYPERLINK("http://x")'
        path = os.path.join(tempfile.mkdtemp(prefix='ac-history-'), 'history.csv')
        history.write_csv(path, hist)
        with open(path, 'r', encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.reader(handle))
        self.assertTrue(rows[1][-1].startswith("'="), rows[1][-1])

    def test_corrupt_file_returns_empty_and_save_roundtrip(self):
        tmp = tempfile.mkdtemp(prefix='ac-history-')
        bad = os.path.join(tmp, 'bad.json')
        with open(bad, 'w', encoding='utf-8') as handle:
            handle.write('{not json')
        self.assertEqual(history.load(bad)['runs'], [])
        path = os.path.join(tmp, 'ok.json')
        hist = history.append_run(history.empty_history(), run())
        saved = history.save(path, hist)
        loaded = history.load(path)
        self.assertEqual(loaded, saved)
        self.assertTrue(os.path.exists(path))

    def test_summary_text_empty(self):
        self.assertIn('暂无', history.summary_text(history.empty_history()))


if __name__ == '__main__':
    unittest.main()
