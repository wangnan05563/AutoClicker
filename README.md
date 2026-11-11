# AutoClicker

<p align="center">
  <img src="docs/social-preview.png" alt="AutoClicker" width="640" />
</p>

一个轻量的桌面自动点击工具，支持自定义点击间隔、点击区域、防锁屏与快捷键控制，支持 Windows 与 Linux（银河麒麟）。

## 功能特性

- 自定义点击间隔（秒 / 毫秒 两种单位，支持 0-100% 随机抖动）
- 三种点击模式：随机位置 / 中心点 / 自定义区域
- 鼠标按键选择（左 / 右 / 中 / 双击）与按住时长（毫秒）
- 多点位序列点击（屏幕坐标拾取 + 手动输入 + 列表管理）
- 防止系统自动锁屏
- 快捷键可自定义（启动/停止键、紧急停止键），Esc 始终为紧急停止
- 启动倒计时、点击次数上限、运行时长上限（安全可控）
- 鼠标移动即停（failsafe，可选）
- 多套配置方案：保存 / 切换 / 删除 / 导入导出 JSON
- 开机自动启动（Windows 注册表 / Linux autostart）
- 后台低资源运行（内存约 20-30MB）
- 实时状态显示与运行日志（应用内 + 磁盘 `~/.auto_clicker_logs/autoclicker.log`，RotatingFileHandler 5MB×5）

## 系统要求

- Windows 10/11 或 Linux（银河麒麟等）
- Python 3.7+

## 快速开始

```bash
# 安装依赖
pip install -r requirements_py3.txt

# 运行
python auto_clicker_py3.py
```

## 打包为可执行文件

```bash
python scripts/build_exe.py
```

产物输出至 `release/dist/AutoClicker.exe`（单文件，无需其他依赖）。

## 使用说明

1. 设置点击间隔（秒 或 毫秒，可选 0-100% 随机抖动；间隔单位通过「间隔单位」切换）
2. 选择点击模式：`random`（区域内随机）/ `center`（中心点）/ `custom`（自定义区域）；或使用「多点位序列」按列表循环点击
3. 选择鼠标按键与按住时长；点击「设置区域」，依次将鼠标移至区域左上角和右下角完成录制
4. 点击「启动」或按自定义启动键开始自动点击；运行中可按紧急停止键 / Esc 急停；托盘菜单会随运行状态显示「启动/停止」

配置保存在用户主目录下（`~/.auto_clicker_config_py3.json`）；运行日志实时显示在应用内，并落盘至 `~/.auto_clicker_logs/autoclicker.log`（可在「配置方案/系统」卡片点击「打开日志目录」）。

> 注意：Windows 设置开机自启动可能需要管理员权限；Linux 需在系统辅助功能设置中授权。

## 项目结构

```
├── auto_clicker_py3.py        # 主程序入口
├── icons/                     # 应用与托盘图标
├── scripts/                   # 打包与工具脚本
├── docs/                      # 文档与部署指南
└── release/                   # 打包构建产物输出目录
```

## 更多文档

- [银河麒麟部署指南](docs/银河麒麟部署指南.md)

## 许可证

[MIT](LICENSE)
