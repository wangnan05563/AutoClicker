# -*- coding: utf-8 -*-
"""FR-13：输入采集层的鼠标轮询与键盘去重逻辑测试。"""
import threading
import time
import unittest
from types import SimpleNamespace

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
