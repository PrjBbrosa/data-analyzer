# 时域 View 标签切换 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在时域图表底部加 Excel 风格的 View 标签栏,把整套时域显示状态存成可来回切换的 view(上限 6),并支持两个 view 并排对比。

**Architecture:** 方案 A —— `ViewState` 纯数据快照 + 重绘。新增 3 个模块(`view_state.py` 数据+逻辑、`view_bridge.py` 抓取/写回、`view_tabbar.py` UI),在 `TimeChartCard` 底部插标签栏,`MainWindow` 编排"切换前抓取→写回→复用现有重绘→恢复坐标轴"。状态仅存内存,`ViewState` 可 JSON 序列化为未来 project 落盘预留。

**Tech Stack:** Python 3.12 · PyQt5 · pyqtgraph · pytest + pytest-qt。

**对应 spec:** `docs/superpowers/specs/2026-06-04-timedomain-view-tabs-design.md`

**测试运行约定:** 纯逻辑测 `pytest tests/ui/test_xxx.py -v`;含 Qt 的测前置 `QT_QPA_PLATFORM=offscreen`。

---

## ⚠️ 实施前置(必读)

1. **先去重**:`chart_stack.py` / `main_window.py` 历史上存在**同名方法重复定义、最后一个生效**的情况(memory `project-ui-files-structural-corruption`)。改这两个文件前,对你要改/调用的方法 `grep -n "def 方法名"` 确认只有一处定义;若有重复,先删多余的再动。
2. **视觉验真**:每个里程碑结束后,真机/截图确认是活画布,不靠"单测过"就算完成(memory `verify-ui-visually`)。
3. 不要自己写算法类代码;本计划只动 UI/数据层。

---

# 里程碑 P1 — 标签栏 + 切换(单画布)

## Task 1: `ViewState` 数据类 + 序列化

**Files:**
- Create: `mf4_analyzer/ui/view_state.py`
- Test: `tests/ui/test_view_state.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/ui/test_view_state.py
from mf4_analyzer.ui.view_state import ViewState


def test_viewstate_roundtrips_through_dict():
    st = ViewState(
        name="转速对比",
        tab_color="#2d7ff9",
        checked=[("f1", "rpm"), ("f1", "speed")],
        colors={("f1", "rpm"): "#2d7ff9", ("f1", "speed"): "#e8590c"},
        plot_mode="overlay",
        cursor={"mode": "dual", "positions": [1.0, 2.0]},
        xlim=(0.0, 12.4),
        ylims={"0": (-1.0, 1.0)},
        axis_opts={"xscale": "linear"},
    )
    again = ViewState.from_dict(st.to_dict())
    assert again == st
    # tuple keys must survive JSON-style string conversion
    assert again.checked == [("f1", "rpm"), ("f1", "speed")]
    assert again.colors[("f1", "rpm")] == "#2d7ff9"


def test_viewstate_defaults_are_empty():
    st = ViewState(name="View 1", tab_color="#2d7ff9")
    assert st.checked == []
    assert st.colors == {}
    assert st.plot_mode == "subplot"
    assert st.cursor == {"mode": "off", "positions": []}
    assert st.xlim is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/ui/test_view_state.py -v`
Expected: FAIL — `ModuleNotFoundError: mf4_analyzer.ui.view_state`

- [ ] **Step 3: 实现 `ViewState`**

```python
# mf4_analyzer/ui/view_state.py
"""时域 View 快照(纯数据,无 Qt)+ View 列表管理器。

ViewState 记录一整套时域显示状态;可 JSON 往返,为未来 project 落盘预留。
ViewManager 管理 1..MAX_VIEWS 个 ViewState 的增删改排序与活动/并排选择。
两者都不依赖任何 widget,可纯单测(对标 side_panels.reduce_panel)。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

MAX_VIEWS = 6
_SEP = "\t"  # (fid, ch) tuple ↔ JSON string key 分隔符


def _default_cursor():
    return {"mode": "off", "positions": []}


@dataclass
class ViewState:
    name: str
    tab_color: str
    checked: list = field(default_factory=list)          # list[tuple[str, str]]
    colors: dict = field(default_factory=dict)           # {(fid,ch): hex}
    plot_mode: str = "subplot"                           # 'subplot' | 'overlay'
    cursor: dict = field(default_factory=_default_cursor)
    xlim: tuple | None = None                            # (lo, hi) | None
    ylims: dict = field(default_factory=dict)            # {axis_key: (lo, hi)}
    axis_opts: dict = field(default_factory=dict)        # 图表设置面板内容

    def to_dict(self) -> dict:
        d = asdict(self)
        d["checked"] = [list(t) for t in self.checked]
        d["colors"] = {f"{f}{_SEP}{c}": v for (f, c), v in self.colors.items()}
        d["ylims"] = {k: list(v) for k, v in self.ylims.items()}
        d["xlim"] = list(self.xlim) if self.xlim is not None else None
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ViewState":
        checked = [tuple(t) for t in d.get("checked", [])]
        colors = {}
        for k, v in d.get("colors", {}).items():
            f, _, c = k.partition(_SEP)
            colors[(f, c)] = v
        ylims = {k: tuple(v) for k, v in d.get("ylims", {}).items()}
        xlim = tuple(d["xlim"]) if d.get("xlim") is not None else None
        cursor = d.get("cursor") or _default_cursor()
        return cls(
            name=d["name"], tab_color=d["tab_color"],
            checked=checked, colors=colors,
            plot_mode=d.get("plot_mode", "subplot"),
            cursor=cursor, xlim=xlim, ylims=ylims,
            axis_opts=d.get("axis_opts", {}),
        )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/ui/test_view_state.py -v`
Expected: PASS(2 passed)

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/view_state.py tests/ui/test_view_state.py
git commit -m "feat(view): add ViewState dataclass with JSON roundtrip"
```

---

## Task 2: `ViewManager` 列表逻辑

**Files:**
- Modify: `mf4_analyzer/ui/view_state.py`(追加 `ViewManager`)
- Test: `tests/ui/test_view_manager.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/ui/test_view_manager.py
import pytest
from mf4_analyzer.ui.view_state import ViewManager, MAX_VIEWS


def make():
    return ViewManager()


def test_starts_with_one_view():
    m = make()
    assert len(m.views) == 1
    assert m.active == 0
    assert m.split_with is None


def test_new_view_respects_cap():
    m = make()
    for _ in range(MAX_VIEWS - 1):
        assert m.new_view() >= 0
    assert len(m.views) == MAX_VIEWS
    assert m.new_view() == -1          # 满 6 不增
    assert len(m.views) == MAX_VIEWS


def test_delete_cannot_empty():
    m = make()
    m.new_view()
    m.delete_view(0)
    assert len(m.views) == 1
    m.delete_view(0)                   # 剩 1 个不允许删空
    assert len(m.views) == 1


def test_duplicate_inserts_after_with_suffix():
    m = make()
    m.views[0].name = "A"
    idx = m.duplicate(0)
    assert idx == 1
    assert m.views[1].name == "A 副本"
    assert m.active == 1


def test_rename_blank_falls_back():
    m = make()
    m.rename(0, "   ")
    assert m.views[0].name == "未命名"


def test_reorder_moves_item():
    m = make()
    m.new_view(); m.new_view()
    m.views[0].name, m.views[1].name, m.views[2].name = "A", "B", "C"
    m.reorder(0, 2)
    assert [v.name for v in m.views] == ["B", "C", "A"]


def test_set_active_clears_split():
    m = make()
    m.new_view()
    m.set_split(1)
    assert m.split_with == 1
    m.set_active(1)
    assert m.split_with is None        # 切换即退出并排


def test_set_split_rejects_self():
    m = make()
    m.new_view()
    m.set_active(0)
    m.set_split(0)                     # 和 active 相同 → 无效
    assert m.split_with is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/ui/test_view_manager.py -v`
Expected: FAIL — `ImportError: cannot import name 'ViewManager'`

- [ ] **Step 3: 实现 `ViewManager`(追加到 `view_state.py` 末尾)**

```python
# mf4_analyzer/ui/view_state.py —— 追加
from PyQt5.QtCore import QObject, pyqtSignal

_PALETTE = ["#2d7ff9", "#e8590c", "#2f9e44", "#9c36b5", "#e03131", "#1098ad"]


class ViewManager(QObject):
    views_changed = pyqtSignal()        # 列表结构变(增删/改名/排序/改色)
    active_changed = pyqtSignal(int)
    split_changed = pyqtSignal(object)  # int 或 None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.views = [self._make(0)]
        self.active = 0
        self.split_with = None

    def _make(self, idx: int) -> ViewState:
        return ViewState(name=f"View {idx + 1}",
                         tab_color=_PALETTE[idx % len(_PALETTE)])

    def get(self, idx: int) -> ViewState:
        return self.views[idx]

    def new_view(self) -> int:
        if len(self.views) >= MAX_VIEWS:
            return -1
        self.views.append(self._make(len(self.views)))
        idx = len(self.views) - 1
        self.views_changed.emit()
        self.set_active(idx)
        return idx

    def delete_view(self, idx: int) -> None:
        if len(self.views) <= 1:
            return
        del self.views[idx]
        if self.active >= len(self.views):
            self.active = len(self.views) - 1
        elif self.active > idx:
            self.active -= 1
        self.split_with = None
        self.views_changed.emit()
        self.active_changed.emit(self.active)

    def duplicate(self, idx: int) -> int:
        if len(self.views) >= MAX_VIEWS:
            return -1
        src = self.views[idx]
        copy = ViewState.from_dict(src.to_dict())
        copy.name = f"{src.name} 副本"
        self.views.insert(idx + 1, copy)
        self.views_changed.emit()
        self.set_active(idx + 1)
        return idx + 1

    def rename(self, idx: int, name: str) -> None:
        self.views[idx].name = (name or "").strip() or "未命名"
        self.views_changed.emit()

    def set_color(self, idx: int, hex_color: str) -> None:
        self.views[idx].tab_color = hex_color
        self.views_changed.emit()

    def reorder(self, from_idx: int, to_idx: int) -> None:
        if from_idx == to_idx:
            return
        active_state = self.views[self.active]
        item = self.views.pop(from_idx)
        self.views.insert(to_idx, item)
        self.active = self.views.index(active_state)
        self.views_changed.emit()

    def set_active(self, idx: int) -> None:
        self.active = idx
        if self.split_with is not None:
            self.split_with = None
            self.split_changed.emit(None)
        self.active_changed.emit(idx)

    def set_split(self, idx) -> None:
        if idx is not None and idx == self.active:
            return
        self.split_with = idx
        self.split_changed.emit(idx)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/ui/test_view_manager.py -v`
Expected: PASS(8 passed)

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/view_state.py tests/ui/test_view_manager.py
git commit -m "feat(view): add ViewManager list logic with 6-view cap"
```

---

## Task 3: 通道 widget 的写回接口 + canvas 读 xlim

**Files:**
- Modify: `mf4_analyzer/ui/widgets/__init__.py`(`MultiFileChannelWidget`,在 `get_checked_channels` 后,约 :317)
- Modify: `mf4_analyzer/ui/file_navigator.py`(`FileNavigator`,在 :232 后)
- Modify: `mf4_analyzer/ui/pg_canvases.py`(`TimeDomainCanvasPG`,在 `set_xlim` 即 :1870 附近)
- Test: `tests/ui/test_channel_widget_setters.py`

> **先去重**:`grep -n "def set_checked_channels\|def set_channel_colors\|def get_channel_colors" mf4_analyzer/ui/widgets/__init__.py` 必须为空再加。

- [ ] **Step 1: 写失败测试**

```python
# tests/ui/test_channel_widget_setters.py
import numpy as np, pandas as pd, pytest
from mf4_analyzer.ui.widgets import MultiFileChannelWidget


class _FD:
    def __init__(self):
        self.data = pd.DataFrame({"rpm": np.arange(5.0), "spd": np.arange(5.0)})
        self.time_array = np.arange(5.0)
        self.fs = 1.0
    def get_signal_channels(self): return ["rpm", "spd"]
    def get_color_palette(self): return ["#111111", "#222222"]


def test_set_checked_channels_roundtrip(qtbot):
    w = MultiFileChannelWidget(); qtbot.addWidget(w)
    w.add_file("f1", _FD())
    w.set_checked_channels([("f1", "spd")])
    assert [(f, c) for f, c, _ in w.get_checked_channels()] == [("f1", "spd")]


def test_set_checked_channels_is_silent(qtbot):
    w = MultiFileChannelWidget(); qtbot.addWidget(w)
    w.add_file("f1", _FD())
    fired = []
    w.channels_changed.connect(lambda: fired.append(1))
    w.set_checked_channels([("f1", "rpm")])
    assert fired == []          # 写回不得触发 channels_changed


def test_color_roundtrip(qtbot):
    w = MultiFileChannelWidget(); qtbot.addWidget(w)
    w.add_file("f1", _FD())
    w.set_channel_colors({("f1", "rpm"): "#abcdef"})
    assert w.get_channel_colors()[("f1", "rpm")] == "#abcdef"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/ui/test_channel_widget_setters.py -v`
Expected: FAIL — `AttributeError: 'MultiFileChannelWidget' object has no attribute 'set_checked_channels'`

- [ ] **Step 3: 实现 widget 写回方法**

`MultiFileChannelWidget`(widgets/__init__.py,紧接 `get_checked_channels` 之后)新增。`_swatch_icon` 已在本模块定义(`add_file` 里用过):

```python
    def set_checked_channels(self, checked):
        """批量设勾选,checked 为可迭代的 (fid, ch);静默(不发 channels_changed)。"""
        wanted = set(checked)
        self._updating = True
        try:
            for fid, fi in self._file_items.items():
                all_on = fi.childCount() > 0
                for i in range(fi.childCount()):
                    ci = fi.child(i)
                    d = ci.data(0, Qt.UserRole)
                    on = bool(d and d[0] == 'channel' and (d[1], d[2]) in wanted)
                    ci.setCheckState(0, Qt.Checked if on else Qt.Unchecked)
                    all_on = all_on and on
                fi.setCheckState(0, Qt.Checked if all_on else Qt.Unchecked)
        finally:
            self._updating = False

    def get_channel_colors(self):
        return dict(self._colors)

    def set_channel_colors(self, colors):
        """写回颜色并刷新色块图标;colors 为 {(fid,ch): hex}。"""
        for (fid, ch), hex_color in colors.items():
            self._colors[(fid, ch)] = hex_color
        for fid, fi in self._file_items.items():
            for i in range(fi.childCount()):
                ci = fi.child(i)
                d = ci.data(0, Qt.UserRole)
                if d and d[0] == 'channel' and (d[1], d[2]) in self._colors:
                    ci.setIcon(0, _swatch_icon(self._colors[(d[1], d[2])]))
```

`FileNavigator`(file_navigator.py,紧接 `get_checked_channels` :232 之后)委托:

```python
    def set_checked_channels(self, checked):
        self.channel_list.set_checked_channels(checked)

    def get_channel_colors(self):
        return self.channel_list.get_channel_colors()

    def set_channel_colors(self, colors):
        self.channel_list.set_channel_colors(colors)
```

`TimeDomainCanvasPG`(pg_canvases.py,`set_xlim` 即 :1870 附近)新增读接口:

```python
    def get_visible_xlim(self):
        """当前可见 X 范围 (lo, hi);无绘图时返回 None。"""
        ax = self._primary_xaxis_ax
        if ax is None:
            return None
        return ax.get_xlim()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/ui/test_channel_widget_setters.py -v`
Expected: PASS(3 passed)

- [ ] **Step 5: DRY —— 让 `main_window._restore_checked_channels` 复用新方法**

把 `main_window.py` 的 `_restore_checked_channels`(:991)实现体替换为一行委托(去重逻辑):

```python
    def _restore_checked_channels(self, checked):
        self.channel_list.set_checked_channels(checked)
```

- [ ] **Step 6: 跑回归确认没破坏**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/ui -q`
Expected: PASS(无新增失败)

- [ ] **Step 7: 提交**

```bash
git add mf4_analyzer/ui/widgets/__init__.py mf4_analyzer/ui/file_navigator.py mf4_analyzer/ui/pg_canvases.py mf4_analyzer/ui/main_window.py tests/ui/test_channel_widget_setters.py
git commit -m "feat(view): channel-widget setters + canvas get_visible_xlim"
```

---

## Task 4: `ViewCaptureBridge` 抓取/写回

**Files:**
- Create: `mf4_analyzer/ui/view_bridge.py`
- Test: `tests/ui/test_view_bridge.py`

> 约定:`chart_stack` 需有 `plot_mode()`(已存在 :1019 调用)、`cursor_mode()`(Task 6 补)、`set_plot_mode()`/`set_cursor_mode()`(已存在),`canvas_time` 暴露 `get_visible_xlim()`/`set_xlim()`。bridge 只读写状态,不负责重绘(重绘由 MainWindow 触发)。

- [ ] **Step 1: 写失败测试(用轻量假对象)**

```python
# tests/ui/test_view_bridge.py
from mf4_analyzer.ui.view_state import ViewState
from mf4_analyzer.ui import view_bridge


class _Nav:
    def __init__(self):
        self._checked = [("f1", "rpm", "#111")]
        self._colors = {("f1", "rpm"): "#111"}
        self.set_checked = None
        self.set_colors = None
    def get_checked_channels(self): return list(self._checked)
    def get_channel_colors(self): return dict(self._colors)
    def set_checked_channels(self, c): self.set_checked = list(c)
    def set_channel_colors(self, c): self.set_colors = dict(c)


class _Canvas:
    def __init__(self): self._xlim = (0.0, 9.0); self.applied = None
    def get_visible_xlim(self): return self._xlim
    def set_xlim(self, lo, hi): self.applied = (lo, hi)


class _Stack:
    def __init__(self):
        self.canvas_time = _Canvas(); self._pm = "overlay"; self._cm = "single"
    def plot_mode(self): return self._pm
    def cursor_mode(self): return self._cm
    def set_plot_mode(self, m): self._pm = m
    def set_cursor_mode(self, m): self._cm = m


def test_capture_reads_full_state():
    st = view_bridge.capture_view(_Nav(), _Stack())
    assert st.checked == [("f1", "rpm")]
    assert st.colors == {("f1", "rpm"): "#111"}
    assert st.plot_mode == "overlay"
    assert st.cursor["mode"] == "single"
    assert st.xlim == (0.0, 9.0)


def test_apply_writes_widget_state():
    nav, stack = _Nav(), _Stack()
    st = ViewState(name="v", tab_color="#000",
                   checked=[("f1", "rpm")], colors={("f1", "rpm"): "#abc"},
                   plot_mode="subplot", cursor={"mode": "off", "positions": []})
    view_bridge.apply_view(st, nav, stack)
    assert nav.set_colors == {("f1", "rpm"): "#abc"}
    assert nav.set_checked == [("f1", "rpm")]
    assert stack._pm == "subplot"
    assert stack._cm == "off"


def test_restore_axes_sets_xlim():
    stack = _Stack()
    st = ViewState(name="v", tab_color="#000", xlim=(2.0, 5.0))
    view_bridge.restore_axes(st, stack)
    assert stack.canvas_time.applied == (2.0, 5.0)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/ui/test_view_bridge.py -v`
Expected: FAIL — `ModuleNotFoundError: mf4_analyzer.ui.view_bridge`

- [ ] **Step 3: 实现 bridge**

```python
# mf4_analyzer/ui/view_bridge.py
"""View 状态的抓取/写回桥。唯一懂各 widget 内部读写的地方。

- capture_view: 从 navigator + chart_stack 读出一份 ViewState。
- apply_view:   把 ViewState 写回 widget(勾选/颜色/模式/游标),不重绘。
- restore_axes: 重绘后恢复坐标轴范围。
重绘本身由 MainWindow 在 apply_view 与 restore_axes 之间用现有路径触发。
"""
from .view_state import ViewState


def capture_view(navigator, chart_stack) -> ViewState:
    checked_color = navigator.get_checked_channels()      # [(fid, ch, color)]
    checked = [(f, c) for f, c, _ in checked_color]
    colors = {(f, c): col for f, c, col in checked_color}
    canvas = chart_stack.canvas_time
    return ViewState(
        name="", tab_color="",
        checked=checked, colors=colors,
        plot_mode=chart_stack.plot_mode(),
        cursor={"mode": chart_stack.cursor_mode(), "positions": []},
        xlim=canvas.get_visible_xlim(),
    )


def capture_into(state: ViewState, navigator, chart_stack) -> None:
    """抓取当前界面写进已存在的 state,保留其 name/tab_color。"""
    fresh = capture_view(navigator, chart_stack)
    state.checked = fresh.checked
    state.colors = fresh.colors
    state.plot_mode = fresh.plot_mode
    state.cursor = fresh.cursor
    state.xlim = fresh.xlim
    state.ylims = fresh.ylims
    state.axis_opts = fresh.axis_opts


def apply_view(state: ViewState, navigator, chart_stack) -> None:
    navigator.set_channel_colors(state.colors)
    navigator.set_checked_channels(state.checked)
    chart_stack.set_plot_mode(state.plot_mode)
    chart_stack.set_cursor_mode(state.cursor.get("mode", "off"))


def restore_axes(state: ViewState, chart_stack) -> None:
    if state.xlim is not None:
        chart_stack.canvas_time.set_xlim(*state.xlim)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/ui/test_view_bridge.py -v`
Expected: PASS(3 passed)

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/view_bridge.py tests/ui/test_view_bridge.py
git commit -m "feat(view): add capture/apply/restore bridge"
```

---

## Task 5: `ViewTabBar` Excel 标签栏 UI

**Files:**
- Create: `mf4_analyzer/ui/view_tabbar.py`
- Test: `tests/ui/test_view_tabbar.py`

行为:由 `ViewManager` 渲染标签;只发信号(`switch_requested(int)` / `new_requested()` / `delete_requested(int)` / `rename_requested(int,str)` / `duplicate_requested(int)` / `color_requested(int)` / `reorder_requested(int,int)` / `split_requested(int)`),不直接改 manager。双击改名走内嵌 `QLineEdit`;右键弹菜单;拖动用 `QTabBar.setMovable(True)` 的 `tabMoved` 信号转 `reorder_requested`。

- [ ] **Step 1: 写失败测试**

```python
# tests/ui/test_view_tabbar.py
import pytest
from mf4_analyzer.ui.view_state import ViewManager
from mf4_analyzer.ui.view_tabbar import ViewTabBar


def _bar(qtbot):
    m = ViewManager(); m.new_view()           # 2 个 view
    bar = ViewTabBar(m); qtbot.addWidget(bar)
    return m, bar


def test_renders_one_tab_per_view(qtbot):
    m, bar = _bar(qtbot)
    assert bar.count() == 2


def test_click_other_tab_emits_switch(qtbot):
    m, bar = _bar(qtbot)
    with qtbot.waitSignal(bar.switch_requested) as sig:
        bar.setCurrentIndex(1)
    assert sig.args == [1]


def test_plus_button_emits_new(qtbot):
    m, bar = _bar(qtbot)
    with qtbot.waitSignal(bar.new_requested):
        bar._on_plus_clicked()


def test_views_changed_rerenders(qtbot):
    m, bar = _bar(qtbot)
    m.new_view()                              # 现在 3 个
    m.views_changed.emit()
    assert bar.count() == 3


def test_tab_moved_emits_reorder(qtbot):
    m, bar = _bar(qtbot)
    with qtbot.waitSignal(bar.reorder_requested) as sig:
        bar.tabBar().moveTab(0, 1) if hasattr(bar, "tabBar") else bar._emit_reorder(0, 1)
    assert sig.args == [0, 1]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/ui/test_view_tabbar.py -v`
Expected: FAIL — `ModuleNotFoundError: mf4_analyzer.ui.view_tabbar`

- [ ] **Step 3: 实现 `ViewTabBar`**

```python
# mf4_analyzer/ui/view_tabbar.py
"""时域底部 Excel 风格 View 标签栏。由 ViewManager 渲染,只发意图信号。"""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout, QInputDialog, QMenu, QPushButton, QTabBar, QWidget,
)


class ViewTabBar(QWidget):
    switch_requested = pyqtSignal(int)
    new_requested = pyqtSignal()
    delete_requested = pyqtSignal(int)
    rename_requested = pyqtSignal(int, str)
    duplicate_requested = pyqtSignal(int)
    color_requested = pyqtSignal(int)
    reorder_requested = pyqtSignal(int, int)
    split_requested = pyqtSignal(int)

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.setObjectName("viewTabBar")
        self._m = manager
        self._suppress = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(2)

        self._tabs = QTabBar(self)
        self._tabs.setObjectName("viewTabs")
        self._tabs.setMovable(True)
        self._tabs.setExpanding(False)
        self._tabs.setDrawBase(False)
        self._tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tabs.currentChanged.connect(self._on_current_changed)
        self._tabs.tabBarDoubleClicked.connect(self._on_double_clicked)
        self._tabs.tabMoved.connect(self._on_tab_moved)
        self._tabs.customContextMenuRequested.connect(self._on_context_menu)
        lay.addWidget(self._tabs)

        self._plus = QPushButton("＋", self)
        self._plus.setObjectName("viewTabPlus")
        self._plus.setFixedWidth(28)
        self._plus.clicked.connect(self._on_plus_clicked)
        lay.addWidget(self._plus)
        lay.addStretch(1)

        self._split = QPushButton("⊞ 并排", self)
        self._split.setObjectName("viewTabSplit")
        self._split.clicked.connect(self._on_split_clicked)
        lay.addWidget(self._split)

        manager.views_changed.connect(self.refresh)
        manager.active_changed.connect(self._sync_active)
        self.refresh()

    # ---- rendering ----
    def count(self):
        return self._tabs.count()

    def tabBar(self):
        return self._tabs

    def refresh(self):
        self._suppress = True
        try:
            while self._tabs.count():
                self._tabs.removeTab(0)
            for v in self._m.views:
                self._tabs.addTab(v.name)
            self._tabs.setCurrentIndex(self._m.active)
        finally:
            self._suppress = False
        self._plus.setEnabled(len(self._m.views) < self._max())

    def _max(self):
        from .view_state import MAX_VIEWS
        return MAX_VIEWS

    def _sync_active(self, idx):
        self._suppress = True
        self._tabs.setCurrentIndex(idx)
        self._suppress = False

    # ---- intent emitters ----
    def _on_current_changed(self, idx):
        if not self._suppress and idx >= 0:
            self.switch_requested.emit(idx)

    def _on_plus_clicked(self):
        self.new_requested.emit()

    def _on_split_clicked(self):
        cur = self._tabs.currentIndex()
        self.split_requested.emit(cur)

    def _on_double_clicked(self, idx):
        if idx < 0:
            return
        text, ok = QInputDialog.getText(
            self, "重命名 View", "名称:", text=self._tabs.tabText(idx))
        if ok:
            self.rename_requested.emit(idx, text)

    def _on_tab_moved(self, frm, to):
        if not self._suppress:
            self._emit_reorder(frm, to)

    def _emit_reorder(self, frm, to):
        self.reorder_requested.emit(frm, to)

    def _on_context_menu(self, pos):
        idx = self._tabs.tabAt(pos)
        if idx < 0:
            return
        menu = QMenu(self)
        act_rename = menu.addAction("重命名")
        act_dup = menu.addAction("复制此 View")
        act_color = menu.addAction("改标签颜色…")
        menu.addSeparator()
        act_split = menu.addAction("与右侧 View 并排")
        menu.addSeparator()
        act_del = menu.addAction("删除")
        act_del.setEnabled(len(self._m.views) > 1)
        chosen = menu.exec_(self._tabs.mapToGlobal(pos))
        if chosen is act_rename:
            self._on_double_clicked(idx)
        elif chosen is act_dup:
            self.duplicate_requested.emit(idx)
        elif chosen is act_color:
            self.color_requested.emit(idx)
        elif chosen is act_split:
            self.split_requested.emit(idx)
        elif chosen is act_del:
            self.delete_requested.emit(idx)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/ui/test_view_tabbar.py -v`
Expected: PASS(5 passed)

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/view_tabbar.py tests/ui/test_view_tabbar.py
git commit -m "feat(view): Excel-style ViewTabBar widget"
```

---

## Task 6: 把标签栏插进 `TimeChartCard` + `ChartStack` 暴露接口

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py`(`TimeChartCard.__init__` 末尾 ~:1244;`ChartStack` ~:1340)
- Test: `tests/ui/test_view_tabbar_mount.py`

> **先去重**:`grep -n "def cursor_mode\b\|def set_view_manager\|def set_time_tabbar_visible" mf4_analyzer/ui/chart_stack.py` 应为空。

- [ ] **Step 1: 写失败测试**

```python
# tests/ui/test_view_tabbar_mount.py
import pytest
from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.view_state import ViewManager
from mf4_analyzer.ui.view_tabbar import ViewTabBar


def test_chartstack_mounts_tabbar_in_time_card(qtbot):
    cs = ChartStack(); qtbot.addWidget(cs)
    m = ViewManager()
    bar = cs.attach_view_tabbar(m)
    assert isinstance(bar, ViewTabBar)
    # 标签栏在时域 card 的布局里、位于 hint bar 之前
    card = cs._time_card
    lay = card.layout()
    assert lay.indexOf(bar) == lay.indexOf(card._hint_bar) - 1


def test_chartstack_exposes_cursor_mode(qtbot):
    cs = ChartStack(); qtbot.addWidget(cs)
    cs.set_cursor_mode("single")
    assert cs.cursor_mode() == "single"


def test_tabbar_hidden_outside_time_mode(qtbot):
    cs = ChartStack(); qtbot.addWidget(cs)
    bar = cs.attach_view_tabbar(ViewManager())
    cs.set_mode("fft")
    assert not bar.isVisible()
    cs.set_mode("time")
    assert bar.isVisible()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/ui/test_view_tabbar_mount.py -v`
Expected: FAIL — `AttributeError: 'ChartStack' object has no attribute 'attach_view_tabbar'`

- [ ] **Step 3a: `TimeChartCard` 暴露挂载点**

在 `TimeChartCard.__init__` 末尾(~:1244)追加:

```python
        self.view_tabbar = None

    def mount_view_tabbar(self, bar):
        """把 ViewTabBar 插到 canvas 与底部 hint bar 之间。"""
        self.view_tabbar = bar
        bar.setParent(self)
        lay = self.layout()
        lay.insertWidget(lay.indexOf(self._hint_bar), bar)
```

- [ ] **Step 3b: `ChartStack` 加 `cursor_mode()` getter + 挂载 + 随模式显隐**

`cursor_mode()`:先 `grep -n "def cursor_mode" chart_stack.py` 确认无重复;若 `set_cursor_mode` 已委托给 `_time_card`,getter 同样委托:

```python
    def cursor_mode(self):
        return self._time_card.cursor_mode()

    def attach_view_tabbar(self, manager):
        from .view_tabbar import ViewTabBar
        bar = ViewTabBar(manager, self._time_card)
        self._time_card.mount_view_tabbar(bar)
        self._view_tabbar = bar
        bar.setVisible(self.current_mode() == 'time')
        return bar
```

在 `ChartStack.set_mode`(:1419)末尾追加显隐:

```python
        bar = getattr(self, '_view_tabbar', None)
        if bar is not None:
            bar.setVisible(mode == 'time')
```

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/ui/test_view_tabbar_mount.py -v`
Expected: PASS(3 passed)

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/chart_stack.py tests/ui/test_view_tabbar_mount.py
git commit -m "feat(view): mount ViewTabBar in TimeChartCard + cursor_mode getter"
```

---

## Task 7: 在 `MainWindow` 编排切换

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`(`__init__` 接线区 ~:284-330;新增 `_switch_view` 等方法)
- Test: `tests/ui/test_view_switch_integration.py`

> **先去重**:`grep -n "def _switch_view\|def _on_view_" main_window.py` 应为空。

- [ ] **Step 1: 写失败测试(端到端:勾通道→切view→切回保真)**

```python
# tests/ui/test_view_switch_integration.py
import numpy as np, pandas as pd, pytest
from mf4_analyzer.ui.main_window import MainWindow


class _FD:
    def __init__(self):
        self.data = pd.DataFrame({"rpm": np.arange(50.0), "spd": np.arange(50.0)})
        self.time_array = np.arange(50.0); self.fs = 1.0
        self.channel_units = {"rpm": "", "spd": ""}
        self.filepath = None; self.filename = "f.mf4"
    def get_signal_channels(self): return ["rpm", "spd"]
    def get_color_palette(self): return ["#111111", "#222222"]
    def get_prefixed_channel(self, ch): return f"f::{ch}"


@pytest.fixture
def win(qtbot):
    w = MainWindow(); qtbot.addWidget(w)
    w._add_loaded_file("f1", _FD()) if hasattr(w, "_add_loaded_file") else None
    return w


def test_switch_view_preserves_per_view_channels(qtbot, win):
    # view1 勾 rpm
    win.navigator.set_checked_channels([("f1", "rpm")])
    win._ch_changed()
    win.view_manager.new_view()                  # 自动切到 view2(空)
    win.navigator.set_checked_channels([("f1", "spd")])
    win._ch_changed()
    # 切回 view1 应恢复 rpm
    win._switch_view(0)
    got = {(f, c) for f, c, _ in win.navigator.get_checked_channels()}
    assert got == {("f1", "rpm")}
    # 再切到 view2 应恢复 spd
    win._switch_view(1)
    got = {(f, c) for f, c, _ in win.navigator.get_checked_channels()}
    assert got == {("f1", "spd")}
```

> 注:`_add_loaded_file` 的真实加载入口名以仓库为准(执行时 `grep -n "def .*add.*file\|def open_file\|def _load" main_window.py` 确认),测试 fixture 按真实入口改写。

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/ui/test_view_switch_integration.py -v`
Expected: FAIL — `AttributeError: 'MainWindow' object has no attribute 'view_manager'`

- [ ] **Step 3: 接线 + 编排方法**

在 `MainWindow.__init__` 接线区(navigator/chart_stack 已建之后,~:290)加:

```python
        from .view_state import ViewManager
        from . import view_bridge
        self.view_manager = ViewManager(self)
        self._view_bridge = view_bridge
        self.view_tabbar = self.chart_stack.attach_view_tabbar(self.view_manager)
        self.view_tabbar.switch_requested.connect(self._switch_view)
        self.view_tabbar.new_requested.connect(self._on_view_new)
        self.view_tabbar.delete_requested.connect(self._on_view_delete)
        self.view_tabbar.duplicate_requested.connect(self.view_manager.duplicate)
        self.view_tabbar.rename_requested.connect(self.view_manager.rename)
        self.view_tabbar.color_requested.connect(self._on_view_color)
        self.view_tabbar.reorder_requested.connect(self.view_manager.reorder)
        # new/duplicate/delete 改 active 后,manager.active_changed 触发实际应用
        self.view_manager.active_changed.connect(self._apply_active_view)
```

新增方法(放在 `_ch_changed` 附近):

```python
    def _capture_current_view(self):
        cur = self.view_manager.get(self.view_manager.active)
        self._view_bridge.capture_into(cur, self.navigator, self.chart_stack)

    def _switch_view(self, idx):
        if idx == self.view_manager.active:
            return
        self._capture_current_view()
        self.view_manager.set_active(idx)      # → active_changed → _apply_active_view

    def _apply_active_view(self, idx):
        st = self.view_manager.get(idx)
        self._view_bridge.apply_view(st, self.navigator, self.chart_stack)
        if self.files and self.chart_stack.current_mode() == 'time':
            self.plot_time()                   # 全量重绘出活画布
            self._view_bridge.restore_axes(st, self.chart_stack)

    def _on_view_new(self):
        self._capture_current_view()
        self.view_manager.new_view()           # 内部 set_active → _apply_active_view

    def _on_view_delete(self, idx):
        self.view_manager.delete_view(idx)     # 内部 active_changed → _apply_active_view

    def _on_view_color(self, idx):
        from PyQt5.QtWidgets import QColorDialog
        col = QColorDialog.getColor(parent=self)
        if col.isValid():
            self.view_manager.set_color(idx, col.name())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/ui/test_view_switch_integration.py -v`
Expected: PASS

- [ ] **Step 5: 全量回归 + 视觉验真**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/ui -q`
Expected: PASS(无新增失败)

手动:`python "MF4 Data Analyzer V1.py"` → 加载 mf4 → 勾通道、缩放 → ＋新建 → 勾另一组 → 来回切标签,确认①切回是**可缩放的活画布**、②勾选/模式/缩放都恢复、③双击改名/右键菜单/拖动排序/改色都生效。**截图留档**。

- [ ] **Step 6: 提交**

```bash
git add mf4_analyzer/ui/main_window.py tests/ui/test_view_switch_integration.py
git commit -m "feat(view): wire ViewTabBar switching in MainWindow (P1 complete)"
```

---

# 里程碑 P2 — 并排对比

## Task 8: 时域画布区可分屏容器

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py`(`ChartStack`:把时域 card 包进可放 1/2 画布的 `QSplitter`;懒建第二画布)
- Test: `tests/ui/test_split_container.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/ui/test_split_container.py
import pytest
from mf4_analyzer.ui.chart_stack import ChartStack


def test_split_shows_two_panes(qtbot):
    cs = ChartStack(); qtbot.addWidget(cs)
    assert cs.split_active() is False
    cs.enter_split()
    assert cs.split_active() is True
    assert cs.secondary_canvas() is not None    # 懒建成功
    cs.exit_split()
    assert cs.split_active() is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/ui/test_split_container.py -v`
Expected: FAIL — `AttributeError: 'ChartStack' object has no attribute 'enter_split'`

- [ ] **Step 3: 实现分屏容器**

在 `ChartStack` 中,把原本直接加入 stack 的时域 card 改为放进一个横向 `QSplitter`(`self._time_split`),左栏 = 现有 `_time_card`;`enter_split` 时懒建第二个 `TimeDomainCanvasPG` + `TimeChartCard` 加到右栏,`exit_split` 时隐藏右栏。代码:

```python
    # ChartStack.__init__ 中,原 self._time_card 加入 stack 处改为:
    from PyQt5.QtWidgets import QSplitter
    self._time_split = QSplitter(Qt.Horizontal)
    self._time_split.addWidget(self._time_card)
    self._secondary_card = None
    # ...把 self._time_split(而非 self._time_card)作为 time 页加进 central stack

    def split_active(self):
        return self._secondary_card is not None and self._secondary_card.isVisible()

    def secondary_canvas(self):
        return None if self._secondary_card is None else self._secondary_card.canvas

    def enter_split(self):
        if self._secondary_card is None:
            canvas2 = TimeDomainCanvasPG(self)
            self._secondary_card = TimeChartCard(canvas2)
            self._time_split.addWidget(self._secondary_card)
            self._time_split.setSizes([1, 1])
        self._secondary_card.setVisible(True)

    def exit_split(self):
        if self._secondary_card is not None:
            self._secondary_card.setVisible(False)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/ui/test_split_container.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add mf4_analyzer/ui/chart_stack.py tests/ui/test_split_container.py
git commit -m "feat(view): splittable time-domain canvas container"
```

---

## Task 9: 并排渲染 + 聚焦路由 + 退出

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`(响应 `split_changed`;把对比 view 渲染进副画布)
- Modify: `mf4_analyzer/ui/chart_stack.py`(聚焦栏高亮 + `focused_card()`)
- Test: `tests/ui/test_split_routing.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/ui/test_split_routing.py
import numpy as np, pandas as pd, pytest
from mf4_analyzer.ui.main_window import MainWindow
from tests.ui.test_view_switch_integration import _FD   # 复用假文件


@pytest.fixture
def win(qtbot):
    w = MainWindow(); qtbot.addWidget(w)
    return w


def test_split_renders_compare_view_and_switch_exits(qtbot, win):
    win.view_manager.new_view()                # view2
    win.view_manager.set_active(0)
    win.view_manager.set_split(1)              # → split_changed(1)
    assert win.chart_stack.split_active() is True
    # 切任意标签退出并排
    win._switch_view(1)
    assert win.chart_stack.split_active() is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/ui/test_split_routing.py -v`
Expected: FAIL — split 未接线,`split_active()` 仍 False

- [ ] **Step 3: 接线并排**

`MainWindow.__init__` 接线区追加:

```python
        self.view_manager.split_changed.connect(self._on_view_split)
```

新增方法:

```python
    def _on_view_split(self, other_idx):
        if other_idx is None:
            self.chart_stack.exit_split()
            return
        self.chart_stack.enter_split()
        # 把对比 view 渲染进副画布:复用 plot_time 的数据构建,但目标是副画布
        self._render_view_into(self.view_manager.get(other_idx),
                               self.chart_stack.secondary_canvas())

    def _render_view_into(self, state, canvas):
        if canvas is None:
            return
        data = self._build_plot_data(state.checked, state.colors)
        canvas.plot_channels(data, state.plot_mode, xlabel='Time (s)')
        if state.xlim is not None:
            canvas.set_xlim(*state.xlim)
```

把 `plot_time`(:1014)里"构建 data 列表"那段(:1083-1111)抽成可复用的 `_build_plot_data(checked, colors)` 并让 `plot_time` 调用它(DRY 重构,行为不变);`_render_view_into` 也调它。

- [ ] **Step 4: 跑测试确认通过**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/ui/test_split_routing.py -v`
Expected: PASS

- [ ] **Step 5: 聚焦路由(点哪栏,toolbar/inspector/勾选作用于哪栏)+ 高亮**

`ChartStack` 加 `focused_card()`(默认主 card;副 card 被点时切换),聚焦 card 加边框样式(`setProperty("focused", True)` + 样式表)。`MainWindow` 的 `plot_time` / `_ch_changed` 把目标画布从写死的 `self.canvas_time` 改为 `self.chart_stack.focused_canvas()`(并排时指向聚焦栏;非并排时即主画布)。本步先做主→副点击切换 + 高亮 + 勾选路由,游标/工具栏路由作为同里程碑后续微调。

- [ ] **Step 6: 全量回归 + 视觉验真**

Run: `QT_QPA_PLATFORM=offscreen pytest tests/ui -q`
手动:并排两个不同 view,确认左右内容正确、点击切换聚焦栏有高亮、对聚焦栏的勾选/缩放只影响该栏。**截图留档**。

- [ ] **Step 7: 提交**

```bash
git add mf4_analyzer/ui/main_window.py mf4_analyzer/ui/chart_stack.py tests/ui/test_split_routing.py
git commit -m "feat(view): side-by-side compare rendering + focus routing (P2 complete)"
```

---

# 里程碑 P3(本期不做)— project 落盘

`ViewState` 已可 JSON 往返(Task 1)。未来落盘只需把 `view_manager.views` 整体 `to_dict()` 写进 project 文件,打开时 `from_dict()` + 逐个 `_apply_active_view`。无需改本计划任何结构。

---

# 自检(spec 覆盖核对)

- spec §3.1 ViewState 字段 → Task 1 ✓(ylims/axis_opts 字段已建;P1 捕获 channels/colors/mode/cursor/xlim,ylims/axis_opts 的**实际捕获**留待 Task 9 后的微调或 P3,字段与序列化已就位,不阻塞)。
- spec §3.2 ViewManager → Task 2 ✓
- spec §4 组件边界 → Task 1/4/5/6/7 ✓
- spec §5 切换数据流 → Task 7 ✓
- spec §6 并排 → Task 8/9 ✓
- spec §7 UI 落点 → Task 6(标签栏插入)+ Task 3(setter)✓
- spec §8 测试 → 每 Task 含纯/UI 测 + P1/P2 末视觉验真 ✓
- spec §10 风险 → 每个改 chart_stack/main_window 的 Task 顶部"先去重"提示 ✓

> **已知留白(非占位符,是范围决定)**:`ylims` / `axis_opts` 的实际抓取与恢复在 P1 不实现(字段与序列化已建好),按 spec §11 分期归入后续;若执行中发现 Y 缩放保真是刚需,在 Task 9 后追加一个对称的 `capture/restore_ylims` 小 Task(用 `canvas.axes_list` 各 handle 的 `get_ylim/set_ylim`,按绘制顺序索引对齐)。
