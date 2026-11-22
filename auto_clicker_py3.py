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
from datetime import datetime, timedelta

# NFR-09 引擎层（纯逻辑、无 tkinter）：本文件保留 UI/平台编排，纯计算下沉到 auto_clicker_layers.engine
from auto_clicker_layers.engine import (
    target_window_matches,
    effective_interval_seconds as _engine_effective_interval_seconds,
    jittered_wait as _engine_jittered_wait,
    validate_interval as _engine_validate_interval,
    validate_countdown as _engine_validate_countdown,
    validate_click_limit as _engine_validate_click_limit,
    validate_duration_limit as _engine_validate_duration_limit,
    validate_jitter as _engine_validate_jitter,
    validate_hold_ms as _engine_validate_hold_ms,
    parse_schedule_start as _engine_parse_schedule_start,
    weekdays_to_label as _engine_weekdays_to_label,
    label_to_weekdays as _engine_label_to_weekdays,
    schedule_occurrence as _engine_schedule_occurrence,
    schedule_grace_end as _engine_schedule_grace_end,
    schedule_next_text as _engine_schedule_next_text,
)
from auto_clicker_layers.theme import (
    THEMES as _THEME_PALETTES,
    SYSTEM_THEME_NAME as _THEME_SYSTEM_NAME,
    load_user_themes as _theme_load_user_themes,
    shade_color as _theme_shade,
    system_is_dark as _theme_system_is_dark,
    resolve_palette as _theme_resolve_palette,
    theme_display_map as _theme_display_map,
    validate_theme_pack as _theme_validate_pack,
)
from auto_clicker_layers.version import APP_VERSION, BUILD_ID
from auto_clicker_layers.config import (
    clone_defaults as _config_clone_defaults,
    read_config as _config_read,
    normalize_config as _config_normalize,
    config_version as _config_version,
    backup_config as _config_backup,
    write_config as _config_write,
)
from auto_clicker_layers import onboarding as _onboarding
from auto_clicker_layers import run_report as _run_report

# 点击抖动使用系统安全随机源，避免可预测的伪随机序列
_RANDOM = random.SystemRandom()

# ==================== 平台层（auto_clicker_layers.platform_io）====================
# NFR-09：平台探测、系统设置恢复、鼠标输入后端（Win32/X11/ydotool/pyautogui）已下沉到
# auto_clicker_layers/platform_io.py；本文件只保留 UI 编排与热键注册。
from auto_clicker_layers import platform_io as _platform
from auto_clicker_layers.platform_io import (
    PLATFORM, IS_WINDOWS, IS_LINUX, IS_MACOS,
    HAS_WIN32GUI, HAS_WIN32API, HAS_X11, HAS_PYSTRAY, HAS_PIL,
    get_foreground_window_info,
    restore_system_settings,
    install_setting_restore_guards,
    detect_input_backend,
    _is_wayland_session,
    _ydotool_run,
    _ydotool_move,
    _ydotool_click,
    _get_pyautogui,
    _pyautogui_click,
    windows_move_mouse,
    windows_click,
    linux_move_mouse,
    linux_click,
    linux_get_cursor_pos,
    get_cursor_pos,
    move_mouse,
    click_mouse,
)

# 平台层内部已做可用性探测；UI 层托盘/单实例仍需直接引用这些模块名，这里按同一条件导入。
import ctypes
if HAS_WIN32GUI:
    import win32gui
    import win32con
    import win32api
    import win32event
    import win32security
    import pywintypes

# ==================== 防锁屏保活参数 ====================
# 后台保活线程每隔该秒数重新断言“系统/显示器保持唤醒”并做一次 1px 微抖动，
# 远小于常见 1~3 分钟的系统空闲锁屏/屏保阈值，从而独立于“点击运行”持续保活。
KEEPALIVE_INTERVAL = 30

# 复用文案与文件类型（S1192：避免同一字面量重复定义）
MSG_SAVE_CONFIG_FAILED = "保存配置失败: "
JSON_FILE_PATTERN = "*.json"

# ==================== 崩溃诊断（独立于 UI/日志初始化）====================
# 目标：即使 UI 尚未建立、Tk 回调抛异常、后台线程崩溃或进程收到致命信号，
# 也能把现场写入磁盘，避免窗口版 exe 的 stderr 丢失后只剩“无提示退出”。
CRASH_LOG_PATH = os.path.expanduser("~/.auto_clicker_logs/crash.log")
_CRASH_STREAM = None


def _write_crash_log(kind, detail):
    """追加一条崩溃/生命周期记录；失败时静默，绝不影响主流程。"""
    try:
        os.makedirs(os.path.dirname(CRASH_LOG_PATH), exist_ok=True)
        with open(CRASH_LOG_PATH, "a", encoding="utf-8", buffering=1) as fh:
            fh.write("\n[%s] %s\n%s\n" % (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), kind, detail))
    except Exception:
        pass


def _install_crash_logging():
    """安装 faulthandler、sys/threading excepthook，尽早捕获致命错误。"""
    global _CRASH_STREAM
    try:
        os.makedirs(os.path.dirname(CRASH_LOG_PATH), exist_ok=True)
        if _CRASH_STREAM is None:
            _CRASH_STREAM = open(CRASH_LOG_PATH, "a", encoding="utf-8", buffering=1)
        import faulthandler
        faulthandler.enable(file=_CRASH_STREAM, all_threads=True)
    except Exception:
        pass

    import traceback

    def _excepthook(exc_type, exc_value, exc_tb):
        _write_crash_log("UNCAUGHT", "".join(
            traceback.format_exception(exc_type, exc_value, exc_tb)))
        try:
            sys.__excepthook__(exc_type, exc_value, exc_tb)
        except Exception:
            pass

    def _thread_excepthook(args):
        _write_crash_log("THREAD_UNCAUGHT", "".join(
            traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook


def _tk_callback_exception(exc_type, exc_value, exc_tb):
    """Tk 回调异常：窗口版 exe 没有 stderr，必须落盘。"""
    import traceback
    _write_crash_log("TK_CALLBACK", "".join(
        traceback.format_exception(exc_type, exc_value, exc_tb)))
    try:
        sys.__excepthook__(exc_type, exc_value, exc_tb)
    except Exception:
        pass


# ==================== 热键（keyboard，延迟导入）====================
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


def normalize_region(x1, y1, x2, y2):
    """把拖拽起止点归一化为闭区间区域；单击（几乎无位移）按 1×1 点处理。"""
    left = min(int(x1), int(x2))
    top = min(int(y1), int(y2))
    width = abs(int(x2) - int(x1))
    height = abs(int(y2) - int(y1))
    if width < 2 and height < 2:
        return {'x': left, 'y': top, 'width': 1, 'height': 1, 'point': True}
    return {'x': left, 'y': top, 'width': max(1, width + 1), 'height': max(1, height + 1)}


# ==================== UI 组件层（auto_clicker_layers.ui）====================
# NFR-09：全屏区域选择遮罩与顶部错误横幅已下沉到 auto_clicker_layers/ui.py，
# 主文件保留主窗口（AutoClicker）作为组合根。
from auto_clicker_layers.ui import RegionSelector, NoticeBar

# ERROR_ALREADY_EXISTS常量（在pywin32中可能未定义）
ERROR_ALREADY_EXISTS = 183

# 单实例检查 - 使用互斥锁
# 允许通过环境变量覆盖互斥名/窗口标题，便于隔离测试与多版本并行启动；
# 未设置时保持生产默认值不变。
SINGLE_INSTANCE_MUTEX_NAME = os.environ.get(
    "AUTOCLICKER_MUTEX_NAME", "AutoClicker_SingleInstance_Mutex")
SINGLE_INSTANCE_LOCK_FILE = os.path.expanduser("~/.autoclicker.lock")
WINDOW_TITLE = os.environ.get(
    "AUTOCLICKER_WINDOW_TITLE",
    "桌面自动点击工具 v%s (Build %s)" % (APP_VERSION, BUILD_ID))
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

        # 窗口尺寸按 DPI 缩放（F-10 / CX-05）：1000x720 是 96dpi 基准；
        # 1024x768 与 1280x800 必须完整显示底部固定操作条，不允许主流程依赖滚动。
        dpi_ratio = max(1.0, min(getattr(self, '_dpi_scale', 1.3333) / 1.3333, 2.0))
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        win_w = min(int(1000 * dpi_ratio), int(screen_w * 0.9))
        win_h = min(int(720 * dpi_ratio), int(screen_h * 0.9))
        self.root.geometry("%dx%d" % (win_w, win_h))
        self._min_w = min(int(900 * dpi_ratio), win_w)
        self._min_h = min(int(620 * dpi_ratio), win_h)
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
        # FR-D01 定时计划状态：Tk after 每秒检查；休眠唤醒后按单调时钟间隔补算
        self._schedule_last_occurrence = None
        self._schedule_active_occurrence = None
        self._schedule_last_tick = time.monotonic()

        # P2 状态可视化默认值（UI-03）
        self.success_count = 0
        self.fail_count = 0
        self.exception_count = 0
        self._pending_end_summary = False
        self._suppress_end_summary = False
        self._start_confirm_window = None
        self._end_summary_window = None
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
            'fail_count': 0, 'exception_count': 0, 'runtime_seconds': 0.0,
            'interval_seconds': 0.0, 'mode': '', 'button': '',
            'stop_reason': '',
        }

        self.load_config()
        self._init_theme()
        self._init_ui_fonts()
        self.setup_ui()
        self.root.after(30, self._poll_ui_queue)
        # FR-D01 定时计划：Tk 主线程每秒检查一次（休眠期间 after 暂停，唤醒后补算）
        self.root.after(1000, self._schedule_tick)
        # 磁盘日志延后到窗口可见后：logging.handlers 会拉入 shutil/socket/pickle，
        # 冷启动不必为首屏承担该导入成本；此前日志先入 _pending_logs，初始化后补写。
        self.root.after(1200, self.setup_logging)
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
        self.root.after(2000, self.setup_hotkeys)
        self.root.after(2000, self._poll_hotkey_queue)
        self.root.after(3000, self.setup_tray_icon)
        # 图标绘制约 0.5 秒（PIL 3 个图标）：窗口先可见，再在空闲回调补图标
        self.root.after(1500, self._load_action_icons)
        # 先完成首屏布局与映射，再让日志/图标/热键/托盘等冷启动重活进入事件队列，
        # 避免窗口在“未响应”状态下被阻塞十几秒（007 启动回退实测）。
        self.root.update_idletasks()
        if self.theme_mode == 'system':
            self.root.after(5000, self._poll_system_theme)
        
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

    def flush_logging(self):
        """退出前强制刷盘：避免 os._exit/快速退出丢最后几行日志。"""
        try:
            if self._file_logger:
                for handler in self._file_logger.handlers:
                    handler.flush()
        except Exception:
            pass
        try:
            if _CRASH_STREAM:
                _CRASH_STREAM.flush()
        except Exception:
            pass

    def _backup_config_before_migration(self):
        """CX-09：迁移/降级前备份原配置，避免旧配置丢失（PRD FR-G02）。"""
        backup = _config_backup(self.config_file)
        if backup:
            self._migration_backup_path = backup
            print("配置迁移前已备份: " + backup)
        return backup

    def load_config(self):
        default_config = _config_clone_defaults()
        try:
            loaded = _config_read(self.config_file)
            if loaded is None:
                self.config = default_config
            else:
                self.config = loaded
                if _config_version(self.config) < 2:
                    self._backup_config_before_migration()
        except Exception as e:
            print("加载配置失败: " + str(e))
            self._backup_config_before_migration()
            self.config = default_config
        # 配置迁移（CX-09）：补齐 schema 版本、配置方案容器与 schedule 子字段
        try:
            _config_normalize(self.config)
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
        """初始化主题：5 套内置主题 + 用户 JSON 主题包 + 可选 ttkbootstrap。"""
        self.user_theme_dir = os.path.expanduser('~/.auto_clicker/themes')
        self._user_themes, self._theme_load_errors = _theme_load_user_themes(self.user_theme_dir)
        # TH-02：语义化变量集中在 theme 层，避免散落十六进制
        self.THEMES = dict(_THEME_PALETTES)
        self.THEMES.update(self._user_themes)
        self._theme_name_map = _theme_display_map(self.THEMES)
        requested = self.config.get('theme_pack') or self.config.get('theme_mode', 'light')
        if requested != 'system' and requested not in self.THEMES:
            requested = 'light'
        self.theme_mode = requested
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
        return _theme_shade(hex_color, factor)

    def _system_is_dark(self):
        """检测系统是否深色模式（Windows 注册表；其他平台默认浅色）"""
        return _theme_system_is_dark()

    def _resolve_palette(self):
        return _theme_resolve_palette(getattr(self, 'theme_mode', 'light'), self.THEMES,
                                      self._system_is_dark)

    def _current_theme_display_name(self):
        if self.theme_mode == 'system':
            return _THEME_SYSTEM_NAME
        pal = self.THEMES.get(self.theme_mode, self.THEMES['light'])
        return pal.get('name') or self.theme_mode

    def _refresh_theme_selector(self):
        """刷新主题下拉框：系统 + 5 套内置 + 用户主题。"""
        try:
            self._theme_name_map = _theme_display_map(self.THEMES)
            names = list(self._theme_name_map.keys())
            if getattr(self, 'theme_var', None) is not None:
                self.theme_var.set(self._current_theme_display_name())
            if getattr(self, 'theme_combo', None) is not None:
                self.theme_combo['values'] = names
        except Exception:
            pass

    def reload_user_themes(self):
        """重新扫描用户主题目录，保留当前主题选择。"""
        try:
            self._user_themes, self._theme_load_errors = _theme_load_user_themes(self.user_theme_dir)
            self.THEMES = dict(_THEME_PALETTES)
            self.THEMES.update(self._user_themes)
            if self.theme_mode != 'system' and self.theme_mode not in self.THEMES:
                self.theme_mode = 'light'
            self._refresh_theme_selector()
        except Exception:
            pass

    def import_user_theme(self):
        """FR-35：导入 JSON 主题包，校验后复制到 ~/.auto_clicker/themes/。"""
        from tkinter import filedialog
        try:
            path = filedialog.askopenfilename(
                title="导入主题包", filetypes=[("JSON 主题包", JSON_FILE_PATTERN)])
            if not path:
                return
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            pal, errors = _theme_validate_pack(data, existing_ids=set(_THEME_PALETTES))
            if errors or not pal:
                messagebox.showerror("主题包无效", "\n".join(errors or ['未知错误']))
                return
            os.makedirs(self.user_theme_dir, exist_ok=True)
            dest = os.path.join(self.user_theme_dir, pal['id'] + '.json')
            with open(dest, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.reload_user_themes()
            self.on_theme_change(pal['id'])
            messagebox.showinfo("主题已导入", "已导入主题：%s" % (pal.get('name') or pal['id']))
        except Exception as e:
            messagebox.showerror("导入失败", str(e))

    def _apply_ttkbootstrap_theme(self, pal=None):
        """切换 ttkbootstrap 主题（TH-01）；未安装或切换失败时静默降级。"""
        if self._ttkb_style is None:
            return
        try:
            pal = pal or self._resolve_palette()
            tb_name = 'darkly' if pal.get('is_dark') else 'cosmo'
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
            dark = bool(pal.get('is_dark'))
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
            for page_canvas in getattr(self, '_page_canvases', {}).values():
                try:
                    page_canvas.configure(bg=pal['bg'], highlightbackground=pal['bg'])
                except Exception:
                    pass
            indicator = getattr(self, 'status_indicator', None)
            if indicator is not None:
                indicator.configure(bg=pal['bg'])
        except Exception:
            pass

    def _on_main_mousewheel(self, event):
        """主内容区滚轮滚动（720p/高 DPI 下底部控件依赖滚动到达）。

        边界：指针不在主画布内、或事件来自日志框时不接管，避免抢走日志/输入框自身滚动。
        """
        try:
            c = getattr(self, 'main_canvas', None)
            if c is None or not c.winfo_ismapped():
                return
            widget = getattr(event, 'widget', None)
            log = getattr(self, 'log_text', None)
            if log is not None and widget is not None and str(widget).startswith(str(log)):
                return
            px, py = self.root.winfo_pointerxy()
            cx, cy = c.winfo_rootx(), c.winfo_rooty()
            cw, ch = c.winfo_width(), c.winfo_height()
            if not (cx <= px <= cx + cw and cy <= py <= cy + ch):
                return
            num = getattr(event, 'num', None)
            if num == 4:
                direction = -1
            elif num == 5:
                direction = 1
            else:
                direction = -1 if getattr(event, 'delta', 0) > 0 else 1
            c.yview_scroll(direction * 3, 'units')
        except Exception:
            pass

    def _bind_main_mousewheel(self):
        for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            try:
                self.root.bind_all(seq, self._on_main_mousewheel, add='+')
            except Exception:
                pass

    def _create_page(self, host, key, padding=14):
        """创建可切换页面容器（FR-24）：独立滚动，切换只 tkraise。"""
        holder = ttk.Frame(host)
        holder.grid(row=0, column=0, sticky='nsew')
        canvas = tk.Canvas(holder, highlightthickness=0)
        scrollbar = ttk.Scrollbar(holder, orient='vertical', command=canvas.yview)
        body = ttk.Frame(canvas, padding=padding)
        window = canvas.create_window((0, 0), window=body, anchor='nw')
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        body.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfig(window, width=e.width))
        canvas.bind('<Enter>', lambda e, c=canvas: setattr(self, 'main_canvas', c))
        self._page_holders[key] = holder
        self._page_canvases[key] = canvas
        self._page_frames[key] = body
        return body

    def _show_page(self, key):
        """切换左侧导航页面；控件实例与配置状态保持不变。"""
        holder = getattr(self, '_page_holders', {}).get(key)
        if holder is None:
            return
        try:
            holder.tkraise()
            self._active_page = key
            self.main_canvas = self._page_canvases.get(key, self.main_canvas)
            self.main_canvas.yview_moveto(0)
            self._refresh_nav_styles()
            if key == 'run' and hasattr(self, 'run_summary_label'):
                self.run_summary_label.config(text=self._run_summary_text())
        except Exception:
            pass

    def _refresh_nav_styles(self):
        """按当前主题高亮导航项。"""
        try:
            pal = self._resolve_palette()
            active = getattr(self, '_active_page', 'run')
            for key, btn in getattr(self, 'nav_buttons', {}).items():
                selected = key == active
                btn.configure(
                    bg=pal['primary'] if selected else pal['surface'],
                    fg=pal['on_primary'] if selected else pal['text'],
                    activebackground=pal['primary_hover'] if selected else pal['surface_alt'],
                    activeforeground=pal['on_primary'] if selected else pal['text'],
                )
        except Exception:
            pass

    def on_ui_mode_change(self):
        """FR-25：切换简单/高级模式，立即持久化，不触碰任何参数。"""
        mode = self.ui_mode_var.get()
        if mode not in ('simple', 'advanced'):
            mode = 'simple'
        self.config['ui_mode'] = mode
        self._apply_ui_mode()
        try:
            self.save_config()
        except Exception as e:
            print(MSG_SAVE_CONFIG_FAILED + str(e))
        try:
            self.log_message("界面模式：%s" % ("高级" if mode == 'advanced' else "简单"))
        except Exception:
            pass

    def _apply_ui_mode(self):
        """Simple 只露出新手必需项；Advanced 恢复全部控件。"""
        mode = self.config.get('ui_mode', 'simple')
        advanced = mode == 'advanced'
        try:
            self.ui_mode_var.set(mode)
            if advanced:
                self.p1_card.pack(fill=tk.X, pady=(0, 15), after=self.safety_card)
                self.p1b_card.pack(fill=tk.X, pady=(0, 15), after=self.p1_card)
                self.target_container.pack(fill=tk.X, pady=(0, 8),
                                           after=self.countdown_container)
                self.motion_frame.pack(fill=tk.X, after=self.prevent_sleep_check)
                self.failsafe_check.pack(anchor=tk.W, after=self.duration_container)
                self.close_tray_check.pack(anchor=tk.W, pady=(4, 0),
                                           after=self.failsafe_check)
            else:
                self.p1_card.pack_forget()
                self.p1b_card.pack_forget()
                self.target_container.pack_forget()
                self.motion_frame.pack_forget()
                self.failsafe_check.pack_forget()
                self.close_tray_check.pack_forget()
            records_btn = getattr(self, 'nav_buttons', {}).get('records')
            settings_btn = getattr(self, 'nav_buttons', {}).get('settings')
            if records_btn is not None:
                if advanced:
                    if settings_btn is not None:
                        records_btn.pack(fill=tk.X, pady=2, before=settings_btn)
                    else:
                        records_btn.pack(fill=tk.X, pady=2)
                else:
                    records_btn.pack_forget()
                    if getattr(self, '_active_page', 'run') == 'records':
                        self._show_page('run')
            self._refresh_nav_styles()
        except Exception as e:
            print("应用界面模式失败: %s" % e)

    def _run_summary_text(self):
        """运行台配置摘要（只读，避免与规则页控件状态不同步）。"""
        try:
            mode_key = self.config.get('click_mode', 'random')
            mode = getattr(self, 'mode_map', {}).get(mode_key, mode_key)
            unit = self.config.get('interval_unit', 's')
            interval = self.config.get('interval_seconds', 10)
            limit = self.config.get('click_limit', 0) or '无限'
            duration = self.config.get('duration_limit', 0) or '无限'
            sleep = '开' if self.config.get('prevent_sleep', False) else '关'
            return ("间隔：%s %s    模式：%s    次数上限：%s    时长上限：%s 分钟\n"
                    "防锁屏：%s    多点位：%s" % (
                        interval, unit, mode, limit, duration, sleep,
                        '开' if self.config.get('use_multi_points', False) else '关'))
        except Exception:
            return "当前配置读取失败，请到「规则」页检查。"

    def _apply_theme(self):
        """运行时应用主题：切换 ttk 主题 + 重着色语义化控件（TH-01/TH-02）"""
        try:
            pal = self._resolve_palette()
            self._current_palette = pal
            self._apply_ttkbootstrap_theme(pal)
            self._apply_ttk_theme_styles(pal)
            # theme_use 会重置 ttk 样式字体，切换后需按统一基准重新覆盖
            self._apply_ttk_fonts()
            # 语义化重着色已知 tk/ttk 控件（TH-02）
            self._recolor_action_buttons(pal)
            self._recolor_semantic_labels(pal)
            self._refresh_nav_styles()
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
        """切换主题并持久化（FR-33/34/35）。"""
        try:
            valid = set(self.THEMES.keys()) | {'system'}
            if mode not in valid:
                return
            self.theme_mode = mode
            self.config['theme_pack'] = mode
            # 兼容旧字段：保留 light/dark/system 口径
            if mode in ('light', 'dark', 'system'):
                self.config['theme_mode'] = mode
            else:
                self.config['theme_mode'] = 'dark' if self._resolve_palette().get('is_dark') else 'light'
            self.save_config()
            self._refresh_theme_selector()
            self._apply_theme()
            # 跟随系统模式：启动轮询，随系统深浅色变化
            if mode == 'system':
                self._poll_system_theme()
        except Exception:
            pass

    def on_theme_change_ui(self, event=None):
        mode = getattr(self, '_theme_name_map', {}).get(self.theme_var.get(), 'light')
        self.on_theme_change(mode)

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
            _config_write(self.config_file, self.config)
        except Exception as e:
            print(MSG_SAVE_CONFIG_FAILED + str(e))
    
    def save_config_if_running(self):
        """保存配置，如果程序正在运行则保存当前配置"""
        if getattr(self, '_config_ui_syncing', False):
            return
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
            # FR-D01：定时计划输入一并持久化（非法值保留上一次有效配置）
            if hasattr(self, 'schedule_start_var'):
                sched = dict(self.config.get('schedule') or {})
                sched['enabled'] = self.schedule_enabled_var.get()
                sched['start_at'] = self.schedule_start_var.get().strip()
                try:
                    sched['stop_after_min'] = max(0, int(self.schedule_stop_var.get() or 0))
                except ValueError:
                    pass
                sched['weekdays'] = self._label_to_weekdays(self.schedule_days_var.get())
                self.config['schedule'] = sched
            self.save_config()
        except Exception as e:
            print(MSG_SAVE_CONFIG_FAILED + str(e))

    # ==================== FR-D01 定时计划 ====================
    @staticmethod
    def _weekdays_to_label(weekdays):
        return _engine_weekdays_to_label(weekdays)

    @staticmethod
    def _label_to_weekdays(label):
        return _engine_label_to_weekdays(label)

    @staticmethod
    def _parse_schedule_start(value):
        return _engine_parse_schedule_start(value)

    def _schedule_settings(self):
        sched = self.config.get('schedule')
        if not isinstance(sched, dict):
            sched = {}
        try:
            start = self._parse_schedule_start(sched.get('start_at', '09:00'))
        except (TypeError, ValueError):
            start = (9, 0)
        try:
            stop_min = max(0, int(sched.get('stop_after_min', 0) or 0))
        except (TypeError, ValueError):
            stop_min = 0
        days = sched.get('weekdays', [1, 2, 3, 4, 5])
        try:
            days = [int(d) for d in days if 1 <= int(d) <= 7]
        except (TypeError, ValueError):
            days = [1, 2, 3, 4, 5]
        return bool(sched.get('enabled', False)), start, stop_min, days

    def _schedule_occurrence(self, now, start, days):
        """返回 <= now 的最近一次生效计划（含跨零点前一天）。"""
        return _engine_schedule_occurrence(now, start, days)

    def _schedule_next_text(self, now=None):
        _, start, stop_min, days = self._schedule_settings()
        return _engine_schedule_next_text(now or datetime.now(), start, days)

    def _schedule_check(self, now=None, running=None):
        """执行一次定时判断。返回 started/stopped/noop，供探针断言。"""
        enabled, start, stop_min, days = self._schedule_settings()
        if not enabled:
            self._schedule_active_occurrence = None
            return 'noop'
        now = now or datetime.now()
        running = self.is_running if running is None else running
        occ = self._schedule_occurrence(now, start, days)
        result = 'noop'
        if occ is not None:
            key = occ.isoformat(timespec='minutes')
            grace_end = _engine_schedule_grace_end(occ, stop_min)
            if (not running and now <= grace_end and key != self._schedule_last_occurrence):
                self._schedule_last_occurrence = key
                self._schedule_active_occurrence = key
                self.start_clicking(source='schedule')
                if self.is_running:
                    self.log_message("定时计划触发：%s 启动" % occ.strftime('%m-%d %H:%M'))
                    result = 'started'
                else:
                    self._schedule_active_occurrence = None
                    self.log_message("定时计划触发失败：启动参数校验未通过")
            if running and stop_min > 0 and self._schedule_active_occurrence == key:
                stop_at = occ + timedelta(minutes=stop_min)
                if now >= stop_at:
                    self._schedule_active_occurrence = None
                    self.stop_clicking(reason="定时计划运行 %d 分钟结束" % stop_min)
                    result = 'stopped'
        return result

    def _schedule_tick(self):
        """每秒检查；Tk after 在系统休眠时暂停，唤醒后用单调时钟差值识别并补算。"""
        try:
            mono = time.monotonic()
            gap = mono - self._schedule_last_tick
            self._schedule_last_tick = mono
            if gap > 90 and self.config.get('schedule', {}).get('enabled'):
                self.log_message("检测到系统休眠/卡顿 %.0f 秒，补算定时计划" % gap)
            self._schedule_check()
        except Exception as e:
            print("定时计划检查失败: " + str(e))
        finally:
            try:
                self.root.after(1000, self._schedule_tick)
            except Exception:
                pass

    def on_schedule_apply(self):
        try:
            start = self._parse_schedule_start(self.schedule_start_var.get())
            stop_min = int(self.schedule_stop_var.get() or 0)
            if stop_min < 0 or stop_min > 1440:
                raise ValueError('运行时长需为 0–1440 分钟')
            days = self._label_to_weekdays(self.schedule_days_var.get())
            sched = {'enabled': bool(self.schedule_enabled_var.get()),
                     'start_at': '%02d:%02d' % start,
                     'stop_after_min': stop_min, 'weekdays': days}
            self.config['schedule'] = sched
            self._schedule_last_occurrence = None
            self._schedule_active_occurrence = None
            self.save_config()
            if sched['enabled']:
                text = "定时计划已启用：%s 启动，运行 %s 分钟，%s；下次 %s" % (
                    sched['start_at'], stop_min if stop_min else '不限',
                    self.schedule_days_var.get(), self._schedule_next_text())
                self.schedule_hint_label.config(text=text)
                self.log_message(text)
            else:
                self.schedule_hint_label.config(text="定时计划已关闭")
                self.log_message("定时计划已关闭")
        except Exception as e:
            messagebox.showerror("定时计划", "参数无效: " + str(e))
    
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

    def on_confirm_start_changed(self):
        """FR-02：启动前确认开关，立即落盘供下次启动使用。"""
        try:
            enabled = bool(self.confirm_start_var.get())
            self.config['start_confirm_enabled'] = enabled
            self.save_config()
            self.log_message("启动前确认已%s" % ("开启" if enabled else "关闭"))
        except Exception as e:
            self.log_message("保存启动前确认设置失败: " + str(e))

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

    def open_config_dir(self):
        """FR-04：打开配置文件所在目录。"""
        try:
            d = os.path.dirname(self.config_file) or os.path.expanduser('~')
            if IS_WINDOWS:
                os.startfile(d)
            elif IS_LINUX:
                import subprocess
                subprocess.Popen(['xdg-open', d])
            else:
                messagebox.showinfo("配置目录", d)
        except Exception as e:
            self.log_message("打开配置目录失败: " + str(e))

    def copy_version_info(self):
        """FR-04：复制版本与路径信息，便于反馈问题。"""
        text = "\n".join((
            "AutoClicker %s" % get_version_text(),
            "Python %d.%d.%d" % sys.version_info[:3],
            "配置: " + self.config_file,
            "日志: " + getattr(self, 'log_dir', os.path.expanduser('~/.auto_clicker_logs')),
        ))
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.show_notice("版本信息已复制", level='operation')
        except Exception as e:
            messagebox.showinfo("版本信息", text + "\n\n复制失败: " + str(e))

    def open_project_home(self):
        """FR-04：打开项目主页（只读外链，不在应用内联网）。"""
        try:
            import webbrowser
            webbrowser.open("https://github.com/wangnan05563/AutoClicker")
        except Exception as e:
            messagebox.showinfo("项目主页", "https://github.com/wangnan05563/AutoClicker\n" + str(e))

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

    # ==================== FR-01 首启 3 步向导 ====================
    def _onboarding_point_area(self):
        """向导默认目标：当前光标点；不可读时退回主屏中心，避免默认全屏随机点击。"""
        try:
            x, y = get_cursor_pos()
            return _onboarding.point_area(x, y)
        except Exception:
            pass
        try:
            return _onboarding.point_area(self.root.winfo_screenwidth() // 2,
                                          self.root.winfo_screenheight() // 2)
        except Exception:
            return {'x': 0, 'y': 0, 'width': 1, 'height': 1}

    def _apply_first_run_preset(self):
        """首次运行：先把当前配置收敛到「推荐安全」，再启动 3 步向导。"""
        try:
            area = self._onboarding_point_area()
            safe_cfg = _onboarding.safe_config(self.config, click_area=area)
            self.config = _onboarding.apply_template(
                self.config, _onboarding.SAFE_ID, click_area=area, mark_done=False)
            self.config.setdefault('profiles', {})['推荐安全'] = {
                k: safe_cfg.get(k) for k in (
                    'interval_seconds', 'click_mode', 'prevent_sleep',
                    'mouse_follow_enabled', 'mouse_move_speed', 'mouse_move_only',
                    'startup_countdown', 'click_limit', 'duration_limit',
                    'failsafe_enabled', 'target_window_keyword', 'click_button',
                    'hold_ms', 'interval_unit', 'jitter_pct', 'use_multi_points',
                    'multi_points', 'click_area', 'hotkey_start',
                    'hotkey_emergency', 'autostart', 'close_to_tray')
            }
            self.save_config()
            self.log_message("首次运行：已写入推荐安全配置与「推荐安全」方案，进入 3 步向导")
        except Exception:
            pass

    def _show_first_run_guidance(self):
        self.show_onboarding_wizard(force=False)

    def _wizard_target_text(self):
        area = getattr(self, '_wizard_click_area', None) or self.config.get('click_area')
        try:
            if int(area.get('width', 1)) <= 1 and int(area.get('height', 1)) <= 1:
                return "当前目标：点 (%d, %d)" % (int(area['x']), int(area['y']))
            return "当前目标：区域 %dx%d @ (%d, %d)" % (
                int(area['width']), int(area['height']),
                int(area['x']), int(area['y']))
        except Exception:
            return "当前目标：未设置"

    def _wizard_refresh_preview(self, event=None):
        try:
            template_id = self._wizard_template_var.get()
            lines = _onboarding.summary_lines(
                template_id, self.config, getattr(self, '_wizard_click_area', None))
            self._wizard_preview_var.set("\n".join(lines))
        except Exception:
            pass
        try:
            self._wizard_target_var.set(self._wizard_target_text())
        except Exception:
            pass

    def _wizard_set_step(self, step):
        self._wizard_step = max(1, min(3, int(step)))
        for idx, frame in enumerate(self._wizard_step_frames, start=1):
            if idx == self._wizard_step:
                frame.pack(fill=tk.BOTH, expand=True, padx=18, pady=14)
            else:
                frame.pack_forget()
        self._wizard_step_var.set("步骤 %d / 3" % self._wizard_step)
        try:
            self._wizard_back_btn.configure(
                state='normal' if self._wizard_step > 1 else 'disabled')
            self._wizard_next_btn.configure(
                text='完成并进入运行台' if self._wizard_step == 3 else '下一步')
            self._wizard_error_var.set('')
        except Exception:
            pass
        self._wizard_refresh_preview()

    def _wizard_next(self):
        if self._wizard_step < 3:
            self._wizard_set_step(self._wizard_step + 1)
        else:
            self._finish_onboarding(self._wizard_template_var.get())

    def _wizard_back(self):
        if self._wizard_step > 1:
            self._wizard_set_step(self._wizard_step - 1)

    def _wizard_pick_region(self):
        try:
            self._wizard_window.withdraw()
            try:
                self._wizard_window.grab_release()
            except Exception:
                pass
            if getattr(self, '_region_selector', None) is None:
                self.root.after(0, self._open_wizard_region_selector)
        except Exception:
            self._wizard_error_var.set("打开取点遮罩失败，请稍后重试")

    def _open_wizard_region_selector(self):
        try:
            self._region_selector = RegionSelector(self.root, self._on_wizard_region_selected)
        except Exception as e:
            self._region_selector = None
            try:
                self._wizard_error_var.set("打开取点遮罩失败: %s" % e)
                self._restore_wizard_window()
            except Exception:
                pass

    def _on_wizard_region_selected(self, region):
        self._region_selector = None
        try:
            if region:
                if region.get('point'):
                    self._wizard_click_area = _onboarding.point_area(region['x'], region['y'])
                else:
                    self._wizard_click_area = {
                        'x': int(region['x']), 'y': int(region['y']),
                        'width': int(region['width']), 'height': int(region['height']),
                    }
        except Exception:
            pass
        self._restore_wizard_window()

    def _restore_wizard_window(self):
        try:
            self._wizard_window.deiconify()
            self._wizard_window.lift()
            if self.root.winfo_viewable():
                self._wizard_window.grab_set()
            self._wizard_refresh_preview()
        except Exception:
            pass

    def _wizard_use_cursor(self):
        self._wizard_click_area = self._onboarding_point_area()
        self._wizard_refresh_preview()

    def _wizard_save_safe_profile(self, cfg):
        try:
            self.config.setdefault('profiles', {})['推荐安全'] = {
                k: cfg.get(k) for k in (
                    'interval_seconds', 'click_mode', 'prevent_sleep',
                    'mouse_follow_enabled', 'mouse_move_speed', 'mouse_move_only',
                    'startup_countdown', 'click_limit', 'duration_limit',
                    'failsafe_enabled', 'target_window_keyword', 'click_button',
                    'hold_ms', 'interval_unit', 'jitter_pct', 'use_multi_points',
                    'multi_points', 'click_area', 'hotkey_start',
                    'hotkey_emergency', 'autostart', 'close_to_tray')
            }
        except Exception:
            pass

    def _finish_onboarding(self, template_id, skipped=False):
        """应用模板并关闭向导；强制重开时“跳过”不覆盖当前参数。"""
        force = bool(getattr(self, '_wizard_force', False))
        try:
            start = self._wizard_hotkey_start_var.get().strip().lower()
            emergency = self._wizard_hotkey_emergency_var.get().strip().lower()
            area = getattr(self, '_wizard_click_area', None) or self._onboarding_point_area()
            if skipped:
                safe_cfg = _onboarding.safe_config(
                    self.config, click_area=area,
                    hotkey_start=start, hotkey_emergency=emergency)
                self._wizard_save_safe_profile(safe_cfg)
                if not force:
                    self.config = safe_cfg
                else:
                    self.config['onboarding_done'] = True
                    self.config['onboarding_template'] = _onboarding.SAFE_ID
            else:
                self.config = _onboarding.apply_template(
                    self.config, template_id, click_area=area,
                    hotkey_start=start, hotkey_emergency=emergency,
                    mark_done=True)
            self.first_run = False
            self.save_config()
            self.apply_config_to_ui()
            self._apply_ui_mode()
            self._show_page('run')
            self._close_wizard()
            self.log_message("首启向导：%s，目标 %s" % (
                '已跳过并使用推荐安全' if skipped else
                ('模板 ' + str(_onboarding.get_template(template_id)['name'])),
                self._wizard_target_text()))
        except Exception as e:
            try:
                self._wizard_error_var.set("应用失败: %s" % e)
            except Exception:
                pass

    def _close_wizard(self):
        try:
            window = getattr(self, '_wizard_window', None)
            if window is not None:
                try:
                    window.grab_release()
                except Exception:
                    pass
                window.destroy()
        finally:
            self._wizard_window = None
            self._wizard_step_frames = []

    def _onboarding_skip(self):
        self._finish_onboarding(_onboarding.SAFE_ID, skipped=True)

    def show_onboarding_wizard(self, force=False):
        """FR-01：选场景 → 取目标 → 确认热键；可跳过，设置页可重开。"""
        if getattr(self, '_wizard_window', None) is not None:
            try:
                self._wizard_window.lift()
                self._wizard_window.focus_force()
            except Exception:
                pass
            return
        if not force and not getattr(self, 'first_run', False):
            return
        try:
            pal = self._resolve_palette()
        except Exception:
            pal = _theme_resolve_palette('light')
        self._wizard_force = bool(force)
        self._wizard_step = 1
        self._wizard_click_area = dict(self.config.get('click_area') or {})
        self._wizard_template_var = tk.StringVar(value='keep_online')
        self._wizard_target_var = tk.StringVar(value=self._wizard_target_text())
        self._wizard_preview_var = tk.StringVar()
        self._wizard_step_var = tk.StringVar(value='步骤 1 / 3')
        self._wizard_error_var = tk.StringVar()
        self._wizard_hotkey_start_var = tk.StringVar(
            value=str(self.config.get('hotkey_start', 'f6')).upper())
        self._wizard_hotkey_emergency_var = tk.StringVar(
            value=str(self.config.get('hotkey_emergency', 'f8')).upper())

        win = tk.Toplevel(self.root)
        self._wizard_window = win
        win.title("首启向导 · AutoClicker")
        win.geometry("820x680")
        win.minsize(760, 640)
        win.configure(bg=pal['bg'])
        win.transient(self.root)
        win.protocol("WM_DELETE_WINDOW", self._onboarding_skip)

        header = tk.Frame(win, bg=pal['primary'], padx=22, pady=14)
        header.grid(row=0, column=0, sticky='ew')
        win.grid_rowconfigure(1, weight=1)
        win.grid_columnconfigure(0, weight=1)
        tk.Label(header, text="欢迎使用 AutoClicker", bg=pal['primary'],
                 fg=pal['on_primary'], font=('微软雅黑', 18, 'bold')).pack(anchor=tk.W)
        tk.Label(header, text="3 步完成首次配置；不设置也能跳过，用推荐安全参数。",
                 bg=pal['primary'], fg=pal['on_primary'],
                 font=('微软雅黑', 10)).pack(anchor=tk.W, pady=(4, 0))
        tk.Label(header, textvariable=self._wizard_step_var, bg=pal['primary'],
                 fg=pal['on_primary'], font=('微软雅黑', 9, 'bold')).pack(anchor=tk.E)

        host = tk.Frame(win, bg=pal['bg'])
        host.grid(row=1, column=0, sticky='nsew')
        self._wizard_step_frames = []

        # 第 1 步：场景
        step1 = tk.Frame(host, bg=pal['bg'])
        tk.Label(step1, text="第 1 步：选择使用场景", bg=pal['bg'], fg=pal['text'],
                 font=('微软雅黑', 13, 'bold')).pack(anchor=tk.W)
        tk.Label(step1, text="场景只影响间隔、停止条件和防锁屏；随时可在规则页修改。",
                 bg=pal['bg'], fg=pal['muted'], font=('微软雅黑', 9)).pack(anchor=tk.W, pady=(2, 8))
        for tpl in _onboarding.TEMPLATES:
            row = tk.Frame(step1, bg=pal['surface'], highlightthickness=1,
                           highlightbackground=pal['border'], padx=10, pady=6)
            row.pack(fill=tk.X, pady=3)
            tk.Radiobutton(row, text=tpl['name'], variable=self._wizard_template_var,
                           value=tpl['id'], command=self._wizard_refresh_preview,
                           bg=pal['surface'], fg=pal['text'], selectcolor=pal['surface'],
                           activebackground=pal['surface'], activeforeground=pal['text'],
                           font=('微软雅黑', 10, 'bold'), anchor=tk.W).pack(anchor=tk.W)
            tk.Label(row, text=tpl['description'], bg=pal['surface'], fg=pal['muted'],
                     font=('微软雅黑', 9), justify=tk.LEFT,
                     wraplength=680).pack(anchor=tk.W, padx=(24, 0))
        preview = tk.LabelFrame(step1, text="模板摘要", bg=pal['surface'], fg=pal['text'],
                                font=('微软雅黑', 9, 'bold'), padx=10, pady=6)
        preview.pack(fill=tk.X, pady=(8, 0))
        tk.Label(preview, textvariable=self._wizard_preview_var, bg=pal['surface'],
                 fg=pal['text'], justify=tk.LEFT, anchor=tk.W,
                 font=('微软雅黑', 9)).pack(anchor=tk.W)
        self._wizard_step_frames.append(step1)

        # 第 2 步：目标
        step2 = tk.Frame(host, bg=pal['bg'])
        tk.Label(step2, text="第 2 步：选择点击目标", bg=pal['bg'], fg=pal['text'],
                 font=('微软雅黑', 13, 'bold')).pack(anchor=tk.W)
        tk.Label(step2, text="拖拽框选区域，或单击取一个点；也可以直接使用当前鼠标位置。",
                 bg=pal['bg'], fg=pal['muted'], font=('微软雅黑', 9),
                 wraplength=690).pack(anchor=tk.W, pady=(2, 8))
        target_box = tk.Frame(step2, bg=pal['surface'], highlightthickness=1,
                              highlightbackground=pal['border'], padx=14, pady=14)
        target_box.pack(fill=tk.X)
        tk.Label(target_box, textvariable=self._wizard_target_var, bg=pal['surface'],
                 fg=pal['primary'], font=('微软雅黑', 12, 'bold')).pack(anchor=tk.W)
        btn_row = tk.Frame(target_box, bg=pal['surface'])
        btn_row.pack(anchor=tk.W, pady=(10, 0))
        ttk.Button(btn_row, text="框选区域", command=self._wizard_pick_region).pack(
            side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="使用当前鼠标位置",
                   command=self._wizard_use_cursor).pack(side=tk.LEFT)
        tk.Label(step2, text="提示：选“保持在线”时只会移动鼠标，不会点击；选签到/连点才会执行点击。",
                 bg=pal['bg'], fg=pal['muted'], font=('微软雅黑', 9),
                 wraplength=690).pack(anchor=tk.W, pady=(10, 0))
        self._wizard_step_frames.append(step2)

        # 第 3 步：热键
        step3 = tk.Frame(host, bg=pal['bg'])
        tk.Label(step3, text="第 3 步：确认快捷键", bg=pal['bg'], fg=pal['text'],
                 font=('微软雅黑', 13, 'bold')).pack(anchor=tk.W)
        tk.Label(step3, text="默认 F6 开始/停止，F8 或 Esc 随时急停。",
                 bg=pal['bg'], fg=pal['muted'], font=('微软雅黑', 9)).pack(anchor=tk.W, pady=(2, 12))
        hotkey_box = tk.Frame(step3, bg=pal['surface'], highlightthickness=1,
                              highlightbackground=pal['border'], padx=16, pady=16)
        hotkey_box.pack(fill=tk.X)
        row1 = tk.Frame(hotkey_box, bg=pal['surface'])
        row1.pack(fill=tk.X, pady=3)
        tk.Label(row1, text="开始 / 停止：", bg=pal['surface'], fg=pal['text'],
                 font=('微软雅黑', 10, 'bold'), width=14, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Combobox(row1, textvariable=self._wizard_hotkey_start_var,
                     values=('F6', 'F7', 'F9', 'F10', 'F11', 'F12'),
                     state='readonly', width=10).pack(side=tk.LEFT)
        row2 = tk.Frame(hotkey_box, bg=pal['surface'])
        row2.pack(fill=tk.X, pady=3)
        tk.Label(row2, text="紧急停止：", bg=pal['surface'], fg=pal['text'],
                 font=('微软雅黑', 10, 'bold'), width=14, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Combobox(row2, textvariable=self._wizard_hotkey_emergency_var,
                     values=('F8', 'F9', 'F10', 'ESC'),
                     state='readonly', width=10).pack(side=tk.LEFT)
        tk.Label(hotkey_box, text="Esc 始终保留为系统级急停；两个快捷键不能相同。",
                 bg=pal['surface'], fg=pal['muted'], font=('微软雅黑', 9)).pack(
                     anchor=tk.W, pady=(10, 0))
        tk.Label(step3, text="完成后点「完成并进入运行台」，再按 F6 或点底部「启动」开始。",
                 bg=pal['bg'], fg=pal['muted'], font=('微软雅黑', 9),
                 wraplength=690).pack(anchor=tk.W, pady=(12, 0))
        self._wizard_step_frames.append(step3)

        footer = tk.Frame(win, bg=pal['bg'], padx=18, pady=12)
        footer.grid(row=2, column=0, sticky='ew')
        ttk.Button(footer, text="跳过（推荐安全）",
                   command=self._onboarding_skip).pack(side=tk.LEFT)
        self._wizard_next_btn = ttk.Button(footer, text="下一步", command=self._wizard_next)
        self._wizard_next_btn.pack(side=tk.RIGHT)
        self._wizard_back_btn = ttk.Button(footer, text="上一步", command=self._wizard_back)
        self._wizard_back_btn.pack(side=tk.RIGHT, padx=(0, 8))
        tk.Label(win, textvariable=self._wizard_error_var, bg=pal['bg'],
                 fg=pal['danger'], font=('微软雅黑', 9)).grid(
                     row=3, column=0, sticky='ew', padx=18)

        self._wizard_set_step(1)
        try:
            win.update_idletasks()
            if self.root.winfo_viewable():
                w = win.winfo_width()
                h = win.winfo_height()
                x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - w) // 2)
                y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - h) // 2)
                win.geometry("+%d+%d" % (x, y))
                win.grab_set()
            win.focus_force()
        except Exception:
            pass


    # ==================== FR-02 启动确认 + 结束摘要 ====================
    def _confirmation_snapshot(self, interval, countdown, click_limit,
                               duration_limit, jitter, hold_ms):
        """用当前控件值拼出确认快照，确保确认框与实际启动参数一致。"""
        snapshot = dict(self.config or {})
        snapshot.update({
            'interval_seconds': interval,
            'interval_unit': self.interval_unit_var.get(),
            'click_mode': self.mode_var.get(),
            'click_button': self.click_button_var.get(),
            'hold_ms': hold_ms,
            'jitter_pct': jitter,
            'click_limit': click_limit,
            'duration_limit': duration_limit,
            'startup_countdown': countdown,
            'prevent_sleep': self.prevent_sleep_var.get(),
            'failsafe_enabled': self.failsafe_var.get(),
            'mouse_move_only': self.mouse_move_only_var.get(),
            'use_multi_points': self.use_multi_points_var.get(),
            'multi_points': self.config.get('multi_points', []),
            'target_window_keyword': self.target_window_var.get().strip(),
            'hotkey_start': self.config.get('hotkey_start', 'f6'),
            'hotkey_emergency': self.config.get('hotkey_emergency', 'f8'),
            'start_confirm_enabled': self.config.get('start_confirm_enabled', True),
        })
        return snapshot

    def _confirm_start(self, snapshot, source='manual'):
        """按设置决定是否弹确认；定时任务跳过，避免无人值守卡在弹窗。"""
        if not _run_report.should_confirm_start(snapshot, source):
            if source == 'schedule':
                self.log_message("定时任务启动：跳过启动前确认")
            return True
        confirmed = self.show_start_confirmation(_run_report.build_start_lines(snapshot))
        if confirmed:
            self.log_message("启动前确认已通过")
        return confirmed

    def show_start_confirmation(self, lines):
        """展示启动参数确认框，返回用户是否继续；勾选可记住关闭后续确认。"""
        try:
            pal = self._resolve_palette()
        except Exception:
            pal = _theme_resolve_palette('light')
        win = tk.Toplevel(self.root)
        self._start_confirm_window = win
        self._start_confirm_result = False
        win.title("启动前确认 · AutoClicker")
        win.configure(bg=pal['bg'])
        win.resizable(False, False)
        if self.root.winfo_viewable():
            win.transient(self.root)

        tk.Label(win, text="即将开始自动点击", bg=pal['bg'], fg=pal['text'],
                 font=('微软雅黑', 16, 'bold')).pack(anchor=tk.W, padx=22, pady=(18, 4))
        tk.Label(win, text="请确认以下参数；取消不会启动。", bg=pal['bg'],
                 fg=pal['muted'], font=('微软雅黑', 9)).pack(anchor=tk.W, padx=22)

        card = tk.Frame(win, bg=pal['surface'], highlightthickness=1,
                        highlightbackground=pal['border'], padx=14, pady=10)
        card.pack(fill=tk.X, padx=22, pady=(12, 8))
        for line in lines:
            tk.Label(card, text=str(line), bg=pal['surface'], fg=pal['text'],
                     font=('微软雅黑', 10), justify=tk.LEFT, anchor=tk.W,
                     wraplength=470).pack(anchor=tk.W, pady=2)

        self._start_confirm_remember_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(win, text="以后不再显示此确认（可在设置中重新开启）",
                        variable=self._start_confirm_remember_var).pack(
                            anchor=tk.W, padx=22, pady=(2, 4))

        btns = ttk.Frame(win)
        btns.pack(fill=tk.X, padx=22, pady=(8, 18))
        ttk.Button(btns, text="取消",
                   command=lambda: self._finish_start_confirmation(False)).pack(
                       side=tk.RIGHT, padx=(8, 0))
        ttk.Button(btns, text="继续并启动",
                   command=lambda: self._finish_start_confirmation(True)).pack(
                       side=tk.RIGHT)

        win.protocol("WM_DELETE_WINDOW",
                     lambda: self._finish_start_confirmation(False))
        win.bind('<Escape>', lambda _e: self._finish_start_confirmation(False))
        win.bind('<Return>', lambda _e: self._finish_start_confirmation(True))
        win.update_idletasks()
        if self.root.winfo_viewable():
            x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - win.winfo_width()) // 2)
            y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - win.winfo_height()) // 2)
            win.geometry("+%d+%d" % (x, y))
            win.grab_set()
        else:
            win.geometry("+%d+%d" % (
                max(0, (win.winfo_screenwidth() - win.winfo_width()) // 2),
                max(0, (win.winfo_screenheight() - win.winfo_height()) // 3)))
        win.lift()
        win.focus_force()
        self.root.wait_window(win)
        return bool(self._start_confirm_result)

    def _finish_start_confirmation(self, confirmed):
        """关闭启动确认框；仅在“继续”时应用“不再提示”。"""
        win = getattr(self, '_start_confirm_window', None)
        if win is None:
            return
        try:
            if confirmed and self._start_confirm_remember_var.get():
                self.config['start_confirm_enabled'] = False
                self.save_config()
                try:
                    self.confirm_start_var.set(False)
                except Exception:
                    pass
                self.log_message("启动前确认已关闭（用户勾选不再提示）")
            self._start_confirm_result = bool(confirmed)
            try:
                win.grab_release()
            except Exception:
                pass
            win.destroy()
        finally:
            self._start_confirm_window = None

    def show_end_summary(self, stats=None):
        """停止后展示本次运行摘要，并提供 JSON/CSV 导出。"""
        stats = stats or getattr(self, 'last_run_stats', None) or {}
        try:
            pal = self._resolve_palette()
        except Exception:
            pal = _theme_resolve_palette('light')
        self._close_end_summary()
        win = tk.Toplevel(self.root)
        self._end_summary_window = win
        win.title("运行结束 · 摘要")
        win.configure(bg=pal['bg'])
        win.resizable(False, False)
        if self.root.winfo_viewable():
            win.transient(self.root)

        tk.Label(win, text="本次运行已停止", bg=pal['bg'], fg=pal['text'],
                 font=('微软雅黑', 16, 'bold')).pack(anchor=tk.W, padx=22, pady=(18, 4))
        tk.Label(win, text="统计来自运行快照，与日志中的运行摘要一致。",
                 bg=pal['bg'], fg=pal['muted'],
                 font=('微软雅黑', 9)).pack(anchor=tk.W, padx=22)
        card = tk.Frame(win, bg=pal['surface'], highlightthickness=1,
                        highlightbackground=pal['border'], padx=14, pady=10)
        card.pack(fill=tk.X, padx=22, pady=(12, 6))
        for line in _run_report.build_end_lines(stats):
            tk.Label(card, text=str(line), bg=pal['surface'], fg=pal['text'],
                     font=('微软雅黑', 10), justify=tk.LEFT, anchor=tk.W,
                     wraplength=470).pack(anchor=tk.W, pady=2)

        btns = ttk.Frame(win)
        btns.pack(fill=tk.X, padx=22, pady=(8, 18))
        ttk.Button(btns, text="导出 JSON",
                   command=lambda: self._export_last_run_stats('json')).pack(
                       side=tk.LEFT)
        ttk.Button(btns, text="导出 CSV",
                   command=lambda: self._export_last_run_stats('csv')).pack(
                       side=tk.LEFT, padx=(8, 0))
        ttk.Button(btns, text="关闭", command=self._close_end_summary).pack(
            side=tk.RIGHT)
        win.protocol("WM_DELETE_WINDOW", self._close_end_summary)
        win.bind('<Escape>', lambda _e: self._close_end_summary())
        win.update_idletasks()
        if self.root.winfo_viewable():
            x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - win.winfo_width()) // 2)
            y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - win.winfo_height()) // 2)
            win.geometry("+%d+%d" % (x, y))
            win.grab_set()
        else:
            win.geometry("+%d+%d" % (
                max(0, (win.winfo_screenwidth() - win.winfo_width()) // 2),
                max(0, (win.winfo_screenheight() - win.winfo_height()) // 3)))
        win.lift()
        win.focus_force()

    def _close_end_summary(self):
        win = getattr(self, '_end_summary_window', None)
        if win is None:
            return
        try:
            try:
                win.grab_release()
            except Exception:
                pass
            win.destroy()
        finally:
            self._end_summary_window = None

    def _export_last_run_stats(self, fmt=None):
        """导出最近一次运行统计；fmt 为空时按文件扩展名判断。"""
        from tkinter import filedialog
        stats = getattr(self, 'last_run_stats', None)
        if not stats or not stats.get('timestamp'):
            messagebox.showinfo("提示", "暂无可导出的运行统计（请先完成一次运行）")
            return
        try:
            stamp = str(stats.get('timestamp', '')).replace(':', '-').replace('T', '-')
            if fmt in ('json', 'csv'):
                types = [("JSON", "*.json")] if fmt == 'json' else [("CSV", "*.csv")]
                path = filedialog.asksaveasfilename(
                    defaultextension='.' + fmt, filetypes=types,
                    initialfile='AutoClicker-run-%s.%s' % (stamp, fmt),
                    title="导出运行统计")
            else:
                path = filedialog.asksaveasfilename(
                    defaultextension=".json",
                    filetypes=[("JSON", JSON_FILE_PATTERN), ("CSV", "*.csv")],
                    initialfile='AutoClicker-run-%s.json' % stamp,
                    title="导出运行统计")
            if not path:
                return
            out_fmt = fmt or ('csv' if path.lower().endswith('.csv') else 'json')
            _run_report.write_stats(path, stats, out_fmt)
            self.log_message("运行统计已导出(%s)：%s" % (out_fmt, path))
            messagebox.showinfo(
                "导出成功", "运行统计已导出：\n" + path,
                parent=getattr(self, '_end_summary_window', None) or self.root)
        except Exception as e:
            messagebox.showerror(
                "错误", "导出失败: " + str(e),
                parent=getattr(self, '_end_summary_window', None) or self.root)

    def export_run_stats(self):
        """将最近一次运行统计导出为 JSON / CSV（REQ-004）"""
        self._export_last_run_stats()

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
        """将 config 参数回填到所有 UI 控件（方案切换 / 迁移后调用）

        回填期间挂起输入变量 trace，避免 interval 先写入触发 save_config，
        把尚未回填的 click_limit/duration_limit 用旧值覆盖掉配置。
        """
        self._config_ui_syncing = True
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
            if getattr(self, 'confirm_start_var', None) is not None:
                self.confirm_start_var.set(bool(self.config.get('start_confirm_enabled', True)))
            self.hotkey_start_var.set(self.config.get('hotkey_start', 'f6'))
            self.hotkey_emergency_var.set(self.config.get('hotkey_emergency', 'f8'))
            sched = self.config.get('schedule') or {}
            self.schedule_enabled_var.set(bool(sched.get('enabled', False)))
            self.schedule_start_var.set(str(sched.get('start_at', '09:00')))
            self.schedule_stop_var.set(str(sched.get('stop_after_min', 0)))
            self.schedule_days_var.set(self._weekdays_to_label(sched.get('weekdays', [1, 2, 3, 4, 5])))
            self._refresh_multi_point_listbox()
        except Exception as e:
            print("回填 UI 失败: " + str(e))
        finally:
            self._config_ui_syncing = False

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
        """信息架构：顶部状态条 + 左侧 4 导航 + 底部固定操作条（FR-24）。"""
        self._icons_ready = False
        self.root.minsize(getattr(self, '_min_w', 900), getattr(self, '_min_h', 620))

        main_container = ttk.Frame(self.root)
        main_container.pack(fill=tk.BOTH, expand=True)

        topbar = ttk.Frame(main_container, padding=(12, 8, 12, 4))
        topbar.pack(side=tk.TOP, fill=tk.X)
        bottom_bar = ttk.Frame(main_container, padding=(12, 6, 12, 8))
        bottom_bar.pack(side=tk.BOTTOM, fill=tk.X)
        body = ttk.Frame(main_container)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        nav_panel = ttk.Frame(body, padding=(8, 8, 4, 8))
        nav_panel.pack(side=tk.LEFT, fill=tk.Y)
        nav_panel.pack_propagate(False)
        nav_panel.configure(width=156)
        content_host = ttk.Frame(body)
        content_host.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        content_host.grid_rowconfigure(0, weight=1)
        content_host.grid_columnconfigure(0, weight=1)

        self._page_holders = {}
        self._page_canvases = {}
        self._page_frames = {}
        self.main_canvas = None
        self.run_page = self._create_page(content_host, 'run', padding=16)
        self.rules_page = self._create_page(content_host, 'rules', padding=14)
        self.records_page = self._create_page(content_host, 'records', padding=14)
        self.settings_page = self._create_page(content_host, 'settings', padding=14)
        self.main_frame = self.run_page
        self._bind_main_mousewheel()

        # 左侧导航不超过 4 项
        ttk.Label(nav_panel, text="AutoClicker", font=('微软雅黑', 12, 'bold')).pack(
            anchor=tk.W, padx=8, pady=(4, 12))
        self.nav_buttons = {}
        for key, label in (('run', '运行台'), ('rules', '规则'),
                           ('records', '记录'), ('settings', '设置')):
            btn = tk.Button(nav_panel, text=label, anchor=tk.W, justify=tk.LEFT,
                            command=lambda k=key: self._show_page(k),
                            font=('微软雅黑', 10, 'bold'), padx=12, pady=8,
                            relief=tk.FLAT, bd=0, cursor='hand2')
            btn.pack(fill=tk.X, pady=2)
            self.nav_buttons[key] = btn
        ttk.Label(nav_panel, text="F6 启动/停止\nF8 / Esc 急停",
                  font=('微软雅黑', 8), foreground=self._color('muted'),
                  justify=tk.LEFT).pack(side=tk.BOTTOM, anchor=tk.W, padx=8, pady=8)

        # ==================== 顶部状态条 ====================
        header_frame = ttk.Frame(topbar)
        header_frame.pack(fill=tk.X)
        self.header_frame = header_frame
        # 8.3 操作级提示：顶部可关闭横幅（按需 pack，位于 header 之前）
        self._notice_bar = NoticeBar(topbar, self._color)

        title_container = ttk.Frame(header_frame)
        title_container.pack(fill=tk.X)
        title_label = ttk.Label(title_container, text="桌面自动点击工具",
                               font=('微软雅黑', 16, 'bold'))
        title_label.pack(side=tk.LEFT)
        self.title_version_label = ttk.Label(
            title_container, text=get_version_text(),
            font=('微软雅黑', 8), foreground=self._color('muted'))
        self.title_version_label.pack(side=tk.LEFT, padx=(10, 0))

        # FR-25：简单 / 高级双模式，记住选择，切换不重置参数
        mode_frame = ttk.Frame(title_container)
        mode_frame.pack(side=tk.LEFT, padx=(14, 0))
        ttk.Label(mode_frame, text="模式", font=('微软雅黑', 8),
                  foreground=self._color('muted')).pack(side=tk.LEFT, padx=(0, 3))
        self.ui_mode_var = tk.StringVar(value=self.config.get('ui_mode', 'simple'))
        for text, value in (("简单", "simple"), ("高级", "advanced")):
            ttk.Radiobutton(mode_frame, text=text, value=value,
                            variable=self.ui_mode_var,
                            command=self.on_ui_mode_change).pack(side=tk.LEFT, padx=2)

        self.status_indicator = tk.Canvas(title_container, width=12, height=12,
                                         highlightthickness=0, bg='white')
        self.status_indicator.pack(side=tk.RIGHT, padx=5)
        self.status_circle = self.status_indicator.create_oval(2, 2, 10, 10, fill='red', outline='')
        self.status_text_label = ttk.Label(title_container, text="已停止",
                                          font=('微软雅黑', 11, 'bold'),
                                          foreground=self._color('danger'))
        self.status_text_label.pack(side=tk.RIGHT, padx=5)

        # 顶部固定状态条：状态/倒计时/计数/运行时长
        status_strip = ttk.Frame(topbar)
        status_strip.pack(fill=tk.X, pady=(5, 0))
        self.status_bar = status_strip
        self.sb_status_label = ttk.Label(status_strip, text="● 已停止",
                                         font=('微软雅黑', 9, 'bold'),
                                         foreground=self._color('danger'))
        self.sb_status_label.pack(side=tk.LEFT)
        ttk.Label(status_strip, text="倒计时", font=('微软雅黑', 8)).pack(
            side=tk.LEFT, padx=(10, 3))
        self.countdown_bar = ttk.Progressbar(status_strip, orient='horizontal',
                                             length=110, mode='determinate', maximum=100)
        self.countdown_bar.pack(side=tk.LEFT, padx=(0, 4))
        self.countdown_bar['value'] = 0
        self.sb_countdown_label = ttk.Label(status_strip, text="--",
                                            font=('微软雅黑', 8),
                                            foreground=self._color('muted'))
        self.sb_countdown_label.pack(side=tk.LEFT, padx=(0, 12))
        self.sb_count_label = ttk.Label(status_strip, text="总点击: 0", font=('微软雅黑', 9))
        self.sb_count_label.pack(side=tk.LEFT, padx=(0, 12))
        self.sb_success_label = ttk.Label(status_strip, text="成功: 0",
                                          font=('微软雅黑', 9),
                                          foreground=self._color('success'))
        self.sb_success_label.pack(side=tk.LEFT, padx=(0, 10))
        self.sb_fail_label = ttk.Label(status_strip, text="失败: 0",
                                       font=('微软雅黑', 9),
                                       foreground=self._color('danger'))
        self.sb_fail_label.pack(side=tk.LEFT, padx=(0, 10))
        self.sb_runtime_label = ttk.Label(status_strip, text="运行时长: 00:00",
                                          font=('微软雅黑', 9),
                                          foreground=self._color('primary'))
        self.sb_runtime_label.pack(side=tk.LEFT)

        # FR-L01 / 6.12.1：Wayland 降级横幅（可关闭；纯文本，保持 UI-02 零 emoji）
        if not self.input_ok:
            warn_bar = tk.Frame(topbar, bg=self._color('warning'))
            warn_bar.pack(fill=tk.X, pady=(6, 0))
            tk.Label(warn_bar,
                     text="注意：Wayland 会话不支持模拟输入，启动已禁用",
                     bg=self._color('warning'), fg=self._color('on_warning'),
                     font=('微软雅黑', 9, 'bold'), wraplength=500,
                     justify=tk.LEFT, anchor=tk.W).pack(
                         side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 6), pady=5)
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

        # ==================== 运行台 ====================
        run_card = ttk.LabelFrame(self.run_page, text="运行台", padding="18")
        run_card.pack(fill=tk.X, pady=(0, 14))
        self.run_state_label = ttk.Label(run_card, text="已停止",
                                         font=('微软雅黑', 22, 'bold'),
                                         foreground=self._color('danger'))
        self.run_state_label.pack(anchor=tk.W)
        ttk.Label(run_card, text="底部操作条固定可用；点击参数在「规则」页维护。",
                  font=('微软雅黑', 10), foreground=self._color('muted')).pack(
                      anchor=tk.W, pady=(2, 10))
        ttk.Separator(run_card, orient='horizontal').pack(fill=tk.X, pady=(0, 10))
        self.run_summary_label = ttk.Label(run_card, text=self._run_summary_text(),
                                           font=('微软雅黑', 10), justify=tk.LEFT)
        self.run_summary_label.pack(anchor=tk.W)
        self.run_next_label = ttk.Label(run_card, text="下次计划：--",
                                        font=('微软雅黑', 9),
                                        foreground=self._color('primary'))
        self.run_next_label.pack(anchor=tk.W, pady=(8, 0))
        ttk.Button(run_card, text="调整点击规则", command=lambda: self._show_page('rules')).pack(
            anchor=tk.W, pady=(12, 0))

        # ==================== 底部固定操作条 ====================
        ttk.Separator(bottom_bar, orient='horizontal').pack(fill=tk.X, pady=(0, 6))
        bottom_row = ttk.Frame(bottom_bar)
        bottom_row.pack(fill=tk.X)
        main_control_frame = ttk.Frame(bottom_row)
        main_control_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # 主控制按钮：tk.Button 带 image 时 width/height 为像素，改用 padx/pady 控制留白。
        self.start_btn = tk.Button(main_control_frame, text=" 启动自动点击",
                                  command=self.start_clicking,
                                  font=('微软雅黑', 12, 'bold'),
                                  bg=self._color('success'), fg=self._color('on_success'),
                                  activebackground=self._shade(self._color('success')),
                                  activeforeground=self._color('on_success'),
                                  padx=12, pady=7, cursor='hand2',
                                  relief=tk.FLAT, bd=0)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8), fill=tk.X, expand=True)

        self.stop_btn = tk.Button(main_control_frame, text=" 停止",
                                 command=self.stop_clicking,
                                 font=('微软雅黑', 12, 'bold'),
                                 bg=self._color('danger'), fg=self._color('on_danger'),
                                 activebackground=self._shade(self._color('danger')),
                                 activeforeground=self._color('on_danger'),
                                 padx=12, pady=7, cursor='hand2',
                                 relief=tk.FLAT, bd=0, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 8), fill=tk.X, expand=True)

        self.test_btn = tk.Button(main_control_frame, text=" 测试点击",
                                 command=self.test_click,
                                 font=('微软雅黑', 10),
                                 bg=self._color('primary'), fg=self._color('on_primary'),
                                 activebackground=self._shade(self._color('primary')),
                                 activeforeground=self._color('on_primary'),
                                 padx=12, pady=7, cursor='hand2',
                                 relief=tk.FLAT, bd=0)
        self.test_btn.pack(side=tk.LEFT, fill=tk.X)

        shortcut_frame = ttk.Frame(bottom_row)
        shortcut_frame.pack(side=tk.RIGHT, padx=(12, 0))
        ttk.Label(shortcut_frame, text="F6 启停 · F8/Esc 急停",
                  font=('微软雅黑', 8), foreground=self._color('muted')).pack(anchor=tk.E)
        self.footer_version_label = ttk.Label(
            shortcut_frame, text=get_version_text(),
            font=('微软雅黑', 8), foreground=self._color('muted'))
        self.footer_version_label.pack(anchor=tk.E)

        # 默认选中运行台
        self._active_page = 'run'
        self._show_page('run')

        # ==================== 配置区域 - 两列布局 ====================
        config_container = ttk.Frame(self.rules_page)
        config_container.pack(fill=tk.X, pady=(0, 15))
        
        # 左列 - 基本配置
        self.left_card = ttk.LabelFrame(config_container, text="目标", padding="15")
        self.left_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        left_card = self.left_card
        
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
        self.right_card = ttk.LabelFrame(config_container, text="状态监控", padding="15")
        self.right_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right_card = self.right_card
        
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
        options_frame = ttk.LabelFrame(right_card, text="选项", padding="10")
        options_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.prevent_sleep_var = tk.BooleanVar(value=self.config['prevent_sleep'])
        self.prevent_sleep_check = ttk.Checkbutton(options_frame, text="防止系统锁屏",
                                             variable=self.prevent_sleep_var,
                                             command=self.on_prevent_sleep_changed)
        self.prevent_sleep_check.pack(anchor=tk.W, pady=3)

        # 鼠标跟随设置（高级模式可见）
        self.motion_frame = ttk.Frame(options_frame)
        self.motion_frame.pack(fill=tk.X)
        self.mouse_follow_var = tk.BooleanVar(value=self.config['mouse_follow_enabled'])
        mouse_follow_check = ttk.Checkbutton(self.motion_frame, text="鼠标跟随移动",
                                             variable=self.mouse_follow_var,
                                             command=self.on_mouse_follow_changed)
        mouse_follow_check.pack(anchor=tk.W, pady=3)
        
        self.mouse_move_only_var = tk.BooleanVar(value=self.config['mouse_move_only'])
        mouse_move_only_check = ttk.Checkbutton(self.motion_frame, text="   只移动不点击",
                                                variable=self.mouse_move_only_var,
                                                command=self.on_mouse_move_only_changed)
        mouse_move_only_check.pack(anchor=tk.W, pady=3)
        
        # 鼠标移动速度调节
        speed_container = ttk.Frame(self.motion_frame)
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
        self.safety_card = ttk.LabelFrame(self.rules_page, text="安全", padding="15")
        self.safety_card.pack(fill=tk.X, pady=(0, 15))
        safety_card = self.safety_card

        # 启动倒计时（CX-04）
        self.countdown_container = ttk.Frame(safety_card)
        self.countdown_container.pack(fill=tk.X, pady=(0, 8))
        countdown_container = self.countdown_container
        ttk.Label(countdown_container, text="启动倒计时(秒, 0-5)",
                 font=('微软雅黑', 10, 'bold')).pack(side=tk.LEFT)
        self.countdown_var = tk.StringVar(value=str(self.config.get('startup_countdown', 3)))
        ttk.Entry(countdown_container, textvariable=self.countdown_var,
                 font=('微软雅黑', 11), width=8, justify='center').pack(side=tk.LEFT, padx=(5, 0))

        # FR-E03：前台目标窗口校验（标题/进程名关键字，留空不校验）
        self.target_container = ttk.Frame(safety_card)
        self.target_container.pack(fill=tk.X, pady=(0, 8))
        target_container = self.target_container
        ttk.Label(target_container, text="目标窗口关键字(留空=不校验)",
                 font=('微软雅黑', 10, 'bold')).pack(side=tk.LEFT)
        self.target_window_var = tk.StringVar(value=str(self.config.get('target_window_keyword', '')))
        ttk.Entry(target_container, textvariable=self.target_window_var,
                 font=('微软雅黑', 11), width=24).pack(side=tk.LEFT, padx=(5, 0))

        # 点击次数上限（CX-02）
        self.limit_container = ttk.Frame(safety_card)
        self.limit_container.pack(fill=tk.X, pady=(0, 8))
        limit_container = self.limit_container
        ttk.Label(limit_container, text="点击次数上限(0=无限)",
                 font=('微软雅黑', 10, 'bold')).pack(side=tk.LEFT)
        self.click_limit_var = tk.StringVar(value=str(self.config.get('click_limit', 0)))
        ttk.Entry(limit_container, textvariable=self.click_limit_var,
                 font=('微软雅黑', 11), width=8, justify='center').pack(side=tk.LEFT, padx=(5, 0))

        # 运行时长上限（CX-02）
        self.duration_container = ttk.Frame(safety_card)
        self.duration_container.pack(fill=tk.X, pady=(0, 8))
        duration_container = self.duration_container
        ttk.Label(duration_container, text="运行时长上限(分钟, 0=无限)",
                 font=('微软雅黑', 10, 'bold')).pack(side=tk.LEFT)
        self.duration_limit_var = tk.StringVar(value=str(self.config.get('duration_limit', 0)))
        ttk.Entry(duration_container, textvariable=self.duration_limit_var,
                 font=('微软雅黑', 11), width=8, justify='center').pack(side=tk.LEFT, padx=(5, 0))

        # 鼠标位移 failsafe（CX-01）
        self.failsafe_var = tk.BooleanVar(value=self.config.get('failsafe_enabled', False))
        self.failsafe_check = ttk.Checkbutton(
            safety_card, text="鼠标移动即停 (failsafe，移动>20px自动急停)",
            variable=self.failsafe_var)
        self.failsafe_check.pack(anchor=tk.W)

        # 关闭行为（CX-06）
        self.close_to_tray_var = tk.BooleanVar(value=self.config.get('close_to_tray', True))
        self.close_tray_check = ttk.Checkbutton(
            safety_card, text="关闭窗口时最小化到托盘（否则直接退出）",
            variable=self.close_to_tray_var,
            command=self.on_close_behavior_changed)
        self.close_tray_check.pack(anchor=tk.W, pady=(4, 0))

        # ==================== P1 功能扩展：点击 / 节奏 / 多点位 ====================
        self.p1_card = ttk.LabelFrame(self.rules_page, text="节奏与点击 (高级)", padding="15")
        self.p1_card.pack(fill=tk.X, pady=(0, 15))
        p1_card = self.p1_card

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
        self.p1b_card = ttk.LabelFrame(self.rules_page, text="高级", padding="15")
        self.p1b_card.pack(fill=tk.X, pady=(0, 15))
        p1b_card = self.p1b_card

        hk_row = ttk.Frame(p1b_card)
        hk_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(hk_row, text="启动/停止键", font=('微软雅黑', 10, 'bold')).pack(side=tk.LEFT)
        self.hotkey_start_var = tk.StringVar(value=self.config.get('hotkey_start', 'f6'))
        ttk.Entry(hk_row, textvariable=self.hotkey_start_var, width=8).pack(side=tk.LEFT, padx=(5, 15))
        ttk.Label(hk_row, text="紧急停止键", font=('微软雅黑', 10, 'bold')).pack(side=tk.LEFT)
        self.hotkey_emergency_var = tk.StringVar(value=self.config.get('hotkey_emergency', 'f8'))
        ttk.Entry(hk_row, textvariable=self.hotkey_emergency_var, width=8).pack(side=tk.LEFT, padx=(5, 10))
        ttk.Button(hk_row, text="应用热键", command=self.on_hotkey_apply).pack(side=tk.LEFT)

        # FR-D01 定时计划（每日 HH:MM 启动 / 运行 N 分钟后停止 / 工作日）
        sched_cfg = self.config.get('schedule') or {}
        sched_row = ttk.Frame(p1b_card)
        sched_row.pack(fill=tk.X, pady=(0, 6))
        self.schedule_enabled_var = tk.BooleanVar(value=bool(sched_cfg.get('enabled', False)))
        ttk.Checkbutton(sched_row, text="定时计划", variable=self.schedule_enabled_var).pack(side=tk.LEFT)
        ttk.Label(sched_row, text="启动 HH:MM").pack(side=tk.LEFT, padx=(6, 2))
        self.schedule_start_var = tk.StringVar(value=str(sched_cfg.get('start_at', '09:00')))
        ttk.Entry(sched_row, textvariable=self.schedule_start_var, width=7,
                  justify='center').pack(side=tk.LEFT)
        ttk.Label(sched_row, text="运行(分)").pack(side=tk.LEFT, padx=(8, 2))
        self.schedule_stop_var = tk.StringVar(value=str(sched_cfg.get('stop_after_min', 0)))
        ttk.Entry(sched_row, textvariable=self.schedule_stop_var, width=5,
                  justify='center').pack(side=tk.LEFT)
        self.schedule_days_var = tk.StringVar(
            value=self._weekdays_to_label(sched_cfg.get('weekdays', [1, 2, 3, 4, 5])))
        ttk.Combobox(sched_row, textvariable=self.schedule_days_var, width=7,
                     values=['每天', '工作日', '周末'], state='readonly').pack(side=tk.LEFT, padx=(8, 2))
        ttk.Button(sched_row, text="应用计划", command=self.on_schedule_apply).pack(side=tk.LEFT)
        self.schedule_hint_label = ttk.Label(p1b_card, text="", font=('微软雅黑', 9))
        self.schedule_hint_label.pack(anchor=tk.W)

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
        self.log_card = ttk.LabelFrame(self.records_page, text="运行日志", padding="10")
        self.log_card.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        log_card = self.log_card

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
        
        # ==================== 设置：外观 ====================
        theme_card = ttk.LabelFrame(self.settings_page, text="外观", padding="15")
        theme_card.pack(fill=tk.X, pady=(0, 14))
        ttk.Label(theme_card, text="主题", font=('微软雅黑', 10, 'bold')).pack(anchor=tk.W)
        theme_row = ttk.Frame(theme_card)
        theme_row.pack(fill=tk.X, pady=(6, 0))
        self.theme_var = tk.StringVar(value=self._current_theme_display_name())
        self.theme_combo = ttk.Combobox(theme_row, textvariable=self.theme_var,
                                        values=list(self._theme_name_map.keys()),
                                        state='readonly', width=18)
        self.theme_combo.pack(side=tk.LEFT, padx=(0, 6))
        self.theme_combo.bind('<<ComboboxSelected>>', self.on_theme_change_ui)
        ttk.Button(theme_row, text="导入主题", command=self.import_user_theme,
                   width=9).pack(side=tk.LEFT)
        ttk.Label(theme_card, text="主题包仅包含 JSON 颜色令牌，不执行脚本。",
                  font=('微软雅黑', 8), foreground=self._color('muted')).pack(
                      anchor=tk.W, pady=(6, 0))

        # ==================== 设置：启动安全（FR-02） ====================
        safety_card = ttk.LabelFrame(self.settings_page, text="启动安全", padding="15")
        safety_card.pack(fill=tk.X, pady=(0, 14))
        self.confirm_start_var = tk.BooleanVar(
            value=bool(self.config.get('start_confirm_enabled', True)))
        ttk.Checkbutton(safety_card, text="启动前显示参数确认摘要",
                        variable=self.confirm_start_var,
                        command=self.on_confirm_start_changed).pack(anchor=tk.W)
        ttk.Label(safety_card,
                  text="确认框展示间隔、目标、停止条件与热键；取消不会启动。"
                       "每次停止后展示运行摘要，可导出 JSON/CSV。",
                  font=('微软雅黑', 8), foreground=self._color('muted')).pack(
                      anchor=tk.W, pady=(6, 0))

        # ==================== 设置：关于（FR-04） ====================
        about_card = ttk.LabelFrame(self.settings_page, text="关于", padding="15")
        about_card.pack(fill=tk.X, pady=(0, 14))
        about_grid = ttk.Frame(about_card)
        about_grid.pack(fill=tk.X)
        rows = (
            ("产品版本", "v%s" % APP_VERSION),
            ("构建号", BUILD_ID),
            ("Python", "%d.%d.%d" % sys.version_info[:3]),
            ("配置文件", self.config_file),
            ("日志目录", getattr(self, 'log_dir', os.path.expanduser('~/.auto_clicker_logs'))),
            ("许可证", "MIT License"),
        )
        for idx, (name, value) in enumerate(rows):
            ttk.Label(about_grid, text=name + "：", font=('微软雅黑', 9, 'bold')).grid(
                row=idx, column=0, sticky='w', padx=(0, 8), pady=2)
            ttk.Label(about_grid, text=str(value), font=('微软雅黑', 9)).grid(
                row=idx, column=1, sticky='w', pady=2)
        about_btns = ttk.Frame(about_card)
        about_btns.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(about_btns, text="打开配置目录", command=self.open_config_dir).pack(
            side=tk.LEFT, padx=(0, 6))
        ttk.Button(about_btns, text="打开日志目录", command=self.open_log_dir).pack(
            side=tk.LEFT, padx=(0, 6))
        ttk.Button(about_btns, text="复制版本信息", command=self.copy_version_info).pack(
            side=tk.LEFT, padx=(0, 6))
        ttk.Button(about_btns, text="重跑首启向导",
                   command=lambda: self.show_onboarding_wizard(force=True)).pack(
                       side=tk.LEFT, padx=(0, 6))
        ttk.Button(about_btns, text="项目主页", command=self.open_project_home).pack(
            side=tk.LEFT)

        # ==================== 底部提示区域 ====================
        footer_frame = ttk.Frame(self.settings_page)
        footer_frame.pack(fill=tk.X)
        ttk.Label(footer_frame, text="快捷键: F6 启动/停止 · F8/Esc 紧急停止",
                  font=('微软雅黑', 9), foreground=self._color('muted')).pack(anchor=tk.CENTER)
        ttk.Label(footer_frame, text="v%s (Build %s)" % (APP_VERSION, BUILD_ID),
                  font=('微软雅黑', 8), foreground=self._color('muted')).pack(anchor=tk.CENTER)

        # 更新状态标签引用
        self.status_label = self.status_text_label
        self._apply_ui_mode()
        self._show_page('run')
        
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
            if getattr(self, 'run_state_label', None) is not None:
                self.run_state_label.config(text=text, foreground=color)
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
        self.exception_count = 0
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
                val = self.interval_var.get()
            except Exception:
                val = 1.0
        return _engine_effective_interval_seconds(val, self.interval_unit)

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
        return _engine_jittered_wait(base_seconds, self.jitter_pct, _RANDOM)

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
        final_ok = bool(ok)
        if ok:
            self.log_message(f"在位置 ({x}, {y}) 执行点击[按键={self.click_button}]")
        else:
            final_ok = bool(_pyautogui_click(x, y, self.click_button))
            if final_ok:
                self.log_message(f"使用pyautogui在位置 ({x}, {y}) 执行点击")
            else:
                self.log_message(f"点击失败且 pyautogui 不可用: ({x}, {y})")
        self.click_count += 1
        if final_ok:
            self.success_count += 1
        else:
            self.fail_count += 1
        self._ui(self.click_count_label.config, text=str(self.click_count))
        self._ui(self._set_sb_counts)
        return final_ok

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
                self.exception_count += 1
                self._ui(self._set_sb_counts)
                time.sleep(1)
                
    def _read_interval(self):
        """读取并校验点击间隔，非法时行内红字提示并返回 None。"""
        value, error = _engine_validate_interval(self.interval_var.get())
        if error:
            self.show_field_error(error)
            return None
        self.clear_field_error()
        return value

    def _read_countdown(self):
        """读取并校验启动倒计时（0-5 秒）。"""
        value, error = _engine_validate_countdown(self.countdown_var.get())
        if error:
            self.show_field_error(error)
            return None
        self.clear_field_error()
        return value

    def _read_click_limit(self):
        """读取并校验点击次数上限（0 表示无限）。"""
        value, error = _engine_validate_click_limit(self.click_limit_var.get())
        if error:
            self.show_field_error(error)
            return None
        self.clear_field_error()
        return value

    def _read_duration_limit(self):
        """读取并校验运行时长上限（分钟，0 表示无限）。"""
        value, error = _engine_validate_duration_limit(self.duration_limit_var.get())
        if error:
            self.show_field_error(error)
            return None
        self.clear_field_error()
        return value

    def _read_jitter(self):
        """读取并校验随机抖动百分比（0-100）。"""
        value, error = _engine_validate_jitter(self.jitter_var.get())
        if error:
            self.show_field_error(error)
            return None
        self.clear_field_error()
        return value

    def _read_hold_ms(self):
        """读取并校验按住时长（毫秒）。"""
        value, error = _engine_validate_hold_ms(self.hold_ms_var.get())
        if error:
            self.show_field_error(error)
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

    def start_clicking(self, source='manual'):
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

            self._close_end_summary()
            snapshot = self._confirmation_snapshot(
                interval, countdown, click_limit, duration_limit, jitter, hold_ms)
            if not self._confirm_start(snapshot, source):
                self.log_message("启动已取消：用户在启动确认框选择取消")
                return

            self.is_running = True
            self.click_count = 0
            self.success_count = 0
            self.fail_count = 0
            self.exception_count = 0
            self._pending_end_summary = False
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
        was_running = bool(getattr(self, 'is_running', False))
        self.is_running = False
        self.countdown_cancelled = False

        if self.click_thread:
            try:
                # 自动停止（点击上限/failsafe）会在点击线程内回调本方法，
                # 此时 join 自身会抛 RuntimeError 并中断后续状态复位（CX-02）。
                if threading.current_thread() is not self.click_thread:
                    self.click_thread.join(timeout=2)
            except RuntimeError:
                pass

        # REQ-004 / FR-02：等点击线程收尾后再记录快照，确保成功/失败计数完整
        try:
            runtime = max(0.0, time.time() - getattr(self, 'start_time', time.time()))
            self.last_run_stats = {
                'timestamp': datetime.now().isoformat(timespec='seconds'),
                'click_count': getattr(self, 'click_count', 0),
                'success_count': getattr(self, 'success_count', 0),
                'fail_count': getattr(self, 'fail_count', 0),
                'exception_count': getattr(self, 'exception_count', 0),
                'runtime_seconds': round(runtime, 1),
                'interval_seconds': self._effective_interval_seconds(),
                'mode': self.config.get('click_mode', ''),
                'button': getattr(self, 'click_button', ''),
                'stop_reason': str(reason or '').strip() or '手动停止',
            }
            self._pending_end_summary = bool(
                was_running and not getattr(self, '_suppress_end_summary', False))
            self.log_message(_run_report.log_summary_line(self.last_run_stats))
        except Exception:
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

        # FR-02：停止后展示运行摘要；退出清理时由 _suppress_end_summary 抑制
        pending_summary = bool(getattr(self, '_pending_end_summary', False))
        self._pending_end_summary = False
        if pending_summary and not getattr(self, '_suppress_end_summary', False):
            try:
                self.show_end_summary()
            except Exception as e:
                try:
                    self.log_message("展示运行结束摘要失败: " + str(e))
                except Exception:
                    pass

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
            dark = bool(getattr(self, '_current_palette', {}).get('is_dark', False))
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
        """停止托盘、点击线程、保活与全局热键；任何一步失败都不得阻断退出。"""
        self.is_running = False
        try:
            self._stop_runtime_tick()
        except Exception:
            pass
        try:
            self.stop_keepalive()
        except Exception:
            pass
        if self.click_thread and self.click_thread.is_alive():
            try:
                # 唤醒 _wait_exact，避免长间隔下 join 等待整个睡眠周期
                self._interval_change_event.set()
                self.click_thread.join(timeout=1.5)
            except Exception:
                pass
        try:
            self._remove_tray_icon()
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
        try:
            self.log_message("开始退出程序：清理线程、托盘与全局热键")
        except Exception:
            pass
        self._suppress_end_summary = True
        self._pending_end_summary = False
        try:
            self._close_end_summary()
        except Exception:
            pass
        self.is_running = False
        try:
            self._shutdown_runtime()
        except Exception:
            pass
        try:
            self._persist_state_on_exit()
        except Exception:
            pass
        try:
            self._cleanup_linux_instance_lock()
        except Exception:
            pass
        try:
            self.flush_logging()
        except Exception:
            pass
        _write_crash_log("APP_EXIT", "exit_application: cleanup finished")
        try:
            self.root.quit()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


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


def get_app_version():
    """产品版本（FR-04 双轨之一）。"""
    return APP_VERSION


def get_build_id():
    """日期构建号（FR-04 双轨之一）。"""
    return BUILD_ID


def get_version_text():
    """统一展示文本，供标题/关于页/日志使用。"""
    return "v%s (Build %s)" % (APP_VERSION, BUILD_ID)


def main():
    if '--version' in sys.argv or '-V' in sys.argv:
        print("AutoClicker %s" % get_version_text())
        return
    _install_crash_logging()
    _write_crash_log("APP_START", "version=%s argv=%s" % (get_version_text(), sys.argv))
    if not IS_SINGLE_INSTANCE:
        activate_existing_window()
        show_single_instance_warning()
        return
    
    setup_dpi_awareness()  # 必须在 tk.Tk() 之前，保证 DPI 感知对根窗口生效
    install_setting_restore_guards()
    root = tk.Tk()
    root.report_callback_exception = _tk_callback_exception

    app = AutoClicker(root)
    exit_code = 0
    try:
        app.root.mainloop()
    except BaseException:
        import traceback
        _write_crash_log("APP_MAINLOOP_EXCEPTION", traceback.format_exc())
        exit_code = 1
    finally:
        try:
            app.flush_logging()
        except Exception:
            pass
        _write_crash_log("APP_EXIT", "mainloop returned, exit_code=%d" % exit_code)
        # Windows 窗口版 onefile：强制结束 Python 解释器，确保临时目录中的
        # DLL/扩展句柄立即释放，避免 PyInstaller 父进程清理 _MEI 目录失败弹窗。
        # Linux 保留正常解释器退出，让 atexit 的 xset/系统设置恢复逻辑执行。
        if IS_WINDOWS:
            os._exit(exit_code)


if __name__ == "__main__":
    main()
