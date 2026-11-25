# -*- coding: utf-8 -*-
"""平台层（NFR-09）：平台探测、系统设置恢复、鼠标输入后端（Win32/X11/ydotool/pyautogui）。

不依赖 tkinter；UI 层只消费这里导出的函数和常量。
"""
import atexit
import ctypes
import os
import signal
import sys
import threading
import time

PLATFORM = sys.platform
IS_WINDOWS = PLATFORM == 'win32'
IS_LINUX = PLATFORM.startswith('linux')
IS_MACOS = PLATFORM == 'darwin'

# ==================== Windows 特定依赖 ====================
HAS_WIN32GUI = False
HAS_WIN32API = False
if IS_WINDOWS:
    try:
        import win32gui  # noqa: F401
        import win32con  # noqa: F401
        import win32api
        import ctypes
        HAS_WIN32GUI = True
        HAS_WIN32API = True
    except ImportError:
        HAS_WIN32API = False
        print("win32gui模块未安装，Windows系统托盘功能将不可用")

# ==================== Linux 特定依赖 ====================
HAS_X11 = False
HAS_PYSTRAY = False
HAS_PIL = False
if IS_LINUX:
    try:
        from Xlib import X, display
        from Xlib.ext.xtest import fake_input
        HAS_X11 = True
    except ImportError:
        print("python-xlib模块未安装，Linux原生鼠标控制功能将使用pyautogui")
    try:
        import pystray  # noqa: F401
        HAS_PYSTRAY = True
    except ImportError:
        print("pystray模块未安装，Linux系统托盘功能将不可用")
    try:
        from PIL import Image  # noqa: F401
        HAS_PIL = True
    except ImportError:
        print("PIL模块未安装，Linux托盘图标功能将不可用")

# ==================== Windows API 常量 ====================
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040

# H4：只记录本进程实际按下、尚未确认释放的鼠标键。
_MOUSE_FLAGS = {
    'left': (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    'right': (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    'middle': (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}
_MOUSE_DOWN_LOCK = threading.Lock()
_MOUSE_DOWN_BUTTONS = set()


def _mark_mouse_down(button):
    with _MOUSE_DOWN_LOCK:
        _MOUSE_DOWN_BUTTONS.add(button)


def _mark_mouse_up(button):
    with _MOUSE_DOWN_LOCK:
        _MOUSE_DOWN_BUTTONS.discard(button)


def get_foreground_window_info():
    """返回当前前台窗口 (title, process_name, class_name)；不支持的平台返回空串。"""
    if IS_WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            hwnd = u.GetForegroundWindow()
            if not hwnd:
                return '', '', ''
            buf = ctypes.create_unicode_buffer(512)
            u.GetWindowTextW(hwnd, buf, 512)
            cls_buf = ctypes.create_unicode_buffer(256)
            u.GetClassNameW(hwnd, cls_buf, 256)
            pid = wintypes.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            proc = ''
            try:
                k32 = ctypes.windll.kernel32
                handle = k32.OpenProcess(0x1000, False, pid.value)
                if handle:
                    path_buf = ctypes.create_unicode_buffer(1024)
                    size = wintypes.DWORD(1024)
                    if k32.QueryFullProcessImageNameW(handle, 0, path_buf, ctypes.byref(size)):
                        proc = os.path.basename(path_buf.value)
                    k32.CloseHandle(handle)
            except Exception:
                pass
            return buf.value or '', proc or '', cls_buf.value or ''
        except Exception:
            return '', '', ''
    if IS_LINUX:
        try:
            import subprocess
            out = subprocess.run(['xdotool', 'getactivewindow', 'getwindowname'],
                                 capture_output=True, text=True, timeout=2)
            return (out.stdout or '').strip(), '', ''
        except Exception:
            return '', '', ''
    if IS_MACOS:
        try:
            import subprocess
            out = subprocess.run(
                ['osascript', '-e',
                 'tell application "System Events" to get name of first application process whose frontmost is true'],
                capture_output=True, text=True, timeout=2)
            return '', (out.stdout or '').strip(), ''
        except Exception:
            return '', '', ''
    return '', '', ''


def restore_system_settings():
    """FR/E 6.6.2：恢复进程/系统级防休眠设置；atexit 与信号处理共用。"""
    try:
        if IS_WINDOWS:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            print("已恢复Windows休眠设置")
        elif IS_LINUX:
            try:
                import subprocess
                subprocess.Popen(['xset', 's', 'on'], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
                subprocess.Popen(['xset', 'dpms'], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE)
                print("已恢复Linux休眠设置")
            except Exception:
                pass
    except Exception as e:
        print(f"恢复系统休眠设置失败: {e}")


_SETTING_GUARDS_INSTALLED = False


def install_setting_restore_guards():
    """注册崩溃/正常退出/信号路径的系统设置复原钩子（幂等）。"""
    global _SETTING_GUARDS_INSTALLED
    if _SETTING_GUARDS_INSTALLED:
        return
    _SETTING_GUARDS_INSTALLED = True
    atexit.register(restore_system_settings)
    # H4：正常/异常退出都释放可能仍按下的鼠标键
    atexit.register(release_mouse_buttons)

    def _signal_handler(signum, _frame):
        release_mouse_buttons()
        restore_system_settings()
        raise SystemExit(0)

    for name in ('SIGINT', 'SIGTERM', 'SIGHUP', 'SIGBREAK'):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _signal_handler)
        except Exception:
            pass
    print("已注册系统设置复原守卫（atexit/信号）")


def detect_input_backend():
    """FR-L01 / 6.12.1：启动时探测当前会话是否支持模拟输入。"""
    if not IS_LINUX:
        return True, ('windows' if IS_WINDOWS else PLATFORM), ''

    session = (os.environ.get('XDG_SESSION_TYPE') or '').strip().lower()
    has_wayland = bool(os.environ.get('WAYLAND_DISPLAY'))
    has_x11 = bool(os.environ.get('DISPLAY'))
    is_wayland = (session == 'wayland') or (not session and has_wayland and not has_x11)
    if not is_wayland:
        return True, (session or ('x11' if has_x11 else 'unknown')), ''

    doc = "\n\n详见 docs/Wayland降级说明.md"
    import shutil
    if not shutil.which('ydotool'):
        return False, 'wayland', (
            "当前为 Wayland 会话，且未检测到 ydotool，无法模拟鼠标输入。\n"
            "请在登录界面切换到 X11 会话；或安装 ydotool 并启动 ydotoold（当前用户需加入 input 组）。"
            + doc)
    uid = getattr(os, 'getuid', lambda: 0)()
    if not (os.environ.get('YDOTOOL_SOCKET') or os.path.exists('/tmp/.ydotool_socket')
            or os.path.exists('/run/user/%d/.ydotool_socket' % uid)):
        print("提示：未检测到 ydotoold socket，若点击失败请先启动 ydotoold")
    return True, 'wayland', ''


def _is_wayland_session():
    if not IS_LINUX:
        return False
    session = (os.environ.get('XDG_SESSION_TYPE') or '').strip().lower()
    has_wayland = bool(os.environ.get('WAYLAND_DISPLAY'))
    has_x11 = bool(os.environ.get('DISPLAY'))
    return (session == 'wayland') or (not session and has_wayland and not has_x11)


def _ydotool_run(args, timeout=2):
    import subprocess
    try:
        out = subprocess.run(['ydotool'] + list(args), capture_output=True,
                             text=True, timeout=timeout)
        if out.returncode != 0:
            print("ydotool 失败(%s)：%s" % (out.returncode,
                                           (out.stderr or out.stdout or '').strip()[:200]))
            return False
        return True
    except Exception as e:
        print("ydotool 执行异常：%s" % e)
        return False


_YDOTOOL_BUTTONS = {'left': '0xC0', 'right': '0xC1', 'middle': '0xC2'}


def _ydotool_move(x, y):
    for flag in ('--absolute', '-a'):
        if _ydotool_run(['mousemove', flag, '-x', str(int(x)), '-y', str(int(y))]):
            return True
    return False


def _ydotool_click(x, y, button='left', hold_ms=0, double_gap_ms=30):
    if not _ydotool_move(x, y):
        return False
    code = _YDOTOOL_BUTTONS.get(button, _YDOTOOL_BUTTONS['left'])
    if button == 'double':
        first = _ydotool_run(['click', code])
        time.sleep(max(0.001, double_gap_ms / 1000.0))
        second = _ydotool_run(['click', code])
        return first and second
    if hold_ms > 0:
        if not _ydotool_run(['mousedown', code]):
            return False
        time.sleep(hold_ms / 1000.0)
        return _ydotool_run(['mouseup', code])
    return _ydotool_run(['click', code])


_PYAUTOGUI = None
_PYAUTOGUI_LOADED = False


def _get_pyautogui():
    global _PYAUTOGUI, _PYAUTOGUI_LOADED
    if not _PYAUTOGUI_LOADED:
        _PYAUTOGUI_LOADED = True
        try:
            import pyautogui as _pg
            _PYAUTOGUI = _pg
        except ImportError:
            _PYAUTOGUI = None
            print("pyautogui 未安装，非原生输入后端将不可用")
    return _PYAUTOGUI


def windows_move_mouse(x, y):
    try:
        ok = ctypes.windll.user32.SetCursorPos(int(x), int(y))
        if not ok:
            print(f"移动鼠标失败：SetCursorPos 返回 {ok}")
            return False
        return True
    except Exception as e:
        print(f"移动鼠标失败：{e}")
        return False


def _windows_click_button(x, y, button, hold_ms, cancel_event=None):
    normalized = button if button in _MOUSE_FLAGS else 'left'
    flags = _MOUSE_FLAGS[normalized]
    if cancel_event is not None and cancel_event.is_set():
        return False
    down_sent = False
    try:
        ctypes.windll.user32.SetCursorPos(int(x), int(y))
        time.sleep(0.005)
        ctypes.windll.user32.mouse_event(flags[0], 0, 0, 0, 0)
        down_sent = True
        _mark_mouse_down(normalized)
        if hold_ms > 0:
            # H4：按住期间分片等待，停止/退出时 cancel_event 可立即打断。
            deadline = time.monotonic() + hold_ms / 1000.0
            while time.monotonic() < deadline:
                if cancel_event is not None and cancel_event.is_set():
                    return False
                time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
        time.sleep(0.005)
        return True
    except Exception as e:
        print(f"点击失败：{e}")
        return False
    finally:
        # H4：无论正常返回、取消还是异常，只要按下过就必须发送 UP。
        if down_sent:
            try:
                ctypes.windll.user32.mouse_event(flags[1], 0, 0, 0, 0)
                _mark_mouse_up(normalized)
            except Exception:
                pass


def release_mouse_buttons(force_all=False):
    """H4：最后一道保险，释放本进程按下的鼠标键，避免异常退出后按键卡住。

    默认只释放本进程实际按下且尚未确认释放的键；`force_all=True` 时无条件
    补发左/右/中三键 UP，用于显式兜底，不会在正常停止时误释放用户物理按住的鼠标。
    """
    # 仅用 ctypes 发送 mouse_event，不依赖 pywin32；缺少 pywin32 时也必须能兜底。
    if not IS_WINDOWS:
        return
    if force_all:
        buttons = ('left', 'right', 'middle')
    else:
        with _MOUSE_DOWN_LOCK:
            buttons = tuple(_MOUSE_DOWN_BUTTONS)
    for button in buttons:
        try:
            ctypes.windll.user32.mouse_event(
                _MOUSE_FLAGS[button][1], 0, 0, 0, 0)
            _mark_mouse_up(button)
        except Exception:
            pass


def windows_click(x, y, button='left', hold_ms=0, double_gap_ms=30, cancel_event=None):
    if not HAS_WIN32API:
        return False
    try:
        if button == 'double':
            ok1 = _windows_click_button(x, y, 'left', hold_ms, cancel_event)
            if not ok1:
                return False
            gap_seconds = max(0.001, double_gap_ms / 1000.0)
            if cancel_event is not None:
                if cancel_event.wait(gap_seconds):
                    return False
            else:
                time.sleep(gap_seconds)
            ok2 = _windows_click_button(x, y, 'left', hold_ms, cancel_event)
            return ok1 and ok2
        return _windows_click_button(x, y, button, hold_ms, cancel_event)
    except Exception as e:
        print(f"点击失败：{e}")
        return False


def linux_move_mouse(x, y):
    import shutil
    if _is_wayland_session() and shutil.which('ydotool'):
        if _ydotool_move(x, y):
            return True
        print("Wayland 移动鼠标失败：ydotool 不可用，请确认 ydotoold 已启动")
        return False
    if HAS_X11:
        try:
            d = display.Display()
            root = d.screen().root
            root.warp_pointer(int(x), int(y))
            d.sync()
            d.close()
            return True
        except Exception as e:
            print(f"Linux移动鼠标失败：{e}")
    pg = _get_pyautogui()
    if pg is None:
        return False
    try:
        pg.moveTo(x, y)
        return True
    except Exception:
        return False


def linux_click(x, y, button='left', hold_ms=0, double_gap_ms=30):
    import shutil
    if _is_wayland_session() and shutil.which('ydotool'):
        if _ydotool_click(x, y, button, hold_ms, double_gap_ms):
            return True
        print("Wayland 点击失败：ydotool 不可用，请确认 ydotoold 已启动")
        return False
    if not HAS_X11:
        return _pyautogui_click(x, y, button, double_gap_ms if button == 'double' else None)
    try:
        d = display.Display()
        linux_move_mouse(x, y)
        btn = {'left': 1, 'right': 3, 'middle': 2}.get(button, 1)

        def press():
            fake_input(d, X.ButtonPress, btn)
            d.sync()

        def release():
            fake_input(d, X.ButtonRelease, btn)
            d.sync()

        press()
        if hold_ms > 0:
            time.sleep(hold_ms / 1000.0)
        if button == 'double':
            release()
            d.sync()
            time.sleep(max(0.001, double_gap_ms / 1000.0))
            press()
            if hold_ms > 0:
                time.sleep(hold_ms / 1000.0)
        release()
        d.sync()
        d.close()
        return True
    except Exception as e:
        print(f"Linux点击失败：{e}")
        return _pyautogui_click(x, y, button, double_gap_ms if button == 'double' else None)


def _pyautogui_click(x, y, button, interval_ms=None):
    pg = _get_pyautogui()
    if pg is None:
        return False
    try:
        kwargs = {}
        if interval_ms is not None:
            kwargs['interval'] = max(0.001, interval_ms / 1000.0)
        pg.click(x, y,
                  button={'left': 'left', 'right': 'right', 'middle': 'middle'}.get(button, 'left'),
                  clicks=2 if button == 'double' else 1,
                  **kwargs)
        return True
    except Exception:
        return False


def linux_get_cursor_pos():
    if HAS_X11:
        try:
            d = display.Display()
            root = d.screen().root
            data = root.query_pointer()._data
            x = data["root_x"]
            y = data["root_y"]
            d.close()
            return x, y
        except Exception:
            pass
    pg = _get_pyautogui()
    if pg is None:
        return (0, 0)
    return pg.position()


def get_cursor_pos():
    if IS_WINDOWS and HAS_WIN32API:
        return win32api.GetCursorPos()
    elif IS_LINUX:
        return linux_get_cursor_pos()
    pg = _get_pyautogui()
    if pg is None:
        return (0, 0)
    return pg.position()


def move_mouse(x, y):
    if IS_WINDOWS:
        return windows_move_mouse(x, y)
    elif IS_LINUX:
        return linux_move_mouse(x, y)
    pg = _get_pyautogui()
    if pg is None:
        return False
    pg.moveTo(x, y)
    return True


def click_mouse(x, y, button='left', hold_ms=0, double_gap_ms=30, cancel_event=None):
    if IS_WINDOWS:
        return windows_click(x, y, button, hold_ms, double_gap_ms, cancel_event)
    elif IS_LINUX:
        return linux_click(x, y, button, hold_ms, double_gap_ms)
    return _pyautogui_click(x, y, button, double_gap_ms if button == 'double' else None)
