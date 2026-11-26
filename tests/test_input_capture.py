# -*- coding: utf-8 -*-
"""FR-13：输入采集层的鼠标轮询与键盘去重逻辑测试。"""
import threading
import time
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from auto_clicker_layers import platform_io
from auto_clicker_layers.input_capture import InputCapture


class KeyboardHookTests(unittest.TestCase):
    def test_key_down_up_and_repeat_is_ignored(self):
        events = []
        capture = InputCapture(events.append)
        capture._on_key(SimpleNamespace(name='a', event_type='down'))
        capture._on_key(SimpleNamespace(name='a', event_type='down'))
        capture._on_key(SimpleNamespace(name='a', event_type='up'))
        capture._on_key(SimpleNamespace(name='a', event_type='down'))
        self.assertEqual([(e['key'], e['action']) for e in events], [
            ('a', 'down'), ('a', 'up'), ('a', 'down'),
        ])

    def test_esc_f8_and_unknown_events_are_ignored(self):
        events = []
        capture = InputCapture(events.append, excluded_keys=['f6'])
        capture._on_key(SimpleNamespace(name='esc', event_type='down'))
        capture._on_key(SimpleNamespace(name='f8', event_type='down'))
        capture._on_key(SimpleNamespace(name='f6', event_type='down'))
        capture._on_key(SimpleNamespace(name='', event_type='down'))
        capture._on_key(SimpleNamespace(name='b', event_type='repeat'))
        self.assertEqual(events, [])


class MousePollTests(unittest.TestCase):
    def _run_poll(self, capture, timeout=1.0, ready=None):
        capture._stop.clear()
        thread = threading.Thread(target=capture._poll_mouse, daemon=True)
        thread.start()
        if ready is not None:
            deadline = time.monotonic() + 0.8
            while time.monotonic() < deadline and not ready():
                time.sleep(0.01)
        else:
            time.sleep(0.08)
        capture._stop.set()
        thread.join(timeout=timeout)
        self.assertFalse(thread.is_alive())

    def test_click_event_emitted_once_on_press(self):
        events = []
        original = platform_io.get_cursor_pos
        platform_io.get_cursor_pos = lambda: (321, 654)
        try:
            class FakeCapture(InputCapture):
                def _button_down(self, button):
                    return button == 'left'

                def _is_ignored_point(self, x, y):
                    return False

            capture = FakeCapture(events.append, mouse_interval=0.01)
            self._run_poll(capture)
        finally:
            platform_io.get_cursor_pos = original
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['type'], 'click')
        self.assertEqual(events[0]['x'], 321)
        self.assertEqual(events[0]['y'], 654)
        self.assertEqual(events[0]['button'], 'left')

    @unittest.skipUnless(platform_io.IS_WINDOWS, '仅 Windows 使用 GetAsyncKeyState')
    def test_windows_button_down_uses_get_async_key_state(self):
        import ctypes
        fake_user32 = SimpleNamespace(
            GetAsyncKeyState=lambda vk: 0x8000 if vk == 0x01 else 0)
        capture = InputCapture(lambda event: None)
        with mock.patch.object(ctypes, 'windll',
                               SimpleNamespace(user32=fake_user32)):
            self.assertTrue(capture._button_down('left'))
            self.assertFalse(capture._button_down('right'))

    def test_press_release_helpers_dedupe_and_emit_hold(self):
        events = []
        capture = InputCapture(events.append, use_low_level_hook=False)
        capture._is_ignored_point = lambda x, y: False
        capture._handle_press('left', 10, 20)
        capture._handle_press('left', 10, 20)
        capture._handle_release('left')
        capture._handle_release('left')
        self.assertEqual([e['type'] for e in events], ['click', 'click_hold'])
        self.assertEqual(events[1]['x'], 10)
        self.assertEqual(events[1]['y'], 20)
        self.assertGreaterEqual(events[1]['hold_ms'], 0)

    def test_hook_message_maps_buttons_to_press_and_release(self):
        import ctypes
        from ctypes import wintypes

        class HookData(ctypes.Structure):
            _fields_ = [
                ('pt', wintypes.POINT),
                ('mouseData', wintypes.DWORD),
                ('flags', wintypes.DWORD),
                ('time', wintypes.DWORD),
                ('dwExtraInfo', ctypes.c_size_t),
            ]

        events = []
        capture = InputCapture(events.append, use_low_level_hook=False)
        capture._is_ignored_point = lambda x, y: False
        data = HookData()
        data.pt.x, data.pt.y = 77, 88
        capture._handle_hook_message(0x0204, ctypes.pointer(data), HookData)
        capture._handle_hook_message(0x0205, ctypes.pointer(data), HookData)
        self.assertEqual([e['type'] for e in events], ['click', 'click_hold'])
        self.assertEqual(events[0]['button'], 'right')
        self.assertEqual(events[0]['x'], 77)
        self.assertEqual(events[0]['y'], 88)

    def test_release_emits_measured_hold(self):
        events = []
        original = platform_io.get_cursor_pos
        platform_io.get_cursor_pos = lambda: (12, 34)
        states = [True, True, False, False, False]
        try:
            class SequenceCapture(InputCapture):
                def _button_down(self, button):
                    if button != 'left':
                        return False
                    return states.pop(0) if states else False

                def _is_ignored_point(self, x, y):
                    return False

            capture = SequenceCapture(events.append, mouse_interval=0.01)
            capture._stop.clear()
            thread = threading.Thread(target=capture._poll_mouse, daemon=True)
            thread.start()
            deadline = time.monotonic() + 0.8
            while time.monotonic() < deadline and len(events) < 2:
                time.sleep(0.01)
            capture._stop.set()
            thread.join(timeout=1.0)
        finally:
            platform_io.get_cursor_pos = original
        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[0]['type'], 'click')
        self.assertEqual(events[1]['type'], 'click_hold')
        self.assertEqual(events[1]['x'], 12)
        self.assertEqual(events[1]['y'], 34)
        self.assertGreaterEqual(events[1]['hold_ms'], 0)

    def test_start_resets_stale_error_and_button_state(self):
        capture = InputCapture(lambda event: None, use_low_level_hook=False)
        capture.error = 'old keyboard error'
        capture.mouse_error = 'old mouse error'
        capture._buttons['left'] = True
        capture._pressed.add('a')
        fake_keyboard = SimpleNamespace(hook=lambda *a, **k: object(),
                                        unhook=lambda *a, **k: None)
        with mock.patch.dict(sys.modules, {'keyboard': fake_keyboard}):
            self.assertTrue(capture.start())
            capture.stop()
        self.assertEqual(capture.error, '')
        self.assertEqual(capture.mouse_error, '')
        self.assertFalse(capture._buttons['left'])
        self.assertEqual(capture._pressed, set())

    def test_cursor_failure_is_reported_without_killing_thread(self):
        original = platform_io.get_cursor_pos

        def fail():
            raise OSError('GetCursorPos denied')

        platform_io.get_cursor_pos = fail
        try:
            capture = InputCapture(lambda event: None, mouse_interval=0.01)
            self._run_poll(
                capture,
                ready=lambda: 'GetCursorPos denied' in capture.mouse_error,
            )
        finally:
            platform_io.get_cursor_pos = original
        self.assertIn('GetCursorPos denied', capture.mouse_error)


if __name__ == '__main__':
    unittest.main(verbosity=2)
