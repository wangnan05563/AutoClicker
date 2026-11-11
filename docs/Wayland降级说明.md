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

当前代码遵循 PRD「**不静默失败**」原则：

- 点击过程中的异常会被 `click_loop` 捕获并写入运行日志（带 `失败` 计数），不会让主流程静默卡死；
- 测试点击失败时弹出原因与修复指引（FR-C04）；
- 开机自启 / 托盘等平台能力在不可用时给出提示而非静默跳过（FR-G03、FR-A05）。

> 说明：PRD 要求的「启动前自动检测 `XDG_SESSION_TYPE` 并在 Wayland 不可用时禁用启动按钮 + 横幅提示」目前**尚未在代码中落地**，属于需要真机 Wayland 环境联调的待办项（见第 4 节）。

## 3. 用户侧推荐做法（降级路径）

| 场景 | 推荐操作 |
| --- | --- |
| 银河麒麟 / 其他 Linux 桌面 | **优先使用 X11 会话登录**（在登录界面选择「X11 / 经典」会话），可获完整点击、热键、托盘能力 |
| 只能用 Wayland | 安装并配置 `ydotool` + `ydotoold`，将当前用户加入 `input` 组；或在测试点击报错后按指引切换 X11 |
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

- [ ] 启动时读取 `XDG_SESSION_TYPE`，Wayland 且 `ydotool` 不可用时：禁用「启动」按钮 + 顶部横幅「Wayland 会话不支持模拟输入，启动已禁用」（PRD 操作级提示）。
- [ ] 集成 `ydotool` 作为 Wayland 下的点击 / 移动后端，替换 pyautogui 在 Wayland 分支的调用。
- [ ] 真机矩阵验证：Kylin V10 SP1 X11（x86_64 / arm64）、Kylin V10 SP1 Wayland（降级路径）（NFR-07）。

> 这些项需要真实 Wayland/arm64 设备与长时 soak 验证，已按「收尾 + 少量补做」决策保留为 `todo`，不在本阶段自动执行。

## 5. 兼容性小结

| 平台 | 会话 | 点击 | 热键 | 托盘 | 状态 |
| --- | --- | --- | --- | --- | --- |
| Windows 10/11 | — | ✅ | ✅ | ✅ | 完整 |
| Kylin V10 SP1 | X11 | ✅ | ✅ | ✅ | 完整 |
| Kylin V10 SP1 | Wayland | ⚠️ 需 ydotool（手动） | ⚠️ | ⚠️ | 降级 + 指引 |
