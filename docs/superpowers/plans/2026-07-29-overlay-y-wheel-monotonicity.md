# Overlay Y Wheel Monotonicity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make overlay Shift+wheel Y zoom strictly monotonic in both directions for every supported Y tick density from 3 through 20.

**Architecture:** Keep `_adjacent_nice_step()` as the sole zoom-step selector. Once it returns `next_per_div`, build exactly `n` divisions from that fixed step instead of passing an `(n - 1)`-division candidate back through `_frame_to_nice()`, which can select the old step again.

**Tech Stack:** Python 3, PyQt5, pyqtgraph, NumPy, pytest, pytest-qt.

## Global Constraints

- Preserve overlay cursor anchoring, per-axis gutter targeting, Ctrl+wheel X zoom, and plain-wheel Y pan.
- Preserve the existing raw pixel-wheel bridge and FFT/heatmap host routing unless regression evidence proves they are harmful.
- Use the repository virtual environment and a writable unique pytest `--basetemp`.
- Isolate Qt settings through the repository UI fixtures.
- Preserve unrelated uncommitted v7.9 release changes.

---

### Task 1: Prove And Fix Monotonic Overlay Y Zoom

**Files:**
- Modify: `tests/ui/test_overlay_grid_ticks.py`
- Modify: `mf4_analyzer/ui/pg_canvas/overlay_axes.py:1343-1358`

**Interfaces:**
- Consumes: `OverlayAxisManager._handle_wheel_dispatch(...)`, `_adjacent_nice_step(step, direction)`, and the configured overlay division count.
- Produces: exactly `n + 1` ticks spanning `n * next_per_div`, with negative delta strictly increasing every channel's Y span and positive delta strictly decreasing it.

- [ ] Add a parameterized canvas regression that runs `n=3..20`, applies repeated negative Shift-wheel steps, and asserts strict span expansion after every step.
- [ ] Add the matching positive-direction assertion so both directions remain strictly monotonic.
- [ ] Run the new test against the current implementation and require a behavioral failure at low densities.
- [ ] Replace the `(n - 1)` candidate plus `_frame_to_nice()` call with a fixed `next_per_div`, aligned bottom, `top = bottom + n * next_per_div`, and `n + 1` explicit ticks.
- [ ] Run the focused wheel/grid tests and the full TimeDomain canvas regression.

### Task 2: Audit Previous Wheel Changes

**Files:**
- Review: `mf4_analyzer/ui/pg_canvas/viewbox.py`
- Review: `mf4_analyzer/ui/pg_canvas/line_canvas.py`
- Review: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
- Review: wheel tests in `tests/ui/`

**Interfaces:**
- Consumes: commits `26e001e`, `9af6654`, and `0d63325`.
- Produces: a keep/revert decision backed by focused pixel-only and angle-wheel tests.

- [ ] Verify the earlier changes are independent raw-event routing repairs rather than modifications to overlay nice-step math.
- [ ] Run their focused positive/negative viewport tests.
- [ ] Revert only if those tests or aggregate regressions show harmful behavior; otherwise retain them.
- [ ] Run `git diff --check`, lessons status, and a final affected-suite verification.
