# -*- coding: utf-8 -*-
"""H3：运行令牌必须让旧点击线程在停止后失效。"""
import threading
import unittest

import auto_clicker_py3 as app_module


class RunTokenTests(unittest.TestCase):
    def _fake_app(self, running=True, run_id=5, local_id=5):
        app = object.__new__(app_module.AutoClicker)
        app.is_running = running
        app._run_id = run_id
        app._click_run_local = threading.local()
        app._click_run_local.run_id = local_id
        return app

    def test_current_run_is_active(self):
        self.assertTrue(self._fake_app()._run_active())

    def test_old_thread_is_inactive_after_new_run(self):
        app = self._fake_app(run_id=6, local_id=5)
        self.assertFalse(app._run_active())

    def test_stopped_run_is_inactive(self):
        app = self._fake_app(running=False)
        self.assertFalse(app._run_active())


if __name__ == '__main__':
    unittest.main(verbosity=2)
