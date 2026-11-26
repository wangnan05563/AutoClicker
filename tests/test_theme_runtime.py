# -*- coding: utf-8 -*-
"""H2 / AC-10：ttk 基底主题必须固定 clam，且 ttkbootstrap 不得参与运行时。"""
import sys
import tkinter as tk
from tkinter import ttk
import types
import unittest
from unittest import mock

import auto_clicker_py3 as app_module


class ThemePinRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as exc:
            raise unittest.SkipTest('无可用 Tk 显示：%s' % exc)
        cls.app = object.__new__(app_module.AutoClicker)
        cls.app.root = cls.root
        cls.app.config = {'theme_pack': 'light'}
        cls.app._ttk_base_theme = None
        cls.app._ttkb_style = 'sentinel'

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def test_init_theme_pins_clam_without_ttkbootstrap(self):
        class ForbiddenStyle:
            def __init__(self, *args, **kwargs):
                raise AssertionError('ttkbootstrap.Style 不应被构造')

        fake = types.ModuleType('ttkbootstrap')
        fake.Style = ForbiddenStyle
        with mock.patch.dict(sys.modules, {'ttkbootstrap': fake}):
            self.app._init_theme()
        self.assertIsNone(self.app._ttkb_style)
        self.assertEqual(ttk.Style(self.root).theme_use(), 'clam')

    def test_pin_repairs_externally_changed_theme(self):
        style = ttk.Style(self.root)
        style.theme_use('alt')
        self.app._pin_ttk_base_theme()
        self.assertEqual(style.theme_use(), 'clam')


if __name__ == '__main__':
    unittest.main(verbosity=2)
