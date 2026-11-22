# -*- coding: utf-8 -*-
"""FR-02 启动确认与结束摘要纯逻辑测试。"""
import csv
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_clicker_layers import run_report


class StartSummaryTests(unittest.TestCase):
    def base_config(self):
        return {
            'interval_seconds': 10,
            'interval_unit': 's',
            'click_mode': 'center',
            'click_area': {'x': 100, 'y': 200, 'width': 1, 'height': 1},
            'click_button': 'left',
            'hold_ms': 10,
            'jitter_pct': 0,
            'click_limit': 1,
            'duration_limit': 0,
            'failsafe_enabled': True,
            'prevent_sleep': True,
            'hotkey_start': 'f6',
            'hotkey_emergency': 'f8',
            'startup_countdown': 3,
        }

    def test_millisecond_interval(self):
        config = self.base_config()
        config['interval_seconds'] = 250
        config['interval_unit'] = 'ms'
        self.assertEqual(run_report.interval_label(config), '250 毫秒')

    def test_target_region_and_window(self):
        config = self.base_config()
        config['click_mode'] = 'random'
        config['click_area'] = {'x': 10, 'y': 20, 'width': 30, 'height': 40}
        config['target_window_keyword'] = 'Excel'
        self.assertEqual(
            run_report.target_label(config),
            '随机位置 30x40 @ (10, 20)；前台窗口含“Excel”')

    def test_target_multi_points(self):
        config = self.base_config()
        config['use_multi_points'] = True
        config['multi_points'] = [{'x': 1, 'y': 2}, {'x': 3, 'y': 4}]
        self.assertEqual(
            run_report.target_label(config), '多点位 2 个（首个 (1, 2)）')

    def test_stop_conditions_combine(self):
        config = self.base_config()
        config['click_limit'] = 5
        config['duration_limit'] = 10
        self.assertEqual(
            run_report.stop_conditions(config),
            '点击 5 次后停止；运行 10 分钟后停止；鼠标位移 >20px 急停')

    def test_stop_manual_fallback(self):
        config = self.base_config()
        config['click_limit'] = 0
        config['failsafe_enabled'] = False
        self.assertEqual(run_report.stop_conditions(config), '手动停止')

    def test_hotkey_esc_not_duplicated(self):
        config = self.base_config()
        config['hotkey_emergency'] = 'esc'
        self.assertEqual(run_report.hotkey_label(config), 'F6 启动/停止；Esc 急停')

    def test_build_start_lines(self):
        lines = run_report.build_start_lines(self.base_config())
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[0], '间隔：10 秒（左键，按住 10ms，抖动 0%）')
        self.assertEqual(lines[1], '目标：点 (100, 200)')
        self.assertEqual(
            lines[2], '停止条件：点击 1 次后停止；鼠标位移 >20px 急停；防锁屏：开')
        self.assertEqual(lines[3], '热键：F6 启动/停止；F8 / Esc 急停；启动倒计时 3 秒')

    def test_should_confirm_toggle_and_schedule(self):
        config = self.base_config()
        self.assertTrue(run_report.should_confirm_start(config))
        config['start_confirm_enabled'] = False
        self.assertFalse(run_report.should_confirm_start(config))
        config['start_confirm_enabled'] = True
        self.assertFalse(run_report.should_confirm_start(config, 'schedule'))


class EndSummaryTests(unittest.TestCase):
    def stats(self):
        return {
            'timestamp': '2026-11-22T19:10:00',
            'click_count': 3,
            'success_count': 2,
            'fail_count': 1,
            'exception_count': 1,
            'runtime_seconds': 65.4,
            'interval_seconds': 10,
            'mode': 'center',
            'button': 'left',
            'stop_reason': '达到点击次数上限 (3 次)',
        }

    def test_runtime_label(self):
        self.assertEqual(run_report.runtime_label(65.4), '01:05（65.4 秒）')
        self.assertEqual(run_report.runtime_label(3661), '01:01:01（3661.0 秒）')

    def test_end_lines(self):
        lines = run_report.build_end_lines(self.stats())
        self.assertEqual(lines[0], '停止原因：达到点击次数上限 (3 次)')
        self.assertEqual(lines[1], '点击：3 次    成功：2 次    失败：1 次    异常：1 次')
        self.assertEqual(lines[2], '运行时长：01:05（65.4 秒）')
        self.assertIn('间隔：10 秒', lines[3])
        self.assertIn('模式：中心点', lines[3])
        self.assertEqual(lines[4], '结束时间：2026-11-22 19:10:00')

    def test_log_summary_matches_stats(self):
        text = run_report.log_summary_line(self.stats())
        self.assertEqual(
            text,
            '运行摘要 | 点击=3 成功=2 失败=1 异常=1 时长=65.4s '
            '原因=达到点击次数上限 (3 次)')

    def test_normalized_stats_clamp_and_default(self):
        data = run_report.normalized_stats({
            'click_count': -2, 'success_count': 'x', 'runtime_seconds': -1,
            'stop_reason': '',
        })
        self.assertEqual(data['click_count'], 0)
        self.assertEqual(data['success_count'], 0)
        self.assertEqual(data['runtime_seconds'], 0.0)
        self.assertEqual(data['stop_reason'], '手动停止')
        self.assertEqual(data['schema'], run_report.SCHEMA)

    def test_write_json(self):
        with tempfile.TemporaryDirectory(prefix='fr02_json_') as tmp:
            path = os.path.join(tmp, 'report.json')
            run_report.write_stats(path, self.stats(), 'json')
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            self.assertEqual(data['schema'], 'autoclicker.run_report/1')
            self.assertEqual(data['click_count'], 3)
            self.assertEqual(data['exception_count'], 1)
            self.assertEqual(data['stop_reason'], '达到点击次数上限 (3 次)')

    def test_write_csv_with_bom_and_readable(self):
        with tempfile.TemporaryDirectory(prefix='fr02_csv_') as tmp:
            path = os.path.join(tmp, 'report.csv')
            run_report.write_stats(path, self.stats(), 'csv')
            with open(path, encoding='utf-8-sig', newline='') as f:
                rows = list(csv.reader(f))
            self.assertEqual(rows[0], ['项目', '数值'])
            self.assertIn(['点击次数', '3'], rows)
            self.assertIn(['异常次数', '1'], rows)
            self.assertIn(['停止原因', '达到点击次数上限 (3 次)'], rows)

    def test_write_rejects_unknown_format(self):
        with self.assertRaises(ValueError):
            run_report.write_stats('report.txt', self.stats(), 'txt')


if __name__ == '__main__':
    unittest.main(verbosity=2)
