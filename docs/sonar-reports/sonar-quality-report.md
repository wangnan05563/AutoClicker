# AutoClicker 代码质量治理报告

- 项目：AutoClicker（Python 3.14 / Tkinter 桌面自动点击工具）
- 项目路径：`D:\code\otherProjects\AutoClicker`
- 扫描日期：2026-11-14
- SonarQube：26.1.0.118079（Community Build，`http://localhost:9000`）
- Scanner：SonarScanner CLI 8.0.1.6346

## 一、结论

| 指标 | 修复前 | 修复后 |
|---|---:|---:|
| Issues（全部） | 30 | **0** |
| Code Smells | 30 | **0** |
| Bugs | 0 | **0** |
| Vulnerabilities | 0 | **0** |
| Security Hotspots | 2 | **0** |
| SQALE 技术债（分钟） | 206 | **0** |
| 认知复杂度 | 611 | 584 |
| 圈复杂度 | 405 | 436 |
| 重复行密度 | 0.0% | 0.0% |
| NCLOC | 2478 | 2582 |

- 修复前问题分布：20 Critical、8 Major、2 Minor，全部为 CODE_SMELL。
- 修复后：扫描问题清零，安全热点清零，质量门禁仅因“新代码覆盖率未上报”显示 ERROR（`new_coverage=0.0`），不是代码缺陷或扫描残留。
- 自动化测试：43 项全部通过（单元测试 + 集成测试 + GUI 冒烟）。
- 生产构建：见第五节。

## 二、修复前问题与处理

| 规则 | 数量 | 问题 | 处理方式 |
|---|---:|---|---|
| `python:S5754` | 12 | 裸 `except:` | 按场景改为 `except Exception:` 或 `except OSError:` |
| `python:S3776` | 6 | 认知复杂度超 15 | 拆分 `_apply_theme`、`set_autostart`、`click_loop`、`start_clicking`、`exit_application`、`build_exe` 的职责 |
| `python:S125` | 5 | 注释被判定为注释掉的代码 | 删除/改写无必要注释，复杂逻辑改由方法 docstring 说明 |
| `python:S1192` | 2 | 重复字面量 | 提取 `MSG_SAVE_CONFIG_FAILED`、`JSON_FILE_PATTERN` |
| `python:S3358` | 2 | 嵌套三元表达式 | 提取 `_log_tag` 静态方法 |
| `python:S3457` | 1 | 无占位符 f-string | 改为普通字符串 |
| `python:S7504` | 1 | 多余的 `list()` | 直接迭代 |
| `python:S1481` | 1 | 未使用局部变量 `app` | 改为 `app.root.mainloop()`，实际使用该变量 |

### 安全热点（2 → 0）

| 位置 | 原实现 | 修复 |
|---|---|---|
| 点击抖动随机数 | `random.randint` / `random.uniform` | 改用 `secrets.SystemRandom()`，避免可预测伪随机序列 |
| macOS 防休眠 | `os.system("caffeinate -u -t 1")` | 改为 `subprocess.run(["caffeinate", "-u", "-t", "1"], check=False, ...)`，参数化调用，无 shell 注入面 |

## 三、修复过程中发现的真实缺陷

- **保活线程忙循环**：`_keepalive_loop` 原来等待一个已 `set` 的 `Event`，导致 `wait(30)` 立即返回并疯狂打印“已设置Windows防休眠”。已新增 `keepalive_stop_event`，由 `start_keepalive` 清零、`stop_keepalive` 置位，循环按 30 秒正常等待。
- **首次运行引导阻塞冒烟测试**：GUI 冒烟使用全新临时用户目录，会触发 `messagebox.showinfo` 模态弹窗。测试入口已预置空配置文件，避免弹窗阻塞，同时保留产品真实首次运行引导。

## 四、测试结果

命令：

```powershell
& ".\.venv\Scripts\python.exe" -X utf8 -m unittest discover -s tests -p "test_*.py" -v
```

结果：`Ran 43 tests ... OK`。

覆盖范围：

- `tests/test_core_logic.py`：间隔换算、主题调色、点击点位、failsafe、上限停止、6 个输入校验、配置加载/保存/迁移、`click_loop` 单次点击与 failsafe 流程、保活不忙循环。
- `tests/test_build_script.py`：构建配置合并、图标解析、PyInstaller 命令组装、hidden imports。
- `tests/test_gui_smoke.py`：通过子进程在隔离 `USERPROFILE` 下真实创建 Tk 主窗口，校验标题/按钮并退出，断言保活日志不刷屏。

## 五、生产构建

- 构建命令：`python scripts/build_exe.py`
- 构建工具：PyInstaller 6.20.0，单文件、windowed
- 产物：`release/dist/AutoClicker.exe`
- 构建结果：**成功**（exit code 0）
- 产物大小：22,391,229 字节（约 21.35 MB）
- 启动冒烟：在隔离 `USERPROFILE` 下启动 exe，进程正常驻留 18 秒后由测试脚本结束（无启动崩溃）
- 构建日志：`docs/sonar-reports/build-run.log`

## 六、扫描配置说明

`sonar-project.properties` 关键项：

- `sonar.projectKey=AutoClicker`
- `sonar.sources=auto_clicker_py3.py,scripts`
- `sonar.tests=tests`、`sonar.test.inclusions=tests/**`
- `sonar.scanner.skipJreProvisioning=true`：使用扫描器自带 JRE，避免与并行扫描争抢下载缓存
- `sonar.scanner.skipSystemTruststore=true`：跳过 Windows 系统证书库遍历，避免扫描器在 `CKeyStore.loadKeysOrCertificateChains` 长时间阻塞（本机环境问题，不影响产品）

## 七、Git 提交

- `aaf2e68`：`refactor(quality): 修复 SonarQube 规范与复杂度问题并新增自动化测试`
- `2ae3a8e`：`fix(security): 消除安全热点并补强测试与质量报告`

## 八、残余事项

- 质量门禁 `new_coverage=0.0(ERROR)`：当前环境未安装覆盖率工具，未生成 Cobertura 报告。SonarQube 将新代码覆盖率按 0 计算。建议后续执行 `pip install coverage`，用 `coverage run -m unittest discover ...` + `coverage xml` 生成报告并配置 `sonar.python.coverage.reportPaths`。
- 本报告中的扫描指标来自最终 CE 任务 `b915ecbb-6be7-4453-9974-14d7057b7239`（SUCCESS）。
