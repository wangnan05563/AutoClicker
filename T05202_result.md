# T05202 P0 安全与体验止血 —— 处理结论

## 根因
依据《产品调研与优化需求.md》5.1 与源码事实（F-1~F-11），本项目在"安全可控"维度存在硬伤：
- F-1 测试点击只弹确认框不真实点击，损害信任；
- F-2 无点击次数/运行时长上限，主打"1 小时间隔挂机"场景却无终点；
- F-3 仅一个 F6 切换键，无独立急停，误触即启停；
- F-10 窗口 geometry(650x700) 与 minsize(700x800) 矛盾；
- F-11 README 与实现不一致（间隔单位、配置文件名、日志目录、开机自启未实现）；
- F-9 关闭即退出，与"托盘常驻挂机"定位冲突。

## 影响范围
仅改动 `auto_clicker_py3.py`（核心逻辑与 UI）与 `README.md`（文档对齐）；不涉及打包 spec / 主题 / 架构拆分（属 P1/P2）。

## 修复（绝对路径与改动点）
文件：`D:/code/otherProjects/AutoClicker/auto_clicker_py3.py`
- CX-01 独立急停：`setup_hotkeys` 新增 F8 / Esc 紧急停止热键，统一调用新增 `emergency_stop()` → `stop_clicking(reason)`；新增可选"鼠标移动即停 (failsafe)"，在 `click_loop` 每秒比对光标位移 >20px 即急停并写明原因。
- CX-02 点击终点：新增 `click_limit` / `duration_limit`，在 `click_loop` 每次点击后判次数上限、每次循环判时长上限，先到先停并写日志原因。
- CX-03 修复测试点击：`test_click` 现真实 `move_mouse`+`click_mouse` 并执行一次点击，记录目标点与 `get_cursor_pos()` 实际落点。
- CX-04 启动倒计时：新增 `run_clicking()` 在 `click_loop` 前执行 0–5s 倒计时（状态区显示"N 秒后启动"），倒计时期间按停止键即取消、不产生任何点击；`start_clicking` 增加倒计时/上限参数校验。
- CX-05 文档一致性：`__init__` 与 `setup_ui` 统一窗口尺寸为 geometry 720x800 / minsize 700x760，消除矛盾；`README.md` 将间隔单位由"分钟"改为"秒(1-3600)"、配置文件名修正为 `~/.auto_clicker_config_py3.json`、日志说明改为"应用内实时显示（文件落盘 P1 规划）"、开机自启标注"规划中(P1)"；快捷键提示补充 F8/Esc 紧急停止。
- CX-06 关闭行为可选：新增 `close_to_tray` 配置（默认 True 保持原常驻行为）与 UI 勾选框 + `on_close_behavior_changed` 回调；`on_closing` 按配置选择最小化到托盘或直接退出。
- 配套：`stop_clicking(reason)` 增加原因参数并差异化日志；`__init__` 初始化 P0 状态默认值；新增线程安全 UI 更新辅助 `_ui/_set_status/_set_next`（用 `root.after(0,...)` 避免跨线程操作 Tk）。

## 验证（实测证据）
- 静态验证：`python -m py_compile auto_clicker_py3.py` 通过；AST 校验确认 `stop_clicking(reason)`、`emergency_stop`、`run_clicking`、`on_close_behavior_changed`、`_set_status/_set_next` 均存在，线程目标已切到 `run_clicking`，F8/Esc 热键已注册，测试点击改用 `click_mouse`，failsafe/次数/时长上限分支均落地，P0 配置键（startup_countdown/click_limit/duration_limit/failsafe_enabled/close_to_tray）在 default_config、读、写三处一致。
- ⚠ 因本环境无 tkinter（GUI 应用需在用户 Python 下运行），**未做 GUI 实测**，标记为未验证。建议人工抽查：
  1. 启停后按 F8/Esc 应在 200ms 内停止且日志写明"紧急停止键"；
  2. 勾选 failsafe 后运行中手动移动鼠标 >20px 应立即停止；
  3. 设次数上限 100，第 100 次后自动停止并写明原因；
  4. 设启动倒计时 3s，状态区显示 3→2→1→0，期间按停止不产生点击；
  5. 点"测试点击"确认光标移动且发生真实点击，日志含落点坐标；
  6. 取消"关闭时最小化到托盘"后点 X 应直接退出；100%/150% DPI 下无控件裁切。

## 本次回写
- Git 提交：`d0ce091ee3cb093efa4f5d3acd71f63557380297`（已通过 mtask_link_git_commit 关联，linked=1）。
- 改动文件：`auto_clicker_py3.py`、`README.md`（独立 commit，未裹挟其他文件）。

## 下一步建议（可选）
- P0 无新增派生动作；后续按既定计划续做 P1（T05203 功能扩展）与 P2（T05204 UI 重构 / T05205 主题系统），相关任务已存在无需新建。
