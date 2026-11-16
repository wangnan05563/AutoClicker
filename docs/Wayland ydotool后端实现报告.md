# Wayland ydotool 后端实现报告（T05249 / PRD 6.12.1）

- 日期：2026-11-16
- 结论：**已把 ydotool 接入 Wayland 下的移动/点击后端，模拟 Wayland 命令链 8/8 通过；真机 Wayland/麒麟目视与 ydotoold 联调仍缺，T05249 标 `done`，不标 `verified`。**

## 1. 代码改动

文件：`D:\code\otherProjects\AutoClicker\auto_clicker_py3.py`

1. `detect_input_backend()`：Wayland 且检测到 `ydotool` 时返回 `(True, 'wayland', '')`，不再一律禁用；无 `ydotool` 仍返回明确拦截原因。检测 `YDOTOOL_SOCKET`/`/tmp/.ydotool_socket`/`/run/user/<uid>/.ydotool_socket`，缺失仅提示先启动 `ydotoold`，不阻断。
2. 新增 `_is_wayland_session()`：与探测判据一致，保守区分 XWayland/仅 DISPLAY。
3. 新增 `_ydotool_run()` / `_ydotool_move()` / `_ydotool_click()`：
   - 移动：`ydotool mousemove --absolute -x <x> -y <y>`，`--absolute` 失败时退回 `-a`；
   - 左/右/中：`click 0xC0/0xC1/0xC2`；
   - 双击：两次 `click`，间隔 30ms；
   - 长按：`mousedown` + sleep + `mouseup`；
   - 子进程失败/超时返回 False，打印 stderr 摘要，不把异常抛到 UI 线程。
4. `linux_move_mouse()` / `linux_click()`：明确 Wayland 且存在 `ydotool` 时优先 ydotool；否则保留 Xlib/pyautogui 路径。失败时明确日志，不再回退到会落空的 X11 点击。

## 2. 验证（模拟 Wayland）

探针：`C:\pyfix_tmp\ac_ydotool_probe.py`；结果：`C:\pyfix_tmp\ac_ydotool_report.json`

- 无 ydotool → 拦截；
- 有 ydotool → 允许 Wayland；
- 移动命令含 `mousemove --absolute -x 321 -y 456`；
- 左/右/中 click 分别为 `0xC0/0xC1/0xC2`；
- 长按出现 `mousedown` + `mouseup`；
- 双击两次 `click`；
- ydotool 返回 1 时 `linux_click` 返回 False（失败可传播）。
- **8/8 通过**。

## 3. 回归

- `py_compile auto_clicker_py3.py` 通过。
- `python -m unittest discover -s tests` → **65 tests OK，29.080s**。
- Windows 主路径未改动（`IS_LINUX` 分支不执行）。

## 4. 未验证/风险

- 真实 Wayland 下 `ydotoold` 权限、socket、`mousemove --absolute` 参数版本差异未联调；
- 全局热键 `keyboard` 在 Wayland 下仍可能被合成器限制；
- 麒麟 V10 SP1 x86_64/arm64 真机目视未做；
- 文档 `docs/Wayland降级说明.md` 已同步为“已接入 ydotool”，但真机结论仍待补。

## 本次回写

- 报告：`D:\code\otherProjects\AutoClicker\docs\Wayland ydotool后端实现报告.md`
- 文档更新：`docs/Wayland降级说明.md`
- 未验证项保留在本任务，不另建派生单。
