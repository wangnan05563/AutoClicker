# AutoClicker

<p align="center">
  <img src="docs/social-preview.png" alt="AutoClicker" width="640" />
</p>

一个轻量的桌面自动点击工具，支持自定义点击间隔、点击区域、防锁屏与快捷键控制，支持 Windows 与 Linux（银河麒麟）。

## 功能特性

- 自定义点击间隔（1-120 分钟）
- 三种点击模式：随机位置 / 中心点 / 自定义区域
- 防止系统自动锁屏
- 开机自动启动
- F6 快捷键快速启动/停止
- 后台低资源运行（内存约 20-30MB）
- 实时状态显示与日志记录

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

1. 设置点击间隔（分钟，1-120）
2. 选择点击模式：`random`（区域内随机）/ `center`（中心点）/ `custom`（自定义区域）
3. 点击「设置区域」，依次将鼠标移至区域左上角和右下角完成录制
4. 点击「启动」或按 F6 开始自动点击

配置与日志保存在用户主目录下（`~/.auto_clicker_config.json`、`~/.auto_clicker_logs/`）。

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
