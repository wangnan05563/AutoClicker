# 录制回放 MVP（FR-13）

面向“重复少量固定操作”的轻量宏：只记录点击、按键与延时，不记录鼠标连续轨迹，不注入其他进程。录制与回放入口都在「记录」页顶部「录制与回放（FR-13）」卡片。

## 使用流程

1. 在「记录」页填写宏名称（默认 `macro-YYYYMMDD-HHMMSS`），点「开始录制（3 秒）」。
2. 3 秒倒计时内切换到目标窗口；倒计时结束后状态条显示“录制中”，托盘图标变红。
3. 正常点击、按键；需要暂时离开时点「暂停」，回来点「继续」。暂停期间的事件不会进入宏。
4. 点「停止并保存」或按 `Esc` / `F8` 停止。宏自动保存到用户目录，并在卡片内显示步数、预计时长、路径和前 5 步预览。
5. 在「宏文件」下拉框选择宏，设置速度（0.5–2.0x）和循环次数（1–99），点「回放（3 秒）」。
6. 3 秒倒计时后开始回放；回放中可「暂停回放 / 继续回放」或「停止回放」。`Esc` / `F8` 随时急停，停止后自动释放仍按下的按键。

## 宏文件位置与格式

默认目录：`~/.auto_clicker_macros/`（Windows 下为 `%USERPROFILE%\.auto_clicker_macros\`）。

可用环境变量覆盖，便于测试或多套宏隔离：

```text
AUTOCLICKER_MACRO_DIR=D:\my-macros
```

应用启动时列出目录内所有 `.json`；坏文件也会显示为 `名称 [损坏]`，不会静默消失。宏名称会过滤 `\ / : * ? " < > |`，重名自动追加 `-2`、`-3`。

文件是可读 JSON，可直接手工编辑后点「刷新」重新载入：

```json
{
  "schema": "autoclicker.macro/1",
  "name": "十步示例",
  "created_at": "2026-11-23T16:00:00",
  "screen": {"left": 0, "top": 0, "width": 1920, "height": 1080},
  "steps": [
    {"type": "move", "x": 100, "y": 200},
    {"type": "click", "x": 100, "y": 200, "button": "left", "hold_ms": 0},
    {"type": "wait", "ms": 300},
    {"type": "key", "key": "ctrl", "action": "down"},
    {"type": "key", "key": "c", "action": "down"},
    {"type": "key", "key": "c", "action": "up"},
    {"type": "key", "key": "ctrl", "action": "up"},
    {"type": "move", "x": 500, "y": 300},
    {"type": "click", "x": 500, "y": 300, "button": "right", "hold_ms": 20},
    {"type": "wait", "ms": 1000}
  ]
}
```

字段约束：

| 字段 | 约束 |
| --- | --- |
| `schema` | 固定 `autoclicker.macro/1` |
| `name` | 非空，最多 80 字符；可省略，默认“未命名宏” |
| `screen` | 可选；`left/top/width/height` 必须完整且 `width/height > 0` |
| `steps` | 非空数组，最多 2000 步 |
| `move` | `x/y` 为整数；只表示点击时刻的离散坐标 |
| `click` | `x/y` 整数；`button` 为 `left/right/middle/double`；`hold_ms` 0–5000 |
| `key` | `key` 非空最多 32 字符；`action` 为 `press/down/up` |
| `wait` | `ms` 1–60000 |

录制器会在每次点击前自动插入一条 `move`，因此 1 次点击至少对应 `move + click` 两步；这是为了在回放时先明确落点。连续鼠标移动不会被采样成 `move`。

## 行为与安全边界

- 录制只在用户主动点击「开始录制」后挂接全局监听；停止、暂停或退出时卸载。
- Windows 鼠标用 20ms 轮询读取 `GetKeyState` 与光标位置，键盘用 `keyboard.hook`；Linux 鼠标用 Xlib 指针 mask，键盘同样用 `keyboard`。
- 点击 AutoClicker 自身窗口会被忽略，避免把界面操作录进宏。
- 录制上限 2000 步；达到上限自动停止并保存。
- 回放前有 3 秒倒计时，给用户切换到目标窗口的时间。
- 速度只缩放 `wait` 等待时长，不改变点击落点或按键顺序；0.5–2.0 之外拒绝启动。
- 回放逐条按原顺序执行：`move → click / key → wait`。循环时整段宏从头重复。
- 回放坐标同时校验录制屏幕与当前虚拟屏；越界、点击失败、键盘模块不可用、宏文件损坏都会在卡片内显示行内错误，并提供「诊断」入口。
- 回放异常或急停后恢复按钮状态，并释放所有由宏按下的键（`key down` 不会卡住）。
- 托盘图标在录制期间替换为红色圆点，结束后恢复主题图标；Linux pystray 同步标题。

## 异常与限制

- 当前 MVP 不绑定目标窗口：不校验“窗口不匹配”，只校验坐标是否在当前/录制屏幕内。需要窗口绑定的场景应在后续 FR 中扩展，而不是把本 MVP 当成窗口级宏。
- 录制器只记录点击发生时的坐标，默认 `hold_ms=0`；需要按住时长时可直接在 JSON 中改 `hold_ms`，回放会按该值按住。
- 鼠标按住时长在录制阶段不单独计时；双击在录制阶段按两次 `left` 点击记录，手工 JSON 可用 `button: double`。
- 纯 Wayland 会话下全局输入采集不可用；程序会按现有 FR-L01 的会话检测禁用启动入口。Linux 建议 X11。
- 录制期间不要同时启动自动点击；两者共用真实输入，应用会拒绝同时启动。
- 宏文件是普通 JSON，不执行脚本，也没有嵌入命令或代码字段。

## 验收与测试

纯逻辑测试：

```text
python -m unittest tests.test_macro tests.test_input_capture -v
Ran 22 tests ... OK
```

覆盖：schema/手工 JSON/坏文件/原子保存/文件名、录制 click→move+wait、暂停/恢复、停止/上限、回放 10 步原序/循环/倍速/停止/clamp、鼠标轮询单击、键盘重复去重与 Esc/F8 过滤、光标读取失败上报。

全量回归：

```text
Ran 209 tests in 40.712s
OK
```

含 FR-13 22 条、GUI 冒烟与既有 R1 用例；日志 `release/test-output-fr13-full.log`。

GUI/真实采集验证（隔离用户目录，脚本位于本轮工作区 `macro_ui_probe.py`，不随仓库提交）：

- 手工 JSON 与坏文件列表/预览；
- 速度、循环非法值行内提示；
- 录制倒计时取消与按钮状态；
- 注入录制缓冲后保存、列表选中、预览；
- 纯 `wait` 宏 2 循环 2x 完成回放；
- 长等待回放中 `Esc/F8` 急停；
- 坐标越界回放失败后 UI 恢复；
- 真实全局键盘 hook：`keybd_event` 注入 `a`，保存 key down/up；
- 真实鼠标轮询：固定平台层坐标后注入左键按下，保存 `move + click (400,300)`；
- 托盘红色图标资产生成。

本次实测虚拟屏为 3840×1080（双屏拼接）；`GetCursorPos` 在当前桌面会话被拒绝时，录制卡片会显示“鼠标位置读取失败”而不是静默空录。

截图：

- `release/ui-mode-shots/fr13-records-macro.png`：手改 10 步宏已选中，速度 1.5x、循环 2 次，预览前 5 步。
- `release/ui-mode-shots/fr13-records-macro-invalid.png`：坏 JSON 列表标 `[损坏]`，行内显示 `wait.ms 必须是整数`。

## 004 交付

- 安装包：`release/publish/AutoClicker-2.0.2-20261123-004-win64-Setup.exe`，16,123,745 B，SHA256 `0FA52650099AC5AC4A680361325E5CD8B7C1E1944C6F84DE09F04C2FF681ADC0`。
- dist：`release/dist/AutoClicker/AutoClicker.exe`，4,957,987 B，SHA256 `5F7C6CCE441CE3D167D52CC6036A511B91FEF3384BECDFCD63F64AEE9775D630`。
- 安装：`F:\Program Files\AutoClicker`；安装版 exe SHA256 与 dist 一致，`--version` 输出 `AutoClicker v2.0.2 (Build 20261123-004)`。
- 干净退出：dist 版 `release/verify-20261123-004-dist.log`，安装版 `release/verify-20261123-004-installed.log`；均 PASS，无 Warning 弹窗、无新增 `_MEI` 残留，安装版启动 5.87s。
- 构建日志：`release/build-20261123-004.log`；NSIS 日志：`release/nsis-20261123-004.log`。

## 代码落点

| 文件 | 作用 |
| --- | --- |
| `auto_clicker_layers/macro.py` | schema、录制缓冲、回放计划、文件读写、预览与时长 |
| `auto_clicker_layers/input_capture.py` | 录制期鼠标轮询、键盘 hook、自身窗口过滤 |
| `auto_clicker_py3.py` | 「记录」页宏卡片、倒计时、线程/热键/托盘编排、异常行内提示 |
| `tests/test_macro.py` | 18 条宏纯逻辑测试 |
| `tests/test_input_capture.py` | 4 条输入采集测试 |
