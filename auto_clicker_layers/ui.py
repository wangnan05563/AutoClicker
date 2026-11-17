# -*- coding: utf-8 -*-
"""UI 层（NFR-09）：可复用的 Tk 组件（全屏区域选择遮罩、顶部错误横幅）。

主窗口的控件编排仍在入口文件作为组合根；这里只承载与业务无关的通用 UI 组件，
便于单独实例化与测试。
"""
import tkinter as tk

from auto_clicker_layers.engine import normalize_region
from auto_clicker_layers.platform_io import IS_WINDOWS


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
