# -*- coding: utf-8 -*-
"""FR-13：录制期的全局鼠标/键盘采集。

不注入其他进程；只在用户主动录制时挂接监听。鼠标使用轻量轮询（20ms），
键盘使用 ``keyboard`` 的全局 hook。无权限或无桌面会话时抛出 MacroError，
由主程序提示并保持 UI 可用。
"""
import threading
import time

from auto_clicker_layers.platform_io import IS_LINUX, IS_WINDOWS


class InputCapture:
    def __init__(self, on_event, excluded_keys=None, ignore_hwnd=None,
                 mouse_interval=0.02):
        self.on_event = on_event
        self.excluded_keys = {str(k).lower() for k in (excluded_keys or ())}
        self.excluded_keys.update({'esc', 'f8'})
        self.ignore_hwnd = ignore_hwnd
        self.mouse_interval = max(0.01, float(mouse_interval))
        self._stop = threading.Event()
        self._mouse_thread = None
        self._kb_hook = None
        self._pressed = set()
        self._buttons = {'left': False, 'right': False, 'middle': False}
        self._display = None
        self._started = False
        self._mouse_fail_count = 0
        self.error = ''
        self.mouse_error = ''

    def start(self):
        if self._started:
            return True
        self._started = True
        self._stop.clear()
        self._mouse_thread = threading.Thread(
            target=self._poll_mouse, name='macro-mouse-capture', daemon=True)
        self._mouse_thread.start()
        try:
            import keyboard
            self._kb_hook = keyboard.hook(self._on_key, suppress=False)
        except Exception as exc:
            self.error = '键盘监听不可用：%s' % exc
        return not self.error

    def stop(self):
        if not self._started:
            return
        self._stop.set()
        if self._kb_hook is not None:
            try:
                import keyboard
                keyboard.unhook(self._kb_hook)
            except Exception:
                pass
            self._kb_hook = None
        if self._mouse_thread is not None and self._mouse_thread.is_alive():
            try:
                self._mouse_thread.join(timeout=1.0)
            except RuntimeError:
                pass
        self._mouse_thread = None
        try:
            if self._display is not None:
                self._display.close()
        except Exception:
            pass
        self._display = None
        self._started = False

    def _on_key(self, event):
        if self._stop.is_set():
            return
        name = str(getattr(event, 'name', '') or '').strip().lower()
        if not name or name in self.excluded_keys:
            return
        event_type = str(getattr(event, 'event_type', '') or '').lower()
        if event_type not in ('down', 'up'):
            return
        if event_type == 'down':
            if name in self._pressed:
                return
            self._pressed.add(name)
        else:
            if name not in self._pressed:
                return
            self._pressed.discard(name)
        try:
            self.on_event({
                'type': 'key',
                'key': name,
                'action': event_type,
            })
        except Exception:
            pass

    def _button_down(self, button):
        if IS_WINDOWS:
            try:
                import win32api
                import win32con
                vk = {
                    'left': win32con.VK_LBUTTON,
                    'right': win32con.VK_RBUTTON,
                    'middle': win32con.VK_MBUTTON,
                }[button]
                return bool(win32api.GetKeyState(vk) & 0x8000)
            except Exception:
                return False
        if IS_LINUX:
            try:
                if self._display is None:
                    from Xlib import display
                    self._display = display.Display()
                pointer = self._display.screen().root.query_pointer()._data
                mask = pointer.get('mask', 0)
                bit = {'left': 1 << 8, 'right': 1 << 10, 'middle': 1 << 9}[button]
                return bool(mask & bit)
            except Exception:
                return False
        return False

    def _is_ignored_point(self, x, y):
        if not self.ignore_hwnd:
            return False
        if not IS_WINDOWS:
            return False
        try:
            import win32gui
            hwnd = win32gui.WindowFromPoint((int(x), int(y)))
            return bool(hwnd) and win32gui.GetAncestor(hwnd, 2) == self.ignore_hwnd
        except Exception:
            return False

    def _poll_mouse(self):
        from auto_clicker_layers.platform_io import get_cursor_pos
        while not self._stop.is_set():
            try:
                x, y = get_cursor_pos()
                self._mouse_fail_count = 0
                self.mouse_error = ''
                for button in ('left', 'right', 'middle'):
                    down = self._button_down(button)
                    if down and not self._buttons[button]:
                        if not self._is_ignored_point(x, y):
                            try:
                                self.on_event({
                                    'type': 'click',
                                    'x': int(x),
                                    'y': int(y),
                                    'button': button,
                                    'hold_ms': 0,
                                })
                            except Exception:
                                pass
                    self._buttons[button] = down
            except Exception as exc:
                self._mouse_fail_count += 1
                if self._mouse_fail_count >= 5:
                    self.mouse_error = "鼠标位置读取失败：%s" % exc
            self._stop.wait(self.mouse_interval)
