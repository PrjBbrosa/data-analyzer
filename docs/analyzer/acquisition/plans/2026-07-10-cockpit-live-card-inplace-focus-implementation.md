# Cockpit 实时卡片就地 Focus — Implementation Plan

Date: 2026-07-10  
Spec: `docs/analyzer/acquisition/specs/2026-07-10-cockpit-live-card-inplace-focus-spec.md`  
Interaction reference: `docs/analyzer/acquisition/reports/2026-07-10-live-monitoring-interaction-model.html`

## Goal

将 Cockpit 当前“单击后只剩目标卡 + 独立 focus bar”的行为，替换为有限笔记本
视口内的就地 Focus：同一张卡、同一个 Sparkline 扩高到 scroll viewport 的 78%
（硬上限 80%），上下卡保留弱上下文，且不复制曲线或样本数据。

## Global Constraints

- 本计划只改显示层：不得触碰 controller、writer、ring、采集状态机、threshold band、
  `SessionConfig` 或 pin 计算。
- 命令全部前台运行，使用
  `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest ...`。
- 不新增依赖；不使用 `QGraphicsBlurEffect`；最多对 4 张 context 卡使用可移除的
  opacity 效果或等价轻量视觉弱化。
- 不引入第二个 `Sparkline`、第二个 raw deque、第二个 display bucket 或第二个统计循环。
- Cockpit 才启用 `inplace`；Replay 保持默认 `isolated`。
- 既有 objectName 全部保留；`liveFocusShell`、`liveFocusBar`、`liveFocusBackButton`
  继续供 Replay 的 `isolated` 路径使用。新增 objectName 只用于可测的内联 controls。
- 每个任务先写失败测试、确认失败、实现、跑绿；执行时每任务单独 commit，除非用户
  另行指示。

## Task 1 — 写入就地 Focus 的失败测试与旧行为回归边界

**Files**

- Modify: `tests/acquisition_ui/test_live_cards.py`
- Modify: `tests/acquisition_ui/test_pinned_monitoring.py`

**Step 1: 新增 Cockpit 就地 Focus 断言**

建立 `LiveCardGrid` 的 `inplace` fixture（中间卡为 `StrWhlTrq`），在 `600×420`
或相近固定几何下断言：

```python
grid.set_focus_presentation("inplace")
grid.set_signals(signals)
qtbot.mouseClick(grid.cards["StrWhlTrq"], Qt.LeftButton)

assert list(grid.cards) == [name for name, *_ in signals]
assert grid.focused_channel == "StrWhlTrq"
assert len(grid.cards["StrWhlTrq"].findChildren(Sparkline)) == 1
shell = grid.findChild(QWidget, "liveFocusShell")
assert shell is not None and shell.isHidden()
```

再断言 layout 稳定后：

- 目标卡高度 `<= floor(0.80 * scroll.viewport().height())` 且约为 78%；
- 目标前后卡的 geometry 与 viewport 有至少 24px 的可见交集；
- 前后卡的 `focusState == "context"`，目标为 `"active"`；
- 收起后卡序、原 card object identity、每个 `Sparkline` object identity 与进入前一致，
  vertical scrollbar 回到进入前位置。

新增控制矩阵：`上一/下一` 循环当前五张卡、Esc 收起、Focus 中 `push_sample` 后所有
卡的样本数继续增长。扩展 `test_pinned_monitoring.py`：idle→recording 时有 Focus 的
center width 仍不变，pin 操作不重启 backend。

**Step 2: 固定 Replay 旧行为**

把现有 `test_single_click_focuses_card_and_back_restores_all` 重命名或拆分为
`test_isolated_focus_remains_default_for_replay_grid`，继续断言 default/Replay 只显示
目标卡和旧返回行为，防止全局切换误伤回放。

**Step 3: 确认失败**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui/test_live_cards.py tests/acquisition_ui/test_pinned_monitoring.py -q \
  -k 'inplace or isolated_focus or focus'
```

Expected: FAIL。当前代码会删掉 sibling cards、显示 `liveFocusShell`，且没有
presentation mode / geometry / context state。

## Task 2 — `LiveSignalCard` 只扩同一条曲线并内联控制

**Files**

- Modify: `mf4_analyzer/acquisition_ui/widgets/live_cards.py`
- Modify: `mf4_analyzer/ui_kit/style.qss`
- Test: Task 1 tests

**Step 1: 卡片状态 API**

在 `LiveSignalCard` 引入受控的 `set_focus_state("normal" | "context" | "active")`：

- 仅设置动态 property、header 的 stats 可见性、`Sparkline` 的 size policy 和内联 controls；
- `active` 隐藏 stats，controls 放进**既有 header 行**，不新加 title/toolbar 行；
- 不创建第二个 `Sparkline`，不复制/重置 `_spark._buffer`；
- `context` 不改变 sample ingest 或 repaint，只留下轻量视觉弱化钩子。

内联控件 objectName：`liveFocusPreviousButton`、`liveFocusNextButton`、
`liveFocusCollapseButton`。它们发 grid 可消费的 signals，不直接操纵采集状态。

**Step 2: 样式**

- 新规则以 `QFrame#liveSignalCard[focusState="active"]` /
  `[focusState="context"]` 为边界；active 的边框可强调，context 降对比度。
- 保留 `liveFocusShell`、`liveFocusBar`、`liveFocusBackButton` 的 QSS，供 Replay 的
  isolated 路径使用；Cockpit inplace 路径只保证 shell 隐藏且不占高度。
- 用 opacity effect 或等价属性弱化 context；不使用 blur effect，不改变 active
  曲线颜色/recording 语义。

**Step 3: 跑绿**

运行 Task 1 选择器；再运行

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui/test_live_cards.py -q
```

## Task 3 — `LiveCardGrid` presentation mode、视口预算与滚动恢复

**Files**

- Modify: `mf4_analyzer/acquisition_ui/widgets/live_cards.py`
- Modify: `mf4_analyzer/acquisition_ui/main_window/_toolbar_mixin.py`
- Test: Task 1 tests

**Step 1: Presentation 分流**

- `LiveCardGrid` 默认 `isolated`，维持现有 `_visible_signals()` 过滤与 Replay 行为。
- 新 `set_focus_presentation("inplace")` 仅由 Cockpit `_center` 调用。
- inplace 的 `_visible_signals()` 始终返回全部 `_all_signals`；focus 只改变 card state，
  不重建为一张卡，不清 cache，不改变 `_cards` 顺序。
- Cockpit inplace 路径让 focus shell 隐藏且不占高度；isolated 路径仍显示原 shell，
  以维持 Replay 行为。

**Step 2: 几何与滚动**

新增私有、布局稳定后执行的 `_apply_inplace_focus_geometry()`：

1. 读取 scroll viewport 高度；计算 `focus_h = floor(0.78 * viewport_h)`，并
   断言/钳制不超过 80%。
2. active card 固定到 `focus_h`；normal/context 卡回到原有 expanding policy。
3. 保存进入 Focus 前 scrollbar value；使目标卡中心进入 viewport。中间目标必须同时
   露出相邻上下卡；首尾仅露出实际邻侧。
4. 收起时清 focus properties/opacity effect，恢复原 scroll value；不重建 card/buffer。

用 `QTimer.singleShot(0, ...)` 或等价的 layout-settled 单次调度；不能在
`refresh_all()`/每个 `push_sample()` 中改尺寸。

**Step 3: 导航与状态变化**

- 上一/下一按 `_all_signals` 当前顺序循环；Esc 等价收起。
- `set_signals()` 若移除目标则清 Focus 并恢复普通布局；保持现有“同名卡 buffer 保留”
  契约。
- recording 切换、pin/unpin/reset 都不启动 backend 或改变 splitter 宽度。

**Step 4: 跑绿**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui/test_live_cards.py tests/acquisition_ui/test_pinned_monitoring.py -q
```

## Task 4 — Tour 几何证据与 macOS 视觉验收

**Files**

- Modify: `scripts/cockpit_ui_tour.py`
- Modify: `tests/acquisition_ui/test_visual_shell.py`（仅当 objectName/geometry 断言已有对应覆盖）

**Step 1: 重写 F12 断言**

替换当前“only focused card visible / focus bar visible”断言：

- `focused_channel == "StrWhlTrq"`；五张实时卡仍在；
- 仅目标 card `focusState == "active"`，其余为 `context`；
- 目标卡高 `<= 80% viewport`，中间目标上下均有实际可见 sibling band；
- 目标 card 内只存在一个 `liveCardSparkline`；Cockpit focus shell 存在但隐藏、不占高度；
- 点击内联“收起”后恢复五张卡与卡序。

截图名替换为 `03c-inplace-focus-card`；不要复用旧 “focused-card” 截图作为新证据。

**Step 2: Offscreen 结构门**

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python \
  scripts/cockpit_ui_tour.py --assert --shots /tmp/cockpit-inplace-focus-offscreen
```

**Step 3: macOS on-screen 门（最终视觉真值）**

```bash
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python \
  scripts/cockpit_ui_tour.py --assert --onscreen --shots /tmp/cockpit-inplace-focus-onscreen
```

逐项目视：没有重复曲线、没有额外 Focus 标题区、目标卡占约 78% 而非整块视口、
上下 sibling 仍存在但退后、960px 窄宽 name/value 仍可读、录制态红色语义正确。

## Task 5 — 完整 focused 回归与文档收口

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui/test_live_cards.py \
  tests/acquisition_ui/test_pinned_monitoring.py \
  tests/acquisition_ui/test_replay_tab.py \
  tests/acquisition_ui/test_visual_shell.py -q
git diff --check
```

完成后在 spec/plan 记录实际 stdout、on-screen 截图位置和任何未验证边界；若 Replay
隔离模式或 960px 视觉未通过，不得将此批次表述为完整交付。

### Execution record (2026-07-10)

Completed. The initial in-place test failed as expected before implementation
with `AttributeError: 'LiveCardGrid' object has no attribute
'set_focus_presentation'`.

Actual validation stdout:

```text
56 passed in 1.18s
71 passed in 1.67s
[tour] all invariants passed  # offscreen
[tour] all invariants passed  # macOS on-screen
```

Commands run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui/test_live_cards.py tests/acquisition_ui/test_pinned_monitoring.py -q
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/acquisition_ui/test_live_cards.py tests/acquisition_ui/test_pinned_monitoring.py \
  tests/acquisition_ui/test_replay_tab.py tests/acquisition_ui/test_visual_shell.py -q
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python \
  scripts/cockpit_ui_tour.py --assert --shots /tmp/cockpit-inplace-focus-offscreen
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python scripts/cockpit_ui_tour.py --assert \
  --onscreen --shots /tmp/cockpit-inplace-focus-onscreen
```

Rendered evidence is at
`/tmp/cockpit-inplace-focus-offscreen/03c-inplace-focus-card.png` and
`/tmp/cockpit-inplace-focus-onscreen/03c-inplace-focus-card.png`. The
on-screen tour exercised the FAKE demo backend; no physical ECU transport
claim is made by this display-only delivery.

Follow-up implemented: the sole Focus `Sparkline` now raises its visual grid
density from compact/context `4×4` to `10×10`, with a focused structural test
and F12 tour assertion. It changes paint-only guide lines, not the data scale,
trace, buffers, sample refresh, or any TimeDomain global setting.
