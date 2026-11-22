"""FR-03 诊断中心：环境采集结果整形、可执行修复指引、脱敏诊断包。

本模块不依赖 tkinter，便于纯逻辑测试。UI 负责提供运行时事实（输入后端、
热键、自启、打包资源、目录可写性等），这里负责判定、文案和落盘。

设计原则：
- 诊断包只收白名单环境字段、脱敏日志尾部与安全配置摘要；
- 不包含点击坐标、窗口标题、完整配置、完整日志、用户名和本机路径；
- 没有诊断结论时也不静默：每项检查都带状态和修复步骤。
"""
from __future__ import annotations

import json
import os
import re
import zipfile
from datetime import datetime

SCHEMA = "autoclicker.diagnostics/1"
STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"

STATUS_LABELS = {
    STATUS_OK: "正常",
    STATUS_WARN: "需关注",
    STATUS_FAIL: "需处理",
}

# 只导出对排障有用、且不含用户目标信息的配置项
SAFE_CONFIG_KEYS = (
    "ui_mode",
    "theme",
    "theme_pack",
    "interval_seconds",
    "interval_unit",
    "click_mode",
    "click_button",
    "hold_ms",
    "jitter_pct",
    "click_limit",
    "duration_limit",
    "failsafe_enabled",
    "startup_countdown",
    "start_confirm_enabled",
    "hotkey_start",
    "hotkey_emergency",
    "autostart",
    "close_to_tray",
    "prevent_sleep",
    "onboarding_done",
)

_SENSITIVE_KEYS = re.compile(
    r"password|passwd|token|secret|api[_-]?key|cookie|authorization", re.I
)
_USER_DIR_RE = re.compile(r"([A-Za-z]:\\Users\\)[^\\\r\n]+", re.I)
_HOME_DIR_RE = re.compile(r"(/home/)[^/\s]+", re.I)
_SECRET_LINE_RE = re.compile(
    r"(?i)(password|passwd|token|secret|api[_-]?key|cookie|authorization)"
    r"(\s*[=:]\s*)([^\s,;]+)"
)


def status_label(status):
    return STATUS_LABELS.get(status, str(status))


def normalize_status(status):
    return status if status in STATUS_LABELS else STATUS_WARN


def _replace_home(text, home):
    """把用户主目录替换为占位符；Windows 路径按大小写不敏感处理。"""
    if not text:
        return ""
    value = str(text)
    candidates = []
    if home:
        candidates.append(str(home))
    expanded = os.path.expanduser("~")
    if expanded and expanded != "~":
        candidates.append(expanded)
    for candidate in candidates:
        candidate = candidate.rstrip("\\/")
        if not candidate:
            continue
        value = re.sub(re.escape(candidate), "<用户目录>", value, flags=re.I)
    return value


def redact_text(text, home=None, username=None):
    """脱敏任意日志/详情文本：用户目录、用户名、凭据字段。"""
    value = _replace_home(text, home)
    value = _USER_DIR_RE.sub(r"\1<用户>", value)
    value = _HOME_DIR_RE.sub(r"\1<用户>", value)
    if username:
        value = re.sub(
            r"(?i)(?<![\w.-])%s(?![\w.-])" % re.escape(str(username)),
            "<用户>",
            value,
        )
    value = _SECRET_LINE_RE.sub(r"\1\2<已隐藏>", value)
    return value


def directory_writable(path):
    """目录是否存在并可由当前用户写入；目录不存在时检查父目录。"""
    try:
        path = os.path.abspath(str(path))
        if os.path.isdir(path):
            return os.access(path, os.W_OK)
        parent = os.path.dirname(path)
        return bool(parent) and os.path.isdir(parent) and os.access(parent, os.W_OK)
    except Exception:
        return False


def read_tail(path, max_lines=60, home=None, username=None):
    """读取文本文件尾部并脱敏；文件不存在或不可读时返回空串。"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return ""
    tail = "".join(lines[-max(1, int(max_lines)):])
    return redact_text(tail, home=home, username=username)


def sanitize_config(config):
    """配置白名单摘要：不导出目标坐标、窗口关键字、方案名或文件路径。"""
    if not isinstance(config, dict):
        return {}
    result = {}
    for key in SAFE_CONFIG_KEYS:
        if key not in config:
            continue
        value = config[key]
        if _SENSITIVE_KEYS.search(str(key)):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
        elif isinstance(value, (list, tuple)):
            # 只保留短标量列表（如工作日），不保留点位字典
            if all(isinstance(v, (str, int, float, bool)) for v in value):
                result[key] = list(value[:16])
    return result


def _check(check_id, label, status, detail, fix=""):
    return {
        "id": check_id,
        "label": label,
        "status": normalize_status(status),
        "detail": str(detail),
        "fix": str(fix) if fix else "",
    }


def _input_check(context):
    ok = bool(context.get("input_ok", True))
    session = str(context.get("input_session") or "unknown")
    backend = str(context.get("input_backend") or "unknown")
    reason = str(context.get("input_reason") or "")
    if ok:
        return _check(
            "input", "输入后端",
            STATUS_OK,
            "可用；会话=%s，后端=%s" % (session, backend),
        )
    session_l = session.lower()
    if "wayland" in session_l:
        fix = (
            "1) 确认已安装 ydotool；2) 执行 systemctl --user start ydotoold；"
            "3) 仍失败时在登录页切换到 X11 会话。详见 docs/Wayland降级说明.md"
        )
    elif "x11" in session_l or "linux" in str(context.get("platform", "")).lower():
        fix = (
            "1) 安装 python-xlib 并确认 DISPLAY 指向当前桌面；"
            "2) 或安装 ydotool 后重试；3) 重启应用让后端重新探测。"
        )
    elif "darwin" in str(context.get("platform", "")).lower():
        fix = "在 系统设置 → 隐私与安全性 → 辅助功能 中勾选 AutoClicker，然后重启应用。"
    else:
        fix = (
            "1) 从当前交互式桌面会话启动（不要以服务或远程无桌面方式运行）；"
            "2) 确认安全软件未拦截鼠标 API；3) 重启应用后重新诊断。"
        )
    return _check("input", "输入后端", STATUS_FAIL,
                  "不可用；会话=%s，后端=%s%s" % (
                      session, backend, ("；" + reason) if reason else ""), fix)


def _hotkey_check(context):
    hk = context.get("hotkeys") or {}
    start = str(hk.get("start") or context.get("hotkey_start") or "f6")
    emergency = str(hk.get("emergency") or context.get("hotkey_emergency") or "f8")
    if start.strip().lower() == emergency.strip().lower():
        return _check(
            "hotkey", "全局热键", STATUS_FAIL,
            "启动键与紧急停止键相同：%s" % start,
            "在设置页把启动键或紧急停止键改成不同按键，再点击“应用热键”。",
        )
    if not hk.get("available", True):
        return _check(
            "hotkey", "全局热键", STATUS_FAIL,
            "keyboard 模块不可用，F6/F8/Esc 无法注册",
            "重新安装完整包；Linux 需确认当前用户可读取输入设备（必要时加入 input 组）。",
        )
    error = str(hk.get("error") or "").strip()
    if error:
        return _check(
            "hotkey", "全局热键", STATUS_FAIL,
            "注册失败：%s" % error,
            "1) 在设置页换用 F7/F9 等不常用按键；2) 关闭游戏/输入法/显卡驱动的同名热键；"
            "3) 重新点击“应用热键”并复查；若仍冲突，重启应用后再试。",
        )
    if hk.get("registered"):
        keys = ", ".join(str(k) for k in (hk.get("keys") or [start, emergency, "esc"]))
        return _check("hotkey", "全局热键", STATUS_OK, "已注册：%s" % keys)
    return _check(
        "hotkey", "全局热键", STATUS_WARN,
        "尚未注册（可能仍在启动初始化）",
        "打开设置页点击“应用热键”；若仍失败，查看本卡片的热键错误详情。",
    )


def _autostart_check(context):
    info = context.get("autostart") or {}
    supported = bool(info.get("supported", False))
    enabled = bool(info.get("enabled", False))
    registered = bool(info.get("registered", False))
    error = str(info.get("error") or "").strip()
    if not supported:
        return _check("autostart", "开机自启", STATUS_WARN,
                      "当前平台不支持开机自启",
                      "Windows 支持 HKCU Run；Linux 支持 ~/.config/autostart。其他平台请手动配置。")
    if enabled and error:
        return _check(
            "autostart", "开机自启", STATUS_FAIL,
            "已开启但读取/写入自启项失败：%s" % error,
            "1) 检查 HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run 写权限；"
            "2) 关闭安全软件对该注册表项的拦截；3) 关闭再重新开启自启开关。",
        )
    if enabled and registered and info.get("path_exists") is False:
        return _check(
            "autostart", "开机自启", STATUS_FAIL,
            "自启项指向的程序不存在%s" % (
                "：%s" % info.get("path") if info.get("path") else ""),
            "在设置页关闭后再开启“开机自动启动”，让自启项指向当前安装位置。",
        )
    if enabled and registered:
        return _check("autostart", "开机自启", STATUS_OK,
                      "已开启，自启项存在%s" % (
                          "：%s" % info.get("path") if info.get("path") else ""))
    if enabled and not registered:
        return _check(
            "autostart", "开机自启", STATUS_FAIL,
            "配置已开启，但未找到自启项",
            "在设置页先关闭“开机自动启动”，保存后再开启；仍失败时按权限项处理。",
        )
    if (not enabled) and registered:
        return _check(
            "autostart", "开机自启", STATUS_WARN,
            "配置已关闭，但系统仍保留自启项",
            "关闭再开启一次开关以清理残留；或手动删除 Run 项后复核。",
        )
    return _check("autostart", "开机自启", STATUS_OK, "未开启（按需开启）")


def _permission_check(context):
    config_ok = bool(context.get("config_writable", True))
    log_ok = bool(context.get("log_writable", True))
    diag_ok = bool(context.get("diag_writable", True))
    failed = []
    if not config_ok:
        failed.append("配置目录不可写")
    if not log_ok:
        failed.append("日志目录不可写")
    if not diag_ok:
        failed.append("诊断目录不可写")
    if failed:
        return _check(
            "permission", "文件权限", STATUS_FAIL,
            "；".join(failed),
            "1) 检查 %s 的目录权限；2) 不要安装到需要管理员写入的受保护目录；"
            "3) 关闭安全软件的目录保护后重试。" % (
                context.get("config_dir") or "配置/日志目录"),
        )
    return _check("permission", "文件权限", STATUS_OK,
                  "配置、日志与诊断目录均可写")


def _packaging_check(context):
    frozen = bool(context.get("frozen", False))
    missing = [str(x) for x in (context.get("missing_resources") or []) if x]
    icon_missing = bool(context.get("icon_missing", False))
    if not frozen:
        return _check("packaging", "打包资源", STATUS_OK,
                      "源码运行；跳过安装包完整性检查")
    if missing:
        return _check(
            "packaging", "打包资源", STATUS_FAIL,
            "缺少运行依赖：%s" % "、".join(missing),
            "重新安装完整安装包；onedir 必须保留 _internal 目录，不要只复制 AutoClicker.exe。",
        )
    if icon_missing:
        return _check(
            "packaging", "打包资源", STATUS_WARN,
            "图标资源缺失，托盘图标可能不显示",
            "重新安装完整包，确认 icons/tray*.ico 随包安装。",
        )
    return _check("packaging", "打包资源", STATUS_OK,
                  "安装包依赖与图标资源完整")


def _crash_check(context):
    path = str(context.get("crash_log") or "")
    if not path or not os.path.isfile(path):
        return _check("crash", "崩溃记录", STATUS_OK, "未发现 crash.log")
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    if size <= 0:
        return _check("crash", "崩溃记录", STATUS_OK, "crash.log 为空")
    return _check(
        "crash", "崩溃记录", STATUS_WARN,
        "检测到 crash.log（%d 字节）" % size,
        "点击“一键复制诊断包”，把脱敏后的日志尾部发给开发者；"
        "若反复出现，记录操作步骤与复现时间。",
    )


def _session_check(context):
    platform = str(context.get("platform") or "unknown")
    session = str(context.get("input_session") or "unknown")
    dpi = context.get("dpi_scale")
    screen = context.get("screen") or ""
    detail = "平台=%s；会话=%s" % (platform, session)
    if dpi is not None:
        detail += "；DPI=%.2f" % float(dpi)
    if screen:
        detail += "；屏幕=%s" % screen
    return _check("session", "会话与 DPI", STATUS_OK, detail)


def _config_check(context):
    config = context.get("config") or {}
    start = str(config.get("hotkey_start") or "f6").strip().lower()
    emergency = str(config.get("hotkey_emergency") or "f8").strip().lower()
    if start == emergency:
        return _check("config", "关键配置", STATUS_FAIL,
                      "启动键与紧急停止键相同",
                      "在设置页改为不同按键并保存。")
    return _check("config", "关键配置", STATUS_OK, "启动/急停键分离")


def build_report(context, now=None):
    """根据 UI 采集的运行时事实生成诊断报告（已脱敏）。"""
    context = dict(context or {})
    home = context.get("home") or os.path.expanduser("~")
    username = context.get("username") or ""
    generated = (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    checks = [
        _input_check(context),
        _hotkey_check(context),
        _autostart_check(context),
        _permission_check(context),
        _packaging_check(context),
        _crash_check(context),
        _session_check(context),
        _config_check(context),
    ]
    for item in checks:
        item["detail"] = redact_text(item["detail"], home=home, username=username)
        item["fix"] = redact_text(item["fix"], home=home, username=username)
    if any(item["status"] == STATUS_FAIL for item in checks):
        overall = STATUS_FAIL
    elif any(item["status"] == STATUS_WARN for item in checks):
        overall = STATUS_WARN
    else:
        overall = STATUS_OK
    report = {
        "schema": SCHEMA,
        "generated_at": generated,
        "overall": overall,
        "overall_label": status_label(overall),
        "app": {
            "version": str(context.get("app_version") or ""),
            "build_id": str(context.get("build_id") or ""),
            "python": str(context.get("python") or ""),
            "platform": str(context.get("platform") or ""),
            "frozen": bool(context.get("frozen", False)),
            "executable": redact_text(str(context.get("executable") or ""),
                                      home=home, username=username),
        },
        "checks": checks,
        "notes": "诊断包不包含点击坐标、窗口标题、完整配置或完整日志。",
    }
    return report


def build_summary(report):
    """生成给人看的纯文本摘要。"""
    if not isinstance(report, dict):
        return "诊断报告不可用"
    lines = [
        "AutoClicker 诊断摘要",
        "生成时间：%s" % report.get("generated_at", ""),
        "总体状态：%s" % report.get("overall_label", status_label(report.get("overall", STATUS_WARN))),
        "",
    ]
    for item in report.get("checks", []):
        lines.append("[%s] %s：%s" % (
            status_label(item.get("status")),
            item.get("label", ""),
            item.get("detail", ""),
        ))
        if item.get("fix"):
            lines.append("  修复：%s" % item["fix"])
    lines.extend(("", str(report.get("notes") or "")))
    return "\n".join(lines).strip() + "\n"


def package_path(base_dir, now=None):
    """诊断包文件名；同一秒冲突时追加序号。"""
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    os.makedirs(base_dir, exist_ok=True)
    base = "AutoClicker-diagnostics-%s.zip" % stamp
    path = os.path.join(base_dir, base)
    if not os.path.exists(path):
        return path
    for idx in range(2, 100):
        candidate = os.path.join(base_dir, "AutoClicker-diagnostics-%s-%d.zip" % (stamp, idx))
        if not os.path.exists(candidate):
            return candidate
    return os.path.join(base_dir, "AutoClicker-diagnostics-%s-%d.zip" % (stamp, 99))


def _write_text(zip_file, name, text):
    zip_file.writestr(name, text.encode("utf-8"))


def _redact_value(value, home=None, username=None):
    """递归脱敏诊断报告中的字符串，作为写包前的最后一道防线。"""
    if isinstance(value, str):
        return redact_text(value, home=home, username=username)
    if isinstance(value, dict):
        return {k: _redact_value(v, home=home, username=username)
                for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(v, home=home, username=username) for v in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(v, home=home, username=username) for v in value)
    return value


def write_package(path, report, log_tails=None, config=None, extra=None,
                  home=None, username=None):
    """写脱敏诊断 zip；report 应已由 build_report 生成。

    log_tails: {"app.log": "...", "crash.log": "..."}，调用方负责 read_tail。
    额外传入 home/username 时，会对报告再做一次递归脱敏。
    返回最终路径。
    """
    log_tails = log_tails or {}
    extra = extra or {}
    home = home or os.path.expanduser("~")
    username = username or os.path.basename(os.path.normpath(home))
    safe_report = _redact_value(report, home=home, username=username)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    files = {}
    report_text = json.dumps(safe_report, ensure_ascii=False, indent=2, sort_keys=True)
    summary_text = build_summary(safe_report)
    config_text = json.dumps(sanitize_config(config), ensure_ascii=False,
                             indent=2, sort_keys=True)
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        _write_text(zf, "diagnostics.json", report_text)
        _write_text(zf, "summary.txt", summary_text)
        _write_text(zf, "config.json", config_text)
        files["diagnostics.json"] = len(report_text.encode("utf-8"))
        files["summary.txt"] = len(summary_text.encode("utf-8"))
        files["config.json"] = len(config_text.encode("utf-8"))
        for name in ("app.log", "crash.log"):
            text = log_tails.get(name) or ""
            if not text:
                continue
            text = redact_text(str(text), home=home, username=username)
            entry = "logs/%s.tail.txt" % name
            _write_text(zf, entry, text)
            files[entry] = len(text.encode("utf-8"))
        for name, text in extra.items():
            if not isinstance(name, str) or "/" in name or "\\" in name:
                continue
            text = redact_text(str(text), home=home, username=username)
            _write_text(zf, "extra/%s" % name, text)
            files["extra/%s" % name] = len(text.encode("utf-8"))
        manifest = {
            "schema": SCHEMA,
            "generated_at": safe_report.get("generated_at", ""),
            "files": files,
            "sanitized": True,
        }
        _write_text(zf, "manifest.json", json.dumps(manifest, ensure_ascii=False,
                                                    indent=2, sort_keys=True))
    os.replace(tmp, path)
    return path
