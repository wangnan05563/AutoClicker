# -*- coding: utf-8 -*-
"""GUI 冒烟测试入口：在隔离的用户目录下创建主窗口并立即退出。"""
import os
import sys
import tempfile

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
print("GUI_SMOKE_OK")
app.exit_application()
