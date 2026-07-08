# Cockpit 实时监控 UX Phase 1+2 — Implementation Plan

> **For agentic workers (Codex):** 按任务顺序执行，checkbox 跟踪进度。每个任务
> 自带测试闭环：先写失败测试 → 实现 → 跑绿 → commit。不要跨任务合并 commit。
> 全程不要 `run_in_background` 跑全量 pytest（TCC 教训）；用前台命令。

Date: 2026-07-08
Spec: `docs/analyzer/acquisition/specs/2026-07-08-cockpit-monitoring-phase12-spec.md`

**Goal:** Phase 1 可读性收口（卡片信号身份 G1 / 录制文案中文化 G2 / 输出路径
紧凑显示 G3 / 复盘弹窗层级 G4）+ Phase 2 固定实时显示（选择顺序 G5 / pin 模型
G6），tour 验收门同步扩展。

**Architecture:** 全部 UI 显示层。G1 用中段省略 label + 卡宽阈值折叠 stats；
G5 在 LeftPane 加自愈式点选顺序；G6 在窗口层加 pin 模型（`_manual_pins` +
`_effective_pinned_names`），中央刷新收口为 `_refresh_center_cards`，
`LiveCardGrid` 加计数条与卡片右键菜单（ReplayTab 不启用，零变化）。录制/预检/
复盘继续吃完整选择，数据通路不动（未 pin 通道的样本本就被
`LiveCardGrid.push_sample` 静默忽略）。

**Tech Stack:** PyQt5 + pytest-qt（offscreen）。无新依赖。

## Global Constraints

- 命令一律用 `.venv/bin/python`；pytest 全部前台跑。
- 既有 objectName 全部保留；新增 objectName：`reviewTitle`、`reviewFileName`、
  `reviewFacts`、`liveMonitorSummary`。
- QSS 只加通用 `[role="destructive"]` 与新 objectName 规则，不写特例覆盖既有 token。
- `ui_kit` 不得 import `ui.*` / `acquisition_ui.*`（反向 import ui_kit 允许，现状已有）。
- 录制契约不动：`_build_session_config` / `expected_channels` / review 流继续用
  `current_selection()` 完整选择。
- pin 操作不得触发 `_idle_restart_timer` / `backend.start`（纯显示层）。
- 选中 ≤ 5 且未定制 pin 时，中央行为与现状一致（无计数条、全部显示）。
- 文案含中文的文件 IO 显式 `encoding="utf-8"`。

---

### Task 1: G2 — 录制质量面板 + 状态栏中文化

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/widgets/right_panel.py`（RecordingQualityPage 标题）
- Modify: `mf4_analyzer/acquisition_ui/main_window/_settings_mixin.py`（`_update_status_bar`）
- Test: `tests/acquisition_ui/test_status_bar_text.py:34,45`（更新）、
  `tests/acquisition_ui/test_right_panel.py`（追加）

- [ ] **Step 1: 更新/新增测试**

`test_status_bar_text.py` 两处期望串改为：

```python
        assert window.statusBar().currentMessage() == "实时流 · 0 evt/s"
```

```python
            "录制中 · 00:00 · 0 样本 · 缓冲中 · 丢帧 0 · 缓冲 0.0%"
```

（同文件如有其他断言含 `streaming`/`RECORDING`，一并按同格式更新。）

`test_right_panel.py` 追加：

```python
def test_recording_page_titles_are_localized(qtbot):
    page = RecordingQualityPage()
    qtbot.addWidget(page)
    titles = [lab.text() for lab in page.findChildren(QLabel, "rightMetricTitle")]
    assert titles == ["缓冲占用", "写入速率", "丢帧", "CAN 总线负载", "最近帧延迟", "磁盘剩余"]
```

- [ ] **Step 2: 确认失败**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_status_bar_text.py tests/acquisition_ui/test_right_panel.py -v -k "localized or status"`
Expected: FAIL（旧英文标题/文案）。

- [ ] **Step 3: 实现**

`right_panel.py` `RecordingQualityPage.__init__` 六行标题替换：

```python
        self._row_ring = _add_metric_section(self._outer, self, "缓冲占用")
        self._row_write = _add_metric_section(self._outer, self, "写入速率")
        self._row_dropped = _add_metric_section(self._outer, self, "丢帧")
        self._row_can = _add_metric_section(self._outer, self, "CAN 总线负载")
        self._row_rx_age = _add_metric_section(self._outer, self, "最近帧延迟")
        self._row_disk = _add_metric_section(self._outer, self, "磁盘剩余")
```

`_settings_mixin._update_status_bar` 两个分支替换：

```python
        if state == CockpitState.CONNECTED_IDLE:
            self._status.showMessage(
                f"实时流 · {self._event_rate_per_s()} evt/s"
            )
            return
        if state == CockpitState.RECORDING:
            elapsed = self._recording_elapsed_text()
            size_mb = self._recording_file_size_mb()
            size_part = f"{size_mb:.1f} MB" if size_mb > 0 else "缓冲中"
            self._status.showMessage(
                f"录制中 · {elapsed} · {self._sample_count()} 样本 · "
                f"{size_part} · "
                f"丢帧 {self._cumulative_dropped} · 缓冲 {self._ring.level_pct:.1f}%"
            )
```

- [ ] **Step 4: 跑绿**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_status_bar_text.py tests/acquisition_ui/test_right_panel.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/widgets/right_panel.py mf4_analyzer/acquisition_ui/main_window/_settings_mixin.py tests/
git commit -m "feat(acquisition): localize recording quality panel and status bar copy"
```

---

### Task 2: G1 — 卡片信号身份（中段省略 + stats 折叠）

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/widgets/live_cards.py`
- Test: `tests/acquisition_ui/test_live_cards.py`（追加）

**Interfaces:**
- Produces: `live_cards._ElidedLabel`（`full_text()` / `visible_text()`）、
  模块常量 `_STATS_COLLAPSE_MIN_CARD_W = 430`。

- [ ] **Step 1: 写失败测试**

```python
def test_narrow_card_keeps_identity_and_value(qtbot):
    """spec 2026-07-08 §G1: 窄卡 stats 先让位，名称省略但可见。"""
    card = LiveSignalCard(
        "Rte_StrWhlTrqSnsrCalib_StrWhlTrqRawFiltered", unit="Nm", raster="event_1ms"
    )
    qtbot.addWidget(card)
    card.resize(360, 120)
    card.show()
    qtbot.waitExposed(card)
    assert card._stats_label.isHidden()
    shown = card._name_label.visible_text()
    assert "…" in shown
    assert shown.startswith("Rte_")
    assert not card._value_label.isHidden()
    card.resize(600, 120)
    assert not card._stats_label.isHidden()


def test_card_name_tooltip_is_full_name(qtbot):
    card = LiveSignalCard("MotSpd", unit="rpm")
    qtbot.addWidget(card)
    assert card._name_label.toolTip() == "MotSpd"
    assert card._name_label.full_text() == "MotSpd"
```

- [ ] **Step 2: 确认失败**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_live_cards.py -v -k "identity or tooltip_is_full"`
Expected: FAIL（`visible_text`/`full_text` 不存在，stats 不折叠）。

- [ ] **Step 3: 实现**

`live_cards.py` 模块级（`_TIME_CHANNEL_RE` 附近）新增：

```python
# Spec 2026-07-08 §G1: 卡宽低于该值时折叠 stats（显示启发式，非健康阈值，
# 不进 thresholds.py）。430 = 1280 布局永不触发、960 布局必触发。
_STATS_COLLAPSE_MIN_CARD_W = 430


class _ElidedLabel(QLabel):
    """QLabel that elides overlong text in the middle instead of clipping.

    EPS 通道名共享长前缀（Rte_…），后缀才是区分位 — ElideMiddle 保留首尾。
    QSS 字体/颜色照常生效（走 setText，不自绘）。
    """

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._full_text = text

    def full_text(self) -> str:
        return self._full_text

    def visible_text(self) -> str:
        return self.text()

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self._update_elide()

    def _update_elide(self) -> None:
        metrics = self.fontMetrics()
        super().setText(
            metrics.elidedText(self._full_text, Qt.ElideMiddle, max(16, self.width()))
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        super().resizeEvent(event)
        self._update_elide()
```

`LiveSignalCard._build_ui` 的 name label 段替换（objectName / 策略保留，
补 60px 保底与 tooltip）：

```python
        self._name_label = _ElidedLabel(self._name, self)
        self._name_label.setObjectName("liveCardName")
        self._name_label.setMinimumWidth(60)
        self._name_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._name_label.setToolTip(self._name)
```

`LiveSignalCard` 新增 resizeEvent（放 `_build_ui` 之后）：

```python
    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        """Spec 2026-07-08 §G1: 挤压时 stats 最先让位。"""
        super().resizeEvent(event)
        self._stats_label.setVisible(self.width() >= _STATS_COLLAPSE_MIN_CARD_W)
```

- [ ] **Step 4: 跑绿**

Run: `.venv/bin/python -m pytest tests/acquisition_ui/test_live_cards.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/widgets/live_cards.py tests/acquisition_ui/test_live_cards.py
git commit -m "feat(acquisition): live card keeps signal identity at narrow widths"
```

---

### Task 3: G3 — 输出路径紧凑显示 + `set_output_dir`

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/main_window/_settings_mixin.py`
- Test: `tests/acquisition_ui/test_main_window_transport_chip.py` 或新建
  `tests/acquisition_ui/test_output_dir_display.py`

**Interfaces:**
- Produces: `_settings_mixin.compact_path_display(text, max_len=32) -> str`
  （模块级纯函数）；`CockpitMainWindow.set_output_dir(path)`（tour Task 8 消费）。

- [ ] **Step 1: 写失败测试**（新文件 `test_output_dir_display.py`）

```python
"""spec 2026-07-08 §G3: 输出路径紧凑显示。"""
from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
from mf4_analyzer.acquisition_ui.main_window._settings_mixin import (
    compact_path_display,
)
from PyQt5.QtWidgets import QLabel


def test_compact_path_display_rules():
    assert compact_path_display("data/runs") == "data/runs"
    assert (
        compact_path_display("output/cockpit-ui-tour-recordings-2026-07-07/deep")
        == "output/…/deep"
    )
    assert (
        compact_path_display("/private/tmp/claude-501/very-long-session/scratch")
        == "…/very-long-session/scratch"
    )
    long_leaf = "/a/b/" + "x" * 40
    assert compact_path_display(long_leaf) == "…/" + "x" * 40


def test_set_output_dir_updates_selector_and_tooltip(qtbot):
    window = CockpitMainWindow()
    qtbot.addWidget(window)
    full = "/private/tmp/claude-501/very-long-session/recordings"
    window.set_output_dir(full)
    assert window._output_dir_label == full
    value = window._output_btn.findChild(QLabel, "cockpitSelectorValue")
    assert value.text() == "…/very-long-session/recordings"
    assert window._output_btn.toolTip() == full
    window.close()
```

- [ ] **Step 2: 确认失败** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_output_dir_display.py -v`
Expected: FAIL（函数/方法不存在）。

- [ ] **Step 3: 实现**

`_settings_mixin.py` 模块级（class 之前）新增：

```python
from pathlib import PurePath


def compact_path_display(text: str, max_len: int = 32) -> str:
    """Compact a filesystem path for the toolbar selector (spec §G3).

    纯字符串规则（不做字体度量），可单测、跨平台稳定。tooltip 始终持有全路径。
    """
    if len(text) <= max_len:
        return text
    pure = PurePath(text)
    parts = [p for p in pure.parts if p not in ("/", "\\")]
    if not parts:
        return text
    if len(parts) >= 2:
        if not pure.is_absolute() and len(parts) >= 3:
            candidate = f"{parts[0]}/…/{parts[-1]}"
        else:
            candidate = f"…/{parts[-2]}/{parts[-1]}"
        if len(candidate) <= max_len:
            return candidate
    return f"…/{parts[-1]}"
```

SettingsMixin 新增方法（`_on_pick_output_dir` 之前）：

```python
    def set_output_dir(self, path) -> None:
        """设置录制输出目录；工具栏显示紧凑形式（spec 2026-07-08 §G3）。

        ``_output_dir_label`` 保持完整路径 —— 落盘（`_next_output_path`）用它。
        """
        text = str(path)
        self._output_dir_label = text
        self._set_selector_value(
            self._output_btn, "输出", compact_path_display(text)
        )
        self._output_btn.setToolTip(text)
```

`_on_pick_output_dir` 替换为：

```python
    def _on_pick_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", "")
        if path:
            self.set_output_dir(path)
            self._status.showMessage(f"输出目录: {path}")
```

- [ ] **Step 4: 跑绿** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_output_dir_display.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/main_window/_settings_mixin.py tests/acquisition_ui/test_output_dir_display.py
git commit -m "feat(acquisition): compact output-path display with full-path tooltip"
```

---

### Task 4: G4 — 复盘弹窗信息层级 + destructive 角色

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/review_modal.py`
- Modify: `mf4_analyzer/ui_kit/style.qss`
- Test: `tests/acquisition_ui/test_review_handoff.py`（追加；若既有用例断言
  `reviewHeader` 文本，随本任务更新）

- [ ] **Step 1: 写失败测试**

```python
def test_review_modal_visual_hierarchy(qtbot, tmp_path):
    """spec 2026-07-08 §G4: 标题/事实行/次级诊断三层 + 破坏性动作隔离。"""
    modal = _make_modal(tmp_path)  # 沿用本文件既有 modal 构造 helper
    assert modal.findChild(QLabel, "reviewTitle").text() == "录制完成"
    facts = modal.findChild(QLabel, "reviewFacts").text()
    assert "时长" in facts and "接收" in facts and "丢帧" in facts
    pf = modal.findChild(QLabel, "reviewPreflight")
    assert "已选通道" in pf.text() and "rows=" not in pf.text()
    assert "rows=" in pf.toolTip()
    assert modal._btn_discard.property("role") == "destructive"
    modal.show()
    qtbot.waitExposed(modal)
    gap = modal._btn_save_only.x() - (
        modal._btn_discard.x() + modal._btn_discard.width()
    )
    assert gap > 40  # stretch 隔离破坏性动作
```

- [ ] **Step 2: 确认失败** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_review_handoff.py -v -k hierarchy`
Expected: FAIL。

- [ ] **Step 3: 实现**

`review_modal.py` `_build_ui` 的 header 段（`header = QLabel(...)` 到
`body_layout.addWidget(header)`）替换为三层：

```python
        # Header 三层（spec 2026-07-08 §G4）：标题 / 事实行 / 文件名次级。
        title = QLabel("录制完成", body)
        title.setObjectName("reviewTitle")
        body_layout.addWidget(title)

        facts = QLabel(
            f"时长 {self._ctx.summary.duration_s:.2f} s · "
            f"接收 {self._ctx.summary.rx_count} 帧 · "
            f"丢帧 {self._ctx.summary.dropped_frames}",
            body,
        )
        facts.setObjectName("reviewFacts")
        facts.setWordWrap(True)
        body_layout.addWidget(facts)

        file_line = QLabel(self._ctx.mf4_path.name, body)
        file_line.setObjectName("reviewFileName")
        file_line.setWordWrap(True)
        body_layout.addWidget(file_line)
```

诊断 label 文本与 tooltip 替换（rows= 移入 tooltip）：

```python
        pf_text_parts = [
            f"已选通道 {len(self._ctx.expected_channels)} · "
            f"缺失 {len(pf.missing_channels)} · "
            f"fs≈{pf.estimated_fs_hz:.1f} Hz",
        ]
        if pf.problems:
            pf_text_parts.append("警告: " + " | ".join(pf.problems))
        pf_label = QLabel("\n".join(pf_text_parts), body)
        pf_label.setObjectName("reviewPreflight")
        pf_label.setWordWrap(True)
        pf_label.setToolTip(
            f"rows={pf.rows} · MDF 通道总数 {len(pf.channels)}（含时间通道）"
        )
```

按钮行：丢弃按钮加 role 属性，其后插入 stretch：

```python
        self._btn_discard.setProperty("role", "destructive")
        btn_row.addWidget(self._btn_discard)
        btn_row.addStretch(1)
```

（其余四个按钮的 addWidget 顺序不变。）

`ui_kit/style.qss` 在 `[role="primary"]` 规则块之后新增：

```css
/* Destructive action role — 红字/浅红边，hover 浅红底（2026-07-08 §G4）。 */
QPushButton[role="destructive"] {
    color: #dc2626;
    border: 1px solid #fca5a5;
    background: transparent;
}
QPushButton[role="destructive"]:hover { background: #fef2f2; }
QPushButton[role="destructive"]:pressed { background: #fee2e2; }
QPushButton[role="destructive"]:disabled { color: #fca5a5; border-color: #fecaca; }
```

文件末尾追加复盘弹窗层级 token：

```css
/* Acquisition review modal hierarchy (2026-07-08 §G4). */
#reviewTitle { font-size: 15px; font-weight: 700; }
#reviewFileName, #reviewPreflight { color: #6b7280; }
```

- [ ] **Step 4: 跑绿** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_review_handoff.py tests/acquisition_ui/test_stop_flush_finalize.py -v`
Expected: 全 PASS（`grep -rn "reviewHeader" tests/` 如有旧断言，改指向
`reviewFacts`/`reviewFileName`）。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/review_modal.py mf4_analyzer/ui_kit/style.qss tests/acquisition_ui/test_review_handoff.py
git commit -m "feat(acquisition): review modal visual hierarchy with destructive discard role"
```

---

### Task 5: G5 — LeftPane 选择顺序追踪

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/widgets/left_pane.py`
- Modify: `mf4_analyzer/acquisition_ui/main_window/_connection_mixin.py:69-73`
- Test: `tests/acquisition_ui/test_left_pane.py`（追加）

**Interfaces:**
- Produces: `LeftPane.selection_order() -> list[str]`（Task 6 消费）。

- [ ] **Step 1: 写失败测试**

```python
def test_selection_order_tracks_click_order(qtbot):
    """spec 2026-07-08 §G5: 勾选顺序对外可读，重复勾选回到队尾。"""
    pane = LeftPane()
    qtbot.addWidget(pane)
    pane.set_pool(_make_pool(5))
    for name in ("Sig_02", "Sig_00", "Sig_01"):
        pane._set_measurement_selected(name, True)
    assert pane.selection_order() == ["Sig_02", "Sig_00", "Sig_01"]
    pane._set_measurement_selected("Sig_00", False)
    pane._set_measurement_selected("Sig_00", True)
    assert pane.selection_order() == ["Sig_02", "Sig_01", "Sig_00"]


def test_selection_order_self_heals_on_direct_set_mutation(qtbot):
    """旧测试路径直改 _selected_names 集合 → 顺序自愈（排序缀尾）。"""
    pane = LeftPane()
    qtbot.addWidget(pane)
    pane.set_pool(_make_pool(5))
    pane._set_measurement_selected("Sig_03", True)
    pane._selected_names.add("Sig_01")  # legacy direct mutation
    assert pane.selection_order() == ["Sig_03", "Sig_01"]


def test_selection_order_filtered_by_set_pool(qtbot):
    pane = LeftPane()
    qtbot.addWidget(pane)
    pane.set_pool(_make_pool(5))
    for name in ("Sig_04", "Sig_02"):
        pane._set_measurement_selected(name, True)
    pane.set_pool(_make_pool(3))  # Sig_04 落出池
    assert pane.selection_order() == ["Sig_02"]
```

- [ ] **Step 2: 确认失败** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_left_pane.py -v -k selection_order`
Expected: FAIL（方法不存在）。

- [ ] **Step 3: 实现**

`left_pane.py` `__init__` 状态段追加：

```python
        self._selection_order: list[str] = []
```

公共方法（`current_selection` 旁）：

```python
    def selection_order(self) -> list[str]:
        """Selected names in user-click order (spec 2026-07-08 §G5).

        自愈式：绕过 `_set_measurement_selected` 直改集合的旧路径（部分测试
        在用）追加在尾部（按名排序），保证返回值覆盖全部选中名。
        """
        ordered = [n for n in self._selection_order if n in self._selected_names]
        missing = self._selected_names.difference(ordered)
        return ordered + sorted(missing)
```

四个突变点同步维护：

`_set_measurement_selected` 的 add/remove 分支：

```python
        if selected:
            self._selected_names.add(name)
            if name not in self._selection_order:
                self._selection_order.append(name)
            ...（事件默认逻辑不动）
        else:
            self._selected_names.discard(name)
            if name in self._selection_order:
                self._selection_order.remove(name)
            self._selected_events.pop(name, None)
```

`_set_measurement_event` 的 `if select and name not in self._selected_names:`
分支内，`self._selected_names.add(name)` 之后加：

```python
            if name not in self._selection_order:
                self._selection_order.append(name)
```

`_clear_context_selection`：`self._selected_events.clear()` 之后加
`self._selection_order.clear()`。

`set_pool`：`self._selected_names = {...}` 过滤之后加：

```python
        self._selection_order = [
            n for n in self._selection_order if n in self._selected_names
        ]
```

`_connection_mixin.py` demo 自动选中（:69-73）替换为走正门：

```python
        if not selection and self._initial_pool:
            # Auto-select first measurement so the demo can start the
            # backend without a real A2L click-through.
            self._left_pane._set_measurement_selected(
                self._initial_pool[0].name, True
            )
            selection = self._left_pane.current_selection()
```

- [ ] **Step 4: 跑绿** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_left_pane.py tests/acquisition_ui/test_demo_smoke.py tests/acquisition_ui/test_capture_session.py -v`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/widgets/left_pane.py mf4_analyzer/acquisition_ui/main_window/_connection_mixin.py tests/acquisition_ui/test_left_pane.py
git commit -m "feat(acquisition): track user click order of measurement selection"
```

---

### Task 6: G6a — pin 模型 + 中央刷新收口 + 计数条

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/main_window/_defs.py`
- Modify: `mf4_analyzer/acquisition_ui/main_window/window.py`
- Modify: `mf4_analyzer/acquisition_ui/main_window/_connection_mixin.py`
- Modify: `mf4_analyzer/acquisition_ui/widgets/live_cards.py`
- Test: `tests/acquisition_ui/test_pinned_monitoring.py`（新建）

**Interfaces:**
- Consumes: Task 5 `selection_order()`。
- Produces: `CockpitMainWindow._refresh_center_cards(explicit=None)`、
  `pin_channel/unpin_channel/reset_pins`、`_effective_pinned_names()`；
  `LiveCardGrid.set_monitor_summary(text | None)`；
  `_defs.DEFAULT_LIVE_PIN_COUNT = 5`。Task 7/8 消费。

- [ ] **Step 1: 写失败测试**（新文件）

```python
"""spec 2026-07-08 §G6: 采集通道 ≠ 实时显示通道。"""
from can_logger.p0.a2l_probe import MeasurementSummary
from PyQt5.QtWidgets import QLabel

from mf4_analyzer.acquisition_capture.backends import FakeRecorderBackend
from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
from mf4_analyzer.acquisition_ui.state import CockpitState


def _pool(n=12):
    return tuple(
        MeasurementSummary(
            name=f"Sig_{i:02d}", address=0x40000000 + 4 * i, datatype="UWORD",
            unit="", conversion="", available_events=("event_10ms",),
        )
        for i in range(n)
    )


class _SpyBackend(FakeRecorderBackend):
    def __init__(self):
        super().__init__()
        self.start_calls = 0

    def start(self, selected):
        self.start_calls += 1
        super().start(selected)


def _idle_window(qtbot, backend=None, n=12):
    window = CockpitMainWindow(
        backend=backend or FakeRecorderBackend(),
        initial_pool=_pool(n),
        allow_fake_backend=True,
    )
    qtbot.addWidget(window)
    for i in range(n):
        window.left_pane._set_measurement_selected(f"Sig_{i:02d}", True)
    window._begin_connection_attempt()
    window._poll_live()
    window._poll_health()
    assert window.state_machine.state == CockpitState.CONNECTED_IDLE
    return window


def test_default_pin_caps_cards_at_five(qtbot):
    window = _idle_window(qtbot)
    assert sorted(window._center.cards) == [f"Sig_{i:02d}" for i in range(5)]
    bar = window._center._summary_bar
    assert not bar.isHidden()
    assert bar.text() == "已选 12 · 实时显示 5 · 其余通道仍会录制"
    window.close()


def test_small_selection_keeps_legacy_behavior(qtbot):
    window = _idle_window(qtbot, n=3)
    assert len(window._center.cards) == 3
    assert window._center._summary_bar.isHidden()
    window.close()


def test_unpin_pin_reset_cycle(qtbot):
    window = _idle_window(qtbot)
    window.unpin_channel("Sig_02")
    assert "Sig_02" not in window._center.cards
    assert len(window._center.cards) == 4
    window.pin_channel("Sig_07")
    assert "Sig_07" in window._center.cards
    window.reset_pins()
    assert sorted(window._center.cards) == [f"Sig_{i:02d}" for i in range(5)]
    window.close()


def test_pin_ops_do_not_restart_stream(qtbot):
    backend = _SpyBackend()
    window = _idle_window(qtbot, backend=backend)
    calls_before = backend.start_calls
    window.unpin_channel("Sig_00")
    window.pin_channel("Sig_09")
    assert backend.start_calls == calls_before
    assert not window._idle_restart_timer.isActive()
    window.close()


def test_recording_config_uses_full_selection(qtbot):
    window = _idle_window(qtbot)
    config = window._build_session_config()
    assert len(config.selected) == 12
    assert len(window._center.cards) == 5
    window.close()
```

- [ ] **Step 2: 确认失败** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_pinned_monitoring.py -v`
Expected: FAIL（API 不存在 / 卡片数 12）。

- [ ] **Step 3: 实现**

`_defs.py` 末尾追加：

```python
# Spec 2026-07-08 §G6 — 默认实时显示的固定通道数上限。
DEFAULT_LIVE_PIN_COUNT = 5
```

`live_cards.py` `LiveCardGrid.__init__`：在 `outer.addWidget(self._scroll_area)`
之前插入计数条：

```python
        # Spec 2026-07-08 §G6: 选中数 > 实时显示数时的提示条。
        self._summary_bar = QLabel(self)
        self._summary_bar.setObjectName("liveMonitorSummary")
        self._summary_bar.setVisible(False)
        outer.addWidget(self._summary_bar)
```

`LiveCardGrid` 新方法（`set_placeholder_copy` 旁）：

```python
    def set_monitor_summary(self, text: str | None) -> None:
        """显示/隐藏「已选 N · 实时显示 P」计数条（spec §G6）。"""
        if text:
            self._summary_bar.setText(text)
            self._summary_bar.setVisible(True)
        else:
            self._summary_bar.setVisible(False)
```

`ui_kit/style.qss` 末尾追加：

```css
/* Live monitor pinned-count bar (2026-07-08 §G6). */
#liveMonitorSummary { padding: 4px 12px; color: #6b7280; }
```

`window.py`：import 处从 `._defs` 增加 `DEFAULT_LIVE_PIN_COUNT`；`__init__`
core state 段追加：

```python
        # Spec 2026-07-08 §G6 — 固定实时显示。
        self._manual_pins: list[str] = []
        self._pin_customized: bool = False
```

新方法组（放 `_refresh_idle_right_panel` 之前）：

```python
    def _effective_pinned_names(self) -> list[str]:
        """有效 pin 集（spec 2026-07-08 §G6）。

        未定制 = 先勾的前 DEFAULT_LIVE_PIN_COUNT 个；已定制 = 手动名单 ∩ 当前选择。
        """
        order = self._left_pane.selection_order()
        if not self._pin_customized:
            return order[:DEFAULT_LIVE_PIN_COUNT]
        selected = set(order)
        return [n for n in self._manual_pins if n in selected]

    def _ensure_pin_customized(self) -> None:
        if not self._pin_customized:
            self._manual_pins = list(self._effective_pinned_names())
            self._pin_customized = True

    def pin_channel(self, name: str) -> None:
        self._ensure_pin_customized()
        if name not in self._manual_pins:
            self._manual_pins.append(name)
        self._refresh_center_cards()

    def unpin_channel(self, name: str) -> None:
        self._ensure_pin_customized()
        if name in self._manual_pins:
            self._manual_pins.remove(name)
        self._refresh_center_cards()

    def reset_pins(self) -> None:
        self._manual_pins = []
        self._pin_customized = False
        self._refresh_center_cards()

    def _refresh_center_cards(self, explicit=None) -> None:
        """中央卡片唯一刷新入口（spec §G6）。

        ``explicit``：demo DemoSignal 兜底路径 —— 原样显示、绕过 pin。
        pin 操作只走这里，绝不触发 `_idle_restart_timer`（纯显示层）。
        """
        if explicit is not None:
            self._center.set_signals(
                [(m.name, m.unit, m.event) for m in explicit]
            )
            self._center.set_monitor_summary(None)
            return
        selection = self._left_pane.current_selection()
        by_name = {m.name: m for m in selection}
        pinned = [n for n in self._effective_pinned_names() if n in by_name]
        self._center.set_signals(
            [(n, by_name[n].unit, by_name[n].event) for n in pinned]
        )
        total = len(selection)
        if total > len(pinned):
            self._center.set_monitor_summary(
                f"已选 {total} · 实时显示 {len(pinned)} · 其余通道仍会录制"
            )
        else:
            self._center.set_monitor_summary(None)
```

两处 set_signals 调用点替换：

`window.py` `_on_selection_changed` 的 CONNECTED_IDLE 分支：

```python
        elif self._state_machine.state == CockpitState.CONNECTED_IDLE:
            self._refresh_center_cards()
            self._refresh_idle_right_panel()
            self._idle_restart_timer.start()
```

`_connection_mixin.py` `_begin_connection_attempt` 末尾
`self._center.set_signals(...)` 替换为：

```python
        # Seed the center pane with cards（pin 模型见 spec §G6）。
        if self._left_pane.current_selection():
            self._refresh_center_cards()
        else:
            self._refresh_center_cards(explicit=selection)
```

- [ ] **Step 4: 跑绿** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_pinned_monitoring.py tests/acquisition_ui/test_capture_session.py tests/acquisition_ui/test_demo_smoke.py tests/acquisition_ui/test_state_machine.py -v`
Expected: 全 PASS（demo/state 既有用例选中 ≤5，兼容承诺生效）。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/main_window/_defs.py mf4_analyzer/acquisition_ui/main_window/window.py mf4_analyzer/acquisition_ui/main_window/_connection_mixin.py mf4_analyzer/acquisition_ui/widgets/live_cards.py mf4_analyzer/ui_kit/style.qss tests/acquisition_ui/test_pinned_monitoring.py
git commit -m "feat(acquisition): pinned live monitoring caps center cards at five by default"
```

---

### Task 7: G6b — pin/unpin 交互入口（左栏右键 + 卡片右键）

**Files:**
- Modify: `mf4_analyzer/acquisition_ui/widgets/left_pane.py`
- Modify: `mf4_analyzer/acquisition_ui/widgets/live_cards.py`
- Modify: `mf4_analyzer/acquisition_ui/main_window/_toolbar_mixin.py`
  （`_build_acquisition_page` 接线）
- Test: `tests/acquisition_ui/test_pinned_monitoring.py`（追加）、
  `tests/acquisition_ui/test_right_click_menu.py`（追加）

**Interfaces:**
- Produces: `LeftPane.set_pin_state_provider(provider)` +
  `pin_toggle_requested = pyqtSignal(str)`；
  `LiveCardGrid.set_pinning_enabled(bool)` + `unpin_requested = pyqtSignal(str)`
  + `pins_reset_requested = pyqtSignal()` + `_build_card_menu(card) -> QMenu`。

- [ ] **Step 1: 写失败测试**

`test_right_click_menu.py` 追加：

```python
def test_context_menu_offers_pin_toggle_for_selected(qtbot):
    """spec 2026-07-08 §G6: provider 存在且已选中时出 pin 开关项。"""
    pane = LeftPane()
    qtbot.addWidget(pane)
    pane.set_pool(_make_pool(3))
    pane._set_measurement_selected("Sig_00", True)
    pane.set_pin_state_provider(lambda name: name == "Sig_00")
    fired = []
    pane.pin_toggle_requested.connect(fired.append)
    menu = pane._build_context_menu([pane._pool[0]])
    labels = [a.text() for a in menu.actions()]
    assert "取消固定实时显示" in labels
    next(a for a in menu.actions() if a.text() == "取消固定实时显示").trigger()
    assert fired == ["Sig_00"]
    # 未选中的测量不出 pin 项
    menu2 = pane._build_context_menu([pane._pool[1]])
    assert all("固定" not in a.text() for a in menu2.actions())
```

`test_pinned_monitoring.py` 追加：

```python
def test_card_menu_emits_unpin_and_reset(qtbot):
    window = _idle_window(qtbot)
    card = window._center.cards["Sig_00"]
    menu = window._center._build_card_menu(card)
    labels = [a.text() for a in menu.actions()]
    assert "取消固定实时显示" in labels and "重置固定（默认前 5）" in labels
    next(a for a in menu.actions() if "取消固定" in a.text()).trigger()
    assert "Sig_00" not in window._center.cards
    remaining = next(iter(window._center.cards.values()))
    menu2 = window._center._build_card_menu(remaining)
    next(a for a in menu2.actions() if "重置固定" in a.text()).trigger()
    assert sorted(window._center.cards) == [f"Sig_{i:02d}" for i in range(5)]
    window.close()
```

- [ ] **Step 2: 确认失败** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_pinned_monitoring.py tests/acquisition_ui/test_right_click_menu.py -v -k "pin or card_menu"`
Expected: FAIL（API 不存在）。

- [ ] **Step 3: 实现**

`left_pane.py` `LeftPane`：

```python
    selection_changed = pyqtSignal()
    pin_toggle_requested = pyqtSignal(str)
```

`__init__` 追加 `self._pin_state_provider = None`；公共方法：

```python
    def set_pin_state_provider(self, provider) -> None:
        """注入「该通道当前是否已固定」查询（spec §G6）；None 关闭 pin 菜单项。"""
        self._pin_state_provider = provider
```

`_build_context_menu` 单测量分支，在 `jump.setEnabled(False)` 之后、
`return menu` 之前插入：

```python
            if (
                self._pin_state_provider is not None
                and m.name in self._selected_names
            ):
                menu.addSeparator()
                pinned = bool(self._pin_state_provider(m.name))
                pin_action = menu.addAction(
                    "取消固定实时显示" if pinned else "固定到实时显示"
                )
                pin_action.triggered.connect(
                    lambda _checked=False, name=m.name: (
                        self.pin_toggle_requested.emit(name)
                    )
                )
```

`live_cards.py` 顶部 import 追加：

```python
from PyQt5.QtWidgets import QMenu

from mf4_analyzer.ui_kit.menus import apply_rounded_menu_chrome
```

`LiveCardGrid`：

```python
    unpin_requested = pyqtSignal(str)
    pins_reset_requested = pyqtSignal()
```

（`LiveCardGrid` 现在继承 QWidget 且无信号——确认类声明处补
`from PyQt5.QtCore import pyqtSignal` 已在文件 import 里，没有则加。）

`__init__` 追加 `self._pinning_enabled = False`；方法组：

```python
    def set_pinning_enabled(self, enabled: bool) -> None:
        """启用卡片右键 pin 菜单（采集页开、回放页保持关闭）。"""
        self._pinning_enabled = bool(enabled)
        for card in self._cards.values():
            self._install_card_menu(card)

    def _install_card_menu(self, card: LiveSignalCard) -> None:
        if not self._pinning_enabled or bool(card.property("pinMenuInstalled")):
            return
        card.setProperty("pinMenuInstalled", True)
        card.setContextMenuPolicy(Qt.CustomContextMenu)
        card.customContextMenuRequested.connect(
            lambda pos, c=card: self._build_card_menu(c).exec_(c.mapToGlobal(pos))
        )

    def _build_card_menu(self, card: LiveSignalCard) -> QMenu:
        menu = apply_rounded_menu_chrome(QMenu(card))
        unpin = menu.addAction("取消固定实时显示")
        unpin.triggered.connect(
            lambda _checked=False, name=card.name: self.unpin_requested.emit(name)
        )
        reset = menu.addAction("重置固定（默认前 5）")
        reset.triggered.connect(
            lambda _checked=False: self.pins_reset_requested.emit()
        )
        return menu
```

`set_signals` 的卡片装配循环内（`self._layout.addWidget(card)` 之前）加：

```python
            self._install_card_menu(card)
```

`_toolbar_mixin.py` `_build_acquisition_page` 在 `layout.addWidget(splitter)`
之前接线：

```python
        # Pin 接线（spec 2026-07-08 §G6b）。ReplayTab 的 grid 不启用。
        self._left_pane.set_pin_state_provider(
            lambda name: name in self._effective_pinned_names()
        )
        self._left_pane.pin_toggle_requested.connect(self._on_pin_toggle)
        self._center.set_pinning_enabled(True)
        self._center.unpin_requested.connect(self.unpin_channel)
        self._center.pins_reset_requested.connect(
            lambda: self.reset_pins()
        )
```

窗口回调（`window.py`，放 `pin_channel` 旁）：

```python
    def _on_pin_toggle(self, name: str) -> None:
        if name in self._effective_pinned_names():
            self.unpin_channel(name)
        else:
            self.pin_channel(name)
```

- [ ] **Step 4: 跑绿** — Run:
`.venv/bin/python -m pytest tests/acquisition_ui/test_pinned_monitoring.py tests/acquisition_ui/test_right_click_menu.py tests/acquisition_ui/test_replay_tab.py -v`
Expected: 全 PASS（replay 不受影响）。

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/acquisition_ui/widgets/left_pane.py mf4_analyzer/acquisition_ui/widgets/live_cards.py mf4_analyzer/acquisition_ui/main_window/_toolbar_mixin.py mf4_analyzer/acquisition_ui/main_window/window.py tests/
git commit -m "feat(acquisition): pin/unpin entry points via left-pane and card context menus"
```

---

### Task 8: 验收门 — tour 扩展 + 全量回归

**Files:**
- Modify: `scripts/cockpit_ui_tour.py`

**Interfaces:**
- Consumes: Task 3 `set_output_dir`、Task 6 pin 模型、Task 1/2 文案与折叠。

- [ ] **Step 1: 修改 tour 脚本**

1. `window._output_dir_label = str(out_dir)` 替换为
   `window.set_output_dir(out_dir)`（G3 顺带修显示不同步）。
2. 在 `idle-added-check` 步骤之后插入 Phase 2 步骤：

```python
    @at(5000, "pin-default-check")
    def s_pin():
        lp = window.left_pane
        for i in range(8):
            lp._set_measurement_selected(f"EpsDiagSig_{i:02d}", True)
        window._restart_idle_stream_for_selection()
        cards = window._center.cards
        check(len(cards) == 5, f"G6 默认 5 张卡 (实测 {len(cards)})")
        bar = window._center._summary_bar
        check(
            (not bar.isHidden())
            and bar.text() == "已选 12 · 实时显示 5 · 其余通道仍会录制",
            f"G6 计数条 (实测 '{bar.text()}')",
        )
        shot(window, "03b-pinned")
```

   （后续 `record` 及之后的步骤时间戳整体 +600ms，保持间隔。）
3. `recording-check` 追加状态栏断言（G2）：

```python
        msg = window._status.currentMessage()
        check(msg.startswith("录制中") and "丢帧" in msg and "RECORDING" not in msg,
              f"G2 状态栏中文 (实测 '{msg}')")
```

4. `review-check` 追加（G6 录制完整选择）。**必须插在 `modal.reject()` 之前**
   ——`_on_review_modal_closed` 会把 `_last_stop_result` 置 None：

```python
        result = window.last_stop_result
        check(result is not None and len(result.selected_measurement_names) == 12,
              "G6 录制含全部 12 通道")
```

5. `narrow-check` 追加（G1）：

```python
        for name, card in window._center.cards.items():
            check(card._stats_label.isHidden(), f"G1 {name} stats 已折叠")
            check(bool(card._name_label.visible_text()), f"G1 {name} 名称可见")
```

- [ ] **Step 2: 跑验收门**

Run: `.venv/bin/python scripts/cockpit_ui_tour.py --assert`
Expected: `[tour] all invariants passed`，exit 0。

- [ ] **Step 3: 全量回归**

Run: `.venv/bin/python -m pytest tests/ -q`（前台）
Expected: 0 新增失败（基线已知：`test_cache_key_dataclass_binding`
manual_rpm 漂移属 manual-order-rpm 线；`test_vector_backend…off_windows`
顺序依赖 flake、单跑过——两者非本波责任）。

- [ ] **Step 4: Commit**

```bash
git add scripts/cockpit_ui_tour.py
git commit -m "test(acquisition): tour asserts pinned monitoring and phase-1 readability invariants"
```

---

## Self-Review 核对表（写完后已过一遍）

- Spec 覆盖：G1→T2、G2→T1、G3→T3、G4→T4、G5→T5、G6→T6+T7、验收门→T8。
- 类型/命名一致：`selection_order()`（T5 定义，T6 `_effective_pinned_names`
  消费）；`set_monitor_summary`/`_summary_bar`（T6 定义，T8 断言）；
  `set_output_dir`（T3 定义，T8 消费）；`_ElidedLabel.visible_text()`
  （T2 定义，T8 narrow 断言）；`_build_card_menu`（T7 定义与测试同名）。
- 兼容点：选中 ≤5 未定制 → 与现状一致（T6 `test_small_selection_keeps_legacy_behavior`
  显式守卫）；DemoSignal 兜底走 `explicit` 参数（T6 connection mixin 分支）；
  ReplayTab 不 setPinningEnabled、不 set_monitor_summary → 回放零变化
  （T7 Step 4 跑 test_replay_tab 守卫）。
- 已知联动：T1 改状态栏文案再次触碰 `test_status_bar_text.py:34,45`
  （上一波刚改过——本任务给了新期望串）；T4 若 tests 有 `reviewHeader`
  断言按步骤内 grep 指引更新。
