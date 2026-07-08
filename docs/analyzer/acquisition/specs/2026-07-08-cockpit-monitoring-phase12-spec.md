# Cockpit 实时监控 UX Phase 1+2 Spec（可读性/本地化 + 固定实时显示）

Date: 2026-07-08
Status: Approved for implementation
Plan: `docs/analyzer/acquisition/plans/2026-07-08-cockpit-monitoring-phase12-implementation.md`
Source report: `docs/analyzer/acquisition/reports/2026-07-08-cockpit-live-monitoring-ux-plan-report.md`
Parent spec: `docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md`
（本 spec 只做增量；四态状态机 / 录制契约 / Health-Preflight-Persistence 契约不动。）

## 背景与报告采信结论

UX 报告经代码核对后采信，本 spec 实现其 Phase 1 + Phase 2（报告自己建议的
下一步范围）。两处修正：

- 报告 Current State 称窄窗「avoids clipping the current value」——只对了一半：
  `liveCardValue` 确有 `setMinimumWidth(72)` 保护，但 name/stats 是
  `QSizePolicy.Ignored + minimumWidth(0)`（`live_cards.py:257-267`），窄窗下
  **无省略号地被硬裁到 0**，真实 EPS 通道名（`Rte_…` 20-40 字符）身份丢失
  ——报告 P1-1 的结论成立，Current State 那句偏乐观。
- 报告 Phase 2 计数文案「已采集 18」在未录制时用词不对，改为「已选」。

Phase 3（Focus View）、Phase 4（Overlay）、Phase 5（真实性能证据）不在本波，
后续单独立 spec。

## 目标

- **Phase 1（G1-G4）**：不改行为的可读性收口——卡片信号身份永不丢失、录制
  监控/状态栏全中文、输出路径紧凑可读、复盘弹窗信息层级 + 破坏性动作视觉隔离。
- **Phase 2（G5-G6）**：采集通道 ≠ 实时显示通道——引入「固定（pin）」模型，
  默认最多 5 张实时卡片，其余通道照常录制；计数条明示差值。
- 验收门：`scripts/cockpit_ui_tour.py --assert` 扩展 Phase 1/2 不变量。

## 非目标（明确不做）

- Focus View（双击放大、滚轮缩放、游标读数）、Overlay 模式、1ms×10ch 性能
  实测——报告 Phase 3-5，后续波次。
- 健康条 chip 值/tooltip 的英文（`ready`/`no evidence yet`/`N off` 汇总）——
  与 probe 证据串联动，单独处理。
- pin 状态持久化到 `acquisition_config.yaml`（本波会话级；持久化随 Phase 3 波）。
- 卡片拖拽排序。
- 回放 tab 的 pin（`ReplayTab` 的 `LiveCardGrid` 不启用 pin，行为不变）。

## 契约

### G1 卡片信号身份（报告 P1-1）

**不变量：任何宽度下，卡片必须可辨识信号名与当前值；挤压时 stats 最先让位，
名称省略显示但永不消失。**

- `liveCardName` 改用中段省略（`Qt.ElideMiddle`）绘制：新 `_ElidedLabel`
  （QLabel 子类，paintEvent 用 `fontMetrics().elidedText`），
  `setMinimumWidth(60)`（名称保底可见），tooltip 保持全名（现状已有）。
  中段省略的理由：EPS 通道名共享长前缀（`Rte_…`），后缀才是区分位。
- stats（`liveCardStats`）按卡片宽度整体隐藏：卡宽 `< 430px` 时
  `setVisible(False)`（`LiveSignalCard.resizeEvent` 驱动）。阈值取 430 =
  1280 布局下永不触发、960 布局（中央 ~300px）必触发。
- `liveCardValue` 维持 `minimumWidth(72)` 不变；raster pill / unit 不动。
- 颜色仍是辅助识别（现状），不作为主标识。
- 验收：卡宽 360 → stats 隐藏、名称以省略形式可见、value 可见；卡宽 600 →
  stats 恢复。60 字符长名在 360 宽下 `_ElidedLabel` 的实际绘制文本含 `…`
  且首尾片段来自原名。

### G2 录制监控/状态栏本地化（报告 P1-2）

- `RecordingQualityPage` 行标题（`right_panel.py`）：
  `ring buffer→缓冲占用`、`dropped frames→丢帧`、`CAN load→CAN 总线负载`、
  `last frame delay→最近帧延迟`、`disk remaining→磁盘剩余`
  （`写入速率` 已中文，不动）。
- 状态栏（`_settings_mixin._update_status_bar`）：
  - RECORDING 态：`录制中 · {mm:ss} · {n} 样本 · {缓冲中|x.x MB} · 丢帧 {d} ·
    缓冲 {pct:.1f}%`
  - CONNECTED_IDLE 态：`实时流 · {n} evt/s`（单位保留拉丁）。
  - DISCONNECTED 态文案已中文，不动。
- 既有断言更新：`tests/acquisition_ui/test_status_bar_text.py:34,45`。
- 验收：两态状态栏无 `RECORDING`/`streaming`/`samples`/`drop`/`buf` 英文词；
  质量面板六行标题全中文。

### G3 输出路径紧凑显示 + 公共 setter（报告 P2-3）

- 纯函数 `compact_path_display(text: str, max_len: int = 32) -> str`
  （`_settings_mixin` 模块级）：
  - `len(text) <= max_len` → 原样；
  - 相对路径且段数 ≥ 3 → `{首段}/…/{末段}`；
  - 其余（绝对路径等）→ `…/{父段}/{末段}`；仍超长 → `…/{末段}`。
  - 只做字符串规则（不做字体度量）——可单测、跨平台稳定。
- 新公共方法 `CockpitMainWindow.set_output_dir(path: Path | str) -> None`：
  写 `_output_dir_label`（保持完整路径——录制落盘用它），selector 值显示
  `compact_path_display(...)`，tooltip = 完整路径。`_on_pick_output_dir`
  和 `scripts/cockpit_ui_tour.py` 改走此方法（顺带修掉 tour 工具栏显示
  不同步的遗留）。
- 不加宽 selector（报告明确：不抢主操作空间），宽度带维持现状。
- 验收：`compact_path_display` 四档规则单测；tour 截图中输出 selector 显示
  紧凑形式且 tooltip 为全路径。

### G4 复盘弹窗信息层级（报告 P2-4）

- Header 重构为三层：
  1. `reviewTitle`：「录制完成」（加粗标题，QSS 15px/600）；
  2. `reviewFacts`：`时长 {d:.2f} s · 接收 {rx} 帧 · 丢帧 {drop}`；
     文件名降为次级行 `reviewFileName`（灰）；
  3. `reviewPreflight` 降为次级灰：`已选通道 {N} · 缺失 {M} · fs≈{X:.1f} Hz`
     （`rows=` 与 MDF 通道总数一并移入 tooltip）。
- 按钮行重排：`[丢弃（不归档）] <stretch> [仅保存文件][保存并归档]
  [在 Analyzer 打开][关闭]`——破坏性动作左侧物理隔离。
- 丢弃按钮标 `role="destructive"`；`ui_kit/style.qss` 在 `[role="primary"]`
  块旁新增 `QPushButton[role="destructive"]`（红字 `#dc2626`、边框
  `#fca5a5`、hover 底 `#fef2f2`）。**QSS 是全局 token，规则写成通用 role，
  不写 objectName 特例**（后续别处破坏性按钮复用）。
- 既有 gating 逐字保留：保存不关窗（`2026-05-15-save-action-must-not-close`
  教训）、`在 Analyzer 打开` 的 save/archive 前置、丢弃确认框（上一波 F9）。
- 验收：title/facts/次级诊断三层存在；丢弃按钮 `property("role") ==
  "destructive"` 且位于按钮行最左、与保存组之间有 stretch；全部既有
  review 测试不回归。

### G5 选择顺序追踪（Phase 2 前置）

**不变量：`LeftPane` 对外提供「用户勾选顺序」的选中名单；直接改
`_selected_names` 集合的旧路径（测试在用）不崩、顺序自愈。**

- `LeftPane` 新增 `self._selection_order: list[str]`，在
  `_set_measurement_selected`（增/删）、`_set_measurement_event(select=True)`
  （增）、`_clear_context_selection`（清）、`set_pool`（过滤失效名）同步维护。
- 公共读取 `selection_order() -> list[str]`：自愈式——
  `[n for n in _selection_order if n in _selected_names] +
  sorted(_selected_names - set(_selection_order))`（容忍外部直改集合，如
  `test_record_backend_swap.py:87`）。
- `_connection_mixin._begin_connection_attempt` 的 demo 自动选中改走
  `self._left_pane._set_measurement_selected(name, True)`（现状直改集合 +
  `_refresh_list`，绕过顺序维护）。
- `current_selection()` 维持按名排序（录制/写盘契约不变——通道顺序与
  MF4 写入无耦合，但不引入无谓 diff）。
- 验收：勾 C→A→B 后 `selection_order() == ["C","A","B"]`；取消 A 再勾 A →
  `["C","B","A"]`；外部直改集合后 `selection_order()` 含全部选中名。

### G6 固定实时显示（pinned，报告 Phase 2）

**不变量：录制/预检/复盘永远使用完整选择；中央卡片只渲染有效 pin 集；
pin 操作纯显示层——不重启空闲流、不触碰录制会话。**

- 常量 `DEFAULT_LIVE_PIN_COUNT = 5`（`main_window/_defs.py`）。
- 窗口态：`_manual_pins: list[str]`、`_pin_customized: bool = False`。
- 有效 pin 集 `_effective_pinned_names() -> list[str]`：
  - 未定制：`selection_order()[:DEFAULT_LIVE_PIN_COUNT]`（先勾的先显示）；
  - 已定制：`[n for n in _manual_pins if n 在当前选择]`（可为空——用户
    自己清空就给空面板 + 计数条兜底）。
  - 首次定制时以当时的有效 pin 集为底（unpin 其中一张，其余四张保留）。
- 中央刷新收口为 `_refresh_center_cards(explicit=None)`：
  - `explicit` 给定（demo DemoSignal 兜底路径）→ 原样显示、绕过 pin；
  - 否则 `set_signals` 只喂有效 pin 集（metadata 取自 `current_selection()`）。
  - 计数条：`选中 > 有效 pin 数` 时
    `LiveCardGrid.set_monitor_summary(f"已选 {S} · 实时显示 {P} ·
    其余通道仍会录制")`，否则 `set_monitor_summary(None)` 隐藏。
  - 替换现有两处 `set_signals` 调用点（`_begin_connection_attempt`、
    `_on_selection_changed`）。**pin 增删只调 `_refresh_center_cards()`，
    不 start `_idle_restart_timer`**（后端选择未变）。
- `LiveCardGrid` 新增：
  - `set_monitor_summary(text: str | None)`：滚动区上方一条细计数栏
    （objectName `liveMonitorSummary`），`None` 隐藏；
  - `set_pinning_enabled(bool)` + `unpin_requested = pyqtSignal(str)` +
    `pins_reset_requested = pyqtSignal()`：启用后卡片右键菜单出
    「取消固定实时显示」「重置固定（回到默认前 5）」。ReplayTab 不启用
    （默认 False，回放行为零变化）。
- `LeftPane` 新增 pin 入口（右键菜单，单选中测量时）：
  - `set_pin_state_provider(provider: Callable[[str], bool] | None)`；
  - `pin_toggle_requested = pyqtSignal(str)`；
  - provider 存在且该测量已选中时，菜单追加
    「固定到实时显示」/「取消固定实时显示」（按 provider 判断当前态）。
- 窗口接线：pin_toggle → `pin_channel/unpin_channel`；grid.unpin →
  `unpin_channel`；grid.reset → `reset_pins`（清 `_manual_pins`、
  `_pin_customized=False`）。三个方法均以 `_refresh_center_cards()` 收尾。
- 卡片被 unpin 后 widget 销毁、缓冲丢弃；重新 pin 后从空缓冲重新累积
  （几秒内填满，接受；不做缓冲驻留）。
- 兼容承诺：**选中 ≤ 5 且未定制时行为与现状逐像素一致**（全部显示、无
  计数条）——既有测试/演示流不回归。
- 验收：
  - 勾 12 通道（连接态）→ 卡片数 == 5（先勾的 5 个）、计数条
    `已选 12 · 实时显示 5 · 其余通道仍会录制`；
  - unpin 一张 → 4 张卡 + 计数条更新；重置固定 → 回 5 张默认；
  - pin 第 6 个通道（左栏右键）→ 6 张卡；
  - 录制 → `last_stop_result.selected_measurement_names` 长度 == 12
    （录制完整选择，与显示无关）；
  - pin/unpin 期间 `backend.start` 不被再次调用（无流重启）。

### 验收门：tour 扩展

`scripts/cockpit_ui_tour.py` 增补（沿用 `--assert` 机制）：

1. 连接后追加勾选 8 个 `EpsDiagSig_*` → 断言卡片数 == 5、
   `liveMonitorSummary` 可见且文案匹配（G6）；
2. 录制→复盘后断言 `selected_measurement_names` 数 == 12（G6）；
3. 窄宽 960 步骤追加：每张卡 `_stats_label` 不可见、名称省略文本非空、
   `_value_label` 可见（G1）；
4. 状态栏断言：录制态含 `录制中` 与 `丢帧`、不含 `RECORDING`（G2）；
5. tour 改用 `window.set_output_dir(out_dir)`（G3，顺带修显示不同步）。

CI/codex 验收命令不变：`.venv/bin/python scripts/cockpit_ui_tour.py --assert`
期望 exit 0。

## 风险与兼容

- G5 顺序追踪触碰 `_selected_names` 的 31 个使用点中的 4 个突变点；其余
  只读点不动。外部直改集合的旧测试路径靠 `selection_order()` 自愈兜底。
- G6 改变「选中即显示」的既有直觉——计数条 + 左栏右键入口是发现性来源；
  ≤5 通道零变化保证平滑过渡。`push_sample` 对未 pin 通道本就静默忽略
  （`LiveCardGrid.push_sample` 查 dict miss 返回），无需改数据通路。
- G1 的 430px 阈值是显示启发式，进 `live_cards.py` 模块常量
  `_STATS_COLLAPSE_MIN_CARD_W`，不进 thresholds.py（非健康阈值）。
- G4 QSS 新增全局 `[role="destructive"]`——检查仓库现有 QPushButton 无
  该 property 撞名（当前 grep 仅 `role="primary"` 在用）。
