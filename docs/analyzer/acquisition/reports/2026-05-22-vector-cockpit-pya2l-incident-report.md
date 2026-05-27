---
date: 2026-05-22
status: 1 of 3 fixed (Vector probe); 2 outstanding (cockpit chips, pya2l AV)
related_commits:
  - f2a2462  # fix(acquisition): Vector probes — use VectorBus.get_application_config, drop phantom canlib API
  - a0f862a  # earlier (incomplete) Windows native-import safety fix
related_lessons:
  - docs/lessons-learned/codex-windows-native-import-guard.md
authors: [hang]
---

# 2026-05-22 Vector / Cockpit / pya2l 联合故障分析报告

## 0. 摘要

本日单次会话里暴露了 **三个层次相关但根因互相独立** 的问题。第一个已经定位 + 修复 + 上游，
另外两个根因已经确认，修复方案已经设计，等待授权落地。

| # | 问题 | 状态 | 阻断什么 |
|---|---|---|---|
| 1 | `vector_probe._stage_app` 和 `vector_hw_probe` 调用了 python-can 里根本不存在的 `canlib.get_application_config` / `canlib.get_channel_count` | **已修复** (`f2a2462`) | CLI probe Stage 2 在所有 Windows 真机上 100% 假阳性；Settings/Test Connection 的 HW 检查误红；任何绑定 `vector_hw_probe` 的 health 入口都会误红 |
| 2 | Cockpit 五个 health chip 在生产入口下永远不亮（全灰） | 已分析，未修 | 操作员无视觉反馈 |
| 3 | 点工具栏 **A2L** 选文件 → 进程闪退（`0xC0000005`，Access Violation） | 已根因确认，未修 | A2L 装载不能；下游所有真机 ECU 路径全部阻断 |

这三个问题不是孤立的：操作员从问题 #2（看不到灯）尝试自救（按提示去加载 A2L），立刻撞上问题 #3（崩溃）。同时，问题 #1 的修复虽然已经让 CLI probe 和 Settings/Test Connection 这类真实 probe 入口恢复可信，但生产 cockpit 的 health strip 目前仍然不读这个真 probe，而是读本地 stub。**它们共同的元教训是"测试通过 ≠ 真机通过"** —— 三个问题在 CI 里全绿。

---

## 1. 背景与今日时间线

按发生顺序：

1. 操作员在真机上首次跑 `python -m can_logger.p0.vector_probe --open --app-name Python --channel 0 --bitrate 500000`。
   - 立即报 `vxlapi DLL not loadable`。
2. 诊断：操作员只装了 **XL Driver Library 25.20.14**（SDK 包，只放 `vxlapi64.dll`，不含设备驱动）。VN1630A 在设备管理器里显示为 "Unknown"（USB 总线认得但内核驱动没绑）。
3. 引导操作员下载并以管理员权限安装正确的 **Vector Driver Setup 26.10.2**（含 VN1630A 的 `.inf/.sys` 内核驱动 + Hardware Configurator）。安装 ≈ 15 min。
4. 安装后 `pnputil` 已注册四个 Vector 驱动包；VN1630A 状态变为 OK，class 为 `Vector-Hardware`。
5. 用 `xlSetApplConfig` 把 `Python` app channel 0 绑到 VN1630A Channel 1 (`hw_type=57, hw_index=0, hw_channel=0`)。
6. **再次跑 probe，stage 4 真正打开 CAN 总线**（`open=true bitrate=500000`），但 stage 2 报 `python-can vector.canlib surface unavailable: module 'can.interfaces.vector.canlib' has no attribute 'get_application_config'`，整体退出码仍是 2。**问题 #1 浮现。**
7. 详细分析 probe 的 stage 2 假阳性逻辑，定位 phantom API；同时在仓库里发现 `mf4_analyzer/acquisition_capture/vector_hw_probe.py` 也犯了同一个错。修复并验证：26/26 测试通过，真机 probe 四绿，commit `f2a2462`，push origin。
8. 操作员尝试在 cockpit 里"选 app=Python 连 1630"，反馈 "**一个灯都不亮**"。问题 #2 浮现。
9. 让操作员先加载 A2L 文件（绕过 chip 路径），**A2L 一选立刻 `0xC0000005` 闪退**。问题 #3 浮现。
10. 对照实验复现：单独 `from pya2l import DB` 干净，先 `QApplication([])` 再 `from pya2l import DB` → 段错误（Linux 重现为 exit 139，等价于 Windows 0xC0000005）。

---

## 2. 问题 #1：Vector probe 使用了 phantom python-can API（已修）

### 2.1 症状

Stage 2 在每一台 Windows 真机上都返回：

```
[stage2/app]  name="Python"  configured=unknown  error=python-can vector.canlib surface unavailable:
              module 'can.interfaces.vector.canlib' has no attribute 'get_application_config'
```

退出码 = 2，操作员据此误判"app 槽没配置"，进入错误诊断流程。同样的代码模式在 `mf4_analyzer.acquisition_capture.vector_hw_probe.vector_hw_probe` 里出现，使 Settings 对话框的 **Test Connection** 以及任何显式绑定 `vector_hw_probe` 的 health 入口 **不管真机健康度如何都会报红**。

### 2.2 根因

两处生产代码都引用了 python-can 4.6 里**不存在的两个 API**：

- `canlib.get_application_config(app_name)` — 不存在
- `canlib.get_channel_count()` — 不存在

真实 API 在 `VectorBus` 类上、是 `@staticmethod`：

- `VectorBus.get_application_config(app_name, app_channel)` → `(hw_type, hw_index, hw_channel)`，失败时抛 `VectorInitializationError`（继承自 `VectorError`，**不是** `LookupError`）
- `len(can.interfaces.vector.get_channel_configs())` 才是通道数

代码里那段 `# Older python-can versions expose canlib differently.` 的注释是**错误的猜测** —— 这两个 API **从来不是模块级**，所有已发布的 python-can 版本都把它们放在 `VectorBus` 类上。

### 2.3 为什么这个 bug 能活到真机

**Plan / spec 文档链路是源头。** 修复前的 Stage 8 spec 在 HW health 表格里把这两个 phantom API 写成权威路径；当前 spec 已在 `docs/analyzer/acquisition/specs/2026-05-17-stage-8-vector-xcp-backend-spec.md:523-532` 修正为 `VectorBus.get_application_config(app_name, channel)` 和 `vector.get_channel_configs()`，并补了 phantom API 警告。Plan 文档仍保留历史错误片段（`docs/analyzer/acquisition/plans/2026-05-17-stage-8-vector-xcp-backend.md:2945-3174`），两个 probe 实现照抄 plan，测试也照抄。

**测试用 MagicMock 完全掩盖了 bug。** `tests/test_vector_hw_probe.py:50-67`：

```python
fake_canlib = MagicMock()
fake_canlib.get_application_config.return_value = MagicMock(...)
fake_canlib.get_channel_count.return_value = 4
```

`MagicMock` 对任意属性访问返回新的 mock 子对象，所以在测试里 `fake_canlib.get_application_config` 永远存在；生产代码在真 `canlib` 模块上访问同名属性立刻 `AttributeError`。

**Probe 自己的 stage 2 测试全部 patch 掉了 `_stage_app` 函数体**（`monkeypatch.setattr(vector_probe, "_stage_app", ...)`），所以 `_stage_app` 的真实代码路径在整个 CI 里**从未被执行过**。

这个反模式叫 **"phantom API tests"**：测试把生产代码依赖的整个接口面 mock 掉了，所以生产代码引用一个根本不存在的 API surface 时，测试期不可能暴露。

### 2.4 修复（commit `f2a2462`）

| 文件 | 改动 |
|---|---|
| `can_logger/p0/vector_probe.py` | `_stage_app` 改用 `VectorBus.get_application_config(app, channel)`；签名补 `app_channel`；捕 `VectorInitializationError`；删除死 `LookupError` 分支和错注释；import / call 拆两个 try 防 `UnboundLocalError` 级联 |
| `mf4_analyzer/acquisition_capture/vector_hw_probe.py` | 同上 + `canlib.get_channel_count()` 改为 `len(vector.get_channel_configs())`；新增 `_decode_dll_version` 从 `XLdriverConfig.dllVersion` 解出 `"major.minor.build"` |
| `tests/test_vector_probe_stages.py` | 新增 `_fake_vector_with_bus` 跨平台 fake；4 个真正驱动 `_stage_app` 函数体的测试（regression guard：必须用 2 参调用） |
| `tests/test_vector_hw_probe.py` | `MagicMock` 全部替换为结构化 `_fake_vector_pkg`；新增"通道枚举失败"和"通道越界"两个测试 |
| `docs/.../2026-05-17-stage-8-vector-xcp-backend-spec.md` | 修正 §HW health 表格的 API 路径；加 phantom API 警告 box |

### 2.5 验证

- 单元测试：`pytest tests/test_vector_probe_stages.py tests/test_vector_hw_probe.py` → **26/26 通过**
- 真机 probe：

```
[stage1/driver]  loadable=true
[stage2/app]  name="Python"  channel=0  configured=true  hw_type=57  hw_index=0  hw_channel=0
[stage3/channel]  index=0  present=true  count=7
[stage4/bus]  open=true  bitrate=500000
result: all_green        EXIT=0
```

---

## 3. 问题 #2：Cockpit 五个 health chip 永远不亮（已分析，未修）

### 3.1 症状

操作员在 cockpit 里 Settings → Transport → app=Python 保存 → 工具栏点 **连接 ECU** → 五个 health chip（HW / CAN / XCP / DAQ / REC）全部停在初始灰色 (`#94a3b8`)。状态栏底部有一行小字提示，但工位上不显眼。

### 3.2 根因

**Health chip 由 `QTimer` 驱动，timer 只在一处启动。** `main_window.py:992-993`：

```python
if not self._health_timer.isActive():
    self._health_timer.start()
```

这一行在 `_begin_connection_attempt` 内部，且位于一道前置守卫之后（line 979-982）：

```python
if not self._maybe_swap_to_vector_backend():
    self._fake_xcp_connected = False
    self._fake_rec_state = "off"
    return                  # 直接 return，下面 timer.start() 不会执行
```

`_maybe_swap_to_vector_backend()` 有三个硬前置：

1. `self._transport_config is not None` — Settings 保存后才有
2. `self._ifdata_xcp is not None` — 需要先加载 A2L
3. `self._left_pane._pool` 非空 — A2L 解析后填充

任意一个缺失 → False → timer 永不启动 → chip 永远是初始灰。当 cockpit 由 production 入口（`MF4 Data Analyzer V1.py` → `mf4_analyzer.app.main`）开起来时，`allow_fake_backend=False`，没有 fallback 路径；状态栏写一行 `[FAKE backend] 不录真实 ECU: A2L IF_DATA 未加载; measurement pool 为空` 就 return。

**第二个潜伏 bug：即便 timer 启动了，chip 也不反映真硬件。** `main_window.py:1953-1969` 的 `_probe_hw` 是 demo stub：

```python
def _probe_hw(self) -> HwHealth:
    if self._connection_attempt_started is not None or self._fake_xcp_connected:
        return HwHealth(ok=True, driver_version="demo-fake", ...)
    return HwHealth(ok=False, ..., error="non-windows host")
```

`HealthAggregator` 用这一组 stub 构造（line 256-262），**从来不调** `vector_hw_probe`。所以 commit `f2a2462` 修好的真 probe 在 cockpit health strip 这条路径上是 dead code；唯一用户可见地调它的入口是 Settings 对话框的 **Test Connection** 按钮（`settings_dialog.py:524`），那个按钮用 `QMessageBox.information/warning` 直接显示结果，不更新 chip。

**第三个潜伏 bug：`_connection_attempt_started` 设置得太早。** `_begin_connection_attempt()` 在调用 `_maybe_swap_to_vector_backend()` 之前就把 `self._connection_attempt_started = time.monotonic()`。如果后续仅把 timer 提前启动、但不改 `_probe_hw`，一次被前置条件挡住的连接尝试也会让 `_probe_hw` 因为 `_connection_attempt_started is not None` 返回 `ok=True / driver_version="demo-fake"`。也就是说，**单独做 F2.1 可能把"灰灯"修成"假绿灯"**，比当前更危险。

### 3.3 为什么测试不报

`tests/acquisition_ui/test_health_strip.py` 之类是构造 `HealthSnapshot` 手动喂给 `HealthStrip.apply_snapshot`，**绕过整个 timer + aggregator + probe 链路**。`MainWindow` 级别的测试用 `health_aggregator` 注入位的 mock，也绕过 `_probe_hw`。`tests/acquisition_ui/test_record_backend_swap.py` 覆盖了 `_maybe_swap_to_vector_backend()` 的缺前置条件和 `_begin_connection_attempt()` 不启动 fake backend，但断言的是 status bar / backend start 次数，**没有断言 health timer 是否启动、chip 是否从初始灰更新、以及失败连接是否会留下假绿状态**。

### 3.4 建议的修复（按优先级）

**(F2.1) 把 health timer 在 `__init__` 就启动，但必须和 F2.2/F2.4 一起做。** 空闲时也轮询，chip 至少能显示"未配置"而不是"灰"。单独提前 timer 不安全：当前 `_probe_hw` 会在失败连接后用 stale `_connection_attempt_started` 喂出 `demo-fake` 绿灯。

**(F2.2) 把 `_probe_hw` 接到真 `vector_hw_probe`**：

```python
def _probe_hw(self) -> HwHealth:
    if self._transport_config is None:
        return HwHealth(ok=False, ..., error="transport 未配置",
                        last_probe_ts=time.monotonic(), ...)
    from mf4_analyzer.acquisition_capture.vector_hw_probe import vector_hw_probe
    return vector_hw_probe(self._transport_config)
```

CAN / XCP / DAQ / REC 四个 probe 也类似（这些需要 backend 真实运行后从 `backend.status()` 取数据 —— 工作量更大，留到后续 Stage）。

**(F2.3) 把 `_maybe_swap_to_vector_backend()` 失败时的静默 status bar 提示改成窗口级 warning**。状态栏在车间里被忽略是高概率事件。实现时不要用 `QMessageBox.warning(...)` 静态方法：仓库 lesson 已确认它在 `QT_QPA_PLATFORM=offscreen` 下会 `exec()` 挂住测试。应当复用 `apply_a2l_path()` 当前模式：构造 `QMessageBox(self)`、`setWindowModality(Qt.WindowModal)`、保存到 `self._connection_warning_box`、最后 `.open()`，并提供 `_warn_connection_preconditions(...)` wrapper 方便测试 stub。

**(F2.4) 调整 `_connection_attempt_started` 的写入时机或失败清理。** 它不应该在前置条件失败时留下非空值。推荐把它移到 `_backend.start(selection)` 成功之后；或者在 `_maybe_swap_to_vector_backend()` / backend start 失败分支里显式清零。否则 F2.1 启动 timer 后会把失败连接误显示成 demo HW OK。

---

## 4. 问题 #3：pya2l 选文件后 `0xC0000005` 段错误（已根因，未修）

### 4.1 症状

PyCharm 跑 `MF4 Data Analyzer V1.py` 起 Analyzer → 打开 cockpit → 点工具栏 **A2L** 按钮 → 文件选择对话框 → 选 `.a2l` → 进程立即结束，PyCharm 终端显示 `进程已结束，退出代码为 -1073741819 (0xC0000005)`。无 Python traceback。

### 4.2 复现与根因

`0xC0000005` 是 Windows Access Violation —— 原生代码段错误，不经过 Python 异常机制，`try/except` 抓不住。

对照实验（PyCharm 用的 venv：`D:\Coding project\data analyzer\.venv`，里面装的是 `pya2ldb-1.0.332` (pya2l 0.10.2)）：

| 实验 | 结果 |
|---|---|
| `from pya2l import DB`（无 PyQt） | OK |
| `QApplication([])` then `from pya2l import DB` | **Segfault** (exit 139 / 0xC0000005) |

结论：**`pya2l` 的原生 ANTLR 运行时无法在已经初始化 `QApplication` 的进程里安全 import**。

### 4.3 为什么之前的修复 `a0f862a` 没解决这个

提交 `a0f862a` 的描述：

> Cockpit and Vector paths could crash with 0xC0000005 when pyxcp.master loaded inside an already-PyQt process, and Cockpit startup eagerly imported pya2l before any A2L file was selected. Guard both:
> - a2l_probe: **lazy-load pya2l** only when an A2L is parsed.
> - backends: probe pyxcp import in an **isolated subprocess**; ...

`pyxcp` 走的是**子进程隔离**（正确 + 永久），`pya2l` 走的是**延迟加载**（错误 + 仅推迟）。延迟加载只让 import 的时间点从 cockpit 启动推到"用户点 A2L"那一刻，并没有改变 import 发生在主进程里这个事实。当用户真点 A2L 时，PyQt 已经在跑，pya2l 原生库照旧崩。**`a0f862a` 是个未完成的修复**，把崩溃从启动期推到了用户首次选 A2L 时，对操作员看起来更突然了。

`docs/lessons-learned/codex-windows-native-import-guard.md` 写明白了规则：

> If a dependency can terminate the process, do not rely on try/except; **guard UI-path imports with an isolated subprocess probe** that mimics the PyQt-loaded context, then surface failure as a normal unavailable backend/status message.

`pya2l` 没遵守这条。

### 4.4 建议的修复

按 lessons-learned 文档明示的 rule，复刻 `backends.py` 里 pyxcp 已有的子进程探针形态：

1. 在 `can_logger/p0/a2l_probe.py` 内拆出一个 **只给子进程调用** 的纯解析函数，例如 `_load_measurement_summary_inprocess(path, limit)`。它可以继续复用 `MeasurementSummary` / `A2LSummary` / `_fill_ifdata_events` 等纯数据逻辑，但真正 `from pya2l import DB` 只能发生在这个函数内部。
2. 新增 `can_logger/p0/_a2l_subprocess.py`（**永远不被主进程 import**）。模块 `__main__`：用 `argparse` 读 A2L 路径，调用 `_load_measurement_summary_inprocess(...)` 拿到 `A2LSummary` 数据，pickle 到 stdout（二进制），异常时 stderr + 非零退出码。
   - 注意：子进程入口不能调用 public `load_measurement_summary(...)`，因为 public 函数会改成"启动子进程"的 wrapper；否则会递归 spawn 自己。
   - `subprocess.run(..., capture_output=True)` 的父进程侧不要设置 `text=True`，stdout 是 pickle bytes。
3. 改造 `can_logger/p0/a2l_probe.py`：
   - 顶层删除 `_load_pya2l()` 和所有 `from pya2l import ...`。
   - `load_measurement_summary(path, limit=None)` 改为：用 `subprocess.run([sys.executable, "-m", "can_logger.p0._a2l_subprocess", path, "--limit", ...], capture_output=True, timeout=...)`。
   - exit 0 → unpickle stdout → 返回 `A2LSummary`。
   - exit ≠ 0 / timeout → 抛 `RuntimeError`，附 stderr 内容 / 段错误标识。
4. cockpit `apply_a2l_path` 的现有 `try: ... except Exception` 接住 RuntimeError，弹窗提示 "A2L 解析子进程退出 (0xC0000005)，请联系开发者"。
5. 测试：
   - `tests/test_p0_a2l_probe.py` 新增 `test_subprocess_pickle_roundtrip`、`test_subprocess_segfault_becomes_runtime_error`、`test_subprocess_timeout_becomes_runtime_error`（用 monkeypatch.setattr(subprocess, "run", ...)）。
   - regression guard：grep 确认主代码里没有任何 `import pya2l` 或 `from pya2l`，唯一例外是 `_load_measurement_summary_inprocess` / `_a2l_subprocess.py` 这条子进程专用链路。

### 4.5 副作用

修完后：

1. 操作员点 A2L → 主进程不再 crash；成功时看到 measurement 列表，失败时看到可读的子进程错误弹窗
2. `_left_pane._pool` 非空 → 满足 `_maybe_swap_to_vector_backend()` 一条前置
3. 加上 transport 保存 → 满足全部前置 → timer 启动 → chip 至少由 demo stub 喂养能"亮成绿"

但 **chip 反映的还是 stub 数据，不是真 Vector 健康**。问题 #2 的 F2.2 仍然要做。

---

## 5. 横向主题：三个 bug 的共同失败模式

| 主题 | 问题 #1 | 问题 #2 | 问题 #3 |
|---|---|---|---|
| CI 期间被 mock 完全屏蔽 | ✓ (`MagicMock`, `monkeypatch _stage_app`) | ✓ (timer + aggregator 被绕过) | ✓ (subprocess 路径根本不存在) |
| 修复时偷工 / 仅触及 spec 边缘 | ✓ (spec 字面写错 API 名) | — | ✓ (`a0f862a` 只延迟未隔离) |
| 真机才暴露 | ✓ | ✓ | ✓ |
| 错误对操作员不显眼 | exit code 2 看起来像"app 没配" | 状态栏一行小字 | 没有 Python traceback |

**根本对策**（应进入或更新到 lessons-learned）：

- **"phantom API" guard**：对外部库的 mock 不能用无约束 `MagicMock` 伪造整个模块 surface。CI 能安装真实库时，至少跑一次 `create_autospec(real_module)` 或等效 API-surface 测试；真实库不可用时，也要用结构化 fake 明确列出允许属性，并用 regression 断言生产代码不会访问 phantom attribute。
- **"native + UI 隔离" guard**：对已证实会终止进程的原生依赖（当前是 `pya2l`、`pyxcp`），**只能**通过子进程探针访问，主进程零 import。`python-can` / Vector `canlib` 目前没有同等 crash 证据，可以作为 bounded probe 留在进程内，但必须有结构化 API-surface 测试、明确超时/节流策略，并且不能用 phantom mock 代替真实 surface。新增 regression：`rg "import pya2l|from pya2l|import pyxcp|from pyxcp" can_logger mf4_analyzer` 必须为空（除子进程入口模块或动态 import wrapper 自身）。
- **"状态栏不算反馈" 准则**：操作员级别的失败（连接前置缺失、A2L 解析失败、硬件不可用）一律弹窗，状态栏只用于持续指标。

---

## 6. 后续行动项（按优先级 + 推荐执行者）

| # | 行动 | 优先级 | 估时 | 涉及文件 |
|---|---|---|---|---|
| A | **修问题 #3：pya2l 子进程隔离** | P0（阻断操作员） | 半天 | `can_logger/p0/a2l_probe.py`, `can_logger/p0/_a2l_subprocess.py`(新), `tests/test_p0_a2l_probe.py`(扩) |
| B | **修问题 #2 F2.1 + F2.4：health timer 在 `__init__` 启动，并修正 `_connection_attempt_started` 写入/清理** | P1 | 45 min | `main_window.py` timer 启动 + 失败路径状态清理 + 1 个 UI 测试 |
| C | **修问题 #2 F2.2：`_probe_hw` 接真 `vector_hw_probe`，并避免失败连接喂出 `demo-fake` 绿灯** | P1 | 1-2 h | `main_window.py` `_probe_hw` 重写 + `tests/acquisition_ui/test_health_strip.py` / `test_record_backend_swap.py` 增 |
| D | **修问题 #2 F2.3：缺失前置改 operator-visible warning** | P2 | 45 min | `main_window.py` `_maybe_swap_to_vector_backend` 静默路径；使用 `QMessageBox(...).open()` wrapper，不用 static `QMessageBox.warning` |
| E | 更新 lessons-learned：新增 "phantom API" 规则，并把 pya2l 子进程结论补进现有 native-import lesson | P2 | 30 min | `docs/lessons-learned/INDEX.md` + 新 md / 更新 `codex-windows-native-import-guard.md` |
| F | 给 `can_logger.p0` 增加 regression CI guard：`rg "import pya2l\|from pya2l\|import pyxcp\|from pyxcp"` 在主代码区为空，允许子进程入口 / 动态 import wrapper 白名单 | P2 | 1 h | `tests/test_lessons_scripts.py` 或类似 |
| G | 给 A2L 子进程加 watchdog（默认 30s 解析超时，避免大文件卡死） | P3 | 包含在 A 里 | 同 A |

### 推荐流程

1. **今天**：完成 A（pya2l 子进程隔离）。无 A 则操作员无法继续真机测试。
2. **明天**：B + C + D 一起出 PR（cockpit 体验闭环：先有灯、灯反映真硬件、失败连接不会假绿、操作员看得到错误）。
3. **本周内**：E + F（防止下次同类 bug 再次落库）。

### 风险与对策

- **A 涉及 pickle subprocess IPC**：pickle 反序列化只信任本地子进程；不引入安全风险，但要确认 `A2LSummary` 及其 nested dataclass 都可 pickle。先跑一个 `pickle.dumps(real_summary)` 的预检。
- **B 改 timer 启动时机后，初始 chip 颜色会变**（从灰变成 "传输未配置=red/off" 一类显式状态）。这是期望变化，但必须同时修 `_connection_attempt_started`，否则失败连接可能变成 `demo-fake` 绿灯。
- **C 在生产里调真 `vector_hw_probe` 每 N 秒一次**：不要假设 XL Driver Library 调用永远轻量。先加 throttle/cache（例如只在 transport 变更或固定较长间隔刷新 HW），再看是否需要 worker/subprocess。至少要有 UI 测试证明 timer tick 不会直接阻塞或误绿。

---

## 7. 附录：关键代码定位

| 主题 | 文件:行 |
|---|---|
| Phantom `canlib.get_application_config` 调用（已修） | `can_logger/p0/vector_probe.py:146` (修前) / `mf4_analyzer/acquisition_capture/vector_hw_probe.py:68` (修前) |
| 真实的 `VectorBus.get_application_config` 定义 | `.venv/Lib/site-packages/can/interfaces/vector/canlib.py:1031` |
| Cockpit health timer 启动唯一入口 | `mf4_analyzer/acquisition_ui/main_window.py:992-993` |
| Cockpit health probe stub | `mf4_analyzer/acquisition_ui/main_window.py:1953-2002` |
| 失败连接会留下 `_connection_attempt_started` | `mf4_analyzer/acquisition_ui/main_window.py:968-982` |
| 三前置守卫 | `mf4_analyzer/acquisition_ui/main_window.py:1024-1043` |
| Settings/Test Connection 真 HW probe 入口 | `mf4_analyzer/acquisition_ui/settings_dialog.py:510-524` |
| pya2l 延迟加载（不充分） | `can_logger/p0/a2l_probe.py:37-51` |
| pyxcp 子进程隔离（正确模板） | `mf4_analyzer/acquisition_capture/backends.py:441-486` |
| 前次同类 bug lessons-learned | `docs/lessons-learned/codex-windows-native-import-guard.md` |
| Spec 已修正的 phantom API 警告 | `docs/analyzer/acquisition/specs/2026-05-17-stage-8-vector-xcp-backend-spec.md:520-540` |

---

## 8. 一句话总结

**XL Driver Library 和 Vector Driver Setup 装对了**（VN1630A 真机已经可用），但软件链路上有三道"看起来在工作"的伪 layer —— phantom API 把 probe 报红、stub probe 把 chip 喂假数据、in-process 原生 import 把 cockpit 在 A2L 点击瞬间一炮打死。三道都是"被 mock 掩盖的真机断点"。**Mock 用对地方是减少耦合，用错地方就是把 bug 焊死在代码里。**
