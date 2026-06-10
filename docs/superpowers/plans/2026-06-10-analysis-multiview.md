# 分析区多视图层（P4）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **前置依赖：** `2026-06-10-analysis-canvas-migration.md`（P1–P3）已全部落地——
> 三个分析画布均为 pyqtgraph（`PgHeatmapCanvas` / `PgLineCanvas`）。
> **CLAUDE.md squad 约定：** 状态/缓存/持久化任务可由 `refactor-architect` 或
> `pyqt-ui-engineer` 执行；所有 UI 接线任务归 `pyqt-ui-engineer`。

**Goal:** FFT / FFT-vs-Time / Order 三个 section 各自获得独立多 view（标签页），view 内支持 split 2 格、FFT 格内 overlay N 条曲线，并带四项对比增强（联动缩放、锁定色阶、FFT 游标 Δ 读数、per-view 结果缓存）与工程文件持久化。

**Architecture:** 四层模型 Section → View → Pane → Source。新数据类 `AnalysisViewState`/`PaneState`（每 section 一个 `ViewManager(state_factory=AnalysisViewState)` 实例）；ChartStack 三个分析页改造为 `AnalysisSectionPage`（QSplitter pane 容器 + 复用 `ViewTabBar`）；参数经 per-section bridge 在 Contextual ↔ ViewState 间 capture/apply。时域 section 代码路径零接触（红线）。

**Tech Stack:** PyQt5、pyqtgraph、现有 `ViewTabBar`/`ViewManager` 基建、pytest + pytest-qt。

**对应 spec：** `docs/superpowers/specs/2026-06-10-analysis-multiview-pyqtgraph-design.md` §3、§4、§6、§9（持久化）、§10（P4）、§11。

**关键既有事实：**

- `ViewManager._make`（`view_state.py:108`）硬编码 `ViewState`；`duplicate`（`:157`）用 `ViewState.from_dict`。泛化点就这两处。
- `ViewTabBar` 信号面（`view_tabbar.py:29-37`）：`switch/new/delete/rename/duplicate/color/reorder/split/clear_split_requested`。
- `ProjectDocument`（`project_io.py:32-37`）字段 `views` + `view_manager`；`remap_view_fids`（`:126`）。
- 参数回填接口已存在：`FFTContextual.apply_params`（`inspector_sections.py:2072`）、`FFTTimeContextual.apply_params`（`:2500`）。**OrderContextual 若无 `apply_params`，照 :2072 的模式补一个（Task 5 内含）。**
- navigator 跨文件勾选：`navigator.get_checked_channels()` → `[(fid, ch, color), ...]`；回填 `set_checked_channels`（`widgets/__init__.py:373-400`）。
- FFT-vs-Time LRU 缓存现状：`main_window.py:100-101`（`_fft_time_cache`, capacity 12，display-only 参数不进键）。
- 时域焦点路由模式：`_focused_card` + eventFilter（`chart_stack.py:1681-1688`）。

---

## Task 1: `PaneState` / `AnalysisViewState` 数据模型

**Files:**
- Create: `mf4_analyzer/ui/analysis_view_state.py`
- Test: `tests/ui/test_analysis_view_state.py`

- [ ] **Step 1: 写失败测试**

```python
"""AnalysisViewState/PaneState: model + serialization round-trip."""
import pytest

from mf4_analyzer.ui.analysis_view_state import AnalysisViewState, PaneState


def test_default_view_one_empty_pane():
    v = AnalysisViewState(name="View 1", tab_color="#2d7ff9")
    assert len(v.panes) == 1
    assert v.panes[0].sources == []
    assert v.compare == {"x_linked": True, "levels_locked": True}


def test_round_trip_preserves_everything():
    v = AnalysisViewState(name="对比", tab_color="#e8590c")
    v.panes = [
        PaneState(sources=[("f1", "vib_x"), ("f2", "vib_x")]),
        PaneState(sources=[("f1", "vib_y")], rpm_source=("f1", "rpm")),
    ]
    v.params = {"nfft": 4096, "window": "hanning"}
    v.compare = {"x_linked": False, "levels_locked": True}
    v2 = AnalysisViewState.from_dict(v.to_dict())
    assert v2.name == "对比"
    assert v2.panes[0].sources == [("f1", "vib_x"), ("f2", "vib_x")]
    assert v2.panes[1].rpm_source == ("f1", "rpm")
    assert v2.params["nfft"] == 4096
    assert v2.compare["x_linked"] is False


def test_from_dict_tolerates_missing_fields():
    v = AnalysisViewState.from_dict({"name": "x", "tab_color": "#fff"})
    assert v.panes[0].sources == []
    assert v.params == {}


def test_overlay_validation():
    v = AnalysisViewState(name="v", tab_color="#fff")
    v.panes[0].sources = [("f1", "a"), ("f1", "b")]
    assert v.validate(allow_overlay=True) == []
    errs = v.validate(allow_overlay=False)
    assert errs and "overlay" in errs[0]


def test_pane_count_capped_at_two():
    v = AnalysisViewState(name="v", tab_color="#fff")
    assert v.add_pane() is True
    assert v.add_pane() is False
    assert len(v.panes) == 2
    v.remove_second_pane()
    assert len(v.panes) == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/ui/test_analysis_view_state.py -v`
Expected: FAIL，ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
"""Analysis-section view state: Section → View → Pane → Source.

Per-section ``ViewManager(state_factory=AnalysisViewState)`` instances
manage these. Unlike the time-domain ``ViewState``, split lives INSIDE
the view as ``panes`` (spec §3) — the time-domain ``_split_pairs``
pairing is not used for analysis sections.

Serialization mirrors view_state.py conventions (JSON-safe dicts,
``(fid, ch)`` keys as 2-lists) so project_io can persist both shapes
with one code path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ChannelKey = tuple[str, str]
MAX_PANES = 2  # spec §2: v1 caps split at 2; the model is list-shaped for later N


def _coerce_key(value: Any) -> ChannelKey:
    fid, ch = value
    return (str(fid), str(ch))


@dataclass
class PaneState:
    sources: list[ChannelKey] = field(default_factory=list)
    rpm_source: ChannelKey | None = None     # Order only
    xlim: tuple[float, float] | None = None
    ylim: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": [list(k) for k in self.sources],
            "rpm_source": list(self.rpm_source) if self.rpm_source else None,
            "xlim": list(self.xlim) if self.xlim else None,
            "ylim": list(self.ylim) if self.ylim else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PaneState":
        def pair(v):
            return (float(v[0]), float(v[1])) if v else None
        return cls(
            sources=[_coerce_key(k) for k in data.get("sources", [])],
            rpm_source=(_coerce_key(data["rpm_source"])
                        if data.get("rpm_source") else None),
            xlim=pair(data.get("xlim")),
            ylim=pair(data.get("ylim")),
        )


@dataclass
class AnalysisViewState:
    name: str
    tab_color: str
    panes: list[PaneState] = field(default_factory=lambda: [PaneState()])
    params: dict[str, Any] = field(default_factory=dict)
    compare: dict[str, bool] = field(
        default_factory=lambda: {"x_linked": True, "levels_locked": True})

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": 1,
            "name": self.name,
            "tab_color": self.tab_color,
            "panes": [p.to_dict() for p in self.panes],
            "params": dict(self.params),
            "compare": dict(self.compare),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnalysisViewState":
        panes = [PaneState.from_dict(p) for p in data.get("panes", [])]
        if not panes:
            panes = [PaneState()]
        compare = {"x_linked": True, "levels_locked": True}
        compare.update(data.get("compare", {}))
        return cls(
            name=data["name"],
            tab_color=data["tab_color"],
            panes=panes[:MAX_PANES],
            params=dict(data.get("params", {})),
            compare=compare,
        )

    # -- structure ops -------------------------------------------------
    def add_pane(self) -> bool:
        if len(self.panes) >= MAX_PANES:
            return False
        self.panes.append(PaneState())
        return True

    def remove_second_pane(self) -> None:
        del self.panes[1:]

    def validate(self, *, allow_overlay: bool) -> list[str]:
        """Heatmap sections pass allow_overlay=False (1 source per pane)."""
        errs = []
        for i, p in enumerate(self.panes):
            if not allow_overlay and len(p.sources) > 1:
                errs.append(
                    f"pane {i}: overlay ({len(p.sources)} sources) "
                    "not allowed for heatmap sections")
        return errs
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/ui/test_analysis_view_state.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/analysis_view_state.py tests/ui/test_analysis_view_state.py
git commit -m "feat(multiview): AnalysisViewState/PaneState model with round-trip serialization"
```

---

## Task 2: `ViewManager` 泛化（state_factory）

**Files:**
- Modify: `mf4_analyzer/ui/view_state.py:101-112`（`__init__`/`_make`）、`:150-164`（duplicate）
- Test: `tests/ui/test_view_manager_factory.py`

- [ ] **Step 1: 写失败测试**

```python
"""ViewManager works with a custom state_factory (analysis views)."""
from mf4_analyzer.ui.analysis_view_state import AnalysisViewState
from mf4_analyzer.ui.view_state import ViewManager, ViewState


def test_default_factory_unchanged(qapp):
    m = ViewManager()
    assert isinstance(m.views[0], ViewState)


def test_analysis_factory(qapp):
    m = ViewManager(state_factory=AnalysisViewState)
    assert isinstance(m.views[0], AnalysisViewState)
    idx = m.new_view()
    assert isinstance(m.views[idx], AnalysisViewState)


def test_duplicate_uses_factory_type(qapp):
    m = ViewManager(state_factory=AnalysisViewState)
    m.views[0].params = {"nfft": 2048}
    idx = m.duplicate(0)
    assert isinstance(m.views[idx], AnalysisViewState)
    assert m.views[idx].params == {"nfft": 2048}
    assert m.views[idx].name.endswith("副本")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/ui/test_view_manager_factory.py -v`
Expected: FAIL，`TypeError: __init__() got an unexpected keyword argument 'state_factory'`

- [ ] **Step 3: 实现（view_state.py 三处小改）**

```python
# __init__（view_state.py:101）
    def __init__(self, parent: QObject | None = None, state_factory=None):
        super().__init__(parent)
        self._state_factory = state_factory or ViewState
        self.views: list = [self._make(0)]
        ...

# _make（:108）——构造调用改为工厂
    def _make(self, idx: int):
        return self._state_factory(
            name=f"View {idx + 1}",
            tab_color=_PALETTE[idx % len(_PALETTE)],
        )

# duplicate（:157）——按源对象类型反序列化
        copied = type(source).from_dict(source.to_dict())
```

- [ ] **Step 4: 跑测试确认通过 + 时域回归**

Run: `python -m pytest tests/ui/test_view_manager_factory.py tests/ui -q -k "view"`
Expected: 新测试 3 passed；现有 view 相关测试全绿（时域零行为变化）

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/view_state.py tests/ui/test_view_manager_factory.py
git commit -m "refactor(views): ViewManager accepts state_factory; time-domain default unchanged"
```

---

## Task 3: 工程文件持久化（analysis_views）

**Files:**
- Modify: `mf4_analyzer/ui/project_io.py`（ProjectDocument、save/load、remap）
- Test: `tests/test_project_io_analysis_views.py`（与现有 project_io 测试同级目录；先 `ls tests/test_project*` 对齐位置）

- [ ] **Step 1: 写失败测试**

```python
"""project_io: analysis_views persistence + fid remap."""
from mf4_analyzer.ui.project_io import (
    ProjectDocument, load_project_from_json, remap_analysis_view_fids,
    save_project_to_json,
)


def _doc():
    return ProjectDocument(
        active_file="f1", current_mode="fft",
        analysis_views={
            "fft": {
                "active": 0,
                "views": [{
                    "schema": 1, "name": "View 1", "tab_color": "#2d7ff9",
                    "panes": [{"sources": [["f1", "vib"], ["f2", "vib"]],
                               "rpm_source": None, "xlim": None, "ylim": None}],
                    "params": {"nfft": 2048},
                    "compare": {"x_linked": True, "levels_locked": True},
                }],
            },
        },
    )


def test_round_trip(tmp_path):
    p = tmp_path / "s.tlproj"
    save_project_to_json(_doc(), p)
    loaded = load_project_from_json(p)
    assert loaded.analysis_views["fft"]["views"][0]["params"]["nfft"] == 2048


def test_old_file_without_field_defaults_empty(tmp_path):
    p = tmp_path / "old.tlproj"
    save_project_to_json(ProjectDocument(active_file=None, current_mode="time"), p)
    raw = p.read_text(encoding="utf-8")
    import json
    d = json.loads(raw)
    d.pop("analysis_views", None)
    p.write_text(json.dumps(d), encoding="utf-8")
    loaded = load_project_from_json(p)
    assert loaded.analysis_views == {}


def test_remap_drops_missing_fids():
    av = _doc().analysis_views
    out = remap_analysis_view_fids(av, {"f1": "F1"})  # f2 missing → dropped
    srcs = out["fft"]["views"][0]["panes"][0]["sources"]
    assert srcs == [["F1", "vib"]]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_project_io_analysis_views.py -v`
Expected: FAIL，`TypeError ... unexpected keyword 'analysis_views'`

- [ ] **Step 3: 实现**

`ProjectDocument`（project_io.py:32）追加字段：

```python
    # {"fft"|"fft_time"|"order": {"active": int, "views": [AnalysisViewState.to_dict()]}}
    analysis_views: dict = field(default_factory=dict)
```

`save_project_to_json` payload（:57 `"view_manager"` 行后）追加：

```python
        "analysis_views": doc.analysis_views,
```

`load_project_from_json` 返回值（:95）追加：

```python
        analysis_views=dict(raw.get("analysis_views", {})),
```

文件末尾追加 remap（key 编码同 `_encode_channel_key`）：

```python
def remap_analysis_view_fids(analysis_views: dict, fid_map: dict) -> dict:
    """Rewrite fids inside analysis_views payloads; drop refs whose fid
    is absent from ``fid_map`` (same contract as remap_view_fids)."""
    out = {}
    for section, block in (analysis_views or {}).items():
        views = []
        for view in block.get("views", []):
            v = dict(view)
            panes = []
            for pane in view.get("panes", []):
                pn = dict(pane)
                pn["sources"] = [
                    [fid_map[fid], ch]
                    for fid, ch in (tuple(s) for s in pane.get("sources", []))
                    if fid in fid_map
                ]
                rpm = pane.get("rpm_source")
                pn["rpm_source"] = (
                    [fid_map[rpm[0]], rpm[1]]
                    if rpm and rpm[0] in fid_map else None
                )
                panes.append(pn)
            v["panes"] = panes
            views.append(v)
        out[section] = {"active": int(block.get("active", 0)), "views": views}
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_project_io_analysis_views.py tests -q -k project`
Expected: 新测试 3 passed；现有 project_io 测试全绿

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/project_io.py tests/test_project_io_analysis_views.py
git commit -m "feat(project): persist per-section analysis views with fid remap"
```

---

## Task 4: `AnalysisResultCache`

**Files:**
- Create: `mf4_analyzer/ui/analysis_cache.py`
- Test: `tests/ui/test_analysis_cache.py`

- [ ] **Step 1: 写失败测试**

```python
"""AnalysisResultCache: keying, LRU eviction, fid invalidation."""
from mf4_analyzer.ui.analysis_cache import AnalysisResultCache


def test_put_get_round_trip():
    c = AnalysisResultCache(capacity=2)
    k = c.make_key("f1", "vib", {"nfft": 1024, "window": "hanning"})
    c.put(k, "RESULT")
    assert c.get(k) == "RESULT"


def test_key_ignores_order_and_is_param_sensitive():
    c = AnalysisResultCache(capacity=2)
    k1 = c.make_key("f1", "vib", {"a": 1, "b": 2})
    k2 = c.make_key("f1", "vib", {"b": 2, "a": 1})
    k3 = c.make_key("f1", "vib", {"a": 1, "b": 3})
    assert k1 == k2 and k1 != k3


def test_lru_eviction():
    c = AnalysisResultCache(capacity=2)
    k1, k2, k3 = (c.make_key("f", str(i), {}) for i in range(3))
    c.put(k1, 1); c.put(k2, 2)
    c.get(k1)            # refresh k1
    c.put(k3, 3)         # evicts k2
    assert c.get(k1) == 1 and c.get(k2) is None and c.get(k3) == 3


def test_invalidate_fid():
    c = AnalysisResultCache(capacity=4)
    ka = c.make_key("f1", "a", {})
    kb = c.make_key("f2", "b", {})
    c.put(ka, 1); c.put(kb, 2)
    c.invalidate_fid("f1")
    assert c.get(ka) is None and c.get(kb) == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/ui/test_analysis_cache.py -v`
Expected: FAIL，ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
"""Per-section LRU result cache (spec §6.4).

Generalizes main_window's _fft_time_cache (capacity 12). Keys hash only
compute-relevant params — callers must pass the filtered dict (the
existing _fft_time_cache_key convention: display-only knobs excluded).
"""
from __future__ import annotations

import json
from collections import OrderedDict


class AnalysisResultCache:
    def __init__(self, capacity: int):
        self._capacity = int(capacity)
        self._store: OrderedDict = OrderedDict()

    def make_key(self, fid: str, channel: str, params: dict) -> tuple:
        blob = json.dumps(params, sort_keys=True, default=str)
        return (str(fid), str(channel), blob)

    def get(self, key):
        if key not in self._store:
            return None
        self._store.move_to_end(key)
        return self._store[key]

    def put(self, key, result) -> None:
        self._store[key] = result
        self._store.move_to_end(key)
        while len(self._store) > self._capacity:
            self._store.popitem(last=False)

    def invalidate_fid(self, fid: str) -> None:
        fid = str(fid)
        for key in [k for k in self._store if k[0] == fid]:
            del self._store[key]

    def clear(self) -> None:
        self._store.clear()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/ui/test_analysis_cache.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/analysis_cache.py tests/ui/test_analysis_cache.py
git commit -m "feat(multiview): AnalysisResultCache LRU with fid invalidation"
```

---

## Task 5: per-section bridge（capture/apply）

**Files:**
- Create: `mf4_analyzer/ui/analysis_view_bridge.py`
- Modify（如需）: `mf4_analyzer/ui/inspector_sections.py`（OrderContextual 补 `apply_params`）
- Test: `tests/ui/test_analysis_view_bridge.py`

- [ ] **Step 1: 确认 OrderContextual 的 apply_params**

```bash
grep -n "def apply_params" mf4_analyzer/ui/inspector_sections.py
```

若只有 2 处（FFT :2072 / FFTTime :2500），给 OrderContextual 补一个：
对照 `FFTContextual.apply_params`（:2072 起）的实现模式——`get_params()` 输出
的每个键对应一个控件 setter，缺键跳过——为 OrderContextual 的
`get_params`（:2461 起）输出的全部键写回（nfft/max_order/order_res/time_res/
samples_per_rev/window/z_* /x_* /y_* 等，以该方法实际返回的键集为准）。
本步带独立小测试：`apply_params(get_params())` 后再次 `get_params()` 结果相等
（幂等回填）。

- [ ] **Step 2: 写 bridge 失败测试**

```python
"""analysis_view_bridge: capture/apply between Contextual and view state.

Uses a stub contextual (duck-typed get_params/apply_params) so the test
doesn't need the full Inspector; the wiring to real Contextuals is
covered by Task 7's integration test.
"""
from mf4_analyzer.ui.analysis_view_bridge import (
    apply_params_from_state, capture_params_to_state,
)
from mf4_analyzer.ui.analysis_view_state import AnalysisViewState


class _StubCtx:
    def __init__(self):
        self._p = {"nfft": 1024, "window": "hanning"}

    def get_params(self):
        return dict(self._p)

    def apply_params(self, d):
        self._p.update(d)


def test_capture_then_apply_round_trip():
    ctx = _StubCtx()
    state = AnalysisViewState(name="v", tab_color="#fff")
    capture_params_to_state(ctx, state)
    assert state.params["nfft"] == 1024
    state.params["nfft"] = 4096
    apply_params_from_state(ctx, state)
    assert ctx.get_params()["nfft"] == 4096


def test_apply_with_empty_params_is_noop():
    ctx = _StubCtx()
    before = ctx.get_params()
    apply_params_from_state(ctx, AnalysisViewState(name="v", tab_color="#fff"))
    assert ctx.get_params() == before
```

- [ ] **Step 3: 跑测试确认失败 → 实现**

Run: `python -m pytest tests/ui/test_analysis_view_bridge.py -v` → ModuleNotFoundError

```python
"""Capture/apply params between a section Contextual and AnalysisViewState.

Mirrors view_bridge.py's capture_view/apply_controls_from_state pattern
(spec §4). All three analysis Contextuals expose get_params()/
apply_params(d); the bridge stays duck-typed so tests can stub them.
"""
from __future__ import annotations


def capture_params_to_state(ctx, state) -> None:
    state.params = dict(ctx.get_params())


def apply_params_from_state(ctx, state) -> None:
    if state.params:
        ctx.apply_params(dict(state.params))
```

- [ ] **Step 4: 跑测试确认通过 → Commit**

```bash
python -m pytest tests/ui/test_analysis_view_bridge.py -v
git add mf4_analyzer/ui/analysis_view_bridge.py tests/ui/test_analysis_view_bridge.py mf4_analyzer/ui/inspector_sections.py
git commit -m "feat(multiview): per-section param bridge; OrderContextual.apply_params"
```

---

## Task 6: `AnalysisSectionPage`（pane 容器 + ViewTabBar）

**Files:**
- Create: `mf4_analyzer/ui/analysis_section_page.py`
- Test: `tests/ui/test_analysis_section_page.py`

- [ ] **Step 1: 写失败测试**

```python
"""AnalysisSectionPage: pane container structure + focus + split + link."""
import pytest

from mf4_analyzer.ui.analysis_section_page import AnalysisSectionPage
from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
from mf4_analyzer.ui.view_state import ViewManager
from mf4_analyzer.ui.analysis_view_state import AnalysisViewState


@pytest.fixture
def page(qapp):
    mgr = ViewManager(state_factory=AnalysisViewState)
    p = AnalysisSectionPage(
        section='order',
        manager=mgr,
        card_factory=lambda: _FakeCard(),
    )
    p.resize(800, 500)
    yield p
    p.deleteLater()


class _FakeCard:
    """Card stub: AnalysisSectionPage only needs .canvas and QWidget-ness."""
    def __new__(cls):
        from PyQt5.QtWidgets import QWidget
        w = QWidget()
        w.canvas = PgHeatmapCanvas(w)
        return w


def test_starts_with_one_pane(page):
    assert page.pane_count() == 1
    assert page.focused_index() == 0


def test_enter_exit_split(page):
    page.enter_split()
    assert page.pane_count() == 2
    page.exit_split()
    assert page.pane_count() == 1
    assert page.focused_index() == 0


def test_set_focus(page):
    page.enter_split()
    page.set_focused_index(1)
    assert page.focused_index() == 1


def test_x_link_toggle(page):
    page.enter_split()
    page.set_linked(True)
    vb0 = page.pane_canvas(0)._plot.vb
    vb1 = page.pane_canvas(1)._plot.vb
    assert vb1.linkedView(vb1.XAxis) is vb0
    page.set_linked(False)
    assert vb1.linkedView(vb1.XAxis) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/ui/test_analysis_section_page.py -v`
Expected: FAIL，ModuleNotFoundError

- [ ] **Step 3: 实现**

```python
"""AnalysisSectionPage: one analysis section's page in the ChartStack.

Layout (spec §4):
    [card pane 0 | card pane 1?]   <- QSplitter(Horizontal)
    [ViewTabBar]                   <- per-section instance

Pane semantics: split lives INSIDE the active view (state.panes), unlike
the time-domain split_pairs pairing. Focus routing mirrors the
time-domain _focused_card pattern (chart_stack.py:1681-1688): click a
pane → it becomes the target for source assignment.
"""
from __future__ import annotations

from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtWidgets import QSplitter, QVBoxLayout, QWidget

from .view_tabbar import ViewTabBar

_FOCUS_ACCENT = "#2d7ff9"


class AnalysisSectionPage(QWidget):
    focus_changed = pyqtSignal(int)          # focused pane index
    link_toggled = pyqtSignal(bool)

    def __init__(self, *, section: str, manager, card_factory, parent=None):
        super().__init__(parent)
        self.section = section
        self.manager = manager
        self._card_factory = card_factory

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._split = QSplitter(Qt.Horizontal, self)
        self._split.setChildrenCollapsible(False)
        self._cards = [self._make_card()]
        self._split.addWidget(self._cards[0])
        lay.addWidget(self._split, stretch=1)

        self.tabbar = ViewTabBar(self)
        lay.addWidget(self.tabbar)

        self._focused = 0
        self._linked = False
        self._apply_focus_style()

    # -- pane management -----------------------------------------------
    def _make_card(self):
        card = self._card_factory()
        card.installEventFilter(self)
        viewport = getattr(getattr(card.canvas, '_glw', None), 'viewport', None)
        if callable(viewport):
            viewport().installEventFilter(self)
        return card

    def pane_count(self) -> int:
        return len(self._cards)

    def pane_canvas(self, idx: int):
        return self._cards[idx].canvas

    def enter_split(self) -> None:
        if len(self._cards) >= 2:
            return
        card = self._make_card()
        self._cards.append(card)
        self._split.addWidget(card)
        half = max(1, self._split.width() // 2)
        self._split.setSizes([half, half])
        self.set_linked(self._linked)

    def exit_split(self) -> None:
        if len(self._cards) < 2:
            return
        self.set_linked(False)
        card = self._cards.pop(1)
        card.setParent(None)
        card.deleteLater()
        self.set_focused_index(0)

    # -- focus ----------------------------------------------------------
    def focused_index(self) -> int:
        return self._focused

    def set_focused_index(self, idx: int) -> None:
        idx = max(0, min(idx, len(self._cards) - 1))
        if idx == self._focused:
            self._apply_focus_style()
            return
        self._focused = idx
        self._apply_focus_style()
        self.focus_changed.emit(idx)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and len(self._cards) > 1:
            for i, card in enumerate(self._cards):
                if obj is card or card.isAncestorOf(obj):
                    self.set_focused_index(i)
                    break
        return super().eventFilter(obj, event)

    def _apply_focus_style(self) -> None:
        for i, card in enumerate(self._cards):
            accent = _FOCUS_ACCENT if (i == self._focused and
                                       len(self._cards) > 1) else "transparent"
            card.setStyleSheet(f"QWidget#chartCard {{ border: 1px solid {accent}; }}")

    # -- compare: linked zoom (spec §6.1) --------------------------------
    def set_linked(self, linked: bool) -> None:
        self._linked = bool(linked)
        if len(self._cards) < 2:
            return
        vb0 = self._cards[0].canvas._plot.vb
        vb1 = self._cards[1].canvas._plot.vb
        if self._linked:
            vb1.setXLink(vb0)
            # heatmaps compare on both axes (spec §6.1)
            if hasattr(self._cards[0].canvas, '_img'):
                vb1.setYLink(vb0)
        else:
            vb1.setXLink(None)
            vb1.setYLink(None)
        self.link_toggled.emit(self._linked)

    def is_linked(self) -> bool:
        return self._linked
```

- [ ] **Step 4: 跑测试确认通过 → Commit**

```bash
python -m pytest tests/ui/test_analysis_section_page.py -v
git add mf4_analyzer/ui/analysis_section_page.py tests/ui/test_analysis_section_page.py
git commit -m "feat(multiview): AnalysisSectionPage pane container with focus + linked zoom"
```

---

## Task 7: ChartStack 三页改造 + MainWindow 路由

本任务是 P4 的接线核心，量最大；步骤内代码为骨架级完整实现，
执行者按编号顺序落地，每个 Step 单独可跑可 commit。

**Files:**
- Modify: `mf4_analyzer/ui/chart_stack.py`（三个裸 card 页 → AnalysisSectionPage）
- Modify: `mf4_analyzer/ui/main_window.py`（per-section manager/bridge/渲染管线）
- Test: `tests/ui/test_analysis_multiview_integration.py`

- [ ] **Step 1: ChartStack 持有三个 page**

`chart_stack.py` `__init__` 中（:1689-1705 区域）三个 card 的创建保留，
但 `stack.addWidget(card)` 改为包页：

```python
        from .analysis_section_page import AnalysisSectionPage

        def _fft_card_factory():
            canvas = PgLineCanvas(self)
            return _ChartCard(canvas, annotations=True, chart_mode='fft')

        def _fft_time_card_factory():
            canvas = PgHeatmapCanvas(self, with_slice=True)
            return _ChartCard(canvas, annotations=True, chart_mode='fft_time')

        def _order_card_factory():
            canvas = PgHeatmapCanvas(self)
            return _ChartCard(canvas, annotations=True, chart_mode='order')

        # managers are owned by MainWindow and injected via set_view_managers()
        self.page_fft = AnalysisSectionPage(
            section='fft', manager=None, card_factory=_fft_card_factory)
        self.page_fft_time = AnalysisSectionPage(
            section='fft_time', manager=None, card_factory=_fft_time_card_factory)
        self.page_order = AnalysisSectionPage(
            section='order', manager=None, card_factory=_order_card_factory)
        self.stack.addWidget(self._time_page)
        self.stack.addWidget(self.page_fft)
        self.stack.addWidget(self.page_fft_time)
        self.stack.addWidget(self.page_order)
```

兼容别名（旧调用面 `canvas_fft` 等大量存在，保留属性指向 pane 0）：

```python
    @property
    def canvas_fft(self):
        return self.page_fft.pane_canvas(0)

    @property
    def canvas_fft_time(self):
        return self.page_fft_time.pane_canvas(0)

    @property
    def canvas_order(self):
        return self.page_order.pane_canvas(0)
```

原 `self.canvas_fft = ...` 等三行直接实例化删除；`_fft_card/_fft_time_card/
_order_card` 引用改为 `self.page_fft._cards[0]` 等（grep 调用面逐个替换：
`grep -n "_fft_card\|_fft_time_card\|_order_card" mf4_analyzer/ui/chart_stack.py`）。

Run: `python -m pytest tests/ui -q -x`（结构性回归——旧 canvas 属性调用面必须全绿）

- [ ] **Step 2: MainWindow 创建三套 manager + 接 tabbar**

`main_window.py` `__init__`（`self._fft_time_cache` 附近）追加：

```python
        from .view_state import ViewManager
        from .analysis_view_state import AnalysisViewState
        from .analysis_cache import AnalysisResultCache

        self.analysis_managers = {
            'fft': ViewManager(self, state_factory=AnalysisViewState),
            'fft_time': ViewManager(self, state_factory=AnalysisViewState),
            'order': ViewManager(self, state_factory=AnalysisViewState),
        }
        self.analysis_caches = {
            'fft': AnalysisResultCache(32),
            'fft_time': AnalysisResultCache(12),
            'order': AnalysisResultCache(12),
        }
```

`_connect()` 中为每个 section 接 tabbar↔manager（模仿时域接线段——
`grep -n "view_tabbar\|tabbar" mf4_analyzer/ui/main_window.py` 找到时域的
连接模式后同款三份）：

```python
        for sec, page in (('fft', self.chart_stack.page_fft),
                          ('fft_time', self.chart_stack.page_fft_time),
                          ('order', self.chart_stack.page_order)):
            mgr = self.analysis_managers[sec]
            page.manager = mgr
            bar = page.tabbar
            bar.switch_requested.connect(mgr.set_active)
            bar.new_requested.connect(
                lambda _=None, m=mgr: m.new_view())
            bar.delete_requested.connect(mgr.delete_view)
            bar.rename_requested.connect(mgr.rename)
            bar.duplicate_requested.connect(mgr.duplicate)
            bar.reorder_requested.connect(mgr.reorder)
            # split_requested 在分析 section 的语义 = 当前 view 增删第二格
            bar.split_requested.connect(
                lambda _idx, s=sec: self._on_analysis_split(s, True))
            bar.clear_split_requested.connect(
                lambda _idx, s=sec: self._on_analysis_split(s, False))
            mgr.views_changed.connect(
                lambda s=sec: self._refresh_analysis_tabbar(s))
            mgr.active_changed.connect(
                lambda idx, s=sec: self._on_analysis_view_switched(s, idx))
            page.focus_changed.connect(
                lambda idx, s=sec: self._on_analysis_focus_changed(s, idx))
```

`_refresh_analysis_tabbar` 对照时域 tabbar 刷新实现（grep 同上）写三合一版本。

- [ ] **Step 3: 切 view 管线（capture → switch → apply → render-from-cache）**

`main_window.py` 新增：

```python
    def _analysis_ctx(self, section):
        return {'fft': self.inspector.fft_ctx,
                'fft_time': self.inspector.fft_time_ctx,
                'order': self.inspector.order_ctx}[section]

    def _analysis_page(self, section):
        return {'fft': self.chart_stack.page_fft,
                'fft_time': self.chart_stack.page_fft_time,
                'order': self.chart_stack.page_order}[section]

    def _capture_active_analysis_view(self, section):
        from .analysis_view_bridge import capture_params_to_state
        mgr = self.analysis_managers[section]
        state = mgr.get(mgr.active)
        capture_params_to_state(self._analysis_ctx(section), state)
        self._capture_analysis_sources(section, state)

    def _on_analysis_view_switched(self, section, idx):
        from .analysis_view_bridge import apply_params_from_state
        mgr = self.analysis_managers[section]
        state = mgr.get(idx)
        page = self._analysis_page(section)
        # pane 结构对齐
        if len(state.panes) == 2:
            page.enter_split()
        else:
            page.exit_split()
        page.set_linked(state.compare.get('x_linked', True))
        apply_params_from_state(self._analysis_ctx(section), state)
        self._apply_analysis_sources(section, state)
        self._render_analysis_view_from_cache(section, state)

    def _on_analysis_split(self, section, on):
        mgr = self.analysis_managers[section]
        state = mgr.get(mgr.active)
        if on and state.add_pane():
            self._analysis_page(section).enter_split()
        elif not on:
            state.remove_second_pane()
            self._analysis_page(section).exit_split()
```

`_render_analysis_view_from_cache`：对 view 每个 pane 每个 source 组缓存键
（`cache.make_key(fid, ch, compute_params)`，compute_params 过滤规则沿用
`_fft_time_cache_key` 的字段集，grep `def _fft_time_cache_key` 对齐），命中
→ 对应 pane canvas 渲染；未命中 → pane 清空 + statusBar 提示
「参数/源已就绪，点击计算」。**不自动计算**（spec §4）。

- [ ] **Step 4: 源路由（spec §4 源分配）**

```python
    def _capture_analysis_sources(self, section, state):
        if section == 'fft':
            checked = self.navigator.get_checked_channels()
            pane = state.panes[self._analysis_page(section).focused_index()]
            pane.sources = [(fid, ch) for fid, ch, _color in checked]
        else:
            ctx = self._analysis_ctx(section)
            sig = ctx.current_signal()      # (fid, ch) userData
            pane = state.panes[self._analysis_page(section).focused_index()]
            pane.sources = [tuple(sig)] if sig else []
            if section == 'order':
                rpm = ctx.current_rpm()
                pane.rpm_source = tuple(rpm) if rpm else None

    def _apply_analysis_sources(self, section, state):
        idx = self._analysis_page(section).focused_index()
        idx = min(idx, len(state.panes) - 1)
        pane = state.panes[idx]
        if section == 'fft':
            self.navigator.set_checked_channels(
                [(fid, ch) for fid, ch in pane.sources])
        else:
            ctx = self._analysis_ctx(section)
            if pane.sources:
                ctx.set_current_signal(pane.sources[0])   # 若无此 setter，
                # 对照 combo_sig 的 userData 结构写 findData+setCurrentIndex
            if section == 'order' and pane.rpm_source:
                ctx.set_current_rpm(pane.rpm_source)
```

`set_current_signal/set_current_rpm` 若 Contextual 没有，本步内补：
`combo.findData((fid, ch))` → `combo.setCurrentIndex`（与 `current_signal`
读取的 userData 对称）。`navigator.set_checked_channels` 的入参签名以
`widgets/__init__.py:373-400` 为准（可能含颜色，按签名适配）。

`_on_analysis_focus_changed(section, idx)`：先 capture 旧焦点 pane 源，
再按新焦点 pane 回显（navigator 勾选/combo 选项），实现为上面两个函数的组合。

- [ ] **Step 5: 计算按钮语义改为「算整个 view」**

`do_fft` / `do_fft_time` / `do_order_time` 顶部统一加：

```python
        self._capture_active_analysis_view('<section>')   # 'fft'/'fft_time'/'order'
```

然后把单源计算体改成对 `state.panes[*].sources[*]` 的循环：
- FFT（同步、便宜）：直接循环算全部 source，结果列表喂
  `canvas.plot_spectra(entries, ...)`（每 pane 一次调用，entries=该 pane 全部源，
  颜色取 navigator 勾选返回的 color，标签 `f"{文件名} · {ch}"`，文件名经
  `self.files[fid]` 的显示名——grep 时域图例取名逻辑对齐）。
- FFT-vs-Time / Order（异步）：把「(pane_idx, fid, ch) 任务」排进顺序队列，
  逐个走 AnalysisComputeWorker（一个 section 同时一个 worker，spec §7），
  每个完成回调里 `cache.put` + 渲染对应 pane。
计算前每 source 查缓存，命中跳过 worker 直接渲染。
**Order 的缓存键 params 必须包含 `rpm_source`（`(fid, ch)` 编为字符串）与全部
COT 参数（spec §6.4）——换 RPM 通道不得命中旧结果。**

集成测试（`tests/ui/test_analysis_multiview_integration.py`）：
构造 MainWindow（offscreen，借用现有 MainWindow 级测试的构造方式——
`grep -rln "MainWindow()" tests/ui | head` 找样例），加载 `loaded_csv`
fixture 两份为两个文件，FFT section：勾两个文件同名通道 → 计算 →
断言 `page_fft.pane_canvas(0)._amp_curves` 长度 2；新建 View 2 →
断言画布清空提示态；切回 View 1 → 断言缓存命中渲染（曲线仍为 2，
且未触发新计算——以 cache hit 计数 spy 断言）。

- [ ] **Step 6: 回归 + Commit**

```bash
python -m pytest tests/ -q
git add -A
git commit -m "feat(multiview): per-section views with pane routing, view-scoped compute and cache-backed switching"
```

---

## Task 8: 锁定色阶（compare.levels_locked）

**Files:**
- Modify: `mf4_analyzer/ui/analysis_section_page.py`
- Modify: `mf4_analyzer/ui/main_window.py`（colorbar↔inspector 同步）
- Test: `tests/ui/test_analysis_section_page.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
import numpy as np


def test_levels_lock_syncs_both_heatmaps(page):
    page.enter_split()
    m = np.ones((4, 5)); m[2, 3] = 100.0
    for i, peak in ((0, 100.0), (1, 50.0)):
        mm = np.ones((4, 5)); mm[2, 3] = peak
        page.pane_canvas(i).plot_or_update_heatmap(
            matrix=mm, x_extent=(0, 10), y_extent=(0, 8),
            amplitude_mode='amplitude', z_auto=True)
    page.set_levels_locked(True)
    lo0, hi0 = page.pane_canvas(0)._img.getLevels()
    lo1, hi1 = page.pane_canvas(1)._img.getLevels()
    assert (lo0, hi0) == (lo1, hi1)
    # combined auto range = min/max across BOTH matrices
    assert hi0 == pytest.approx(100.0) and lo0 == pytest.approx(1.0)


def test_levels_drag_propagates_when_locked(page):
    page.enter_split()
    for i in (0, 1):
        m = np.ones((4, 5)); m[2, 3] = 100.0
        page.pane_canvas(i).plot_or_update_heatmap(
            matrix=m, x_extent=(0, 10), y_extent=(0, 8),
            amplitude_mode='amplitude', z_auto=True)
    page.set_levels_locked(True)
    page.pane_canvas(0)._cbar.setLevels((5.0, 60.0))   # simulate user drag
    assert page.pane_canvas(1)._img.getLevels() == (
        pytest.approx(5.0), pytest.approx(60.0))
```

- [ ] **Step 2: 跑测试确认失败 → 实现**

`AnalysisSectionPage` 追加：

```python
    # -- compare: locked color levels (spec §6.2, heatmap sections) ------
    def set_levels_locked(self, locked: bool) -> None:
        self._levels_locked = bool(locked)
        canvases = [c.canvas for c in self._cards if hasattr(c.canvas, '_img')]
        if not self._levels_locked or len(canvases) < 2:
            return
        # combined auto range across both display matrices
        mats = [c._matrix_disp for c in canvases if c._matrix_disp is not None]
        if len(mats) == 2:
            import numpy as np
            lo = float(min(np.nanmin(m) for m in mats))
            hi = float(max(np.nanmax(m) for m in mats))
            for c in canvases:
                c._img.setLevels((lo, hi))
                if c._cbar is not None:
                    c._cbar.blockSignals(True)
                    c._cbar.setLevels((lo, hi))
                    c._cbar.blockSignals(False)
        for c in canvases:
            c.levels_changed.connect(self._on_locked_levels_changed)

    def _on_locked_levels_changed(self, lo: float, hi: float) -> None:
        if not getattr(self, '_levels_locked', False):
            return
        for card in self._cards:
            c = card.canvas
            if not hasattr(c, '_img') or c._matrix_disp is None:
                continue
            c._img.setLevels((lo, hi))
            if c._cbar is not None:
                c._cbar.blockSignals(True)
                c._cbar.setLevels((lo, hi))
                c._cbar.blockSignals(False)
```

注意 `__init__` 中初始化 `self._levels_locked = False`，且 `set_levels_locked`
重复调用时先 `disconnect` 再 connect（防多次连接重复触发——用 try/except
TypeError 包 disconnect，pg 信号无 connected 查询）。

MainWindow 侧（同 Task 7 Step 2 的 for 循环内）：

```python
            if sec != 'fft':
                page.pane_canvas(0).levels_changed.connect(
                    lambda lo, hi, s=sec: self._on_analysis_levels_dragged(s, lo, hi))
```

```python
    def _on_analysis_levels_dragged(self, section, lo, hi):
        """Colorbar drag → inspector z fields switch to manual + take values."""
        ctx = self._analysis_ctx(section)
        ctx.apply_params({'z_auto': False, 'z_floor': lo, 'z_ceiling': hi})
```

（`apply_params` 接受部分键——Task 5 Step 1 验证过；若实现要求全量 dict，
改为 `p = ctx.get_params(); p.update(...); ctx.apply_params(p)`。）

- [ ] **Step 3: 跑测试 + 「锁定色阶」「联动」toolbar 按钮**

在 `AnalysisSectionPage` 的 tabbar 行旁加两个 QToolButton（split 激活时可见）：
「联动缩放」（checked ↔ `set_linked` + 写回 `state.compare['x_linked']`）、
「锁定色阶」（仅热力图 section 显示，checked ↔ `set_levels_locked` + 写回
`state.compare['levels_locked']`）。写回经 MainWindow 的
`_on_analysis_compare_toggled(section, key, on)` 落到活动 state。

```bash
python -m pytest tests/ui/test_analysis_section_page.py -v
git add -A
git commit -m "feat(multiview): locked color levels across split panes + compare toggles"
```

---

## Task 9: FFT 游标 Δ 读数（多曲线）

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`（hover 文本加 Δ）
- Test: `tests/ui/test_pg_line_canvas.py`（追加）

- [ ] **Step 1: 写失败测试**

```python
def test_readout_text_includes_delta_for_multi_curve(canvas):
    e1, e2 = _entry('a', '#2563eb'), _entry('b', '#dc2626')
    e2 = dict(e2, amp=e2['amp'] * 0.5, psd=e2['psd'] * 0.25)
    canvas.plot_spectra(
        [e1, e2], xlim=(0.0, 500.0), amp_label='Amplitude',
        psd_label='PSD', title='FFT', y_auto=True, y_min=0.0, y_max=0.0,
    )
    text = canvas.format_readout(120.0)
    assert 'Δ' in text
    # at the peak: a=1.0, b=0.5 → Δ(b-a) = -0.5
    assert '-0.5' in text
```

- [ ] **Step 2: 跑测试确认失败 → 实现**

`PgLineCanvas` 把 `_on_hover` 的文本拼装抽成公开方法并加 Δ（相对第一条/主曲线，
spec §5.1：dB 轴下为 dB 差，线性轴下为差值——本画布收到的已是 display-space
值，直接相减即两种语义的正确实现）：

```python
    def format_readout(self, freq: float) -> str:
        rows = self.readout_at(freq)
        if not rows:
            return ""
        parts = []
        base_amp = rows[0][2]
        for i, (label, _f, amp, psd) in enumerate(rows):
            seg = f"{label}: {amp:.4g} / {psd:.4g}"
            if i > 0:
                seg += f"  Δ{amp - base_amp:+.4g}"
            parts.append(seg)
        return f"f={rows[0][1]:.2f} Hz  " + "  |  ".join(parts)
```

`_on_hover` 末两行改为 `self.cursor_info.emit(self.format_readout(x))`。

- [ ] **Step 3: 跑测试 + Commit**

```bash
python -m pytest tests/ui/test_pg_line_canvas.py -v
git add mf4_analyzer/ui/pg_canvas/line_canvas.py tests/ui/test_pg_line_canvas.py
git commit -m "feat(fft): cursor readout with per-curve delta vs primary"
```

---

## Task 10: 工程保存/加载接线 + 缓存失效

**Files:**
- Modify: `mf4_analyzer/ui/main_window.py`（项目保存/加载方法——grep
  `save_project_to_json\|load_project_from_json\|remap_view_fids` 定位）
- Test: `tests/ui/test_analysis_multiview_integration.py`（追加）

- [ ] **Step 1: 保存侧**

项目保存处（构造 `ProjectDocument(...)` 的调用点）追加：

```python
            analysis_views={
                sec: {
                    "active": mgr.active,
                    "views": [v.to_dict() for v in mgr.views],
                }
                for sec, mgr in self.analysis_managers.items()
            },
```

保存前先 `self._capture_active_analysis_view(sec)` ×3（当前 UI 态落入 state）。

- [ ] **Step 2: 加载侧**

加载处 `remap_view_fids(...)` 调用旁追加：

```python
        from .project_io import remap_analysis_view_fids
        from .analysis_view_state import AnalysisViewState
        remapped = remap_analysis_view_fids(doc.analysis_views, fid_map)
        for sec, mgr in self.analysis_managers.items():
            block = remapped.get(sec)
            if not block or not block["views"]:
                continue
            mgr.views = [AnalysisViewState.from_dict(v) for v in block["views"]]
            mgr.active = min(int(block["active"]), len(mgr.views) - 1)
            mgr.views_changed.emit()
            mgr.active_changed.emit(mgr.active)
```

- [ ] **Step 3: 缓存失效接线**

文件关闭路径（grep `def close_file\|_fft_time_cache` 的失效调用点，对齐
`_fft_time_cache` 现有失效位置）追加：

```python
        for cache in self.analysis_caches.values():
            cache.invalidate_fid(fid)
```

并把 `do_fft_time` 的旧 `_fft_time_cache` 读写替换为
`self.analysis_caches['fft_time']`（键经 `make_key(fid, ch, compute_params)`；
旧 `_fft_time_cache_key` 的字段过滤逻辑保留复用），删除
`_fft_time_cache/_fft_time_cache_capacity/_fft_time_cache_get/_put` 旧簇。

- [ ] **Step 4: 集成测试（追加）**

save → load round-trip：两个 section 各建 2 views（一个带 split），保存到
tmp_path，重开 MainWindow 加载，断言 view 数 / active / pane 数 / sources 全等。

```bash
python -m pytest tests/ -q
git add -A
git commit -m "feat(multiview): project persistence for analysis views; unified cache invalidation"
```

---

## Task 11: split 合成导出 + P4 视觉验收 + 时域冒烟（发布门）

- [ ] **Step 0: split 合成导出（spec §8 对等时域「左右 pixmap 合成」）**

`AnalysisSectionPage` 追加：

```python
    def grab_combined_pixmap(self, scale: float = 2.0):
        """Side-by-side composite of all panes (time-domain split parity)."""
        from PyQt5.QtGui import QPainter, QPixmap
        from PyQt5.QtCore import Qt
        pixes = [c.canvas.grab_pixmap(scale=scale) for c in self._cards]
        if len(pixes) == 1:
            return pixes[0]
        gap = int(4 * scale)
        w = sum(p.width() for p in pixes) + gap
        h = max(p.height() for p in pixes)
        out = QPixmap(w, h)
        out.fill(Qt.white)
        painter = QPainter(out)
        x = 0
        for p in pixes:
            painter.drawPixmap(x, 0, p)
            x += p.width() + gap
        painter.end()
        return out
```

测试（追加到 `tests/ui/test_analysis_section_page.py`）：split 态下
`grab_combined_pixmap().width()` 大于任一单格宽度；单格态下与
`pane_canvas(0).grab_pixmap()` 同宽。
MainWindow 侧：各分析 card 的 `copy_image_requested` 路由处，split 激活时改用
`page.grab_combined_pixmap()`（对照 ChartStack `_combined_split_pixmap` 的
时域接线，grep `_combined_split_pixmap` 对齐挂接方式）。

- [ ] **Step 1: 截图脚本** `tools/_screenshot_multiview_acceptance.py` →
  `docs/superpowers/verify/p4-*.png`（每 section 各一张 split 态 + FFT overlay 态）

- [ ] **Step 2: 人工核对清单（硬性，逐项）**

1. FFT：勾 2 文件同名通道 → 一格 2 条曲线、图例「文件 · 通道」、悬停读数含 Δ。
2. FFT view 标签：新建/重命名/删除/复制/拖动重排，各 view 的源与参数互不串扰。
3. Order：split 2 格、各选一个文件计算 → 联动缩放一格拖动另一格跟随；
   关「联动」后独立。
4. 锁定色阶：开 → 两格 colorbar 同范围（合并 auto min/max）、拖任一 colorbar
   两格同步、inspector z 字段跟随且切手动；关 → 各自独立。
5. FFT-vs-Time：split 下点击任一格热力图 → 仅该格切片更新。
6. 切 view：缓存命中秒渲染；未算过的 pane 显示提示态；点计算只算缺的。
7. 工程保存 → 关闭 → 重开加载：三 section 的 views/split/源/参数全还原。
8. **时域 section 全功能冒烟**（红线验证）：多 view、split（旧配对语义）、
   overlay、光标、导出——一项不许变。
9. 复制图片：每 section split 态导出含两格内容。

- [ ] **Step 3: Commit + 收尾**

```bash
git add -A
git commit -m "chore(multiview): P4 visual acceptance evidence"
```

---

## Self-review 记录

- spec 覆盖检查：§3 数据模型→Task 1/2；§4 UI/源路由/计算语义→Task 6/7；
  §6 四项增强→Task 6（联动）/8（锁色阶）/9（Δ）/4+7（缓存）；§9 持久化→Task 3/10；
  §11 测试→各任务 Step + Task 11。spec §2 非目标（2×2、per-pane 参数、差值图、
  时域统一）均未引入——MAX_PANES=2 留了模型扩展位。
- 类型一致性：`AnalysisViewState.panes/params/compare`、`PaneState.sources/rpm_source`、
  `cache.make_key(fid, ch, params)`、`page.enter_split/exit_split/set_linked/
  set_levels_locked/pane_canvas/focused_index` 跨任务引用一致。
- 已知执行期收敛点（带验证程序，非 TBD）：`navigator.set_checked_channels` 入参
  形状（Task 7 Step 4）、Contextual `set_current_signal` 缺失时的 findData 补法
  （同步骤）、`_refresh_analysis_tabbar` 对照时域实现（Task 7 Step 2）、
  `apply_params` 是否接受部分键（Task 8 Step 2 备援写法）。
- 风险提示：Task 7 是大接线任务，执行时严格按 Step 分 commit，任何一步红了
  先修再进——禁止跨 Step 攒改动。
