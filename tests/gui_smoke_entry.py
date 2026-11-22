# -*- coding: utf-8 -*-
"""GUI 冒烟测试入口：在隔离的用户目录下创建主窗口并立即退出。"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 隔离配置与日志，避免污染真实用户目录
_TMP_HOME = tempfile.mkdtemp(prefix='autoclicker_smoke_')
os.environ['USERPROFILE'] = _TMP_HOME
os.environ['HOME'] = _TMP_HOME

# 预置空配置，避免首次运行引导弹窗阻塞冒烟流程（AutoClicker 会自动补齐默认值）
with open(os.path.join(_TMP_HOME, '.auto_clicker_config_py3.json'), 'w', encoding='utf-8') as _f:
    _f.write('{}')

import tkinter as tk  # noqa: E402

import auto_clicker_py3 as app_module  # noqa: E402

root = tk.Tk()
root.withdraw()
app = app_module.AutoClicker(root)
root.update_idletasks()
root.update()
assert root.title() == app_module.WINDOW_TITLE, root.title()
assert app.start_btn is not None
assert app.test_btn is not None
for page in ('run', 'rules', 'records', 'settings'):
    assert page in app._page_frames, page
    t0 = time.perf_counter()
    app._show_page(page)
    root.update_idletasks()
    elapsed = time.perf_counter() - t0
    assert app._active_page == page, page
    assert elapsed < 0.1, 'page switch too slow: %s %.3fs' % (page, elapsed)
print("GUI_SMOKE_OK")

# FR-25：Simple 隐藏高级卡片/记录页入口，Advanced 恢复且不重置参数
assert app.config.get('ui_mode') == 'simple', app.config.get('ui_mode')
assert app.p1_card.winfo_manager() == ''
assert app.nav_buttons['records'].winfo_manager() == ''
assert app.failsafe_check.winfo_manager() == ''
assert app.close_tray_check.winfo_manager() == ''
app.config['interval_seconds'] = 7
app.ui_mode_var.set('advanced')
app.on_ui_mode_change()
root.update_idletasks()
assert app.p1_card.winfo_manager() == 'pack'
assert app.p1b_card.winfo_manager() == 'pack'
assert app.nav_buttons['records'].winfo_manager() == 'pack'
assert app.failsafe_check.winfo_manager() == 'pack'
assert app.close_tray_check.winfo_manager() == 'pack'
assert app.config['interval_seconds'] == 7
app.ui_mode_var.set('simple')
app.on_ui_mode_change()
root.update_idletasks()
assert app.p1_card.winfo_manager() == ''
assert app.nav_buttons['records'].winfo_manager() == ''
assert app.failsafe_check.winfo_manager() == ''
assert app.close_tray_check.winfo_manager() == ''
assert app.config['interval_seconds'] == 7
print("GUI_MODE_OK")

app.exit_application()
