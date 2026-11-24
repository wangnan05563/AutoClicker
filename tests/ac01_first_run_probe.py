# -*- coding: utf-8 -*-
"""AC-01 首启 60 秒闭环探针：隔离用户目录，真实走 3 步向导并启动运行。

只使用默认「保持在线」模板（只移动不点击），避免测试期间产生真实点击。
输出 JSON 到 stdout，供 docs 证据引用。
"""
import json
import os
import shutil
import sys
import tempfile
import time

T0 = time.perf_counter()
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

TMP_HOME = tempfile.mkdtemp(prefix='autoclicker_ac01_')
os.environ['USERPROFILE'] = TMP_HOME
os.environ['HOME'] = TMP_HOME
os.environ['AUTOCLICKER_PICKER_NO_CAPTURE'] = '1'
os.environ['AUTOCLICKER_MACRO_DIR'] = os.path.join(TMP_HOME, 'macros')

import tkinter as tk  # noqa: E402

import auto_clicker_py3 as app_module  # noqa: E402


def pump(root, seconds=0.02):
    root.update()
    time.sleep(seconds)


def wait_until(root, predicate, timeout=10.0):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        pump(root)
        if predicate():
            return True
    return False


config_guess = os.path.expanduser('~/.auto_clicker_config_py3.json')
config_exists_before = os.path.exists(config_guess)
root = tk.Tk()
init_started = time.perf_counter()
app = app_module.AutoClicker(root)
init_s = time.perf_counter() - init_started
config_file = app.config_file
first_run_flag = bool(app.first_run)
result = {
    'ac01_pass': False,
    'first_run_flag': first_run_flag,
    'config_exists_before': config_exists_before,
    'app_init_s': round(init_s, 3),
    'tmp_home': TMP_HOME,
}
try:
    if not wait_until(root, lambda: getattr(app, '_wizard_window', None) is not None, 8.0):
        raise RuntimeError('首启向导未在 8s 内出现')
    result['wizard_appeared_s'] = round(time.perf_counter() - T0, 3)
    result['wizard_step'] = app._wizard_step
    result['wizard_template'] = app._wizard_template_var.get()

    assert app._wizard_step == 1
    app._wizard_next_btn.invoke()
    assert wait_until(root, lambda: app._wizard_step == 2, 2.0)
    app._wizard_next_btn.invoke()
    assert wait_until(root, lambda: app._wizard_step == 3, 2.0)
    assert app._wizard_next_btn.cget('text') == '完成并进入运行台'
    app._wizard_next_btn.invoke()
    assert wait_until(root, lambda: getattr(app, '_wizard_window', None) is None, 4.0)
    result['wizard_done_s'] = round(time.perf_counter() - T0, 3)
    result['onboarding_done'] = bool(app.config.get('onboarding_done'))
    result['onboarding_template'] = app.config.get('onboarding_template')
    result['after_wizard_page'] = app._active_page

    confirm = {'seen': False, 'accepted': False}

    def poll_confirm():
        if getattr(app, '_start_confirm_window', None) is not None:
            confirm['seen'] = True
            app._finish_start_confirmation(True)
            confirm['accepted'] = True
            return
        if not app.is_running:
            root.after(30, poll_confirm)

    assert app.start_btn.cget('state') == 'normal', app.start_btn.cget('state')
    root.after(30, poll_confirm)
    app.start_btn.invoke()
    result['start_clicked_s'] = round(time.perf_counter() - T0, 3)
    result['start_confirm'] = confirm
    result['start_confirm_required'] = bool(app.config.get('start_confirm_enabled', True))

    def running_tick_ready():
        text = ''
        try:
            text = app.sb_runtime_label.cget('text')
        except Exception:
            pass
        return app.is_running and text.startswith('运行时长:')

    if not wait_until(root, running_tick_ready, 7.0):
        raise RuntimeError('倒计时后未进入运行态: %s' % app.sb_status_label.cget('text'))
    result['running_s'] = round(time.perf_counter() - T0, 3)
    result['status'] = app.sb_status_label.cget('text')
    result['is_running'] = bool(app.is_running)
    log_text = app.log_text.get('1.0', tk.END)
    result['log_has_start'] = '自动点击已启动' in log_text
    result['log_has_move_only'] = '只移动不点击模式: 启用' in log_text
    result['wizard_to_running_s'] = round(
        result['running_s'] - result['wizard_appeared_s'], 3)
    result['ac01_limit_s'] = 60
    result['ac01_pass'] = bool(result['running_s'] < 60.0)
finally:
    try:
        if app.is_running:
            app.stop_clicking(reason='AC-01 探针结束')
    except Exception:
        pass
    try:
        root.update()
        root.destroy()
    except Exception:
        pass
    result['config_exists_after'] = os.path.exists(config_file)
    result['config_cleanup'] = True
    shutil.rmtree(TMP_HOME, ignore_errors=True)

print(json.dumps(result, ensure_ascii=False, indent=2))
