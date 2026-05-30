# PyQtGraph TimeDomain Auto Idle AA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the static, hands-off TimeDomain picture as crisp as the exported image — by enabling curve anti-aliasing 150 ms after the last interaction settles — WITHOUT touching the AA-off hot path that the 2026-05-29 perf-regression fix protects.

**Architecture:** Add an "Auto Idle AA" local state machine to `TimeDomainCanvasPG`. Every interaction (X-range change, overlay Y-drag, replot) forces curve AA *off* immediately at a single chokepoint; each settle re-arms a 150 ms single-shot timer whose slot enables AA *once* — gated on (mouse up) AND (not overlay-dragging) AND (density under a hysteresis threshold). The cursor is deliberately left untouched (Strategy A) so hovering never flips AA and never flickers. AA is toggled by flipping `PlotCurveItem.opts["antialias"]` + `self._glw.update()` only — never `setData`, so the envelope cache is left intact.

**Tech Stack:** Python 3.12, PyQt5, pyqtgraph 0.14.0, pytest (`QT_QPA_PLATFORM=offscreen`).

---

## Background / Spec

Full design: [`docs/superpowers/specs/2026-05-30-pyqtgraph-timedomain-auto-idle-aa-design.md`](../specs/2026-05-30-pyqtgraph-timedomain-auto-idle-aa-design.md).
Upstream feasibility: [`docs/analyzer/reviews/2026-05-30-pyqtgraph-realtime-aa-feasibility.md`](../../analyzer/reviews/2026-05-30-pyqtgraph-realtime-aa-feasibility.md).

Verified mechanics that make this safe:
- `draw_idle()` is just `self._glw.update()` (`pg_canvases.py:1723-1735`); pyqtgraph reads `opts["antialias"]` at paint time, so the AA flag is **sticky** across repaints → one settle = one "crisp" transition, not flicker.
- `_glw.update()` does **not** call `_refresh_visible_data()` (the envelope+`setData` path, `pg_canvases.py:2577-2623`), so flipping AA never re-pushes data.
- All X-range mutations funnel through `_on_xrange_changed()` (`pg_canvases.py:2465-2485`) — the single chokepoint for AA-off.
- Overlay Y-drag bypasses X-range; it owns `_overlay_dragging` (`pg_canvases.py:861`, `:2049`, `:2074`).
- Export AA already flips the same opt via `_curves_antialiased()` (`pg_canvases.py:3329-3361`) using `_collect_curve_items()` (`pg_canvases.py:3325-3327`); we reuse that collection.

Three deltas vs the feasibility report (locked in the design):
1. **Cursor never flips AA** (Strategy A). A is the default and needs **zero** cursor code (it is the *absence* of an AA-off call on hover). Ship A first; only if the **live** cursor verification (Task 9 step 4.4 — real on-screen rendering, the offscreen suite cannot judge perceived shimmer/lag) shows the curve flickering jagged↔smooth or the sweep feeling sticky, add the purely-additive `DeviceCoordinateCache` (Strategy B, Task 5B). Switching A→B is cheap and undoes none of A.
2. **Pen width 1.7 → 1.5 done together** with idle-AA (`_overlay_default_lw`, `pg_canvases.py:832`) to shrink the off↔on visual jump.
3. **Density gate uses hysteresis** (two thresholds) to avoid on/off chatter when slowly zooming across a single cutoff.

---

## File Structure

- `mf4_analyzer/ui/pg_canvases.py` — all production changes:
  - Import: add `QApplication` to the `PyQt5.QtWidgets` block (`pg_canvases.py:68`).
  - `__init__`: idle-AA state + 150 ms single-shot timer, next to the existing `_refresh_timer` wiring (`pg_canvases.py:760-764`).
  - New: `_set_curves_antialias(on)`, `disable_interactive_quality()`, `schedule_idle_quality()`, `try_enable_idle_quality()`, `_idle_quality_allowed()`, `_idle_aa_density_ok()`.
  - Wire-in: `_on_xrange_changed` top (`:2465`), `_refresh_visible_data` end (`:2623`), `_handle_overlay_mouse_press` (`:2049`), `_handle_overlay_mouse_release` (`:2074`), `plot_channels` start/end (`:911`). Do not add a trailing disable to `plot_channels_preserving_xlim` because its restore path schedules the idle upgrade after flushing the restored viewport.
  - `_overlay_default_lw` 1.7 → 1.5 (`:832`).
- `tests/ui/test_pg_timedomain_canvas.py` — new `TestAutoIdleAA` class; reuse helpers `_pg_canvas(qapp)` (`:534`) and `_five_channel_rows()` (`:1162`).

All test commands use the repo's offscreen invocation:
`TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest ...`

---

## Task 1: Commit to Strategy A first; defer the A→B decision to live verification

**Strategy A is the default and the starting point — it requires no cursor code.** Do NOT
gate the build on an offscreen benchmark: offscreen Qt timing does not represent real
on-screen GPU/compositor behavior, and this repo's standing rule is that rendering
smoothness/flicker must be judged on real rendering, not the offscreen suite. The A→B
decision is therefore made in **Task 9 step 4.4** against live hardware, with this explicit
criterion:

> **Switch to Strategy B (Task 5B) only if**, sweeping the cursor along curves on the real
> app, the curve visibly flickers jagged↔smooth, OR the sweep feels sticky/drops frames.
> Otherwise keep Strategy A.

**Files:** none (framing task; A emerges from Tasks 2–5).

- [ ] **Step 1 (OPTIONAL diagnostic — not a gate, no commit): quick offscreen hint**

If you want an early, *non-authoritative* read before live testing, create `/tmp/probe_hover_aa.py`:

```python
import os, time
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
from PyQt5.QtCore import QCoreApplication
from PyQt5.QtWidgets import QApplication
import pyqtgraph as pg
from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

app = QApplication.instance() or QApplication([])
canvas = TimeDomainCanvasPG(); canvas.resize(1600, 800); canvas.show()
QCoreApplication.processEvents()
t = np.linspace(0.0, 10.0, 200_000)
rows = [(f"ch{i}", True, t, np.sin(t + i) + i, "#1769e0", "u", "fid") for i in range(5)]
canvas.plot_channels(rows, mode="subplot")
QCoreApplication.processEvents()
curves = [it for it in canvas._glw.scene().items() if isinstance(it, pg.PlotCurveItem)]

def frame_ms(aa):
    for c in curves:
        c.opts["antialias"] = aa
    n, t0 = 40, time.perf_counter()
    for _ in range(n):
        canvas._glw.update(); QCoreApplication.processEvents()
    return (time.perf_counter() - t0) / n * 1000.0

print("AA off frame ms:", round(frame_ms(False), 3))
print("AA on  frame ms:", round(frame_ms(True), 3))
```

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python /tmp/probe_hover_aa.py`

Treat the numbers as a hint only. A large AA-on/AA-off ratio is a heads-up that B may be
needed, but the **live** Task 9 step 4.4 verdict decides. Proceed to Task 2 regardless.

---

## Task 2: Curve AA setter + idle-AA state/timer

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py` (import `:68`; `__init__` after `:764`; new `_set_curves_antialias`)
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Write the failing test**

Append a new class to `tests/ui/test_pg_timedomain_canvas.py`:

```python
class TestAutoIdleAA:
    """2026-05-30 Auto Idle AA: enable curve antialiasing 150 ms after the
    last interaction settles, off during any interaction.

    See docs/superpowers/plans/2026-05-30-pyqtgraph-timedomain-auto-idle-aa.md
    """

    def test_set_curves_antialias_flips_every_curve(self, qapp):
        import pyqtgraph as pg

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        curves = [it for it in canvas._glw.scene().items()
                  if isinstance(it, pg.PlotCurveItem)]
        assert curves

        n_on = canvas._set_curves_antialias(True)
        assert n_on == len(curves)
        assert all(c.opts.get("antialias") for c in curves)

        canvas._set_curves_antialias(False)
        assert not any(c.opts.get("antialias") for c in curves)

    def test_idle_timer_is_single_shot_150ms(self, qapp):
        canvas = _pg_canvas(qapp)
        assert canvas._idle_aa_timer.isSingleShot()
        assert canvas._idle_aa_timer.interval() == 150
        assert canvas._idle_aa_on is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest "tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA::test_set_curves_antialias_flips_every_curve" "tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA::test_idle_timer_is_single_shot_150ms" -q`
Expected: FAIL — `AttributeError: ... has no attribute '_set_curves_antialias'` / `_idle_aa_timer`.

- [ ] **Step 3: Write minimal implementation**

3a. Add `QApplication` to the import block. In `pg_canvases.py:68-77`, insert after `QActionGroup,`:
```python
    QApplication,
```

3b. In `__init__`, immediately after `self._refresh_pending = False` (`pg_canvases.py:764`), add:
```python
        # --- Auto Idle AA wiring ----------------------------------------
        # Crisp (anti-aliased) curves return 150 ms after the last
        # interaction settles; any interaction forces AA back off. The flag
        # is sticky across repaints (pyqtgraph reads opts['antialias'] at
        # paint time), so a settle yields ONE crisp transition, not flicker.
        self._idle_aa_on = False
        self._idle_aa_timer = QTimer(self)
        self._idle_aa_timer.setSingleShot(True)
        self._idle_aa_timer.setInterval(150)
        self._idle_aa_timer.timeout.connect(self.try_enable_idle_quality)
        # Hysteresis density gate (drawn points per curve). Tunable on the
        # live-verification pass; envelope normally caps points near the
        # pixel-column width so most curves qualify.
        self._AA_DENSITY_ON = 4000
        self._AA_DENSITY_OFF = 6000
```

3c. Add the setter next to `_curves_antialiased` (just above it, ~`pg_canvases.py:3329`):
```python
    def _set_curves_antialias(self, on: bool) -> int:
        """Persistently set opts['antialias'] on every curve. Does NOT
        repaint or setData — callers pair this with self._glw.update().
        Reuses the same PlotCurveItem set as the export AA context so live
        idle AA and export AA never disagree. Returns curves touched."""
        n = 0
        for it in self._collect_curve_items():
            try:
                it.opts["antialias"] = bool(on)
                n += 1
            except Exception:
                pass
        return n
```

- [ ] **Step 4: Run test to verify it passes**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest "tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA::test_set_curves_antialias_flips_every_curve" "tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA::test_idle_timer_is_single_shot_150ms" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvases.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "feat(ui): add idle-AA curve setter + 150ms timer scaffolding"
```

---

## Task 3: State machine — disable / schedule / try-enable + gates

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py` (new methods)
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Write the failing test**

Add to `TestAutoIdleAA`:

```python
    def test_idle_slot_enables_aa_when_mouse_up(self, qapp, monkeypatch):
        import pyqtgraph as pg
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        monkeypatch.setattr(QApplication, "mouseButtons",
                            staticmethod(lambda: Qt.NoButton))

        canvas.try_enable_idle_quality()
        assert canvas._idle_aa_on is True
        curves = [it for it in canvas._glw.scene().items()
                  if isinstance(it, pg.PlotCurveItem)]
        assert all(c.opts.get("antialias") for c in curves)

    def test_disable_interactive_quality_forces_aa_off(self, qapp, monkeypatch):
        import pyqtgraph as pg
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        monkeypatch.setattr(QApplication, "mouseButtons",
                            staticmethod(lambda: Qt.NoButton))
        canvas.try_enable_idle_quality()
        assert canvas._idle_aa_on is True

        canvas.disable_interactive_quality()
        assert canvas._idle_aa_on is False
        assert not canvas._idle_aa_timer.isActive()
        curves = [it for it in canvas._glw.scene().items()
                  if isinstance(it, pg.PlotCurveItem)]
        assert not any(c.opts.get("antialias") for c in curves)

    def test_idle_slot_blocked_while_mouse_down(self, qapp, monkeypatch):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        monkeypatch.setattr(QApplication, "mouseButtons",
                            staticmethod(lambda: Qt.LeftButton))
        canvas.try_enable_idle_quality()
        assert canvas._idle_aa_on is False

    def test_idle_slot_blocked_while_overlay_dragging(self, qapp, monkeypatch):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        monkeypatch.setattr(QApplication, "mouseButtons",
                            staticmethod(lambda: Qt.NoButton))
        canvas._overlay_dragging = True
        canvas.try_enable_idle_quality()
        assert canvas._idle_aa_on is False

    def test_schedule_idle_quality_starts_timer(self, qapp):
        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        canvas.schedule_idle_quality()
        assert canvas._idle_aa_timer.isActive()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest "tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA" -q`
Expected: FAIL — `AttributeError: ... 'try_enable_idle_quality'` (and the other new methods).

- [ ] **Step 3: Write minimal implementation**

Add these methods to `TimeDomainCanvasPG` (place them just below `_set_curves_antialias` from Task 2):

```python
    def disable_interactive_quality(self):
        """Any interaction (X-range change, overlay Y-drag, replot) calls
        this. Cancel a pending idle upgrade and force curve AA off NOW.
        Idempotent + cheap: opts flip + scene update, never setData — safe
        to call on every range-change frame."""
        self._idle_aa_timer.stop()
        if self._idle_aa_on:
            self._set_curves_antialias(False)
            self._idle_aa_on = False
            try:
                self._glw.update()
            except Exception:
                pass

    def schedule_idle_quality(self):
        """Re-arm the single-shot idle timer after an interaction settles."""
        try:
            self._idle_aa_timer.start()
        except Exception:
            pass

    def try_enable_idle_quality(self):
        """Idle-timer slot: enable curve AA exactly once if every gate
        passes. A failed gate simply declines; the next settle re-arms."""
        if self._idle_aa_on:
            return
        if not self._idle_quality_allowed():
            return
        if self._set_curves_antialias(True) > 0:
            self._idle_aa_on = True
            try:
                self._glw.update()
            except Exception:
                pass

    def _idle_quality_allowed(self) -> bool:
        """Idle AA is allowed only when the user is truly hands-off:
        no mouse button down (rules out pan/rect/drag), not mid overlay
        Y-drag, and curve density under the hysteresis threshold."""
        try:
            if QApplication.mouseButtons() != Qt.NoButton:
                return False
        except Exception:
            return False
        if self._overlay_dragging:
            return False
        return self._idle_aa_density_ok()

    def _idle_aa_density_ok(self) -> bool:
        """Hysteresis density gate. Enable only when EVERY curve's drawn
        point count is <= _AA_DENSITY_ON; once on, tolerate up to
        _AA_DENSITY_OFF before the next decision re-rejects. Two thresholds
        prevent on/off chatter when slowly zooming across one cutoff."""
        max_points = 0
        for it in self._collect_curve_items():
            try:
                xd, _ = it.getData()
                n = 0 if xd is None else len(xd)
            except Exception:
                n = 0
            max_points = max(max_points, n)

        if max_points <= self._AA_DENSITY_ON:
            self._idle_aa_density_allowed = True
        elif max_points > self._AA_DENSITY_OFF:
            self._idle_aa_density_allowed = False
        return bool(self._idle_aa_density_allowed)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest "tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA" -q`
Expected: PASS (the 7 tests so far).

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvases.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "feat(ui): idle-AA state machine + hands-off gating"
```

---

## Task 4: Wire the state machine into interaction entry points

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py` (`_on_xrange_changed`, `_refresh_visible_data`, overlay press/release, both `plot_channels*`)
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Write the failing test**

Add to `TestAutoIdleAA`:

```python
    def test_xrange_change_forces_aa_off(self, qapp, monkeypatch):
        import pyqtgraph as pg
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        monkeypatch.setattr(QApplication, "mouseButtons",
                            staticmethod(lambda: Qt.NoButton))
        canvas.try_enable_idle_quality()
        assert canvas._idle_aa_on is True

        # A pan/zoom range change must drop AA immediately.
        canvas.set_xlim(0.2, 0.8)
        assert canvas._idle_aa_on is False
        curves = [it for it in canvas._glw.scene().items()
                  if isinstance(it, pg.PlotCurveItem)]
        assert not any(c.opts.get("antialias") for c in curves)

    def test_refresh_rearms_idle_timer(self, qapp):
        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        canvas.set_xlim(0.1, 0.9)
        canvas._flush_pending_refresh()
        assert canvas._idle_aa_timer.isActive()

    def test_overlay_drag_drops_aa_and_release_rearms(self, qapp, monkeypatch):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="overlay")
        monkeypatch.setattr(QApplication, "mouseButtons",
                            staticmethod(lambda: Qt.NoButton))
        canvas.try_enable_idle_quality()
        assert canvas._idle_aa_on is True

        # Simulate the overlay-drag begin/end gate transitions directly.
        canvas._overlay_dragging = True
        canvas.disable_interactive_quality()
        assert canvas._idle_aa_on is False

        canvas._overlay_dragging = False
        canvas.schedule_idle_quality()
        assert canvas._idle_aa_timer.isActive()

    def test_replot_leaves_curves_aa_off(self, qapp):
        import pyqtgraph as pg

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        assert canvas._idle_aa_on is False
        curves = [it for it in canvas._glw.scene().items()
                  if isinstance(it, pg.PlotCurveItem)]
        assert curves and not any(c.opts.get("antialias") for c in curves)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest "tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA::test_xrange_change_forces_aa_off" "tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA::test_refresh_rearms_idle_timer" -q`
Expected: FAIL — AA stays on after `set_xlim`; timer not armed after refresh.

- [ ] **Step 3: Write minimal implementation**

3a. In `_on_xrange_changed` (`pg_canvases.py:2465`), insert as the FIRST statement of the body (before `_propagate_xlim_to_siblings` and before the `_refresh_pending` early-return at `:2482`):
```python
        # Any range mutation (pan / rect-zoom / wheel / Home / Back /
        # Forward) is an interaction → curves go AA-off immediately.
        self.disable_interactive_quality()
```

3b. At the END of `_refresh_visible_data` (after `self._refresh = True` at `pg_canvases.py:2623`), add:
```python
        # Data has settled for this viewport → arm the idle upgrade.
        self.schedule_idle_quality()
```

3c. In `_handle_overlay_mouse_press` (`pg_canvases.py:2049`), right after `self._overlay_dragging = True`, add:
```python
            self.disable_interactive_quality()
```

3d. In `_handle_overlay_mouse_release` (`pg_canvases.py:2076`), right after `self._set_x_master_mouse_enabled(True)` and before `return True`, add:
```python
        self.schedule_idle_quality()
```

3e. At the START of `plot_channels` (`pg_canvases.py:911`), before `self.clear()`, add:
```python
        self.disable_interactive_quality()
```

At the END of `plot_channels`, after `_run_replot_callbacks()`, add:
```python
        # Fresh build is an interaction: curves are created AA-off; reset
        # idle state + cancel any stale timer so the rebuild starts clean.
        self.disable_interactive_quality()
```

Do not add a trailing disable to `plot_channels_preserving_xlim()`: it calls `plot_channels()`,
then restores the prior X range and `_flush_pending_refresh()` schedules the idle upgrade for
the restored viewport. A final disable there would stop that freshly scheduled timer.

3f. In `_handle_wheel_dispatch`, call `disable_interactive_quality()` once the wheel event is
known to be valid (after `step != 0`, before the `try:` block) and call `schedule_idle_quality()`
after a successful range mutation. This is required because Shift/plain wheel change only Y range
and do not pass through `_on_xrange_changed()`.

3g. In `eventFilter`'s non-overlay `MouseButtonRelease` path, call `schedule_idle_quality()` so
a timer that fired and was rejected while the mouse button was still held gets re-armed on release.

- [ ] **Step 4: Run test to verify it passes**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest "tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvases.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "feat(ui): wire idle-AA into range/overlay/replot entry points"
```

---

## Task 5: Cursor Strategy A — hover never flips AA

**Files:**
- Modify: none (Strategy A is the *absence* of cursor wiring — `_handle_cursor_mouse_move` must NOT call `disable_interactive_quality`)
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Write the failing/guard test**

Add to `TestAutoIdleAA`:

```python
    def test_cursor_move_does_not_flip_aa(self, qapp, monkeypatch):
        """Strategy A: hovering the cursor reads values; it never touches
        curve AA, so the crisp idle frame stays crisp and never flickers
        jagged<->smooth while the user sweeps the cursor."""
        import pyqtgraph as pg
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        monkeypatch.setattr(QApplication, "mouseButtons",
                            staticmethod(lambda: Qt.NoButton))
        canvas.try_enable_idle_quality()
        assert canvas._idle_aa_on is True

        canvas.set_cursor_visible(True)
        handle = canvas.axes_list[0]
        # Defeat the 33 ms hover throttle so each synthetic move lands.
        for i in range(10):
            canvas._last_t = 0
            point = _viewport_point_for_data(canvas, handle, 0.1 + 0.05 * i)
            assert canvas._handle_cursor_mouse_move(
                _FakeMove(point.x(), point.y())
            ) is True

        # AA stayed on the whole time — no jagged<->smooth chatter.
        assert canvas._idle_aa_on is True
        curves = [it for it in canvas._glw.scene().items()
                  if isinstance(it, pg.PlotCurveItem)]
        assert all(c.opts.get("antialias") for c in curves)
```

Add this tiny fake-event helper near the top of the `TestAutoIdleAA` class (or module-level if one does not already exist):

```python
class _FakeMove:
    """Minimal stand-in for a Qt mouse-move event for hover tests."""
    def __init__(self, x, y):
        from PyQt5.QtCore import QPoint, Qt
        self._p = QPoint(x, y)
        self._b = Qt.NoButton
    def pos(self):
        return self._p
    def buttons(self):
        return self._b
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest "tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA::test_cursor_move_does_not_flip_aa" -q`
Expected: PASS without any production change (Strategy A means cursor code is untouched). If it FAILS, some cursor path is flipping AA — find and remove that call; do NOT add an AA-off in the cursor handler.

> If `set_cursor_mode`/`_handle_cursor_mouse_move` signatures differ, adapt the test driver to the real cursor entry (confirm via `grep -n "def set_cursor_mode\|def _handle_cursor_mouse_move" mf4_analyzer/ui/pg_canvases.py`). The assertion (AA unchanged across hover) does not change.

- [ ] **Step 3: Commit (test only)**

```bash
git add tests/ui/test_pg_timedomain_canvas.py
git commit -m "test(ui): assert cursor hover never flips idle AA (Strategy A)"
```

---

## Task 5B: Cursor Strategy B fallback — DeviceCoordinateCache (ONLY if live verification fails)

**Skip this task unless Task 9 step 4.4 (live cursor sweep on real hardware) showed
jagged↔smooth flicker or a sticky/dropped-frame sweep under Strategy A.** This task is
purely additive — it does not remove or change any Strategy A code.

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py` (cache-mode toggle inside `try_enable_idle_quality` / `disable_interactive_quality`)
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Write the failing test**

Add to `TestAutoIdleAA`:

```python
    def test_idle_aa_sets_device_cache_and_clears_on_interaction(self, qapp, monkeypatch):
        """Strategy B: while idle-AA is on, curve items use
        DeviceCoordinateCache so cursor-driven repaints blit a cached
        bitmap instead of re-rasterizing AA every 33 ms; the cache MUST be
        cleared on interaction or panning would smear the stale bitmap."""
        import pyqtgraph as pg
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtWidgets import QGraphicsItem

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        monkeypatch.setattr(QApplication, "mouseButtons",
                            staticmethod(lambda: Qt.NoButton))
        canvas.try_enable_idle_quality()
        curves = [it for it in canvas._glw.scene().items()
                  if isinstance(it, pg.PlotCurveItem)]
        assert all(c.cacheMode() == QGraphicsItem.DeviceCoordinateCache
                   for c in curves)

        canvas.disable_interactive_quality()
        assert all(c.cacheMode() == QGraphicsItem.NoCache for c in curves)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest "tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA::test_idle_aa_sets_device_cache_and_clears_on_interaction" -q`
Expected: FAIL — cache mode is `NoCache` after enabling idle AA.

- [ ] **Step 3: Write minimal implementation**

3a. Add a cache helper next to `_set_curves_antialias`:
```python
    def _set_curves_cache_mode(self, cached: bool):
        """Strategy B: cache idle AA frames so cursor-driven repaints blit
        instead of re-rasterizing. MUST be cleared on any geometry change."""
        from PyQt5.QtWidgets import QGraphicsItem
        mode = (QGraphicsItem.DeviceCoordinateCache if cached
                else QGraphicsItem.NoCache)
        for it in self._collect_curve_items():
            try:
                it.setCacheMode(mode)
            except Exception:
                pass
```

3b. In `try_enable_idle_quality`, after `self._idle_aa_on = True`, add:
```python
            self._set_curves_cache_mode(True)
```

3c. In `disable_interactive_quality`, inside the `if self._idle_aa_on:` block (before/after the AA-off flip), add:
```python
            self._set_curves_cache_mode(False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest "tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA::test_idle_aa_sets_device_cache_and_clears_on_interaction" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvases.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "feat(ui): Strategy B device cache for idle AA hover"
```

---

## Task 6: Density hysteresis gate

**Files:**
- Modify: none if Task 3 already shipped `_idle_aa_density_ok` (it did) — this task only adds coverage and tunes thresholds.
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Write the test**

Add to `TestAutoIdleAA`:

```python
    def test_density_gate_blocks_dense_curves(self, qapp, monkeypatch):
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        monkeypatch.setattr(QApplication, "mouseButtons",
                            staticmethod(lambda: Qt.NoButton))
        # Force the gate to reject by setting the ON threshold below the
        # current drawn-point count.
        canvas._AA_DENSITY_ON = 1
        canvas._AA_DENSITY_OFF = 2
        canvas.try_enable_idle_quality()
        assert canvas._idle_aa_on is False

    def test_density_gate_uses_hysteresis_window(self, qapp):
        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        canvas._AA_DENSITY_ON = 4
        canvas._AA_DENSITY_OFF = 6
        monkeypatch.setattr(
            canvas, "_collect_curve_items", lambda: [_FakeCurveData(5)]
        )

        canvas._idle_aa_density_allowed = False
        assert canvas._idle_aa_density_ok() is False

        canvas._idle_aa_density_allowed = True
        assert canvas._idle_aa_density_ok() is True

    def test_density_gate_fails_closed_when_curve_data_unreadable(self, qapp, monkeypatch):
        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        canvas._idle_aa_density_allowed = True
        monkeypatch.setattr(
            canvas, "_collect_curve_items", lambda: [_BrokenCurveData()]
        )

        assert canvas._idle_aa_density_ok() is False
        assert canvas._idle_aa_density_allowed is False
```

- [ ] **Step 2: Run test to verify it passes**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest "tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA::test_density_gate_blocks_dense_curves" "tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA::test_density_gate_uses_hysteresis_window" "tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA::test_density_gate_fails_closed_when_curve_data_unreadable" -q`
Expected: PASS (logic already present from Task 3).

- [ ] **Step 3: Commit**

```bash
git add tests/ui/test_pg_timedomain_canvas.py
git commit -m "test(ui): cover idle-AA density hysteresis gate"
```

---

## Task 7: Pen width 1.7 → 1.5 (co-tuned with idle AA)

**Files:**
- Modify: `mf4_analyzer/ui/pg_canvases.py:832`
- Test: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Write the test**

Add to `TestAutoIdleAA`:

```python
    def test_default_line_width_is_1_5(self, qapp):
        """Co-tuned with idle AA: a thinner default pen shrinks the visual
        jump between AA-off (chunky) and AA-on (thin+soft) frames."""
        canvas = _pg_canvas(qapp)
        assert canvas._overlay_default_lw == 1.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest "tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA::test_default_line_width_is_1_5" -q`
Expected: FAIL — `_overlay_default_lw == 1.7`.

- [ ] **Step 3: Write minimal implementation**

In `pg_canvases.py:832`, change:
```python
        self._overlay_default_lw = 1.7
```
to:
```python
        self._overlay_default_lw = 1.5
```

- [ ] **Step 4: Run test to verify it passes**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest "tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA::test_default_line_width_is_1_5" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/ui/pg_canvases.py tests/ui/test_pg_timedomain_canvas.py
git commit -m "feat(ui): thin default curve pen 1.7->1.5 to soften AA toggle"
```

---

## Task 8: Export compatibility — idle AA must survive grab

**Files:**
- Test only: `tests/ui/test_pg_timedomain_canvas.py`

- [ ] **Step 1: Write the test**

Add to `TestAutoIdleAA`:

```python
    def test_grab_preserves_idle_aa_on_state(self, qapp, monkeypatch):
        """The export AA context saves+restores the PRIOR state. With idle
        AA already on, grab must leave it on (not force interactive off)."""
        import pyqtgraph as pg
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        canvas = _pg_canvas(qapp)
        canvas.plot_channels(_five_channel_rows(), mode="subplot")
        monkeypatch.setattr(QApplication, "mouseButtons",
                            staticmethod(lambda: Qt.NoButton))
        canvas.try_enable_idle_quality()
        curves = [it for it in canvas._glw.scene().items()
                  if isinstance(it, pg.PlotCurveItem)]
        assert all(c.opts.get("antialias") for c in curves)

        pix = canvas.grab_pixmap(scale=1.0)
        assert not pix.isNull()
        # Idle AA stays ON after export (prior state preserved).
        assert all(c.opts.get("antialias") for c in curves)
        assert canvas._idle_aa_on is True
```

- [ ] **Step 2: Run test to verify it passes**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest "tests/ui/test_pg_timedomain_canvas.py::TestAutoIdleAA::test_grab_preserves_idle_aa_on_state" -q`
Expected: PASS — `_curves_antialiased()` already saves/restores the prior value, so an on→on round-trip is preserved.

- [ ] **Step 3: Commit**

```bash
git add tests/ui/test_pg_timedomain_canvas.py
git commit -m "test(ui): idle-AA-on survives export grab round-trip"
```

---

## Task 9: Full regression sweep + perf marker + live GUI verification

**Files:** none (verification only)

- [ ] **Step 1: Run the canvas suite**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_pg_timedomain_canvas.py -q`
Expected: all pass, including the pre-existing `test_curves_are_not_antialiased_for_pan_perf` (freshly built curves are still AA-off because `plot_channels` ends in `disable_interactive_quality()` and the idle timer never fires synchronously) and `test_grab_pixmap_restores_curve_antialias`.

- [ ] **Step 2: Run adjacent UI suites**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui/test_chart_stack.py tests/ui/test_axis_handle.py tests/ui/test_main_window_smoke.py -q`
Expected: all pass.

- [ ] **Step 3: Run the pan perf marker**

Run: `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest -m slow tests/perf/test_timedomain_pan_perf.py -q -s`
Expected: pass; p95 not worse than the recorded baseline (idle AA only acts AFTER pan settles, never during).

- [ ] **Step 4: Live GUI verification (REQUIRED — offscreen does not prove perceived flicker)**

Per the project lesson that offscreen tests miss live rendering, launch the real app, load a 4–5 channel file (e.g. `tiaodamping`), and confirm by hand:
1. Subplot mode, drag-pan: curves stay AA-off (chunky) while dragging; smoothness only returns ~150–200 ms after release. Pan stays smooth (no regression).
2. Rect-zoom: rubber band does not flicker; AA returns only after release.
3. Ctrl / Shift / plain wheel, several quick steps: no jagged↔smooth chatter mid-scroll; crisp only after the last step.
4. **Cursor (the flicker-risk case + the A→B decision point):** single + dual cursor — sweep along curves with the idle frame crisp. **Decision:** if the curve visibly shimmers jagged↔smooth while sweeping, OR the sweep feels sticky / drops frames → Strategy A is insufficient, go do **Task 5B** (DeviceCoordinateCache), then re-run this step. If the curve stays crisp and the sweep is smooth → keep Strategy A, skip Task 5B. (After Task 5B, also confirm a pan started right after a cursor session is not smeared by a stale cache.)
5. Overlay: select a channel and Y-drag — AA off during drag, no false X-pan, selection unchanged; AA returns after release.
6. Copy image: still crisp; doing it while idle-AA is on does not permanently corrupt the live AA state.
7. Slowly zoom through dense data: no on/off chatter at the density boundary (hysteresis).

Capture two screenshots to `/tmp`: one mid-interaction (AA off), one ~200 ms after release (AA on). Save them with the work report.

Run (suggested launch): `PYTHONPATH=. .venv/bin/python -m mf4_analyzer`

- [ ] **Step 5: Final commit (only if Step 1–3 required a test edit)**

```bash
git add tests/ui/test_pg_timedomain_canvas.py
git commit -m "test(ui): reconcile idle-AA suite with existing AA-off regression"
```

---

## Self-Review

- **Spec coverage:**
  - Design §A (AA setter) → Task 2. §B (state machine) → Task 3. §C (entry points) → Task 4. §D cursor Strategy A → Task 5 (default, Task 1 frames it); A→B decision → Task 9 step 4.4 on real hardware; Strategy B fallback → Task 5B (conditional, additive). §E pen width → Task 7. §F density hysteresis → Task 3 (logic) + Task 6 (coverage/tuning). §G export compat → Task 8.
  - Acceptance "interaction → off immediately / idle → on" → Tasks 3+4. "no cursor chatter" → Task 5 + Task 9 step 4.4. "perf not regressed" → Task 9 step 3. "export not corrupted" → Task 8. "live verification + 2 screenshots" → Task 9 step 4.
- **Placeholder scan:** none — every code step shows exact text and exact commands. Task 5's "adapt the driver if signatures differ" is a guarded verification note (the assertion is fixed), not a code placeholder. Task 5B is fully concrete and explicitly conditional on the live Task 9 step 4.4 verdict.
- **Type/name consistency:** `_set_curves_antialias`, `_idle_aa_on`, `_idle_aa_timer`, `_AA_DENSITY_ON`, `_AA_DENSITY_OFF`, `disable_interactive_quality`, `schedule_idle_quality`, `try_enable_idle_quality`, `_idle_quality_allowed`, `_idle_aa_density_ok` are defined in Tasks 2–3 and reused with identical spelling in Tasks 4–8. `_collect_curve_items` / `_curves_antialiased` / `_overlay_dragging` / `_overlay_default_lw` / `_glw` / `_refresh_visible_data` / `_on_xrange_changed` are existing symbols verified by line number. `QApplication` is imported in Task 2 step 3a before first use in Task 3's `_idle_quality_allowed`.
