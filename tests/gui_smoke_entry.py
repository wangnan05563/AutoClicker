# -*- coding: utf-8 -*-
"""GUI 冒烟测试入口：在隔离的用户目录下创建主窗口并立即退出。"""
import os
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 隔离配置与日志，避免污染真实用户目录
_TMP_HOME = tempfile.mkdtemp(prefix='autoclicker_smoke_')
os.environ['USERPROFILE'] = _TMP_HOME
os.environ['HOME'] = _TMP_HOME
os.environ['AUTOCLICKER_PICKER_NO_CAPTURE'] = '1'

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

# FR-26：状态环、今日统计、会话保持与倒计时小数秒可刷新
app._show_page('run')
app.daily_stats = app_module._dashboard.empty_daily_stats()
app.daily_stats.update({
    'click_count': 20, 'success_count': 17, 'fail_count': 3,
    'run_count': 2, 'runtime_seconds': 32.0,
})
app.last_run_stats = {
    'timestamp': '2026-11-23T09:00:00', 'click_count': 4,
    'success_count': 3, 'fail_count': 1, 'exception_count': 0,
    'runtime_seconds': 10.0, 'interval_seconds': 10, 'mode': 'center',
    'button': 'left', 'stop_reason': '手动停止',
}
app.refresh_run_dashboard()
assert app.today_clicks_var.get() == '20'
assert app.today_rate_var.get() == '85.0%'
assert app.today_runs_var.get() == '2'
assert '点击 4 次' in app.run_last_label.cget('text')
assert app.run_session_check.cget('text') in ('开', '关')
assert app.run_ring_canvas.find_all()
app.is_running = True
app.start_time = time.time() - 5
app.click_count = 3
app.success_count = 2
app.fail_count = 1
app._set_run_countdown(2.5, 3.0)
assert '2.5' in app.run_state_detail_var.get()
assert '2.5s' in app._ring_subtext
app.is_running = False
app._set_run_ring('stopped', '已停止', '等待开始', progress=0.0, detail='等待开始')
# 异常态：顶栏/标题/状态环统一，原因只出现一次，诊断入口可点
app.is_running = True
app._mark_run_abnormal('连续 3 次点击失败，请检查输入后端或权限')
assert app.status_text_label.cget('text') == '异常', app.status_text_label.cget('text')
assert app._ring_state == 'abnormal'
assert '点击线程仍在继续' in app.run_state_detail_var.get()
assert '连续 3 次点击失败' in app.run_error_var.get()
assert '连续 3 次点击失败' not in app.run_state_detail_var.get()
assert app.run_diag_btn.winfo_manager() == 'pack'
app.is_running = False
app._do_set_status('已停止', app._color('muted'))
app.refresh_run_dashboard()
print("GUI_DASHBOARD_OK")

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

# FR-03：诊断卡片可刷新，详情窗口可开，一键生成脱敏诊断包
app._show_page('settings')
root.update_idletasks()
report = app.refresh_diagnostics()
assert report is not None
assert report['schema'] == 'autoclicker.diagnostics/1'
assert '总体状态' in app.diag_status_var.get()
app.show_diagnostics_window()
root.update_idletasks()
assert app._diagnostics_window is not None
app._close_diagnostics_window()
assert app._diagnostics_window is None
diag_path = app.create_diagnostic_package()
assert os.path.isfile(diag_path), diag_path
with zipfile.ZipFile(diag_path) as zf:
    names = set(zf.namelist())
    assert 'diagnostics.json' in names
    assert 'summary.txt' in names
    assert 'config.json' in names
print("GUI_DIAGNOSTICS_OK")

# FR-27：遮罩框选/单击/方向键微调/Enter 确认，3 秒内完成；Esc 返回 None
from auto_clicker_layers.ui import RegionSelector  # noqa: E402

class _PickerEvent:
    def __init__(self, x, y, state=0, keysym=''):
        self.x_root = x
        self.y_root = y
        self.x = x
        self.y = y
        self.state = state
        self.keysym = keysym

def _wait_picker_reveal(selector, timeout=1.0):
    end = time.time() + timeout
    while time.time() < end and not selector._revealed:
        root.update()
        time.sleep(0.005)
    assert selector._revealed, 'picker overlay not revealed'
    root.update_idletasks()

picker_results = []
picker_t0 = time.perf_counter()
picker = RegionSelector(root, picker_results.append)
construct_elapsed = time.perf_counter() - picker_t0
reveal_t0 = time.perf_counter()
picker._check_reveal()
update_elapsed = time.perf_counter() - reveal_t0
print('PICKER_CONSTRUCT_MS', round(construct_elapsed * 1000, 1), 'REVEAL_MS', round(update_elapsed * 1000, 1))
assert construct_elapsed < 0.1, 'picker construction blocked main thread: %.1fms' % (construct_elapsed * 1000)
assert update_elapsed < 0.1, 'picker reveal blocked main thread: %.1fms' % (update_elapsed * 1000)
root.update()
picker._on_motion(_PickerEvent(500, 300))
picker._on_press(_PickerEvent(500, 300))
picker._on_drag(_PickerEvent(900, 600))
picker._on_release(_PickerEvent(900, 600))
assert picker.selection == {'x': 500, 'y': 300, 'width': 400, 'height': 300, 'point': False}
assert '400×300' in picker.size_label.cget('text')
picker._on_nudge(_PickerEvent(0, 0, state=0, keysym='Left'))
assert picker.selection['x'] == 499
picker._on_nudge(_PickerEvent(0, 0, state=1, keysym='Up'))
assert picker.selection['y'] == 290
assert picker.selection['width'] == 400 and picker.selection['height'] == 300
assert time.perf_counter() - picker_t0 < 3.0, 'picker selection exceeded 3s'
picker._on_confirm()
root.update()
assert picker_results[-1] == {'x': 499, 'y': 290, 'width': 400, 'height': 300, 'point': False}
assert picker._finished

picker2_results = []
picker2 = RegionSelector(root, picker2_results.append)
_wait_picker_reveal(picker2, timeout=0.1)
picker2._on_motion(_PickerEvent(800, 500))
picker2._on_press(_PickerEvent(800, 500))
picker2._on_release(_PickerEvent(800, 500))
assert picker2.selection['point'] is True
assert picker2.selection['width'] == 1 and picker2.selection['height'] == 1
picker2._on_nudge(_PickerEvent(0, 0, state=0, keysym='Left'))
assert picker2.selection['x'] == 799
picker2._on_right(_PickerEvent(800, 500))
assert picker2.selection is None
picker2._on_cancel()
root.update()
assert picker2_results[-1] is None
assert picker2._finished

# 应用级路径：取区域按钮异步打开遮罩，单击取点后 Enter 回填并持久化
app._show_page('run')
root.update()
app.set_click_area()
for _ in range(200):
    root.update()
    if app._region_selector is not None:
        break
    time.sleep(0.005)
assert app._region_selector is not None, 'application region selector not opened'
app_selector = app._region_selector
_wait_picker_reveal(app_selector, timeout=0.1)
app_selector._on_motion(_PickerEvent(640, 360))
app_selector._on_press(_PickerEvent(640, 360))
app_selector._on_release(_PickerEvent(640, 360))
app_selector._on_confirm()
root.update()
assert app._region_selector is None
assert app.config['click_area'] == {'x': 640, 'y': 360, 'width': 1, 'height': 1}
assert '1x1 (640,360)' in app.area_label.cget('text')
print("GUI_PICKER_APP_OK")

# 应用级取消：Esc 后原区域保持不变
old_area = dict(app.config['click_area'])
app.set_click_area()
for _ in range(200):
    root.update()
    if app._region_selector is not None:
        break
    time.sleep(0.005)
assert app._region_selector is not None
_wait_picker_reveal(app._region_selector, timeout=0.1)
app._region_selector._on_cancel()
root.update()
assert app._region_selector is None
assert app.config['click_area'] == old_area
print("GUI_PICKER_APP_CANCEL_OK")

print("GUI_PICKER_OK")

app.exit_application()
