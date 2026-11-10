# -*- coding: utf-8 -*-
"""
桌面自动点击工具 - Python 3.14 兼容版
支持 Windows、银河麒麟等多操作系统
支持系统托盘最小化运行
"""

import sys
import os
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import random
import json
from datetime import datetime

# ==================== 平台检测 ====================
PLATFORM = sys.platform
IS_WINDOWS = PLATFORM == 'win32'
IS_LINUX = PLATFORM.startswith('linux')
IS_MACOS = PLATFORM == 'darwin'

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

def windows_click(x, y):
    """使用 Windows API 执行鼠标点击"""
    if HAS_WIN32API:
        try:
            ctypes.windll.user32.SetCursorPos(int(x), int(y))
            time.sleep(0.01)
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.01)
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            return True
        except Exception as e:
            print(f"点击失败：{e}")
            return False
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

def linux_click(x, y):
    """使用 X11 API 执行鼠标点击（银河麒麟兼容）"""
    if HAS_X11:
        try:
            d = display.Display()
            linux_move_mouse(x, y)
            time.sleep(0.01)
            fake_input(d, X.ButtonPress, 1)
            d.sync()
            time.sleep(0.01)
            fake_input(d, X.ButtonRelease, 1)
            d.sync()
            d.close()
            return True
        except Exception as e:
            print(f"Linux点击失败：{e}")
            # 降级使用 pyautogui
            try:
                pyautogui.click(x, y)
                return True
            except:
                return False
    else:
        try:
            pyautogui.click(x, y)
            return True
        except:
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

def click_mouse(x, y):
    """跨平台点击鼠标"""
    if IS_WINDOWS:
        return windows_click(x, y)
    elif IS_LINUX:
        return linux_click(x, y)
    else:
        pyautogui.click(x, y)
        return True

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
        
        # 增大窗口尺寸，确保所有内容都能显示
        self.root.geometry("650x700")
        # 增大最小尺寸
        self.root.minsize(600, 650)
        
        self.is_running = False
        self.click_thread = None
        self.config_file = os.path.expanduser("~/.auto_clicker_config_py3.json")
        
        self.setup_logging()
        self.load_config()
        self.setup_ui()
        self.setup_hotkeys()
        self.setup_tray_icon()
        
        # 关闭按钮直接退出程序
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
    def setup_logging(self):
        print("自动点击工具启动 (Python 3.14)")
            
    def load_config(self):
        default_config = {
            'interval_seconds': 10,
            'click_mode': 'random',
            'click_area': {'x': 0, 'y': 0, 'width': 1920, 'height': 1080},
            'prevent_sleep': True,
            'mouse_follow_enabled': True,  # 鼠标跟随功能
            'mouse_move_speed': 0.1,  # 鼠标移动速度 (0.0-1.0)
            'mouse_move_only': False  # 只移动不点击
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
        # 设置窗口最小尺寸
        self.root.minsize(700, 800)
        
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
        title_label = ttk.Label(title_container, text="🖱️ 桌面自动点击工具", 
                               font=('微软雅黑', 18, 'bold'))
        title_label.pack(side=tk.LEFT)
        
        # 状态指示器（带颜色圆点）
        self.status_indicator = tk.Canvas(title_container, width=12, height=12, 
                                         highlightthickness=0, bg='white')
        self.status_indicator.pack(side=tk.RIGHT, padx=5)
        self.status_circle = self.status_indicator.create_oval(2, 2, 10, 10, fill='red', outline='')
        
        self.status_text_label = ttk.Label(title_container, text="已停止", 
                                          font=('微软雅黑', 11, 'bold'), foreground='red')
        self.status_text_label.pack(side=tk.RIGHT, padx=5)
        
        # 分隔线
        separator = ttk.Separator(self.main_frame, orient='horizontal')
        separator.pack(fill=tk.X, pady=(0, 15))
        
        # ==================== 核心控制区域 ====================
        control_card = ttk.LabelFrame(self.main_frame, text="⚡ 核心控制", padding="15")
        control_card.pack(fill=tk.X, pady=(0, 15))
        
        # 主控制按钮 - 大按钮设计
        main_control_frame = ttk.Frame(control_card)
        main_control_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.start_btn = tk.Button(main_control_frame, text="▶ 启动自动点击", 
                                  command=self.start_clicking,
                                  font=('微软雅黑', 12, 'bold'),
                                  bg='#28a745', fg='white',
                                  activebackground='#218838', activeforeground='white',
                                  width=20, height=2, cursor='hand2',
                                  relief=tk.FLAT, bd=0)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 10), fill=tk.X, expand=True)
        
        self.stop_btn = tk.Button(main_control_frame, text="⏹ 停止", 
                                 command=self.stop_clicking,
                                 font=('微软雅黑', 12, 'bold'),
                                 bg='#dc3545', fg='white',
                                 activebackground='#c82333', activeforeground='white',
                                 width=15, height=2, cursor='hand2',
                                 relief=tk.FLAT, bd=0, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # 测试按钮
        self.test_btn = tk.Button(control_card, text="🎯 测试点击位置", 
                                 command=self.test_click,
                                 font=('微软雅黑', 10),
                                 bg='#17a2b8', fg='white',
                                 activebackground='#138496', activeforeground='white',
                                 height=1, cursor='hand2',
                                 relief=tk.FLAT, bd=0)
        self.test_btn.pack(fill=tk.X, pady=(5, 0))
        
        # ==================== 配置区域 - 两列布局 ====================
        config_container = ttk.Frame(self.main_frame)
        config_container.pack(fill=tk.X, pady=(0, 15))
        
        # 左列 - 基本配置
        left_card = ttk.LabelFrame(config_container, text="⚙️ 基本配置", padding="15")
        left_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        # 点击间隔配置
        interval_container = ttk.Frame(left_card)
        interval_container.pack(fill=tk.X, pady=(0, 12))
        
        ttk.Label(interval_container, text="⏱️ 点击间隔", 
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
        
        ttk.Label(mode_container, text="🎯 点击模式", 
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
        
        ttk.Label(area_container, text="📐 点击区域", 
                 font=('微软雅黑', 10, 'bold')).pack(anchor=tk.W)
        
        area_input_frame = ttk.Frame(area_container)
        area_input_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.area_label = ttk.Label(area_input_frame, 
                                   text=str(self.config['click_area']['width']) + "x" + str(self.config['click_area']['height']),
                                   font=('微软雅黑', 10), foreground='#007bff')
        self.area_label.pack(side=tk.LEFT, padx=(0, 10))
        
        self.set_area_btn = tk.Button(area_input_frame, text="设置区域", 
                                     command=self.set_click_area,
                                     font=('微软雅黑', 9),
                                     bg='#6c757d', fg='white',
                                     activebackground='#5a6268',
                                     cursor='hand2', relief=tk.FLAT, bd=0)
        self.set_area_btn.pack(side=tk.LEFT)
        
        # 右列 - 高级选项和状态
        right_card = ttk.LabelFrame(config_container, text="📊 状态监控", padding="15")
        right_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 状态信息
        status_info_frame = ttk.Frame(right_card)
        status_info_frame.pack(fill=tk.X, pady=(0, 10))
        
        # 下次点击时间
        next_click_container = ttk.Frame(status_info_frame)
        next_click_container.pack(fill=tk.X, pady=(0, 8))
        
        ttk.Label(next_click_container, text="⏰ 下次点击:", 
                 font=('微软雅黑', 9)).pack(side=tk.LEFT)
        self.next_click_label = ttk.Label(next_click_container, text="--", 
                                         font=('微软雅黑', 10, 'bold'), foreground='#007bff')
        self.next_click_label.pack(side=tk.LEFT, padx=(5, 0))
        
        # 点击次数
        count_container = ttk.Frame(status_info_frame)
        count_container.pack(fill=tk.X)
        
        ttk.Label(count_container, text="📈 点击次数:", 
                 font=('微软雅黑', 9)).pack(side=tk.LEFT)
        self.click_count_label = ttk.Label(count_container, text="0", 
                                          font=('微软雅黑', 14, 'bold'), foreground='#28a745')
        self.click_count_label.pack(side=tk.LEFT, padx=(5, 0))
        
        self.click_count = 0
        
        # 高级选项
        options_frame = ttk.LabelFrame(right_card, text="🔧 高级选项", padding="10")
        options_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.prevent_sleep_var = tk.BooleanVar(value=self.config['prevent_sleep'])
        prevent_sleep_check = ttk.Checkbutton(options_frame, text="☕ 防止系统锁屏",
                                             variable=self.prevent_sleep_var,
                                             command=self.on_prevent_sleep_changed)
        prevent_sleep_check.pack(anchor=tk.W, pady=3)

        # 鼠标跟随设置
        self.mouse_follow_var = tk.BooleanVar(value=self.config['mouse_follow_enabled'])
        mouse_follow_check = ttk.Checkbutton(options_frame, text="🖱️ 鼠标跟随移动",
                                             variable=self.mouse_follow_var,
                                             command=self.on_mouse_follow_changed)
        mouse_follow_check.pack(anchor=tk.W, pady=3)
        
        self.mouse_move_only_var = tk.BooleanVar(value=self.config['mouse_move_only'])
        mouse_move_only_check = ttk.Checkbutton(options_frame, text="   📍 只移动不点击",
                                                variable=self.mouse_move_only_var,
                                                command=self.on_mouse_move_only_changed)
        mouse_move_only_check.pack(anchor=tk.W, pady=3)
        
        # 鼠标移动速度调节
        speed_container = ttk.Frame(options_frame)
        speed_container.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Label(speed_container, text="⚡ 移动速度:", 
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
        
        # ==================== 日志区域 ====================
        log_card = ttk.LabelFrame(self.main_frame, text="📝 运行日志", padding="10")
        log_card.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # 日志工具栏
        log_toolbar = ttk.Frame(log_card)
        log_toolbar.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(log_toolbar, text="实时日志", font=('微软雅黑', 9), 
                 foreground='gray').pack(side=tk.LEFT)
        
        # 清空日志按钮
        clear_btn = tk.Button(log_toolbar, text="清空", 
                             command=self.clear_log,
                             font=('微软雅黑', 8),
                             bg='#dc3545', fg='white',
                             activebackground='#c82333',
                             cursor='hand2', relief=tk.FLAT, bd=0, width=6)
        clear_btn.pack(side=tk.RIGHT)
        
        # 日志文本框
        self.log_text = tk.Text(log_card, height=10, state=tk.DISABLED,
                               font=('Consolas', 9), bg='#f8f9fa',
                               relief=tk.FLAT, padx=5, pady=5)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(log_card, orient=tk.VERTICAL, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text['yscrollcommand'] = scrollbar.set
        
        # ==================== 底部提示区域 ====================
        footer_frame = ttk.Frame(self.main_frame)
        footer_frame.pack(fill=tk.X)
        
        # 快捷键提示
        shortcut_frame = ttk.Frame(footer_frame)
        shortcut_frame.pack(fill=tk.X, pady=(0, 5))
        
        shortcut_text = "⌨️ 快捷键: F6 - 快速启动/停止"
        ttk.Label(shortcut_frame, text=shortcut_text, 
                 font=('微软雅黑', 9), foreground='#6c757d').pack(anchor=tk.CENTER)
        
        # 版本信息
        version_label = ttk.Label(footer_frame, text="v2.0 (Python 3.14)", 
                                 font=('微软雅黑', 8), foreground='#adb5bd')
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
        if keyboard:
            try:
                keyboard.add_hotkey('f6', self.toggle_clicking)
                print("快捷键 F6 已注册")
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
        
        self.log_message(f"当前点击模式: {mode}")
        
        if mode == 'center':
            x = area['x'] + area['width'] // 2
            y = area['y'] + area['height'] // 2
        else:
            x = random.randint(area['x'], area['x'] + area['width'])
            y = random.randint(area['y'], area['y'] + area['height'])
            
        self.log_message(f"生成的点击位置: ({x}, {y})")
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
                
    def click_loop(self):
        while self.is_running:
            try:
                interval = int(self.interval_var.get())
                
                if self.prevent_sleep_var.get():
                    self.prevent_system_sleep()
                
                for remaining in range(interval, 0, -1):
                    if not self.is_running:
                        break
                    
                    self.next_click_label.config(text=f"{remaining}秒")
                    time.sleep(1)
                
                if not self.is_running:
                    break
                    
                x, y = self.get_click_position()
                
                # 鼠标跟随移动
                if self.mouse_follow_var.get():
                    try:
                        speed = float(self.mouse_speed_var.get())
                        # 根据速度调整移动时间，速度越快，时间越短
                        duration = max(0.1, 1.0 - speed)
                        self.log_message(f"[DEBUG] 移动到 ({x}, {y}), 速度={speed:.2f}, 持续时间={duration:.2f}秒")
                        self.smooth_move_to(x, y, duration=duration)
                        self.log_message(f"鼠标已移动到位置 ({x}, {y})")
                        # 短暂延迟，确保鼠标移动完成
                        time.sleep(0.1)
                    except Exception as e:
                        self.log_message(f"鼠标跟随失败: {e}")
                
                # 只移动不点击模式下不执行点击
                if not self.mouse_move_only_var.get():
                    # 使用跨平台点击函数
                    if click_mouse(x, y):
                        self.log_message(f"在位置 ({x}, {y}) 执行点击")
                    else:
                        pyautogui.click(x, y)
                        self.log_message(f"使用pyautogui在位置 ({x}, {y}) 执行点击")
                    self.click_count += 1
                    try:
                        self.log_message(f"已在位置 ({x}, {y}) 执行点击，总点击次数: {self.click_count}")
                    except Exception as e:
                        print(f"日志写入失败: {e}")
                    self.click_count_label.config(text=str(self.click_count))
                else:
                    try:
                        self.log_message(f"仅移动到位置 ({x}, {y})，未执行点击")
                    except Exception as e:
                        print(f"日志写入失败: {e}")
                
            except Exception as e:
                self.log_message(f"点击过程中发生错误: {e}")
                time.sleep(5)
                
    def start_clicking(self):
        try:
            interval = int(self.interval_var.get())
            if interval < 1 or interval > 3600:
                messagebox.showerror("错误", "点击间隔必须在1-3600秒之间")
                return
                
            self.is_running = True
            self.click_count = 0
            
            self.config['interval_seconds'] = interval
            self.config['click_mode'] = self.mode_var.get()
            self.config['prevent_sleep'] = self.prevent_sleep_var.get()
            self.config['mouse_follow_enabled'] = self.mouse_follow_var.get()
            self.config['mouse_move_speed'] = float(self.mouse_speed_var.get())
            self.config['mouse_move_only'] = self.mouse_move_only_var.get()
            self.save_config()
            
            self.log_message(f"启动配置: 模式={self.config['click_mode']}, 间隔={self.config['interval_seconds']}秒")
            if self.mouse_move_only_var.get():
                self.log_message(f"只移动不点击模式: 启用")
            
            self.click_thread = threading.Thread(target=self.click_loop, daemon=True)
            self.click_thread.start()
            
            # 更新状态指示器
            self.status_indicator.itemconfig(self.status_circle, fill='green')
            self.status_label.config(text="运行中", foreground='green')
            
            # 更新按钮状态
            self.start_btn.config(state=tk.DISABLED)
            self.stop_btn.config(state=tk.NORMAL)
            self.interval_entry.config(state=tk.DISABLED)
            
            self.log_message("自动点击已启动")
                
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字")
        except Exception as e:
            self.log_message(f"启动失败: {e}")
            messagebox.showerror("错误", f"启动失败: {e}")
            
    def stop_clicking(self):
        self.is_running = False
        
        if self.click_thread:
            self.click_thread.join(timeout=2)
            
        self.allow_system_sleep()
        
        # 更新状态指示器
        self.status_indicator.itemconfig(self.status_circle, fill='red')
        self.status_label.config(text="已停止", foreground='red')
        self.next_click_label.config(text="--")
        
        # 更新按钮状态
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.interval_entry.config(state=tk.NORMAL)
        
        self.log_message("自动点击已停止")
            
    def toggle_clicking(self):
        if self.is_running:
            self.stop_clicking()
        else:
            self.start_clicking()
            
    def test_click(self):
        try:
            x, y = self.get_click_position()
            
            result = messagebox.askyesno("测试点击", 
                                         f"将在位置 ({x}, {y}) 执行测试点击\n是否继续？")
            
            if result:
                self.log_message(f"测试点击: 位置 ({x}, {y})")
                messagebox.showinfo("测试成功", f"测试点击: 位置 ({x}, {y})")
                    
        except Exception as e:
            error_msg = f"测试点击失败: {e}"
            self.log_message(error_msg)
            messagebox.showerror("错误", error_msg)
    
    def clear_log(self):
        """清空日志"""
        try:
            self.log_text.config(state=tk.NORMAL)
            self.log_text.delete(1.0, tk.END)
            self.log_text.config(state=tk.DISABLED)
            self.log_message("日志已清空")
        except Exception as e:
            print(f"清空日志失败: {e}")
            
    def log_message(self, message):
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            log_entry = f"[{timestamp}] {message}\n"
            # 输出到控制台
            print(log_entry)
            # 输出到UI文本框
            self.log_text.config(state=tk.NORMAL)
            self.log_text.insert(tk.END, log_entry)
            self.log_text.see(tk.END)
            self.log_text.config(state=tk.DISABLED)
        except Exception as e:
            print(f"日志写入失败: {e}")
    
    def setup_tray_icon(self):
        """设置系统托盘图标和菜单（跨平台）"""
        try:
            # 创建原生托盘菜单（使用tkinter Menu）
            self.tray_menu = tk.Menu(self.root, tearoff=0, bg='#f0f0f0', fg='black')
            self.tray_menu.add_command(label="📱 显示窗口", command=self.show_from_tray)
            self.tray_menu.add_separator()
            self.tray_menu.add_command(label="❌ 退出程序", command=self.exit_from_tray)
            
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
        """窗口关闭处理 - 最小化到系统托盘"""
        # 隐藏窗口而不是关闭
        self.root.withdraw()
        self.log_message("程序已最小化到系统托盘")
    
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
    """设置DPI感知"""
    if sys.platform == 'win32':
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def main():
    if not IS_SINGLE_INSTANCE:
        activate_existing_window()
        show_single_instance_warning()
        return
    
    root = tk.Tk()
    setup_dpi_awareness()

    app = AutoClicker(root)

    root.mainloop()


if __name__ == "__main__":
    main()
