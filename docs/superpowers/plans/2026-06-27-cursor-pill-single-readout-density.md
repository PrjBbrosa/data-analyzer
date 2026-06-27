# 单游标读数面板密度与折叠态优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 优化 TimeDomain 单游标读数 pill：展开态更紧凑，收起态只显示彩色数值，并让 `-` / `+` 状态有清晰区别。

**Architecture:** 不改 canvas 游标计算和 HTML emission。`ChartStack` 继续接收现有单游标 HTML，并在 pill 层生成 full/mini 两套 detail；`CursorPill` 负责保存 full/mini variants、切换显示和刷新按钮状态；QSS 只负责按钮视觉差异。

**Tech Stack:** PyQt5 · QLabel rich text · QSS dynamic property · pytest-qt · offscreen Qt rendering。

设计依据：`docs/superpowers/specs/2026-06-27-cursor-pill-single-readout-density-design.md`

---

## Global Constraints

- 只触碰 cursor pill 显示层：`mf4_analyzer/ui/chart_stack/stack.py`、`mf4_analyzer/ui/chart_stack/cursor_pill.py`、`mf4_analyzer/ui_kit/style.qss`、相关 UI tests。
- 不修改 `mf4_analyzer/ui/pg_canvas/cursor.py` 的 `_emit_single_cursor_html(...)`。
- 不修改 `mf4_analyzer/ui/plot_helpers.py` 的 `_format_single_cursor_channel_html(...)`。
- 不改 `ChartStack._pill_for_canvas(...)` 的主/副 pane 路由。
- 不把 FFT / FFT vs Time / Order 的 heatmap hover 重新接回 cursor pill。
- 测试命令使用仓库 venv：`TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest ...`。
- 当前工作树可能有无关改动；提交时只 stage 本计划列出的文件。

---

## File Structure

- Modify `mf4_analyzer/ui/chart_stack/stack.py`  
  生成单游标 full/mini detail variants；保留 `_format_cursor_info_for_pill(...)` 兼容返回值。

- Modify `mf4_analyzer/ui/chart_stack/cursor_pill.py`  
  让 `CursorPill` 支持单游标 full/mini variants、tooltip、动态按钮 property。

- Modify `mf4_analyzer/ui_kit/style.qss`  
  用 `cursorPillMode` property 区分 `-` / `+` 按钮视觉状态。

- Modify `tests/ui/test_chart_stack.py`  
  更新行距契约测试，新增 mini single readout 与 toggle 状态测试，保留圆角像素回归。

- Modify `tests/ui/test_split_per_pane_controls.py`  
  增加副 pane 单游标 mini detail 不覆盖主 pane 的小回归。

---

## Task 1: 更新单游标字符串契约测试

**Files:**
- Modify: `tests/ui/test_chart_stack.py`

**Interfaces:**
- Existing: `ChartStack._format_cursor_info_for_pill(text)` 仍返回 `(primary, detail)`。
- New: `ChartStack._format_single_cursor_variants_for_pill(text)` 返回 `(primary, full_detail, mini_detail, tooltip)`。

- [ ] **Step 1: 更新已有行距断言**

在 `tests/ui/test_chart_stack.py::test_single_cursor_pill_uses_vertical_channel_readout` 中，把当前断言：

```python
assert 'padding-top:6px' in detail
```

改成：

```python
assert 'padding-top:6px' not in detail
assert 'padding-top:2px' in detail
assert 'line-height:1.15' in detail
```

在同文件下方的 `_format_cursor_info_for_pill` 测试中，把：

```python
assert 'padding-top:6px' in detail
```

改成：

```python
assert 'padding-top:6px' not in detail
assert 'padding-top:2px' in detail
assert 'line-height:1.15' in detail
```

- [ ] **Step 2: 新增 mini variant 字符串测试**

在 `test_single_cursor_pill_uses_vertical_channel_readout` 后追加：

```python
def test_single_cursor_pill_builds_mini_value_only_detail(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack, _CURSOR_HTML_SEP

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('time')
    cs.set_cursor_mode('single')

    text = _CURSOR_HTML_SEP.join([
        '<span style="color:#111827;">t=35.0358s</span>',
        '<span style="color:#64748b;">[taiyaok]</span> '
        '<span style="color:#ef4444;">Rte_ESChkPlausi_mESMotorTorque_xds16=<b>0 Nm</b></span>',
        '<span style="color:#64748b;">[taiyaok]</span> '
        '<span style="color:#1769e0;">Rte_InCo_mInertiaCompMotorTorque_xds16=<b>0.04395 Nm</b></span>',
    ])

    primary, full_detail, mini_detail, tooltip = (
        cs._format_single_cursor_variants_for_pill(text)
    )

    assert primary == '<span style="color:#111827;">t=35.0358s</span>'
    assert 'Rte_ESChkPlausi_mESMotorTorque_xds16' in full_detail
    assert 'Rte_InCo_mInertiaCompMotorTorque_xds16' in full_detail
    assert '0 Nm' in mini_detail
    assert '0.04395 Nm' in mini_detail
    assert '#ef4444' in mini_detail
    assert '#1769e0' in mini_detail
    assert 'Rte_ESChkPlausi_mESMotorTorque_xds16' not in mini_detail
    assert 'Rte_InCo_mInertiaCompMotorTorque_xds16' not in mini_detail
    assert '[taiyaok]' not in mini_detail
    assert '=' not in mini_detail
    assert 'Rte_ESChkPlausi_mESMotorTorque_xds16=0 Nm' in tooltip
    assert 'Rte_InCo_mInertiaCompMotorTorque_xds16=0.04395 Nm' in tooltip
```

- [ ] **Step 3: 运行确认失败**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_chart_stack.py::test_single_cursor_pill_uses_vertical_channel_readout \
  tests/ui/test_chart_stack.py::test_single_cursor_pill_builds_mini_value_only_detail \
  tests/ui/test_chart_stack.py::test_cursor_pill_formats_single_cursor_details_for_mode \
  -q
```

Expected:

- `test_single_cursor_pill_uses_vertical_channel_readout` 失败，因为当前仍有 `padding-top:6px` 且没有 `line-height:1.15`。
- `test_single_cursor_pill_builds_mini_value_only_detail` 失败，因为 `_format_single_cursor_variants_for_pill` 还不存在。
- `_format_cursor_info_for_pill` 相关测试失败，因为仍断言旧间距。

---

## Task 2: 在 ChartStack 生成 full/mini 单游标 detail

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack/stack.py`
- Test: `tests/ui/test_chart_stack.py`

**Interfaces:**
- Create private helpers:
  - `_format_single_cursor_variants_for_pill(self, text)`
  - `_mini_single_cursor_part(self, part)`
  - `_plain_single_cursor_tooltip_line(self, part)`

- [ ] **Step 1: 修改 `_on_cursor_info(...)` 调用单游标 variants**

把 `mf4_analyzer/ui/chart_stack/stack.py:1040-1043` 附近逻辑改成：

```python
        if mode == 'single':
            primary, detail, mini_detail, tooltip = (
                self._format_single_cursor_variants_for_pill(text)
            )
            pill.set_primary(primary)
            pill.set_single_detail_html(detail, mini_detail, tooltip)
        else:
            primary, detail = self._format_cursor_info_for_pill(text, mode)
            pill.set_primary(primary)
            pill.set_detail_html(detail)
```

保留后续：

```python
        pill.setVisible(self._cursor_pill_visible_for_mode())
        self._reposition_pill()
```

- [ ] **Step 2: 保留兼容 `_format_cursor_info_for_pill(...)`，降低 full detail 行距**

将 `_format_cursor_info_for_pill(...)` 改成：

```python
    def _format_cursor_info_for_pill(self, text, mode=None):
        from .cursor_pill import _CURSOR_HTML_SEP
        if mode is None:
            mode = self.cursor_mode()
        if mode != 'single' or _CURSOR_HTML_SEP not in (text or ''):
            return text, ''
        primary, detail, _mini_detail, _tooltip = (
            self._format_single_cursor_variants_for_pill(text)
        )
        return primary, detail
```

- [ ] **Step 3: 新增 single variant helper**

在 `_format_cursor_info_for_pill(...)` 后面新增：

```python
    def _format_single_cursor_variants_for_pill(self, text):
        from .cursor_pill import _CURSOR_HTML_SEP
        parts = [part for part in (text or '').split(_CURSOR_HTML_SEP) if part]
        if len(parts) <= 1:
            return text, '', '', ''
        full_rows = ['<table cellspacing="0" cellpadding="0">']
        mini_rows = [
            '<table cellspacing="0" cellpadding="0" '
            'style="font-size:12px;">'
        ]
        tooltip_lines = []
        for i, part in enumerate(parts[1:]):
            top_pad = '2px' if i > 0 else '0'
            full_rows.append(
                '<tr><td style="padding-top:'
                f'{top_pad}; padding-bottom:0; line-height:1.15;">'
                f'{part}</td></tr>'
            )
            mini_rows.append(self._mini_single_cursor_part(part, top_pad))
            tooltip_line = self._plain_single_cursor_tooltip_line(part)
            if tooltip_line:
                tooltip_lines.append(tooltip_line)
        full_rows.append('</table>')
        mini_rows.append('</table>')
        return parts[0], ''.join(full_rows), ''.join(mini_rows), '\n'.join(tooltip_lines)
```

- [ ] **Step 4: 新增 mini row parser**

在 `stack.py` 顶部 imports 附近如已有 `re` / `html` 未导入，则新增：

```python
import re
from html import unescape
```

在 `ChartStack` 类内新增：

```python
    _COLOR_RE = re.compile(r'color:\s*([^;"\']+)')
    _BOLD_VALUE_RE = re.compile(r'<b[^>]*>(.*?)</b>', re.S)
    _TAG_RE = re.compile(r'<[^>]+>')

    def _mini_single_cursor_part(self, part, top_pad):
        color_match = self._COLOR_RE.search(part or '')
        color = color_match.group(1).strip() if color_match else '#111827'
        value_match = self._BOLD_VALUE_RE.search(part or '')
        if value_match:
            value = self._strip_html(value_match.group(1)).strip()
        else:
            plain = self._strip_html(part)
            value = plain.split('=', 1)[-1].strip() if '=' in plain else plain.strip()
        value = value or '—'
        mono = "font-family:'SF Mono',Menlo,Consolas,monospace;"
        return (
            f'<tr>'
            f'<td style="padding-top:{top_pad}; padding-right:5px;">'
            f'<span style="color:{color};">●</span></td>'
            f'<td style="padding-top:{top_pad}; color:{color}; '
            f'{mono} font-weight:650;">{value}</td>'
            f'</tr>'
        )

    def _plain_single_cursor_tooltip_line(self, part):
        plain = self._strip_html(part).strip()
        return plain.replace(' = ', '=')

    def _strip_html(self, value):
        return unescape(self._TAG_RE.sub('', value or ''))
```

如果 `ChartStack` 类已有同名 helper，复用并避免重复定义。

- [ ] **Step 5: 运行 Task 1 测试确认通过**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_chart_stack.py::test_single_cursor_pill_uses_vertical_channel_readout \
  tests/ui/test_chart_stack.py::test_single_cursor_pill_builds_mini_value_only_detail \
  tests/ui/test_chart_stack.py::test_cursor_pill_formats_single_cursor_details_for_mode \
  -q
```

Expected: 3 passed.

---

## Task 3: 扩展 CursorPill full/mini 状态和按钮属性

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack/cursor_pill.py`
- Modify: `tests/ui/test_chart_stack.py`

**Interfaces:**
- Add `CursorPill.set_single_detail_html(full_html, mini_html, tooltip="")`。
- Add `CursorPill._update_toggle_button()`。
- Existing `set_detail_html(...)` and `set_dual_rows(...)` continue to work.

- [ ] **Step 1: 新增 widget 状态测试**

在 `tests/ui/test_chart_stack.py` 的 `test_cursor_pill_renders_transparent_rounded_corners` 后追加：

```python
def test_cursor_pill_toggle_exposes_distinct_full_and_mini_states(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import CursorPill

    pill = CursorPill()
    qtbot.addWidget(pill)

    assert pill._toggle_btn.text() == "−"
    assert pill._toggle_btn.toolTip() == "收起为数值"
    assert pill._toggle_btn.property("cursorPillMode") == "full"

    pill._toggle_mode()

    assert pill._toggle_btn.text() == "+"
    assert pill._toggle_btn.toolTip() == "展开通道名"
    assert pill._toggle_btn.property("cursorPillMode") == "mini"

    pill._toggle_mode()

    assert pill._toggle_btn.text() == "−"
    assert pill._toggle_btn.toolTip() == "收起为数值"
    assert pill._toggle_btn.property("cursorPillMode") == "full"
```

在同文件追加：

```python
def test_single_cursor_pill_toggle_shows_value_only_mini_detail(qapp, qtbot):
    from mf4_analyzer.ui.chart_stack import ChartStack, _CURSOR_HTML_SEP

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_mode('time')
    cs.set_cursor_mode('single')

    text = _CURSOR_HTML_SEP.join([
        '<span style="color:#111827;">t=35.0358s</span>',
        '<span style="color:#64748b;">[taiyaok]</span> '
        '<span style="color:#ef4444;">Rte_PA_mAtMotorTorque_xds16=<b>-1.841 Nm</b></span>',
    ])
    cs.canvas_time.cursor_info.emit(text)

    assert 'Rte_PA_mAtMotorTorque_xds16' in cs._pill._detail.text()
    cs._pill._toggle_mode()

    detail = cs._pill._detail.text()
    assert '-1.841 Nm' in detail
    assert 'Rte_PA_mAtMotorTorque_xds16' not in detail
    assert '[taiyaok]' not in detail
    assert '=' not in detail
    assert 'Rte_PA_mAtMotorTorque_xds16=-1.841 Nm' in cs._pill._detail.toolTip()
```

- [ ] **Step 2: 运行确认失败**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_chart_stack.py::test_cursor_pill_toggle_exposes_distinct_full_and_mini_states \
  tests/ui/test_chart_stack.py::test_single_cursor_pill_toggle_shows_value_only_mini_detail \
  -q
```

Expected:

- toggle state 测试失败，因为按钮还没有 tooltip/property。
- single mini widget 测试失败，因为 `set_single_detail_html(...)` 还不存在或 toggle 不刷新 single detail。

- [ ] **Step 3: 初始化 single detail state 和按钮 state**

在 `CursorPill.__init__` 中，`self._dual_rows = []` 后加入：

```python
        self._single_full_detail = ""
        self._single_mini_detail = ""
        self._single_tooltip = ""
```

在 `_toggle_btn` 建好并 connect 后加入：

```python
        self._update_toggle_button()
```

同时把 layout spacing 从：

```python
        lay.setSpacing(4)
```

改成：

```python
        lay.setSpacing(2)
```

- [ ] **Step 4: 新增 `set_single_detail_html(...)` 并增强 `set_detail_html(...)`**

把 `set_detail_html(...)` 改成：

```python
    def set_detail_html(self, html):
        self._single_full_detail = ""
        self._single_mini_detail = ""
        self._single_tooltip = ""
        if html:
            self._detail.setText(html)
            self._detail.setToolTip("")
            self._detail.setVisible(True)
        else:
            self._detail.clear()
            self._detail.setToolTip("")
            self._detail.setVisible(False)
        self.adjustSize()
```

在其后新增：

```python
    def set_single_detail_html(self, full_html, mini_html, tooltip=""):
        self._dual_rows = []
        self._single_full_detail = full_html or ""
        self._single_mini_detail = mini_html or ""
        self._single_tooltip = tooltip or ""
        self._refresh_detail()
        self.adjustSize()
```

- [ ] **Step 5: 清理 state，防止 tooltip 残留**

在 `clear()` 中 `self._dual_rows = []` 后加入：

```python
        self._single_full_detail = ""
        self._single_mini_detail = ""
        self._single_tooltip = ""
        self._detail.setToolTip("")
```

- [ ] **Step 6: 更新 toggle 和 detail refresh**

把 `_toggle_mode()` 改成：

```python
    def _toggle_mode(self):
        self._mode = "mini" if self._mode == "full" else "full"
        self._update_toggle_button()
        self._refresh_detail()
        self.adjustSize()
```

新增：

```python
    def _update_toggle_button(self):
        self._toggle_btn.setText("+" if self._mode == "mini" else "−")
        self._toggle_btn.setToolTip(
            "展开通道名" if self._mode == "mini" else "收起为数值"
        )
        self._toggle_btn.setProperty("cursorPillMode", self._mode)
        self._toggle_btn.style().unpolish(self._toggle_btn)
        self._toggle_btn.style().polish(self._toggle_btn)
```

把 `_refresh_detail()` 改成：

```python
    def _refresh_detail(self):
        if self._dual_rows:
            from ..plot_helpers import _format_dual_html
            html = (
                _format_dual_html(self._dual_rows)
                if self._mode == "full"
                else _format_mini_html(self._dual_rows)
            )
            tooltip = ""
        elif self._single_full_detail:
            html = (
                self._single_mini_detail
                if self._mode == "mini" and self._single_mini_detail
                else self._single_full_detail
            )
            tooltip = self._single_tooltip if self._mode == "mini" else ""
        else:
            html = ""
            tooltip = ""
        if html:
            self._detail.setText(html)
            self._detail.setToolTip(tooltip)
            self._detail.setVisible(True)
        else:
            self._detail.clear()
            self._detail.setToolTip("")
            self._detail.setVisible(False)
```

- [ ] **Step 7: 保持 `set_dual_rows(...)` 优先级明确**

把 `set_dual_rows(...)` 改成：

```python
    def set_dual_rows(self, rows):
        self._dual_rows = rows or []
        if self._dual_rows:
            self._single_full_detail = ""
            self._single_mini_detail = ""
            self._single_tooltip = ""
        self._refresh_detail()
        if self._dual_rows:
            self._detail.setVisible(True)
        self.adjustSize()
```

- [ ] **Step 8: 运行 widget 测试确认通过**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_chart_stack.py::test_cursor_pill_toggle_exposes_distinct_full_and_mini_states \
  tests/ui/test_chart_stack.py::test_single_cursor_pill_toggle_shows_value_only_mini_detail \
  tests/ui/test_chart_stack.py::test_cursor_pill_renders_transparent_rounded_corners \
  -q
```

Expected: 3 passed.

---

## Task 4: QSS 区分 `-` / `+` 状态

**Files:**
- Modify: `mf4_analyzer/ui_kit/style.qss`
- Test: `tests/ui/test_chart_stack.py`

**Interfaces:**
- Consumes `QPushButton#cursorPillToggle[cursorPillMode="full"]` and `[cursorPillMode="mini"]`。

- [ ] **Step 1: 新增 QSS 内容测试**

在 `tests/ui/test_chart_stack.py` 中追加：

```python
def test_cursor_pill_toggle_qss_has_distinct_full_and_mini_rules():
    from pathlib import Path

    qss = Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
    assert 'QPushButton#cursorPillToggle[cursorPillMode="full"]' in qss
    assert 'QPushButton#cursorPillToggle[cursorPillMode="mini"]' in qss
    assert '#2563eb' in qss
```

- [ ] **Step 2: 运行确认失败**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_chart_stack.py::test_cursor_pill_toggle_qss_has_distinct_full_and_mini_rules \
  -q
```

Expected: FAIL，因为 QSS 还没有 property selector。

- [ ] **Step 3: 修改 QSS**

在 `mf4_analyzer/ui_kit/style.qss` 的 `QPushButton#cursorPillToggle` 规则后追加：

```css
QPushButton#cursorPillToggle[cursorPillMode="full"] {
    background: rgba(100, 116, 139, 0.15);
    border: 1px solid rgba(100, 116, 139, 0.30);
    color: #475569;
}
QPushButton#cursorPillToggle[cursorPillMode="mini"] {
    background: rgba(37, 99, 235, 0.14);
    border: 1px solid rgba(37, 99, 235, 0.52);
    color: #2563eb;
}
```

把 hover / pressed 保持通用即可：

```css
QPushButton#cursorPillToggle:hover {
    background: rgba(37, 99, 235, 0.18);
}
QPushButton#cursorPillToggle:pressed {
    background: rgba(37, 99, 235, 0.26);
}
```

- [ ] **Step 4: 运行 QSS 测试**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_chart_stack.py::test_cursor_pill_toggle_qss_has_distinct_full_and_mini_rules \
  -q
```

Expected: 1 passed.

---

## Task 5: 分屏回归和完整验证

**Files:**
- Modify: `tests/ui/test_split_per_pane_controls.py`

**Interfaces:**
- Uses existing per-pane routing: `_pill_for_canvas(...)` and `CursorPill.set_single_detail_html(...)`。

- [ ] **Step 1: 新增副 pane mini 独立测试**

在 `tests/ui/test_split_per_pane_controls.py` 的 per-pane cursor pill tests 后追加：

```python
def test_split_secondary_single_cursor_mini_detail_stays_on_secondary_pill(
    qtbot, qapp, loaded_csv
):
    from mf4_analyzer.ui.chart_stack import _CURSOR_HTML_SEP

    w, *_ = _make_speed_vs_torque_views(qtbot, qapp, loaded_csv)
    cs = w.chart_stack
    _enter_split(w, qapp)
    _click_card(qapp, cs._secondary_card)
    cs._secondary_card.set_cursor_mode("single")
    qapp.processEvents()

    cs.canvas_time.cursor_info.emit("t=9.0s | speed=1")
    secondary_text = _CURSOR_HTML_SEP.join([
        "<span>t=1.0000s</span>",
        '<span style="color:#1769e0;">secondary_speed=<b>5 rpm</b></span>',
    ])
    cs.secondary_canvas().cursor_info.emit(secondary_text)
    qapp.processEvents()

    assert "t=9.0s" in cs.cursor_pill_text()
    assert cs._pill_secondary is not None
    assert "secondary_speed" in cs._pill_secondary._detail.text()

    cs._pill_secondary._toggle_mode()

    assert "secondary_speed" not in cs._pill_secondary._detail.text()
    assert "5 rpm" in cs._pill_secondary._detail.text()
    assert "secondary_speed=5 rpm" in cs._pill_secondary._detail.toolTip()
    assert "t=9.0s" in cs.cursor_pill_text()
```

- [ ] **Step 2: 运行分屏测试**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_split_per_pane_controls.py::test_secondary_canvas_cursor_readout_reaches_secondary_pill \
  tests/ui/test_split_per_pane_controls.py::test_split_dual_cursor_results_show_on_both_pane_pills \
  tests/ui/test_split_per_pane_controls.py::test_pill_formats_detail_using_emitting_pane_cursor_mode \
  tests/ui/test_split_per_pane_controls.py::test_split_secondary_single_cursor_mini_detail_stays_on_secondary_pill \
  -q
```

Expected: 4 passed.

- [ ] **Step 3: 运行 cursor pill 集合测试**

Run:

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_chart_stack.py \
  tests/ui/test_split_per_pane_controls.py \
  tests/ui/test_split_routing.py \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 4: 静态检查**

Run:

```bash
git diff --check -- \
  mf4_analyzer/ui/chart_stack/stack.py \
  mf4_analyzer/ui/chart_stack/cursor_pill.py \
  mf4_analyzer/ui_kit/style.qss \
  tests/ui/test_chart_stack.py \
  tests/ui/test_split_per_pane_controls.py
```

Expected: no output.

- [ ] **Step 5: 人工 UI 验证**

Run TraceLab normally, load a file with at least 6 visible time-domain channels, enable single cursor, then verify:

- Full state shows `t=...` plus compact channel rows.
- Clicking `-` changes button to visually distinct `+`.
- Mini state shows only colored values and units, no channel names.
- Detail tooltip includes channel names and values.
- Clicking `+` restores channel names.
- In split view, primary and secondary panes keep independent readout pills.

- [ ] **Step 6: Commit only intended files**

Before commit:

```bash
git status --short --branch
git diff -- \
  mf4_analyzer/ui/chart_stack/stack.py \
  mf4_analyzer/ui/chart_stack/cursor_pill.py \
  mf4_analyzer/ui_kit/style.qss \
  tests/ui/test_chart_stack.py \
  tests/ui/test_split_per_pane_controls.py
```

Commit:

```bash
git add \
  mf4_analyzer/ui/chart_stack/stack.py \
  mf4_analyzer/ui/chart_stack/cursor_pill.py \
  mf4_analyzer/ui_kit/style.qss \
  tests/ui/test_chart_stack.py \
  tests/ui/test_split_per_pane_controls.py
git commit -m "fix(ui): compact single cursor readout pill"
```

---

## Self-Review

- Spec coverage: Task 1 covers row density string contract; Task 2 covers full/mini detail generation; Task 3 covers `CursorPill` state and tooltip; Task 4 covers visible `-` / `+` distinction; Task 5 covers split-pane routing and final verification.
- No placeholders: every task has explicit paths, code snippets, commands, and expected outcomes.
- Type consistency: `set_single_detail_html(full_html, mini_html, tooltip)` is introduced before being consumed; `cursorPillMode` is used consistently in widget tests and QSS.
- Scope control: plan leaves `pg_canvas/cursor.py` and `plot_helpers.py` unchanged, so cursor interpolation and source HTML contracts remain stable.
