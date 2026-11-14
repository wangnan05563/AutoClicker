# -*- coding: utf-8 -*-
"""端到端/GUI 冒烟：在隔离子进程中真实创建主窗口并退出。"""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY = os.path.join(ROOT, 'tests', 'gui_smoke_entry.py')


class GuiSmokeTests(unittest.TestCase):
    def test_main_window_builds_and_closes(self):
        proc = subprocess.run(
            [sys.executable, '-X', 'utf8', ENTRY],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('GUI_SMOKE_OK', proc.stdout)
        # 修复保活忙循环后，启动输出不应出现大量重复保活日志
        self.assertLess(proc.stdout.count('已设置Windows防休眠'), 10)


if __name__ == '__main__':
    unittest.main(verbosity=2)
