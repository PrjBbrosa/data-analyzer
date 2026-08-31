# 游标显示设置与结果面板自适应实施计划

> **执行要求：** 每个实现任务由独立 agent 按 TDD 完成，随后由独立 reviewer 对照规格审查；不允许在红测之前写生产实现。

- 日期：2026-08-31
- 状态：已完成（2026-08-31，分支 `codex/cursor-display-settings`）
- 实施基线：`main@44a65faad9f141b29397d930f8c8f8cbafb0b3a7`
- 对应规格：[`2026-08-31-cursor-display-settings-spec.md`](../specs/2026-08-31-cursor-display-settings-spec.md)
- 交互原型：[`2026-08-31-cursor-display-settings.html`](../ui-prototypes/2026-08-31-cursor-display-settings.html)

## 1. Goal、架构与技术栈

**Goal：** 为时域游标增加一个全局显示设置入口；单游标自定义 X 只显示当前位置的 `X↑/X↓` 值，双游标按设置显示极值点和 Min/Max/Avg，并保证所有组合、窄窗、分屏和重复通道名下结果面板不溢出、不重叠、不串数据。

**Architecture：** 数值层新增 UI-neutral 的自定义 X 单点分支采样结果；chart stack 新增不可变设置值对象、纯展示模型和弹出控件；pyqtgraph cursor collaborator 继续拥有实时数据与 marker；ChartStack 作为唯一偏好协调者，使用 QSettings 同步所有当前/未来 pane。兼容字符串 signal 保留，新增结构化单游标结果沿 canvas → stack → pill 传递。

**Tech Stack：** Python、NumPy、PyQt5、pyqtgraph、QSettings、pytest、pytest-qt、现有 QSS/token 系统。

## 2. 全局约束与共享接口

1. 不新增 MainWindow mutable state，不写 ViewState/project/preset schema。
2. `signal/` 不 import Qt/UI；`ui/pg_canvas/` 新增 backref 名称时同步 `_owned_names`/`_delegate_names`。
3. 通道身份始终使用 composite source/channel key；display label 只用于显示。
4. 五个字段及默认值固定为：

   ```python
   @dataclass(frozen=True)
   class CursorDisplayOptions:
       show_max_point: bool = True
       show_min_point: bool = True
       show_max_value: bool = True
       show_min_value: bool = True
       show_avg_value: bool = True
   ```

5. 所有 formatter/layout 输入使用结构化 DTO；HTML 不作为数值真相或身份键。Canvas 新增 `single_cursor_rows = pyqtSignal(object)`，ChartStack 新增 `_on_single_cursor_rows(rows)`；旧 `cursor_info` 保留。
6. 所有 content/setting/full-mini/resize 变化继续汇入 `ChartStack._update_pill_content()` 的单一定位路径。
7. 设置存储接口固定为 `CursorDisplaySettingsStore.load() -> CursorDisplayOptions` 与 `save(options) -> None`，使用单一 key `charts/time_cursor/display_options_v1`。TimeChartCard 发出 `cursor_display_options_changed = pyqtSignal(object)`。
8. 新交互同步更新 `mf4_analyzer/ui/hints.py` 与 `mf4_analyzer/ui/quickref.py`。
9. 每个 worker 只改其 owner 文件，不回退其他 agent 或用户修改；发现共享接口不匹配先记录到 progress ledger，再停下协调。

## Task 1 — 自定义 X 单游标数值契约

**Agent：** signal-processing expert
**Owner files：**

- `mf4_analyzer/signal/custom_x_paths.py`
- `tests/test_custom_x_paths.py`

**不改：** 任何 `mf4_analyzer/ui/` 文件。

### 3.1 RED：先写失败测试

在 `tests/test_custom_x_paths.py` 增加覆盖：

- `test_sample_custom_x_cursor_returns_rise_then_fall_values`
- `test_sample_custom_x_cursor_interpolates_within_each_leg_only`
- `test_sample_custom_x_cursor_reports_one_reliable_direction`
- `test_sample_custom_x_cursor_rejects_shape_mismatch_without_truncation`
- `test_sample_custom_x_cursor_handles_empty_short_and_nonfinite_segments`
- `test_sample_custom_x_cursor_does_not_extrapolate`
- `test_sample_custom_x_cursor_reports_ambiguous_multi_turn_path`
- endpoint、整数/浮点 dtype、重复转折点和既有 tolerance policy 回归。

运行并确认新增测试因 API 缺失或行为缺失而失败：

```powershell
$env:PYTHONPATH='.'
& 'D:\Coding project\data analyzer\.venv\Scripts\python.exe' -m pytest tests/test_custom_x_paths.py -q
```

### 3.2 GREEN：最小 UI-neutral 实现

在 `custom_x_paths.py` 增加公开不可变 DTO：

```python
@dataclass(frozen=True)
class CursorBranchValue:
    direction: int       # +1 => X↑, -1 => X↓
    value: float

@dataclass(frozen=True)
class CustomXCursorResult:
    values: tuple[CursorBranchValue, ...]
    reason: str

def sample_custom_x_cursor(
    x: np.ndarray,
    y: np.ndarray,
    x_value: float,
) -> CustomXCursorResult: ...
```

复用 `analyze_custom_x_paths()` 的有限段、转折和 major-leg policy；仅在单条已确认物理 leg 内局部插值。禁止复制/分叉已有 leg 分类算法，禁止 `min(len(x), len(y))`。

### 3.3 REFACTOR 与验证

- 运行 `tests/test_custom_x_paths.py`。
- 运行边界门禁：

  ```powershell
  & 'D:\Coding project\data analyzer\.venv\Scripts\python.exe' -m pytest tests/test_signal_no_gui_import.py tests/ui/test_import_boundaries.py -q
  ```

- 运行 `git diff --check`。
- 提交：`feat(signal): sample custom-x cursor branches`

## Task 2 — 设置控件、展示模型与结果面板布局

**Agent：** PyQt UI engineer
**Owner files：**

- 新建 `mf4_analyzer/ui/chart_stack/cursor_display.py`
- `mf4_analyzer/ui/chart_stack/cursor_pill.py`
- `mf4_analyzer/ui/chart_stack/cards.py`
- `mf4_analyzer/ui/plot_helpers.py`
- `mf4_analyzer/ui_kit/style.qss`
- `tests/ui/test_cursor_display_settings.py`（新建）
- `tests/ui/test_cursor_pill_formatting.py`
- `tests/ui/test_plot_helpers.py`
- `tests/ui/test_chart_stack.py` 中仅控件/几何层用例

**不改：** `signal/`、`ui/pg_canvas/cursor.py`、MainWindow、ViewState/project persistence。

### 4.1 RED：冻结 32 组合与几何规则

先增加纯模型参数化测试，穷举 `itertools.product((False, True), repeat=5)`，每种组合覆盖 Time-X/Custom-X、单/多通道、full/mini：

- enabled value 字段严格按 Min、Max、Avg 排序；disabled 字段不存在；
- point-only bit 变化不改变展示模型、HTML、layout category；
- Time-X 保留 `Δ`；Custom-X 保留 branch；全关不产生 blank/orphan；
- mini tooltip 保留所有 enabled metrics、diagnostics 和 source-qualified identity；
- duplicate display labels 仍输出两个 composite entries。

再写代表性 Qt 几何红测：

- natural horizontal layout；
- constrained stacked layout width `<= parent.width() - 16`；
- constrained height 只截断 whole channel blocks，带 `+N channels`；
- single custom-X full/mini；
- settings popover 与 pill 保持 8 px gap，关闭后 anchor 无漂移；
- user-moved pill 在内容变化后保持 top/right 并 clamp；
- settings button 在游标控件旁，响应式压缩不丢失。

先运行并确认红：

```powershell
& 'D:\Coding project\data analyzer\.venv\Scripts\python.exe' -m pytest tests/ui/test_cursor_display_settings.py tests/ui/test_cursor_pill_formatting.py tests/ui/test_plot_helpers.py tests/ui/test_chart_stack.py -q
```

### 4.2 GREEN：展示值对象、popover 与布局

实现：

- `CursorDisplayOptions` 与唯一 QSettings key map；对缺失/非法值回退默认 `True`；
- 纯 presentation DTO/builder，区分 full/mini、natural/constrained、visible/tooltip rows；
- 五项 switch popover，point 与 value 视觉分组；single mode 显示“双游标统计”说明；
- TimeChartCard 的小设置按钮、popover 生命周期和 signal；
- CursorPill 的 safe-rectangle、stacked fallback、whole-block truncation、tooltip、collision/restore；
- 兼容旧 formatter/signals，不移除当前公开 helper/import。

QSS 使用现有 token/控件风格；不得新增 border shorthand 与 radius 冲突，不用 `.connect(lambda ...)`。

### 4.3 REFACTOR 与验证

```powershell
& 'D:\Coding project\data analyzer\.venv\Scripts\python.exe' -m pytest tests/ui/test_cursor_display_settings.py tests/ui/test_cursor_pill_formatting.py tests/ui/test_plot_helpers.py tests/ui/test_chart_stack.py -q
& 'D:\Coding project\data analyzer\.venv\Scripts\python.exe' -m pytest tests/ui_kit/test_qss_border_shorthand.py tests/ui/test_no_lambda_signal_connections.py -q
git diff --check
```

提交：`feat(ui): add cursor display controls and adaptive result layout`

## Task 3 — 实时游标、marker、分屏同步与帮助接线

**Agent：** PyQt UI engineer
**Owner files：**

- `mf4_analyzer/ui/pg_canvas/cursor.py`
- `mf4_analyzer/ui/pg_canvas/canvas.py` 及实际 backref 声明文件
- `mf4_analyzer/ui/chart_stack/stack.py`
- `mf4_analyzer/ui/hints.py`
- `mf4_analyzer/ui/quickref.py`
- `tests/ui/test_custom_x_cursor_contract.py`
- `tests/ui/test_pg_timedomain_canvas.py`
- `tests/ui/test_chart_stack.py` 中现有 split-pane owner 区域
- `tests/ui/test_pg_canvas_backref_invariants.py`
- 对应 hints/quickref 测试

**不改：** Task 1 数值算法、Task 2 控件内部实现、MainWindow/project schema。

### 5.1 RED：实时契约测试

先增加失败测试：

- custom-X single 通过结构化 result 输出当前 `X↑`、`X↓`，且不含 Min/Max/Avg/Delta；
- time single 兼容输出不变；
- five options 默认全开、QSettings round-trip、非法旧值回退；
- value toggles 只改变 dual rows；marker toggles 只改变 scatter data；
- min 为绿色圆、max 为红色菱形；
- coaxis members 各自保留；相同 display name 的两个来源不会互相隐藏；
- 两个 split panes 同步设置但结果互不混合；新 pane 首帧使用当前 snapshot；
- off/clear/teardown 关闭 popover、清 transient marker/result，但不重置偏好；
- backref owned/delegate declarations 完整；hints 与 quickref 都出现新交互。

先运行新增/修改测试并确认红：

```powershell
& 'D:\Coding project\data analyzer\.venv\Scripts\python.exe' -m pytest tests/ui/test_custom_x_cursor_contract.py tests/ui/test_pg_timedomain_canvas.py tests/ui/test_chart_stack.py tests/ui/test_pg_canvas_backref_invariants.py -q
```

### 5.2 GREEN：接线与 identity 修复

- 单游标 custom-X 调用 Task 1 sampler，并发出 source-qualified structured rows；保留旧 `cursor_info` 兼容信号。
- dual formatter 接收 immutable options，过滤 value columns。
- extrema scatter data 按 `show_min_point`/`show_max_point` 过滤并使用规定 shape/color。
- 把 `_hidden_channel_names()` 的 display-name 过滤改成 composite-key 过滤；不通过 `dict(...)` 或展示键转换 `_ChannelKeyDict`。
- ChartStack 加载/保存 QSettings，向所有 card/canvas/pill 广播 snapshot；split pane 只共享设置，不共享结果。
- 所有 pill 变化经 `_update_pill_content()`；popup collision 只调用 Task 2 的布局 API。
- 同步 hints/quickref 文案。

### 5.3 REFACTOR、focused gates 与提交

```powershell
& 'D:\Coding project\data analyzer\.venv\Scripts\python.exe' -m pytest tests/test_custom_x_paths.py tests/ui/test_custom_x_cursor_contract.py tests/ui/test_plot_helpers.py tests/ui/test_cursor_pill_formatting.py tests/ui/test_cursor_display_settings.py tests/ui/test_chart_stack.py tests/ui/test_pg_timedomain_canvas.py tests/ui/test_pg_canvas_backref_invariants.py -q
& 'D:\Coding project\data analyzer\.venv\Scripts\python.exe' -m pytest tests/ui/test_import_boundaries.py tests/test_signal_no_gui_import.py tests/ui/test_main_window_state_ownership.py tests/ui_kit/test_qss_border_shorthand.py tests/ui/test_no_lambda_signal_connections.py -q
git diff --check
```

提交：`feat(ui): integrate cursor settings with live panes`

## Task 4 — 协调者集成、渲染与验收

**Owner：** 主协调者。实现 agent 不运行全套。

### 6.1 稳定快照与代码审查

1. 确认三个 task commit 均在当前 feature branch，worktree 仅保留 `.state` 证据。
2. 独立 final reviewer 对规格逐条审查 diff、测试及报告；重大项回派原 implementer 修复并重新 review。
3. 记录验证前后 `HEAD` 与 `git status --short`；若相关文件在 gate 期间变化，结果标为 `UNVERIFIED` 并重跑相应 focused gate。

### 6.2 确定性渲染证据

使用实际 TimeChartCard/CursorPill 路径生成 `.state/cursor-display-settings/` 下的 PNG 与 JSON geometry evidence，至少包含：

- 720 px normal/full/all-on；
- 360 px constrained/full/selected subset；
- constrained height/many channels/`+N channels`；
- custom-X single `X↑/X↓`；
- dual split + popover collision；
- duplicate display name/full tooltip。

自动断言每个 widget 落在 safe rectangle、popover 与 pill 不相交、无空单元格；主协调者再逐张检查像素。随后在 Windows 前台启动同一真实 widget probe，验证字体、点击、popover、拖动与切换无明显抖动；记录为 `.state` 非 Git 证据。

### 6.3 最终 gates

先运行全部 focused owner tests，再运行边界门禁：

```powershell
& 'D:\Coding project\data analyzer\.venv\Scripts\python.exe' -m pytest tests/test_custom_x_paths.py tests/ui/test_custom_x_cursor_contract.py tests/ui/test_plot_helpers.py tests/ui/test_cursor_pill_formatting.py tests/ui/test_cursor_display_settings.py tests/ui/test_chart_stack.py tests/ui/test_pg_timedomain_canvas.py -q
& 'D:\Coding project\data analyzer\.venv\Scripts\python.exe' -m pytest tests/ui/test_pg_canvas_backref_invariants.py tests/ui/test_import_boundaries.py tests/test_signal_no_gui_import.py tests/ui/test_main_window_state_ownership.py tests/ui_kit/test_qss_border_shorthand.py tests/ui/test_no_lambda_signal_connections.py -q
git diff --check
```

本轮不是 release、merge acceptance 或跨边界大重构，不默认运行完整 pytest；如 final review 发现跨模块污染或 order/teardown 风险，再由主协调者按 AGENTS.md 规则运行唯一一次稳定快照 full gate。

### 6.4 文档与 lesson 收口

- 对规格逐项勾选 `.state/cursor-display-settings-checklist.md`。
- `rg -n "TO[D]O|TB[D]|FIXM[E]|待[定]|稍[后]"` 扫描本轮 spec/plan/代码新增区域。
- `rg -n "cursor display|游标显示|最大点|最小点" mf4_analyzer/ui/hints.py mf4_analyzer/ui/quickref.py` 证明双文档同步。
- 运行 `scripts/lessons/check.py --status`；只有形成可复用的新 failure pattern 时才记录并 promote lesson。
- 最终文档提交：`docs(ui): document cursor display settings`

## 完成定义

- Task 1–3 每项都有 RED 证据、focused pass、commit、implementer report 和独立 review pass。
- 规格 §12 的五条 acceptance criteria 全部有对应自动化或明确的 Windows 前台证据。
- 五个 setting 的 32 组合在 pure presentation layer 全覆盖；Qt 层覆盖等价类，不以肉眼替代 geometry assertion。
- 单游标无统计、custom-X 当前分支值、dual 过滤、marker、split、identity、popover collision、宽高 fallback 均通过。
- 没有扩大 MainWindow state、破坏 import boundary、引入未声明 backref、修改 project schema 或碰触无关 dirty files。

## 实施结果

- Task 1–3 均按 RED → GREEN 实施并通过独立 task review；Task 2、Task 3 各有一轮 review fix，整分支 final review 的一轮 fix 也已通过 scoped re-review。
- 稳定代码快照 `a3ce6edd` 上，`test_chart_stack.py` 为 141 passed；核心数值/展示/格式化组为 222 passed、1 skipped；游标与 paint/backstop 聚焦节点为 36 passed；边界与帮助门禁为 97 passed。
- `test_pg_timedomain_canvas.py` 全文件曾出现 2 个与本改动无关的环境/顺序型失败；两个节点在最终稳定快照独立复跑为 2 passed，不将先前 partial/full-file 结果误记为全绿。
- 六个确定性布局场景和 Windows 前台诊断/单向分支场景的非 Git 证据保存在 `.state/cursor-display-settings-final/`；几何 JSON 证明 safe bounds、popover 不相交、无空单元格与 whole-block 截断。
- 完整 pytest 未运行：本轮不是 release/merge acceptance 或跨边界大重构，按仓库门禁只运行 owner tests、paint backstop 与相关边界 ratchets。
