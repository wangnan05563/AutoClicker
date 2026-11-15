# Wayland 降级说明（FR-L01 关联文档）

> 适用版本：AutoClicker v2.0（`auto_clicker_py3.py`）
> 关联需求：PRD `FR-L01`「Wayland 适配与明确降级」、`NFR-07`「兼容矩阵」

## 1. 现状

AutoClicker 的模拟输入在 Linux 上目前依赖 **pyautogui → X11（Xlib / `xdotool`）** 链路：

- 鼠标移动 / 点击：`pyautogui` 在 X11 会话下工作正常；
- 全局热键：`keyboard` 库依赖 `uinput`，同样要求 X11 或有相应输入权限；
- 托盘：`pystray` + `Pillow`（X11 可用；无 X11 时降级为无托盘）。

在 **Wayland** 会话下，X11 的模拟输入接口默认被合成器屏蔽，pyautogui 会抛异常或点击落空，全局热键也可能失效。

## 2. 已实现的「明确降级」

当前代码遵循 PRD「**不静默失败**」原则，启动时由 `detect_input_backend()` 完成会话探测：

| 环节 | 行为 |
| --- | --- |
| 会话判定 | 读取 `XDG_SESSION_TYPE` / `WAYLAND_DISPLAY` / `DISPLAY`；仅当明确为 Wayland 且无 X11 可用时拦截。**XWayland 与「未设 XDG 但有 DISPLAY」不会被误判**，避免误伤国产桌面 |
| 顶部横幅 | 显示「注意：Wayland 会话不支持模拟输入，启动已禁用」，可点「×」关闭；「详情」按钮给出完整诊断与修复指引 |
| 启动禁用 | 禁用「启动」按钮；`start_clicking()` **首句守卫**同时拦住 F6 热键通道（`toggle_clicking` 也经过此处），`test_click()` 同样拦截；`stop_clicking()` 不会把按钮误恢复为可用 |
| 分级提示 | 未装 `ydotool` → 提示切换 X11 或安装 `ydotool` + 启动 `ydotoold` + 加入 `input` 组；已装 `ydotool` → 明确告知本版本**尚未接入 ydotool 后端**，仍需切换 X11 |
| 运行期兜底 | 点击过程中的异常由 `click_loop` 捕获并写入日志（带 `失败` 计数），不静默卡死；开机自启 / 托盘不可用时给出提示而非静默跳过 |

判定矩阵（已用模拟环境变量实测 7 个分支全部通过）：

| 环境变量 | 判定 | 结果 |
| --- | --- | --- |
| Windows / macOS | 原生 | 可用 |
| `XDG_SESSION_TYPE=x11` | x11 | 可用 |
| `XDG_SESSION_TYPE=x11` + `WAYLAND_DISPLAY` | XWayland | 可用（不误伤） |
| 仅 `DISPLAY=:0` | x11 | 可用 |
| `XDG_SESSION_TYPE=wayland` | wayland | 拦截 |
| 仅 `WAYLAND_DISPLAY`（无 `DISPLAY`） | wayland | 拦截 |

## 3. 用户侧推荐做法（降级路径）

| 场景 | 推荐操作 |
| --- | --- |
| 银河麒麟 / 其他 Linux 桌面 | **优先使用 X11 会话登录**（在登录界面选择「X11 / 经典」会话），可获完整点击、热键、托盘能力 |
| 只能用 Wayland | 程序会自动禁用启动并给出指引；**最可靠的做法是注销后切换 X11 会话**。安装 `ydotool` 仅是为后续版本集成预留，当前版本即使检测到也不会自动启用 |
| 临时规避 | 在 X11 会话下运行本程序，避免 Wayland 下的模拟输入限制 |

### 安装 ydotool（Wayland 兼容输入，未来集成路径）

```bash
# Debian/Ubuntu/Kylin 系
sudo apt install ydotool
# 启动守护进程（需 input 组权限）
sudo systemctl enable --now ydotoold
sudo usermod -aG input $USER
# 重新登录使组生效
```

> 当前程序**未**自动调用 `ydotool`。上述步骤为后续 FR-L01「Wayland 优先 ydotool」集成预留的手动替代方案。

## 4. 待办（真机联调项，本环境无法验证）

- [x] 启动时读取 `XDG_SESSION_TYPE`，Wayland 且无可用输入后端时：禁用「启动」按钮 + 顶部横幅 + 首句守卫拦截热键 / 测试点击（PRD 操作级提示）——**已实现，逻辑分支已实测，待真机 Wayland 目视确认横幅与按钮态**。
- [ ] 集成 `ydotool` 作为 Wayland 下的点击 / 移动后端，替换 pyautogui 在 Wayland 分支的调用（需要 `ydotoold` + `input` 组真机环境联调）。
- [ ] 真机矩阵验证：Kylin V10 SP1 X11（x86_64 / arm64）、Kylin V10 SP1 Wayland（降级路径）（NFR-07）。
- [ ] GUI 实测：本 Agent 环境无图形显示、无法运行 tkinter 主循环，横幅渲染、按钮禁用态与详情弹窗尚未做目视验证。

> 剩余项需要真实 Wayland/arm64 设备与 GUI 环境，已按「收尾 + 少量补做」决策保留为 `todo`（对应 mtask `T05249`），不在本阶段自动执行。

## 5. 兼容性小结

| 平台 | 会话 | 点击 | 热键 | 托盘 | 状态 |
| --- | --- | --- | --- | --- | --- |
| Windows 10/11 | — | ✅ | ✅ | ✅ | 完整 |
| Kylin V10 SP1 | X11 | ✅ | ✅ | ✅ | 完整 |
| Kylin V10 SP1 | Wayland | 启动已禁用 | 停止通道保留 | 视合成器 | 自动检测 + 横幅提示 + 启动禁用（不静默失败） |

## 6. 不做项（与 PRD §2.3 对齐）

本降级文档仅描述 Wayland 输入限制与切换 X11 的路径，不承诺在 Wayland 下提供等效输入能力，并明确沿用 PRD §2.3「非目标（明确不做）」边界：

1. 不做反检测/绕过反作弊，不提供「防封号」能力承诺。
2. 不做进程注入、内存修改、驱动级隐藏。
3. 不做无提示的后台静默点击（本程序默认托盘可见、状态可查；Wayland 下启动禁用并显示横幅）。
4. 不做全功能脚本引擎（录制回放仅「点击 + 按键 + 延时」最小集）。

> 若后续接入 `ydotool`，仍须遵守上述边界；当前版本未接入，检测到 `ydotool` 也会明确提示仍需切换 X11。
