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

# FR-01：三步向导可走通，完成挂机签到模板后参数真实落地
app.show_onboarding_wizard(force=True)
root.update_idletasks()
assert app._wizard_window is not None
assert app._wizard_step == 1
app._wizard_next(); root.update_idletasks()
assert app._wizard_step == 2
app._wizard_click_area = {'x': 123, 'y': 456, 'width': 1, 'height': 1}
app._wizard_refresh_preview()
app._wizard_next(); root.update_idletasks()
assert app._wizard_step == 3
app._wizard_hotkey_start_var.set('F6')
app._wizard_hotkey_emergency_var.set('ESC')
app._finish_onboarding('checkin')
root.update_idletasks()
assert app.config['onboarding_template'] == 'checkin'
assert app.config['onboarding_done'] is True
assert app.config['click_limit'] == 1
assert app.config['click_area'] == {'x': 123, 'y': 456, 'width': 1, 'height': 1}
assert app.config['hotkey_emergency'] == 'esc'
assert app._wizard_window is None
print("GUI_WIZARD_OK")

# FR-01：设置页重开向导后“跳过”只更新推荐安全方案，不覆盖当前参数
app.config['interval_seconds'] = 321
app.show_onboarding_wizard(force=True)
root.update_idletasks()
app._onboarding_skip()
root.update_idletasks()
assert app.config['interval_seconds'] == 321
assert app.config['click_limit'] == 1
assert app.config['onboarding_done'] is True
print("GUI_WIZARD_SKIP_KEEPS_CONFIG_OK")

# FR-02：启动确认框可取消/继续，勾选“不再提示”会关闭后续确认
app.config['start_confirm_enabled'] = True
app.confirm_start_var.set(True)

def _accept_start_confirm():
    assert app._start_confirm_window is not None
    app._start_confirm_remember_var.set(True)
    app._finish_start_confirmation(True)

root.after(80, _accept_start_confirm)
assert app.show_start_confirmation(['间隔：10 秒', '目标：点 (1, 2)'])
assert app.config['start_confirm_enabled'] is False
assert app._start_confirm_window is None
assert app.confirm_start_var.get() is False
print("GUI_START_CONFIRM_OK")

# FR-02：取消不启动，且不因取消而关闭后续确认
app.config['start_confirm_enabled'] = True
app.confirm_start_var.set(True)

def _cancel_start_confirm():
    app._finish_start_confirmation(False)

root.after(80, _cancel_start_confirm)
assert app.show_start_confirmation(['间隔：10 秒']) is False
assert app.config['start_confirm_enabled'] is True
print("GUI_START_CONFIRM_CANCEL_OK")

# FR-02：结束摘要能打开，包含点击/成功/失败/异常并支持关闭
app.last_run_stats = {
    'timestamp': '2026-11-22T19:10:00', 'click_count': 3, 'success_count': 2,
    'fail_count': 1, 'exception_count': 1, 'runtime_seconds': 65.4,
    'interval_seconds': 10, 'mode': 'center', 'button': 'left',
    'stop_reason': '达到点击次数上限 (3 次)',
}
app.show_end_summary(app.last_run_stats)
root.update_idletasks()
assert app._end_summary_window is not None
app._close_end_summary()
assert app._end_summary_window is None
print("GUI_END_SUMMARY_OK")

app.exit_application()
