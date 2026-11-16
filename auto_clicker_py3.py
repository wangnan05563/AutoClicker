# -*- coding: utf-8 -*-
"""
桌面自动点击工具 - Python 3.14 兼容版
支持 Windows、银河麒麟等多操作系统
支持系统托盘最小化运行
"""

import sys
import os
import atexit
import signal
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import queue
import time
import random
import json
from datetime import datetime

# 点击抖动使用系统安全随机源，避免可预测的伪随机序列
_RANDOM = random.SystemRandom()

# ==================== 平台检测 ====================
PLATFORM = sys.platform
IS_WINDOWS = PLATFORM == 'win32'
IS_LINUX = PLATFORM.startswith('linux')
IS_MACOS = PLATFORM == 'darwin'


def target_window_matches(keyword, title, process_name=''):
    """FR-E03：目标窗口关键字匹配（标题或进程名，大小写不敏感）。空关键字=不校验。"""
    key = (keyword or '').strip().lower()
    if not key:
        return True
    return key in (title or '').lower() or key in (process_name or '').lower()


def get_foreground_window_info():
    """返回当前前台窗口 (title, process_name)；不支持的平台返回 ('','')。"""
    if IS_WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes
            u = ctypes.windll.user32
            hwnd = u.GetForegroundWindow()
            if not hwnd:
                return '', ''
            buf = ctypes.create_unicode_buffer(512)
            u.GetWindowTextW(hwnd, buf, 512)
            pid = wintypes.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            proc = ''
            try:
                k32 = ctypes.windll.kernel32
                handle = k32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
                if handle:
                    path_buf = ctypes.create_unicode_buffer(1024)
                    size = wintypes.DWORD(1024)
                    if k32.QueryFullProcessImageNameW(handle, 0, path_buf, ctypes.byref(size)):
                        proc = os.path.basename(path_buf.value)
                    k32.CloseHandle(handle)
            except Exception:
                pass
            return buf.value or '', proc or ''
        except Exception:
            return '', ''
    if IS_LINUX:
        try:
            import subprocess
            out = subprocess.run(['xdotool', 'getactivewindow', 'getwindowname'],
                                 capture_output=True, text=True, timeout=2)
            title = (out.stdout or '').strip()
            return title, ''
        except Exception:
            return '', ''
    if IS_MACOS:
        try:
            import subprocess
            out = subprocess.run(
                ['osascript', '-e',
                 'tell application "System Events" to get name of first application process whose frontmost is true'],
                capture_output=True, text=True, timeout=2)
            return '', (out.stdout or '').strip()
        except Exception:
            return '', ''
    return '', ''


def restore_system_settings():
    """FR/E 6.6.2：恢复进程/系统级防休眠设置；atexit 与信号处理共用。"""
    try:
        if IS_WINDOWS:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)  # ES_CONTINUOUS
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

    def _signal_handler(signum, _frame):
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
    """FR-L01 / 6.12.1：启动时探测当前会话是否支持模拟输入。

    返回 (ok, session, reason)。ok=False 时必须明确提示并禁用启动，不静默失败。
    判据保持保守：只有明确是 Wayland 且没有 X11 可用时才拦截，避免误伤
    XWayland / X11 会话（银河麒麟等国产桌面常同时设置多个环境变量）。
    """
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
    # ydotool 已安装：由 _ydotool_* 后端执行移动/点击；ydotoold 未启动时命令会失败，
    # 由调用方给出明确错误，不再静默禁用整个 Wayland 会话。
    uid = getattr(os, 'getuid', lambda: 0)()
    if not (os.environ.get('YDOTOOL_SOCKET') or os.path.exists('/tmp/.ydotool_socket')
            or os.path.exists('/run/user/%d/.ydotool_socket' % uid)):
        print("提示：未检测到 ydotoold socket，若点击失败请先启动 ydotoold")
    return True, 'wayland', ''


def _is_wayland_session():
    """是否明确处于 Wayland 会话（与 detect_input_backend 判据一致）。"""
    if not IS_LINUX:
        return False
    session = (os.environ.get('XDG_SESSION_TYPE') or '').strip().lower()
    has_wayland = bool(os.environ.get('WAYLAND_DISPLAY'))
    has_x11 = bool(os.environ.get('DISPLAY'))
    return (session == 'wayland') or (not session and has_wayland and not has_x11)


def _ydotool_run(args, timeout=2):
    """执行 ydotool 子命令；失败返回 False（不抛出到 UI 线程）。"""
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
    # ydotool 新旧版本参数兼容：优先 --absolute，再退回 -a
    for flag in ('--absolute', '-a'):
        if _ydotool_run(['mousemove', flag, '-x', str(int(x)), '-y', str(int(y))]):
            return True
    return False


def _ydotool_click(x, y, button='left', hold_ms=0):
    if not _ydotool_move(x, y):
        return False
    code = _YDOTOOL_BUTTONS.get(button, _YDOTOOL_BUTTONS['left'])
    if button == 'double':
        first = _ydotool_run(['click', code])
        time.sleep(0.03)
        second = _ydotool_run(['click', code])
        return first and second
    if hold_ms > 0:
        if not _ydotool_run(['mousedown', code]):
            return False
        time.sleep(hold_ms / 1000.0)
        return _ydotool_run(['mouseup', code])
    return _ydotool_run(['click', code])


# ==================== 核心依赖 ====================
# pyautogui 仅作为无原生输入后端时的降级路径。顶部 import 会串行加载
# mouseinfo/pyscreeze/pygetwindow，实测拖慢冷启动 8 秒以上；改为首次使用时懒加载。
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

keyboard = None
_KEYBOARD_LOADED = False


def _get_keyboard():
    """延迟导入 keyboard：冷启动时省掉约 1.3 秒全局钩子初始化，窗口显示后再注册。"""
    global keyboard, _KEYBOARD_LOADED
    if not _KEYBOARD_LOADED:
        _KEYBOARD_LOADED = True
        try:
            import keyboard as _kb
            keyboard = _kb
        except ImportError:
            keyboard = None
            print("keyboard模块未安装，快捷键功能将不可用")
    return keyboard

# ==================== Windows 特定依赖 ====================
HAS_WIN32GUI = False
HAS_WIN32API = False
if IS_WINDOWS:
    try:
        import win32gui
        import win32con
        import win32api
        import ctypes
        HAS_WIN32GUI = True
        HAS_WIN32API = True
    except ImportError:
        HAS_WIN32GUI = False
        HAS_WIN32API = False
        print("win32gui模块未安装，Windows系统托盘功能将不可用")

# ==================== Linux 特定依赖 ====================
HAS_X11 = False
HAS_PYSTRAY = False
HAS_PIL = False
if IS_LINUX:
    # X11 鼠标控制
    try:
        from Xlib import X, display
        from Xlib.ext.xtest import fake_input
        HAS_X11 = True
    except ImportError:
        print("python-xlib模块未安装，Linux原生鼠标控制功能将使用pyautogui")
    
    # 系统托盘支持
    try:
        import pystray
        HAS_PYSTRAY = True
    except ImportError:
        print("pystray模块未安装，Linux系统托盘功能将不可用")
    
    # 图像处理（用于托盘图标）
    try:
        from PIL import Image
        HAS_PIL = True
    except ImportError:
        print("PIL模块未安装，Linux托盘图标功能将不可用")

# ==================== Windows API 常量 ====================
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_ABSOLUTE = 0x8000

# ==================== 防锁屏保活参数 ====================
# 后台保活线程每隔该秒数重新断言“系统/显示器保持唤醒”并做一次 1px 微抖动，
# 远小于常见 1~5 分钟的系统空闲锁屏/屏保阈值，从而独立于“点击运行”持续保活。
KEEPALIVE_INTERVAL = 30

# 复用文案与文件类型（S1192：避免同一字面量重复定义）
MSG_SAVE_CONFIG_FAILED = "保存配置失败: "
JSON_FILE_PATTERN = "*.json"

# ==================== 平台通用函数 ====================
def windows_move_mouse(x, y):
    """使用 Windows API 移动鼠标（ctypes 直连，不依赖 pywin32 是否可用）"""
    try:
        ok = ctypes.windll.user32.SetCursorPos(int(x), int(y))
        if not ok:
            print(f"移动鼠标失败：SetCursorPos 返回 {ok}")
            return False
        return True
    except Exception as e:
        print(f"移动鼠标失败：{e}")
        return False

def windows_click(x, y, button='left', hold_ms=0):
    """使用 Windows API 执行鼠标点击（支持左/右/中键、双击与按住时长）"""
    if not HAS_WIN32API:
        return False
    try:
        if button == 'double':
            _windows_click_button(x, y, 'left', hold_ms)
            time.sleep(0.03)
            _windows_click_button(x, y, 'left', hold_ms)
            return True
        return _windows_click_button(x, y, button, hold_ms)
    except Exception as e:
        print(f"点击失败：{e}")
        return False


def _windows_click_button(x, y, button, hold_ms):
    """Windows 单键按下/抬起（含按住时长）"""
    flags = {
        'left': (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
        'right': (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        'middle': (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
    }.get(button, (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP))
    try:
        ctypes.windll.user32.SetCursorPos(int(x), int(y))
        time.sleep(0.005)
        ctypes.windll.user32.mouse_event(flags[0], 0, 0, 0, 0)
        if hold_ms > 0:
            time.sleep(hold_ms / 1000.0)
        time.sleep(0.005)
        ctypes.windll.user32.mouse_event(flags[1], 0, 0, 0, 0)
        return True
    except Exception as e:
        print(f"点击失败：{e}")
        return False

def linux_move_mouse(x, y):
    """使用 X11 API 或 ydotool（Wayland）移动鼠标（银河麒麟兼容）"""
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

def linux_click(x, y, button='left', hold_ms=0):
    """使用 X11 API 或 ydotool（Wayland）执行点击（支持左/右/中键、双击与按住时长）"""
    import shutil
    if _is_wayland_session() and shutil.which('ydotool'):
        if _ydotool_click(x, y, button, hold_ms):
            return True
        print("Wayland 点击失败：ydotool 不可用，请确认 ydotoold 已启动")
        return False
    if not HAS_X11:
        return _pyautogui_click(x, y, button)
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
            time.sleep(0.03)
            press()
            if hold_ms > 0:
                time.sleep(hold_ms / 1000.0)
        release()
        d.sync()
        d.close()
        return True
    except Exception as e:
        print(f"Linux点击失败：{e}")
        return _pyautogui_click(x, y, button)


def _pyautogui_click(x, y, button):
    """pyautogui 降级点击（无 X11 或异常时）"""
    pg = _get_pyautogui()
    if pg is None:
        return False
    try:
        pg.click(x, y,
                  button={'left': 'left', 'right': 'right', 'middle': 'middle'}.get(button, 'left'),
                  clicks=2 if button == 'double' else 1)
        return True
    except Exception:
        return False

def linux_get_cursor_pos():
    """获取 Linux 鼠标位置"""
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
    """跨平台获取鼠标位置"""
    if IS_WINDOWS and HAS_WIN32API:
        return win32api.GetCursorPos()
    elif IS_LINUX:
        return linux_get_cursor_pos()
    else:
        pg = _get_pyautogui()
        if pg is None:
            return (0, 0)
        return pg.position()

def move_mouse(x, y):
    """跨平台移动鼠标"""
    if IS_WINDOWS:
        return windows_move_mouse(x, y)
    elif IS_LINUX:
        return linux_move_mouse(x, y)
    else:
        pg = _get_pyautogui()
        if pg is None:
            return False
        pg.moveTo(x, y)
        return True

def click_mouse(x, y, button='left', hold_ms=0):
    """跨平台点击鼠标（支持按键类型与按住时长）"""
    if IS_WINDOWS:
        return windows_click(x, y, button, hold_ms)
    elif IS_LINUX:
        return linux_click(x, y, button, hold_ms)
    else:
        return _pyautogui_click(x, y, button)


def normalize_region(x1, y1, x2, y2):
    """把拖拽起止点归一化为闭区间区域；单击（几乎无位移）按 1×1 点处理。"""
    left = min(int(x1), int(x2))
    top = min(int(y1), int(y2))
    width = abs(int(x2) - int(x1))
    height = abs(int(y2) - int(y1))
    if width < 2 and height < 2:
        return {'x': left, 'y': top, 'width': 1, 'height': 1, 'point': True}
    return {'x': left, 'y': top, 'width': max(1, width + 1), 'height': max(1, height + 1)}


class RegionSelector:
    """FR-C01/8.1：全屏半透明遮罩 + 十字线 + 拖拽框选 + 实时尺寸标签。

    交互：
      - 按下左键并拖拽：实时绘制选框，标签显示 `W×H (x,y)`；
      - 松开左键：选框保留 1 秒后关闭并回调；几乎无位移时按单击取 1×1 点；
      - 右键：撤销当前选框；
      - Esc：立即取消，原配置不变；Enter：确认当前选框。
    """

    def __init__(self, parent, on_done):
        self.parent = parent
        self.on_done = on_done
        self.start_xy = None
        self.start_abs = None
        self.rect_id = None
        self.last_region = None
        self._finished = False
        self._finish_after = None

        self.top = tk.Toplevel(parent)
        self.top.overrideredirect(True)
        self.top.configure(bg='#000000')
        try:
            self.top.attributes('-topmost', True)
            self.top.attributes('-alpha', 0.45)
        except Exception:
            pass

        # 虚拟屏幕范围：Windows 用系统指标，其他平台用 Tk 虚拟根窗口
        ox, oy, sw, sh = 0, 0, parent.winfo_screenwidth(), parent.winfo_screenheight()
        if IS_WINDOWS:
            try:
                import ctypes
                u = ctypes.windll.user32
                ox = int(u.GetSystemMetrics(76))   # SM_XVIRTUALSCREEN
                oy = int(u.GetSystemMetrics(77))   # SM_YVIRTUALSCREEN
                sw = int(u.GetSystemMetrics(78))   # SM_CXVIRTUALSCREEN
                sh = int(u.GetSystemMetrics(79))   # SM_CYVIRTUALSCREEN
            except Exception:
                pass
        self.origin_x, self.origin_y = ox, oy
        try:
            self.top.geometry("%dx%d%+d%+d" % (sw, sh, ox, oy))
        except Exception:
            self.top.geometry("%dx%d+0+0" % (sw, sh))

        self.canvas = tk.Canvas(self.top, bg='#000000', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.configure(cursor='crosshair')
        self.hline = self.canvas.create_line(0, 0, sw, 0, fill='#60A5FA', width=1)
        self.vline = self.canvas.create_line(0, 0, 0, sh, fill='#60A5FA', width=1)
        self.prompt = tk.Label(
            self.top, text="拖拽框选区域 · 单击取点 · Esc 取消 · 右键撤销 · Enter 确认",
            bg='#1F2229', fg='#E8EAED', font=('微软雅黑', 10, 'bold'),
            padx=14, pady=7)
        # 提示条放在主屏可见区域中央，虚拟屏扩展到多屏时不会跑到副屏外
        primary_w = sw
        if IS_WINDOWS:
            try:
                import ctypes
                primary_w = int(ctypes.windll.user32.GetSystemMetrics(0)) or sw
            except Exception:
                pass
        self.prompt.place(x=max(0, primary_w // 2), y=18, anchor='n')
        self.size_label = tk.Label(
            self.top, text='', bg='#2563EB', fg='white',
            font=('Consolas', 10, 'bold'), padx=8, pady=4)
        self.size_label.place(x=20, y=20)

        for widget in (self.top, self.canvas):
            widget.bind('<Motion>', self._on_motion)
            widget.bind('<ButtonPress-1>', self._on_press)
            widget.bind('<B1-Motion>', self._on_drag)
            widget.bind('<ButtonRelease-1>', self._on_release)
            widget.bind('<ButtonPress-3>', self._on_right)
        self.top.bind('<Escape>', self._on_cancel)
        self.top.bind('<Return>', self._on_confirm)
        self.top.bind('<KP_Enter>', self._on_confirm)

        self.top.update_idletasks()
        # Windows 上负坐标虚拟屏由 SetWindowPos 兜底，避免 Tk 把 -x 解释成右边缘偏移
        if IS_WINDOWS:
            try:
                import ctypes
                hwnd = self.top.winfo_id()
                u = ctypes.windll.user32
                # Tk 的顶层窗口外面还有一层 wrapper，必须对根 HWND 设置 TOPMOST
                root_hwnd = u.GetAncestor(hwnd, 2) or hwnd
                u.SetWindowPos(
                    root_hwnd, -1, ox, oy, sw, sh, 0x0040)  # HWND_TOPMOST, SWP_SHOWWINDOW
            except Exception:
                pass
        try:
            self.top.attributes('-topmost', True)
            self.top.lift()
        except Exception:
            pass
        try:
            # 全局 grab：遮罩必须优先拿到鼠标事件，避免被主窗口/其他窗口抢走
            self.top.grab_set_global()
        except Exception:
            try:
                self.top.grab_set()
            except Exception:
                pass
        try:
            self.top.focus_force()
        except Exception:
            pass

    def _abs_xy(self, event):
        return int(event.x_root), int(event.y_root)

    def _draw_size(self, region, px, py):
        text = "%d×%d (%d,%d)" % (region['width'], region['height'], region['x'], region['y'])
        self.size_label.config(text=text)
        # 标签放在光标右下方，贴近当前框选操作
        self.size_label.place(x=max(0, px + 14), y=max(0, py + 14))

    def _on_motion(self, event):
        if self._finished:
            return
        self.canvas.coords(self.hline, 0, event.y, self.canvas.winfo_width(), event.y)
        self.canvas.coords(self.vline, event.x, 0, event.x, self.canvas.winfo_height())

    def _on_press(self, event):
        if self._finished:
            return
        self.start_xy = (event.x, event.y)
        self.start_abs = self._abs_xy(event)
        self.last_region = None
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline='#60A5FA', width=2, fill='')
        self.size_label.config(text='0×0')
        self.size_label.place(x=max(0, event.x + 14), y=max(0, event.y + 14))

    def _on_drag(self, event):
        if self._finished or not self.start_xy or not self.rect_id:
            return
        self.canvas.coords(self.rect_id, self.start_xy[0], self.start_xy[1], event.x, event.y)
        x1, y1 = self._abs_xy(event)
        sx, sy = self.start_abs if self.start_abs else (
            self.origin_x + self.start_xy[0], self.origin_y + self.start_xy[1])
        self.last_region = normalize_region(sx, sy, x1, y1)
        self._draw_size(self.last_region, event.x, event.y)

    def _on_release(self, event):
        if self._finished or not self.start_xy:
            return
        x1, y1 = self._abs_xy(event)
        sx, sy = self.start_abs if self.start_abs else (
            self.origin_x + self.start_xy[0], self.origin_y + self.start_xy[1])
        self.last_region = normalize_region(sx, sy, x1, y1)
        self._draw_size(self.last_region, event.x, event.y)
        # 选框保留 1 秒，随后回填并关闭
        self._finish_after = self.top.after(1000, self._finish_with_last)

    def _on_right(self, event):
        if self._finished:
            return
        if self.rect_id:
            self.canvas.delete(self.rect_id)
            self.rect_id = None
        self.start_xy = None
        self.start_abs = None
        self.last_region = None
        self.size_label.config(text='已撤销当前选框')

    def _on_confirm(self, event=None):
        if self.last_region:
            self._finish_with_last()

    def _on_cancel(self, event=None):
        if self._finished:
            return
        self._finish(None, cancelled=True)

    def _finish_with_last(self):
        if self._finished:
            return
        if self.last_region:
            self._finish(self.last_region)
        else:
            self._finish(None, cancelled=True)

    def _finish(self, region, cancelled=False):
        if self._finished:
            return
        self._finished = True
        try:
            if self._finish_after:
                self.top.after_cancel(self._finish_after)
        except Exception:
            pass
        try:
            self.top.grab_release()
        except Exception:
            pass
        try:
            self.top.destroy()
        except Exception:
            pass
        try:
            self.on_done(None if cancelled else region)
        except Exception:
            pass


class NoticeBar:
    """8.3 错误提示分级：顶部可关闭横幅（operation 级）。"""

    def __init__(self, parent, color_getter):
        self.color_getter = color_getter
        self.frame = tk.Frame(parent, bg=color_getter('warning'))
        self.label = tk.Label(
            self.frame, text='', bg=color_getter('warning'), fg=color_getter('on_warning'),
            font=('微软雅黑', 10, 'bold'), wraplength=520, justify=tk.LEFT, anchor=tk.W)
        self.label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 6), pady=7)
        self.close_btn = tk.Button(
            self.frame, text='×', command=self.hide, bg=color_getter('warning'),
            fg=color_getter('on_warning'),
            activebackground=color_getter('warning'), activeforeground=color_getter('on_warning'),
            relief=tk.FLAT, bd=0, font=('微软雅黑', 11, 'bold'), cursor='hand2')
        self.close_btn.pack(side=tk.RIGHT, padx=(0, 8))
        self._after_id = None
        self._parent = parent

    def show(self, message, level='operation', timeout=0, before=None):
        color = self.color_getter('danger' if level == 'fatal' else 'warning')
        on_color = self.color_getter('on_danger' if level == 'fatal' else 'on_warning')
        self.frame.configure(bg=color)
        self.label.configure(text=message, bg=color, fg=on_color)
        self.close_btn.configure(bg=color, activebackground=color,
                                 fg=on_color, activeforeground=on_color)
        if not self.frame.winfo_manager():
            pack_kw = {'fill': tk.X, 'pady': (0, 10)}
            if before is not None:
                pack_kw['before'] = before
            self.frame.pack(**pack_kw)
        if self._after_id:
            try:
                self.frame.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if timeout:
            self._after_id = self.frame.after(timeout, self.hide)

    def hide(self):
        try:
            self.frame.pack_forget()
        except Exception:
            pass


# ERROR_ALREADY_EXISTS常量（在pywin32中可能未定义）
ERROR_ALREADY_EXISTS = 183

# 单实例检查 - 使用互斥锁
# 允许通过环境变量覆盖互斥名/窗口标题，便于隔离测试与多版本并行启动；
# 未设置时保持生产默认值不变。
SINGLE_INSTANCE_MUTEX_NAME = os.environ.get(
    "AUTOCLICKER_MUTEX_NAME", "AutoClicker_SingleInstance_Mutex")
SINGLE_INSTANCE_LOCK_FILE = os.path.expanduser("~/.autoclicker.lock")
WINDOW_TITLE = os.environ.get(
    "AUTOCLICKER_WINDOW_TITLE", "桌面自动点击工具 v2.0.2 (Python 3.14)")
IS_SINGLE_INSTANCE = True
EXISTING_WINDOW_HWND = None
SINGLE_INSTANCE_LOCK_FD = None

# Windows 单实例检查
if IS_WINDOWS and HAS_WIN32GUI:
    try:
        import win32event
        import win32security
        import pywintypes
        
        try:
            EXISTING_WINDOW_HWND = win32gui.FindWindow(None, WINDOW_TITLE)
        except Exception:
            EXISTING_WINDOW_HWND = None
            
        if EXISTING_WINDOW_HWND:
            IS_SINGLE_INSTANCE = False
        else:
            sa = win32security.SECURITY_ATTRIBUTES()
            sa.bInheritHandle = False
            
            try:
                mutex = win32event.CreateMutex(sa, False, SINGLE_INSTANCE_MUTEX_NAME)
                if win32api.GetLastError() == ERROR_ALREADY_EXISTS:
                    IS_SINGLE_INSTANCE = False
                    try:
                        EXISTING_WINDOW_HWND = win32gui.FindWindow(None, WINDOW_TITLE)
                    except Exception:
                        EXISTING_WINDOW_HWND = None
            except pywintypes.error:
                IS_SINGLE_INSTANCE = False
            
    except ImportError:
        pass

# Linux 单实例检查（使用文件锁）
elif IS_LINUX:
    try:
        import fcntl
        
        # 检查锁文件是否存在且被占用
        if os.path.exists(SINGLE_INSTANCE_LOCK_FILE):
            try:
                with open(SINGLE_INSTANCE_LOCK_FILE, 'r') as f:
                    try:
                        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        # 可以获取锁，说明没有其他进程在运行
                        fcntl.flock(f, fcntl.LOCK_UN)
                    except IOError:
                        # 无法获取锁，说明有其他进程在运行
                        IS_SINGLE_INSTANCE = False
            except OSError:
                pass
        
        # 创建锁文件
        if IS_SINGLE_INSTANCE:
            SINGLE_INSTANCE_LOCK_FD = open(SINGLE_INSTANCE_LOCK_FILE, 'w')
            try:
                fcntl.flock(SINGLE_INSTANCE_LOCK_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)
                SINGLE_INSTANCE_LOCK_FD.write(str(os.getpid()))
                SINGLE_INSTANCE_LOCK_FD.flush()
            except OSError:
                IS_SINGLE_INSTANCE = False
                
    except ImportError:
        print("fcntl模块未安装，Linux单实例检查功能将不可用")
    except Exception as e:
        print(f"Linux单实例检查失败: {e}")


class AutoClicker:
    def __init__(self, root):
        self.root = root
        self.root.title(WINDOW_TITLE)
        self._init_dpi_awareness()

        # 窗口尺寸按 DPI 缩放（F-10 / CX-05）：720x800 是 96dpi 基准；
        # 高 DPI 下若仍用固定物理像素，字体会把按钮挤成 1px（T05247 实测 200% 裁切）。
        dpi_ratio = max(1.0, min(getattr(self, '_dpi_scale', 1.3333) / 1.3333, 2.0))
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        win_w = min(int(720 * dpi_ratio), int(screen_w * 0.9))
        win_h = min(int(800 * dpi_ratio), int(screen_h * 0.9))
        self.root.geometry("%dx%d" % (win_w, win_h))
        self._min_w = min(int(700 * dpi_ratio), win_w)
        self._min_h = min(int(760 * dpi_ratio), win_h)
        self.root.minsize(self._min_w, self._min_h)
        
        self.is_running = False
        self.click_thread = None
        self._region_selector = None
        self._region_starting = False
        self.config_file = os.path.expanduser("~/.auto_clicker_config_py3.json")
        # 首启检测（6.9.1 引导与预设配置）：配置不存在即视为首次运行
        self.first_run = not os.path.exists(self.config_file)
        # FR-L01：会话输入能力探测（Wayland 降级，须早于 setup_ui 建按钮）
        self.input_ok, self.input_session, self.input_reason = detect_input_backend()

        # P0 安全/体验状态默认值（CX-01 / CX-02 / CX-04）
        self.countdown_cancelled = False
        self.startup_countdown = 3
        self.click_limit = 0
        self.duration_limit = 0
        self.failsafe_enabled = False
        self.target_window_cache = ''
        self._window_mismatch_active = False
        self.start_time = time.time()

        # P1 功能扩展状态默认值（FN-01 / FN-02 / CX-07 / FN-03）
        self.click_button = 'left'
        self.hold_ms = 10
        self.interval_unit = 's'
        self._interval_change_event = threading.Event()
        self._interval_hot_after_id = None
        self.jitter_pct = 0
        self.use_multi_points = False
        self.multi_points = []

        # P2 状态可视化默认值（UI-03）
        self.success_count = 0
        self.fail_count = 0
        self._runtime_after_id = None
        self._log_buffer = []  # [(text, level)] 全量日志缓冲（UI-04 过滤用）
        self._pending_logs = []  # 磁盘日志尚未初始化时的待落盘消息
        self._file_logger = None
        self._log_filter = ''
        self._log_collapsed = False
        # Tk 只能在主线程访问：后台线程通过该队列把 UI 回调交回主线程执行。
        # 原实现 _ui() 直接 root.after(...)，主线程 join 点击线程时会互相等待，
        # 导致急停后点击线程卡死（T05212/T05215/T05229 实测）。
        self._ui_queue = queue.Queue()
        # REQ-004 运行统计：最近一次会话快照（供导出）
        self.last_run_stats = {
            'timestamp': '', 'click_count': 0, 'success_count': 0,
            'fail_count': 0, 'runtime_seconds': 0.0,
            'interval_seconds': 0.0, 'mode': '', 'button': '',
        }

        self.load_config()
        self._init_theme()
        self._init_ui_fonts()
        self.setup_ui()
        self.root.after(30, self._poll_ui_queue)
        # 磁盘日志延后到窗口可见后：logging.handlers 会拉入 shutil/socket/pickle，
        # 冷启动不必为首屏承担该导入成本；此前日志先入 _pending_logs，初始化后补写。
        self.root.after(250, self.setup_logging)
        # 补记 DPI 诊断（此时日志/UI 设施已就绪）
        self.log_message("DPI 适配：系统缩放 %.2f，UI 字体基准 %dpt（不做二次放大）" % (
            getattr(self, '_dpi_scale', 1.0), getattr(self, 'ui_font_size', 9)))
        self._apply_theme()
        # FR-L01：无可用输入后端时禁用启动（按钮 + 热键通道由 start_clicking 统一守卫兜底）
        if not self.input_ok:
            try:
                self.start_btn.config(state=tk.DISABLED)
            except Exception:
                pass
            self.log_message("Wayland 降级：启动已禁用（会话=%s）" % self.input_session)
        # 热键/托盘初始化延迟到主窗口首次显示后：keyboard 全局钩子导入约 1.3 秒，
        # 不应阻塞 NFR-05 的启动时间；窗口先可见，再在空闲回调里注册。
        self._hotkey_queue = queue.Queue()
        self.root.after(300, self.setup_hotkeys)
        self.root.after(300, self._poll_hotkey_queue)
        self.root.after(450, self.setup_tray_icon)
        # 图标绘制约 0.5 秒（PIL 3 个图标）：窗口先可见，再在空闲回调补图标
        self.root.after(250, self._load_action_icons)
        if self.theme_mode == 'system':
            self._poll_system_theme()
        
        # 6.9.1 引导与预设配置：首次运行写入推荐安全预设并弹出引导
        if self.first_run:
            self._apply_first_run_preset()
            self.root.after(800, self._show_first_run_guidance)
        
        # 关闭按钮直接退出程序
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # 防锁屏保活：初始化状态，并根据默认/已保存配置自动启动（独立于点击运行）
        self.keepalive_running = threading.Event()
        self.keepalive_stop_event = threading.Event()
        self.keepalive_thread = None
        if self.prevent_sleep_var.get():
            self.start_keepalive()
        
    def setup_logging(self):
        """CX-10：初始化磁盘日志（RotatingFileHandler，单文件 5MB × 5 备份）"""
        try:
            import logging
            from logging.handlers import RotatingFileHandler
            self.log_dir = os.path.expanduser("~/.auto_clicker_logs")
            os.makedirs(self.log_dir, exist_ok=True)
            log_file = os.path.join(self.log_dir, "autoclicker.log")
            self._file_logger = logging.getLogger("autoclicker")
            self._file_logger.setLevel(logging.INFO)
            # 避免重复添加 handler（多次调用时）
            if not self._file_logger.handlers:
                fh = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024,
                                         backupCount=5, encoding='utf-8')
                fh.setFormatter(logging.Formatter(
                    "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
                self._file_logger.addHandler(fh)
            # 兼容旧控制台提示
            self._file_logger.info("自动点击工具启动 (Python 3.14)")
            pending = getattr(self, '_pending_logs', [])
            for msg in pending:
                self._file_logger.info(msg)
            pending.clear()
        except Exception as e:
            # 日志初始化失败不应阻断程序启动
            self._file_logger = None
            print("初始化日志失败: " + str(e))

    def _backup_config_before_migration(self):
        """CX-09：迁移/降级前备份原配置，避免旧配置丢失（PRD FR-G02）。"""
        try:
            if not os.path.exists(self.config_file):
                return None
            import shutil
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = self.config_file + ".v1-backup-" + stamp
            shutil.copy2(self.config_file, backup)
            self._migration_backup_path = backup
            print("配置迁移前已备份: " + backup)
            return backup
        except Exception as e:
            print("配置迁移备份失败: " + str(e))
            return None

    def load_config(self):
        default_config = {
            'interval_seconds': 10,
            'click_mode': 'random',
            'click_area': {'x': 0, 'y': 0, 'width': 1920, 'height': 1080},
            'prevent_sleep': True,
            'mouse_follow_enabled': True,  # 鼠标跟随功能
            'mouse_move_speed': 0.1,  # 鼠标移动速度 (0.0-1.0)
            'mouse_move_only': False,  # 只移动不点击
            # P0 安全与体验止血（CX-02 / CX-04 / CX-06）
            'startup_countdown': 3,  # 启动倒计时（秒，0-5）
            'click_limit': 0,  # 点击次数上限（0 表示无限）
            'duration_limit': 0,  # 运行时长上限（分钟，0 表示无限）
            'failsafe_enabled': False,  # 鼠标位移即停
            'target_window_keyword': '',  # FR-E03 前台目标窗口关键字（空=不校验）
            'close_to_tray': True,  # 关闭窗口最小化到托盘（否则直接退出）
            # P1 功能扩展（FN-01 / FN-02 / CX-07 / CX-08 / CX-11 / FN-03）
            'click_button': 'left',  # 鼠标按键：left/right/middle/double
            'hold_ms': 10,  # 按住时长（毫秒）
            'interval_unit': 's',  # 间隔单位：s 表示秒，ms 表示毫秒
            'jitter_pct': 0,  # 随机抖动百分比（0 表示关闭）
            'hotkey_start': 'f6',  # 启动/停止热键（可自定义）
            'hotkey_emergency': 'f8',  # 紧急停止热键（可自定义）
            'autostart': False,  # 开机自启
            'use_multi_points': False,  # 使用多点位序列
            'multi_points': [],  # 多点位坐标列表 [{'x':, 'y':}, ...]
            'theme_mode': 'light',  # 主题：light / dark / system（TH-01/TH-03）
            'config_version': 2  # 配置 schema 版本（CX-09 迁移用）
        }
        
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
                try:
                    raw_version = int(self.config.get('config_version', 0) or 0)
                except (TypeError, ValueError, AttributeError):
                    raw_version = 0
                if raw_version < 2:
                    self._backup_config_before_migration()
                for key in default_config:
                    if key not in self.config:
                        self.config[key] = default_config[key]
            else:
                self.config = default_config
        except Exception as e:
            print("加载配置失败: " + str(e))
            self._backup_config_before_migration()
            self.config = default_config
            
        # 配置迁移（CX-09）：补齐 schema 版本与配置方案容器
        try:
            if 'config_version' not in self.config:
                self.config['config_version'] = 2
            if 'profiles' not in self.config or not isinstance(self.config['profiles'], dict):
                self.config['profiles'] = {}
            if 'current_profile' not in self.config:
                self.config['current_profile'] = None
        except Exception:
            pass

    # ==================== 6.11.2 DPI 适配 / UI 字体基准 ====================
    def _init_dpi_awareness(self):
        """进程级 DPI 感知已在 main() 中、创建 Tk 根窗口之前设置（保证点击坐标与
        物理像素一致）。此处只记录 tk 渲染比例供诊断/日志使用，不再据此放大字体。

        注意：Windows 上 `tk scaling` 是「每点像素数」（96dpi 默认 1.333、200% 缩放为 2.0），
        Tk 的 point-size 字体本就会随它渲染。若再按 scale 手工放大字号，等于二次放大。
        """
        try:
            try:
                scale = float(self.root.tk.call('tk', 'scaling'))
            except Exception:
                scale = 1.0
            self._dpi_scale = scale
            # 此处日志设施尚未初始化（setup_logging/setup_ui 在后），仅控制台留痕；
            # UI/磁盘日志在 __init__ 中 setup_ui() 之后补记
            print("[DPI] 系统缩放 %.2f（字体基准由 _init_ui_fonts 统一设置）" % scale)
        except Exception:
            self._dpi_scale = 1.0

    def _init_ui_fonts(self):
        """统一 tk/ttk 控件与 Combobox 弹层的字体基准；须在 _init_theme() 之后调用。

        旧实现用 `option_add('*Font', '微软雅黑 %d' % (10 * scale))` 把全局默认字体
        放大到 16pt，而该 option 只命中「未显式指定 font」的控件（ttk 按钮、Combobox
        输入区与下拉 Listbox、Entry），源码里显式 9~11pt 的 Label 不受影响，于是出现
        「标签小、下拉/按钮巨大」的字号割裂，并撑爆按钮导致文字裁切。
        """
        from tkinter import font as tkfont
        family, size = '微软雅黑', 9
        self.ui_font_size = size
        self.ui_font = (family, size)
        font_str = '%s %d' % (family, size)
        try:
            # 1) named fonts：ttk 默认样式、菜单、Combobox 弹层 Listbox 均引用它们
            for name in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont'):
                try:
                    tkfont.nametofont(name).configure(family=family, size=size)
                except Exception:
                    pass
            # 2) option database：未显式指定 font 的 tk 控件 + 下拉弹层
            self.root.option_add('*Font', font_str)
            self.root.option_add('*Listbox.font', font_str)
            self.root.option_add('*TCombobox*Listbox.font', font_str)
            self.root.option_add('*Menu.font', font_str)
        except Exception:
            pass
        self._apply_ttk_fonts()

    def _apply_ttk_fonts(self):
        """按统一基准覆盖 ttk 样式字体；主题切换后须重调（theme_use 会重置样式）。"""
        from tkinter import ttk
        family, size = getattr(self, 'ui_font', None) or ('微软雅黑', 9)
        try:
            style = ttk.Style()
            for name in ('TButton', 'TCombobox', 'TEntry', 'TLabel', 'TCheckbutton',
                         'TRadiobutton', 'TNotebook.Tab', 'TLabelframe.Label',
                         'Treeview', 'TSpinbox'):
                try:
                    style.configure(name, font=(family, size))
                except Exception:
                    pass
            try:
                style.configure('Treeview.Heading', font=(family, size, 'bold'))
            except Exception:
                pass
        except Exception:
            pass

    # ==================== P2 矢量图标工厂（UI-02，无 PIL 时降级为文本） ====================
    def make_icon(self, name, size=16, color='#333333'):
        """生成单色矢量图标的 tk.PhotoImage；无 PIL 时返回 None（调用方降级为文本）"""
        try:
            from PIL import Image, ImageDraw, ImageTk
            img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            c = color
            if name == 'play':
                d.polygon([(size*0.30, size*0.20), (size*0.30, size*0.80), (size*0.80, size*0.50)], fill=c)
            elif name == 'stop':
                d.rectangle([size*0.28, size*0.28, size*0.72, size*0.72], fill=c)
            elif name == 'target':
                d.ellipse([size*0.18, size*0.18, size*0.82, size*0.82], outline=c, width=2)
                d.line([(size*0.5, size*0.10), (size*0.5, size*0.90)], fill=c, width=2)
                d.line([(size*0.10, size*0.5), (size*0.90, size*0.5)], fill=c, width=2)
            elif name == 'gear':
                d.ellipse([size*0.30, size*0.30, size*0.70, size*0.70], outline=c, width=2)
                for a in range(0, 360, 45):
                    import math
                    r = math.radians(a)
                    d.line([(size*0.5 + 0.30*size*math.cos(r), size*0.5 + 0.30*size*math.sin(r)),
                            (size*0.5 + 0.42*size*math.cos(r), size*0.5 + 0.42*size*math.sin(r))], fill=c, width=2)
            elif name == 'clipboard':
                d.rectangle([size*0.30, size*0.22, size*0.70, size*0.80], outline=c, width=2)
                d.rectangle([size*0.40, size*0.14, size*0.60, size*0.26], outline=c, width=2)
            elif name == 'broom':
                d.line([(size*0.25, size*0.65), (size*0.70, size*0.25)], fill=c, width=3)
                d.line([(size*0.30, size*0.78), (size*0.72, size*0.40)], fill=c, width=3)
            elif name == 'funnel':
                d.line([(size*0.20, size*0.25), (size*0.80, size*0.25), (size*0.55, size*0.55), (size*0.55, size*0.80), (size*0.45, size*0.80), (size*0.45, size*0.55)], fill=c, width=2, closed=True)
            elif name == 'folder':
                d.rectangle([size*0.20, size*0.35, size*0.80, size*0.75], outline=c, width=2)
                d.line([(size*0.20, size*0.35), (size*0.35, size*0.25), (size*0.55, size*0.25), (size*0.55, size*0.35)], fill=c, width=2)
            elif name == 'shield':
                d.polygon([(size*0.5, size*0.15), (size*0.82, size*0.28), (size*0.82, size*0.55),
                           (size*0.5, size*0.85), (size*0.18, size*0.55), (size*0.18, size*0.28)], outline=c, width=2)
            elif name == 'clock':
                d.ellipse([size*0.18, size*0.18, size*0.82, size*0.82], outline=c, width=2)
                d.line([(size*0.5, size*0.5), (size*0.5, size*0.30)], fill=c, width=2)
                d.line([(size*0.5, size*0.5), (size*0.68, size*0.5)], fill=c, width=2)
            else:
                return None
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    # ==================== P2 主题系统（TH-01 / TH-02 / TH-03） ====================
    def _init_theme(self):
        """初始化主题：语义化调色板 + 可选接入 ttkbootstrap + 读取持久化主题"""
        # TH-02：主色/成功/危险/警告等语义化变量，集中定义，避免散落十六进制
        self.THEMES = {
            'light': {
                'bg': '#ffffff', 'fg': '#212529', 'muted': '#6c757d',
                'primary': '#0056b3', 'success': '#1e7e34', 'danger': '#b02a37',
                'warning': '#8a4b00', 'surface': '#f8f9fa', 'border': '#868e96',
                'on_primary': '#ffffff', 'on_success': '#ffffff',
                'on_danger': '#ffffff', 'on_warning': '#ffffff', 'on_muted': '#ffffff',
            },
            'dark': {
                'bg': '#212529', 'fg': '#e9ecef', 'muted': '#adb5bd',
                'primary': '#4a90d9', 'success': '#2ecc71', 'danger': '#f16c6c',
                'warning': '#e67e22', 'surface': '#2b3035', 'border': '#6c757d',
                'on_primary': '#0b0f14', 'on_success': '#0b0f14',
                'on_danger': '#0b0f14', 'on_warning': '#0b0f14', 'on_muted': '#0b0f14',
            },
        }
        self.theme_mode = self.config.get('theme_mode', 'light')
        self._ttkb_style = None
        # TH-01：可选接入 ttkbootstrap（缺失则降级为纯 ttk + 手动语义配色）
        try:
            import ttkbootstrap as ttkb  # noqa
            self._ttkb_style = ttkb.Style(theme='cosmo')
        except Exception:
            self._ttkb_style = None
        self._current_palette = self._resolve_palette()

    def _color(self, key):
        return self._current_palette.get(key, '#000000')

    def _on_color(self, key):
        """语义色背景上的文字色：浅色主题白字、深色主题深字，保证 ≥4.5:1。"""
        return self._current_palette.get('on_' + key, '#ffffff')

    def _shade(self, hex_color, factor=0.85):
        """按比例调暗十六进制色，用于 activebackground（TH-02）"""
        try:
            h = hex_color.lstrip('#')
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            r = max(0, int(r * factor)); g = max(0, int(g * factor)); b = max(0, int(b * factor))
            return '#%02x%02x%02x' % (r, g, b)
        except Exception:
            return hex_color

    def _system_is_dark(self):
        """检测系统是否深色模式（Windows 注册表；其他平台默认浅色）"""
        try:
            if IS_WINDOWS:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
                val = winreg.QueryValueEx(key, "AppsUseLightTheme")[0]
                return val == 0
        except Exception:
            pass
        return False

    def _resolve_palette(self):
        mode = self.theme_mode
        if mode == 'system':
            mode = 'dark' if self._system_is_dark() else 'light'
        return self.THEMES.get(mode, self.THEMES['light'])

    def _apply_ttkbootstrap_theme(self):
        """切换 ttkbootstrap 主题（TH-01）；未安装或切换失败时静默降级。"""
        if self._ttkb_style is None:
            return
        try:
            effective = self.theme_mode
            if effective == 'system':
                effective = 'dark' if self._system_is_dark() else 'light'
            tb_name = 'darkly' if effective == 'dark' else 'cosmo'
            self._ttkb_style.theme_use(tb_name)
        except Exception:
            pass

    def _recolor_action_buttons(self, pal):
        """按语义色重着色操作按钮（TH-02）。"""
        button_colors = (
            ('start_btn', 'success'),
            ('stop_btn', 'danger'),
            ('test_btn', 'primary'),
            ('set_area_btn', 'muted'),
        )
        for attr, key in button_colors:
            btn = getattr(self, attr, None)
            if btn:
                on_key = pal.get('on_' + key, '#ffffff')
                btn.configure(bg=pal[key], activebackground=self._shade(pal[key]),
                              fg=on_key, activeforeground=on_key)
        icon_specs = (
            ('start_btn', '_icon_play', 'play', 18, 'success'),
            ('stop_btn', '_icon_stop', 'stop', 18, 'danger'),
            ('test_btn', '_icon_target', 'target', 16, 'primary'),
        )
        if not getattr(self, '_icons_ready', False):
            return
        for btn_attr, icon_attr, kind, size, key in icon_specs:
            btn = getattr(self, btn_attr, None)
            if not btn:
                continue
            icon = self.make_icon(kind, size, pal.get('on_' + key, '#ffffff'))
            if icon:
                setattr(self, icon_attr, icon)
                btn.configure(image=icon, compound=tk.LEFT)

    def _load_action_icons(self):
        """窗口可见后补绘操作按钮图标，避免 PIL 绘制阻塞首屏。"""
        if getattr(self, '_icons_ready', False):
            return
        self._icons_ready = True
        self._recolor_action_buttons(self._current_palette)

    def _apply_ttk_theme_styles(self, pal):
        """TH-01/TH-02：把语义调色板落到 ttk 全局样式，深色主题不能只改变量。

        纯 ttk（无 ttkbootstrap）时，vista 主题忽略多数颜色选项；深色模式改用
        内置 clam 主题承载颜色，浅色模式回到 vista（非 Windows 用 clam）。
        """
        try:
            style = ttk.Style(self.root)
            dark = pal.get('bg') == self.THEMES['dark']['bg']
            available = set(style.theme_names())
            if dark:
                if 'clam' in available:
                    style.theme_use('clam')
            elif IS_WINDOWS and 'vista' in available:
                style.theme_use('vista')
            elif 'clam' in available:
                style.theme_use('clam')

            common = {
                'TFrame': {'background': pal['bg']},
                'TLabelframe': {'background': pal['bg'], 'foreground': pal['fg'],
                                'bordercolor': pal['border']},
                'TLabelframe.Label': {'background': pal['bg'], 'foreground': pal['fg']},
                'TLabel': {'background': pal['bg'], 'foreground': pal['fg']},
                'TButton': {'background': pal['surface'], 'foreground': pal['fg'],
                            'bordercolor': pal['border']},
                'TEntry': {'fieldbackground': pal['surface'], 'foreground': pal['fg'],
                           'insertcolor': pal['fg'], 'bordercolor': pal['border']},
                'TCombobox': {'fieldbackground': pal['surface'], 'foreground': pal['fg'],
                              'background': pal['surface'], 'arrowcolor': pal['fg'],
                              'bordercolor': pal['border'],
                              'selectbackground': pal['primary'], 'selectforeground': 'white'},
                'TCheckbutton': {'background': pal['bg'], 'foreground': pal['fg'],
                                 'indicatorbackground': pal['surface'],
                                 'indicatorforeground': pal['fg'],
                                 'bordercolor': pal['border']},
                'TRadiobutton': {'background': pal['bg'], 'foreground': pal['fg'],
                                 'indicatorbackground': pal['surface'],
                                 'bordercolor': pal['border']},
                'TScale': {'background': pal['bg'], 'troughcolor': pal['surface'],
                           'bordercolor': pal['border']},
                'TProgressbar': {'background': pal['primary'], 'troughcolor': pal['surface'],
                                 'bordercolor': pal['border']},
                'TScrollbar': {'background': pal['surface'], 'troughcolor': pal['bg'],
                               'arrowcolor': pal['fg'], 'bordercolor': pal['border'],
                               'darkcolor': pal['surface'], 'lightcolor': pal['bg']},
                'Vertical.TScrollbar': {'background': pal['surface'], 'troughcolor': pal['bg'],
                                        'arrowcolor': pal['fg'], 'bordercolor': pal['border'],
                                        'darkcolor': pal['surface'], 'lightcolor': pal['bg']},
                'Horizontal.TScrollbar': {'background': pal['surface'], 'troughcolor': pal['bg'],
                                          'arrowcolor': pal['fg'], 'bordercolor': pal['border'],
                                          'darkcolor': pal['surface'], 'lightcolor': pal['bg']},
                'Treeview': {'background': pal['surface'], 'fieldbackground': pal['surface'],
                             'foreground': pal['fg'], 'bordercolor': pal['border']},
                'Treeview.Heading': {'background': pal['bg'], 'foreground': pal['fg']},
            }
            for name, opts in common.items():
                try:
                    style.configure(name, **opts)
                except Exception:
                    pass
            for name, opts in (
                ('TCombobox', {'fieldbackground': [('readonly', pal['surface'])],
                               'foreground': [('readonly', pal['fg'])],
                               'background': [('readonly', pal['surface'])],
                               'arrowcolor': [('readonly', pal['fg'])]}),
                ('TEntry', {'fieldbackground': [('disabled', pal['surface'])]}),
                ('TCheckbutton', {'background': [('active', pal['bg'])],
                                  'foreground': [('active', pal['fg'])]}),
                ('TButton', {'background': [('active', pal['bg'])],
                             'foreground': [('active', pal['fg'])]}),
            ):
                try:
                    style.map(name, **opts)
                except Exception:
                    pass
        except Exception:
            pass

    def _recolor_semantic_labels(self, pal):
        """TH-02：主题切换后同步语义色标签/画布，避免残留上一主题的硬编码色。"""
        try:
            status_key = 'success' if getattr(self, 'is_running', False) else 'danger'
            pairs = (
                ('status_text_label', status_key),
                ('sb_status_label', status_key),
                ('sb_success_label', 'success'),
                ('sb_fail_label', 'danger'),
                ('sb_runtime_label', 'primary'),
                ('sb_countdown_label', 'muted'),
                ('area_label', 'primary'),
                ('next_click_label', 'primary'),
                ('click_count_label', 'success'),
                ('mouse_speed_label', 'primary'),
            )
            for attr, key in pairs:
                widget = getattr(self, attr, None)
                if widget is not None:
                    try:
                        widget.configure(foreground=pal[key])
                    except Exception:
                        pass
            canvas = getattr(self, 'main_canvas', None)
            if canvas is not None:
                canvas.configure(bg=pal['bg'], highlightbackground=pal['bg'])
            indicator = getattr(self, 'status_indicator', None)
            if indicator is not None:
                indicator.configure(bg=pal['bg'])
        except Exception:
            pass

    def _apply_theme(self):
        """运行时应用主题：切换 ttk 主题 + 重着色语义化控件（TH-01/TH-02）"""
        try:
            pal = self._resolve_palette()
            self._current_palette = pal
            self._apply_ttkbootstrap_theme()
            self._apply_ttk_theme_styles(pal)
            # theme_use 会重置 ttk 样式字体，切换后需按统一基准重新覆盖
            self._apply_ttk_fonts()
            # 语义化重着色已知 tk/ttk 控件（TH-02）
            self._recolor_action_buttons(pal)
            self._recolor_semantic_labels(pal)
            # 托盘图标跟随浅/深主题刷新（T05257）
            self._refresh_tray_icon()
            if getattr(self, 'log_text', None):
                try:
                    self.log_text.configure(bg=pal['surface'], fg=pal['fg'])
                except Exception:
                    pass
            try:
                self.root.configure(bg=pal['bg'])
            except Exception:
                pass
        except Exception:
            pass

    def on_theme_change(self, mode):
        """切换主题并持久化（TH-03）"""
        try:
            if mode not in ('light', 'dark', 'system'):
                return
            self.theme_mode = mode
            self.config['theme_mode'] = mode
            self.save_config()
            if getattr(self, 'theme_var', None) is not None:
                self.theme_var.set({'light': '浅色', 'dark': '深色', 'system': '跟随系统'}.get(mode, '浅色'))
            self._apply_theme()
            # 跟随系统模式：启动轮询，随系统深浅色变化
            if mode == 'system':
                self._poll_system_theme()
        except Exception:
            pass

    def on_theme_change_ui(self, event=None):
        mapping = {'浅色': 'light', '深色': 'dark', '跟随系统': 'system'}
        self.on_theme_change(mapping.get(self.theme_var.get(), 'light'))

    def _poll_system_theme(self):
        """system 模式下每 5s 检测系统深浅色变化并应用（TH-03）"""
        try:
            if self.theme_mode == 'system':
                self._apply_theme()
                self.root.after(5000, self._poll_system_theme)
        except Exception:
            pass

    def save_config(self):
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(MSG_SAVE_CONFIG_FAILED + str(e))
    
    def save_config_if_running(self):
        """保存配置，如果程序正在运行则保存当前配置"""
        try:
            self.config['interval_seconds'] = int(self.interval_var.get())
            self.config['prevent_sleep'] = self.prevent_sleep_var.get()
            self.config['mouse_follow_enabled'] = self.mouse_follow_var.get()
            self.config['mouse_move_speed'] = float(self.mouse_speed_var.get())
            self.config['mouse_move_only'] = self.mouse_move_only_var.get()
            # P0 安全与体验参数持久化（CX-02 / CX-04 / CX-06）
            if hasattr(self, 'countdown_var'):
                self.config['startup_countdown'] = int(self.countdown_var.get() or 0)
                self.config['click_limit'] = int(self.click_limit_var.get() or 0)
                self.config['duration_limit'] = int(self.duration_limit_var.get() or 0)
                self.config['failsafe_enabled'] = self.failsafe_var.get()
                self.config['target_window_keyword'] = self.target_window_var.get().strip()
                self.config['close_to_tray'] = self.close_to_tray_var.get()
            self.save_config()
        except Exception as e:
            print(MSG_SAVE_CONFIG_FAILED + str(e))
    
    def on_prevent_sleep_changed(self):
        """防止系统锁屏选项改变时的回调（即时启停后台保活）"""
        try:
            self.config['prevent_sleep'] = self.prevent_sleep_var.get()
            self.save_config()
            if self.prevent_sleep_var.get():
                self.start_keepalive()
                self.log_message("已启用防止系统锁屏")
            else:
                self.stop_keepalive()
                self.allow_system_sleep()
                self.log_message("已禁用防止系统锁屏")
        except Exception as e:
            print(MSG_SAVE_CONFIG_FAILED + str(e))

    def on_mouse_follow_changed(self):
        """鼠标跟随选项改变时的回调"""
        try:
            self.config['mouse_follow_enabled'] = self.mouse_follow_var.get()
            self.save_config()
            if self.mouse_follow_var.get():
                self.log_message("已启用鼠标跟随移动")
            else:
                self.log_message("已禁用鼠标跟随移动")
        except Exception as e:
            print(MSG_SAVE_CONFIG_FAILED + str(e))
            
    def on_mouse_move_only_changed(self):
        """只移动不点击选项改变时的回调"""
        try:
            self.config['mouse_move_only'] = self.mouse_move_only_var.get()
            self.save_config()
            if self.mouse_move_only_var.get():
                # 自动启用鼠标跟随
                self.mouse_follow_var.set(True)
                self.config['mouse_follow_enabled'] = True
                self.log_message("已启用只移动不点击模式（鼠标跟随已自动启用）")
            else:
                self.log_message("已禁用只移动不点击模式")
        except Exception as e:
            print(MSG_SAVE_CONFIG_FAILED + str(e))

    def on_close_behavior_changed(self):
        """关闭行为选项改变时的回调（CX-06）"""
        try:
            self.config['close_to_tray'] = self.close_to_tray_var.get()
            self.save_config()
            self.log_message("关闭行为已设为：" + ("最小化到托盘" if self.close_to_tray_var.get() else "直接退出"))
        except Exception as e:
            print("保存关闭行为失败: " + str(e))

    # ==================== P1 辅助方法 ====================
    def _refresh_multi_point_listbox(self):
        try:
            self.multi_point_listbox.delete(0, tk.END)
            for p in self.config.get('multi_points', []):
                self.multi_point_listbox.insert(tk.END, f"({p['x']}, {p['y']})")
        except Exception:
            pass

    def _add_point(self, x, y):
        try:
            self.config.setdefault('multi_points', []).append({'x': int(x), 'y': int(y)})
            self.save_config()
            self._refresh_multi_point_listbox()
            self.log_message(f"已添加多点位：({int(x)}, {int(y)})")
        except Exception as e:
            self.log_message("添加多点位失败: " + str(e))

    def pick_coordinate(self):
        """FN-04：3 秒后拾取当前光标坐标"""
        try:
            self.log_message("3 秒后拾取当前光标坐标…（请勿移动鼠标）")
            def _pick():
                time.sleep(3)
                try:
                    x, y = get_cursor_pos()
                    self.root.after(0, lambda: self._add_point(x, y))
                except Exception as e:
                    self.root.after(0, lambda: self.log_message("拾取失败: " + str(e)))
            threading.Thread(target=_pick, daemon=True).start()
        except Exception as e:
            self.log_message("拾取失败: " + str(e))

    def add_manual_point(self):
        try:
            x = int(self.mp_x_var.get())
            y = int(self.mp_y_var.get())
            self._add_point(x, y)
        except ValueError:
            messagebox.showerror("错误", "请输入有效的整数坐标")

    def remove_point(self):
        try:
            sel = self.multi_point_listbox.curselection()
            if not sel:
                return
            idx = sel[0]
            pts = self.config.get('multi_points', [])
            if 0 <= idx < len(pts):
                pts.pop(idx)
                self.save_config()
                self._refresh_multi_point_listbox()
        except Exception as e:
            self.log_message("删除多点位失败: " + str(e))

    def clear_points(self):
        self.config['multi_points'] = []
        self.save_config()
        self._refresh_multi_point_listbox()
        self.log_message("已清空多点位列表")

    def on_hotkey_apply(self):
        """CX-08：校验冲突并重新注册热键"""
        try:
            start_k = self.hotkey_start_var.get().strip().lower()
            emer_k = self.hotkey_emergency_var.get().strip().lower()
            if not start_k or not emer_k:
                messagebox.showerror("错误", "热键不能为空")
                return
            if start_k == emer_k:
                messagebox.showerror("冲突", "启动键与紧急停止键不能相同")
                return
            if start_k == 'esc' or emer_k == 'esc':
                messagebox.showerror("冲突", "Esc 为保留紧急停止键，不可用作启动/停止键")
                return
            self.config['hotkey_start'] = start_k
            self.config['hotkey_emergency'] = emer_k
            self.save_config()
            self._register_hotkeys()
            self.log_message(f"热键已应用：启动={start_k}，紧急停止={emer_k}（Esc 始终为紧急停止）")
        except Exception as e:
            messagebox.showerror("错误", "应用热键失败: " + str(e))

    def on_autostart_changed(self):
        """CX-11：开机自启开关"""
        self.set_autostart(self.autostart_var.get())

    @staticmethod
    def _autostart_executable():
        """返回开机自启应指向的可执行路径（打包后为 exe，源码运行为脚本）。"""
        if getattr(sys, 'frozen', False):
            return os.path.abspath(sys.argv[0])
        return os.path.abspath(__file__)

    def _set_autostart_windows(self, enable):
        """写入/删除 Windows 注册表 Run 项。"""
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run",
                             0, winreg.KEY_SET_VALUE)
        try:
            if enable:
                winreg.SetValueEx(key, "AutoClicker", 0, winreg.REG_SZ,
                                  '"' + self._autostart_executable() + '"')
            else:
                try:
                    winreg.DeleteValue(key, "AutoClicker")
                except FileNotFoundError:
                    pass
        finally:
            winreg.CloseKey(key)

    def _set_autostart_linux(self, enable):
        """写入/删除 Linux autostart desktop 文件。"""
        adir = os.path.expanduser("~/.config/autostart")
        os.makedirs(adir, exist_ok=True)
        desk = os.path.join(adir, "autoclicker.desktop")
        if enable:
            with open(desk, 'w', encoding='utf-8') as f:
                f.write("[Desktop Entry]\nType=Application\nName=AutoClicker\n"
                        "Exec=\"%s\"\nHidden=false\nX-GNOME-Autostart-enabled=true\n"
                        % self._autostart_executable())
        elif os.path.exists(desk):
            os.remove(desk)

    def set_autostart(self, enable):
        try:
            if IS_WINDOWS:
                self._set_autostart_windows(enable)
            elif IS_LINUX:
                self._set_autostart_linux(enable)
            else:
                messagebox.showinfo("提示", "当前平台不支持开机自启")
                return
            self.config['autostart'] = enable
            self.save_config()
            self.log_message("开机自启已" + ("开启" if enable else "关闭"))
        except Exception as e:
            self.log_message("设置开机自启失败: " + str(e))
            messagebox.showerror("错误", "设置开机自启失败: " + str(e))

    def open_log_dir(self):
        """CX-10：打开日志目录"""
        try:
            d = getattr(self, 'log_dir', os.path.expanduser("~/.auto_clicker_logs"))
            if not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            if IS_WINDOWS:
                os.startfile(d)
            elif IS_LINUX:
                import subprocess
                subprocess.Popen(['xdg-open', d])
            else:
                messagebox.showinfo("日志目录", d)
        except Exception as e:
            self.log_message("打开日志目录失败: " + str(e))

    # ==================== 6.9.1 引导与预设配置 ====================
    def _apply_first_run_preset(self):
        """首次运行：落盘推荐安全预设，并预置一个「推荐安全」配置方案用于引导。"""
        try:
            # 以当前默认配置（已含安全止血参数）作为基线落盘
            self.save_config()
            safe = {
                'interval_seconds': 10, 'click_mode': 'random', 'prevent_sleep': True,
                'startup_countdown': 3, 'click_limit': 0, 'duration_limit': 0,
                'failsafe_enabled': True, 'click_button': 'left', 'hold_ms': 10,
                'interval_unit': 's', 'jitter_pct': 0, 'use_multi_points': False,
                'multi_points': [], 'hotkey_start': 'f6', 'hotkey_emergency': 'f8',
                'autostart': False, 'close_to_tray': True,
            }
            self.config.setdefault('profiles', {})['推荐安全'] = safe
            self.save_config()
            self.log_message("首次运行：已写入推荐安全预设与「推荐安全」配置方案")
        except Exception:
            pass

    def _show_first_run_guidance(self):
        try:
            messagebox.showinfo("欢迎使用 AutoClicker",
                "首次运行已为你写入推荐安全预设：\n"
                "• 启动前 3 秒倒计时，避免误触\n"
                "• F8 / Esc 紧急停止；鼠标移开 20px 自动停（安全停止）\n"
                "• 可在「安全设置」中开启点击上限 / 时长上限\n\n"
                "建议在自动点击前，先用「测试点击」确认目标位置。")
        except Exception:
            pass

    # ==================== REQ-004 运行统计与导出 ====================
    def export_run_stats(self):
        """将最近一次运行统计导出为 JSON / CSV（REQ-004）"""
        try:
            from tkinter import filedialog
            stats = getattr(self, 'last_run_stats', None)
            if not stats or stats.get('click_count', 0) == 0:
                messagebox.showinfo("提示", "暂无可导出的运行统计（请先完成至少一次点击）")
                return
            path = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("JSON", JSON_FILE_PATTERN), ("CSV", "*.csv")],
                title="导出运行统计")
            if not path:
                return
            if path.lower().endswith('.csv'):
                import csv
                with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                    w = csv.writer(f)
                    w.writerow(["项目", "数值"])
                    for k, v in stats.items():
                        w.writerow([k, v])
            else:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(stats, f, ensure_ascii=False, indent=2)
            self.log_message("运行统计已导出：" + path)
            messagebox.showinfo("导出成功", "运行统计已导出：\n" + path)
        except Exception as e:
            messagebox.showerror("错误", "导出失败: " + str(e))

    # ==================== FR-L01 Wayland 降级指引 ====================
    def show_input_diag(self):
        """展示会话输入能力诊断与可执行的修复指引（不静默失败）"""
        try:
            self.log_message("会话输入能力诊断：%s / 可用=%s"
                             % (self.input_session, self.input_ok))
        except Exception:
            pass
        messagebox.showwarning(
            "当前会话不支持模拟输入",
            "会话类型：%s\n\n%s\n\n启动按钮、启动热键与测试点击均已禁用。"
            % (self.input_session, self.input_reason))

    # ==================== 8.3 错误提示分级组件 ====================
    def clear_field_error(self):
        """清除字段级行内红字。"""
        try:
            self.field_error_label.config(text='')
        except Exception:
            pass

    def show_field_error(self, message):
        """字段级：行内红字，不弹窗。"""
        try:
            self.field_error_label.config(text=message)
        except Exception:
            pass

    def show_operation_message(self, message, level='operation', timeout=0):
        """操作级：顶部可关闭横幅；fatal 级额外记录日志并弹模态框。"""
        if threading.current_thread() is not threading.main_thread():
            try:
                self._ui(self.show_operation_message, message, level, timeout)
            except Exception:
                pass
            return
        if level == 'fatal':
            try:
                self.log_message("致命错误：" + message)
            except Exception:
                pass
            messagebox.showerror("错误", message)
            return
        try:
            self._notice_bar.show(message, level='operation', timeout=timeout,
                                  before=getattr(self, 'header_frame', None))
        except Exception:
            pass
        try:
            self.log_message("操作提示：" + message)
        except Exception:
            pass

    def show_fatal_error(self, message, title="错误"):
        """致命级：模态对话框 + 日志（供启动/配置类不可恢复错误复用）。"""
        if threading.current_thread() is not threading.main_thread():
            try:
                self._ui(self.show_fatal_error, message, title)
            except Exception:
                pass
            return
        try:
            self.log_message("致命错误：" + message)
        except Exception:
            pass
        messagebox.showerror(title, message)

    def _refresh_profile_combo(self):
        try:
            names = list(self.config.get('profiles', {}).keys())
            self.profile_combo['values'] = names
            cur = self.config.get('current_profile')
            if cur and cur in names:
                self.profile_var.set(cur)
            elif names:
                self.profile_var.set(names[0])
            else:
                self.profile_var.set('')
        except Exception:
            pass

    def profile_save(self):
        """CX-09：将当前参数保存为命名方案"""
        from tkinter import simpledialog
        name = simpledialog.askstring("保存方案", "请输入方案名称：")
        if not name:
            return
        name = name.strip()
        keys = ['interval_seconds', 'click_mode', 'prevent_sleep', 'mouse_follow_enabled',
                'mouse_move_speed', 'mouse_move_only', 'startup_countdown', 'click_limit',
                'duration_limit', 'failsafe_enabled', 'target_window_keyword',
                'click_button', 'hold_ms',
                'interval_unit', 'jitter_pct', 'use_multi_points', 'multi_points', 'click_area',
                'hotkey_start', 'hotkey_emergency', 'autostart', 'close_to_tray']
        snap = {k: self.config.get(k) for k in keys}
        self.config.setdefault('profiles', {})[name] = snap
        self.config['current_profile'] = name
        self.save_config()
        self._refresh_profile_combo()
        self.log_message("已保存配置方案：" + name)

    def profile_switch(self):
        name = self.profile_var.get()
        if not name or name not in self.config.get('profiles', {}):
            messagebox.showerror("错误", "请先选择有效方案")
            return
        snap = self.config['profiles'][name]
        for k, v in snap.items():
            self.config[k] = v
        self.config['current_profile'] = name
        self.save_config()
        self.apply_config_to_ui()
        self.log_message("已切换到配置方案：" + name)

    def profile_delete(self):
        name = self.profile_var.get()
        if not name or name not in self.config.get('profiles', {}):
            return
        del self.config['profiles'][name]
        if self.config.get('current_profile') == name:
            self.config['current_profile'] = None
        self.save_config()
        self._refresh_profile_combo()
        self.log_message("已删除配置方案：" + name)

    def profile_export(self):
        try:
            from tkinter import filedialog
            path = filedialog.asksaveasfilename(defaultextension=".json",
                                               filetypes=[("JSON", JSON_FILE_PATTERN)],
                                               title="导出配置方案")
            if not path:
                return
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.config.get('profiles', {}), f, ensure_ascii=False, indent=2)
            self.log_message("配置方案已导出：" + path)
        except Exception as e:
            messagebox.showerror("错误", "导出失败: " + str(e))

    def profile_import(self):
        try:
            from tkinter import filedialog
            path = filedialog.askopenfilename(filetypes=[("JSON", JSON_FILE_PATTERN)], title="导入配置方案")
            if not path:
                return
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.config.setdefault('profiles', {}).update(data)
                self.save_config()
                self._refresh_profile_combo()
                self.log_message("配置方案已导入：" + str(len(data)) + " 个")
        except Exception as e:
            messagebox.showerror("错误", "导入失败: " + str(e))

    def apply_config_to_ui(self):
        """将 config 参数回填到所有 UI 控件（方案切换 / 迁移后调用）"""
        try:
            self.interval_var.set(str(self.config.get('interval_seconds', 10)))
            self.mode_var.set(self.config.get('click_mode', 'random'))
            self.prevent_sleep_var.set(self.config.get('prevent_sleep', True))
            self.mouse_follow_var.set(self.config.get('mouse_follow_enabled', True))
            self.mouse_speed_var.set(str(self.config.get('mouse_move_speed', 0.1)))
            self.mouse_move_only_var.set(self.config.get('mouse_move_only', False))
            self.countdown_var.set(str(self.config.get('startup_countdown', 3)))
            self.click_limit_var.set(str(self.config.get('click_limit', 0)))
            self.duration_limit_var.set(str(self.config.get('duration_limit', 0)))
            self.failsafe_var.set(self.config.get('failsafe_enabled', False))
            self.target_window_var.set(str(self.config.get('target_window_keyword', '')))
            self.close_to_tray_var.set(self.config.get('close_to_tray', True))
            self.click_button_var.set(self.config.get('click_button', 'left'))
            self.hold_ms_var.set(str(self.config.get('hold_ms', 10)))
            self.interval_unit_var.set(self.config.get('interval_unit', 's'))
            self.jitter_var.set(str(self.config.get('jitter_pct', 0)))
            self.use_multi_points_var.set(self.config.get('use_multi_points', False))
            self.autostart_var.set(self.config.get('autostart', False))
            self.hotkey_start_var.set(self.config.get('hotkey_start', 'f6'))
            self.hotkey_emergency_var.set(self.config.get('hotkey_emergency', 'f8'))
            self._refresh_multi_point_listbox()
        except Exception as e:
            print("回填 UI 失败: " + str(e))

    def on_mouse_speed_changed(self, value):
        """鼠标移动速度改变时的回调"""
        try:
            speed = float(value)
            self.config['mouse_move_speed'] = speed
            self.save_config()
            self.mouse_speed_label.config(text=f"{speed:.2f}")
        except Exception as e:
            print(MSG_SAVE_CONFIG_FAILED + str(e))
                
    def setup_ui(self):
        """设置现代化UI界面 - 采用卡片式布局和响应式设计"""
        self._icons_ready = False
        # 设置窗口最小尺寸（与 __init__ 的 DPI 缩放值保持一致：CX-05）
        self.root.minsize(getattr(self, '_min_w', 700), getattr(self, '_min_h', 760))
        
        # 创建主容器 - 使用Canvas支持滚动
        main_container = ttk.Frame(self.root)
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # 创建Canvas和滚动条
        canvas = tk.Canvas(main_container, highlightthickness=0)
        self.main_canvas = canvas
        scrollbar = ttk.Scrollbar(main_container, orient="vertical", command=canvas.yview)
        
        # 创建可滚动框架
        self.main_frame = ttk.Frame(canvas, padding="20")
        
        # 配置Canvas
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # 布局
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 将主框架添加到Canvas
        canvas_window = canvas.create_window((0, 0), window=self.main_frame, anchor="nw", width=680)
        
        # 更新滚动区域
        def on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        self.main_frame.bind("<Configure>", on_frame_configure)
        
        # 更新Canvas窗口宽度
        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", on_canvas_configure)
        
        # ==================== 头部区域 ====================
        header_frame = ttk.Frame(self.main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 15))
        self.header_frame = header_frame
        # 8.3 操作级提示：顶部可关闭横幅（按需 pack，位于 header 之前）
        self._notice_bar = NoticeBar(self.main_frame, self._color)
        
        # 标题和状态指示器
        title_container = ttk.Frame(header_frame)
        title_container.pack(fill=tk.X)
        
        # 主标题
        title_label = ttk.Label(title_container, text="桌面自动点击工具", 
                               font=('微软雅黑', 18, 'bold'))
        title_label.pack(side=tk.LEFT)
        
        # 状态指示器（带颜色圆点）
        self.status_indicator = tk.Canvas(title_container, width=12, height=12, 
                                         highlightthickness=0, bg='white')
        self.status_indicator.pack(side=tk.RIGHT, padx=5)
        self.status_circle = self.status_indicator.create_oval(2, 2, 10, 10, fill='red', outline='')
        
        self.status_text_label = ttk.Label(title_container, text="已停止", 
                                          font=('微软雅黑', 11, 'bold'), foreground=self._color('danger'))
        self.status_text_label.pack(side=tk.RIGHT, padx=5)
        
        # 主题选择器（TH-01 / TH-03）
        theme_row = ttk.Frame(header_frame)
        theme_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(theme_row, text="主题", font=('微软雅黑', 9)).pack(side=tk.LEFT)
        self.theme_var = tk.StringVar(
            value={'light': '浅色', 'dark': '深色', 'system': '跟随系统'}.get(self.theme_mode, '浅色'))
        self.theme_combo = ttk.Combobox(theme_row, textvariable=self.theme_var,
                                        values=['浅色', '深色', '跟随系统'], state='readonly', width=10)
        self.theme_combo.pack(side=tk.LEFT, padx=(5, 0))
        self.theme_combo.bind('<<ComboboxSelected>>', self.on_theme_change_ui)

        # FR-L01 / 6.12.1：Wayland 降级横幅（可关闭；纯文本，保持 UI-02 零 emoji）
        if not self.input_ok:
            warn_bar = tk.Frame(self.main_frame, bg=self._color('warning'))
            warn_bar.pack(fill=tk.X, pady=(0, 10))
            tk.Label(warn_bar,
                     text="注意：Wayland 会话不支持模拟输入，启动已禁用",
                     bg=self._color('warning'), fg=self._color('on_warning'),
                     font=('微软雅黑', 10, 'bold'), wraplength=500,
                     justify=tk.LEFT, anchor=tk.W).pack(
                         side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 6), pady=7)
            tk.Button(warn_bar, text="详情", command=self.show_input_diag,
                      relief=tk.FLAT, bd=0, bg=self._color('warning'), fg=self._color('on_warning'),
                      activebackground=self._shade(self._color('warning')),
                      activeforeground=self._color('on_warning'),
                      font=('微软雅黑', 9, 'underline'), cursor='hand2').pack(
                          side=tk.RIGHT, padx=(0, 6))
            tk.Button(warn_bar, text="×", command=warn_bar.destroy,
                      relief=tk.FLAT, bd=0, bg=self._color('warning'), fg=self._color('on_warning'),
                      activebackground=self._shade(self._color('warning')),
                      activeforeground=self._color('on_warning'),
                      font=('微软雅黑', 11, 'bold'), cursor='hand2').pack(
                          side=tk.RIGHT, padx=(0, 4))
            self._input_banner = warn_bar

        # 分隔线
        separator = ttk.Separator(self.main_frame, orient='horizontal')
        separator.pack(fill=tk.X, pady=(0, 15))

        # ==================== 顶部运行状态条（UI-01 / UI-03） ====================
        status_bar = ttk.LabelFrame(self.main_frame, text="运行状态", padding="10")
        status_bar.pack(fill=tk.X, pady=(0, 15))

        # 状态文字 + 倒计时进度条（同一行）
        sb_top = ttk.Frame(status_bar)
        sb_top.pack(fill=tk.X, pady=(0, 6))
        self.sb_status_label = ttk.Label(sb_top, text="● 已停止", font=('微软雅黑', 11, 'bold'), foreground=self._color('danger'))
        self.sb_status_label.pack(side=tk.LEFT)
        ttk.Label(sb_top, text="  启动倒计时", font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(10, 4))
        self.countdown_bar = ttk.Progressbar(sb_top, orient='horizontal', length=160, mode='determinate', maximum=100)
        self.countdown_bar.pack(side=tk.LEFT, padx=(0, 6))
        self.countdown_bar['value'] = 0
        self.sb_countdown_label = ttk.Label(sb_top, text="--", font=('微软雅黑', 9), foreground='gray')
        self.sb_countdown_label.pack(side=tk.LEFT)

        # 计数 / 运行时长（同一行）
        sb_mid = ttk.Frame(status_bar)
        sb_mid.pack(fill=tk.X)
        self.sb_count_label = ttk.Label(sb_mid, text="总点击: 0", font=('微软雅黑', 10))
        self.sb_count_label.pack(side=tk.LEFT, padx=(0, 16))
        self.sb_success_label = ttk.Label(sb_mid, text="成功: 0", font=('微软雅黑', 10), foreground=self._color('success'))
        self.sb_success_label.pack(side=tk.LEFT, padx=(0, 16))
        self.sb_fail_label = ttk.Label(sb_mid, text="失败: 0", font=('微软雅黑', 10), foreground=self._color('danger'))
        self.sb_fail_label.pack(side=tk.LEFT, padx=(0, 16))
        self.sb_runtime_label = ttk.Label(sb_mid, text="运行时长: 00:00", font=('微软雅黑', 10), foreground=self._color('primary'))
        self.sb_runtime_label.pack(side=tk.LEFT)

        # ==================== 核心控制区域 ====================
        control_card = ttk.LabelFrame(self.main_frame, text="核心控制", padding="15")
        control_card.pack(fill=tk.X, pady=(0, 15))
        
        # 主控制按钮 - 大按钮设计
        # 注意：tk.Button 带 image 时 width/height 的单位是「像素」而非字符/行，
        # 旧代码 height=2 会把按钮压成 2px 色条（文字不可见）；改用 padx/pady 控制留白。
        main_control_frame = ttk.Frame(control_card)
        main_control_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.start_btn = tk.Button(main_control_frame, text=" 启动自动点击",
                                  command=self.start_clicking,
                                  font=('微软雅黑', 12, 'bold'),
                                  bg=self._color('success'), fg=self._color('on_success'),
                                  activebackground=self._shade(self._color('success')),
                                  activeforeground=self._color('on_success'),
                                  padx=12, pady=8, cursor='hand2',
                                  relief=tk.FLAT, bd=0)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 10), fill=tk.X, expand=True)
        
        self.stop_btn = tk.Button(main_control_frame, text=" 停止",
                                 command=self.stop_clicking,
                                 font=('微软雅黑', 12, 'bold'),
                                 bg=self._color('danger'), fg=self._color('on_danger'),
                                 activebackground=self._shade(self._color('danger')),
                                 activeforeground=self._color('on_danger'),
                                 padx=12, pady=8, cursor='hand2',
                                 relief=tk.FLAT, bd=0, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 测试按钮
        self.test_btn = tk.Button(control_card, text=" 测试点击位置",
                                 command=self.test_click,
                                 font=('微软雅黑', 10),
                                 bg=self._color('primary'), fg=self._color('on_primary'),
                                 activebackground=self._shade(self._color('primary')),
                                 activeforeground=self._color('on_primary'),
                                 pady=6, cursor='hand2',
                                 relief=tk.FLAT, bd=0)
        self.test_btn.pack(fill=tk.X, pady=(5, 0))
        
        # ==================== 配置区域 - 两列布局 ====================
        config_container = ttk.Frame(self.main_frame)
        config_container.pack(fill=tk.X, pady=(0, 15))
        
        # 左列 - 基本配置
        left_card = ttk.LabelFrame(config_container, text="目标", padding="15")
        left_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        # 点击间隔配置
        interval_container = ttk.Frame(left_card)
        interval_container.pack(fill=tk.X, pady=(0, 12))
        
        ttk.Label(interval_container, text="点击间隔", 
                 font=('微软雅黑', 10, 'bold')).pack(anchor=tk.W)
        
        interval_input_frame = ttk.Frame(interval_container)
        interval_input_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.interval_var = tk.StringVar(value=str(self.config['interval_seconds']))
        self.interval_entry = ttk.Entry(interval_input_frame, textvariable=self.interval_var, 
                                       font=('微软雅黑', 11), width=8, justify='center')
        self.interval_entry.pack(side=tk.LEFT, padx=(0, 5))
        
        # 添加trace，当间隔改变时自动保存配置
        self.interval_var.trace_add('write', lambda *args: self.save_config_if_running())
        self.interval_var.trace_add('write', self._on_interval_hot_update)
        
        ttk.Label(interval_input_frame, text="秒 (1-3600)", 
                 font=('微软雅黑', 9), foreground='gray').pack(side=tk.LEFT)
        
        # 点击模式配置
        mode_container = ttk.Frame(left_card)
        mode_container.pack(fill=tk.X, pady=(0, 12))
        
        ttk.Label(mode_container, text="点击模式", 
                 font=('微软雅黑', 10, 'bold')).pack(anchor=tk.W)
        
        # 模式映射
        self.mode_map = {
            'random': '随机位置',
            'center': '中心点',
            'custom': '自定义区域'
        }
        self.reverse_mode_map = {v: k for k, v in self.mode_map.items()}
        self.mode_var = tk.StringVar(value=self.config['click_mode'])
        
        display_values = list(self.mode_map.values())
        self.mode_combo = ttk.Combobox(mode_container, values=display_values, 
                                      font=('微软雅黑', 10), state='readonly', width=15)
        self.mode_combo.pack(fill=tk.X, pady=(5, 0))
        
        # 设置初始值
        current_mode = self.config.get('click_mode', 'random')
        display_value = self.mode_map.get(current_mode, '随机位置')
        self.mode_combo.set(display_value)
        self.mode_var.set(current_mode)
        
        self.mode_combo.bind('<<ComboboxSelected>>', self.on_mode_change)
        
        # 点击区域配置
        area_container = ttk.Frame(left_card)
        area_container.pack(fill=tk.X)
        
        ttk.Label(area_container, text="点击区域", 
                 font=('微软雅黑', 10, 'bold')).pack(anchor=tk.W)
        
        area_input_frame = ttk.Frame(area_container)
        area_input_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.area_label = ttk.Label(area_input_frame, 
                                   text=str(self.config['click_area']['width']) + "x" + str(self.config['click_area']['height']),
                                   font=('微软雅黑', 10), foreground=self._color('primary'))
        self.area_label.pack(side=tk.LEFT, padx=(0, 10))
        
        self.set_area_btn = tk.Button(area_input_frame, text="设置区域", 
                                     command=self.set_click_area,
                                     font=('微软雅黑', 9),
                                     bg=self._color('muted'), fg=self._color('on_muted'),
                                     activebackground=self._shade(self._color('muted')),
                                     activeforeground=self._color('on_muted'),
                                     cursor='hand2', relief=tk.FLAT, bd=0)
        self.set_area_btn.pack(side=tk.LEFT)

        # 8.3 字段级提示：行内红字，不弹窗
        self.field_error_label = tk.Label(
            left_card, text='', anchor=tk.W, justify=tk.LEFT,
            fg=self._color('danger'), bg=self._color('bg'),
            font=('微软雅黑', 9))
        self.field_error_label.pack(fill=tk.X, pady=(4, 0))
        
        # 右列 - 高级选项和状态
        right_card = ttk.LabelFrame(config_container, text="状态监控", padding="15")
        right_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 状态信息
        status_info_frame = ttk.Frame(right_card)
        status_info_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 下次点击时间
        next_click_container = ttk.Frame(status_info_frame)
        next_click_container.pack(fill=tk.X, pady=(0, 8))
        
        ttk.Label(next_click_container, text="下次点击:", 
                 font=('微软雅黑', 9)).pack(side=tk.LEFT)
        self.next_click_label = ttk.Label(next_click_container, text="--", 
                                         font=('微软雅黑', 10, 'bold'), foreground=self._color('primary'))
        self.next_click_label.pack(side=tk.LEFT, padx=(5, 0))
        
        # 点击次数
        count_container = ttk.Frame(status_info_frame)
        count_container.pack(fill=tk.X)
        
        ttk.Label(count_container, text="点击次数:", 
                 font=('微软雅黑', 9)).pack(side=tk.LEFT)
        self.click_count_label = ttk.Label(count_container, text="0", 
                                          font=('微软雅黑', 14, 'bold'), foreground=self._color('success'))
        self.click_count_label.pack(side=tk.LEFT, padx=(5, 0))
        
        self.click_count = 0
        
        # 高级选项
        options_frame = ttk.LabelFrame(right_card, text="高级选项", padding="10")
        options_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.prevent_sleep_var = tk.BooleanVar(value=self.config['prevent_sleep'])
        prevent_sleep_check = ttk.Checkbutton(options_frame, text="防止系统锁屏",
                                             variable=self.prevent_sleep_var,
                                             command=self.on_prevent_sleep_changed)
        prevent_sleep_check.pack(anchor=tk.W, pady=3)

        # 鼠标跟随设置
        self.mouse_follow_var = tk.BooleanVar(value=self.config['mouse_follow_enabled'])
        mouse_follow_check = ttk.Checkbutton(options_frame, text="鼠标跟随移动",
                                             variable=self.mouse_follow_var,
                                             command=self.on_mouse_follow_changed)
        mouse_follow_check.pack(anchor=tk.W, pady=3)
        
        self.mouse_move_only_var = tk.BooleanVar(value=self.config['mouse_move_only'])
        mouse_move_only_check = ttk.Checkbutton(options_frame, text="   只移动不点击",
                                                variable=self.mouse_move_only_var,
                                                command=self.on_mouse_move_only_changed)
        mouse_move_only_check.pack(anchor=tk.W, pady=3)
        
        # 鼠标移动速度调节
        speed_container = ttk.Frame(options_frame)
        speed_container.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Label(speed_container, text="移动速度:", 
                 font=('微软雅黑', 9)).pack(side=tk.LEFT, padx=(0, 10))
        
        self.mouse_speed_var = tk.StringVar(value=str(self.config['mouse_move_speed']))
        self.mouse_speed_scale = ttk.Scale(speed_container, from_=0.0, to=1.0, 
                                         orient=tk.HORIZONTAL, length=150, 
                                         variable=self.mouse_speed_var, 
                                         command=self.on_mouse_speed_changed)
        self.mouse_speed_scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        self.mouse_speed_label = ttk.Label(speed_container, 
                                          text=f"{float(self.mouse_speed_var.get()):.2f}",
                                          font=('微软雅黑', 9), width=5)
        self.mouse_speed_label.pack(side=tk.LEFT)
        
        # ==================== 安全与终点控制（P0 止血） ====================
        safety_card = ttk.LabelFrame(self.main_frame, text="安全", padding="15")
        safety_card.pack(fill=tk.X, pady=(0, 15))

        # 启动倒计时（CX-04）
        countdown_container = ttk.Frame(safety_card)
        countdown_container.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(countdown_container, text="启动倒计时(秒, 0-5)",
                 font=('微软雅黑', 10, 'bold')).pack(side=tk.LEFT)
        self.countdown_var = tk.StringVar(value=str(self.config.get('startup_countdown', 3)))
        ttk.Entry(countdown_container, textvariable=self.countdown_var,
                 font=('微软雅黑', 11), width=8, justify='center').pack(side=tk.LEFT, padx=(5, 0))

        # FR-E03：前台目标窗口校验（标题/进程名关键字，留空不校验）
        target_container = ttk.Frame(safety_card)
        target_container.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(target_container, text="目标窗口关键字(留空=不校验)",
                 font=('微软雅黑', 10, 'bold')).pack(side=tk.LEFT)
        self.target_window_var = tk.StringVar(value=str(self.config.get('target_window_keyword', '')))
        ttk.Entry(target_container, textvariable=self.target_window_var,
                 font=('微软雅黑', 11), width=24).pack(side=tk.LEFT, padx=(5, 0))

        # 点击次数上限（CX-02）
        limit_container = ttk.Frame(safety_card)
        limit_container.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(limit_container, text="点击次数上限(0=无限)",
                 font=('微软雅黑', 10, 'bold')).pack(side=tk.LEFT)
        self.click_limit_var = tk.StringVar(value=str(self.config.get('click_limit', 0)))
        ttk.Entry(limit_container, textvariable=self.click_limit_var,
                 font=('微软雅黑', 11), width=8, justify='center').pack(side=tk.LEFT, padx=(5, 0))

        # 运行时长上限（CX-02）
        duration_container = ttk.Frame(safety_card)
        duration_container.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(duration_container, text="运行时长上限(分钟, 0=无限)",
                 font=('微软雅黑', 10, 'bold')).pack(side=tk.LEFT)
        self.duration_limit_var = tk.StringVar(value=str(self.config.get('duration_limit', 0)))
        ttk.Entry(duration_container, textvariable=self.duration_limit_var,
                 font=('微软雅黑', 11), width=8, justify='center').pack(side=tk.LEFT, padx=(5, 0))

        # 鼠标位移 failsafe（CX-01）
        self.failsafe_var = tk.BooleanVar(value=self.config.get('failsafe_enabled', False))
        ttk.Checkbutton(safety_card, text="鼠标移动即停 (failsafe，移动>20px自动急停)",
                       variable=self.failsafe_var).pack(anchor=tk.W)

        # 关闭行为（CX-06）
        self.close_to_tray_var = tk.BooleanVar(value=self.config.get('close_to_tray', True))
        ttk.Checkbutton(safety_card, text="关闭窗口时最小化到托盘（否则直接退出）",
                       variable=self.close_to_tray_var,
                       command=self.on_close_behavior_changed).pack(anchor=tk.W, pady=(4, 0))

        # ==================== P1 功能扩展：点击 / 节奏 / 多点位 ====================
        p1_card = ttk.LabelFrame(self.main_frame, text="节奏与点击 (P1)", padding="15")
        p1_card.pack(fill=tk.X, pady=(0, 15))

        row1 = ttk.Frame(p1_card)
        row1.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row1, text="鼠标按键", font=('微软雅黑', 10, 'bold')).pack(side=tk.LEFT)
        self.click_button_var = tk.StringVar(value=self.config.get('click_button', 'left'))
        ttk.Combobox(row1, textvariable=self.click_button_var, width=10,
                     values=['left', 'right', 'middle', 'double'], state='readonly').pack(side=tk.LEFT, padx=(5, 15))
        ttk.Label(row1, text="按住时长(ms)", font=('微软雅黑', 10, 'bold')).pack(side=tk.LEFT)
        self.hold_ms_var = tk.StringVar(value=str(self.config.get('hold_ms', 10)))
        ttk.Entry(row1, textvariable=self.hold_ms_var, width=8, justify='center').pack(side=tk.LEFT, padx=(5, 0))

        row2 = ttk.Frame(p1_card)
        row2.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row2, text="间隔单位", font=('微软雅黑', 10, 'bold')).pack(side=tk.LEFT)
        self.interval_unit_var = tk.StringVar(value=self.config.get('interval_unit', 's'))
        self.interval_unit_var.trace_add('write', self._on_interval_hot_update)
        ttk.Combobox(row2, textvariable=self.interval_unit_var, width=8,
                     values=['s', 'ms'], state='readonly').pack(side=tk.LEFT, padx=(5, 15))
        ttk.Label(row2, text="随机抖动(%)", font=('微软雅黑', 10, 'bold')).pack(side=tk.LEFT)
        self.jitter_var = tk.StringVar(value=str(self.config.get('jitter_pct', 0)))
        ttk.Entry(row2, textvariable=self.jitter_var, width=8, justify='center').pack(side=tk.LEFT, padx=(5, 0))

        mp_frame = ttk.Frame(p1_card)
        mp_frame.pack(fill=tk.X, pady=(4, 0))
        self.use_multi_points_var = tk.BooleanVar(value=self.config.get('use_multi_points', False))
        ttk.Checkbutton(mp_frame, text="使用多点位序列点击（按列表循环）",
                        variable=self.use_multi_points_var).pack(anchor=tk.W)
        self.multi_point_listbox = tk.Listbox(p1_card, height=4)
        self.multi_point_listbox.pack(fill=tk.X, pady=(4, 4))
        self._refresh_multi_point_listbox()
        mp_btn = ttk.Frame(p1_card)
        mp_btn.pack(fill=tk.X)
        ttk.Button(mp_btn, text="拾取当前光标", command=self.pick_coordinate).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(mp_btn, text="添加(手动)", command=self.add_manual_point).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(mp_btn, text="删除选中", command=self.remove_point).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(mp_btn, text="清空", command=self.clear_points).pack(side=tk.LEFT)
        mp_entry = ttk.Frame(p1_card)
        mp_entry.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(mp_entry, text="X").pack(side=tk.LEFT)
        self.mp_x_var = tk.StringVar()
        ttk.Entry(mp_entry, textvariable=self.mp_x_var, width=8).pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(mp_entry, text="Y").pack(side=tk.LEFT)
        self.mp_y_var = tk.StringVar()
        ttk.Entry(mp_entry, textvariable=self.mp_y_var, width=8).pack(side=tk.LEFT)

        # ==================== P1 功能扩展：热键 / 配置方案 / 系统 ====================
        p1b_card = ttk.LabelFrame(self.main_frame, text="高级 (P1)", padding="15")
        p1b_card.pack(fill=tk.X, pady=(0, 15))

        hk_row = ttk.Frame(p1b_card)
        hk_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(hk_row, text="启动/停止键", font=('微软雅黑', 10, 'bold')).pack(side=tk.LEFT)
        self.hotkey_start_var = tk.StringVar(value=self.config.get('hotkey_start', 'f6'))
        ttk.Entry(hk_row, textvariable=self.hotkey_start_var, width=8).pack(side=tk.LEFT, padx=(5, 15))
        ttk.Label(hk_row, text="紧急停止键", font=('微软雅黑', 10, 'bold')).pack(side=tk.LEFT)
        self.hotkey_emergency_var = tk.StringVar(value=self.config.get('hotkey_emergency', 'f8'))
        ttk.Entry(hk_row, textvariable=self.hotkey_emergency_var, width=8).pack(side=tk.LEFT, padx=(5, 10))
        ttk.Button(hk_row, text="应用热键", command=self.on_hotkey_apply).pack(side=tk.LEFT)

        prof_row = ttk.Frame(p1b_card)
        prof_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(prof_row, text="配置方案", font=('微软雅黑', 10, 'bold')).pack(side=tk.LEFT)
        self.profile_var = tk.StringVar()
        self.profile_combo = ttk.Combobox(prof_row, textvariable=self.profile_var, width=11, state='readonly')
        self.profile_combo.pack(side=tk.LEFT, padx=(5, 5))
        self._refresh_profile_combo()
        ttk.Button(prof_row, text="保存当前", command=self.profile_save).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(prof_row, text="切换", command=self.profile_switch).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(prof_row, text="删除", command=self.profile_delete).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(prof_row, text="导出", command=self.profile_export).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(prof_row, text="导入", command=self.profile_import).pack(side=tk.LEFT)

        sys_row = ttk.Frame(p1b_card)
        sys_row.pack(fill=tk.X, pady=(0, 6))
        self.autostart_var = tk.BooleanVar(value=self.config.get('autostart', False))
        ttk.Checkbutton(sys_row, text="开机自动启动", variable=self.autostart_var,
                        command=self.on_autostart_changed).pack(side=tk.LEFT)
        ttk.Button(sys_row, text="打开日志目录", command=self.open_log_dir).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(sys_row, text="导出运行统计", command=self.export_run_stats).pack(side=tk.LEFT, padx=(10, 0))

        # ==================== 日志区域 ====================
        log_card = ttk.LabelFrame(self.main_frame, text="运行日志", padding="10")
        log_card.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # 日志工具栏（UI-04：过滤 / 复制 / 清空；UI-01：可折叠）
        log_toolbar = ttk.Frame(log_card)
        log_toolbar.pack(fill=tk.X, pady=(0, 5))

        ttk.Label(log_toolbar, text="过滤:", font=('微软雅黑', 9)).pack(side=tk.LEFT)
        self.log_filter_var = tk.StringVar()
        self.log_filter_entry = ttk.Entry(log_toolbar, textvariable=self.log_filter_var,
                                         width=16, font=('微软雅黑', 9))
        self.log_filter_entry.pack(side=tk.LEFT, padx=(2, 4))
        self.log_filter_entry.bind('<Return>', lambda e: self.filter_log())
        ttk.Button(log_toolbar, text="过滤", command=self.filter_log, width=6).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(log_toolbar, text="复制", command=self.copy_log, width=6).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(log_toolbar, text="清空", command=self.clear_log, width=6).pack(side=tk.LEFT)
        self.log_toggle_btn = ttk.Button(log_toolbar, text="收起", command=self.toggle_log_collapse, width=6)
        self.log_toggle_btn.pack(side=tk.RIGHT)

        # 可折叠日志内容（UI-01）
        self.log_inner = ttk.Frame(log_card)
        self.log_inner.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(self.log_inner, height=10, state=tk.DISABLED,
                               font=('Consolas', 9), bg=self._color('surface'),
                               relief=tk.FLAT, padx=5, pady=5)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(self.log_inner, orient=tk.VERTICAL, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text['yscrollcommand'] = scrollbar.set
        # 日志分级着色标签（UI-04）
        self.log_text.tag_config('lvl_err', foreground=self._color('danger'))
        self.log_text.tag_config('lvl_warn', foreground=self._color('warning'))
        
        # ==================== 底部提示区域 ====================
        footer_frame = ttk.Frame(self.main_frame)
        footer_frame.pack(fill=tk.X)
        
        # 快捷键提示
        shortcut_frame = ttk.Frame(footer_frame)
        shortcut_frame.pack(fill=tk.X, pady=(0, 5))
        
        shortcut_text = "快捷键: F6 启动/停止 · F8/Esc 紧急停止"
        ttk.Label(shortcut_frame, text=shortcut_text, 
                 font=('微软雅黑', 9), foreground=self._color('muted')).pack(anchor=tk.CENTER)
        
        # 版本信息
        version_label = ttk.Label(footer_frame, text="v2.0.2 (Python 3.14)", 
                                 font=('微软雅黑', 8), foreground=self._color('muted'))
        version_label.pack(anchor=tk.CENTER)
        
        # 更新状态标签引用
        self.status_label = self.status_text_label
        
    def on_mode_change(self, event):
        """模式变更事件处理"""
        try:
            display_value = self.mode_combo.get()
            actual_value = self.reverse_mode_map.get(display_value, 'random')
            self.mode_var.set(actual_value)
            self.config['click_mode'] = actual_value
            self.save_config()
            print(f"模式已切换为: {actual_value}")
        except Exception as e:
            print(f"模式切换错误: {e}")
    
    def setup_hotkeys(self):
        self._register_hotkeys()

    def _register_hotkeys(self):
        """CX-08：按配置注册热键，支持自定义与冲突规避（Esc 始终为紧急停止）

        keyboard 的全局钩子回调在独立监听线程执行；Tk 控件（interval_var 等）
        只能在主线程访问，否则会抛「main thread is not in main loop」，
        表现为物理 F6/F8/Esc 按了没反应。这里统一投递到主线程队列。
        """
        kb = _get_keyboard()
        if not kb:
            return
        if not hasattr(self, '_hotkey_queue'):
            self._hotkey_queue = queue.Queue()
        # 清除旧热键，避免重复注册
        for k in getattr(self, '_hk_keys', []):
            try:
                kb.remove_hotkey(k)
            except Exception:
                pass
        self._hk_keys = []
        try:
            start_k = self.config.get('hotkey_start', 'f6')
            emer_k = self.config.get('hotkey_emergency', 'f8')
            kb.add_hotkey(start_k, lambda: self._hotkey_queue.put('toggle'))
            kb.add_hotkey(emer_k, lambda: self._hotkey_queue.put('emergency'))
            kb.add_hotkey('esc', lambda: self._hotkey_queue.put('emergency'))
            self._hk_keys = [start_k, emer_k, 'esc']
            print("快捷键已注册：启动=" + start_k + "，紧急停止=" + emer_k + "，Esc")
        except Exception as e:
            print("注册快捷键失败: " + str(e))

    def _poll_hotkey_queue(self):
        """主线程消费热键队列，确保 Tk 只在主线程被访问（CX-08 修复）。"""
        try:
            while True:
                action = self._hotkey_queue.get_nowait()
                if action == 'toggle':
                    self.toggle_clicking()
                elif action == 'emergency':
                    self.emergency_stop()
        except queue.Empty:
            pass
        except Exception as e:
            print("处理热键动作失败: " + str(e))
        try:
            self.root.after(50, self._poll_hotkey_queue)
        except Exception:
            pass
                    
    def set_click_area(self):
        """FR-C01/8.1：全屏遮罩 + 十字线 + 拖拽框选，实时显示尺寸并回填区域。

        遮罩构建放到 event loop 的下一次空闲回调，避免按钮点击路径同步阻塞主线程。
        """
        try:
            if getattr(self, '_region_selector', None) is not None:
                return
            if getattr(self, '_region_starting', False):
                return
            self._region_starting = True
            self.log_message("取区域：拖拽框选 · 单击取点 · Esc 取消")
            self.root.after(0, self._open_region_selector)
        except Exception as e:
            self._region_starting = False
            self._region_selector = None
            error_msg = f"打开取区域遮罩失败: {e}"
            self.log_message(error_msg)
            self.show_operation_message(error_msg, level='fatal')

    def _open_region_selector(self):
        self._region_starting = False
        try:
            self._region_selector = RegionSelector(self.root, self._on_region_selected)
        except Exception as e:
            self._region_selector = None
            error_msg = f"打开取区域遮罩失败: {e}"
            self.log_message(error_msg)
            self.show_operation_message(error_msg, level='fatal')

    def _on_region_selected(self, region):
        """区域选择回调：None=取消（原配置不变）；否则回填并持久化。"""
        self._region_selector = None
        if region is None:
            self.log_message("取区域：已取消，原区域保持不变")
            return
        try:
            if region.get('point'):
                self.config['click_area'] = {
                    'x': int(region['x']), 'y': int(region['y']),
                    'width': 1, 'height': 1,
                }
                self.log_message("已取点：(%d, %d)" % (region['x'], region['y']))
            else:
                self.config['click_area'] = {
                    'x': int(region['x']), 'y': int(region['y']),
                    'width': int(region['width']), 'height': int(region['height']),
                }
                self.log_message("点击区域已设置: %s" % self.config['click_area'])
            self.area_label.config(
                text="%dx%d (%d,%d)" % (
                    self.config['click_area']['width'],
                    self.config['click_area']['height'],
                    self.config['click_area']['x'],
                    self.config['click_area']['y']))
            self.save_config()
        except Exception as e:
            self.log_message("回填点击区域失败: " + str(e))
            self.show_operation_message("回填点击区域失败: " + str(e), level='fatal')
            
    def get_click_position(self):
        mode = getattr(self, 'click_mode_cache', None) or self.mode_var.get()
        area = self.config['click_area']
        if mode == 'center':
            x = area['x'] + area['width'] // 2
            y = area['y'] + area['height'] // 2
        else:
            # FR-C02：闭区间 [x, x+w-1] / [y, y+h-1]，不得越过区域右下边界
            x = _RANDOM.randint(area['x'], area['x'] + max(0, area['width'] - 1))
            y = _RANDOM.randint(area['y'], area['y'] + max(0, area['height'] - 1))
        return x, y
    
    def smooth_move_to(self, x, y, duration=0.5):
        """平滑移动鼠标到指定位置（带视觉动画效果，跨平台）

        Args:
            x: 目标X坐标
            y: 目标Y坐标
            duration: 移动持续时间（秒）
        """
        try:
            current_x, current_y = get_cursor_pos()
            distance = ((x - current_x) ** 2 + (y - current_y) ** 2) ** 0.5

            if distance < 2:
                move_mouse(x, y)
                return

            steps = max(10, int(distance / 5))
            step_time = duration / steps
            
            self.log_message(f"[平滑移动] 起点=({current_x}, {current_y}), 终点=({x}, {y}), 距离={distance:.1f}像素，步数={steps}")

            for i in range(steps):
                t = (i + 1) / steps
                eased_t = t * t * (3 - 2 * t)
                target_x = int(current_x + (x - current_x) * eased_t)
                target_y = int(current_y + (y - current_y) * eased_t)
                move_mouse(target_x, target_y)
                time.sleep(step_time)

            move_mouse(x, y)
            self.log_message("[平滑移动] 完成")
        except Exception as e:
            self.log_message(f"鼠标移动失败: {e}")
        
    def prevent_system_sleep(self):
        """跨平台防止系统休眠"""
        # 高频点击时每次循环都调用 SetThreadExecutionState 会引入额外开销，
        # 把重复调用节流到 1 秒一次，既保持防休眠效果又不拖慢毫秒级间隔。
        now = time.monotonic()
        last = getattr(self, '_prevent_sleep_last_at', 0)
        if now - last < 1.0:
            return
        self._prevent_sleep_last_at = now
        try:
            if IS_WINDOWS:
                import ctypes
                ES_CONTINUOUS = 0x80000000
                ES_SYSTEM_REQUIRED = 0x00000001
                ES_DISPLAY_REQUIRED = 0x00000002
                ctypes.windll.kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
                )
                print("已设置Windows防休眠")
            elif IS_LINUX:
                try:
                    import subprocess
                    subprocess.Popen(['xdg-screensaver', 'suspend'], 
                                   stdout=subprocess.PIPE, 
                                   stderr=subprocess.PIPE)
                except Exception:
                    try:
                        import subprocess
                        subprocess.Popen(['xset', 's', 'off'], 
                                       stdout=subprocess.PIPE, 
                                       stderr=subprocess.PIPE)
                        subprocess.Popen(['xset', '-dpms'], 
                                       stdout=subprocess.PIPE, 
                                       stderr=subprocess.PIPE)
                    except Exception:
                        pass
                print("已设置Linux防休眠")
            elif IS_MACOS:
                import subprocess
                subprocess.run(["caffeinate", "-u", "-t", "1"], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("已设置macOS防休眠")
        except Exception as e:
            print(f"防止系统休眠失败: {e}")
                
    # ==================== 后台防锁屏保活（独立于点击运行） ====================
    def start_keepalive(self):
        """启动后台防锁屏保活线程。

        只要“防止系统锁屏”开启即持续生效，不再依赖点击是否在运行：
        周期性断言 SetThreadExecutionState 并做一次 1px 微抖动鼠标，
        以击败“策略型锁屏/屏保”（也兼顾用户期望的“鼠标自动移动”诉求）。
        """
        if getattr(self, 'keepalive_running', None) is None:
            self.keepalive_running = threading.Event()
            self.keepalive_thread = None
        if getattr(self, 'keepalive_stop_event', None) is None:
            self.keepalive_stop_event = threading.Event()
        if self.keepalive_running.is_set():
            return
        self.keepalive_stop_event.clear()
        self.keepalive_running.set()
        self.keepalive_thread = threading.Thread(target=self._keepalive_loop, daemon=True)
        self.keepalive_thread.start()
        self.log_message("已启动后台防锁屏保活（每 %d 秒保活一次）" % KEEPALIVE_INTERVAL)

    def stop_keepalive(self):
        """停止后台防锁屏保活线程（不在此清除系统唤醒状态，交由 allow_system_sleep 统一处理）。"""
        if not getattr(self, 'keepalive_running', None) or not self.keepalive_running.is_set():
            return
        self.keepalive_running.clear()
        if getattr(self, 'keepalive_stop_event', None) is not None:
            self.keepalive_stop_event.set()
        self.log_message("已停止后台防锁屏保活")

    def _keepalive_loop(self):
        """保活循环：断言系统/显示器唤醒 + 1px 微抖动，直到被停止。"""
        try:
            self.prevent_system_sleep()
        except Exception:
            pass
        while self.keepalive_running.is_set():
            # 等待一个间隔；stop_keepalive 通过独立停止事件立即唤醒退出。
            # 注意不能等待 keepalive_running 本身：Event 已 set 时 wait 会立即返回，形成忙循环。
            if self.keepalive_stop_event.wait(KEEPALIVE_INTERVAL):
                break
            if not self.keepalive_running.is_set():
                break
            try:
                self.prevent_system_sleep()
            except Exception:
                pass
            # 1px 微抖动：先右移/下移 1 像素再回原位，几乎无感但足以重置空闲计时
            try:
                cx, cy = get_cursor_pos()
                move_mouse(cx + 1, cy + 1)
                move_mouse(cx, cy)
            except Exception:
                pass

    def allow_system_sleep(self):
        """跨平台恢复系统休眠设置。

        若后台保活仍在运行（防止系统锁屏开启），则不清除唤醒状态，
        避免 stop_clicking 误清导致保活中断（由 keep-alive 继续持有状态）。
        """
        if getattr(self, 'keepalive_running', None) and self.keepalive_running.is_set():
            return
        restore_system_settings()

    # ==================== 线程安全的 UI 更新辅助方法 ====================
    def _ui(self, fn, *args, **kwargs):
        """后台线程安全地请求主线程执行 UI 回调（T05212/T05215/T05229）。"""
        try:
            if not hasattr(self, '_ui_queue'):
                self._ui_queue = queue.Queue()
            self._ui_queue.put((fn, args, kwargs))
        except Exception:
            pass

    def _poll_ui_queue(self):
        """主线程消费 UI 回调队列，避免后台线程直接调用 Tk 造成死锁。"""
        try:
            while True:
                fn, args, kwargs = self._ui_queue.get_nowait()
                try:
                    fn(*args, **kwargs)
                except Exception:
                    pass
        except queue.Empty:
            pass
        except Exception:
            pass
        try:
            self.root.after(30, self._poll_ui_queue)
        except Exception:
            pass

    def _do_set_status(self, text, color):
        try:
            self.status_indicator.itemconfig(self.status_circle, fill=color)
            self.status_label.config(text=text, foreground=color)
            if getattr(self, 'sb_status_label', None) is not None:
                self.sb_status_label.config(text="● " + text, foreground=color)
            # REQ-005：窗口标题随运行状态联动（停止时恢复基础标题）
            base_title = WINDOW_TITLE
            if text and text != "已停止":
                self.root.title(base_title + " - " + text)
            else:
                self.root.title(base_title)
        except Exception:
            pass

    # ==================== P2 状态条辅助（UI-03） ====================
    def _set_sb_counts(self):
        try:
            self.sb_count_label.config(text="总点击: " + str(self.click_count))
            self.sb_success_label.config(text="成功: " + str(self.success_count))
            self.sb_fail_label.config(text="失败: " + str(self.fail_count))
        except Exception:
            pass

    def _start_runtime_tick(self):
        try:
            self._stop_runtime_tick()
            def _tick():
                if not self.is_running:
                    return
                try:
                    elapsed = int(time.time() - self.start_time)
                    mm = elapsed // 60
                    ss = elapsed % 60
                    self.sb_runtime_label.config(text="运行时长: %02d:%02d" % (mm, ss))
                except Exception:
                    pass
                self._runtime_after_id = self.root.after(1000, _tick)
            self._runtime_after_id = self.root.after(1000, _tick)
        except Exception:
            pass

    def _stop_runtime_tick(self):
        try:
            if self._runtime_after_id is not None:
                self.root.after_cancel(self._runtime_after_id)
                self._runtime_after_id = None
        except Exception:
            pass

    def _set_status(self, text, color):
        self._ui(self._do_set_status, text, color)

    def _set_next(self, text):
        self._ui(self.next_click_label.config, text=text)

    def run_clicking(self):
        """点击主流程（后台线程）：先启动倒计时，再进入点击循环（CX-04）"""
        self.start_time = time.time()
        self.success_count = 0
        self.fail_count = 0
        self._ui(self._set_sb_counts)
        countdown = self.startup_countdown
        if countdown > 0:
            self._ui(self.countdown_bar.config, value=0)
            self._ui(self.sb_countdown_label.config, text=f"{countdown}s")
            for i in range(countdown, 0, -1):
                if not self.is_running:
                    return
                self._set_status(f"{i} 秒后启动", 'orange')
                self._set_next(f"启动倒计时 {i}s")
                self._ui(self.countdown_bar.config, value=int((countdown - i) / countdown * 100))
                self._ui(self.sb_countdown_label.config, text=f"{i}s")
                time.sleep(1)
            if not self.is_running:
                return
        self._ui(self.countdown_bar.config, value=100)
        self._set_status("运行中", 'green')
        self._set_next("--")
        self._ui(self._start_runtime_tick)
        self.click_loop()
        self._ui(self._stop_runtime_tick)
        self._ui(self.countdown_bar.config, value=0)

    def _effective_interval_seconds(self):
        """按间隔单位换算为秒（CX-07）：优先用启动时缓存，避免后台线程读 Tk 变量"""
        val = getattr(self, 'interval_seconds_cache', None)
        if val is None:
            try:
                val = float(self.interval_var.get())
            except ValueError:
                val = 1.0
        if val < 0:
            val = 0.0
        if self.interval_unit == 'ms':
            return val / 1000.0
        return val

    def _on_interval_hot_update(self, *args):
        """FR-A03：运行中修改间隔后防抖 120ms 生效，避免逐字符改缓存。"""
        if not getattr(self, 'is_running', False):
            return
        try:
            if self._interval_hot_after_id is not None:
                self.root.after_cancel(self._interval_hot_after_id)
            self._interval_hot_after_id = self.root.after(120, self._apply_interval_hot_update)
        except Exception:
            pass

    def _apply_interval_hot_update(self):
        self._interval_hot_after_id = None
        if not getattr(self, 'is_running', False):
            return
        try:
            value = int(self.interval_var.get().strip())
            unit = self.interval_unit_var.get()
            if value < 0 or unit not in ('s', 'ms'):
                return
            self.interval_unit = unit
            self.interval_seconds_cache = value / 1000.0 if unit == 'ms' else float(value)
            self.config['interval_seconds'] = value
            self.config['interval_unit'] = unit
            self._interval_change_event.set()
            self.log_message("运行参数热更新：间隔=" + str(value) + ("毫秒" if unit == 'ms' else "秒"))
        except (ValueError, tk.TclError):
            pass

    def _jittered_wait(self, base_seconds):
        """返回叠加 jitter 后的等待秒数。"""
        if base_seconds <= 0:
            return 0.0
        jp = self.jitter_pct
        if jp and jp > 0:
            factor = 1.0 + _RANDOM.uniform(-jp / 100.0, jp / 100.0)
            return max(0.0, base_seconds * factor)
        return base_seconds

    def _wait_interval(self, base_seconds):
        """按 jitter 随机化后分段等待，期间可响应停止、failsafe 与参数热更新"""
        wait = self._jittered_wait(base_seconds)
        if wait <= 0:
            return self.is_running
        show_countdown = base_seconds >= 1.0 and self.interval_unit == 's'
        step = 0.05
        remaining = wait
        while remaining > 0 and self.is_running:
            if self._interval_change_event.is_set():
                self._interval_change_event.clear()
                base_seconds = self._effective_interval_seconds()
                wait = self._jittered_wait(base_seconds)
                show_countdown = base_seconds >= 1.0 and self.interval_unit == 's'
                remaining = wait
                continue
            if show_countdown:
                self._set_next(f"{max(0, int(remaining))}秒")
            chunk = min(step, remaining)
            time.sleep(chunk)
            remaining -= chunk
        if not show_countdown and self.is_running:
            self._set_next("ms 模式")
        return self.is_running

    def _failsafe_triggered(self, base_pos):
        """鼠标相对基线位移超过 20px 时视为触发 failsafe。"""
        if not base_pos:
            return False
        cur = get_cursor_pos()
        dx = cur[0] - base_pos[0]
        dy = cur[1] - base_pos[1]
        return (dx * dx + dy * dy) ** 0.5 > 20

    def _next_click_point(self, points, point_idx):
        """按多点位序列或当前点击模式取下一个坐标。"""
        if points:
            pt = points[point_idx % len(points)]
            return int(pt['x']), int(pt['y']), point_idx + 1
        x, y = self.get_click_position()
        return x, y, point_idx

    def _move_before_click(self, x, y):
        """鼠标跟随开启时平滑移动到目标点。"""
        if not getattr(self, 'mouse_follow_cache', True):
            return
        try:
            speed = getattr(self, 'mouse_speed_cache', 0.1)
            duration = max(0.1, 1.0 - speed)
            self.smooth_move_to(x, y, duration=duration)
            time.sleep(0.1)
        except Exception as e:
            self.log_message(f"鼠标跟随失败: {e}")

    def _click_once_at(self, x, y):
        """执行一次点击（或仅移动），并刷新计数显示。"""
        if getattr(self, 'mouse_move_only_cache', False):
            self.log_message(f"仅移动到位置 ({x}, {y})，未执行点击")
            return
        # FN-01/FN-02：支持按键类型与按住时长
        ok = click_mouse(x, y, button=self.click_button, hold_ms=self.hold_ms)
        if ok:
            self.log_message(f"在位置 ({x}, {y}) 执行点击[按键={self.click_button}]")
        else:
            if _pyautogui_click(x, y, self.click_button):
                self.log_message(f"使用pyautogui在位置 ({x}, {y}) 执行点击")
            else:
                self.log_message(f"点击失败且 pyautogui 不可用: ({x}, {y})")
        self.click_count += 1
        self.success_count = self.click_count
        self._ui(self.click_count_label.config, text=str(self.click_count))
        self._ui(self._set_sb_counts)

    def _limit_reached(self):
        """点击次数/运行时长达到上限时停止并返回 True。"""
        if self.click_limit and self.click_count >= self.click_limit:
            self.stop_clicking(reason=f"达到点击次数上限 ({self.click_limit} 次)")
            return True
        if self.duration_limit:
            elapsed_min = (time.time() - self.start_time) / 60.0
            if elapsed_min >= self.duration_limit:
                self.stop_clicking(reason=f"达到运行时长上限 ({self.duration_limit} 分钟)")
                return True
        return False

    def _target_window_ok(self):
        if not getattr(self, 'target_window_cache', ''):
            return True
        title, proc = get_foreground_window_info()
        return target_window_matches(self.target_window_cache, title, proc)

    def _pause_for_target_window(self):
        """FR-E03：前台窗口不匹配时暂停点击，切回目标窗口后自动恢复。"""
        if not getattr(self, 'target_window_cache', ''):
            return self.is_running
        while self.is_running:
            if self._target_window_ok():
                if getattr(self, '_window_mismatch_active', False):
                    self._window_mismatch_active = False
                    self.log_message("目标窗口已恢复，自动继续点击")
                return True
            if not getattr(self, '_window_mismatch_active', False):
                self._window_mismatch_active = True
                self.log_message("前台窗口不匹配，已暂停点击（切回目标窗口后恢复）")
                self.show_operation_message(
                    "前台窗口不匹配，已暂停点击；切回目标窗口后自动恢复", level='operation')
            time.sleep(0.2)
        return False

    def _wait_exact(self, seconds):
        """高精度等待：短间隔用 sleep + 自旋补齐，避免 Windows 定时器粒度造成漂移。"""
        if seconds <= 0:
            return self.is_running
        deadline = time.perf_counter() + seconds
        while self.is_running:
            if self._interval_change_event.is_set():
                self._interval_change_event.clear()
                return True
            remain = deadline - time.perf_counter()
            if remain <= 0:
                break
            if remain > 0.004:
                time.sleep(min(max(0.0005, remain - 0.003), 0.05))
            else:
                time.sleep(0.0002)
        return self.is_running

    def click_loop(self):
        # 多点位序列模式（FN-03）
        points = self.multi_points if self.use_multi_points else None
        point_idx = 0
        last_click_at = None
        lead_est = 0.001  # 等待结束到点击动作之间的预估开销，按实测自适应
        while self.is_running:
            try:
                base = self._effective_interval_seconds()
                if getattr(self, 'prevent_sleep_cache', False):
                    self.prevent_system_sleep()

                # 安全：鼠标位移 failsafe 基线（CX-01）
                failsafe_base = get_cursor_pos() if self.failsafe_enabled else None

                # 等待一个间隔（含随机抖动），期间可响应停止（CX-07）
                # 短间隔按“上次点击时刻 + 间隔”排程，补偿点击/校验开销，避免累积漂移。
                scheduled_target = None
                if base <= 0.05 and last_click_at is not None:
                    scheduled_target = last_click_at + self._jittered_wait(base) - lead_est
                    if not self._wait_exact(scheduled_target - time.perf_counter()):
                        break
                else:
                    if not self._wait_interval(base):
                        break

                # 安全：运行中若开启 failsafe 且鼠标被移动 >20px，立即急停（CX-01）
                if self.failsafe_enabled and self.is_running and self._failsafe_triggered(failsafe_base):
                    self.stop_clicking(reason="鼠标位移触发安全停止 (failsafe)")
                    return

                # FR-E03：前台窗口校验，不匹配则循环等待（不点击），切回后继续
                if not self._pause_for_target_window():
                    return

                # 计算本次点击坐标并执行（含鼠标跟随/仅移动模式）
                x, y, point_idx = self._next_click_point(points, point_idx)
                self._move_before_click(x, y)
                click_at = time.perf_counter()
                self._click_once_at(x, y)
                last_click_at = click_at
                if scheduled_target is not None:
                    excess = click_at - scheduled_target
                    lead_est = 0.7 * lead_est + 0.3 * max(0.0, min(excess, base))

                # 安全：点击次数 / 运行时长上限（CX-02）
                if self._limit_reached():
                    break

            except Exception as e:
                self.log_message(f"点击过程中发生错误: {e}")
                self.fail_count += 1
                self._ui(self._set_sb_counts)
                time.sleep(1)
                
    def _read_interval(self):
        """读取并校验点击间隔，非法时行内红字提示并返回 None。"""
        try:
            value = int(self.interval_var.get())
        except ValueError:
            self.show_field_error("点击间隔必须为整数")
            return None
        if value < 1:
            self.show_field_error("点击间隔必须 >= 1")
            return None
        if value > 3600:
            self.show_field_error("点击间隔必须 <= 3600")
            return None
        self.clear_field_error()
        return value

    def _read_countdown(self):
        """读取并校验启动倒计时（0-5 秒）。"""
        try:
            value = int(self.countdown_var.get())
        except ValueError:
            self.show_field_error("启动倒计时必须为整数")
            return None
        if value < 0 or value > 5:
            self.show_field_error("启动倒计时必须在 0-5 秒之间")
            return None
        self.clear_field_error()
        return value

    def _read_click_limit(self):
        """读取并校验点击次数上限（0 表示无限）。"""
        try:
            value = int(self.click_limit_var.get())
        except ValueError:
            self.show_field_error("点击次数上限必须为整数")
            return None
        if value < 0:
            self.show_field_error("点击次数上限不能为负数")
            return None
        self.clear_field_error()
        return value

    def _read_duration_limit(self):
        """读取并校验运行时长上限（分钟，0 表示无限）。"""
        try:
            value = int(self.duration_limit_var.get())
        except ValueError:
            self.show_field_error("运行时长上限必须为整数")
            return None
        if value < 0:
            self.show_field_error("运行时长上限不能为负数")
            return None
        self.clear_field_error()
        return value

    def _read_jitter(self):
        """读取并校验随机抖动百分比（0-100）。"""
        try:
            value = int(self.jitter_var.get())
        except ValueError:
            self.show_field_error("随机抖动必须为整数")
            return None
        if value < 0 or value > 100:
            self.show_field_error("随机抖动必须在 0-100 之间")
            return None
        self.clear_field_error()
        return value

    def _read_hold_ms(self):
        """读取并校验按住时长（毫秒）。"""
        try:
            value = int(self.hold_ms_var.get())
        except ValueError:
            self.show_field_error("按住时长必须为整数")
            return None
        if value < 0:
            self.show_field_error("按住时长不能为负数")
            return None
        self.clear_field_error()
        return value

    def _startup_summary(self, interval, countdown, click_limit, duration_limit, jitter, hold_ms):
        """拼装启动日志摘要（把可选片段从主流程中拆出，降低认知复杂度）。"""
        unit_text = "毫秒" if self.interval_unit == 'ms' else "秒"
        parts = [
            "启动配置: 模式=" + str(self.config['click_mode']) + ", 间隔=" + str(interval) + unit_text,
            ", 按键=" + str(self.click_button) + ", 按住=" + str(hold_ms) + "ms",
        ]
        if jitter:
            parts.append(f", 抖动={jitter}%")
        if self.use_multi_points:
            parts.append(", 多点位")
        if countdown:
            parts.append(", 倒计时=" + str(countdown) + "秒")
        if click_limit:
            parts.append(", 次数上限=" + str(click_limit))
        if duration_limit:
            parts.append(", 时长上限=" + str(duration_limit) + "分钟")
        if self.failsafe_enabled:
            parts.append(", failsafe开")
        return "".join(parts)

    def start_clicking(self):
        # FR-L01：统一守卫，按钮与 F6 热键（toggle_clicking）都经过此处，避免绕过 UI 禁用
        if not self.input_ok:
            messagebox.showerror("启动已禁用", self.input_reason)
            return
        try:
            interval = self._read_interval()
            if interval is None:
                return
            countdown = self._read_countdown()
            if countdown is None:
                return
            click_limit = self._read_click_limit()
            if click_limit is None:
                return
            duration_limit = self._read_duration_limit()
            if duration_limit is None:
                return
            jitter = self._read_jitter()
            if jitter is None:
                return
            hold_ms = self._read_hold_ms()
            if hold_ms is None:
                return

            self.is_running = True
            self.click_count = 0
            self.countdown_cancelled = False
            self._interval_change_event.clear()
            self.startup_countdown = countdown
            self.click_limit = click_limit
            self.duration_limit = duration_limit
            self.failsafe_enabled = self.failsafe_var.get()
            self.start_time = time.time()
            # P1 状态（FN-01 / FN-02 / CX-07 / FN-03 / CX-11）
            self.interval_unit = self.interval_unit_var.get()
            self.jitter_pct = jitter
            self.click_button = self.click_button_var.get()
            self.hold_ms = hold_ms
            self.use_multi_points = self.use_multi_points_var.get()
            # 后台点击线程只读以下缓存，禁止在非主线程调用 Tk Var.get()
            self.interval_seconds_cache = interval
            self.prevent_sleep_cache = self.prevent_sleep_var.get()
            self.target_window_cache = self.target_window_var.get().strip()
            self._window_mismatch_active = False
            self.mouse_follow_cache = self.mouse_follow_var.get()
            self.mouse_speed_cache = float(self.mouse_speed_var.get())
            self.mouse_move_only_cache = self.mouse_move_only_var.get()
            self.click_mode_cache = self.mode_var.get()
            self.config['autostart'] = self.autostart_var.get()
            self.multi_points = self.config.get('multi_points', [])

            self.config['interval_seconds'] = interval
            self.config['click_mode'] = self.mode_var.get()
            self.config['prevent_sleep'] = self.prevent_sleep_var.get()
            self.config['mouse_follow_enabled'] = self.mouse_follow_var.get()
            self.config['mouse_move_speed'] = float(self.mouse_speed_var.get())
            self.config['mouse_move_only'] = self.mouse_move_only_var.get()
            # P0 持久化安全/体验参数（CX-02 / CX-04 / CX-06）
            self.config['startup_countdown'] = self.startup_countdown
            self.config['click_limit'] = self.click_limit
            self.config['duration_limit'] = self.duration_limit
            self.config['failsafe_enabled'] = self.failsafe_enabled
            self.config['close_to_tray'] = self.close_to_tray_var.get()
            # P1 持久化（FN-01 / FN-02 / CX-07 / FN-03 / CX-11）
            self.config['interval_unit'] = self.interval_unit
            self.config['jitter_pct'] = self.jitter_pct
            self.config['click_button'] = self.click_button
            self.config['hold_ms'] = self.hold_ms
            self.config['use_multi_points'] = self.use_multi_points
            self.save_config()

            self.log_message(self._startup_summary(
                interval, countdown, click_limit, duration_limit, jitter, hold_ms))
            if self.mouse_move_only_var.get():
                self.log_message("只移动不点击模式: 启用")

            self.click_thread = threading.Thread(target=self.run_clicking, daemon=True)
            self.click_thread.start()

            # 更新状态指示器（含底部状态条与窗口标题联动）
            self._do_set_status("运行中", 'green')

            # 更新按钮状态（倒计时期间停止按钮即作为取消键）
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            # FR-A03：运行中允许修改间隔，由 trace 热更新到点击线程缓存
            self.interval_entry.config(state=tk.NORMAL)

            self.log_message("自动点击已启动")

            # CX-12：托盘状态区分（运行中）
            self._update_tray_status(True)

        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字")
        except Exception as e:
            self.log_message(f"启动失败: {e}")
            messagebox.showerror("错误", f"启动失败: {e}")
            
    def _update_tray_status(self, running):
        """CX-12：托盘状态区分（运行/停止），同步托盘菜单与 Windows 提示气泡"""
        try:
            # Windows 托盘提示气泡（szTip）随运行状态变化
            if IS_WINDOWS and getattr(self, 'tray_icon_created', False) and hasattr(self, 'tray_nid'):
                try:
                    tip = "AutoClicker - 运行中" if running else "AutoClicker - 已停止"
                    new_nid = self.tray_nid[:5] + (tip,)
                    win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, new_nid)
                    self.tray_nid = new_nid
                except Exception:
                    pass
            # 托盘右键菜单顶部插入动态“停止/启动”项，区分当前状态
            menu = getattr(self, 'tray_menu', None)
            if menu is not None:
                try:
                    # 先删掉上一次的动态项及其分隔符，避免每次启停多一条分隔线
                    if getattr(self, '_tray_dynamic_present', False):
                        menu.delete(0, 1)
                except Exception:
                    pass
                if running:
                    menu.insert_command(0, label="停止点击", command=self.emergency_stop)
                else:
                    menu.insert_command(0, label="启动点击", command=self.start_clicking)
                menu.insert_separator(1)
                self._tray_dynamic_present = True
        except Exception:
            pass

    def stop_clicking(self, reason=""):
        self.is_running = False
        self.countdown_cancelled = False

        # REQ-004：记录最近一次运行统计快照（供导出）
        try:
            runtime = max(0.0, time.time() - getattr(self, 'start_time', time.time()))
            self.last_run_stats = {
                'timestamp': datetime.now().isoformat(timespec='seconds'),
                'click_count': getattr(self, 'click_count', 0),
                'success_count': getattr(self, 'success_count', 0),
                'fail_count': getattr(self, 'fail_count', 0),
                'runtime_seconds': round(runtime, 1),
                'interval_seconds': self._effective_interval_seconds(),
                'mode': self.config.get('click_mode', ''),
                'button': getattr(self, 'click_button', ''),
            }
        except Exception:
            pass

        if self.click_thread:
            try:
                # 自动停止（点击上限/failsafe）会在点击线程内回调本方法，
                # 此时 join 自身会抛 RuntimeError 并中断后续状态复位（CX-02）。
                if threading.current_thread() is not self.click_thread:
                    self.click_thread.join(timeout=2)
            except RuntimeError:
                pass

        self.allow_system_sleep()

        if threading.current_thread() is threading.main_thread():
            self._apply_stopped_ui()
        else:
            self._ui(self._apply_stopped_ui)

        if reason:
            self.log_message("自动点击已停止（原因：" + str(reason) + "）")
        else:
            self.log_message("自动点击已停止")

    def _apply_stopped_ui(self):
        """停止后的主线程 UI 复位（后台线程自动停止时经 _ui 队列调用）。"""
        # 更新状态指示器（含底部状态条与窗口标题联动）
        self._do_set_status("已停止", self._color('danger'))
        self.next_click_label.config(text="--")

        # P2 状态条复位（UI-03）
        self._stop_runtime_tick()
        try:
            self.countdown_bar['value'] = 0
            self.sb_countdown_label.config(text="--")
            self.sb_runtime_label.config(text="运行时长: 00:00")
            self._set_sb_counts()
        except Exception:
            pass

        # 更新按钮状态
        # FR-L01：Wayland 降级下停止后不得把启动按钮误恢复为可用
        self.start_btn.config(state=tk.NORMAL if self.input_ok else tk.DISABLED)
        self.stop_btn.config(state=tk.DISABLED)
        self.interval_entry.config(state=tk.NORMAL)

        # CX-12：托盘状态区分（已停止）
        self._update_tray_status(False)

    def emergency_stop(self):
        """P0 独立急停（CX-01）：仅作为停止入口，统一走 stop_clicking(reason)"""
        if self.is_running:
            self.stop_clicking(reason="用户按下紧急停止键 (F8/Esc)")
            
    def toggle_clicking(self):
        if self.is_running:
            self.stop_clicking()
        else:
            self.start_clicking()
            
    def test_click(self):
        # FR-L01：测试点击同样是真实模拟输入，Wayland 下先给出原因，避免"点了没反应"
        if not self.input_ok:
            messagebox.showerror("测试点击已禁用", self.input_reason)
            return
        try:
            x, y = self.get_click_position()

            result = messagebox.askyesno("测试点击",
                                         f"将在位置 ({x}, {y}) 执行一次真实点击\n是否继续？")

            if result:
                # 修复 F-1：原先只弹窗不真实点击，现移动并执行一次真实点击（CX-03）
                move_mouse(x, y)
                time.sleep(0.05)
                ok = click_mouse(x, y)
                landed = get_cursor_pos()
                self.log_message("测试点击已执行：目标=(" + str(x) + ", " + str(y) + ")，"
                                "落点=" + str(landed) + "，结果=" + ("成功" if ok else "降级pyautogui"))
                messagebox.showinfo("测试点击",
                                   f"已在位置 ({x}, {y}) 执行一次真实点击\n实际落点：{landed}")

        except Exception as e:
            error_msg = f"测试点击失败: {e}"
            self.log_message(error_msg)
            messagebox.showerror("错误", error_msg)
    
    def clear_log(self):
        """清空日志（UI-04）：清空缓冲区与文本框"""
        try:
            self._log_buffer = []
            self._render_log()
            print("日志已清空")
        except Exception as e:
            print(f"清空日志失败: {e}")

    # ==================== P2 日志：分级着色 / 过滤 / 复制（UI-04） ====================
    def _log_level(self, msg):
        m = msg.lower()
        if any(k in msg for k in ('失败', '错误', '异常', 'error', 'exception', 'traceback')) or 'fail' in m:
            return 'err'
        if any(k in msg for k in ('警告', '警示')) or 'warn' in m:
            return 'warn'
        return ''

    @staticmethod
    def _log_tag(level):
        """日志级别到 Text tag 的映射（S3358：避免嵌套三元表达式）"""
        if level == 'err':
            return 'lvl_err'
        if level == 'warn':
            return 'lvl_warn'
        return ''

    def _render_log(self):
        """按当前过滤条件重绘日志文本框（UI-04）"""
        try:
            flt = (self._log_filter or '').lower()
            self.log_text.config(state=tk.NORMAL)
            self.log_text.delete(1.0, tk.END)
            for entry, level in self._log_buffer:
                if flt and flt not in entry.lower():
                    continue
                tag = self._log_tag(level)
                self.log_text.insert(tk.END, entry, tag)
            self._trim_log_widget()
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        except Exception:
            pass

    def filter_log(self):
        """应用关键字过滤（UI-04）"""
        try:
            self._log_filter = (self.log_filter_var.get() or '').strip()
            self._render_log()
        except Exception:
            pass

    def copy_log(self):
        """复制当前（过滤后）日志内容到剪贴板（UI-04）"""
        try:
            flt = (self._log_filter or '').lower()
            lines = [e for e, _ in self._log_buffer if not flt or flt in e.lower()]
            text = ''.join(lines)
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.log_message("已复制日志内容到剪贴板")
        except Exception as e:
            print(f"复制日志失败: {e}")

    def toggle_log_collapse(self):
        """折叠/展开日志内容区（UI-01）"""
        try:
            if getattr(self, '_log_collapsed', False):
                self.log_inner.pack(fill=tk.BOTH, expand=True)
                self.log_toggle_btn.config(text="收起")
                self._log_collapsed = False
            else:
                self.log_inner.pack_forget()
                self.log_toggle_btn.config(text="展开")
                self._log_collapsed = True
        except Exception:
            pass

    def _trim_log_widget(self):
        """FR-H01：界面只保留最近 500 行，避免 8 小时运行后 Text 控件无限增长。"""
        try:
            end_line = int(self.log_text.index('end-1c').split('.')[0])
            if end_line > 500:
                self.log_text.delete('1.0', f'{end_line - 500}.0')
        except Exception:
            pass

    def _append_log_ui(self, log_entry, level):
        """主线程写入日志控件；后台线程统一通过 _ui() 投递到主线程。"""
        try:
            if self._log_filter:
                self._render_log()
            else:
                self.log_text.config(state=tk.NORMAL)
                tag = self._log_tag(level)
                self.log_text.insert(tk.END, log_entry, tag)
                self._trim_log_widget()
                self.log_text.see(tk.END)
                self.log_text.config(state=tk.DISABLED)
        except Exception:
            pass

    def log_message(self, message):
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_entry = f"[{timestamp}] {message}\n"
            # 输出到控制台
            print(log_entry)
            # CX-10：同时写入磁盘日志
            if getattr(self, '_file_logger', None) is not None:
                try:
                    self._file_logger.info(message)
                except Exception:
                    pass
            else:
                pending = getattr(self, '_pending_logs', None)
                if pending is not None:
                    pending.append(message)
            # UI-04：写入缓冲区并按过滤条件渲染
            level = self._log_level(message)
            self._log_buffer.append((log_entry, level))
            if len(self._log_buffer) > 2000:
                self._log_buffer = self._log_buffer[-2000:]
            if threading.current_thread() is threading.main_thread():
                self._append_log_ui(log_entry, level)
            else:
                self._ui(self._append_log_ui, log_entry, level)
        except Exception as e:
            print(f"日志写入失败: {e}")
    
    def setup_tray_icon(self):
        """设置系统托盘图标和菜单（跨平台）"""
        try:
            # 创建原生托盘菜单（使用tkinter Menu）
            self._tray_dynamic_present = False
            self.tray_menu = tk.Menu(self.root, tearoff=0,
                                     bg=self._color('surface'), fg=self._color('fg'))
            self.tray_menu.add_command(label="显示窗口", command=self.show_from_tray)
            self.tray_menu.add_separator()
            self.tray_menu.add_command(label="退出程序", command=self.exit_from_tray)
            
            self.tray_enabled = True
            self.tray_icon = None
            self.tray_icon_created = False
            
            # Windows 系统托盘
            if IS_WINDOWS and HAS_WIN32GUI:
                self._create_windows_tray_icon()
                if getattr(self, 'tray_icon_created', False):
                    self._update_tray_status(False)
            # Linux 系统托盘
            elif IS_LINUX and HAS_PYSTRAY and HAS_PIL:
                self._create_linux_tray_icon()
            
        except Exception as e:
            print(f"设置托盘菜单失败: {e}")
            self.tray_enabled = False
    
    def _create_linux_tray_icon(self):
        """创建 Linux 系统托盘图标（使用 pystray）"""
        try:
            from pystray import Menu, MenuItem
            
            def on_show(icon, item):
                self.show_window()
            
            def on_exit(icon, item):
                icon.stop()
                self.exit_application()
            
            menu = Menu(
                MenuItem("显示窗口", on_show, default=True),
                Menu.SEPARATOR,
                MenuItem("退出程序", on_exit)
            )
            
            icon_path = self._get_icon_path()
            if icon_path and os.path.exists(icon_path):
                try:
                    image = Image.open(icon_path)
                except Exception:
                    image = self._create_default_icon()
            else:
                image = self._create_default_icon()
            
            self.tray_icon = pystray.Icon(
                "AutoClicker",
                image,
                "自动点击工具",
                menu
            )
            
            def run_tray():
                self.tray_icon.run()
            
            tray_thread = threading.Thread(target=run_tray, daemon=True)
            tray_thread.start()
            print("Linux系统托盘图标创建成功")
            
        except Exception as e:
            print(f"创建Linux托盘图标失败: {e}")
    
    def _create_default_icon(self):
        """创建默认托盘图标"""
        try:
            from PIL import Image, ImageDraw
            img = Image.new('RGB', (64, 64), color='#28a745')
            draw = ImageDraw.Draw(img)
            draw.rectangle([10, 10, 54, 54], fill='#ffffff', outline='#28a745', width=3)
            draw.ellipse([20, 20, 44, 44], fill='#28a745')
            return img
        except Exception:
            return None
    
    def _create_windows_tray_icon(self):
        """创建Windows系统托盘图标"""
        try:
            # 创建一个隐藏的消息窗口来接收托盘消息
            # 类名带进程号：多个 AutoClicker 实例并存时，固定类名会触发
            # RegisterClass「类已存在」，导致后启动的实例没有托盘图标（T05257）。
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = self._tray_window_proc
            wc.lpszClassName = "AutoClickerTrayMessageWindow_%d" % os.getpid()
            wc.hInstance = win32api.GetModuleHandle(None)
            
            class_atom = win32gui.RegisterClass(wc)
            
            # 创建隐藏的消息窗口
            self.tray_hwnd = win32gui.CreateWindow(
                class_atom,
                "AutoClickerTray",
                0, 0, 0, 0, 0,
                0, 0, wc.hInstance, None
            )
            
            # 加载自定义图标（浅/深两套 16/32px，由 _get_icon_path 按主题选择）
            hicon = None
            icon_path = self._get_icon_path()
            if icon_path and os.path.exists(icon_path):
                try:
                    hicon = win32gui.LoadImage(
                        None,
                        icon_path,
                        win32con.IMAGE_ICON,
                        32, 32,
                        win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE
                    )
                except Exception as e:
                    print(f"加载自定义图标失败: {e}")
            
            # 如果自定义图标加载失败，使用系统默认图标
            if not hicon:
                hicon = win32gui.LoadIcon(0, win32con.IDI_APPLICATION)
            
            # 创建托盘图标数据结构
            flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP
            
            # 创建托盘图标
            nid = (self.tray_hwnd,  # hWnd
                   0,               # uID
                   flags,           # uFlags
                   win32con.WM_USER + 20,  # uCallbackMessage
                   hicon,           # hIcon
                   "自动点击工具")  # szTip
            
            # 添加托盘图标（pywin32 的 Shell_NotifyIcon 成功时返回 None，
            # 不能按布尔值判断，否则每次都会误报「创建失败」并跳过后续状态同步）
            try:
                win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)
                self.tray_nid = nid
                self.tray_icon_created = True
                print("系统托盘图标创建成功")
            except Exception as e:
                print(f"系统托盘图标创建失败: {e}")
                self.tray_icon_created = False
                
        except Exception as e:
            print(f"创建Windows托盘图标失败: {e}")
            self.tray_icon_created = False
    
    def _get_icon_path(self):
        """获取图标文件路径：按当前主题选浅色/深色托盘图标。"""
        try:
            # 获取程序所在目录
            if getattr(sys, 'frozen', False):
                # 打包后的exe
                base_path = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(sys.executable)
            else:
                # 开发环境
                base_path = os.path.dirname(__file__)
            
            # 查找当前主题对应的双套图标（16/32px 已打包进 ICO）
            dark = getattr(self, '_current_palette', {}).get('bg') == self.THEMES['dark']['bg']
            preferred = 'tray_dark.ico' if dark else 'tray_light.ico'
            for name in (preferred, 'tray.ico', 'autoclicker.ico'):
                icon_path = os.path.join(base_path, 'icons', name)
                if os.path.exists(icon_path):
                    return icon_path
                
        except Exception:
            pass
        return None

    def _refresh_tray_icon(self):
        """主题切换后刷新托盘图标，避免深色任务栏仍显示浅色图标（T05257）。"""
        if not (IS_WINDOWS and HAS_WIN32GUI and getattr(self, 'tray_icon_created', False)):
            return
        try:
            icon_path = self._get_icon_path()
            if not icon_path or not os.path.exists(icon_path):
                return
            hicon = win32gui.LoadImage(
                None, icon_path, win32con.IMAGE_ICON, 32, 32,
                win32con.LR_LOADFROMFILE | win32con.LR_DEFAULTSIZE)
            if not hicon:
                return
            new_nid = self.tray_nid[:4] + (hicon, self.tray_nid[5])
            win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY, new_nid)
            self.tray_nid = new_nid
        except Exception as e:
            print(f"刷新托盘图标失败: {e}")
    
    def _tray_window_proc(self, hwnd, msg, wparam, lparam):
        """托盘消息窗口处理函数"""
        if msg == win32con.WM_USER + 20:
            if lparam == win32con.WM_LBUTTONDBLCLK:
                # 双击左键 - 显示窗口
                self.show_from_tray()
            elif lparam == win32con.WM_RBUTTONUP:
                # 右键单击 - 显示托盘菜单
                self.show_tray_menu()
        elif msg == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)
    
    def _remove_tray_icon(self):
        """移除系统托盘图标"""
        try:
            # 移除Windows托盘图标
            if HAS_WIN32GUI and hasattr(self, 'tray_icon_created') and self.tray_icon_created:
                if hasattr(self, 'tray_nid'):
                    win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, self.tray_nid)
                    self.tray_icon_created = False
            
            # 隐藏托盘菜单（如果正在显示）
            self.hide_tray_menu()
        except Exception:
            pass
    
    def minimize_to_tray(self):
        """最小化到系统托盘"""
        try:
            # 隐藏主窗口
            self.root.withdraw()
        except Exception as e:
            print(f"最小化到托盘失败: {e}")
    
    def show_tray_menu(self, event=None):
        """显示托盘右键菜单：根据鼠标位置自适应定位，避免菜单超出屏幕边界。"""
        try:
            if hasattr(self, 'tray_menu'):
                # 使用Windows API获取鼠标位置（更可靠）
                try:
                    import win32gui
                    cursor_pos = win32gui.GetCursorPos()
                    x, y = cursor_pos[0], cursor_pos[1]
                except Exception:
                    # 备用方案：使用tkinter获取鼠标位置
                    x = self.root.winfo_pointerx()
                    y = self.root.winfo_pointery()
                
                screen_width = self.root.winfo_screenwidth()
                screen_height = self.root.winfo_screenheight()

                menu_width = 150
                menu_height = 80

                if x + menu_width > screen_width:
                    x = x - menu_width

                if y + menu_height > screen_height:
                    y = y - menu_height

                x = max(0, x)
                y = max(0, y)

                self.tray_menu.post(x, y)
                
        except Exception as e:
            print(f"显示托盘菜单失败: {e}")
    
    def hide_tray_menu(self):
        """隐藏托盘菜单"""
        try:
            if hasattr(self, 'tray_menu'):
                self.tray_menu.unpost()
        except Exception:
            pass
    
    def show_from_tray(self):
        """从托盘显示主窗口"""
        self.hide_tray_menu()
        self.show_window()
    
    def exit_from_tray(self):
        """从托盘退出程序"""
        self.hide_tray_menu()
        self.exit_application()
    
    def show_window(self):
        """从托盘还原窗口"""
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            self.log_message("程序已从托盘还原")
        except Exception as e:
            print(f"还原窗口失败: {e}")
    
    def on_closing(self):
        """窗口关闭处理：根据配置选择最小化到托盘或直接退出（CX-06）"""
        if self.config.get('close_to_tray', True):
            # 隐藏窗口而不是关闭
            self.root.withdraw()
            self.log_message("程序已最小化到系统托盘")
        else:
            self.exit_application()
    
    def _shutdown_runtime(self):
        """停止托盘、点击线程、保活与全局热键。"""
        try:
            self._remove_tray_icon()
        except Exception:
            pass
        if self.click_thread and self.click_thread.is_alive():
            try:
                self.click_thread.join(timeout=0.2)
            except Exception:
                pass
        try:
            self.stop_keepalive()
        except Exception:
            pass
        try:
            self.allow_system_sleep()
        except Exception:
            pass
        if keyboard:
            try:
                keyboard.unhook_all()
            except Exception:
                pass

    def _persist_state_on_exit(self):
        """退出前把当前 UI 状态写回配置。"""
        try:
            self.config['interval_seconds'] = int(self.interval_var.get())
            self.config['click_mode'] = self.mode_var.get()
            self.config['prevent_sleep'] = self.prevent_sleep_var.get()
            self.config['mouse_follow_enabled'] = self.mouse_follow_var.get()
            self.config['mouse_move_speed'] = float(self.mouse_speed_var.get())
            self.config['mouse_move_only'] = self.mouse_move_only_var.get()
            self.save_config()
        except Exception:
            pass

    def _cleanup_linux_instance_lock(self):
        """清理 Linux 单实例锁文件。"""
        if not (IS_LINUX and SINGLE_INSTANCE_LOCK_FD):
            return
        try:
            SINGLE_INSTANCE_LOCK_FD.close()
        except OSError:
            pass
        try:
            if os.path.exists(SINGLE_INSTANCE_LOCK_FILE):
                os.remove(SINGLE_INSTANCE_LOCK_FILE)
        except OSError:
            pass

    def exit_application(self):
        """完全退出应用程序 - 从托盘菜单调用（跨平台）"""
        self.is_running = False
        self._shutdown_runtime()
        self._persist_state_on_exit()
        self._cleanup_linux_instance_lock()
        self.root.destroy()


def activate_existing_window():
    """激活已存在的程序窗口（跨平台）"""
    if IS_WINDOWS:
        if EXISTING_WINDOW_HWND:
            try:
                win32gui.ShowWindow(EXISTING_WINDOW_HWND, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(EXISTING_WINDOW_HWND)
            except Exception:
                pass
        elif HAS_WIN32GUI:
            try:
                hwnd = win32gui.FindWindow(None, WINDOW_TITLE)
                if hwnd:
                    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
    elif IS_LINUX:
        print("程序已在运行中")


def show_single_instance_warning():
    """显示单实例警告"""
    root = tk.Tk()
    root.withdraw()
    messagebox.showwarning("提示", "程序已在运行，请勿重复启动！")
    root.destroy()


def setup_dpi_awareness():
    """6.11.2 DPI 适配：开启进程级 DPI 感知，使点击坐标与物理像素一致。
    必须在创建 Tk 根窗口之前调用（否则对已创建的窗口不生效）。"""
    if sys.platform == 'win32':
        try:
            from ctypes import windll
            # 优先 per-monitor v2，回退 v1，再回退 SetProcessDPIAware
            try:
                windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                try:
                    windll.shcore.SetProcessDpiAwareness(1)
                except Exception:
                    windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main():
    if not IS_SINGLE_INSTANCE:
        activate_existing_window()
        show_single_instance_warning()
        return
    
    setup_dpi_awareness()  # 必须在 tk.Tk() 之前，保证 DPI 感知对根窗口生效
    install_setting_restore_guards()
    root = tk.Tk()

    app = AutoClicker(root)

    app.root.mainloop()


if __name__ == "__main__":
    main()
