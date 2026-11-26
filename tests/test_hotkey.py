# -*- coding: utf-8 -*-
"""T06151 热键解析与探测单测。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_clicker_layers import hotkey


class HotkeyTests(unittest.TestCase):
    def test_parse_common(self):
        self.assertEqual(hotkey.parse_hotkey('Ctrl+Alt+K')[:2],
                         (hotkey.MOD_CTRL | hotkey.MOD_ALT, ord('K')))
        self.assertEqual(hotkey.parse_hotkey('f6')[:2], (0, 0x75))
        self.assertEqual(hotkey.parse_hotkey('shift+f12')[:2],
                         (hotkey.MOD_SHIFT, 0x70 + 11))

    def test_parse_invalid(self):
        for value in ('', 'ctrl+', 'ctrl+alt+a+b', 'ctrl+unknown'):
            _, _, _, error = hotkey.parse_hotkey(value)
            self.assertTrue(error, value)

    def test_shifted_symbols_add_shift(self):
        mods, vk, normalized, error = hotkey.parse_hotkey('Ctrl++')
        self.assertEqual(error, '')
        self.assertEqual(mods, hotkey.MOD_CTRL | hotkey.MOD_SHIFT)
        self.assertEqual(vk, 0xBB)
        self.assertEqual(normalized, 'ctrl+plus')
        mods, vk, _, error = hotkey.parse_hotkey('Ctrl+colon')
        self.assertEqual(error, '')
        self.assertEqual(mods, hotkey.MOD_CTRL | hotkey.MOD_SHIFT)
        self.assertEqual(vk, 0xBA)

    def test_probe_returns_tuple_and_does_not_claim(self):
        occupied, reason = hotkey.probe_windows_hotkey('ctrl+alt+k')
        self.assertIsInstance(occupied, bool)
        self.assertIsInstance(reason, str)
        # 探测失败不应阻断应用；仅冲突时 occupied=True
        if occupied:
            self.assertIn('占用', reason)

    def test_probe_invalid_hotkey(self):
        occupied, reason = hotkey.probe_windows_hotkey('ctrl+')
        self.assertFalse(occupied)
        self.assertTrue(reason)


if __name__ == '__main__':
    unittest.main()
