# -*- coding: utf-8 -*-
"""H4：Windows 按住可取消、异常/取消必发 UP、双击失败不得误报成功。"""
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from auto_clicker_layers import platform_io


@unittest.skipUnless(platform_io.IS_WINDOWS,
                     '仅 Windows 原生输入后端可测')
class WindowsClickCancelTests(unittest.TestCase):
    def tearDown(self):
        with platform_io._MOUSE_DOWN_LOCK:
            platform_io._MOUSE_DOWN_BUTTONS.clear()

    def _fake_user32(self):
        events = []
        fake = SimpleNamespace(
            SetCursorPos=lambda x, y: True,
            mouse_event=lambda flag, dx, dy, data, extra: events.append(flag),
        )
        return fake, events

    def _call_with_fake(self, fake, fn):
        with mock.patch.object(platform_io.ctypes, 'windll',
                               SimpleNamespace(user32=fake)):
            return fn()

    def test_pre_cancelled_click_does_not_press(self):
        fake, events = self._fake_user32()
        cancel = threading.Event()
        cancel.set()
        ok = self._call_with_fake(
            fake, lambda: platform_io._windows_click_button(1, 2, 'left', 500, cancel))
        self.assertFalse(ok)
        self.assertEqual(events, [])

    def test_cancel_during_hold_sends_up_quickly(self):
        fake, events = self._fake_user32()
        cancel = threading.Event()
        threading.Timer(0.05, cancel.set).start()
        start = time.monotonic()
        ok = self._call_with_fake(
            fake, lambda: platform_io._windows_click_button(1, 2, 'left', 1000, cancel))
        elapsed = time.monotonic() - start
        self.assertFalse(ok)
        self.assertEqual(events, [platform_io.MOUSEEVENTF_LEFTDOWN,
                                  platform_io.MOUSEEVENTF_LEFTUP])
        self.assertLess(elapsed, 0.5)

    def test_double_click_reports_failure(self):
        def deny(*args):
            raise OSError('denied')

        fake = SimpleNamespace(SetCursorPos=lambda x, y: True, mouse_event=deny)
        ok = self._call_with_fake(
            fake, lambda: platform_io.windows_click(1, 2, 'double', 0, 30))
        self.assertFalse(ok)

    def test_release_mouse_buttons_sends_three_ups(self):
        fake, events = self._fake_user32()
        self._call_with_fake(
            fake, lambda: platform_io.release_mouse_buttons(force_all=True))
        self.assertEqual(events, [platform_io.MOUSEEVENTF_LEFTUP,
                                  platform_io.MOUSEEVENTF_RIGHTUP,
                                  platform_io.MOUSEEVENTF_MIDDLEUP])

    def test_release_mouse_buttons_does_not_require_pywin32(self):
        fake, events = self._fake_user32()
        with mock.patch.object(platform_io, 'HAS_WIN32API', False):
            self._call_with_fake(
                fake, lambda: platform_io.release_mouse_buttons(force_all=True))
        self.assertEqual(len(events), 3)

    def test_release_mouse_buttons_only_releases_owned_buttons(self):
        fake, events = self._fake_user32()
        platform_io._mark_mouse_down('left')
        self._call_with_fake(fake, platform_io.release_mouse_buttons)
        self.assertEqual(events, [platform_io.MOUSEEVENTF_LEFTUP])
        with platform_io._MOUSE_DOWN_LOCK:
            self.assertEqual(platform_io._MOUSE_DOWN_BUTTONS, set())

    def test_release_mouse_buttons_keeps_user_physical_button(self):
        fake, events = self._fake_user32()
        self._call_with_fake(fake, platform_io.release_mouse_buttons)
        self.assertEqual(events, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
