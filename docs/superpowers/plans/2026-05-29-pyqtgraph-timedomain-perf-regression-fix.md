# PyQtGraph TimeDomain Perf-Regression Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the smooth (~14x) pan/zoom of `TimeDomainCanvasPG` that existed at commit `55d8a93e`, while keeping the grid and the inside subplot labels that the recent "UI-alignment" follow-up added.

**Architecture:** The follow-up (uncommitted working tree) introduced three rendering costs that did NOT exist in the smooth `HEAD` version: (1) anti-aliased curves, (2) inside-labels attached to the GraphicsScene and repositioned on every range-change frame, and (3) a `clear()` that orphans those scene labels so they accumulate ("ghost badges") and slow the scene further on each rebuild. This plan removes cost (1), pins the labels so cost (2) only fires on resize, and fixes the leak behind cost (3) — keeping grid + labels visible.

**Tech Stack:** Python 3.12, PyQt5, pyqtgraph 0.14.0, pytest (`QT_QPA_PLATFORM=offscreen`).

---

## Background / Spec

The user confirmed the canvas was *smooth before the recent UI-alignment work* and only became laggy afterward. Diffing the working tree against `HEAD` (`55d8a93e`, the "~14x faster pan" commit) isolates the regression to three additions, all in `mf4_analyzer/ui/pg_canvases.py`, none present in the smooth version:

| # | Regression | Site (current working tree) | HEAD (smooth) |
|---|-----------|------------------------------|---------------|
| 1 | `antialias=True` on every curve | `pg_canvases.py:572`, `pg_canvases.py:581` | no `antialias` anywhere → defaults False |
| 2 | Inside label repositioned every range-change frame | `pg_canvases.py:2106-2111` (`sigRangeChanged.connect`) | label was a ViewBox child, no per-frame handler |
| 3 | Inside labels attached to scene + leaked on rebuild ("ghost badges") | `scene().addItem(text_item)` at `pg_canvases.py:2093`; `clear()` nulls refs without `removeItem` at `pg_canvases.py:754-762` | label was `vb.addItem(...)`, removed automatically by `_glw.clear()` |

**Why #3 leaks (verified against pyqtgraph source):** `GraphicsLayout.clear()` (`.venv/.../pyqtgraph/graphicsItems/GraphicsLayout.py:199-205`) only removes items registered via `addItem()` (the PlotItems). A `TextItem` added through `scene().addItem()` is invisible to it. `clear()` then nulls `_inside_label_items = []` (`pg_canvases.py:761`) with a comment asserting "pg.GLW.clear() already removed" them — that assertion is false, so the old badges stay in the scene forever, frozen (their reposition handlers were just disconnected). This is the cause of BOTH the "位置错乱 / ghost badges" AND a growing per-frame scene cost.

**User decisions for this fix:**
- Keep the grid.
- Keep the inside labels, pinned at the **top-left corner** of each subplot (they must NOT pan/zoom with the data).

**Design notes that make the fix correct:**
- A ViewBox's `sceneBoundingRect()` (its on-screen geometry) is **constant during pan/zoom** — only `viewRange` changes. It changes only on **resize**. Therefore a top-left-pinned label needs repositioning ONLY on `sigResized`, never on `sigRangeChanged`. Dropping the `sigRangeChanged` handler is both the perf fix (#2) and exactly the "fixed top-left" behavior the user asked for.
- Removing `antialias=True` restores the `HEAD` curve exactly (the smooth version never passed it).
- Grid (`showGrid`, `pg_canvases.py:453`) is intentionally left untouched.
- Overlay-mode's per-channel ViewBox stack (`_add_overlay_axis_handle`) is out of scope — the user is in subplot mode and that path is a separate, heavier profile.

---

## File Structure

- `mf4_analyzer/ui/pg_canvases.py` — all three production fixes.
  - `_bind_channel` (~`pg_canvases.py:543-606`): drop `antialias=True` (2 sites).
  - New helper `_teardown_inside_labels(self)`: single owner of inside-label teardown (disconnect listeners + `scene.removeItem` each item + null the lists). Called by `clear()` and `_recheck_subplot_label_placement`.
  - `clear()` (~`pg_canvases.py:726-768`): replace the ad-hoc disconnect + null-out with a call to `_teardown_inside_labels()`.
  - `_recheck_subplot_label_placement` (~`pg_canvases.py:2048-2126`): use `_teardown_inside_labels()` for its teardown block; remove the `sigRangeChanged` connection; keep only `sigResized`.
- `tests/ui/test_pg_timedomain_canvas.py` — three regression tests (one per fix).

---

## Task 1: Disable curve anti-aliasing (restore HEAD render cost)

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py:572`, `mf4_analyzer/ui/pg_canvases.py:581`
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_pg_timedomain_canvas.py`:

```python
def test_curves_are_not_antialiased_for_pan_perf(qtbot):
    """Regression: the smooth (~14x) HEAD never anti-aliased curves.
    Re-enabling it was the #1 cause of the post-UI-alignment lag."""
    import numpy as np
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    qtbot.addWidget(canvas)
    t = np.linspace(0.0, 10.0, 5000)
    rows = [
        (f"ch{i}", True, t, np.sin(t) + i, "#d62728", "u", "fid")
        for i in range(3)
    ]
    canvas.plot_channels(rows, mode="subplot")

    assert canvas._channel_lines  # sanity: curves were built
    for _name, (_axis, line) in canvas._channel_lines.items():
        pdi = line.plot_data_item
        # opts['antialias'] must be falsy on every curve.
        assert not pdi.opts.get("antialias", False), (
            f"{_name} curve is anti-aliased; this regresses pan perf"
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::test_curves_are_not_antialiased_for_pan_perf -q`
Expected: FAIL — `pdi.opts['antialias']` is `True`.

- [ ] **Step 3: Write minimal implementation**

In `mf4_analyzer/ui/pg_canvases.py`, change both curve-creation sites in `_bind_channel`.

At `pg_canvases.py:572`:
```python
            pdi = pg.PlotDataItem(bind_t, bind_s, pen=pen, name=name)
```
At `pg_canvases.py:581`:
```python
            pdi = pi.plot(bind_t, bind_s, pen=pen, name=name)
```
(Both: remove the trailing `, antialias=True`. Anti-aliasing then follows pyqtgraph's global default, which is `False` — identical to the smooth HEAD build.)

- [ ] **Step 4: Run test to verify it passes**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::test_curves_are_not_antialiased_for_pan_perf -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvases.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "fix(ui): disable pg curve antialias to restore smooth pan"
```

---

## Task 2: Single teardown helper — fix ghost-badge leak on rebuild

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py` (add `_teardown_inside_labels`; rewire `clear()` and `_recheck_subplot_label_placement`)
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_pg_timedomain_canvas.py`:

```python
def test_rebuild_does_not_accumulate_inside_label_items(qtbot):
    """Regression: clear() must remove inside-label scene items, not just
    null the Python refs. pyqtgraph's GraphicsLayout.clear() does NOT
    remove items added via scene().addItem(), so without an explicit
    removeItem the old badges pile up in the scene on every rebuild."""
    import numpy as np
    import pyqtgraph as pg
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    qtbot.addWidget(canvas)
    t = np.linspace(0.0, 10.0, 2000)
    # >=4 channels with long names -> dense subplot -> inside labels on.
    rows = [
        (f"long_channel_name_{i}", True, t, np.sin(t) + i, "#1f77b4", "u", "fid")
        for i in range(5)
    ]

    counts = []
    for _ in range(4):
        canvas.plot_channels(rows, mode="subplot")
        text_items = [
            it for it in canvas._glw.scene().items()
            if isinstance(it, pg.TextItem)
        ]
        counts.append(len(text_items))

    # One badge per subplot, and NO growth across rebuilds.
    assert counts[0] == 5, counts
    assert counts[-1] == counts[0], f"ghost badges accumulated: {counts}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::test_rebuild_does_not_accumulate_inside_label_items -q`
Expected: FAIL — `counts` grows (e.g. `[5, 10, 15, 20]`).

- [ ] **Step 3: Write minimal implementation**

3a. Add the shared helper. Place it directly above `_disconnect_inside_label_listeners` (~`pg_canvases.py:2001`):

```python
    def _teardown_inside_labels(self):
        """Remove every inside-label scene item and drop its listeners.

        Single owner of inside-label teardown. pyqtgraph's
        GraphicsLayout.clear() only removes items registered via
        addItem() (the PlotItems); our TextItem badges are attached with
        scene().addItem(), so they MUST be removed explicitly here or
        they leak into the scene on every rebuild (ghost badges).
        """
        self._disconnect_inside_label_listeners()
        for item in self._inside_label_items:
            try:
                scene = item.scene()
                if scene is not None:
                    scene.removeItem(item)
            except Exception:
                pass
        self._inside_label_items = []
        self._inside_label_handles = []
```

3b. In `clear()`, remove the standalone disconnect call at `pg_canvases.py:731`:
```python
        self._disconnect_overlay_view_sync()
        self._disconnect_inside_label_listeners()
```
becomes
```python
        self._disconnect_overlay_view_sync()
        self._teardown_inside_labels()
```

3c. In `clear()`, replace the stale-comment null-out block at `pg_canvases.py:752-762`:
```python
        # T6 — drop overlay selection + subplot label scaffolding so the
        # next plot_channels build starts from a clean slate. The
        # _inside_label_items list owns scene items that pg.GLW.clear()
        # already removed, but we still need to drop our Python-side
        # references.
        self._selected_overlay_channel = None
        self._overlay_y_drag_start = None
        self._overlay_aux_viewboxes = []
        self._overlay_aux_axes = []
        self._inside_label_items = []
        self._inside_label_handles = []
        self._subplot_label_specs = []
```
becomes (inside-label lists are now owned by `_teardown_inside_labels`, called above):
```python
        # T6 — drop overlay selection + subplot label scaffolding so the
        # next plot_channels build starts from a clean slate. Inside-label
        # scene items were already removed by _teardown_inside_labels()
        # above (pg.GLW.clear() does NOT remove scene().addItem() items).
        self._selected_overlay_channel = None
        self._overlay_y_drag_start = None
        self._overlay_aux_viewboxes = []
        self._overlay_aux_axes = []
        self._subplot_label_specs = []
```

3d. In `_recheck_subplot_label_placement`, replace its teardown block at `pg_canvases.py:2056-2066`:
```python
        # Drop any previously-installed inside-label items.
        self._disconnect_inside_label_listeners()
        for handle, item in zip(self._inside_label_handles, self._inside_label_items):
            try:
                scene = item.scene()
                if scene is not None:
                    scene.removeItem(item)
            except Exception:
                pass
        self._inside_label_items = []
        self._inside_label_handles = []
```
becomes:
```python
        # Drop any previously-installed inside-label items.
        self._teardown_inside_labels()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::test_rebuild_does_not_accumulate_inside_label_items -q`
Expected: PASS — `counts == [5, 5, 5, 5]`.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvases.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "fix(ui): remove inside-label scene items on rebuild (ghost badges)"
```

---

## Task 3: Pin inside labels top-left — drop per-frame reposition

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py:2106-2111` (remove the `sigRangeChanged` connection)
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/ui/test_pg_timedomain_canvas.py`:

```python
def test_pan_does_not_reposition_inside_labels(qtbot, monkeypatch):
    """Regression: inside labels are pinned to each subplot's top-left
    corner. That corner is fixed during pan/zoom (only viewRange moves,
    not the ViewBox geometry), so labels must NOT be repositioned on
    sigRangeChanged — doing so cost a Python callback every pan frame."""
    import numpy as np
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    qtbot.addWidget(canvas)
    t = np.linspace(0.0, 10.0, 2000)
    rows = [
        (f"long_channel_name_{i}", True, t, np.sin(t) + i, "#1f77b4", "u", "fid")
        for i in range(5)
    ]
    canvas.plot_channels(rows, mode="subplot")
    assert canvas._inside_label_items  # sanity: inside labels are active

    calls = {"n": 0}
    orig = canvas._position_inside_label_item

    def spy(*args, **kwargs):
        calls["n"] += 1
        return orig(*args, **kwargs)

    monkeypatch.setattr(canvas, "_position_inside_label_item", spy)

    # Pan/zoom the X range — this fires sigXRangeChanged/sigRangeChanged.
    canvas.set_xlim(2.0, 8.0)
    canvas._flush_pending_refresh()

    assert calls["n"] == 0, (
        "inside labels were repositioned during pan; they should be "
        "pinned and only reflow on resize"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::test_pan_does_not_reposition_inside_labels -q`
Expected: FAIL — `calls["n"] > 0` (the `sigRangeChanged` handler fired on the pan).

- [ ] **Step 3: Write minimal implementation**

In `_recheck_subplot_label_placement`, delete the `sigRangeChanged` connection block at `pg_canvases.py:2106-2111`:
```python
                        if hasattr(vb, "sigRangeChanged"):
                            def _handler(*_args, _handle=handle, _item=text_item):
                                self._position_inside_label_item(_handle, _item)

                            vb.sigRangeChanged.connect(_handler)
                            self._inside_label_conns.append((vb.sigRangeChanged, _handler))
                        if hasattr(vb, "sigResized"):
```
becomes (keep ONLY the `sigResized` handler that follows it):
```python
                        if hasattr(vb, "sigResized"):
```
Leave the `sigResized` block (`pg_canvases.py:2112-2117`) intact — resize is the only event that moves a subplot's screen corner, and it fires rarely.

- [ ] **Step 4: Run test to verify it passes**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py::test_pan_does_not_reposition_inside_labels -q`
Expected: PASS — `calls["n"] == 0`.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvases.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "fix(ui): pin inside labels top-left, drop per-frame reposition"
```

---

## Task 4: Full regression sweep + live GUI verification

**Files:** none (verification only)

- [ ] **Step 1: Run the canvas suite**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q`
Expected: all pass (the 85 pre-existing + 3 new). If any pre-existing test asserted `antialias=True`, update it to expect `False` — the smooth HEAD did not anti-alias.

- [ ] **Step 2: Run the adjacent UI suites**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_dialogs.py tests/ui/test_axis_handle.py tests/ui/test_chart_stack.py tests/ui/test_main_window_smoke.py -q`
Expected: all pass.

- [ ] **Step 3: Run the pan perf marker**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -m slow tests/perf/test_timedomain_pan_perf.py::test_timedomain_pan_refresh_pg_canvas -q -s`
Expected: pass; p95 not worse than the recorded baseline.

- [ ] **Step 4: Live GUI verification (REQUIRED — offscreen does NOT prove this)**

The 2026-05-29 work report correctly noted offscreen tests missed the live lag. Launch the real app, load a multi-channel file, and confirm by hand:
1. Subplot mode, 5+ channels: drag-pan is smooth (no progressive slowdown).
2. Repeatedly check/uncheck channels: no leftover/ghost labels appear; only one badge per visible subplot.
3. Grid is still visible; each subplot's label sits pinned at its top-left and does not drift during pan/zoom.
4. Resize the window: labels reflow to the new top-left corners.

Run (suggested): `PYTHONPATH=. .venv/bin/python -m mf4_analyzer` (or the project's normal launch command), then exercise the four checks above.

- [ ] **Step 5: Final commit (only if Step 1 required a test edit)**

```bash
git add tests/ui/test_pg_timedomain_canvas.py
git commit -m "test(ui): expect non-antialiased pg curves"
```

---

## Self-Review

- **Spec coverage:** Regression #1 → Task 1. #3 (leak) → Task 2. #2 (per-frame reposition) + "pin top-left" user requirement → Task 3. Grid "keep" requirement → untouched (verified in Task 4 step 4.3). Live-verification gap from the work report → Task 4 step 4.
- **Placeholder scan:** none — every code step shows exact before/after text and exact commands.
- **Type/name consistency:** `_teardown_inside_labels` is defined once (Task 2 step 3a) and referenced by `clear()` and `_recheck_subplot_label_placement`; it owns `_inside_label_items` / `_inside_label_handles` and calls the existing `_disconnect_inside_label_listeners`. The `sigResized` handler and `_inside_label_conns` structure are preserved unchanged, so `_disconnect_inside_label_listeners` still matches.
