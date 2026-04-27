# Wave-4 Review - Batch Blocks Redesign

**Date:** 2026-04-27
**Commit reviewed:** ad28d29
**Reference commit:** 8fb5b9d (squad artifact only)
**Reviewer:** Claude code-review (gating reviewer from W4 onward, replaces codex)
**Verdict:** APPROVED

## Summary

Verdict: APPROVED. The W4 diff is a clean, behavior-preserving relocate of `batch_sheet.py` into a `drawers/batch/` package shell. Scope is exactly the eight files listed in the plan (3 new under `drawers/batch/`, 1 deletion, 1 import fix in `main_window.py`, 1 new smoke test, 2 test edits). Constructor signature and the public `BatchSheet` symbol are preserved. Gating tests are 11/11 green; W1/W2/W3 backend regression suite is 32/32 green. The two pre-existing UI failures the specialist flagged in `tests/ui/test_inspector.py` reproduce identically on the parent commit (`48ee122`), confirming they are not introduced by W4.

## Spec / Plan Conformance

- PASS: Spec §3.1 整体布局 — placeholder shell renders the planned skeleton: top toolbar with three disabled buttons (`从当前单次填入` / `导入 preset…` / `导出 preset…`), `PipelineStrip` with three INPUT/ANALYSIS/OUTPUT cards, three detail-column placeholders, and Cancel/运行 footer. Dialog resizes to 1080×760 (`mf4_analyzer/ui/drawers/batch/sheet.py:21`) per spec §3.1.
- PASS: Spec §5 模块边界 — only the three sanctioned filenames appear under `mf4_analyzer/ui/drawers/batch/` (`__init__.py`, `sheet.py`, `pipeline_strip.py`). No premature siblings (`signal_picker.py`, `method_buttons.py`, `input_panel.py`, `analysis_panel.py`, `output_panel.py`, `task_list.py`, `runner_thread.py`, `toolbar.py`) — those remain W5/W6/W7 territory.
- PASS: Plan Wave 4 Step 3 (`__init__.py`) is verbatim — `mf4_analyzer/ui/drawers/batch/__init__.py:1-4` matches plan lines 1220-1224.
- PASS: Plan Wave 4 Step 4 (`pipeline_strip.py`) is verbatim — `mf4_analyzer/ui/drawers/batch/pipeline_strip.py:1-61` matches plan lines 1230-1290.
- PASS: Plan Wave 4 Step 5 (`sheet.py`) is verbatim — `mf4_analyzer/ui/drawers/batch/sheet.py:1-65` matches plan lines 1296-1360.
- PASS: Plan Wave 4 Step 1 (smoke test) is verbatim — `tests/ui/test_batch_smoke.py:1-13` matches plan lines 1197-1209.
- PASS: Plan Wave 4 Step 6 (main_window import) — `mf4_analyzer/ui/main_window.py:948` reads `from .drawers.batch import BatchSheet`. Plan says line 953 but the actual line is 948; this 5-line drift is content-correct and explicitly allowed by the review brief.
- PASS: Plan Wave 4 Step 7 (`test_order_smoke.py:66`) — patch target is now `'mf4_analyzer.ui.drawers.batch.BatchSheet'`.
- PASS: Plan Wave 4 Step 8 — the two pre-redesign tests `test_batch_sheet_current_single_returns_current_preset` and `test_batch_sheet_without_current_preset_starts_on_free_config` are deleted from `tests/ui/test_drawers.py`, along with their `BatchSheet` import. Surviving tests intact: `test_channel_editor_drawer_constructs`, `test_export_sheet_constructs`, `test_axis_lock_popover_emits`, `test_axis_lock_popover_anchors`, `test_rebuild_time_popover_returns_fs`, `test_rebuild_time_popover_anchors_below_widget`, `test_rebuild_time_popover_does_not_close_on_spin_interaction`.
- PASS: Plan Wave 4 Step 9 — `mf4_analyzer/ui/drawers/batch_sheet.py` is deleted (`git ls-files mf4_analyzer/ui/drawers/` no longer lists it; only the new package files remain).

## Public-contract checks (review brief items 3-7)

- PASS (item 3): The relative import in `sheet.py:11` is `from ....batch import AnalysisPreset` — exactly four dots. Path arithmetic confirms correctness:
  - `sheet.py` lives in package `mf4_analyzer.ui.drawers.batch`
  - `.` → `mf4_analyzer.ui.drawers.batch`
  - `..` → `mf4_analyzer.ui.drawers`
  - `...` → `mf4_analyzer.ui`
  - `....` → `mf4_analyzer` ✓ (resolves `mf4_analyzer.batch`)
  - The old `batch_sheet.py` lived one level shallower and used three dots; bumping to four dots when going one level deeper is correct.
- PASS (item 4): Constructor signature `BatchSheet.__init__(self, parent, files, current_preset=None)` at `sheet.py:16` matches the public contract used by `main_window.open_batch`.
- PASS (item 5): `BatchSheet.get_preset()` returns `AnalysisPreset.free_config(name="placeholder", method="fft")` at `sheet.py:59-61`. `BatchSheet.output_dir()` returns `str(Path.home() / "Desktop" / "mf4_batch_output")` at `sheet.py:63-65`.
- PASS (item 6): All three toolbar buttons set `setEnabled(False)` (Wave 7 wires them) at `sheet.py:30-33`.
- PASS (item 7): `pipeline_strip.py` exposes only the documented surface — `PipelineCard` (class), `PipelineStrip` (class), `PipelineStrip.set_stage(stage_index, status, summary_text)`, and `PipelineStrip.cards` (list). No extra public methods or symbols. `_STAGE_DEFS` is a private module constant.

## Boundary check (forbidden file leak)

`git show ad28d29 --name-only` reports the eight files listed in the W4 plan and nothing else:

```text
mf4_analyzer/ui/drawers/batch/__init__.py        (new)
mf4_analyzer/ui/drawers/batch/pipeline_strip.py  (new)
mf4_analyzer/ui/drawers/batch/sheet.py           (new)
mf4_analyzer/ui/drawers/batch_sheet.py           (deleted)
mf4_analyzer/ui/main_window.py                   (1-line import edit, line 948)
tests/ui/test_batch_smoke.py                     (new)
tests/ui/test_drawers.py                         (deletion of 2 obsolete tests)
tests/ui/test_order_smoke.py                     (1-line patch-target edit, line 66)
```

`git show ad28d29 -- mf4_analyzer/batch.py mf4_analyzer/batch_preset_io.py tests/test_batch_runner.py tests/test_batch_preset_dataclass.py tests/test_batch_preset_io.py` returns empty — no edits to any W1/W2/W3-closed file. PASS.

No premature W5/W6/W7 siblings appear under `drawers/batch/`. PASS.

## Tests run

### Gating tests (review brief item 11)

```text
.venv\Scripts\python.exe -m pytest tests/ui/test_batch_smoke.py tests/ui/test_drawers.py tests/ui/test_order_smoke.py -v --basetemp=.pytest-tmp -p no:cacheprovider
============================= test session starts =============================
platform win32 -- Python 3.13.1, pytest-9.0.3, pluggy-1.6.0
PyQt5 5.15.11 -- Qt runtime 5.15.2 -- Qt compiled 5.15.2
collected 11 items

tests/ui/test_batch_smoke.py::test_batch_sheet_can_be_imported_from_new_package PASSED [  9%]
tests/ui/test_batch_smoke.py::test_pipeline_strip_set_stage_updates_summary PASSED [ 18%]
tests/ui/test_drawers.py::test_channel_editor_drawer_constructs PASSED   [ 27%]
tests/ui/test_drawers.py::test_export_sheet_constructs PASSED            [ 36%]
tests/ui/test_drawers.py::test_axis_lock_popover_emits PASSED            [ 45%]
tests/ui/test_drawers.py::test_axis_lock_popover_anchors PASSED          [ 54%]
tests/ui/test_drawers.py::test_rebuild_time_popover_returns_fs PASSED    [ 63%]
tests/ui/test_drawers.py::test_rebuild_time_popover_anchors_below_widget PASSED [ 72%]
tests/ui/test_drawers.py::test_rebuild_time_popover_does_not_close_on_spin_interaction PASSED [ 81%]
tests/ui/test_order_smoke.py::test_order_contextual_exposes_cancel_signal PASSED [ 90%]
tests/ui/test_order_smoke.py::test_open_batch_drops_stale_preset_signal PASSED [100%]

============================= 11 passed in 3.76s ==============================
```

11/11 PASS. The new smoke tests prove (a) the public symbol `BatchSheet` is reachable via the new package path and (b) `PipelineStrip.set_stage(0, "ok", ...)` correctly mutates `card.stage_status` and `card.summary_label.text()`.

### Backend regression (review brief item 12)

```text
.venv\Scripts\python.exe -m pytest tests/test_batch_runner.py tests/test_batch_preset_dataclass.py tests/test_batch_preset_io.py -v --basetemp=.pytest-tmp -p no:cacheprovider
============================= 32 passed in 5.27s ==============================
```

32/32 PASS (21 runner + 4 dataclass + 7 IO). W1/W2/W3 backend semantics are intact. (Note: the brief estimated "7 + 4 + 25 = 36"; actual count is 21+4+7=32 because `test_batch_runner.py` currently holds 21 tests post-W2.)

### Pre-existing failures verification (review brief item 13)

The two failures the specialist flagged on baseline:

```text
.venv\Scripts\python.exe -m pytest tests/ui/test_inspector.py::test_signal_card_qframes_have_no_white_bleed tests/ui/test_inspector.py::test_fft_contextual_fields_fill_column_under_qss -v --basetemp=.pytest-tmp -p no:cacheprovider

# On W4 commit (ad28d29):
FAILED tests/ui/test_inspector.py::test_signal_card_qframes_have_no_white_bleed
FAILED tests/ui/test_inspector.py::test_fft_contextual_fields_fill_column_under_qss
============================== 2 failed in 3.62s ==============================

# Replayed on parent commit (48ee122) via `git checkout 48ee122 -- mf4_analyzer tests`:
FAILED tests/ui/test_inspector.py::test_signal_card_qframes_have_no_white_bleed
FAILED tests/ui/test_inspector.py::test_fft_contextual_fields_fill_column_under_qss
============================== 2 failed in 3.63s ==============================
```

Both failures reproduce identically on the parent of W4. They are confirmed pre-existing and unrelated to this wave. See "Out of scope" section below.

## Findings

**1. Vestigial dead code in `PipelineCard.__init__` (nit)**

`mf4_analyzer/ui/drawers/batch/pipeline_strip.py:37-39`:

```python
title_row = lay.itemAt(0).widget()
# badge stacked into title row via separate horizontal sub-layout
# (kept simple here)
```

`title_row` is assigned but never used. The badge is created (`self.badge_label`, line 34) and styled, but is never added to the layout — so the badge widget is parented but invisible. This is consistent with the verbatim plan source (which is being copied as-is by the refactor), and the smoke test only asserts on `summary_label.text()` and `stage_status`, so it passes. Wave 5 or Wave 6 should add the badge into a horizontal sub-layout next to the title and remove the dead `title_row` line. Not a W4 blocker — flagging for downstream waves so it doesn't get forgotten.

**2. `set_stage` accepts unknown status silently (nit)**

`pipeline_strip.py:54-61` — if a caller passes a `status` not in `{"ok", "warn", "pending"}`, `c.stage_status` is set to that arbitrary string while the badge falls back to the warn glyph and a fallback color. No validation, no warning. Plan-faithful, fine for placeholder. Worth pinning a `raise ValueError` or `assert` once panels start driving this in W5+.

**3. `_STAGE_DEFS` `index` field is human-displayed but parallel to list index (nit)**

The dict's `"index": 1/2/3` is purely cosmetic (used in the title `f"{stage_def['index']}. {stage_def['title']}"`). Callers index `cards[]` 0-based, so `set_stage(0, ...)` updates the card whose displayed title says "1. INPUT". The smoke test exercises this off-by-one-looking pattern explicitly (`strip.set_stage(0, "ok", ...)` → `strip.cards[0]`), so the contract is "0-based stage_index". Fine, just slightly confusing — could become a footgun later if a panel writes `set_stage(1, ...)` thinking "stage 1 = INPUT". Not a W4 issue.

No blocker findings. No should-fix findings.

## Out of scope (pre-existing failures, not for W4 to fix)

These two failures exist on the parent of W4 (`48ee122`) and are explicitly out of W4's scope. Verified by checkout-replay above.

1. `tests/ui/test_inspector.py::test_signal_card_qframes_have_no_white_bleed` — `style.qss` is read via `Path.read_text()` without `encoding='utf-8'`, raising `UnicodeDecodeError` on cp936-default Windows. Same bug class as the W3 lesson `signal-processing/2026-04-27-pathlib-text-io-needs-explicit-utf8-on-windows.md`. Tracked work, separate from batch-blocks redesign.
2. `tests/ui/test_inspector.py::test_fft_contextual_fields_fill_column_under_qss` — assertion error with unknown root cause. Tracked work, separate from batch-blocks redesign.

Recommendation: file these under a UI-baseline cleanup track (or hand them to a follow-up `pyqt-ui-engineer` dispatch); do not gate W5 on them.

## Verdict reasoning

- All eight files in the W4 diff match the plan and the spec sections cited.
- Public contract preserved: `BatchSheet(parent, files, current_preset=None)`, `get_preset()`, `output_dir()`, and the toolbar's three disabled buttons.
- The 4-dot relative import in `sheet.py` is path-arithmetically correct for the new package depth, and is verified by the smoke test that imports `from mf4_analyzer.ui.drawers.batch import BatchSheet`.
- No leak into W1/W2/W3-closed files (`mf4_analyzer/batch.py`, `mf4_analyzer/batch_preset_io.py`, `tests/test_batch_runner.py`, `tests/test_batch_preset_dataclass.py`, `tests/test_batch_preset_io.py`).
- No premature W5/W6/W7 siblings under `drawers/batch/`.
- 11/11 gating tests green; 32/32 backend regression green.
- Two flagged UI failures are pre-existing and reproduce identically on the W4 parent commit.

Verdict: **APPROVED**.

Blockers: None.

Wave 5 may proceed.
