# -*- coding: utf-8 -*-
"""FR-13：录制期的全局鼠标/键盘采集。

不注入其他进程；只在用户主动录制时挂接监听。Windows 优先使用
``WH_MOUSE_LL`` 低级鼠标钩子（可捕获极快点击），安装失败时回退 20ms
轮询；其他平台使用轮询。键盘使用 ``keyboard`` 的全局 hook。无权限或无
桌面会话时抛出 MacroError，由主程序提示并保持 UI 可用。
"""
import threading
import time

from auto_clicker_layers.platform_io import IS_LINUX, IS_WINDOWS


class InputCapture:
    def __init__(self, on_event, excluded_keys=None, ignore_hwnd=None,
                 mouse_interval=0.02, use_low_level_hook=None):
        self.on_event = on_event
        self.excluded_keys = {str(k).lower() for k in (excluded_keys or ())}
        self.excluded_keys.update({'esc', 'f8'})
        self.ignore_hwnd = ignore_hwnd
        self.mouse_interval = max(0.01, float(mouse_interval))
        self.use_low_level_hook = (
            IS_WINDOWS if use_low_level_hook is None else bool(use_low_level_hook))
        self._stop = threading.Event()
        self._mouse_thread = None
        self._mouse_hook_thread = None
        self._mouse_hook_handle = None
        self._mouse_hook_tid = None
        self._mouse_hook_callback = None
        self._mouse_hook_ready = threading.Event()
        self._mouse_hook_ok = False
        self._kb_hook = None
        self._pressed = set()
        self._buttons = {'left': False, 'right': False, 'middle': False}
        self._down_times = {}
        self._down_points = {}
        self._display = None
        self._started = False
        self._mouse_fail_count = 0
        self.error = ''
        self.mouse_error = ''

    def start(self):
        if self._started:
            return True
        # H5：每次录制从干净状态开始，避免上一次失败/按住状态污染本次。
        self.error = ''
        self.mouse_error = ''
        self._mouse_fail_count = 0
        self._buttons = {'left': False, 'right': False, 'middle': False}
        self._down_times = {}
        self._down_points = {}
        self._pressed.clear()
        self._started = True
        self._stop.clear()
        self._mouse_hook_ok = False
        if self.use_low_level_hook and self._start_mouse_hook():
            self._mouse_hook_ok = True
        else:
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
        if self._mouse_hook_thread is not None:
            try:
                import ctypes
                if self._mouse_hook_tid:
                    ctypes.windll.user32.PostThreadMessageW(
                        self._mouse_hook_tid, 0x0012, 0, 0)  # WM_QUIT
                if self._mouse_hook_thread.is_alive():
                    self._mouse_hook_thread.join(timeout=1.0)
                if self._mouse_hook_handle:
                    ctypes.windll.user32.UnhookWindowsHookEx(
                        self._mouse_hook_handle)
            except Exception:
                pass
            self._mouse_hook_thread = None
            self._mouse_hook_handle = None
            self._mouse_hook_tid = None
            self._mouse_hook_callback = None
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
        self._buttons = {'left': False, 'right': False, 'middle': False}
        self._down_times = {}
        self._down_points = {}
        self._pressed.clear()
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

    def _start_mouse_hook(self):
        """H5：Windows 优先装 WH_MOUSE_LL；失败回退轮询。"""
        if not IS_WINDOWS:
            return False
        self._mouse_hook_ready.clear()
        self._mouse_hook_thread = threading.Thread(
            target=self._mouse_hook_loop, name='macro-mouse-hook', daemon=True)
        self._mouse_hook_thread.start()
        if not self._mouse_hook_ready.wait(timeout=1.5):
            return False
        return bool(self._mouse_hook_ok)

    def _mouse_hook_loop(self):
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            class MSLLHOOKSTRUCT(ctypes.Structure):
                _fields_ = [
                    ('pt', wintypes.POINT),
                    ('mouseData', wintypes.DWORD),
                    ('flags', wintypes.DWORD),
                    ('time', wintypes.DWORD),
                    ('dwExtraInfo', ctypes.c_size_t),
                ]

            hook_proc = ctypes.WINFUNCTYPE(
                wintypes.LPARAM, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
            user32.SetWindowsHookExW.restype = ctypes.c_void_p
            user32.SetWindowsHookExW.argtypes = (
                ctypes.c_int, hook_proc, ctypes.c_void_p, ctypes.c_uint)
            user32.CallNextHookEx.restype = wintypes.LPARAM
            user32.CallNextHookEx.argtypes = (
                ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
            user32.UnhookWindowsHookEx.argtypes = (ctypes.c_void_p,)
            user32.GetMessageW.argtypes = (
                ctypes.POINTER(wintypes.MSG), ctypes.c_void_p,
                ctypes.c_uint, ctypes.c_uint)
            user32.GetMessageW.restype = ctypes.c_int
            user32.PeekMessageW.argtypes = (
                ctypes.POINTER(wintypes.MSG), ctypes.c_void_p,
                ctypes.c_uint, ctypes.c_uint, ctypes.c_uint)
            user32.TranslateMessage.argtypes = (ctypes.POINTER(wintypes.MSG),)
            user32.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)

            def on_mouse(code, wparam, lparam):
                if code >= 0 and not self._stop.is_set():
                    try:
                        self._handle_hook_message(wparam, lparam, MSLLHOOKSTRUCT)
                    except Exception:
                        pass
                return user32.CallNextHookEx(
                    self._mouse_hook_handle, code, wparam, lparam)

            self._mouse_hook_tid = kernel32.GetCurrentThreadId()
            self._mouse_hook_callback = hook_proc(on_mouse)
            self._mouse_hook_handle = user32.SetWindowsHookExW(
                14, self._mouse_hook_callback, None, 0)  # WH_MOUSE_LL
            if not self._mouse_hook_handle:
                raise OSError('SetWindowsHookExW(WH_MOUSE_LL) 返回空句柄')
            msg = wintypes.MSG()
            # 先创建线程消息队列，保证 stop 的 PostThreadMessage 不会丢
            user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 0)
            self._mouse_hook_ok = True
            self._mouse_hook_ready.set()
            while not self._stop.is_set():
                if user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) <= 0:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:
            self.mouse_error = '低级鼠标钩子不可用：%s' % exc
            self._mouse_hook_ok = False
            self._mouse_hook_ready.set()
        finally:
            if self._mouse_hook_handle:
                try:
                    ctypes.windll.user32.UnhookWindowsHookEx(self._mouse_hook_handle)
                except Exception:
                    pass
                self._mouse_hook_handle = None

    def _handle_hook_message(self, wparam, lparam, structure):
        """把 WM_*BUTTON* 转成与轮询相同的 press/release 语义。"""
        if wparam == 0x0201:  # WM_LBUTTONDOWN
            button = 'left'
        elif wparam == 0x0204:  # WM_RBUTTONDOWN
            button = 'right'
        elif wparam == 0x0207:  # WM_MBUTTONDOWN
            button = 'middle'
        elif wparam == 0x0202:  # WM_LBUTTONUP
            button = 'left'
        elif wparam == 0x0205:  # WM_RBUTTONUP
            button = 'right'
        elif wparam == 0x0208:  # WM_MBUTTONUP
            button = 'middle'
        else:
            return
        import ctypes
        data = ctypes.cast(lparam, ctypes.POINTER(structure)).contents
        x, y = int(data.pt.x), int(data.pt.y)
        if wparam in (0x0201, 0x0204, 0x0207):
            self._handle_press(button, x, y)
        else:
            self._handle_release(button)

    def _handle_press(self, button, x, y):
        if self._buttons.get(button):
            return
        self._buttons[button] = True
        if self._is_ignored_point(x, y):
            self._down_times[button] = None
            self._down_points[button] = None
            return
        self._down_times[button] = time.monotonic()
        self._down_points[button] = (int(x), int(y))
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

    def _handle_release(self, button):
        if not self._buttons.get(button):
            return
        self._buttons[button] = False
        started = self._down_times.pop(button, None)
        point = self._down_points.pop(button, None)
        if started is None or point is None:
            return
        hold_ms = max(0, int((time.monotonic() - started) * 1000))
        try:
            self.on_event({
                'type': 'click_hold',
                'x': point[0],
                'y': point[1],
                'button': button,
                'hold_ms': hold_ms,
            })
        except Exception:
            pass

    def _button_down(self, button):
        if IS_WINDOWS:
            try:
                import ctypes
                # H5：轮询线程没有消息循环，GetKeyState 不可靠；GetAsyncKeyState 读取全局状态。
                vk = {'left': 0x01, 'right': 0x02, 'middle': 0x04}[button]
                return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
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
                    if down:
                        self._handle_press(button, x, y)
                    else:
                        self._handle_release(button)
            except Exception as exc:
                self._mouse_fail_count += 1
                if self._mouse_fail_count >= 5:
                    self.mouse_error = "鼠标位置读取失败：%s" % exc
            self._stop.wait(self.mouse_interval)
