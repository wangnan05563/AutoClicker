# arm64 冒烟测试方案（T05276 / PRD 1.3）

- 日期：2026-11-16
- 状态：**方案已制定；无麒麟 arm64 真机/借测环境，未执行交叉编译与冒烟。T05276 标 `done`，不标 `verified`。**
- 适用：银河麒麟 V10 SP1 arm64（Python 3.x + PyInstaller）

## 1. 原则

- **优先原生构建**：在 arm64 真机/容器内 `pip install -r requirements_linux.txt` + PyInstaller，避免 x86 交叉编译导致 Python ABI、tkinter、PyInstaller bootloader 不匹配。
- **交叉编译仅作备选**：用同版本 arm64 基础镜像（Docker/QEMU binfmt）构建；产物必须在真机复验，不把 QEMU 结果当作性能/输入验证结论。
- **不修改生产配置**：测试使用隔离 `HOME`/`USERPROFILE`、独立互斥名与窗口标题。

## 2. 借用环境冒烟流程

1. 准备麒麟 V10 SP1 arm64 真机或借测机，确认 `uname -m` 为 `aarch64`、Python ≥3.10、tkinter 可用。
2. 上传源码与 `requirements_linux.txt`，创建 venv，安装依赖（pystray/Pillow/python-xlib/pyinstaller）。
3. 原生构建：
   - `pyinstaller --noconfirm --clean --onedir --name AutoClickerArm64 auto_clicker_py3.py`
   - 记录产物目录、启动脚本、体积。
4. 无显示环境用 `xvfb-run` 冒烟；有桌面则直接双击/命令行启动。
5. 执行冒烟用例：
   - 启动后主窗口出现，标题与版本正确；
   - 开始/停止按钮可用，F6/F8/Esc 热键注册；
   - 区域选择遮罩出现、Esc 取消、Enter 确认；
   - 测试点击落点高亮；
   - 托盘图标出现/菜单可用；
   - 关闭到托盘、退出无残留进程；
   - 日志文件写入、配置读写正常；
   - 10 分钟 UI 心跳无 Tcl 异常。
6. 记录 `uname -a`、Python/PyInstaller 版本、依赖版本、启动耗时、体积、失败截图/日志。

## 3. 交叉编译备选（QEMU）

```bash
# 在 x86_64 主机（需 binfmt_misc）
docker run --rm --platform linux/arm64 -v /path/AutoClicker:/work -w /work \
  kylin/arm64-base:V10SP1 \
  bash -lc "python3 -m venv .venv-arm64 && .venv-arm64/bin/pip install -r requirements_linux.txt && .venv-arm64/bin/pyinstaller --noconfirm --clean --onedir auto_clicker_py3.py"
```

- 限制：QEMU 下启动/点击性能不可信；只验证「能否构建、能否导入、窗口能否创建」。
- 最终验收必须在真机执行第 2 节用例。

## 4. 验收标准

- 产物可启动且主窗口可见；
- 上述 8 项冒烟用例全部通过；
- 无崩溃/Tcl 异常，退出后无残留进程；
- 记录体积与启动耗时；不把 QEMU 数据作为性能结论。

## 5. 风险

| 风险 | 处置 |
|---|---|
| 无 arm64 真机 | 借用环境/云 arm64；在风险登记挂起 |
| tkinter 缺失 | 安装 `python3-tk`；构建前 `import tkinter` 预检 |
| pystray/xdotool 缺失 | 按 `requirements_linux.txt` 安装；无托盘时记录降级 |
| PyInstaller bootloader 不匹配 | 必须 arm64 原生构建，不用 x86 产物 |
| Wayland 输入受限 | 按 FR-L01 提示切 X11 或装 ydotool |

## 本次回写

- 报告：`D:\code\otherProjects\AutoClicker\docs\arm64冒烟测试方案.md`
- 未执行：无 arm64 环境；T05276 `done`，`verified=false`。
- 借用环境到位后按本方案执行，结果回写本任务，不另建派生单。
