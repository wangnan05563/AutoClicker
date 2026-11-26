# -*- coding: utf-8 -*-
"""M4：宏热键必须按注册结果判定，失败时回滚配置与绑定。"""
import os
import unittest

import auto_clicker_py3 as app_module


class _Var:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


class MacroHotkeyRollbackTests(unittest.TestCase):
    def _app(self, state):
        app = object.__new__(app_module.AutoClicker)
        app.config = {
            'hotkey_start': 'f6', 'hotkey_emergency': 'f8',
            'macro_hotkeys': {'D:/old.ahk': 'ctrl+1'},
        }
        app._macro_hotkey_bindings = {'D:/old.ahk': 'ctrl+1'}
        app._macro_hotkey_bindings_paths = {}
        app.macro_hotkey_var = _Var('Ctrl+2')
        app._hotkey_state = state
        app._saved = 0
        app._status = []
        app._logs = []

        def save_config():
            app._saved += 1

        def register():
            app._hotkey_state = state

        app.save_config = save_config
        app._register_hotkeys = register
        app._macro_set_status = lambda text, kind: app._status.append((text, kind))
        app.log_message = lambda text: app._logs.append(text)
        app._current_macro_entry = lambda: {'path': 'D:/new.ahk', 'name': 'new'}
        return app

    def test_registration_error_rolls_back_binding(self):
        app = self._app({
            'registered': False, 'error': 'keyboard 不可用',
            'macro_errors': [], 'macro_keys': [],
        })
        app.apply_macro_hotkey()
        self.assertEqual(app._macro_hotkey_bindings, {'D:/old.ahk': 'ctrl+1'})
        self.assertEqual(app.config['macro_hotkeys'], {'D:/old.ahk': 'ctrl+1'})
        self.assertEqual(app._saved, 2)
        self.assertTrue(app._status[-1][0].startswith('绑定失败'))

    def test_missing_key_in_macro_keys_rolls_back(self):
        app = self._app({
            'registered': True, 'error': '',
            'macro_errors': [], 'macro_keys': [],
        })
        app.apply_macro_hotkey()
        self.assertEqual(app._macro_hotkey_bindings, {'D:/old.ahk': 'ctrl+1'})
        self.assertEqual(app._saved, 2)

    def test_success_keeps_binding_and_config(self):
        app = self._app({
            'registered': True, 'error': '',
            'macro_errors': [], 'macro_keys': ['ctrl+2'],
        })
        app.apply_macro_hotkey()
        self.assertEqual(app._macro_hotkey_bindings, {
            'D:/old.ahk': 'ctrl+1', os.path.abspath('D:/new.ahk'): 'ctrl+2'})
        self.assertEqual(app.config['macro_hotkeys'], app._macro_hotkey_bindings)
        self.assertEqual(app._saved, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
