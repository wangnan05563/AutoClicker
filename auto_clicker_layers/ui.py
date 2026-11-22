# -*- coding: utf-8 -*-
"""UI 层（NFR-09）：可复用的 Tk 组件（取点遮罩、顶部错误横幅）。

主窗口的控件编排仍在入口文件作为组合根；这里只承载与业务无关的通用 UI 组件，
便于单独实例化与测试。
"""
import os
import threading
import time
import tkinter as tk

from auto_clicker_layers import picker
from auto_clicker_layers.platform_io import IS_WINDOWS

ACCENT = '#60A5FA'
ACCENT_STRONG = '#2563EB'
DANGER = '#F87171'
PANEL_BG = '#111827'
PANEL_FG = '#F9FAFB'
BASE_PROMPT = "拖拽框选 · 单击取点 · 方向键 1px/Shift 10px · Enter 确认 · Esc 取消"
PIXEL_PANEL = 120
PIXEL_BORDER = 6


def _monitor_rects(ox, oy, sw, sh):
    """返回所有显示器矩形；失败时退化为整个虚拟屏。"""
    fallback = [(int(ox), int(oy), int(ox) + int(sw), int(oy) + int(sh))]
    if not IS_WINDOWS:
        return fallback
    try:
        import win32api
        rects = []
        for _handle, _hdc, rect in win32api.EnumDisplayMonitors():
            rects.append(tuple(int(v) for v in rect))
        return rects or fallback
    except Exception:
        return fallback


class RegionSelector:
    """FR-27：全屏变暗遮罩 + 十字线 + 5×5 放大镜 + 框选/取点 + 键盘微调。"""

    def __init__(self, parent, on_done, warmup=False):
        self.parent = parent
        self.on_done = on_done
        self.start_abs = None
        self.start_raw = None
        self.selection = None
        self._finished = False
        self._rect_id = None
        self._marker_ids = []
        self._screen_image = None
        self._screen_size = None
        self._capture_done = False
        self._revealed = False
        self._reveal_after = None
        self._magnifier_photo = None

        self.top = tk.Toplevel(parent)
        self.top.overrideredirect(True)
        self.top.configure(bg='#000000')
        try:
            self.top.attributes('-topmost', True)
            self.top.attributes('-alpha', 0.40)
        except Exception:
            pass

        # 虚拟屏幕范围：负坐标显示器同样覆盖；Windows 再用 SetWindowPos 兜底。
        ox, oy, sw, sh = 0, 0, parent.winfo_screenwidth(), parent.winfo_screenheight()
        primary_w, primary_h = sw, sh
        if IS_WINDOWS:
            try:
                import ctypes
                u = ctypes.windll.user32
                ox = int(u.GetSystemMetrics(76))   # SM_XVIRTUALSCREEN
                oy = int(u.GetSystemMetrics(77))   # SM_YVIRTUALSCREEN
                sw = int(u.GetSystemMetrics(78))   # SM_CXVIRTUALSCREEN
                sh = int(u.GetSystemMetrics(79))   # SM_CYVIRTUALSCREEN
                primary_w = int(u.GetSystemMetrics(0)) or sw
                primary_h = int(u.GetSystemMetrics(1)) or sh
            except Exception:
                pass
        self.origin_x, self.origin_y = ox, oy
        self.width, self.height = sw, sh
        self.bounds = (ox, oy, ox + sw, oy + sh)
        self.monitor_rects = _monitor_rects(ox, oy, sw, sh)
        try:
            self.top.geometry("%dx%d%+d%+d" % (sw, sh, ox, oy))
        except Exception:
            self.top.geometry("%dx%d+0+0" % (sw, sh))

        self.canvas = tk.Canvas(self.top, bg='#000000', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.configure(cursor='crosshair')
        self.hline = self.canvas.create_line(0, 0, sw, 0, fill=ACCENT, width=1)
        self.vline = self.canvas.create_line(0, 0, 0, sh, fill=ACCENT, width=1)

        self.prompt = tk.Label(
            self.top, text=BASE_PROMPT, bg='#1F2937', fg=PANEL_FG,
            font=('微软雅黑', 10, 'bold'), padx=14, pady=7)
        # 顶部提示固定在主屏中心，避免多屏时跑到副屏边缘。
        self.prompt.place(
            x=max(20, -ox + primary_w // 2), y=max(8, -oy + 18), anchor='n')

        self.size_label = tk.Label(
            self.top, text='', bg=ACCENT_STRONG, fg='white',
            font=('Consolas', 10, 'bold'), padx=8, pady=4)
        self.size_label.place(x=max(8, -ox + 20), y=max(8, -oy + 20))

        # 放大镜放在主屏右上角，不覆盖中央取点区。
        mag_x = max(20, -ox + primary_w - 170)
        mag_y = max(8, -oy + 20)
        self.magnifier = tk.Canvas(
            self.top, width=PIXEL_PANEL + PIXEL_BORDER * 2,
            height=PIXEL_PANEL + PIXEL_BORDER * 2,
            bg=PANEL_BG, highlightthickness=1, highlightbackground=ACCENT)
        self.magnifier.place(x=mag_x, y=mag_y)
        self.mag_label = tk.Label(
            self.top, text='5×5  (--, --)', bg=PANEL_BG, fg=PANEL_FG,
            font=('Consolas', 9, 'bold'), padx=6, pady=3)
        self.mag_label.place(x=mag_x, y=mag_y + PIXEL_PANEL + PIXEL_BORDER * 2 + 2)

        bind_widgets = (self.top, self.canvas, self.magnifier, self.mag_label,
                        self.prompt, self.size_label)
        for widget in bind_widgets:
            widget.bind('<Motion>', self._on_motion)
            widget.bind('<ButtonPress-1>', self._on_press)
            widget.bind('<B1-Motion>', self._on_drag)
            widget.bind('<ButtonRelease-1>', self._on_release)
            widget.bind('<ButtonPress-3>', self._on_right)
        for widget in (self.top, self.canvas):
            widget.bind('<Escape>', self._on_cancel)
            widget.bind('<Return>', self._on_confirm)
            widget.bind('<KP_Enter>', self._on_confirm)
            for key in ('Left', 'Right', 'Up', 'Down'):
                widget.bind('<%s>' % key, self._on_nudge)
                widget.bind('<Shift-%s>' % key, self._on_nudge)

        # 先隐藏遮罩，后台抓屏完成后再显示，避免把遮罩自身抓进 5×5 放大图。
        self.top.withdraw()
        if warmup:
            # 启动期预热：建好完整控件树后立即销毁，避免首次取点时首次加载字体/控件类
            # 造成主线程卡顿；不启动抓屏线程，也不会显示遮罩。
            self._finished = True
            self.top.destroy()
            return
        self._capture_deadline = time.monotonic() + 0.30
        self._start_capture()
        self._reveal_after = self.top.after(20, self._check_reveal)

    def _start_capture(self):
        if os.environ.get('AUTOCLICKER_PICKER_NO_CAPTURE') == '1':
            self._capture_done = True
            return

        def worker():
            try:
                from PIL import ImageGrab
                image = ImageGrab.grab(
                    bbox=self.bounds,
                    all_screens=bool(IS_WINDOWS),
                )
                if image.size == (self.width, self.height):
                    self._screen_image = image.convert('RGB')
                    self._screen_size = image.size
            except Exception:
                self._screen_image = None
            finally:
                self._capture_done = True

        threading.Thread(target=worker, name='picker-capture', daemon=True).start()

    def _check_reveal(self):
        self._reveal_after = None
        if self._finished:
            return
        if self._capture_done or time.monotonic() >= self._capture_deadline:
            self._reveal()
        else:
            self._reveal_after = self.top.after(20, self._check_reveal)

    def _reveal(self):
        if self._finished or self._revealed:
            return
        self._revealed = True
        try:
            self.top.deiconify()
            self.top.update_idletasks()
        except Exception:
            pass
        if IS_WINDOWS:
            try:
                import ctypes
                hwnd = self.top.winfo_id()
                u = ctypes.windll.user32
                root_hwnd = u.GetAncestor(hwnd, 2) or hwnd
                u.SetWindowPos(
                    root_hwnd, -1, self.origin_x, self.origin_y,
                    self.width, self.height, 0x0040)  # HWND_TOPMOST, SWP_SHOWWINDOW
            except Exception:
                pass
        try:
            self.top.attributes('-topmost', True)
            self.top.lift()
        except Exception:
            pass
        try:
            # 遮罩已覆盖整个虚拟屏，局部 grab 足以把本应用鼠标事件留在遮罩上；
            # 不用 grab_set_global：跨进程全局抓取在本机实测会让首次显示阻塞 2.8s。
            self.top.grab_set()
        except Exception:
            pass
        try:
            self.top.focus_force()
            self.canvas.focus_set()
        except Exception:
            pass
        try:
            px, py = self.top.winfo_pointerxy()
            self._set_cursor(px, py)
        except Exception:
            self._set_cursor(
                self.origin_x + self.width // 2,
                self.origin_y + self.height // 2)

    def _abs_xy(self, event):
        return int(event.x_root), int(event.y_root)

    def _set_cursor(self, x, y):
        x, y = picker.snap_point(
            x, y, self.bounds, self.monitor_rects, picker.DEFAULT_SNAP_PX)
        self.cursor_abs = (x, y)
        self._move_crosshair(x, y)
        self._refresh_magnifier(x, y)

    def _move_crosshair(self, x, y):
        cx = max(0, min(self.width - 1, x - self.origin_x))
        cy = max(0, min(self.height - 1, y - self.origin_y))
        self.canvas.coords(self.hline, 0, cy, self.width, cy)
        self.canvas.coords(self.vline, cx, 0, cx, self.height)

    def _refresh_magnifier(self, x, y):
        try:
            self.mag_label.config(text="5×5  (%d, %d)" % (x, y))
        except Exception:
            pass
        try:
            self.magnifier.delete('all')
        except Exception:
            return
        box = picker.magnifier_box(x, y, self.bounds, 5)
        if getattr(self, '_screen_image', None) is not None:
            try:
                from PIL import Image, ImageTk
                ix1 = box[0] - self.origin_x
                iy1 = box[1] - self.origin_y
                ix2 = box[2] - self.origin_x
                iy2 = box[3] - self.origin_y
                crop = self._screen_image.crop((ix1, iy1, ix2, iy2))
                enlarged = crop.resize(
                    (PIXEL_PANEL, PIXEL_PANEL), Image.Resampling.NEAREST)
                self._magnifier_photo = ImageTk.PhotoImage(enlarged)
                self.magnifier.create_image(
                    PIXEL_BORDER, PIXEL_BORDER, anchor='nw',
                    image=self._magnifier_photo)
            except Exception:
                self._draw_magnifier_fallback()
        else:
            self._draw_magnifier_fallback()
        # 5×5 网格 + 中心十字，方便判断像素落点。
        for i in range(1, 5):
            pos = PIXEL_BORDER + i * (PIXEL_PANEL // 5)
            self.magnifier.create_line(pos, PIXEL_BORDER, pos,
                                       PIXEL_BORDER + PIXEL_PANEL,
                                       fill='#0B1220')
            self.magnifier.create_line(PIXEL_BORDER, pos,
                                       PIXEL_BORDER + PIXEL_PANEL, pos,
                                       fill='#0B1220')
        center = PIXEL_BORDER + PIXEL_PANEL // 2
        self.magnifier.create_line(center - 7, center, center + 7, center,
                                   fill=DANGER, width=2)
        self.magnifier.create_line(center, center - 7, center, center + 7,
                                   fill=DANGER, width=2)

    def _draw_magnifier_fallback(self):
        block = PIXEL_PANEL // 5
        for row in range(5):
            for col in range(5):
                x1 = PIXEL_BORDER + col * block
                y1 = PIXEL_BORDER + row * block
                fill = '#1F2937' if (row + col) % 2 else '#374151'
                if row == 2 and col == 2:
                    fill = ACCENT_STRONG
                self.magnifier.create_rectangle(
                    x1, y1, x1 + block, y1 + block, fill=fill, outline='')

    def _on_motion(self, event):
        if self._finished:
            return
        self._set_cursor(*self._abs_xy(event))

    def _on_press(self, event):
        if self._finished:
            return
        self.start_raw = self._abs_xy(event)
        self.start_abs = picker.snap_point(
            *self.start_raw, self.bounds, self.monitor_rects, picker.DEFAULT_SNAP_PX)
        self.selection = None
        self._clear_marker()
        self.prompt.config(text=BASE_PROMPT)
        sx = self.start_abs[0] - self.origin_x
        sy = self.start_abs[1] - self.origin_y
        self._rect_id = self.canvas.create_rectangle(
            sx, sy, sx, sy, outline=ACCENT, width=2,
            fill='#1E3A5F', stipple='gray25')
        self.size_label.config(text='拖拽中…')
        self._place_size_label(sx, sy)
        self._set_cursor(*self.start_abs)

    def _on_drag(self, event):
        if self._finished or not self.start_raw:
            return
        end_raw = self._abs_xy(event)
        self.selection = picker.rect_selection(
            self.start_raw[0], self.start_raw[1], end_raw[0], end_raw[1],
            self.bounds, self.monitor_rects,
            threshold=picker.DEFAULT_SNAP_PX, click_threshold=-1)
        self._draw_selection(self.selection)
        self.prompt.config(text="松手后可方向键微调 · Enter 确认 · Esc 取消")
        self._set_cursor(*end_raw)

    def _on_release(self, event):
        if self._finished or not self.start_raw:
            return
        end_raw = self._abs_xy(event)
        self.selection = picker.rect_selection(
            self.start_raw[0], self.start_raw[1], end_raw[0], end_raw[1],
            self.bounds, self.monitor_rects)
        self._draw_selection(self.selection)
        self.prompt.config(text="已选区域 · 方向键微调 · Enter 确认 · Esc 取消")
        self._set_cursor(*end_raw)

    def _on_right(self, event):
        if self._finished:
            return
        self.selection = None
        self.start_raw = None
        self.start_abs = None
        self._clear_marker()
        self.size_label.config(text='已撤销当前选框')
        self.prompt.config(text=BASE_PROMPT)
        self._refresh_magnifier(*getattr(self, 'cursor_abs', (0, 0)))

    def _on_nudge(self, event):
        if self._finished:
            return 'break'
        step = 10 if (getattr(event, 'state', 0) & 0x0001) else 1
        key = getattr(event, 'keysym', '')
        dx = -step if key == 'Left' else step if key == 'Right' else 0
        dy = -step if key == 'Up' else step if key == 'Down' else 0
        if not dx and not dy:
            return 'break'
        if self.selection is None:
            self.selection = picker.point_selection(
                *getattr(self, 'cursor_abs', (self.origin_x, self.origin_y)),
                bounds=self.bounds, monitor_rects=self.monitor_rects)
        self.selection = picker.nudge_selection(
            self.selection, dx, dy, self.bounds)
        if self.selection is None:
            return 'break'
        self._draw_selection(self.selection)
        x, y = self._selection_anchor(self.selection)
        self.cursor_abs = (x, y)
        self._move_crosshair(x, y)
        self._refresh_magnifier(x, y)
        self.prompt.config(text="方向键微调中 · Enter 确认 · Esc 取消")
        return 'break'

    def _selection_anchor(self, selection):
        x = int(selection.get('x', 0))
        y = int(selection.get('y', 0))
        if not selection.get('point'):
            x += max(0, int(selection.get('width', 1)) // 2)
            y += max(0, int(selection.get('height', 1)) // 2)
        return x, y

    def _clear_marker(self):
        for item in self._marker_ids:
            try:
                self.canvas.delete(item)
            except Exception:
                pass
        self._marker_ids = []
        if self._rect_id:
            try:
                self.canvas.delete(self._rect_id)
            except Exception:
                pass
            self._rect_id = None

    def _draw_selection(self, selection):
        if self._finished or selection is None:
            return
        self._clear_marker()
        x = int(selection.get('x', 0))
        y = int(selection.get('y', 0))
        w = max(1, int(selection.get('width', 1)))
        h = max(1, int(selection.get('height', 1)))
        cx = x - self.origin_x
        cy = y - self.origin_y
        if selection.get('point'):
            self._rect_id = self.canvas.create_rectangle(
                cx - 4, cy - 4, cx + 4, cy + 4,
                outline=DANGER, width=2, fill='')
            self._marker_ids = [
                self.canvas.create_line(cx - 9, cy, cx + 9, cy, fill=DANGER, width=1),
                self.canvas.create_line(cx, cy - 9, cx, cy + 9, fill=DANGER, width=1),
            ]
        else:
            self._rect_id = self.canvas.create_rectangle(
                cx, cy, cx + w, cy + h, outline=ACCENT, width=2,
                fill='#1E3A5F', stipple='gray25')
        self.size_label.config(
            text="%d×%d  (%d, %d)" % (w, h, x, y))
        self._place_size_label(cx + w, cy + h)

    def _place_size_label(self, px, py):
        x = min(max(8, px + 12), max(8, self.width - 220))
        y = min(max(8, py + 12), max(8, self.height - 40))
        self.size_label.place(x=x, y=y)

    def _on_confirm(self, event=None):
        if self._finished:
            return
        selection = self.selection
        if selection is None:
            selection = picker.point_selection(
                *getattr(self, 'cursor_abs', (self.origin_x, self.origin_y)),
                bounds=self.bounds, monitor_rects=self.monitor_rects)
        self._finish(dict(selection))

    def _on_cancel(self, event=None):
        if self._finished:
            return
        self._finish(None, cancelled=True)

    def _finish(self, selection, cancelled=False):
        if self._finished:
            return
        self._finished = True
        if self._reveal_after:
            try:
                self.top.after_cancel(self._reveal_after)
            except Exception:
                pass
            self._reveal_after = None
        try:
            self.top.grab_release()
        except Exception:
            pass
        try:
            self.top.destroy()
        except Exception:
            pass
        try:
            self.on_done(None if cancelled else selection)
        except Exception:
            pass


def prewarm_region_selector(parent):
    """启动期预热取点遮罩控件树；失败不影响主流程。"""
    try:
        RegionSelector(parent, lambda _selection: None, warmup=True)
        return True
    except Exception:
        return False


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
