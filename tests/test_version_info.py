# -*- coding: utf-8 -*-
"""FR-04：产品版本与构建号双轨。"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from auto_clicker_layers import version  # noqa: E402


class VersionInfoTests(unittest.TestCase):
    def test_version_and_build_are_separate(self):
        self.assertRegex(version.APP_VERSION, r'^\d+\.\d+\.\d+$')
        self.assertTrue(version.BUILD_ID)
        self.assertNotEqual(version.APP_VERSION, version.BUILD_ID)

    def test_window_title_comes_from_version_module(self):
        import auto_clicker_py3 as app
        self.assertEqual(
            app.WINDOW_TITLE,
            "桌面自动点击工具 v%s (Build %s)" % (version.APP_VERSION, version.BUILD_ID))
        self.assertIn(version.APP_VERSION, app.get_version_text())
        self.assertIn(version.BUILD_ID, app.get_version_text())

    def test_version_override_for_tests(self):
        old = os.environ.get('AUTOCLICKER_WINDOW_TITLE')
        os.environ['AUTOCLICKER_WINDOW_TITLE'] = 'Custom Title'
        try:
            import importlib
            import auto_clicker_py3 as app
            importlib.reload(app)
            self.assertEqual(app.WINDOW_TITLE, 'Custom Title')
        finally:
            if old is None:
                os.environ.pop('AUTOCLICKER_WINDOW_TITLE', None)
            else:
                os.environ['AUTOCLICKER_WINDOW_TITLE'] = old
            import importlib
            import auto_clicker_py3 as app
            importlib.reload(app)


if __name__ == '__main__':
    unittest.main()
