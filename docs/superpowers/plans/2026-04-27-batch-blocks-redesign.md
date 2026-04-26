# Batch Blocks Redesign Implementation Plan

> **For agentic workers:** This plan is **squad-driven**. Each Wave is a single PR
> dispatched via the squad runbook (see CLAUDE.md): main Claude calls
> `squad-orchestrator` in `mode: plan` for the wave brief, then dispatches
> the listed specialist(s); after green tests + codex wave review, advance to
> the next wave. Do NOT use `superpowers:subagent-driven-development` or
> `superpowers:executing-plans` directly — the squad runbook supersedes them
> for this project. The `- [ ]` checkbox steps inside each wave are the
> contract the wave's specialist owes back; specialists internally apply
> `superpowers:test-driven-development` to deliver them.

**Goal:** Refactor the batch processing dialog from a tab-based shell into a
three-stage pipeline (input → analysis → output) with summary strip + aligned
detail columns, add JSON preset import/export, and surface a folding task
list that doubles as dry-run preview AND live per-task progress.

**Architecture:** Single dataclass `AnalysisPreset` (factory invariants +
serialization whitelist) drives a thread-safe `BatchRunner` that emits
`BatchProgressEvent` events with cancellation support. The PyQt5 UI is split
into a new `mf4_analyzer/ui/drawers/batch/` package; runner work happens on
`BatchRunnerThread(QThread)`, events cross threads via `pyqtSignal`. Disk-added
files use a metadata-only probe (asammdf `channels_db`) for signal intersection
and lazy full-load at run time.

**Tech Stack:** Python 3.12 · PyQt5 · pandas / numpy / asammdf · pytest · matplotlib

**Source spec:** `docs/superpowers/specs/2026-04-26-batch-blocks-redesign-design.md`
(approved by codex rev 4)

---

## Squad routing summary

| Wave | Scope | Primary specialist | Notes |
|---|---|---|---|
| 1 | `AnalysisPreset` extension + factory invariants | `signal-processing-expert` | Pure dataclass; numerical correctness adjacent (preserves `from_current_single`) |
| 2 | `BatchRunner` extension (events / cancel / loader) | `signal-processing-expert` | Touches numerical control flow + thread safety |
| 3 | `batch_preset_io.py` JSON IO | `signal-processing-expert` | Pure I/O; serialization whitelist |
| 4 | `drawers/batch/` package skeleton + relocate `batch_sheet.py` | `refactor-architect` | Module boundaries; no behavior change |
| 5 | Detail panels (signal picker, method buttons, file states) | `pyqt-ui-engineer` | UI widgets only |
| 6 | Task list + runner thread + cancel button | `pyqt-ui-engineer` | UI threading + visual states |
| 7 | Toolbar buttons (preset import/export + fill-from-current) | `pyqt-ui-engineer` | Wires Wave 3 IO + Wave 2 runner |
| 8 | Cleanup (remove `signal_pattern` UI input + final dead code) | `refactor-architect` | YAGNI sweep |

After every wave: codex wave review (saved to
`docs/superpowers/reports/2026-04-27-batch-blocks-wave-<N>-review.md`)
must return "approved" before advancing.

---

## File Structure (target end-state after Wave 8)

**New files:**
```
mf4_analyzer/
├── batch_preset_io.py                       # Wave 3 — JSON read/write + schema_version
└── ui/drawers/batch/
    ├── __init__.py                          # Wave 4 — re-exports BatchSheet
    ├── sheet.py                             # Wave 4 — top-level dialog container
    ├── pipeline_strip.py                    # Wave 4 — top summary cards
    ├── input_panel.py                       # Wave 5 — INPUT detail column
    ├── signal_picker.py                     # Wave 5 — chips + popup multiselect
    ├── analysis_panel.py                    # Wave 5 — ANALYSIS detail column
    ├── method_buttons.py                    # Wave 5 — 4-button method selector
    ├── output_panel.py                      # Wave 5 — OUTPUT detail column
    ├── task_list.py                         # Wave 6 — folding list + progress bar
    └── runner_thread.py                     # Wave 6 — QThread wrapper
```

**Modified files:**
```
mf4_analyzer/batch.py                        # Waves 1, 2 — preset model + runner
mf4_analyzer/ui/main_window.py               # Wave 7 — open_batch wiring
```

**Deleted files:**
```
mf4_analyzer/ui/drawers/batch_sheet.py       # Wave 4 — replaced by batch/ package
```

**New tests:**
```
tests/test_batch_preset_dataclass.py         # Wave 1
tests/test_batch_preset_io.py                # Wave 3
tests/ui/test_batch_signal_picker.py         # Wave 5
tests/ui/test_batch_method_buttons.py        # Wave 5
tests/ui/test_batch_input_panel.py           # Wave 5
tests/ui/test_batch_task_list.py             # Wave 6
tests/ui/test_batch_runner_thread.py         # Wave 6
```

**Modified tests:**
```
tests/test_batch_runner.py                   # Wave 2 — extensive expansion
tests/ui/test_drawers.py                     # Wave 4 — relocate batch sheet smoke
```

---

## Wave 1 — `AnalysisPreset` extension + factory invariants

**Specialist:** `signal-processing-expert`
**Files:**
- Modify: `mf4_analyzer/batch.py:31-66` (`AnalysisPreset` dataclass + factories)
- Create: `tests/test_batch_preset_dataclass.py`

### Wave brief for orchestrator

The dataclass currently has `signal_pattern`, `signal`, `rpm_signal`,
`rpm_channel` fields and two factories (`from_current_single`, `free_config`).
This wave adds `target_signals` (configuration) plus two run-time fields
(`file_ids`, `file_paths`) that **never serialize** and **only apply to
`free_config` source**. The factories must enforce these invariants — calling
`free_config(file_ids=...)` should raise; calling `from_current_single(target_signals=...)`
should raise. Run-time selection fields are injected later via
`dataclasses.replace(preset, file_ids=..., file_paths=...)` from the UI; the
plan tests this path.

This wave does **not** touch `BatchRunner`. Old tests must keep passing.

### Tasks

- [ ] **Step 1: Write failing test for new fields**

Create `tests/test_batch_preset_dataclass.py`:
```python
from __future__ import annotations

import pytest

from mf4_analyzer.batch import AnalysisPreset, BatchOutput


def test_free_config_accepts_target_signals():
    p = AnalysisPreset.free_config(
        name="t",
        method="fft",
        target_signals=("sig_a", "sig_b"),
        params={"window": "hanning", "nfft": 1024},
    )
    assert p.target_signals == ("sig_a", "sig_b")
    assert p.source == "free_config"
    assert p.file_ids == ()
    assert p.file_paths == ()


def test_free_config_rejects_runtime_only_fields():
    with pytest.raises(ValueError, match="file_ids"):
        AnalysisPreset.free_config(
            name="t", method="fft", file_ids=(1, 2),
        )
    with pytest.raises(ValueError, match="file_paths"):
        AnalysisPreset.free_config(
            name="t", method="fft", file_paths=("/tmp/a.mf4",),
        )


def test_from_current_single_rejects_free_config_fields():
    with pytest.raises(ValueError, match="target_signals"):
        AnalysisPreset.from_current_single(
            name="t", method="fft", signal=(1, "sig"),
            target_signals=("sig",),
        )


def test_runtime_selection_via_replace():
    """UI 注入 file_ids / file_paths 走 dataclasses.replace 路径，而非工厂。"""
    from dataclasses import replace
    p = AnalysisPreset.free_config(
        name="t", method="fft", target_signals=("sig",),
    )
    p2 = replace(p, file_ids=(1, 2), file_paths=("/tmp/a.mf4",))
    assert p2.file_ids == (1, 2)
    assert p2.file_paths == ("/tmp/a.mf4",)
    assert p.file_ids == ()  # original untouched
```

- [ ] **Step 2: Run test — expect failure**

```bash
cd "/Users/donghang/Downloads/data analyzer"
pytest tests/test_batch_preset_dataclass.py -v
```
Expected: 4 failures (`target_signals`, `file_ids`, `file_paths` not on dataclass).

- [ ] **Step 3: Extend `AnalysisPreset` and factories**

Edit `mf4_analyzer/batch.py` around lines 31-66:
```python
@dataclass
class AnalysisPreset:
    name: str
    method: str
    source: str
    params: dict = field(default_factory=dict)
    outputs: BatchOutput = field(default_factory=BatchOutput)
    signal: tuple | None = None
    rpm_signal: tuple | None = None
    signal_pattern: str = ''
    rpm_channel: str = ''
    # NEW (configuration; free_config only)
    target_signals: tuple = ()
    # NEW (run-time selection; free_config only; injected via dataclasses.replace)
    file_ids: tuple = ()
    file_paths: tuple = ()

    @classmethod
    def from_current_single(cls, name, method, signal, params=None,
                            outputs=None, rpm_channel='', rpm_signal=None,
                            target_signals=None, file_ids=None, file_paths=None):
        if target_signals:
            raise ValueError(
                "target_signals is a free_config-only field; "
                "use AnalysisPreset.free_config instead"
            )
        if file_ids or file_paths:
            raise ValueError(
                "file_ids / file_paths are run-time selection fields; "
                "inject via dataclasses.replace, not from_current_single"
            )
        return cls(
            name=str(name or 'current analysis'),
            method=str(method),
            source='current_single',
            signal=tuple(signal) if signal is not None else None,
            rpm_signal=tuple(rpm_signal) if rpm_signal is not None else None,
            rpm_channel=str(rpm_channel or ''),
            params=dict(params or {}),
            outputs=outputs or BatchOutput(),
        )

    @classmethod
    def free_config(cls, name, method, signal_pattern='', rpm_channel='',
                    params=None, outputs=None, target_signals=None,
                    file_ids=None, file_paths=None):
        if file_ids:
            raise ValueError(
                "file_ids is a run-time selection field; "
                "inject via dataclasses.replace after free_config()"
            )
        if file_paths:
            raise ValueError(
                "file_paths is a run-time selection field; "
                "inject via dataclasses.replace after free_config()"
            )
        return cls(
            name=str(name or 'custom batch'),
            method=str(method),
            source='free_config',
            signal_pattern=str(signal_pattern or ''),
            rpm_channel=str(rpm_channel or ''),
            target_signals=tuple(target_signals or ()),
            params=dict(params or {}),
            outputs=outputs or BatchOutput(),
        )
```

- [ ] **Step 4: Run new test — expect pass**

```bash
pytest tests/test_batch_preset_dataclass.py -v
```
Expected: 4 passes.

- [ ] **Step 5: Run existing batch tests — expect zero regressions**

```bash
pytest tests/test_batch_runner.py -v
```
Expected: all existing tests still pass (factories' added kwargs default
to `None`, `target_signals=()` default does not affect old `_expand_tasks`).

- [ ] **Step 6: Commit**

```bash
git add mf4_analyzer/batch.py tests/test_batch_preset_dataclass.py
git commit -m "feat(batch): extend AnalysisPreset with target_signals + run-time fields

Add target_signals (config) plus file_ids/file_paths (run-time selection)
to AnalysisPreset. Factories enforce source-specific invariants: free_config
rejects runtime fields; from_current_single rejects target_signals. Run-time
fields are injected via dataclasses.replace from the UI layer.

See spec §4.1."
```

### Wave 1 acceptance

- [ ] All 4 new tests pass
- [ ] All existing `tests/test_batch_runner.py` tests pass
- [ ] codex wave-1 review: approved

---

## Wave 2 — `BatchRunner` extension (events / cancel / loader)

**Specialist:** `signal-processing-expert`
**Files:**
- Modify: `mf4_analyzer/batch.py` (BatchRunner + BatchProgressEvent + BatchRunResult)
- Modify: `tests/test_batch_runner.py` (expand)

### Wave brief for orchestrator

This is the heaviest wave. Adds:
1. `BatchProgressEvent` dataclass (5 kinds; per-kind payload table per spec §4.4)
2. `BatchRunResult.status` accepts `'cancelled'`
3. `BatchRunner.__init__(files, loader=None)` — `loader` default is
   `_default_loader` (calls `DataLoader.load_mf4` + wraps in `FileData`)
4. New `BatchRunner.run(preset, output_dir, progress_callback=None, *,
   on_event=None, cancel_token=None)` signature
5. `_resolve_files(preset)` — yields `(fid, fd)` from `file_ids` (lookup in
   `self.files`) and `file_paths` (lazy load via `self._loader`, cache in
   `self._disk_cache`); for `current_single` source, returns the single file
6. `_expand_tasks(preset)` — two-phase for `target_signals` (per spec §4.3):
   phase 1 short-circuits to 0 yields if no `(file, signal)` pair has a
   present column; phase 2 yields full cartesian product
7. Cancel token check between tasks; remaining tasks emit `task_cancelled`
8. Output-dir create failure → `BatchRunResult(status='blocked',
   blocked=['cannot create output dir: ...'])` + `run_finished(blocked)`
9. Disk-load failure for one file → all that file's tasks emit `task_failed`;
   other files continue (no fast-fail)
10. Old `progress_callback(index, total)` still invoked once per `task_done`,
    AFTER `on_event(task_done)` — both can coexist

### Tasks

- [ ] **Step 1: Write failing tests for BatchProgressEvent + new signature**

Append to `tests/test_batch_runner.py`:
```python
import threading
import pandas as pd
import numpy as np
import pytest
from dataclasses import replace

from mf4_analyzer.batch import (
    AnalysisPreset, BatchOutput, BatchRunner,
    BatchProgressEvent, BatchRunResult,
)
from mf4_analyzer.io import FileData


def _make_fd(tmp_path, name="a", channels=("sig", "rpm"), idx=0, fs=1024.0):
    n = 2048
    t = np.arange(n, dtype=float) / fs
    cols = {"Time": t}
    for c in channels:
        cols[c] = np.sin(2 * np.pi * 50 * t) if c == "sig" else np.full(n, 3000.0)
    df = pd.DataFrame(cols)
    p = tmp_path / f"{name}.csv"
    df.to_csv(p, index=False)
    return FileData(p, df, list(df.columns), {}, idx=idx)


def test_event_kinds_emitted_in_order(tmp_path):
    fd = _make_fd(tmp_path, "a")
    preset = AnalysisPreset.free_config(
        name="ev", method="fft",
        target_signals=("sig",),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_ids=(0,))
    events = []
    BatchRunner({0: fd}).run(
        preset, tmp_path / "out",
        on_event=events.append,
    )
    kinds = [e.kind for e in events]
    assert kinds[0] == "task_started"
    assert "task_done" in kinds
    assert kinds[-1] == "run_finished"
    finish = events[-1]
    assert finish.final_status == "done"


def test_cancel_token_stops_after_current_task(tmp_path):
    fds = {0: _make_fd(tmp_path, "a", idx=0),
           1: _make_fd(tmp_path, "b", idx=1),
           2: _make_fd(tmp_path, "c", idx=2)}
    preset = AnalysisPreset.free_config(
        name="cn", method="fft", target_signals=("sig",),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_ids=(0, 1, 2))

    token = threading.Event()
    seen = []

    def on_event(e):
        seen.append(e)
        if e.kind == "task_done" and e.task_index == 1:
            token.set()  # cancel after first done

    result = BatchRunner(fds).run(
        preset, tmp_path / "out",
        on_event=on_event, cancel_token=token,
    )
    assert result.status == "cancelled"
    cancelled = [e for e in seen if e.kind == "task_cancelled"]
    assert len(cancelled) >= 1   # at least one remaining task cancelled
    assert seen[-1].kind == "run_finished"
    assert seen[-1].final_status == "cancelled"


def test_loader_injection_for_disk_paths(tmp_path):
    fd_disk = _make_fd(tmp_path, "disk", idx=99)
    calls = []
    def fake_loader(path):
        calls.append(path)
        return fd_disk

    preset = AnalysisPreset.free_config(
        name="lp", method="fft", target_signals=("sig",),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_paths=("/fake/path/x.mf4",))

    runner = BatchRunner({}, loader=fake_loader)
    result = runner.run(preset, tmp_path / "out")
    assert calls == ["/fake/path/x.mf4"]
    assert result.status == "done"


def test_loader_failure_marks_files_tasks_failed(tmp_path):
    fd_ok = _make_fd(tmp_path, "ok", idx=0)
    def loader(path):
        if "bad" in path:
            raise IOError("simulated bad mf4")
        return fd_ok  # pragma: no cover

    preset = AnalysisPreset.free_config(
        name="lf", method="fft", target_signals=("sig",),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_ids=(0,), file_paths=("/fake/bad.mf4",))

    events = []
    runner = BatchRunner({0: fd_ok}, loader=loader)
    result = runner.run(preset, tmp_path / "out", on_event=events.append)

    failed = [e for e in events if e.kind == "task_failed"]
    done = [e for e in events if e.kind == "task_done"]
    assert any("simulated bad mf4" in (e.error or "") for e in failed)
    assert len(done) >= 1   # the OK file still ran
    assert result.status == "partial"


def test_target_signals_all_missing_returns_blocked(tmp_path):
    fd = _make_fd(tmp_path, "x", idx=0)
    preset = AnalysisPreset.free_config(
        name="m", method="fft", target_signals=("nonexistent",),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_ids=(0,))
    result = BatchRunner({0: fd}).run(preset, tmp_path / "out")
    assert result.status == "blocked"
    assert result.blocked == ["no matching batch tasks"]


def test_target_signals_partial_missing_yields_failed_rows(tmp_path):
    fd_a = _make_fd(tmp_path, "a", channels=("sig",), idx=0)
    fd_b = _make_fd(tmp_path, "b", channels=("other",), idx=1)
    preset = AnalysisPreset.free_config(
        name="pm", method="fft", target_signals=("sig",),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_ids=(0, 1))
    events = []
    result = BatchRunner({0: fd_a, 1: fd_b}).run(
        preset, tmp_path / "out", on_event=events.append,
    )
    done = [e for e in events if e.kind == "task_done"]
    failed = [e for e in events if e.kind == "task_failed"]
    assert len(done) == 1
    assert len(failed) == 1
    assert "missing signal" in (failed[0].error or "").lower()
    assert result.status == "partial"


def test_legacy_progress_callback_still_works(tmp_path):
    fd = _make_fd(tmp_path, "a", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="cs", method="fft", signal=(0, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    calls = []
    BatchRunner({0: fd}).run(
        preset, tmp_path / "out",
        progress_callback=lambda i, n: calls.append((i, n)),
    )
    assert calls == [(1, 1)]


def test_progress_callback_count_excludes_failed_tasks(tmp_path):
    """Legacy contract: progress_callback fires once per task_done, never on
    task_failed (per spec §4.4 / §8)."""
    fd_ok = _make_fd(tmp_path, "ok", channels=("sig",), idx=0)
    fd_bad = _make_fd(tmp_path, "bad", channels=("other",), idx=1)
    preset = AnalysisPreset.free_config(
        name="pf", method="fft", target_signals=("sig",),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_ids=(0, 1))
    calls = []
    result = BatchRunner({0: fd_ok, 1: fd_bad}).run(
        preset, tmp_path / "out",
        progress_callback=lambda i, n: calls.append((i, n)),
    )
    # 2 tasks total: 1 done (fd_ok), 1 failed (fd_bad missing 'sig')
    assert result.status == "partial"
    assert len(calls) == 1   # only the completed task bumped progress


def test_all_disk_files_failed_yields_per_task_failures(tmp_path):
    """If every file in selection fails to load, runner emits task_failed for
    each (not a blanket blocked) — spec §3.2, §7."""
    def loader(path):
        raise IOError(f"corrupt: {path}")
    preset = AnalysisPreset.free_config(
        name="adf", method="fft", target_signals=("sig",),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_paths=("/fake/a.mf4", "/fake/b.mf4"))
    events = []
    result = BatchRunner({}, loader=loader).run(
        preset, tmp_path / "out", on_event=events.append,
    )
    failed = [e for e in events if e.kind == "task_failed"]
    assert len(failed) == 2
    assert result.status == "blocked"  # all-failed maps to blocked
    # but events still document each failure
    assert all("corrupt" in (e.error or "") for e in failed)


def test_target_signals_multi_signal_expansion(tmp_path):
    """N files × M target_signals → N*M task_done events (spec §8)."""
    fd_a = _make_fd(tmp_path, "a", channels=("vib_x", "vib_y"), idx=0)
    fd_b = _make_fd(tmp_path, "b", channels=("vib_x", "vib_y"), idx=1)
    preset = AnalysisPreset.free_config(
        name="mm", method="fft", target_signals=("vib_x", "vib_y"),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_ids=(0, 1))
    events = []
    result = BatchRunner({0: fd_a, 1: fd_b}).run(
        preset, tmp_path / "out", on_event=events.append,
    )
    done = [e for e in events if e.kind == "task_done"]
    assert len(done) == 4   # 2 files × 2 signals
    assert result.status == "done"


def test_cancel_no_half_written_files(tmp_path):
    """Cancellation happens at task BOUNDARIES; the in-flight task must finish
    its file write before cancel takes effect (spec §4.5)."""
    fds = {0: _make_fd(tmp_path, "a", idx=0),
           1: _make_fd(tmp_path, "b", idx=1)}
    preset = AnalysisPreset.free_config(
        name="cw", method="fft", target_signals=("sig",),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    preset = replace(preset, file_ids=(0, 1))
    token = threading.Event()
    def on_event(e):
        if e.kind == "task_done" and e.task_index == 1:
            token.set()
    BatchRunner(fds).run(preset, tmp_path / "out",
                          on_event=on_event, cancel_token=token)
    out = tmp_path / "out"
    csvs = list(out.glob("*.csv"))
    # The first task's file must exist and be complete (parseable)
    assert any("a_sig_fft" in p.name for p in csvs)
    for p in csvs:
        # No partial writes — file is complete CSV
        text = p.read_text()
        assert text.endswith("\n") or len(text) > 50


def test_dual_callback_ordering(tmp_path):
    fd = _make_fd(tmp_path, "a", idx=0)
    preset = AnalysisPreset.from_current_single(
        name="dc", method="fft", signal=(0, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    log = []
    BatchRunner({0: fd}).run(
        preset, tmp_path / "out",
        progress_callback=lambda i, n: log.append("pc"),
        on_event=lambda e: log.append(f"ev:{e.kind}"),
    )
    # task_done 事件先，progress_callback 后
    assert "ev:task_done" in log
    assert "pc" in log
    assert log.index("ev:task_done") < log.index("pc")


def test_output_dir_create_failure_returns_blocked(tmp_path):
    """如果 output_dir 创建失败（如父路径是文件而非目录），blocked + run_finished(blocked)。"""
    fd = _make_fd(tmp_path, "a", idx=0)
    bad_parent = tmp_path / "is_a_file"
    bad_parent.write_text("not a dir")
    preset = AnalysisPreset.from_current_single(
        name="b", method="fft", signal=(0, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024},
    )
    events = []
    result = BatchRunner({0: fd}).run(
        preset, bad_parent / "sub",
        on_event=events.append,
    )
    assert result.status == "blocked"
    assert events[-1].kind == "run_finished"
    assert events[-1].final_status == "blocked"
```

- [ ] **Step 2: Run new tests — expect failures**

```bash
pytest tests/test_batch_runner.py -v -k "event_kinds or cancel_token or loader_injection or loader_failure or target_signals_all_missing or partial_missing or legacy_progress or dual_callback or output_dir_create" 2>&1 | tail -40
```
Expected: all 9 new tests fail with import errors / signature errors.

- [ ] **Step 3: Implement `BatchProgressEvent` + extended `BatchRunResult`**

In `mf4_analyzer/batch.py`, add (after existing dataclasses):
```python
from typing import Callable, Literal
import threading


@dataclass
class BatchProgressEvent:
    kind: Literal[
        'task_started', 'task_done', 'task_failed',
        'task_cancelled', 'run_finished',
    ]
    task_index: int | None = None
    total: int | None = None
    file_name: str | None = None
    signal: str | None = None
    method: str | None = None
    error: str | None = None        # task_failed only
    final_status: str | None = None # run_finished only


# Extend BatchRunResult.status to allow 'cancelled' (string is already free-form
# in current dataclass; no class change needed — document only).
```

- [ ] **Step 4: Implement `_default_loader` and BatchRunner constructor**

> **Note** (vs spec §4.3): Spec §4.3 wrote `loader.load_file(path)`, but
> the actual `mf4_analyzer/io/loader.py` exposes `DataLoader.load_mf4`,
> not a top-level `load_file`. This plan uses the existing API; behavior
> is the same. Spec §4.3 should be considered to read `DataLoader.load_mf4`.

```python
def _default_loader(path):
    """Default disk loader for `BatchRunner.file_paths` resolution.

    Returns FileData. Idx -1 marks "not registered with main_window".
    """
    from mf4_analyzer.io import DataLoader, FileData
    data, chs, units = DataLoader.load_mf4(path)
    return FileData(path, data, chs, units, idx=-1)


class BatchRunner:
    SUPPORTED_METHODS = {'fft', 'order_time', 'order_rpm', 'order_track'}

    def __init__(self, files, loader: Callable | None = None):
        self.files = files
        self._loader = loader or _default_loader
        self._disk_cache: dict[str, object] = {}
```

- [ ] **Step 5: Implement new `_resolve_files`**

```python
    def _resolve_files(self, preset):
        """Yield (fid, FileData) pairs for the preset.

        For free_config: file_ids resolved via self.files; file_paths
        lazy-loaded via self._loader, cached on this BatchRunner instance.
        For current_single: yield (signal[0], self.files[signal[0]]).
        """
        if preset.source == 'current_single':
            if preset.signal is None:
                return
            fid = preset.signal[0]
            fd = self.files.get(fid)
            if fd is not None:
                yield fid, fd
            return
        # free_config
        for fid in preset.file_ids:
            fd = self.files.get(fid)
            if fd is not None:
                yield fid, fd
        for path in preset.file_paths:
            if path in self._disk_cache:
                yield path, self._disk_cache[path]
                continue
            try:
                fd = self._loader(path)
            except Exception as exc:
                # signal back via a sentinel that _expand_tasks/run can detect
                yield path, _LoadFailure(path, str(exc))
                continue
            self._disk_cache[path] = fd
            yield path, fd


@dataclass
class _LoadFailure:
    path: str
    error: str
```

- [ ] **Step 6: Implement two-phase `_expand_tasks`**

Replace the existing `_expand_tasks` body with:
```python
    def _expand_tasks(self, preset):
        if preset.method not in self.SUPPORTED_METHODS:
            return
        if preset.source == 'current_single':
            if preset.signal is None:
                return
            fid, ch = preset.signal
            fd = self.files.get(fid)
            if fd is not None and ch in fd.data.columns:
                yield fid, fd, ch
            return
        files_iter = list(self._resolve_files(preset))
        if preset.target_signals:
            # Phase 1: will phase 2 yield ANY task at all?
            # _LoadFailure entries DO count — phase 2 yields them so run() can
            # surface task_failed rows (per spec §3.2 / §7: disk-load failures
            # become per-task ✗, not a blanket blocked status).
            has_any_yield = False
            for fid, fd in files_iter:
                if isinstance(fd, _LoadFailure):
                    has_any_yield = True
                    break
                for ch in preset.target_signals:
                    if ch in fd.data.columns:
                        has_any_yield = True
                        break
                if has_any_yield:
                    break
            if not has_any_yield:
                return  # → run() blocked path (UI rule § 7 normally pre-empts this)
            # Phase 2: yield full cartesian product (load failures and missing
            # signals surface as task_failed via run() try/except).
            for fid, fd in files_iter:
                for ch in preset.target_signals:
                    yield fid, fd, ch
            return
        # Pattern fallback (existing behavior unchanged for tests)
        pattern = preset.signal_pattern.strip()
        for fid, fd in files_iter:
            if isinstance(fd, _LoadFailure):
                continue
            for ch in fd.get_signal_channels():
                if preset.method.startswith('order') and ch == preset.rpm_channel:
                    continue
                if self._matches(ch, pattern):
                    yield fid, fd, ch
```

- [ ] **Step 7: Implement new `run` signature with cancellation + events**

Replace the existing `run` body:
```python
    def run(self, preset, output_dir,
            progress_callback: Callable[[int, int], None] | None = None,
            *,
            on_event: Callable[[BatchProgressEvent], None] | None = None,
            cancel_token: threading.Event | None = None) -> BatchRunResult:
        output_dir = Path(output_dir)
        # Output-dir create — fail-fast if impossible
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            err = f"cannot create output dir: {exc}"
            if on_event:
                on_event(BatchProgressEvent(
                    kind='run_finished',
                    final_status='blocked',
                ))
            return BatchRunResult(status='blocked', blocked=[err])

        tasks = list(self._expand_tasks(preset))
        if not tasks:
            if on_event:
                on_event(BatchProgressEvent(
                    kind='run_finished', final_status='blocked',
                ))
            return BatchRunResult(
                status='blocked', blocked=['no matching batch tasks'],
            )

        items: list[BatchItemResult] = []
        blocked: list[str] = []
        cancelled = False
        total = len(tasks)

        for index, task in enumerate(tasks, start=1):
            fid, fd_or_fail, signal_name = task
            if cancel_token is not None and cancel_token.is_set():
                cancelled = True
                # Emit task_cancelled for this and all remaining
                for j in range(index, total + 1):
                    fid_j, fd_j, sig_j = tasks[j - 1]
                    fname = (fd_j.path if isinstance(fd_j, _LoadFailure)
                             else getattr(fd_j, 'filename', str(fid_j)))
                    if on_event:
                        on_event(BatchProgressEvent(
                            kind='task_cancelled',
                            task_index=j, total=total,
                            file_name=fname, signal=sig_j,
                            method=preset.method,
                        ))
                break

            # Determine file_name for events (works for _LoadFailure too)
            if isinstance(fd_or_fail, _LoadFailure):
                fname = fd_or_fail.path
            else:
                fname = getattr(fd_or_fail, 'filename', str(fid))

            if on_event:
                on_event(BatchProgressEvent(
                    kind='task_started',
                    task_index=index, total=total,
                    file_name=fname, signal=signal_name, method=preset.method,
                ))
            try:
                if isinstance(fd_or_fail, _LoadFailure):
                    raise IOError(fd_or_fail.error)
                if signal_name not in fd_or_fail.data.columns:
                    raise ValueError(f"missing signal: {signal_name}")
                item = self._run_one(preset, fid, fd_or_fail,
                                     signal_name, output_dir)
                items.append(item)
                if on_event:
                    on_event(BatchProgressEvent(
                        kind='task_done',
                        task_index=index, total=total,
                        file_name=fname, signal=signal_name,
                        method=preset.method,
                    ))
                # progress_callback fires ONLY on task_done (legacy contract
                # was "called once per completed task"). Failed tasks do NOT
                # bump it — see spec §4.4 / §8.
                if progress_callback:
                    progress_callback(index, total)
            except Exception as exc:
                items.append(BatchItemResult(
                    method=preset.method, file_id=fid,
                    file_name=fname, signal=signal_name,
                    status='blocked', message=str(exc),
                ))
                blocked.append(f"{fname}:{signal_name}: {exc}")
                if on_event:
                    on_event(BatchProgressEvent(
                        kind='task_failed',
                        task_index=index, total=total,
                        file_name=fname, signal=signal_name,
                        method=preset.method, error=str(exc),
                    ))

        if cancelled:
            status = 'cancelled'
        elif blocked and len(blocked) == len(items):
            status = 'blocked'
        elif blocked:
            status = 'partial'
        else:
            status = 'done'

        if on_event:
            on_event(BatchProgressEvent(
                kind='run_finished', final_status=status,
            ))
        return BatchRunResult(status=status, items=items, blocked=blocked)
```

- [ ] **Step 8: Run new + existing tests — expect all green**

```bash
pytest tests/test_batch_runner.py -v
```
Expected: all tests (existing + 9 new) pass.

- [ ] **Step 9: Commit**

```bash
git add mf4_analyzer/batch.py tests/test_batch_runner.py
git commit -m "feat(batch): runner events + cancellation + loader injection

Add BatchProgressEvent (5 kinds), cancel_token support, lazy disk-file
loader injection (_default_loader + _disk_cache), two-phase _expand_tasks
for target_signals, and run() canonical signature
(progress_callback positional, on_event/cancel_token keyword-only).

Old progress_callback path preserved; both callbacks coexist with
'event before progress_callback' ordering. Output-dir create failure
short-circuits to blocked status with run_finished(blocked) event.

See spec §4.3, §4.4."
```

### Wave 2 acceptance

- [ ] All new tests pass; all existing batch tests pass
- [ ] No mf4_analyzer/ui/ files modified (Wave 2 is backend-only)
- [ ] codex wave-2 review: approved

---

## Wave 3 — `batch_preset_io.py` JSON IO

**Specialist:** `signal-processing-expert`
**Files:**
- Create: `mf4_analyzer/batch_preset_io.py`
- Create: `tests/test_batch_preset_io.py`

### Wave brief for orchestrator

Pure I/O. Whitelist serialization (only fields marked ✓ in spec §4.1
table get written). Read tolerates missing `schema_version` (treats as v1);
rejects unknown versions with `UnsupportedPresetVersion`. Bad JSON →
`ValueError`. Output:
```json
{"schema_version": 1, "name": ..., "method": ..., "target_signals": [...],
 "rpm_channel": ..., "params": {...},
 "outputs": {"export_data": ..., "export_image": ..., "data_format": ...}}
```

### Tasks

- [ ] **Step 1: Write failing tests**

Create `tests/test_batch_preset_io.py`:
```python
from __future__ import annotations
import json
import pytest

from mf4_analyzer.batch import AnalysisPreset, BatchOutput
from mf4_analyzer.batch_preset_io import (
    save_preset_to_json, load_preset_from_json, UnsupportedPresetVersion,
)


def _basic_preset():
    return AnalysisPreset.free_config(
        name="vib", method="fft",
        target_signals=("vibration_x", "vibration_y"),
        rpm_channel="",
        params={"window": "hanning", "nfft": 1024},
        outputs=BatchOutput(export_data=True, export_image=True, data_format="csv"),
    )


def test_round_trip_preserves_recipe(tmp_path):
    p1 = _basic_preset()
    path = tmp_path / "p.json"
    save_preset_to_json(p1, path)
    p2 = load_preset_from_json(path)
    assert p2.name == p1.name
    assert p2.method == p1.method
    assert p2.target_signals == p1.target_signals
    assert p2.params == p1.params
    assert p2.outputs.export_data is p1.outputs.export_data
    assert p2.outputs.data_format == p1.outputs.data_format


def test_serialization_whitelist(tmp_path):
    """Even if runtime/sentinel fields are injected, JSON must not contain them."""
    from dataclasses import replace
    p = replace(
        _basic_preset(),
        file_ids=(1, 2),
        file_paths=("/tmp/a.mf4",),
        signal=(0, "x"),  # forced, illegal for free_config but tolerated by dataclass
        rpm_signal=(0, "rpm"),
        signal_pattern="vib.*",
    )
    path = tmp_path / "p.json"
    save_preset_to_json(p, path)
    raw = json.loads(path.read_text())
    for forbidden in ("file_ids", "file_paths", "signal", "rpm_signal",
                      "signal_pattern"):
        assert forbidden not in raw, f"{forbidden} leaked into JSON"
    # output dir never present (BatchOutput has no directory field; just verify)
    assert "directory" not in raw["outputs"]


def test_schema_version_written_as_1(tmp_path):
    path = tmp_path / "p.json"
    save_preset_to_json(_basic_preset(), path)
    raw = json.loads(path.read_text())
    assert raw["schema_version"] == 1


def test_missing_schema_version_treated_as_v1(tmp_path):
    """For back-compat with hand-written presets / fixtures."""
    path = tmp_path / "p.json"
    path.write_text(json.dumps({
        "name": "x", "method": "fft", "target_signals": ["sig"],
        "rpm_channel": "", "params": {"window": "hanning", "nfft": 1024},
        "outputs": {"export_data": True, "export_image": True, "data_format": "csv"},
    }))
    p = load_preset_from_json(path)
    assert p.method == "fft"
    assert p.target_signals == ("sig",)


def test_unknown_schema_version_rejected(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({
        "schema_version": 2,
        "name": "x", "method": "fft", "target_signals": [],
        "params": {}, "outputs": {},
    }))
    with pytest.raises(UnsupportedPresetVersion):
        load_preset_from_json(path)


def test_corrupt_json_raises(tmp_path):
    path = tmp_path / "p.json"
    path.write_text("{not json")
    with pytest.raises(ValueError):
        load_preset_from_json(path)
```

- [ ] **Step 2: Run tests — expect import failures**

```bash
pytest tests/test_batch_preset_io.py -v 2>&1 | tail -10
```
Expected: ImportError (`batch_preset_io` doesn't exist yet).

- [ ] **Step 3: Implement `batch_preset_io.py`**

Create `mf4_analyzer/batch_preset_io.py`:
```python
"""JSON serialization for AnalysisPreset (recipe-only, portable).

Excludes runtime selection fields (file_ids, file_paths, signal,
rpm_signal) and the legacy signal_pattern fallback. Output directory
is never persisted — preset is "what to compute", not "where to write".
"""
from __future__ import annotations

import json
from pathlib import Path

from .batch import AnalysisPreset, BatchOutput


SCHEMA_VERSION = 1


class UnsupportedPresetVersion(ValueError):
    """Raised when reading a preset whose schema_version is unknown."""


def save_preset_to_json(preset: AnalysisPreset, path: str | Path) -> None:
    """Write preset to JSON using the §4.1 serialization whitelist."""
    path = Path(path)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "name": preset.name,
        "method": preset.method,
        "target_signals": list(preset.target_signals),
        "rpm_channel": preset.rpm_channel,
        "params": dict(preset.params),
        "outputs": {
            "export_data": bool(preset.outputs.export_data),
            "export_image": bool(preset.outputs.export_image),
            "data_format": str(preset.outputs.data_format),
        },
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def load_preset_from_json(path: str | Path) -> AnalysisPreset:
    """Read preset from JSON. Missing schema_version → v1; unknown → reject."""
    path = Path(path)
    text = path.read_text()
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid preset JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("preset JSON must be a JSON object")

    version = raw.get("schema_version")
    if version is None:
        version = 1   # back-compat: pre-versioned hand-written fixture
    if version != SCHEMA_VERSION:
        raise UnsupportedPresetVersion(
            f"preset schema_version={version} not supported "
            f"(this app reads v{SCHEMA_VERSION})"
        )

    outputs_raw = raw.get("outputs") or {}
    return AnalysisPreset.free_config(
        name=raw.get("name", ""),
        method=raw.get("method", "fft"),
        rpm_channel=raw.get("rpm_channel", ""),
        target_signals=tuple(raw.get("target_signals") or ()),
        params=dict(raw.get("params") or {}),
        outputs=BatchOutput(
            export_data=bool(outputs_raw.get("export_data", True)),
            export_image=bool(outputs_raw.get("export_image", True)),
            data_format=str(outputs_raw.get("data_format", "csv")),
        ),
    )
```

- [ ] **Step 4: Run tests — expect green**

```bash
pytest tests/test_batch_preset_io.py -v
```
Expected: 6 passes.

- [ ] **Step 5: Commit**

```bash
git add mf4_analyzer/batch_preset_io.py tests/test_batch_preset_io.py
git commit -m "feat(batch): JSON preset serialization with whitelist + schema_version

Add batch_preset_io module: save_preset_to_json (whitelisted recipe-only
output, schema_version=1) and load_preset_from_json (missing version →
v1, unknown → UnsupportedPresetVersion). Excludes file_ids, file_paths,
signal, rpm_signal, signal_pattern from JSON.

See spec §4.2."
```

### Wave 3 acceptance

- [ ] All 6 new tests pass
- [ ] No regressions in existing tests
- [ ] codex wave-3 review: approved

---

## Wave 4 — `drawers/batch/` package skeleton

**Specialist:** `refactor-architect`
**Files:**
- Create: `mf4_analyzer/ui/drawers/batch/__init__.py`
- Create: `mf4_analyzer/ui/drawers/batch/sheet.py`
- Create: `mf4_analyzer/ui/drawers/batch/pipeline_strip.py`
- Modify: `mf4_analyzer/ui/main_window.py` (import path)
- Delete: `mf4_analyzer/ui/drawers/batch_sheet.py`
- Modify: `tests/ui/test_drawers.py` (3 import sites, lines 38, 56, plus the
  test bodies that exercise the old QTabWidget-based BatchSheet — these
  tests test pre-redesign UX and should be **deleted** since waves 5/6/7
  cover the new dialog comprehensively)
- Modify: `tests/ui/test_order_smoke.py:66` — patch target string
  `'mf4_analyzer.ui.drawers.batch_sheet.BatchSheet'` →
  `'mf4_analyzer.ui.drawers.batch.BatchSheet'`

### Wave brief for orchestrator

Behavior-preserving relocate. The new `BatchSheet` in `drawers/batch/sheet.py`
should accept the **same constructor signature** as the current
`BatchSheet(parent, files, current_preset=None)`, render a placeholder layout
(top toolbar with three disabled buttons "从当前单次填入"/"导入 preset…"/"导出 preset…",
a `PipelineStrip` showing three static cards INPUT/ANALYSIS/OUTPUT, and a
placeholder detail area + footer with Cancel/运行 buttons). `get_preset()`
returns a hard-coded `AnalysisPreset.free_config(name="placeholder", method="fft")`
for now; the next waves fill in real logic.

`PipelineStrip` is a `QWidget` with three `PipelineCard` children laid out in
a `QHBoxLayout`. Each card shows: stage number circle, stage title, stage
summary text (placeholder "未配置"), and a status badge (✓/⚠). Card has
property `stage_status: str` ("ok" / "warn" / "pending"); strip exposes
`set_stage(stage_index, status, summary_text)`.

### Tasks

- [ ] **Step 1: Write smoke test for new package import**

Add to `tests/ui/test_drawers.py` (or new `tests/ui/test_batch_smoke.py`):
```python
def test_batch_sheet_can_be_imported_from_new_package():
    from mf4_analyzer.ui.drawers.batch import BatchSheet
    assert BatchSheet is not None


def test_pipeline_strip_set_stage_updates_summary(qtbot):
    from mf4_analyzer.ui.drawers.batch.pipeline_strip import PipelineStrip
    strip = PipelineStrip()
    qtbot.addWidget(strip)
    strip.set_stage(0, "ok", "3 文件 · 2 信号")
    card = strip.cards[0]
    assert card.stage_status == "ok"
    assert "3 文件" in card.summary_label.text()
```

- [ ] **Step 2: Run — expect import failure**

```bash
pytest tests/ui/test_batch_smoke.py -v 2>&1 | tail -5
```

- [ ] **Step 3: Create `drawers/batch/__init__.py`**

```python
"""Batch processing dialog (block-style pipeline)."""
from .sheet import BatchSheet

__all__ = ["BatchSheet"]
```

- [ ] **Step 4: Create `drawers/batch/pipeline_strip.py`**

```python
"""Top summary strip: three pipeline-stage cards (INPUT / ANALYSIS / OUTPUT)."""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


_STAGE_DEFS = [
    {"index": 1, "title": "INPUT", "color": "#3b82f6"},
    {"index": 2, "title": "ANALYSIS", "color": "#10b981"},
    {"index": 3, "title": "OUTPUT", "color": "#f59e0b"},
]


class PipelineCard(QFrame):
    def __init__(self, stage_def, parent=None):
        super().__init__(parent)
        self._stage_def = stage_def
        self.stage_status = "pending"
        self.setObjectName("PipelineCard")
        self.setStyleSheet(
            f"#PipelineCard {{background:#fff;border:1px solid #cbd5e1;"
            f"border-top:4px solid {stage_def['color']};border-radius:10px;}}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        title = QLabel(f"{stage_def['index']}. {stage_def['title']}")
        title.setStyleSheet(f"color:{stage_def['color']};font-weight:600;font-size:14px;")
        lay.addWidget(title)
        self.summary_label = QLabel("未配置")
        self.summary_label.setStyleSheet("color:#475569;font-size:12px;")
        self.summary_label.setWordWrap(True)
        lay.addWidget(self.summary_label)
        self.badge_label = QLabel("⚠")
        self.badge_label.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self.badge_label.setStyleSheet("color:#f59e0b;")
        title_row = lay.itemAt(0).widget()
        # badge stacked into title row via separate horizontal sub-layout
        # (kept simple here)


class PipelineStrip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        self.cards: list[PipelineCard] = []
        for d in _STAGE_DEFS:
            c = PipelineCard(d, self)
            lay.addWidget(c, 1)
            self.cards.append(c)

    def set_stage(self, stage_index: int, status: str, summary_text: str):
        c = self.cards[stage_index]
        c.stage_status = status
        c.summary_label.setText(summary_text)
        badge_map = {"ok": "✓", "warn": "⚠", "pending": "⏸"}
        color_map = {"ok": "#10b981", "warn": "#f59e0b", "pending": "#94a3b8"}
        c.badge_label.setText(badge_map.get(status, "⚠"))
        c.badge_label.setStyleSheet(f"color:{color_map.get(status, '#94a3b8')};")
```

- [ ] **Step 5: Create `drawers/batch/sheet.py`** (placeholder shell)

```python
"""BatchSheet — pipeline-style batch dialog (placeholder shell, Wave 4)."""
from __future__ import annotations

from pathlib import Path

from PyQt5.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from ....batch import AnalysisPreset
from .pipeline_strip import PipelineStrip


class BatchSheet(QDialog):
    def __init__(self, parent, files, current_preset=None):
        super().__init__(parent)
        self.setObjectName("SheetSurface")
        self.setModal(True)
        self.setWindowTitle("批处理分析")
        self.resize(1080, 760)
        self._files = files
        self._current_preset = current_preset

        root = QVBoxLayout(self)

        # Toolbar (placeholder buttons, Wave 7 wires)
        bar = QHBoxLayout()
        bar.addStretch(1)
        for label in ("从当前单次填入", "导入 preset…", "导出 preset…"):
            b = QPushButton(label)
            b.setEnabled(False)  # enabled in Wave 7
            bar.addWidget(b)
        root.addLayout(bar)

        # Pipeline strip
        self.strip = PipelineStrip(self)
        root.addWidget(self.strip)

        # Detail placeholder (Waves 5-6)
        detail = QWidget(self)
        detail_lay = QHBoxLayout(detail)
        for txt in ("INPUT 详情", "ANALYSIS 详情", "OUTPUT 详情"):
            placeholder = QLabel(txt)
            placeholder.setStyleSheet(
                "background:#fff;border:1px solid #cbd5e1;border-radius:10px;"
                "padding:14px;color:#94a3b8;"
            )
            detail_lay.addWidget(placeholder, 1)
        root.addWidget(detail, 1)

        # Footer
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("运行")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def get_preset(self):
        # TODO Wave 5+: assemble from real input/analysis/output panels
        return AnalysisPreset.free_config(name="placeholder", method="fft")

    def output_dir(self) -> str:
        # TODO Wave 5+: pull from real output panel
        return str(Path.home() / "Desktop" / "mf4_batch_output")
```

- [ ] **Step 6: Update `main_window.open_batch` import**

In `mf4_analyzer/ui/main_window.py:953`, change:
```python
from .drawers.batch_sheet import BatchSheet
```
to:
```python
from .drawers.batch import BatchSheet
```

- [ ] **Step 7: Update `tests/ui/test_order_smoke.py`**

Edit `tests/ui/test_order_smoke.py` line 66:
```python
# OLD: 'mf4_analyzer.ui.drawers.batch_sheet.BatchSheet', FakeSheet,
'mf4_analyzer.ui.drawers.batch.BatchSheet', FakeSheet,
```

- [ ] **Step 8: Replace pre-redesign BatchSheet tests in `tests/ui/test_drawers.py`**

The two tests at lines 36-65 (`test_batch_sheet_current_single_returns_current_preset`
and `test_batch_sheet_without_current_preset_starts_on_free_config`) probe
the old QTabWidget UX (`tabs.setTabEnabled`). Delete them — Waves 5-7 add
comprehensive replacements (`tests/ui/test_batch_smoke.py`, `_input_panel.py`,
`_method_buttons.py`, `_signal_picker.py`, `_task_list.py`, `_runner_thread.py`,
`_toolbar.py`).

Use the Edit tool to remove those two functions plus their `BatchSheet` import
from `tests/ui/test_drawers.py`.

- [ ] **Step 9: Delete old `batch_sheet.py`**

```bash
rm mf4_analyzer/ui/drawers/batch_sheet.py
```

- [ ] **Step 10: Run smoke + order tests**

```bash
pytest tests/ui/test_batch_smoke.py tests/ui/test_drawers.py tests/ui/test_order_smoke.py -v
```
Expected: green (no `mf4_analyzer.ui.drawers.batch_sheet` import errors,
no failed patches).

- [ ] **Step 11: Manual smoke (optional but recommended)**

Run the app, click 批处理 — confirm dialog opens at 1080×760 with three
disabled toolbar buttons, three pipeline cards, three detail placeholders,
and Cancel/运行 footer. The dialog accepts cancel; clicking 运行 returns
the placeholder preset (which Wave 7 verifies works end-to-end).

- [ ] **Step 12: Commit**

```bash
git add mf4_analyzer/ui/drawers/batch tests/ui/test_batch_smoke.py \
        mf4_analyzer/ui/main_window.py tests/ui/test_order_smoke.py \
        tests/ui/test_drawers.py
git rm mf4_analyzer/ui/drawers/batch_sheet.py
git commit -m "refactor(batch): relocate batch_sheet to drawers/batch/ package shell

Replace single-file batch_sheet.py with a package containing sheet.py
(top-level dialog), pipeline_strip.py (three summary cards), and
__init__.py re-exports. Layout is the placeholder skeleton for waves
5-7; constructor signature and module-level public API
(BatchSheet(parent, files, current_preset=None)) preserved.

Migrate dependent test fixtures: test_order_smoke.py patches the new
module path; pre-redesign tests in test_drawers.py removed (waves 5-7
add coverage of the new layout).

See spec §3.1, §5."
```

### Wave 4 acceptance

- [ ] App opens batch dialog without import errors
- [ ] Smoke tests green
- [ ] codex wave-4 review: approved

---

## Wave 5 — Detail panels (signal picker, method buttons, file states)

**Specialist:** `pyqt-ui-engineer`
**Files:**
- Create: `mf4_analyzer/ui/drawers/batch/signal_picker.py`
- Create: `mf4_analyzer/ui/drawers/batch/method_buttons.py`
- Create: `mf4_analyzer/ui/drawers/batch/input_panel.py`
- Create: `mf4_analyzer/ui/drawers/batch/analysis_panel.py`
- Create: `mf4_analyzer/ui/drawers/batch/output_panel.py`
- Modify: `mf4_analyzer/ui/drawers/batch/sheet.py` (replace placeholders)
- Create: `tests/ui/test_batch_signal_picker.py`
- Create: `tests/ui/test_batch_method_buttons.py`
- Create: `tests/ui/test_batch_input_panel.py`

### Wave brief for orchestrator

Three detail columns. Specialist focus: PyQt5 widget correctness, signal
flow, Chinese font support. No threading yet.

**Components**:
1. `SignalPickerPopup`: chips display + popup with QLineEdit search +
   QListWidget multiselect. Emits `selectionChanged(tuple[str, ...])`.
   Constructor takes `available_signals: list[str]`,
   `partially_available: dict[str, str]` (signal → "(2/3)" hint), and
   initial selection.
2. `MethodButtonGroup`: 4 toggle buttons (FFT / order_time / order_rpm /
   order_track). Emits `methodChanged(str)`.
3. `DynamicParamForm`: shown below method buttons. Slot `on_method_changed`
   re-renders the form per method (tables in spec §3.3). Returns current
   values via `get_params() -> dict`.
4. `FileListWidget`: list of files with state per row (loaded /
   path_pending / probing / probe_failed). "+ 已加载" and "+ 磁盘…"
   buttons. Disk-add triggers a metadata-only probe via `QThreadPool`
   (run a worker that calls `MDF(path).channels_db.keys()` then closes;
   convert exceptions to `probe_failed` state). Emits `filesChanged()`
   and `intersectionChanged(frozenset[str])`.
5. `InputPanel` aggregates FileListWidget + SignalPickerPopup +
   RPM dropdown + time-range field.
6. `OutputPanel` mirrors current output group (dir + checkboxes + format).

`BatchSheet` now wires:
- INPUT / ANALYSIS / OUTPUT panel changes → `_recompute_pipeline_status()`
- `get_preset()` returns a real `AnalysisPreset.free_config(...)` enriched
  via `dataclasses.replace` with `file_ids` / `file_paths` from FileListWidget

**Public BatchSheet / panel accessors** (consumed by Wave 7's `apply_preset`
and tests):

```python
class BatchSheet(QDialog):
    # Accessors (read current UI state)
    def method(self) -> str: ...                          # 'fft' / 'order_*'
    def selected_signals(self) -> tuple[str, ...]: ...    # from SignalPickerPopup
    def rpm_channel(self) -> str: ...                     # InputPanel
    def time_range(self) -> tuple[float, float] | None: ...  # InputPanel
    def file_ids(self) -> tuple: ...                      # FileListWidget loaded entries
    def file_paths(self) -> tuple[str, ...]: ...          # FileListWidget disk entries
    def params(self) -> dict: ...                         # DynamicParamForm
    def output_dir(self) -> str: ...                      # OutputPanel
    def export_data(self) -> bool: ...
    def export_image(self) -> bool: ...
    def data_format(self) -> str: ...

    # Mutators (Wave 7 apply_preset path)
    def apply_method(self, method: str) -> None: ...
    def apply_signals(self, signals: tuple[str, ...]) -> None: ...
    def apply_rpm_channel(self, ch: str) -> None: ...
    def apply_time_range(self, rng: tuple[float, float] | None) -> None: ...
    def apply_params(self, params: dict) -> None: ...
    def apply_outputs(self, out: BatchOutput) -> None: ...
    def apply_files(self, file_ids: tuple, file_paths: tuple[str, ...]) -> None: ...
    def apply_preset(self, preset: AnalysisPreset) -> None: ...  # composes the above
```

These accessors are the contract Wave 7 binds against; specialists adding
panels in Wave 5 must expose equivalent panel-level methods that BatchSheet
delegates to.

### Tasks (high-level — specialist applies TDD per component)

- [ ] **Step 1: Write tests for `SignalPickerPopup`**

`tests/ui/test_batch_signal_picker.py`:
```python
def test_picker_emits_selection_on_check(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    p = SignalPickerPopup(available_signals=["sig_a", "sig_b", "sig_c"])
    qtbot.addWidget(p)
    received = []
    p.selectionChanged.connect(lambda tup: received.append(tup))
    p.set_selected(("sig_a",))
    assert received[-1] == ("sig_a",)


def test_picker_search_filters_list(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    p = SignalPickerPopup(available_signals=["vibration_x", "vibration_y", "temp"])
    qtbot.addWidget(p)
    p.set_search_text("vib")
    visible = p.visible_items()
    assert "vibration_x" in visible
    assert "temp" not in visible


def test_picker_marks_partial_signals_grey(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    p = SignalPickerPopup(
        available_signals=["sig_a"],
        partially_available={"sig_b": "(2/3)"},
    )
    qtbot.addWidget(p)
    assert p.is_disabled("sig_b") is True
    assert "(2/3)" in p.label_for("sig_b")
```

- [ ] **Step 2: Implement `SignalPickerPopup`**

(Implementation: `QPushButton` showing chips → on click, opens floating
`QFrame` containing `QLineEdit` + `QListWidget` with `QCheckBox` items.
`partially_available` items are added with `Qt.ItemIsEnabled` cleared.
Search box filters items via `setHidden`. Loses focus → hide popup.)

Specialist completes implementation; reference spec §3.2 for behavior.

- [ ] **Step 3: Tests for `MethodButtonGroup` + `DynamicParamForm`**

`tests/ui/test_batch_method_buttons.py`:
```python
def test_method_buttons_emit_signal(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import MethodButtonGroup
    g = MethodButtonGroup()
    qtbot.addWidget(g)
    seen = []
    g.methodChanged.connect(seen.append)
    g.set_method("order_time")
    assert seen[-1] == "order_time"


def test_param_form_renders_per_method(qtbot):
    from mf4_analyzer.ui.drawers.batch.method_buttons import (
        MethodButtonGroup, DynamicParamForm,
    )
    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("fft")
    assert "window" in form.visible_field_names()
    assert "nfft" in form.visible_field_names()
    assert "max_order" not in form.visible_field_names()
    form.set_method("order_time")
    assert {"max_order", "order_res", "time_res", "rpm_factor"}.issubset(
        form.visible_field_names())
```

- [ ] **Step 4: Implement `MethodButtonGroup` + `DynamicParamForm`**

(Specialist implements; reference spec §3.3 method-vs-field table.)

- [ ] **Step 5: Tests for `FileListWidget` state machine**

`tests/ui/test_batch_input_panel.py`:
```python
def test_disk_add_triggers_probe(qtbot, tmp_path):
    from mf4_analyzer.ui.drawers.batch.input_panel import FileListWidget
    w = FileListWidget()
    qtbot.addWidget(w)
    # mock probe to return synchronously
    w._probe_signals_for = lambda path: frozenset({"sig_a", "sig_b"})
    w.add_disk_path(str(tmp_path / "fake.mf4"))
    qtbot.wait(50)
    state = w.row_state(str(tmp_path / "fake.mf4"))
    assert state in ("loaded", "probing")  # probing transient


def test_probe_failure_sets_probe_failed(qtbot, tmp_path):
    from mf4_analyzer.ui.drawers.batch.input_panel import FileListWidget
    w = FileListWidget()
    qtbot.addWidget(w)
    def fail(path):
        raise IOError("bad mf4")
    w._probe_signals_for = fail
    path = str(tmp_path / "x.mf4")
    w.add_disk_path(path)
    qtbot.wait(100)
    assert w.row_state(path) == "probe_failed"


def test_intersection_changes_emit_signal(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import FileListWidget
    w = FileListWidget()
    qtbot.addWidget(w)
    seen = []
    w.intersectionChanged.connect(seen.append)
    w.add_loaded_file(0, "a.mf4", frozenset({"sig", "rpm"}))
    w.add_loaded_file(1, "b.mf4", frozenset({"sig", "other"}))
    # Intersection should now be {"sig"}
    assert seen[-1] == frozenset({"sig"})
```

- [ ] **Step 6: Implement `FileListWidget` + `InputPanel`**

(Specialist implements; reference spec §3.2 file state machine table.)

- [ ] **Step 7: Implement `OutputPanel`**

Mirror the output controls from the pre-Wave-4 `batch_sheet.py` (recoverable
from git: `git show HEAD~5:mf4_analyzer/ui/drawers/batch_sheet.py`, lines
50-69 — output group). Field signatures:
```python
class OutputPanel(QWidget):
    """Output column: directory + export checkboxes + format dropdown."""
    changed = pyqtSignal()  # any field changed
    def directory(self) -> str: ...     # str of QLineEdit
    def export_data(self) -> bool: ...
    def export_image(self) -> bool: ...
    def data_format(self) -> str: ...   # 'csv' or 'xlsx'
    def apply_outputs(self, out: BatchOutput) -> None: ...
    def apply_directory(self, path: str) -> None: ...
```
The directory line edit gets a "选择…" button that opens
`QFileDialog.getExistingDirectory`. Default directory is
`~/Desktop/mf4_batch_output` (matches old behavior).

- [ ] **Step 8: Wire panels into `sheet.py`**

Replace placeholders with real panels; implement
`_recompute_pipeline_status()` driven by panel signals; `get_preset()`
assembles the real `AnalysisPreset` and injects file_ids/file_paths via
`dataclasses.replace`.

- [ ] **Step 9: Run all UI tests**

```bash
pytest tests/ui/test_batch_signal_picker.py tests/ui/test_batch_method_buttons.py tests/ui/test_batch_input_panel.py tests/ui/test_batch_smoke.py -v
```

- [ ] **Step 10: Commit**

```bash
git add mf4_analyzer/ui/drawers/batch tests/ui
git commit -m "feat(batch-ui): detail panels with signal picker + method buttons + file states

Implement SignalPickerPopup (chips + search popup + multiselect),
MethodButtonGroup + DynamicParamForm (per-method visible fields per
spec §3.3), FileListWidget (state machine for loaded/path_pending/
probing/probe_failed via QThreadPool probe of MDF.channels_db), and
the InputPanel/AnalysisPanel/OutputPanel composition. BatchSheet
now derives a real AnalysisPreset on get_preset().

See spec §3.2, §3.3, §3.4."
```

### Wave 5 acceptance

- [ ] All UI tests pass
- [ ] Manual: open batch dialog, add a real .mf4 from disk, see probe
      complete and signals appear in picker
- [ ] codex wave-5 review: approved

---

## Wave 6 — Task list + runner thread + cancel button

**Specialist:** `pyqt-ui-engineer`
**Files:**
- Create: `mf4_analyzer/ui/drawers/batch/task_list.py`
- Create: `mf4_analyzer/ui/drawers/batch/runner_thread.py`
- Modify: `mf4_analyzer/ui/drawers/batch/sheet.py`
- Create: `tests/ui/test_batch_task_list.py`
- Create: `tests/ui/test_batch_runner_thread.py`

### Wave brief for orchestrator

This wave makes the dialog functional end-to-end (run real batch from UI).

**Components**:
1. `TaskListWidget`: collapsible header + body. Header reads
   `▾ N 任务待执行 · M 输出` (idle) or `进度 i/N  [progress bar]  ~Ts 剩余`
   (running). Body is a list of rows: icon (⏸/⟳/✓/✗/—) + `file · signal ·
   method` + optional error tooltip. Slots:
   - `apply_dry_run(tasks: list[tuple[str, str, str]], outputs_per_task: int)`
   - `on_event(event: BatchProgressEvent)` — drives icon transitions and
     header progress; ETA computed as
     `(now - run_start) / max(done, 1) * (total - done)`
   - `on_run_started()` / `on_run_finished(result)` — toggle header mode
   Emits no signals (read-only).
2. `BatchRunnerThread(QThread)`: holds preset/output_dir/runner. Constructor
   takes `runner: BatchRunner`, `preset`, `output_dir`. Defines:
   - `progress = pyqtSignal(object)` (BatchProgressEvent)
   - `finished_with_result = pyqtSignal(object)` (BatchRunResult)
   - `request_cancel()`: sets internal `cancel_token` (threading.Event)
   - `run(self)`: wraps `runner.run(...)` in `try/except` so any unexpected
     exception is converted to `BatchRunResult(status='blocked',
     blocked=[str(exc)])` (so unlock always happens via QThread.finished;
     see §6.2 unlock contract)
3. `BatchSheet` updates:
   - Track `_running: bool`. Footer button bar swaps between
     `[Cancel] [运行]` (idle) and `[中断]` (running). Setting `_running=True`
     and disabling Run button **happens synchronously before** thread.start()
     to prevent double-click reentrance.
   - **Dry-run preview is computed from UI state ONLY** (per spec §3.2:
     disk files use the cached probe set, NOT a full sample load). Add
     `BatchSheet._build_dry_run_preview()` returning
     `list[tuple[file_label, signal, method]]` from:
     - For each `file_id` in `InputPanel.file_ids()`: pull `fd =
       self._files[fid]`, iterate target_signals, append a row even if
       signal not in fd.data.columns (UI just shows it; runner emits ✗ at
       run time).
     - For each `file_path` in `InputPanel.file_paths()`: pull cached
       probed signal set from FileListWidget (Wave 5); append rows.
     - **Never** call `BatchRunner._expand_tasks` for preview — that path
       triggers `_resolve_files` which would `loader(path)` full-load disk
       files on the UI thread.
   - On 运行: `tasks = sheet._build_dry_run_preview()`;
     `task_list.apply_dry_run(tasks, outputs_per_task)` (where
     outputs_per_task = export_data + export_image); `lock_editing()`;
     launch `BatchRunnerThread`. Connect signals.
   - On 中断: call `thread.request_cancel()`; disable button so it can't
     be clicked twice.
   - **Unlock is bound to `QThread.finished` (Qt's built-in signal)**, NOT
     `finished_with_result`. The `finished_with_result` handler stores the
     result; the `finished` handler does the unlock + toast based on the
     stored result. This guarantees unlock even if `runner.run()` raises
     before `finished_with_result` would be emitted.
   - `closeEvent`: if `_running`, prompt confirmation; if confirmed, route
     to cancel path; accept close in the QThread.finished handler.

### Tasks

- [ ] **Step 1: Tests for `TaskListWidget`**

`tests/ui/test_batch_task_list.py`:
```python
def test_apply_dry_run_renders_rows(qtbot):
    from mf4_analyzer.ui.drawers.batch.task_list import TaskListWidget
    w = TaskListWidget()
    qtbot.addWidget(w)
    w.apply_dry_run([("a.mf4", "sig", "fft"), ("b.mf4", "sig", "fft")],
                    outputs_per_task=2)
    assert w.row_count() == 2
    assert w.row_icon(0) == "⏸"
    # Header (idle): "▾ 2 任务待执行 · 4 输出"
    assert "2 任务" in w.header_text()
    assert "4 输出" in w.header_text()


def test_on_event_updates_icons_and_progress(qtbot):
    from mf4_analyzer.ui.drawers.batch.task_list import TaskListWidget
    from mf4_analyzer.batch import BatchProgressEvent
    w = TaskListWidget()
    qtbot.addWidget(w)
    w.apply_dry_run([("a.mf4", "sig", "fft"), ("b.mf4", "sig", "fft")],
                    outputs_per_task=1)
    w.on_run_started()
    w.on_event(BatchProgressEvent(
        kind="task_started", task_index=1, total=2,
        file_name="a.mf4", signal="sig", method="fft"))
    assert w.row_icon(0) == "⟳"
    # Header (running): includes "进度 0/2" before first done
    assert "0/2" in w.header_text() or "0 / 2" in w.header_text()
    w.on_event(BatchProgressEvent(
        kind="task_done", task_index=1, total=2,
        file_name="a.mf4", signal="sig", method="fft"))
    assert w.row_icon(0) == "✓"
    assert "1/2" in w.header_text() or "1 / 2" in w.header_text()
    # Progress bar value matches
    assert w.progress_value() == 50  # 1/2 * 100


def test_on_event_failed_and_cancelled_icons(qtbot):
    from mf4_analyzer.ui.drawers.batch.task_list import TaskListWidget
    from mf4_analyzer.batch import BatchProgressEvent
    w = TaskListWidget()
    qtbot.addWidget(w)
    w.apply_dry_run([("a.mf4", "sig", "fft"),
                     ("b.mf4", "sig", "fft"),
                     ("c.mf4", "sig", "fft")], outputs_per_task=1)
    w.on_event(BatchProgressEvent(
        kind="task_failed", task_index=1, total=3,
        file_name="a.mf4", signal="sig", method="fft",
        error="missing signal: sig"))
    assert w.row_icon(0) == "✗"
    assert "missing" in w.row_tooltip(0).lower()
    w.on_event(BatchProgressEvent(
        kind="task_cancelled", task_index=2, total=3,
        file_name="b.mf4", signal="sig", method="fft"))
    assert w.row_icon(1) == "—"


def test_collapse_toggle(qtbot):
    from mf4_analyzer.ui.drawers.batch.task_list import TaskListWidget
    w = TaskListWidget()
    qtbot.addWidget(w)
    w.apply_dry_run([("a.mf4", "sig", "fft")], outputs_per_task=1)
    assert w.is_expanded() is True   # Default expanded
    w.toggle_collapse()
    assert w.is_expanded() is False
    # Body widget hidden when collapsed
    assert not w._body.isVisible()
```

- [ ] **Step 2: Implement `TaskListWidget`**

- [ ] **Step 3: Tests for `BatchRunnerThread`**

`tests/ui/test_batch_runner_thread.py`:
```python
def test_runner_thread_emits_progress_and_result(qtbot, tmp_path):
    """Smoke test that the QThread wrapper forwards events + final result."""
    import numpy as np, pandas as pd
    from mf4_analyzer.batch import (
        AnalysisPreset, BatchOutput, BatchRunner,
    )
    from mf4_analyzer.io import FileData
    from mf4_analyzer.ui.drawers.batch.runner_thread import BatchRunnerThread

    n = 1024
    t = np.arange(n) / 512.0
    df = pd.DataFrame({"Time": t, "sig": np.sin(2*np.pi*50*t)})
    fd = FileData(tmp_path / "x.csv", df, list(df.columns), {}, idx=0)
    preset = AnalysisPreset.from_current_single(
        name="t", method="fft", signal=(0, "sig"),
        params={"fs": 512.0, "window": "hanning", "nfft": 512},
    )
    runner = BatchRunner({0: fd})
    th = BatchRunnerThread(runner, preset, tmp_path / "out")
    events, results = [], []
    th.progress.connect(events.append)
    th.finished_with_result.connect(results.append)
    th.start()
    qtbot.waitUntil(lambda: len(results) == 1, timeout=5000)
    assert results[0].status == "done"
    assert any(e.kind == "run_finished" for e in events)
```

- [ ] **Step 4: Implement `BatchRunnerThread`**

```python
"""QThread wrapping BatchRunner.run with cross-thread event forwarding.

Wraps run() in try/except so unexpected exceptions become a 'blocked'
result. Unlock in BatchSheet uses QThread.finished (Qt-emitted) — never
the result signal — so the dialog can never get stuck locked.
"""
from __future__ import annotations

import threading

from PyQt5.QtCore import QThread, pyqtSignal

from ....batch import BatchRunResult


class BatchRunnerThread(QThread):
    progress = pyqtSignal(object)             # BatchProgressEvent
    finished_with_result = pyqtSignal(object) # BatchRunResult

    def __init__(self, runner, preset, output_dir, parent=None):
        super().__init__(parent)
        self._runner = runner
        self._preset = preset
        self._output_dir = output_dir
        self._cancel_token = threading.Event()

    def request_cancel(self):
        self._cancel_token.set()

    def run(self):
        try:
            result = self._runner.run(
                self._preset,
                self._output_dir,
                on_event=self.progress.emit,
                cancel_token=self._cancel_token,
            )
        except Exception as exc:
            # Convert unexpected exception to a blocked result so the UI
            # gets a deterministic value via finished_with_result, and
            # QThread.finished still fires for unlock.
            result = BatchRunResult(
                status='blocked',
                blocked=[f"runner crashed: {exc}"],
            )
        self.finished_with_result.emit(result)
```

- [ ] **Step 5: Update `sheet.py` — wire run/cancel, lock/unlock**

- [ ] **Step 6: Run all UI tests + manual smoke**

```bash
pytest tests/ui -v
```

- [ ] **Step 7: Manual end-to-end**

Open dialog → pick file/signal → 运行 → watch ⏸ → ⟳ → ✓ row updates → toast on done.
Re-run, click 中断 mid-run → confirm runner stops at task boundary.

- [ ] **Step 8: Commit**

```bash
git add mf4_analyzer/ui/drawers/batch tests/ui
git commit -m "feat(batch-ui): task list + runner thread + cancel path

Add TaskListWidget (collapsible list with ⏸/⟳/✓/✗/— state icons driven
by BatchProgressEvent) and BatchRunnerThread (QThread wrapping
BatchRunner.run with progress/finished_with_result signals and
request_cancel). BatchSheet gains lock_editing/unlock_editing,
[中断] button swap during run, and closeEvent confirmation.

See spec §3.5, §4.5, §6.2."
```

### Wave 6 acceptance

- [ ] Functional end-to-end batch run from UI
- [ ] Cancel works (verified manually + by test)
- [ ] codex wave-6 review: approved

---

## Wave 7 — Toolbar buttons (preset import/export + fill-from-current)

**Specialist:** `pyqt-ui-engineer`
**Files:**
- Modify: `mf4_analyzer/ui/drawers/batch/sheet.py`
- Modify: `mf4_analyzer/ui/main_window.py` (passes current preset)

### Wave brief for orchestrator

Wires the three placeholder toolbar buttons:
1. `从当前单次填入`: enabled iff `current_preset is not None` (passed by
   main_window). Click → `BatchSheet.apply_preset(self._current_preset)`.
2. `导入 preset…`: `QFileDialog.getOpenFileName(filter="*.json")` →
   `load_preset_from_json(path)` → `apply_preset(preset)`. Catch
   `UnsupportedPresetVersion` and `ValueError` → toast.
3. `导出 preset…`: build current preset via `_build_preset_for_export()`
   (uses configuration fields only — strips file_ids/file_paths via
   `dataclasses.replace`) → `QFileDialog.getSaveFileName(filter="*.json")`
   → `save_preset_to_json(preset, path)`. Toast success.

`apply_preset(preset)`:
- For `current_single`: fills file list with `[preset.signal[0]]`,
  fills signal picker with `[preset.signal[1]]`, sets method, sets
  params, sets RPM channel.
- For `free_config`: fills file list keeping current files, sets target_signals
  in picker (red-mark missing), sets method, sets params, sets RPM channel.

### Tasks

- [ ] **Step 1: Tests for apply_preset and import/export**

Create `tests/ui/test_batch_toolbar.py`:
```python
import json
from unittest.mock import patch
from PyQt5.QtWidgets import QFileDialog


def test_apply_preset_free_config_fills_picker(qtbot, tmp_path):
    from mf4_analyzer.ui.drawers.batch import BatchSheet
    from mf4_analyzer.batch import AnalysisPreset, BatchOutput
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    p = AnalysisPreset.free_config(
        name="t", method="order_time",
        target_signals=("vibration_x",), rpm_channel="engine_rpm",
        params={"window": "hanning", "nfft": 1024, "max_order": 20.0},
    )
    sheet.apply_preset(p)
    assert sheet.method() == "order_time"
    assert "vibration_x" in sheet.selected_signals()
    assert sheet.rpm_channel() == "engine_rpm"


def test_apply_preset_current_single_round_trip(qtbot, tmp_path, qt_app_files):
    """current_single preset (from main window) should fill picker with the
    one captured signal and select that file (spec §6.4)."""
    from mf4_analyzer.ui.drawers.batch import BatchSheet
    from mf4_analyzer.batch import AnalysisPreset
    files = qt_app_files  # fixture providing {fid: FileData}
    sheet = BatchSheet(None, files=files)
    qtbot.addWidget(sheet)
    fid = next(iter(files))
    p = AnalysisPreset.from_current_single(
        name="cs", method="fft", signal=(fid, "sig"),
        params={"fs": 1024.0, "window": "hanning", "nfft": 1024,
                "time_range": (1.0, 5.0)},
    )
    sheet.apply_preset(p)
    assert sheet.method() == "fft"
    assert sheet.selected_signals() == ("sig",)
    assert fid in sheet.file_ids()
    assert sheet.time_range() == (1.0, 5.0)


def test_apply_preset_marks_unavailable_signals(qtbot):
    """Imported preset whose target_signals are not in the file intersection
    must red-mark them and warn (spec §4.2 partial-missing rule)."""
    from mf4_analyzer.ui.drawers.batch import BatchSheet
    from mf4_analyzer.batch import AnalysisPreset
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    p = AnalysisPreset.free_config(
        name="m", method="fft",
        target_signals=("absent_signal",),
        params={"window": "hanning", "nfft": 1024},
    )
    sheet.apply_preset(p)
    # Signal still selected, but red-marked
    assert "absent_signal" in sheet.selected_signals()
    assert sheet.signals_marked_unavailable() == ("absent_signal",)


def test_import_unsupported_version_toasts(qtbot, tmp_path):
    from mf4_analyzer.ui.drawers.batch import BatchSheet
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": 99, "name": "x",
                                "method": "fft", "params": {}, "outputs": {}}))
    with patch.object(QFileDialog, "getOpenFileName",
                      return_value=(str(bad), "")):
        sheet._on_import_preset()
    assert sheet._last_toast_kind == "warning"
    assert "不支持" in sheet._last_toast_text


def test_export_strips_runtime_fields(qtbot, tmp_path):
    from mf4_analyzer.ui.drawers.batch import BatchSheet
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    out = tmp_path / "p.json"
    with patch.object(QFileDialog, "getSaveFileName",
                      return_value=(str(out), "")):
        sheet._on_export_preset()
    raw = json.loads(out.read_text())
    for forbidden in ("file_ids", "file_paths", "signal", "rpm_signal"):
        assert forbidden not in raw
    assert raw["schema_version"] == 1
```

(`_last_toast_kind` / `_last_toast_text` are test-helper attributes the
specialist adds to `BatchSheet` to make toast assertions deterministic
without mocking the parent's toast API.)

- [ ] **Step 2: Implement toolbar handlers in `sheet.py`**

- [ ] **Step 3: Implement `apply_preset(preset)`**

- [ ] **Step 4: `main_window.open_batch` change** — already passes
      `current_preset`, so just verify it still works after Wave 4
      relocate.

- [ ] **Step 5: Manual end-to-end**

Run app → batch dialog → 导出 preset to `~/Desktop/test.json` → close →
reopen → 导入 preset → verify all fields restored.

- [ ] **Step 6: Cross-machine smoke** (optional but spec'd)

Copy preset JSON to a colleague's machine; load it. All fields restore.

- [ ] **Step 7: Commit**

```bash
git add mf4_analyzer/ui/drawers/batch
git commit -m "feat(batch-ui): preset import/export + fill-from-current toolbar

Wire the three top-row buttons. Import handles UnsupportedPresetVersion
and corrupt JSON via toast. Export uses dataclasses.replace to strip
file_ids/file_paths before save_preset_to_json (which already
whitelists). apply_preset handles both current_single and free_config
sources.

See spec §6.3, §6.4."
```

### Wave 7 acceptance

- [ ] Round-trip preset save/load works
- [ ] Cross-machine smoke (or simulated via temp dir) green
- [ ] codex wave-7 review: approved

---

## Wave 8 — Cleanup (`signal_pattern` UI removal + dead code sweep)

**Specialist:** `refactor-architect`
**Files:**
- Modify: any remaining UI files mentioning `signal_pattern`
- Verify: backend `signal_pattern` fallback path remains in `batch.py`

### Wave brief for orchestrator

YAGNI sweep. Backend `signal_pattern` stays (tests still construct presets
with it). UI side: confirm no widget has a "signal pattern" input. Sweep
imports / dead code from earlier waves' transitions.

### Tasks

- [ ] **Step 1: Grep for any UI residue**

```bash
grep -r "signal_pattern" mf4_analyzer/ui/ tests/ui/
```
Expected: only test fixtures or comments referencing the fallback;
no live widget input.

- [ ] **Step 2: Confirm backend tests still cover `signal_pattern` path**

```bash
pytest tests/test_batch_runner.py -k "free_config_order_track" -v
```
Expected: pass (this test uses `signal_pattern="sig"`).

- [ ] **Step 3: Remove any orphan imports / dead branches** found in step 1.

- [ ] **Step 4: Final regression sweep**

```bash
pytest -v
```
Expected: all green.

- [ ] **Step 5: Commit if any cleanup needed**

```bash
git add -A
git commit -m "chore(batch): post-redesign cleanup sweep"
```

(If nothing to clean, skip the commit.)

### Wave 8 acceptance

- [ ] Full regression suite green
- [ ] No `signal_pattern` UI input remains
- [ ] codex wave-8 review: approved

---

## Self-review checklist (run after writing this plan)

- [ ] Spec coverage: every section in spec §3-§10 has a wave that delivers it.
  - §3.1 layout → Waves 4 (skeleton) + 5/6 (panels)
  - §3.2 INPUT (incl. file states) → Wave 5
  - §3.3 ANALYSIS dynamic params → Wave 5
  - §3.4 OUTPUT → Wave 5
  - §3.5 task list (run-time states) → Wave 6
  - §4.1 AnalysisPreset extension → Wave 1
  - §4.2 preset JSON → Wave 3
  - §4.3 _expand_tasks two-phase → Wave 2
  - §4.4 BatchProgressEvent + new run signature → Wave 2
  - §4.5 cancel path → Wave 2 (backend) + Wave 6 (UI)
  - §5 component decomposition → Waves 4/5/6 file structure
  - §6 data flows → Waves 5 (config flow), 6 (run flow), 7 (preset IO flow)
  - §7 error/edge table → distributed (Wave 2 backend, Waves 5/6 UI)
  - §8 test plan → tests created in Waves 1-6
  - §9 PR slicing → IS this plan
  - §10 migration → Wave 4 imports + Wave 8 cleanup
- [ ] Type consistency: `BatchProgressEvent`, `BatchRunResult.status`,
      `_resolve_files`, `_expand_tasks`, signatures — all match across waves.
- [ ] No placeholders: every code block contains real, runnable code; every
      step has a concrete command.
