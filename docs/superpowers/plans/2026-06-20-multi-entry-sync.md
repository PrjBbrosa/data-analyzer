# 图表多入口输入同步修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修掉图表控制六处「多入口之间不同步」的问题，让每个控件的多个入口口径一致，且不改动既有交互语义。

**Architecture:** 针对性补丁，不动「ViewBox 显示态 / inspector 参数 / 持久化」三套存储分层。① 用一个新画布信号 + 复用 `_ChartCard` 的 hint 机制做「临时缩放」持续提示；② 给鼠标模式 controller 加一条「带 peer 广播」的入口供右键菜单走；③④⑤⑥ 是对话框/菜单/轴句柄的小范围一致性修复。

**Tech Stack:** Python 3 / PyQt5 / pyqtgraph；pytest + pytest-qt（`qapp`/`qtbot` fixture，`QT_QPA_PLATFORM=offscreen`）。

## Global Constraints

- 设计依据 `docs/superpowers/specs/2026-06-20-multi-entry-sync-design.md`，其 Non-Goals 为硬边界。
- ①：**只加提示**。严禁把手动缩放回写 inspector 的 自动/最小/最大，严禁改 `reset_view_to_data_extents` 行为（它已正确回到参数范围）。
- ③：对话框网格**保持单勾**（X+Y 联动），不拆 X/Y。
- ②：**防递归**——广播只在新入口做一层，对 peer 调用非广播 setter（`set_mouse_mode`）。
- 任何 `setXRange/setYRange` 程序化设范围一律 `padding=0`（仓库惯例）。
- UI/视觉改动（Task 1/2/3/6）**必须验真机渲染**（截图或 objc 读原生属性），不接受「属性设上了 + 单测过」即判定修好。
- codex baseline 有记录在案的既有失败（`_CaptureCanvas` 缺 `set_tick_density`），勿误判为本次回归。
- 测试运行前确保 offscreen：文件顶部若无 `qapp` fixture 注入，则 `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")`。

---

### Task 1: ① 分析图临时缩放提示 — FFT 线图 + _ChartCard

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`（信号定义 ~145；`_on_interactive_range_changed` 475-479；`plot_spectra` 设范围后 ~720；`reset_view_to_data_extents` 857-868）
- Modify: `mf4_analyzer/ui/chart_stack/cards.py`(`_ChartCard.__init__` 分析信号区 ~100-120；新增 `set_transient_zoom_hint`)
- Test: `tests/ui/test_pg_line_canvas.py`、`tests/ui/test_chart_stack.py`

**Interfaces:**
- Produces: `PgLineCanvas.manual_zoom_changed = pyqtSignal(bool)` — True=进入临时缩放，False=已回参数范围；`_ChartCard.set_transient_zoom_hint(on: bool) -> None`

- [ ] **Step 1: 写失败测试（画布信号）**

在 `tests/ui/test_pg_line_canvas.py` 末尾追加：

```python
def test_amp_manual_zoom_emits_transient_true(qapp):
    c = PgLineCanvas()
    seen = []
    c.manual_zoom_changed.connect(seen.append)
    # amp 主图的手动缩放 → 进入临时缩放
    c._on_interactive_range_changed(c._plot_amp)
    assert seen == [True]


def test_time_preview_zoom_does_not_emit_transient(qapp):
    c = PgLineCanvas()
    seen = []
    c.manual_zoom_changed.connect(seen.append)
    # 时域预览缩放是「改 FFT 时间窗」，不算临时缩放
    c._on_interactive_range_changed(c._plot_time)
    assert seen == []


def test_plot_spectra_clears_transient_zoom(qapp):
    c = PgLineCanvas()
    seen = []
    c.manual_zoom_changed.connect(seen.append)
    entry = {
        "freq": np.array([1.0, 2.0, 3.0]),
        "amp": np.array([0.1, 0.2, 0.1]),
        "label": "x",
        "color": "#2563eb",
    }
    c.plot_spectra([entry], xlim=(0.0, 100.0), amp_label="A", title="t")
    assert seen and seen[-1] is False
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `python -m pytest tests/ui/test_pg_line_canvas.py -k "transient or manual_zoom" -v`
Expected: FAIL（`AttributeError: 'PgLineCanvas' object has no attribute 'manual_zoom_changed'`）

- [ ] **Step 3: 加信号定义**

在 `line_canvas.py` 既有信号块（`time_preview_range_changed = pyqtSignal(float, float)` 一行，约 145）下方加：

```python
    manual_zoom_changed = pyqtSignal(bool)
```

- [ ] **Step 4: 在 amp 手动缩放时发 True**

把 `_on_interactive_range_changed`（475-479）改为：

```python
    def _on_interactive_range_changed(self, plot=None, *_args):
        self.disable_interactive_quality()
        self.schedule_idle_quality()
        if plot is self._plot_time:
            self._emit_time_preview_range()
        elif plot is self._plot_amp:
            self.manual_zoom_changed.emit(True)
```

- [ ] **Step 5: 重算 / 查看全部时发 False**

`plot_spectra` 内，在设完 amp 范围处（`self._plot_amp.setXRange(...)` 与其后的 `if manual_y: ... else: self._plot_amp.enableAutoRange(axis='y')` 块，约 716-720）之后，紧接着加一行：

```python
        self.manual_zoom_changed.emit(False)
```

`reset_view_to_data_extents`（857-868）方法体末尾（最后一条语句之后）加同一行：

```python
        self.manual_zoom_changed.emit(False)
```

- [ ] **Step 6: 跑画布测试，确认通过**

Run: `python -m pytest tests/ui/test_pg_line_canvas.py -k "transient or manual_zoom" -v`
Expected: PASS（3 个）

- [ ] **Step 7: 写失败测试（card 提示）**

在 `tests/ui/test_chart_stack.py` 末尾追加：

```python
def test_card_transient_zoom_hint_shows_and_clears(qapp):
    from mf4_analyzer.ui.chart_stack.cards import _ChartCard
    from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas
    c = PgLineCanvas()
    card = _ChartCard(c, chart_mode='fft')
    card.set_transient_zoom_hint(True)
    assert "临时缩放" in card._hint_context.text()
    card.set_transient_zoom_hint(False)
    assert "临时缩放" not in card._hint_context.text()


def test_card_wires_canvas_manual_zoom_to_hint(qapp):
    from mf4_analyzer.ui.chart_stack.cards import _ChartCard
    from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas
    c = PgLineCanvas()
    card = _ChartCard(c, chart_mode='fft')
    c.manual_zoom_changed.emit(True)
    assert "临时缩放" in card._hint_context.text()
```

- [ ] **Step 8: 跑测试，确认失败**

Run: `python -m pytest tests/ui/test_chart_stack.py -k "transient_zoom or manual_zoom" -v`
Expected: FAIL（`AttributeError: ... 'set_transient_zoom_hint'`）

- [ ] **Step 9: 加 card 方法 + 接线**

在 `cards.py` 的 `_ChartCard` 加方法（放在 `flash_hint` 附近，约 610 之后）：

```python
    def set_transient_zoom_hint(self, on):
        """① 分析图手动缩放时持续提示，重算 / 查看全部后撤下。

        不新建浮层：复用底部 context-hint 行，缩放期间暂停轮播显示固定
        文案，清除时恢复轮播（与 spec Non-Goal「不回写 inspector」一致）。
        """
        if bool(on):
            self.set_hint_rotation_paused(True)
            self._hint_context.setText("临时缩放 · 重算 / 查看全部将回到设定范围")
        else:
            self.set_hint_rotation_paused(False)
            self._set_context_hint(reset=True)
```

在 `_ChartCard.__init__` 的分析画布信号 wiring 区（`context_menu_requested` 接线之后，约 104）加 getattr 守卫的接线（line/heatmap 均有该信号才连）：

```python
        manual_zoom_changed = getattr(canvas, 'manual_zoom_changed', None)
        if manual_zoom_changed is not None:
            manual_zoom_changed.connect(self.set_transient_zoom_hint)
```

- [ ] **Step 10: 跑测试，确认通过**

Run: `python -m pytest tests/ui/test_chart_stack.py -k "transient_zoom or manual_zoom" -v`
Expected: PASS（2 个）

- [ ] **Step 11: 真机验证**

真机运行（非 offscreen）打开 FFT 分析图，鼠标拖动缩放 → 底部出现「临时缩放…」提示；点右键「查看全部」或重算 → 提示消失。截图留存。

- [ ] **Step 12: 提交**

```bash
git add mf4_analyzer/ui/pg_canvas/line_canvas.py mf4_analyzer/ui/chart_stack/cards.py tests/ui/test_pg_line_canvas.py tests/ui/test_chart_stack.py
git commit -m "feat(chart): transient-zoom hint on FFT line canvas (no inspector writeback)"
```

---

### Task 2: ① 分析图临时缩放提示 — Heatmap（阶次 / fft_time）

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`（信号定义 ~642；主图缩放接线 726-727；新增 `_on_main_manual_zoom`；`plot_or_update_heatmap` 1044 / `plot_result` 1411 / `reset_view_to_data_extents` 1356 末尾各 emit False）
- Test: `tests/ui/test_pg_heatmap_canvas.py`

**Interfaces:**
- Consumes: `_ChartCard` 的 getattr 接线（Task 1 Step 9，已对任意带 `manual_zoom_changed` 的画布生效）
- Produces: `PgHeatmapCanvas.manual_zoom_changed = pyqtSignal(bool)`；`PgHeatmapCanvas._on_main_manual_zoom(*_args) -> None`

- [ ] **Step 1: 写失败测试**

在 `tests/ui/test_pg_heatmap_canvas.py` 末尾追加（构造参照该文件顶部既有用例；若需 parent 用 `None`）：

```python
def test_heatmap_main_manual_zoom_emits_transient_true(qapp):
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
    c = PgHeatmapCanvas(None)
    seen = []
    c.manual_zoom_changed.connect(seen.append)
    c._on_main_manual_zoom()
    assert seen == [True]


def test_heatmap_reset_clears_transient(qapp):
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
    c = PgHeatmapCanvas(None)
    seen = []
    c.manual_zoom_changed.connect(seen.append)
    c.reset_view_to_data_extents()
    assert seen and seen[-1] is False
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `python -m pytest tests/ui/test_pg_heatmap_canvas.py -k "manual_zoom or transient" -v`
Expected: FAIL（`AttributeError: ... 'manual_zoom_changed'`）

- [ ] **Step 3: 加信号定义**

在 `heatmap_canvas.py` 既有信号块（`levels_changed = pyqtSignal(float, float)` 一行，约 642）附近加：

```python
    manual_zoom_changed = pyqtSignal(bool)
```

- [ ] **Step 4: 主图缩放接线 + slot**

在主图缩放接线处（726-727 的 `self._plot.vb.sigRangeChangedManually.connect(self._on_interactive_range_changed)`）下方**追加**一条连接：

```python
        self._plot.vb.sigRangeChangedManually.connect(
            self._on_main_manual_zoom)
```

新增 slot（放在 `_on_interactive_range_changed`（963）附近）：

```python
    def _on_main_manual_zoom(self, *_args) -> None:
        self.manual_zoom_changed.emit(True)
```

- [ ] **Step 5: 重算 / 查看全部时发 False**

用 grep 定位下列三个方法体末尾（`return` 或最后一条语句之后），各插入一行 `self.manual_zoom_changed.emit(False)`：
- `reset_view_to_data_extents`（1356）
- `plot_or_update_heatmap`（1044）
- `plot_result`（1411）

```python
        self.manual_zoom_changed.emit(False)
```

（slice 预览缩放不发信号——只有主图 `_plot` 缩放算临时缩放，避免噪音。）

- [ ] **Step 6: 跑测试，确认通过**

Run: `python -m pytest tests/ui/test_pg_heatmap_canvas.py -k "manual_zoom or transient" -v`
Expected: PASS（2 个）

- [ ] **Step 7: 真机验证**

真机打开「阶次」与「FFT 时间」分析图，拖动主图缩放 → 出现「临时缩放…」提示；重算 / 查看全部 → 撤下。截图留存。

- [ ] **Step 8: 提交**

```bash
git add mf4_analyzer/ui/pg_canvas/heatmap_canvas.py tests/ui/test_pg_heatmap_canvas.py
git commit -m "feat(chart): transient-zoom hint on heatmap canvas (order / fft_time)"
```

---

### Task 3: ② 分屏右键鼠标模式广播

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack/toolbar.py`（新增 `set_mouse_mode_broadcast`，放在 `set_mouse_mode` 610 附近）
- Modify: `mf4_analyzer/ui/pg_canvas/context_menu.py`（`_select_pan`/`_select_zoom` 381-392 改调广播入口）
- Modify: `mf4_analyzer/ui/chart_stack/stack.py`（把 `_sync_shared_nav_highlight` 也连到 focused toolbar 的 `mouse_mode_changed`）
- Modify: `mf4_analyzer/ui/pg_canvas/canvas.py`（620-631 controller 契约注释补 `set_mouse_mode_broadcast`）
- Test: `tests/ui/test_chart_stack.py`、`tests/ui/test_pg_line_canvas.py`

**Interfaces:**
- Consumes: `PgNavigationToolbar._peers()`（600）、`set_mouse_mode(mode)`（610，非广播）、`set_pan_mode/set_zoom_mode`（580/590）
- Produces: `PgNavigationToolbar.set_mouse_mode_broadcast(mode: str) -> None`（mode ∈ {'pan','zoom'}）

- [ ] **Step 1: 写失败测试（广播逻辑）**

在 `tests/ui/test_chart_stack.py` 末尾追加：

```python
class _StubCanvasForToolbar:
    axes_list = []
    _overlay_mode = False
    _x_master_handle = None
    def register_replot_callback(self, *_a): pass


def test_set_mouse_mode_broadcast_sets_self_and_peers(qapp):
    from mf4_analyzer.ui.chart_stack import PgNavigationToolbar
    t_main = PgNavigationToolbar(_StubCanvasForToolbar())
    t_peer = PgNavigationToolbar(_StubCanvasForToolbar())
    t_main._peer_toolbars_provider = lambda: [t_peer]

    t_main.set_mouse_mode_broadcast('zoom')
    assert t_main.mode == 'zoom'
    assert t_peer.mode == 'zoom'

    t_main.set_mouse_mode_broadcast('pan')
    assert t_main.mode == 'pan'
    assert t_peer.mode == 'pan'


def test_broadcast_does_not_recurse(qapp):
    # 两个互为 peer 的 toolbar：广播只能传播一层，不得成环/无限递归。
    from mf4_analyzer.ui.chart_stack import PgNavigationToolbar
    a = PgNavigationToolbar(_StubCanvasForToolbar())
    b = PgNavigationToolbar(_StubCanvasForToolbar())
    a._peer_toolbars_provider = lambda: [b]
    b._peer_toolbars_provider = lambda: [a]
    a.set_mouse_mode_broadcast('zoom')   # 不挂起即视为通过
    assert a.mode == 'zoom' and b.mode == 'zoom'
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `python -m pytest tests/ui/test_chart_stack.py -k "broadcast" -v`
Expected: FAIL（`AttributeError: ... 'set_mouse_mode_broadcast'`）

- [ ] **Step 3: 加广播入口**

在 `toolbar.py` 的 `set_mouse_mode`（610-619）下方加：

```python
    def set_mouse_mode_broadcast(self, mode):
        """右键菜单专用：在本 toolbar 设模式并广播到可见 peer 面板。

        与 _click_pan/_click_zoom 的按钮路径对称。防递归：对 peer 调用
        非广播的 set_mouse_mode（610），peer 不会再次广播回来。
        """
        if mode == self._MODE_ZOOM:
            self.set_zoom_mode()
        else:
            self.set_pan_mode()
        for toolbar in self._peers():
            toolbar.set_mouse_mode(self.mode)
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `python -m pytest tests/ui/test_chart_stack.py -k "broadcast" -v`
Expected: PASS（2 个）

- [ ] **Step 5: 写失败测试（右键菜单走广播）**

在 `tests/ui/test_pg_line_canvas.py`，扩展 `_FakeMouseModeController`（37-48）并加用例。先在该类内补一个记录方法（若直接改类不便，则在测试内子类化）：

```python
def test_menu_pan_button_calls_broadcast(qapp, monkeypatch):
    from mf4_analyzer.ui.pg_canvas import context_menu as cm

    calls = []

    class _Ctrl:
        def current_mouse_mode(self): return "zoom"
        def set_pan_mode(self): calls.append(("set_pan_mode",))
        def set_zoom_mode(self): calls.append(("set_zoom_mode",))
        def set_mouse_mode_broadcast(self, mode): calls.append(("broadcast", mode))

    from PyQt5.QtWidgets import QMenu
    menu = QMenu()
    ctrl = _Ctrl()
    cm._add_mouse_mode_toggle_row(menu, ctrl)
    row = None
    for act in menu.actions():
        w = act.defaultWidget() if hasattr(act, "defaultWidget") else None
        if w is not None and w.objectName() == "pgMouseModeToggleRow":
            row = w
            break
    assert row is not None
    from PyQt5.QtWidgets import QToolButton
    buttons = row.findChildren(QToolButton)  # [zoom, pan]
    buttons[1].click()  # 平移
    assert ("broadcast", "pan") in calls
```

- [ ] **Step 6: 跑测试，确认失败**

Run: `python -m pytest tests/ui/test_pg_line_canvas.py -k "menu_pan_button_calls_broadcast" -v`
Expected: FAIL（当前 `_select_pan` 调 `set_pan_mode`，calls 里无 `("broadcast","pan")`）

- [ ] **Step 7: 菜单改调广播入口**

在 `context_menu.py` 的 `_add_mouse_mode_toggle_row` 内，把 `_select_zoom`/`_select_pan`（371-389）改为优先调广播入口、回退到原 setter：

```python
    def _select_zoom(_checked=False):
        try:
            if hasattr(controller, "set_mouse_mode_broadcast"):
                controller.set_mouse_mode_broadcast("zoom")
            else:
                controller.set_zoom_mode()
        except Exception:
            pass
        try:
            menu.close()
        except Exception:
            pass

    def _select_pan(_checked=False):
        try:
            if hasattr(controller, "set_mouse_mode_broadcast"):
                controller.set_mouse_mode_broadcast("pan")
            else:
                controller.set_pan_mode()
        except Exception:
            pass
        try:
            menu.close()
        except Exception:
            pass
```

- [ ] **Step 8: 跑测试，确认通过**

Run: `python -m pytest tests/ui/test_pg_line_canvas.py -k "menu_pan_button_calls_broadcast" -v`
Expected: PASS

- [ ] **Step 9: 共享图标随右键刷新**

在 `stack.py` 构造里，紧接现有「pan/zoom action.triggered → `_sync_shared_nav_highlight`」接线（188-193）之后，把同一刷新也挂到主 toolbar 的 `mouse_mode_changed`（右键路径只 emit 这个信号、不触发 action）：

```python
        self._time_toolbar.mouse_mode_changed.connect(
            lambda *_a: self._sync_shared_nav_highlight()
        )
```

- [ ] **Step 10: 补 controller 契约注释**

`canvas.py` 的 `register_mouse_mode_controller`（620-631）docstring 内，在列出 `set_pan_mode()`/`set_zoom_mode()` 处补一句：controller 可选实现 `set_mouse_mode_broadcast(mode)`，右键菜单优先用它以在分屏下广播到 peer 面板。

- [ ] **Step 11: 全量跑相关套件 + 真机验证**

Run: `python -m pytest tests/ui/test_chart_stack.py tests/ui/test_pg_line_canvas.py -q`
真机：开分屏，在一个面板右键切「框选/平移」→ 两个面板都切换、共享 toolbar 图标同步刷新；单画布右键正常。截图留存。

- [ ] **Step 12: 提交**

```bash
git add mf4_analyzer/ui/chart_stack/toolbar.py mf4_analyzer/ui/pg_canvas/context_menu.py mf4_analyzer/ui/chart_stack/stack.py mf4_analyzer/ui/pg_canvas/canvas.py tests/ui/test_chart_stack.py tests/ui/test_pg_line_canvas.py
git commit -m "fix(chart): right-click mouse-mode broadcasts to split peers (parity with toolbar)"
```

---

### Task 4: ③ 网格双入口 — 脏检查 + alpha 统一

**Files:**
- Modify: `mf4_analyzer/ui/_axis_handle.py`(`PgAxisHandle.grid` 629-637 改走共享应用函数)
- Modify: `mf4_analyzer/ui/dialogs.py`(`apply_changes` 844 改脏检查)
- Test: `tests/ui/test_axis_handle.py`、`tests/ui/test_dialog_with_handle.py`

**Interfaces:**
- Consumes: `mf4_analyzer/ui/pg_canvas/_shared.py: show_major_grid_left_bottom_only(plot, *, x, y, alpha=0.25)`
- Produces: 无新公共符号（行为修复）

- [ ] **Step 1: 写失败测试（脏检查）**

在 `tests/ui/test_dialog_with_handle.py` 末尾追加：

```python
def test_grid_apply_skipped_when_checkbox_unchanged(qapp):
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes_with_curve()
    handle = MplAxisHandle(ax)
    dlg = ChartOptionsDialog(None, handle)

    calls = []
    handle.grid = lambda enabled: calls.append(enabled)  # spy

    # 用户没动「显示网格线」，只点确定：不应写网格
    dlg.apply_changes()
    assert calls == []


def test_grid_apply_runs_when_checkbox_changed(qapp):
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes_with_curve()
    handle = MplAxisHandle(ax)
    dlg = ChartOptionsDialog(None, handle)

    calls = []
    handle.grid = lambda enabled: calls.append(enabled)

    dlg.chk_grid.setChecked(not dlg._initial["grid"])  # 拨动
    dlg.apply_changes()
    assert calls == [not dlg._initial["grid"]]
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `python -m pytest tests/ui/test_dialog_with_handle.py -k "grid_apply" -v`
Expected: `test_grid_apply_skipped...` FAIL（当前无条件写，calls 非空）

- [ ] **Step 3: apply_changes 脏检查**

`dialogs.py` 把 `self.handle.grid(self.chk_grid.isChecked())`（844）替换为：

```python
        if self.chk_grid.isChecked() != self._initial.get("grid", False):
            self.handle.grid(self.chk_grid.isChecked())
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `python -m pytest tests/ui/test_dialog_with_handle.py -k "grid_apply" -v`
Expected: PASS（2 个）

- [ ] **Step 5: 写失败测试（alpha 统一）**

在 `tests/ui/test_axis_handle.py` 末尾追加（验证 `PgAxisHandle.grid` 走共享函数、带 0.28 alpha）：

```python
def test_pg_axis_handle_grid_uses_shared_helper_with_alpha(qapp, monkeypatch):
    import pyqtgraph as pg
    from mf4_analyzer.ui._axis_handle import PgAxisHandle
    from mf4_analyzer.ui.pg_canvas import _shared

    captured = {}

    def _fake(plot, *, x, y, alpha=0.25):
        captured.update(x=x, y=y, alpha=alpha)

    monkeypatch.setattr(_shared, "show_major_grid_left_bottom_only", _fake)

    pi = pg.PlotItem()
    h = PgAxisHandle(plot_item=pi)
    h.grid(True)
    assert captured == {"x": True, "y": True, "alpha": 0.28}
```

- [ ] **Step 6: 跑测试，确认失败**

Run: `python -m pytest tests/ui/test_axis_handle.py -k "grid_uses_shared_helper" -v`
Expected: FAIL（当前 `grid` 直接 `pi.showGrid`，未调 `_shared`）

- [ ] **Step 7: PgAxisHandle.grid 走共享函数**

`_axis_handle.py` 顶部 import 区加（若尚无）：

```python
from mf4_analyzer.ui.pg_canvas._shared import show_major_grid_left_bottom_only
```

把 `PgAxisHandle.grid`（629-637）改为：

```python
    def grid(self, enabled: bool) -> None:
        pi = self._plot_item
        if pi is None or not hasattr(pi, "showGrid"):
            return
        self._grid_enabled = bool(enabled)
        show_major_grid_left_bottom_only(
            pi,
            x=self._grid_enabled,
            y=self._grid_enabled if self._allow_y_grid else False,
            alpha=0.28,
        )
```

若顶部 import 触发循环导入，则把 import 移到方法体内首行（`_shared` 仅依赖 `plot_helpers`，正常无环）。

- [ ] **Step 8: 跑测试，确认通过**

Run: `python -m pytest tests/ui/test_axis_handle.py -k "grid_uses_shared_helper" -v`
Expected: PASS

- [ ] **Step 9: 回归 + 真机验证**

Run: `python -m pytest tests/ui/test_axis_handle.py tests/ui/test_dialog_with_handle.py -q`
真机：右键菜单只开 X 网格 → 打开「图表选项」改标题、点确定 → X/Y 网格不被改动；对话框拨动「显示网格线」→ X+Y 一起开/关、alpha 与右键一致。截图留存。

- [ ] **Step 10: 提交**

```bash
git add mf4_analyzer/ui/_axis_handle.py mf4_analyzer/ui/dialogs.py tests/ui/test_axis_handle.py tests/ui/test_dialog_with_handle.py
git commit -m "fix(dialog): grid apply is dirty-checked + shares menu alpha (no clobber)"
```

---

### Task 5: ④ 移除对话框色图下拉

**Files:**
- Modify: `mf4_analyzer/ui/dialogs.py`(`_mappable_group` 710-714/726；`_read_axes` 771-797 的 `cmap`；`reset_fields` 817；`apply_changes`/`_apply_appearance` 963-985 的 `combo_cmap` 读用)
- Test: `tests/ui/test_dialog_with_handle.py`

**Interfaces:**
- Produces: 对话框不再有 `combo_cmap` 属性；色阶 `spin_color_min/max` + `chk_color_auto` 保留不变

- [ ] **Step 1: 写失败测试**

在 `tests/ui/test_dialog_with_handle.py` 末尾追加：

```python
def test_dialog_has_no_cmap_combo(qapp):
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog
    ax = _axes_with_curve()
    dlg = ChartOptionsDialog(None, MplAxisHandle(ax))
    assert not hasattr(dlg, "combo_cmap")
    # 色阶控件仍在
    assert hasattr(dlg, "spin_color_min")
    assert hasattr(dlg, "chk_color_auto")
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `python -m pytest tests/ui/test_dialog_with_handle.py -k "no_cmap_combo" -v`
Expected: FAIL（`combo_cmap` 仍存在）

- [ ] **Step 3: 从 `_mappable_group` 删除色图下拉**

`dialogs.py` `_mappable_group`（698-730）删去 `combo_cmap` 的创建与添加：删除 710-714（`self.combo_cmap = QComboBox(...)` 与 `addItems([...])`）、719（`form.addRow("色图", self.combo_cmap)`），以及 726 `setEnabled(False)` 块里的 `self.combo_cmap.setEnabled(False)` 一行。其余（`chk_color_auto`、`spin_color_min/max`、最小/最大行）保留。

- [ ] **Step 4: 清除 `cmap` 读写引用**

- `_read_axes`（771-797）：删除 `mappable.get_cmap().name` 相关——把 772-777 块改为只取 clim：

```python
        mappable = self._current_mappable()
        if mappable is not None:
            cmin, cmax = mappable.get_clim()
        else:
            cmin, cmax = 0.0, 1.0
```

并从返回 dict 删除 `"cmap": cmap,`（794）。
- `reset_fields`（817）：删除 `self._set_combo_text(self.combo_cmap, d["cmap"])`。
- `apply_changes` → `_apply_appearance`（963-985）：删除 `mappable.set_cmap(self.combo_cmap.currentText())`（973），保留 clim 应用逻辑。

- [ ] **Step 5: 跑测试，确认通过**

Run: `python -m pytest tests/ui/test_dialog_with_handle.py -k "no_cmap_combo" -v`
Expected: PASS

- [ ] **Step 6: 回归（确保色阶路径未坏）**

Run: `python -m pytest tests/ui/test_dialog_with_handle.py tests/ui/test_dialogs.py -q`
Expected: 全绿（除既有 baseline）

- [ ] **Step 7: 提交**

```bash
git add mf4_analyzer/ui/dialogs.py tests/ui/test_dialog_with_handle.py
git commit -m "fix(dialog): remove non-persisting colormap dropdown (render is fixed turbo)"
```

---

### Task 6: ⑤ idle 态右键菜单口径与 toolbar 一致

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/context_menu.py`(`_add_mouse_mode_toggle_row` 复用分支 319-322；初始 checked 367-368)
- Test: `tests/ui/test_pg_line_canvas.py`

**Interfaces:**
- Consumes: `controller.current_mouse_mode()` ∈ {'', 'pan', 'zoom'}
- Produces: 无新符号（idle 时两按钮均不高亮）

- [ ] **Step 1: 写失败测试**

在 `tests/ui/test_pg_line_canvas.py` 末尾追加：

```python
def _toggle_row_buttons(menu):
    from PyQt5.QtWidgets import QToolButton
    for act in menu.actions():
        w = act.defaultWidget() if hasattr(act, "defaultWidget") else None
        if w is not None and w.objectName() == "pgMouseModeToggleRow":
            return w.findChildren(QToolButton)  # [zoom, pan]
    return []


def test_idle_mode_leaves_both_buttons_unchecked(qapp):
    from PyQt5.QtWidgets import QMenu
    from mf4_analyzer.ui.pg_canvas import context_menu as cm

    class _Ctrl:
        def current_mouse_mode(self): return ""   # idle
        def set_pan_mode(self): pass
        def set_zoom_mode(self): pass

    menu = QMenu()
    cm._add_mouse_mode_toggle_row(menu, _Ctrl())
    zoom_btn, pan_btn = _toggle_row_buttons(menu)
    assert zoom_btn.isChecked() is False
    assert pan_btn.isChecked() is False


def test_pan_mode_checks_only_pan(qapp):
    from PyQt5.QtWidgets import QMenu
    from mf4_analyzer.ui.pg_canvas import context_menu as cm

    class _Ctrl:
        def current_mouse_mode(self): return "pan"
        def set_pan_mode(self): pass
        def set_zoom_mode(self): pass

    menu = QMenu()
    cm._add_mouse_mode_toggle_row(menu, _Ctrl())
    zoom_btn, pan_btn = _toggle_row_buttons(menu)
    assert zoom_btn.isChecked() is False
    assert pan_btn.isChecked() is True
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `python -m pytest tests/ui/test_pg_line_canvas.py -k "idle_mode_leaves or pan_mode_checks" -v`
Expected: `test_idle_mode_leaves...` FAIL（当前 idle 时 pan 被 `current != zoom` 置 checked）

- [ ] **Step 3: 改初始 checked 逻辑**

`context_menu.py` `_add_mouse_mode_toggle_row` 内，初始设置（367-368）：

```python
    btn_zoom.setChecked(is_zoom)
    btn_pan.setChecked(not is_zoom)
```

改为按真实模式判定（需先允许「都不选」——`QButtonGroup` 默认 exclusive 不允许全不选）：

```python
    group.setExclusive(False)
    btn_zoom.setChecked(current == _PG_MOUSE_MODE_ZOOM)
    btn_pan.setChecked(current == _PG_MOUSE_MODE_PAN)
    group.setExclusive(True)
```

- [ ] **Step 4: 改复用分支**

同函数顶部「菜单复用」分支（319-322）同样按真实模式：

```python
                    current = controller.current_mouse_mode()
                    buttons = widget.findChildren(QToolButton)
                    if len(buttons) >= 2:
                        group = buttons[0].group()
                        if group is not None:
                            group.setExclusive(False)
                        buttons[0].setChecked(current == _PG_MOUSE_MODE_ZOOM)
                        buttons[1].setChecked(current == _PG_MOUSE_MODE_PAN)
                        if group is not None:
                            group.setExclusive(True)
```

- [ ] **Step 5: 跑测试，确认通过**

Run: `python -m pytest tests/ui/test_pg_line_canvas.py -k "idle_mode_leaves or pan_mode_checks" -v`
Expected: PASS（2 个）

- [ ] **Step 6: 真机验证**

真机：连点 toolbar「平移」两次进入 idle（或 overlay 选中曲线）→ 右键菜单两按钮均不高亮，与 toolbar 一致；切回 pan/zoom 后对应按钮高亮。截图留存。

- [ ] **Step 7: 提交**

```bash
git add mf4_analyzer/ui/pg_canvas/context_menu.py tests/ui/test_pg_line_canvas.py
git commit -m "fix(menu): idle mouse-mode leaves both toggle buttons unchecked (toolbar parity)"
```

---

### Task 7: ⑥ 对话框「自动范围」读真实 autorange

**Files:**
- Modify: `mf4_analyzer/ui/_axis_handle.py`(`PgAxisHandle` 新增 `is_autorange`)
- Modify: `mf4_analyzer/ui/dialogs.py`(`_read_axes` 784/789 用 handle 真实 autorange)
- Test: `tests/ui/test_axis_handle.py`

**Interfaces:**
- Consumes: `PgAxisHandle._view_box`（377）— pyqtgraph ViewBox
- Produces: `PgAxisHandle.is_autorange(axis: str = "x") -> bool`

- [ ] **Step 1: 写失败测试**

在 `tests/ui/test_axis_handle.py` 末尾追加：

```python
def test_pg_axis_handle_is_autorange(qapp):
    import pyqtgraph as pg
    from mf4_analyzer.ui._axis_handle import PgAxisHandle

    pi = pg.PlotItem()
    h = PgAxisHandle(plot_item=pi)

    pi.vb.enableAutoRange(axis='y', enable=True)
    pi.vb.setXRange(0.0, 1.0, padding=0)   # X 手动
    assert h.is_autorange('y') is True
    assert h.is_autorange('x') is False
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `python -m pytest tests/ui/test_axis_handle.py -k "is_autorange" -v`
Expected: FAIL（`AttributeError: ... 'is_autorange'`）

- [ ] **Step 3: 加 is_autorange**

`_axis_handle.py` `PgAxisHandle` 内（`is_grid_enabled` 639 附近）加：

```python
    def is_autorange(self, axis: str = "x") -> bool:
        vb = self._view_box
        state = getattr(vb, "state", None) if vb is not None else None
        if not isinstance(state, dict):
            return False
        flags = state.get("autoRange") or [False, False]
        idx = 1 if str(axis).lower().startswith("y") else 0
        try:
            return bool(flags[idx])
        except (IndexError, TypeError):
            return False
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `python -m pytest tests/ui/test_axis_handle.py -k "is_autorange" -v`
Expected: PASS

- [ ] **Step 5: `_read_axes` 用真实 autorange**

`dialogs.py` `_read_axes`（745-798）把 `"x_auto": False`（784）/`"y_auto": False`（789）改为按 handle 查询（getattr 防护 mpl 等无该方法的 handle）：

在 `_read_axes` 计算区（`line = self._current_line()` 前后）加：

```python
        if hasattr(self.handle, "is_autorange"):
            x_auto = bool(self.handle.is_autorange("x"))
            y_auto = bool(self.handle.is_autorange("y"))
        else:
            x_auto = False
            y_auto = False
```

并把返回 dict 的 `"x_auto": False,` → `"x_auto": x_auto,`、`"y_auto": False,` → `"y_auto": y_auto,`。（`color_auto` 维持现状，本点不扩 Z。）

- [ ] **Step 6: 写失败测试（对话框反映真实 autorange）**

在 `tests/ui/test_axis_handle.py` 末尾追加：

```python
def test_dialog_reflects_real_autorange(qapp):
    import pyqtgraph as pg
    from mf4_analyzer.ui._axis_handle import PgAxisHandle
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    pi = pg.PlotItem()
    pi.vb.enableAutoRange(axis='y', enable=True)
    pi.vb.setXRange(0.0, 1.0, padding=0)
    h = PgAxisHandle(plot_item=pi)
    dlg = ChartOptionsDialog(None, h)
    assert dlg.chk_y_auto.isChecked() is True
    assert dlg.chk_x_auto.isChecked() is False
```

- [ ] **Step 7: 跑测试，确认通过**

Run: `python -m pytest tests/ui/test_axis_handle.py -k "is_autorange or reflects_real_autorange" -v`
Expected: PASS

- [ ] **Step 8: 回归 + 真机验证**

Run: `python -m pytest tests/ui/test_axis_handle.py tests/ui/test_dialog_with_handle.py -q`
真机：对处于自动 Y 的分析图打开「图表选项」→「自动范围(Y)」勾选反映真实；手动设过范围的轴显示未勾。截图留存。

- [ ] **Step 9: 提交**

```bash
git add mf4_analyzer/ui/_axis_handle.py mf4_analyzer/ui/dialogs.py tests/ui/test_axis_handle.py
git commit -m "fix(dialog): auto-range checkboxes read real pyqtgraph autoRange state"
```

---

## 全量验证（所有 Task 完成后）

Run: `python -m pytest tests/ui -q`
Expected: 全绿（除记录在案的 codex baseline 既有失败 `_CaptureCanvas.set_tick_density`）。

逐条对照 spec §5 Acceptance Criteria 勾选确认。
