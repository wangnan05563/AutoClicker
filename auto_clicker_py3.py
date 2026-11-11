# -*- coding: utf-8 -*-
"""
桌面自动点击工具 - Python 3.14 兼容版
支持 Windows、银河麒麟等多操作系统
支持系统托盘最小化运行
"""

import sys
import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import subprocess
import threading
import time
import random
import json
import logging
import shutil
from logging.handlers import RotatingFileHandler
from datetime import datetime

# ==================== 平台检测 ====================
PLATFORM = sys.platform
IS_WINDOWS = PLATFORM == 'win32'
IS_LINUX = PLATFORM.startswith('linux')
IS_MACOS = PLATFORM == 'darwin'


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
    if not shutil.which('ydotool'):
        return False, 'wayland', (
            "当前为 Wayland 会话，且未检测到 ydotool，无法模拟鼠标输入。\n"
            "请在登录界面切换到 X11 会话；或安装 ydotool 并启动 ydotoold（当前用户需加入 input 组）。"
            + doc)
    # 有 ydotool 二进制也不代表可用：本版本尚未把 ydotool 接入点击后端
    return False, 'wayland', (
        "当前为 Wayland 会话。虽已检测到 ydotool，但本版本尚未接入 ydotool 输入后端，"
        "pyautogui 仍依赖 X11，点击可能落空。\n"
        "请切换到 X11 会话后使用。"
        + doc)


# ==================== 核心依赖 ====================
try:
    import pyautogui
except ImportError:
    print("请安装依赖: pip install pyautogui")
    sys.exit(1)

try:
    import keyboard
except ImportError:
    keyboard = None
    print("keyboard模块未安装，快捷键功能将不可用")

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

# ==================== 平台通用函数 ====================
def windows_move_mouse(x, y):
    """使用 Windows API 移动鼠标"""
    if HAS_WIN32API:
        try:
            ctypes.windll.user32.SetCursorPos(int(x), int(y))
            return True
        except Exception as e:
            print(f"移动鼠标失败：{e}")
            return False
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
    """使用 X11 API 移动鼠标（银河麒麟兼容）"""
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
            # 降级使用 pyautogui
            try:
                pyautogui.moveTo(x, y)
                return True
            except:
                return False
    else:
        try:
            pyautogui.moveTo(x, y)
            return True
        except:
            return False

def linux_click(x, y, button='left', hold_ms=0):
    """使用 X11 API 执行鼠标点击（银河麒麟兼容，支持左/右/中键、双击与按住时长）"""
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
    try:
        pyautogui.click(x, y,
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
        except:
            pass
    return pyautogui.position()

def get_cursor_pos():
    """跨平台获取鼠标位置"""
    if IS_WINDOWS and HAS_WIN32API:
        return win32api.GetCursorPos()
    elif IS_LINUX:
        return linux_get_cursor_pos()
    else:
        return pyautogui.position()

def move_mouse(x, y):
    """跨平台移动鼠标"""
    if IS_WINDOWS:
        return windows_move_mouse(x, y)
    elif IS_LINUX:
        return linux_move_mouse(x, y)
    else:
        pyautogui.moveTo(x, y)
        return True

def click_mouse(x, y, button='left', hold_ms=0):
    """跨平台点击鼠标（支持按键类型与按住时长）"""
    if IS_WINDOWS:
        return windows_click(x, y, button, hold_ms)
    elif IS_LINUX:
        return linux_click(x, y, button, hold_ms)
    else:
        return _pyautogui_click(x, y, button)

# ERROR_ALREADY_EXISTS常量（在pywin32中可能未定义）
ERROR_ALREADY_EXISTS = 183

# 单实例检查 - 使用互斥锁
SINGLE_INSTANCE_MUTEX_NAME = "AutoClicker_SingleInstance_Mutex"
SINGLE_INSTANCE_LOCK_FILE = os.path.expanduser("~/.autoclicker.lock")
WINDOW_TITLE = "桌面自动点击工具 v2.0 (Python 3.14)"
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
            except:
                pass
        
        # 创建锁文件
        if IS_SINGLE_INSTANCE:
            SINGLE_INSTANCE_LOCK_FD = open(SINGLE_INSTANCE_LOCK_FILE, 'w')
            try:
                fcntl.flock(SINGLE_INSTANCE_LOCK_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)
                SINGLE_INSTANCE_LOCK_FD.write(str(os.getpid()))
                SINGLE_INSTANCE_LOCK_FD.flush()
            except:
                IS_SINGLE_INSTANCE = False
                
    except ImportError:
        print("fcntl模块未安装，Linux单实例检查功能将不可用")
    except Exception as e:
        print(f"Linux单实例检查失败: {e}")


class AutoClicker:
    def __init__(self, root):
        self.root = root
        self.root.title(WINDOW_TITLE)
        
        # 窗口尺寸（修正 geometry 与 minsize 矛盾：F-10 / CX-05）
        self.root.geometry("720x800")
        self.root.minsize(700, 760)
        self._init_dpi_awareness()
        
        self.is_running = False
        self.click_thread = None
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
        self.start_time = time.time()

        # P1 功能扩展状态默认值（FN-01 / FN-02 / CX-07 / FN-03）
        self.click_button = 'left'
        self.hold_ms = 10
        self.interval_unit = 's'
        self.jitter_pct = 0
        self.use_multi_points = False
        self.multi_points = []

        # P2 状态可视化默认值（UI-03）
        self.success_count = 0
        self.fail_count = 0
        self._runtime_after_id = None
        self._log_buffer = []  # [(text, level)] 全量日志缓冲（UI-04 过滤用）
        self._log_filter = ''
        self._log_collapsed = False
        # REQ-004 运行统计：最近一次会话快照（供导出）
        self.last_run_stats = {
            'timestamp': '', 'click_count': 0, 'success_count': 0,
            'fail_count': 0, 'runtime_seconds': 0.0,
            'interval_seconds': 0.0, 'mode': '', 'button': '',
        }

        self.setup_logging()
        self.load_config()
        self._init_theme()
        self.setup_ui()
        # 补记 DPI 诊断（此时日志/UI 设施已就绪）
        self.log_message("DPI 适配：系统缩放 %.2f，已据缩放调整渲染" % getattr(self, '_dpi_scale', 1.0))
        self._apply_theme()
        # FR-L01：无可用输入后端时禁用启动（按钮 + 热键通道由 start_clicking 统一守卫兜底）
        if not self.input_ok:
            try:
                self.start_btn.config(state=tk.DISABLED)
            except Exception:
                pass
            self.log_message("Wayland 降级：启动已禁用（会话=%s）" % self.input_session)
        self.setup_hotkeys()
        self.setup_tray_icon()
        if self.theme_mode == 'system':
            self._poll_system_theme()
        
        # 6.9.1 引导与预设配置：首次运行写入推荐安全预设并弹出引导
        if self.first_run:
            self._apply_first_run_preset()
            self.root.after(800, self._show_first_run_guidance)
        
        # 关闭按钮直接退出程序
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
    def setup_logging(self):
        """CX-10：初始化磁盘日志（RotatingFileHandler，单文件 5MB × 5 备份）"""
        try:
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
        except Exception as e:
            # 日志初始化失败不应阻断程序启动
            self._file_logger = None
            print("初始化日志失败: " + str(e))

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
            'click_limit': 0,  # 点击次数上限（0=无限）
            'duration_limit': 0,  # 运行时长上限（分钟，0=无限）
            'failsafe_enabled': False,  # 鼠标位移即停
            'close_to_tray': True,  # 关闭窗口最小化到托盘（否则直接退出）
            # P1 功能扩展（FN-01 / FN-02 / CX-07 / CX-08 / CX-11 / FN-03）
            'click_button': 'left',  # 鼠标按键：left/right/middle/double
            'hold_ms': 10,  # 按住时长（毫秒）
            'interval_unit': 's',  # 间隔单位：s=秒 / ms=毫秒
            'jitter_pct': 0,  # 随机抖动百分比（0=关闭）
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
                    for key in default_config:
                        if key not in self.config:
                            self.config[key] = default_config[key]
            else:
                self.config = default_config
        except Exception as e:
            print("加载配置失败: " + str(e))
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

    # ==================== 6.11.2 DPI 适配 ====================
    def _init_dpi_awareness(self):
        """进程级 DPI 感知已在 main() 中、创建 Tk 根窗口之前设置（保证点击坐标与
        物理像素一致）。此处依据系统缩放设置 tk 渲染比例，避免高分屏下 UI 过小。"""
        try:
            scale = 1.0
            try:
                scale = float(self.root.tk.call('tk', 'scaling'))
            except Exception:
                scale = 1.0
            self._dpi_scale = scale
            # 缩放较高时放大全局默认字体（仅作用于未显式指定 font 的控件，如按钮/下拉框）
            if scale and scale > 1.25:
                try:
                    size = int(round(10 * min(scale, 1.6)))
                    self.root.option_add('*Font', '微软雅黑 %d' % size)
                except Exception:
                    pass
            # 此处日志设施尚未初始化（setup_logging/setup_ui 在后），仅控制台留痕；
            # UI/磁盘日志在 __init__ 中 setup_ui() 之后补记
            print("[DPI] 系统缩放 %.2f" % scale)
        except Exception:
            self._dpi_scale = 1.0

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
                'primary': '#007bff', 'success': '#28a745', 'danger': '#dc3545',
                'warning': '#fd7e14', 'surface': '#f8f9fa', 'border': '#ced4da',
            },
            'dark': {
                'bg': '#212529', 'fg': '#e9ecef', 'muted': '#adb5bd',
                'primary': '#4a90d9', 'success': '#2ecc71', 'danger': '#e74c3c',
                'warning': '#e67e22', 'surface': '#2b3035', 'border': '#495057',
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

    def _apply_theme(self):
        """运行时应用主题：切换 ttkbootstrap 主题 + 重着色语义化控件（TH-01/TH-02）"""
        try:
            pal = self._resolve_palette()
            self._current_palette = pal
            # ttkbootstrap 主题切换（TH-01）
            if self._ttkb_style is not None:
                try:
                    effective = self.theme_mode
                    if effective == 'system':
                        effective = 'dark' if self._system_is_dark() else 'light'
                    tb_name = 'darkly' if effective == 'dark' else 'cosmo'
                    self._ttkb_style.theme_use(tb_name)
                except Exception:
                    pass
            # 语义化重着色已知 tk 控件（TH-02）
            if getattr(self, 'start_btn', None):
                self.start_btn.configure(bg=pal['success'], activebackground=self._shade(pal['success']),
                                         fg='white', activeforeground='white')
            if getattr(self, 'stop_btn', None):
                self.stop_btn.configure(bg=pal['danger'], activebackground=self._shade(pal['danger']),
                                        fg='white', activeforeground='white')
            if getattr(self, 'test_btn', None):
                self.test_btn.configure(bg=pal['primary'], activebackground=self._shade(pal['primary']),
                                        fg='white', activeforeground='white')
            if getattr(self, 'set_area_btn', None):
                self.set_area_btn.configure(bg=pal['muted'], activebackground=self._shade(pal['muted']),
                                            fg='white', activeforeground='white')
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
            print("保存配置失败: " + str(e))
    
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
                self.config['close_to_tray'] = self.close_to_tray_var.get()
            self.save_config()
        except Exception as e:
            print("保存配置失败: " + str(e))
    
    def on_prevent_sleep_changed(self):
        """防止系统锁屏选项改变时的回调"""
        try:
            self.config['prevent_sleep'] = self.prevent_sleep_var.get()
            self.save_config()
            if self.prevent_sleep_var.get():
                self.log_message("已启用防止系统锁屏")
            else:
                self.log_message("已禁用防止系统锁屏")
        except Exception as e:
            print("保存配置失败: " + str(e))

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
            print("保存配置失败: " + str(e))
            
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
            print("保存配置失败: " + str(e))

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

    def set_autostart(self, enable):
        try:
            if IS_WINDOWS:
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                    r"Software\Microsoft\Windows\CurrentVersion\Run",
                                    0, winreg.KEY_SET_VALUE)
                exe = os.path.abspath(sys.argv[0]) if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
                if enable:
                    winreg.SetValueEx(key, "AutoClicker", 0, winreg.REG_SZ, '"' + exe + '"')
                else:
                    try:
                        winreg.DeleteValue(key, "AutoClicker")
                    except FileNotFoundError:
                        pass
                winreg.CloseKey(key)
            elif IS_LINUX:
                adir = os.path.expanduser("~/.config/autostart")
                os.makedirs(adir, exist_ok=True)
                desk = os.path.join(adir, "autoclicker.desktop")
                if enable:
                    exe = os.path.abspath(sys.argv[0]) if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
                    with open(desk, 'w', encoding='utf-8') as f:
                        f.write("[Desktop Entry]\nType=Application\nName=AutoClicker\n"
                                "Exec=\"%s\"\nHidden=false\nX-GNOME-Autostart-enabled=true\n" % exe)
                elif os.path.exists(desk):
                    os.remove(desk)
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
            stats = getattr(self, 'last_run_stats', None)
            if not stats or stats.get('click_count', 0) == 0:
                messagebox.showinfo("提示", "暂无可导出的运行统计（请先完成至少一次点击）")
                return
            path = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("JSON", "*.json"), ("CSV", "*.csv")],
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
        name = simpledialog.askstring("保存方案", "请输入方案名称：")
        if not name:
            return
        name = name.strip()
        keys = ['interval_seconds', 'click_mode', 'prevent_sleep', 'mouse_follow_enabled',
                'mouse_move_speed', 'mouse_move_only', 'startup_countdown', 'click_limit',
                'duration_limit', 'failsafe_enabled', 'click_button', 'hold_ms',
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
            path = filedialog.asksaveasfilename(defaultextension=".json",
                                               filetypes=[("JSON", "*.json")],
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
            path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")], title="导入配置方案")
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
            print("保存配置失败: " + str(e))
                
    def setup_ui(self):
        """设置现代化UI界面 - 采用卡片式布局和响应式设计"""
        # 设置窗口最小尺寸（与 __init__ 保持一致，避免矛盾：CX-05）
        self.root.minsize(700, 760)
        
        # 创建主容器 - 使用Canvas支持滚动
        main_container = ttk.Frame(self.root)
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # 创建Canvas和滚动条
        canvas = tk.Canvas(main_container, highlightthickness=0)
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
                     bg=self._color('warning'), fg='white',
                     font=('微软雅黑', 10, 'bold'), wraplength=500,
                     justify=tk.LEFT, anchor=tk.W).pack(
                         side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 6), pady=7)
            tk.Button(warn_bar, text="详情", command=self.show_input_diag,
                      relief=tk.FLAT, bd=0, bg=self._color('warning'), fg='white',
                      activebackground=self._shade(self._color('warning')),
                      font=('微软雅黑', 9, 'underline'), cursor='hand2').pack(
                          side=tk.RIGHT, padx=(0, 6))
            tk.Button(warn_bar, text="×", command=warn_bar.destroy,
                      relief=tk.FLAT, bd=0, bg=self._color('warning'), fg='white',
                      activebackground=self._shade(self._color('warning')),
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
        main_control_frame = ttk.Frame(control_card)
        main_control_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.start_btn = tk.Button(main_control_frame, text=" 启动自动点击",
                                  command=self.start_clicking,
                                  font=('微软雅黑', 12, 'bold'),
                                  bg=self._color('success'), fg='white',
                                  activebackground=self._shade(self._color('success')), activeforeground='white',
                                  width=20, height=2, cursor='hand2',
                                  relief=tk.FLAT, bd=0)
        self._icon_play = self.make_icon('play', 18, 'white')
        if self._icon_play:
            self.start_btn.configure(image=self._icon_play, compound=tk.LEFT)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 10), fill=tk.X, expand=True)
        
        self.stop_btn = tk.Button(main_control_frame, text=" 停止",
                                 command=self.stop_clicking,
                                 font=('微软雅黑', 12, 'bold'),
                                 bg=self._color('danger'), fg='white',
                                 activebackground=self._shade(self._color('danger')), activeforeground='white',
                                 width=15, height=2, cursor='hand2',
                                 relief=tk.FLAT, bd=0, state=tk.DISABLED)
        self._icon_stop = self.make_icon('stop', 18, 'white')
        if self._icon_stop:
            self.stop_btn.configure(image=self._icon_stop, compound=tk.LEFT)
        self.stop_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 测试按钮
        self.test_btn = tk.Button(control_card, text=" 测试点击位置",
                                 command=self.test_click,
                                 font=('微软雅黑', 10),
                                 bg=self._color('primary'), fg='white',
                                 activebackground=self._shade(self._color('primary')), activeforeground='white',
                                 height=1, cursor='hand2',
                                 relief=tk.FLAT, bd=0)
        self._icon_target = self.make_icon('target', 16, 'white')
        if self._icon_target:
            self.test_btn.configure(image=self._icon_target, compound=tk.LEFT)
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
                                     bg=self._color('muted'), fg='white',
                                     activebackground=self._shade(self._color('muted')),
                                     cursor='hand2', relief=tk.FLAT, bd=0)
        self.set_area_btn.pack(side=tk.LEFT)
        
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
        self.profile_combo = ttk.Combobox(prof_row, textvariable=self.profile_var, width=14, state='readonly')
        self.profile_combo.pack(side=tk.LEFT, padx=(5, 5))
        self._refresh_profile_combo()
        ttk.Button(prof_row, text="保存当前", command=self.profile_save).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(prof_row, text="切换", command=self.profile_switch).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(prof_row, text="删除", command=self.profile_delete).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(prof_row, text="导出", command=self.profile_export).pack(side=tk.LEFT, padx=(0, 5))
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
        version_label = ttk.Label(footer_frame, text="v2.0 (Python 3.14)", 
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
        """CX-08：按配置注册热键，支持自定义与冲突规避（Esc 始终为紧急停止）"""
        if not keyboard:
            return
        # 清除旧热键，避免重复注册
        for k in list(getattr(self, '_hk_keys', [])):
            try:
                keyboard.remove_hotkey(k)
            except Exception:
                pass
        self._hk_keys = []
        try:
            start_k = self.config.get('hotkey_start', 'f6')
            emer_k = self.config.get('hotkey_emergency', 'f8')
            keyboard.add_hotkey(start_k, self.toggle_clicking)
            keyboard.add_hotkey(emer_k, self.emergency_stop, suppress=False)
            keyboard.add_hotkey('esc', self.emergency_stop, suppress=False)
            self._hk_keys = [start_k, emer_k, 'esc']
            print("快捷键已注册：启动=" + start_k + "，紧急停止=" + emer_k + "，Esc")
        except Exception as e:
            print("注册快捷键失败: " + str(e))
                    
    def set_click_area(self):
        try:
            messagebox.showinfo("设置点击区域", 
                               "请在5秒内将鼠标移动到点击区域的左上角\n程序将自动记录位置")
            
            self.root.iconify()
            time.sleep(5)
            
            x, y = get_cursor_pos()
            
            messagebox.showinfo("设置点击区域", 
                               f"已记录左上角位置: ({x}, {y})\n请在5秒内将鼠标移动到点击区域的右下角")
            
            time.sleep(5)
            
            x2, y2 = get_cursor_pos()
            
            self.config['click_area'] = {
                'x': min(x, x2),
                'y': min(y, y2),
                'width': abs(x2 - x),
                'height': abs(y2 - y)
            }
            
            self.area_label.config(text=f"{self.config['click_area']['width']}x{self.config['click_area']['height']}")
            self.save_config()
            
            self.log_message(f"点击区域已设置: {self.config['click_area']}")
            
        except Exception as e:
            error_msg = f"设置点击区域失败: {e}"
            self.log_message(error_msg)
            messagebox.showerror("错误", error_msg)
        finally:
            self.root.deiconify()
            
    def get_click_position(self):
        mode = self.mode_var.get()
        area = self.config['click_area']
        if mode == 'center':
            x = area['x'] + area['width'] // 2
            y = area['y'] + area['height'] // 2
        else:
            x = random.randint(area['x'], area['x'] + area['width'])
            y = random.randint(area['y'], area['y'] + area['height'])
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
            self.log_message(f"[平滑移动] 完成")
        except Exception as e:
            self.log_message(f"鼠标移动失败: {e}")
        
    def prevent_system_sleep(self):
        """跨平台防止系统休眠"""
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
                except:
                    try:
                        import subprocess
                        subprocess.Popen(['xset', 's', 'off'], 
                                       stdout=subprocess.PIPE, 
                                       stderr=subprocess.PIPE)
                        subprocess.Popen(['xset', '-dpms'], 
                                       stdout=subprocess.PIPE, 
                                       stderr=subprocess.PIPE)
                    except:
                        pass
                print("已设置Linux防休眠")
            elif IS_MACOS:
                os.system("caffeinate -u -t 1")
                print("已设置macOS防休眠")
        except Exception as e:
            print(f"防止系统休眠失败: {e}")
                
    def allow_system_sleep(self):
        """跨平台恢复系统休眠设置"""
        try:
            if IS_WINDOWS:
                import ctypes
                ES_CONTINUOUS = 0x80000000
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
                print("已恢复Windows休眠设置")
            elif IS_LINUX:
                try:
                    import subprocess
                    subprocess.Popen(['xset', 's', 'on'], 
                                   stdout=subprocess.PIPE, 
                                   stderr=subprocess.PIPE)
                    subprocess.Popen(['xset', 'dpms'], 
                                   stdout=subprocess.PIPE, 
                                   stderr=subprocess.PIPE)
                except:
                    pass
                print("已恢复Linux休眠设置")
        except Exception as e:
            print(f"恢复系统休眠设置失败: {e}")
                
    # ==================== 线程安全的 UI 更新辅助方法 ====================
    def _ui(self, fn, *args):
        try:
            self.root.after(0, lambda: fn(*args))
        except Exception:
            pass

    def _do_set_status(self, text, color):
        try:
            self.status_indicator.itemconfig(self.status_circle, fill=color)
            self.status_label.config(text=text, foreground=color)
            if getattr(self, 'sb_status_label', None) is not None:
                self.sb_status_label.config(text="● " + text, foreground=color)
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
        self._start_runtime_tick()
        self.click_loop()
        self._stop_runtime_tick()
        self._ui(self.countdown_bar.config, value=0)

    def _effective_interval_seconds(self):
        """按间隔单位换算为秒（CX-07）：秒模式直接取，毫秒模式除以 1000"""
        try:
            val = float(self.interval_var.get())
        except ValueError:
            val = 1.0
        if val < 0:
            val = 0.0
        if self.interval_unit == 'ms':
            return val / 1000.0
        return val

    def _wait_interval(self, base_seconds):
        """按 jitter 随机化后分段等待，期间可响应停止与 failsafe（CX-07）"""
        if base_seconds <= 0:
            return self.is_running
        jp = self.jitter_pct
        if jp and jp > 0:
            factor = 1.0 + random.uniform(-jp / 100.0, jp / 100.0)
            wait = max(0.0, base_seconds * factor)
        else:
            wait = base_seconds
        show_countdown = base_seconds >= 1.0 and self.interval_unit == 's'
        step = 0.05
        remaining = wait
        while remaining > 0 and self.is_running:
            if show_countdown:
                self._set_next(f"{max(0, int(remaining))}秒")
            chunk = min(step, remaining)
            time.sleep(chunk)
            remaining -= chunk
        if not show_countdown and self.is_running:
            self._set_next("ms 模式")
        return self.is_running

    def click_loop(self):
        # 多点位序列模式（FN-03）
        points = self.multi_points if self.use_multi_points else None
        point_idx = 0
        while self.is_running:
            try:
                base = self._effective_interval_seconds()
                if self.prevent_sleep_var.get():
                    self.prevent_system_sleep()

                # 安全：鼠标位移 failsafe 基线（CX-01）
                if self.failsafe_enabled:
                    failsafe_base = get_cursor_pos()

                # 等待一个间隔（含随机抖动），期间可响应停止（CX-07）
                if not self._wait_interval(base):
                    break

                # 安全：运行中若开启 failsafe 且鼠标被移动 >20px，立即急停（CX-01）
                if self.failsafe_enabled and self.is_running:
                    cur = get_cursor_pos()
                    dx = cur[0] - failsafe_base[0]
                    dy = cur[1] - failsafe_base[1]
                    if (dx * dx + dy * dy) ** 0.5 > 20:
                        self.stop_clicking(reason="鼠标位移触发安全停止 (failsafe)")
                        return

                # 计算本次点击坐标：多点位模式按序列循环，否则按模式取点
                if points:
                    if not points:
                        break
                    pt = points[point_idx % len(points)]
                    x, y = int(pt['x']), int(pt['y'])
                    point_idx += 1
                else:
                    x, y = self.get_click_position()

                # 鼠标跟随移动
                if self.mouse_follow_var.get():
                    try:
                        speed = float(self.mouse_speed_var.get())
                        duration = max(0.1, 1.0 - speed)
                        self.smooth_move_to(x, y, duration=duration)
                        time.sleep(0.1)
                    except Exception as e:
                        self.log_message(f"鼠标跟随失败: {e}")

                # 只移动不点击模式下不执行点击
                if not self.mouse_move_only_var.get():
                    # FN-01/FN-02：支持按键类型与按住时长
                    ok = click_mouse(x, y, button=self.click_button, hold_ms=self.hold_ms)
                    if ok:
                        self.log_message(f"在位置 ({x}, {y}) 执行点击[按键={self.click_button}]")
                    else:
                        pyautogui.click(x, y)
                        self.log_message(f"使用pyautogui在位置 ({x}, {y}) 执行点击")
                    self.click_count += 1
                    self.success_count = self.click_count
                    self.click_count_label.config(text=str(self.click_count))
                    self._ui(self._set_sb_counts)
                else:
                    self.log_message(f"仅移动到位置 ({x}, {y})，未执行点击")

                # 安全：点击次数上限（CX-02）
                if self.click_limit and self.click_count >= self.click_limit:
                    self.stop_clicking(reason=f"达到点击次数上限 ({self.click_limit} 次)")
                    break

                # 安全：运行时长上限（CX-02）
                if self.duration_limit:
                    elapsed_min = (time.time() - self.start_time) / 60.0
                    if elapsed_min >= self.duration_limit:
                        self.stop_clicking(reason=f"达到运行时长上限 ({self.duration_limit} 分钟)")
                        break

            except Exception as e:
                self.log_message(f"点击过程中发生错误: {e}")
                self.fail_count += 1
                self._ui(self._set_sb_counts)
                time.sleep(1)
                
    def start_clicking(self):
        # FR-L01：统一守卫，按钮与 F6 热键（toggle_clicking）都经过此处，避免绕过 UI 禁用
        if not self.input_ok:
            messagebox.showerror("启动已禁用", self.input_reason)
            return
        try:
            interval = int(self.interval_var.get())
            if interval < 1:
                messagebox.showerror("错误", "点击间隔必须 >= 1")
                return

            # P0 安全/体验参数校验（CX-02 / CX-04）
            try:
                countdown = int(self.countdown_var.get())
                if countdown < 0 or countdown > 5:
                    messagebox.showerror("错误", "启动倒计时必须在 0-5 秒之间")
                    return
            except ValueError:
                messagebox.showerror("错误", "启动倒计时必须为整数")
                return

            try:
                click_limit = int(self.click_limit_var.get())
                if click_limit < 0:
                    messagebox.showerror("错误", "点击次数上限不能为负数")
                    return
            except ValueError:
                messagebox.showerror("错误", "点击次数上限必须为整数")
                return

            try:
                duration_limit = int(self.duration_limit_var.get())
                if duration_limit < 0:
                    messagebox.showerror("错误", "运行时长上限不能为负数")
                    return
            except ValueError:
                messagebox.showerror("错误", "运行时长上限必须为整数")
                return

            # P1 参数校验（CX-07 / FN-02）
            try:
                jitter = int(self.jitter_var.get())
                if jitter < 0 or jitter > 100:
                    messagebox.showerror("错误", "随机抖动必须在 0-100 之间")
                    return
            except ValueError:
                messagebox.showerror("错误", "随机抖动必须为整数")
                return

            try:
                hold_ms = int(self.hold_ms_var.get())
                if hold_ms < 0:
                    messagebox.showerror("错误", "按住时长不能为负数")
                    return
            except ValueError:
                messagebox.showerror("错误", "按住时长必须为整数")
                return

            self.is_running = True
            self.click_count = 0
            self.countdown_cancelled = False
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

            unit_text = "毫秒" if self.interval_unit == 'ms' else "秒"
            self.log_message(
                "启动配置: 模式=" + str(self.config['click_mode']) + ", 间隔=" + str(interval) + unit_text
                + ", 按键=" + str(self.click_button) + ", 按住=" + str(hold_ms) + "ms"
                + (f", 抖动={jitter}%" if jitter else "")
                + (", 多点位" if self.use_multi_points else "")
                + (", 倒计时=" + str(countdown) + "秒" if countdown else "")
                + (", 次数上限=" + str(click_limit) if click_limit else "")
                + (", 时长上限=" + str(duration_limit) + "分钟" if duration_limit else "")
                + (", failsafe开" if self.failsafe_enabled else ""))
            if self.mouse_move_only_var.get():
                self.log_message("只移动不点击模式: 启用")

            self.click_thread = threading.Thread(target=self.run_clicking, daemon=True)
            self.click_thread.start()

            # 更新状态指示器
            self.status_indicator.itemconfig(self.status_circle, fill='green')
            self.status_label.config(text="运行中", foreground='green')

            # 更新按钮状态（倒计时期间停止按钮即作为取消键）
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.interval_entry.config(state=tk.DISABLED)

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
                except Exception:
                    pass
            # 托盘右键菜单顶部插入动态“停止/启动”项，区分当前状态
            menu = getattr(self, 'tray_menu', None)
            if menu is not None:
                try:
                    menu.delete(0)
                except Exception:
                    pass
                if running:
                    menu.insert_command(0, label="停止点击", command=self.emergency_stop)
                else:
                    menu.insert_command(0, label="启动点击", command=self.start_clicking)
                menu.insert_separator(1)
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
            self.click_thread.join(timeout=2)

        self.allow_system_sleep()

        # 更新状态指示器
        self.status_indicator.itemconfig(self.status_circle, fill='red')
        self.status_label.config(text="已停止", foreground=self._color('danger'))
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

        if reason:
            self.log_message("自动点击已停止（原因：" + str(reason) + "）")
        else:
            self.log_message("自动点击已停止")

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

    def _render_log(self):
        """按当前过滤条件重绘日志文本框（UI-04）"""
        try:
            flt = (self._log_filter or '').lower()
            self.log_text.config(state=tk.NORMAL)
            self.log_text.delete(1.0, tk.END)
            for entry, level in self._log_buffer:
                if flt and flt not in entry.lower():
                    continue
                tag = 'lvl_err' if level == 'err' else ('lvl_warn' if level == 'warn' else '')
                self.log_text.insert(tk.END, entry, tag)
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
            # UI-04：写入缓冲区并按过滤条件渲染
            level = self._log_level(message)
            self._log_buffer.append((log_entry, level))
            if len(self._log_buffer) > 2000:
                self._log_buffer = self._log_buffer[-2000:]
            if self._log_filter:
                self._render_log()
            else:
                try:
                    self.log_text.config(state=tk.NORMAL)
                    tag = 'lvl_err' if level == 'err' else ('lvl_warn' if level == 'warn' else '')
                    self.log_text.insert(tk.END, log_entry, tag)
                    self.log_text.see(tk.END)
                    self.log_text.config(state=tk.DISABLED)
                except Exception:
                    pass
        except Exception as e:
            print(f"日志写入失败: {e}")
    
    def setup_tray_icon(self):
        """设置系统托盘图标和菜单（跨平台）"""
        try:
            # 创建原生托盘菜单（使用tkinter Menu）
            self.tray_menu = tk.Menu(self.root, tearoff=0,
                                     bg=self._color('surface'), fg=self._color('fg'))
            self.tray_menu.add_command(label="显示窗口", command=self.show_from_tray)
            self.tray_menu.add_separator()
            self.tray_menu.add_command(label="退出程序", command=self.exit_from_tray)
            
            self.tray_enabled = True
            self.tray_icon = None
            
            # Windows 系统托盘
            if IS_WINDOWS and HAS_WIN32GUI:
                self._create_windows_tray_icon()
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
                except:
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
        except:
            return None
    
    def _create_windows_tray_icon(self):
        """创建Windows系统托盘图标"""
        try:
            # 创建一个隐藏的消息窗口来接收托盘消息
            wc = win32gui.WNDCLASS()
            wc.lpfnWndProc = self._tray_window_proc
            wc.lpszClassName = "AutoClickerTrayMessageWindow"
            wc.hInstance = win32api.GetModuleHandle(None)
            
            class_atom = win32gui.RegisterClass(wc)
            
            # 创建隐藏的消息窗口
            self.tray_hwnd = win32gui.CreateWindow(
                class_atom,
                "AutoClickerTray",
                0, 0, 0, 0, 0,
                0, 0, wc.hInstance, None
            )
            
            # 加载自定义图标
            hicon = None
            icon_path = self._get_icon_path()
            if icon_path and os.path.exists(icon_path):
                try:
                    # 尝试加载自定义图标
                    hicon = win32gui.LoadImage(
                        None,
                        icon_path,
                        win32con.IMAGE_ICON,
                        32, 32,  # 托盘图标推荐尺寸
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
            
            # 添加托盘图标
            result = win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)
            
            if result:
                self.tray_nid = nid
                self.tray_icon_created = True
                print("系统托盘图标创建成功")
            else:
                print("系统托盘图标创建失败")
                
        except Exception as e:
            print(f"创建Windows托盘图标失败: {e}")
            self.tray_icon_created = False
    
    def _get_icon_path(self):
        """获取图标文件路径"""
        try:
            # 获取程序所在目录
            if getattr(sys, 'frozen', False):
                # 打包后的exe
                base_path = sys._MEIPASS if hasattr(sys, '_MEIPASS') else os.path.dirname(sys.executable)
            else:
                # 开发环境
                base_path = os.path.dirname(__file__)
            
            # 查找图标文件
            icon_path = os.path.join(base_path, 'icons', 'tray.ico')
            if os.path.exists(icon_path):
                return icon_path
            
            # 备用路径
            icon_path = os.path.join(base_path, 'icons', 'autoclicker.ico')
            if os.path.exists(icon_path):
                return icon_path
                
        except Exception:
            pass
        return None
    
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
        """显示托盘右键菜单 - 带自适应定位"""
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
                
                # 获取屏幕尺寸
                screen_width = self.root.winfo_screenwidth()
                screen_height = self.root.winfo_screenheight()
                
                # 菜单尺寸（估算）
                menu_width = 150
                menu_height = 80
                
                # 自适应定位：确保菜单不会超出屏幕边缘
                # 如果鼠标位置太靠右，菜单向左弹出
                if x + menu_width > screen_width:
                    x = x - menu_width
                
                # 如果鼠标位置太靠下，菜单向上弹出
                if y + menu_height > screen_height:
                    y = y - menu_height
                
                # 确保菜单不会超出左边界和上边界
                x = max(0, x)
                y = max(0, y)
                
                # 使用 tkinter Menu 的 post 方法显示菜单
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
    
    def exit_application(self):
        """完全退出应用程序 - 从托盘菜单调用（跨平台）"""
        self.is_running = False
        
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
            self.allow_system_sleep()
        except Exception:
            pass
        
        if keyboard:
            try:
                keyboard.unhook_all()
            except Exception:
                pass
        
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
        
        # 清理 Linux 锁文件
        if IS_LINUX and SINGLE_INSTANCE_LOCK_FD:
            try:
                SINGLE_INSTANCE_LOCK_FD.close()
            except:
                pass
            try:
                if os.path.exists(SINGLE_INSTANCE_LOCK_FILE):
                    os.remove(SINGLE_INSTANCE_LOCK_FILE)
            except:
                pass
        
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
    root = tk.Tk()

    app = AutoClicker(root)

    root.mainloop()


if __name__ == "__main__":
    main()
