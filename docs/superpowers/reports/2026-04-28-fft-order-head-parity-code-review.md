# Code Review · FFT/Order HEAD Parity Implementation

**Date:** 2026-04-28
**Reviewer:** Claude (Sonnet 4.6) via `code-review-skill`
**Scope:** Commits `5250c75..0abf185` (12 commits, 18 files, 1290 insertions)
**Plan:** `docs/superpowers/plans/2026-04-28-fft-order-head-parity.md`
**Spec:** `docs/superpowers/specs/2026-04-28-fft-order-head-parity-design.md`
**Status:** 💬 **Comment** — approved with optional follow-ups

This document records the code review findings and the analysis of the four
"Important" issues raised. It is **not an execution plan** — it is the historical
record so the user can decide later whether/how to address each item.

---

## Phase 1 · Context

| Metric | Value |
|--------|-------|
| Commits | 12 |
| Files changed | 18 |
| Source LOC added | ~660 |
| Test LOC added | ~631 |
| Test ratio | ~1:1 (TDD discipline visible) |
| Final test count | 376/376 passing |
| Coverage | 4 sub-projects (SP1-SP4) all shipped |

## Phase 2 · High-level architecture

### Praise (🎉)

- **P1 — Defaults preserve backwards compat.** Every new control (`algorithm`,
  `avg_mode`, `amp_y`, etc.) defaults to the legacy behaviour. Existing user
  presets render identically. No silent migration needed.
- **P2 — Tests carry physical meaning.** COT verification uses 175× and 177×
  isolation ratios on synthetic constant-RPM and swept-RPM signals — these
  thresholds collapse to a single FFT bin only if angular resampling is
  correct. They will detect real regressions.
- **P3 — `compute_peak_hold_fft` placement.** DSP helper sits in
  `signal/fft.py` next to `compute_averaged_fft` (resolved during plan
  review). Not in `main_window.py`.
- **P4 — Pre-condition checks in COT.** `_validate` rejects non-monotonic
  time vectors; `compute()` rejects all-zero RPM signals before division.
- **P5 — Cancel point per frame, not per bin.** `_check_cancel()` at the
  top of the COT frame loop matches the existing `OrderAnalyzer` pattern.

### File organisation

- New widget at `mf4_analyzer/ui/widgets/searchable_combo.py` (folderised
  the previously-flat `widgets.py` cleanly via git rename).
- New DSP module `mf4_analyzer/signal/order_cot.py` parallel to existing
  `order.py` — no entanglement, both analyzers callable.
- COT branch in `main_window.py` does the import lazily inside the function
  to avoid loading `qtawesome`/`asammdf` chains transitively.

---

## Phase 3 · Issues by severity

### 🔴 Blocking
*(none)*

### 🟡 Important — analysis follows below in §4

- **I1** COT runs on the GUI thread, freezes UI on long signals
- **I2** Zero-RPM frames silently filled with 0.0 → user reads as "no order energy"
- **I3** `COTParams.time_res` is a dead field, never read by `compute()`
- **I4** `combo_dynamic` initial enable-state not seeded (works today, defends future-default change)

### 🟢 Nit

- **N1** dB reference = current spectrum peak (not absolute full-scale).
  Acceptable for single-channel viewing; document in tooltip.
- **N2** Magic constant `1e-12` repeated in three sites for dB floor.
  Could promote to module-level `_DB_FLOOR_AMP`. Only 3 sites; YAGNI.
- **N3** `SearchableComboBox.setCurrentText` override emits
  `currentIndexChanged` whereas plain `QComboBox.setCurrentText` on an
  editable combo does not. Worth one comment line acknowledging the
  signal-semantics divergence so downstream code wiring
  `currentIndexChanged` doesn't get surprised.

### 💡 Suggestion

- **S1** Two near-duplicate dB-conversion blocks
  (`canvases.py:plot_or_update_heatmap` 1597-1620 and
  `SpectrogramCanvas._color_limits` 1310-1325). Could share a helper.
  Only 2 sites — defer.
- **S2** No "reset to defaults" button on inspector panels. Out of scope.

### 📚 Learning

- `np.errstate(divide='ignore')` (canvases.py:1604) — correct defensive
  scoping for `np.log10(0)` warning suppression.

---

## Phase 4 · Decision

**💬 Comment** — approved with optional follow-ups.

Main code is healthy. Tests are real. Defaults are conservative. The four
Important items are worth addressing but **none block deployment**.

---

# §4 · Important Issues — Detailed Analysis

This section is the analysis of HOW each Important could be fixed. It is
intentionally separate from the plan so it can become a future plan when
the user decides to act on it.

## I1 — COT runs on GUI thread

### Symptom
```python
# mf4_analyzer/ui/main_window.py:1346 (do_order_time, 'cot' branch)
result = COTOrderAnalyzer.compute(sig, rpm, t, p)   # blocks GUI thread
```

### Impact estimate

| Signal size | Approx COT time | UX impact |
|-------------|----------------|-----------|
| T08 (17644 pts @ 100Hz, 176s) | <100 ms | Imperceptible |
| 5 min @ 1 kHz (300k pts) | 2-5 s | Visible freeze |
| 30 min @ 5 kHz (9M pts) | 60+ s | Unacceptable |

### Three repair paths

| Option | Effort | Trade-offs |
|--------|--------|------------|
| **A. Independent COTOrderWorker** | 80-150 LOC + tests | Cleanest. Mirrors existing `OrderWorker` for progress/cancel/generation tracking. New thread class, signal wiring, cancel_token plumbing. |
| **B. Reuse existing OrderWorker, dispatch by `algorithm` flag** | 30-50 LOC | Leverages existing thread infrastructure. Cost: `OrderWorker` becomes algorithm-aware (more branching). Benefit: zero UI changes. |
| **C. Sync execution + `QApplication.processEvents()` between frames** | 3 lines | Stops "completely frozen" appearance but still laggy and progress bar doesn't move. **Band-aid only — discourages anyone from doing A or B properly.** |

### Investigation needed before picking

Read `mf4_analyzer/ui/main_window.py:_dispatch_order_worker` and locate
the `OrderWorker` class. If `OrderWorker` is loosely coupled (accepts a
callable or an analyzer instance), **B** is nearly free. If hard-coded
to `OrderAnalyzer.compute_time_order_result`, **A** is cleaner than
retrofitting B.

### Recommendation
**Do A or B; do NOT do C.** Without progress feedback, the UX hit is
silently bad rather than loudly bad — band-aids in this category tend to
prevent real fixes.

---

## I2 — Zero-RPM frames silently zeroed

### Symptom
```python
# mf4_analyzer/signal/order_cot.py:141-143
if mean_rpm_frame < params.min_rpm_floor:
    continue   # amp_matrix[idx] stays at the np.zeros initialiser
times_arr[idx] = ...   # but time-axis IS populated for the skipped frame
```

The order heatmap at low-RPM time intervals shows pure black (amp=0 → log10
→ -∞ → clip to -100 dB → bottom of colormap). User reads this as "no order
energy at that time" rather than "we couldn't compute orders here".

### Real-data exposure

T08's RPM channel oscillates ±300+ with frequent zero crossings. Each crossing
produces a sub-second window where `mean_rpm_frame < min_rpm_floor=10`. The
heatmap then shows multiple thin vertical black stripes — visually
indistinguishable from "signal lost" or "data corrupt".

### Two repair paths

| Option | Change | Render result |
|--------|--------|---------------|
| **a. Initialise `amp_matrix` with NaN, leave skipped frames as NaN** | 1 line: `np.full(..., np.nan)` instead of `np.zeros(...)` | matplotlib's imshow renders NaN as transparent (showing axes facecolor underneath) — visually distinct from "0 amplitude". User sees a grey/blank patch. Ambiguity gone. |
| **b. Drop skipped frames entirely (shrink matrix and times array)** | More invasive | Time axis becomes non-uniform. `imshow` requires uniform grid → would need to switch to `pcolormesh` for the order canvas. Ripples through `_render_order_time` and breaks the heatmap reuse fast-path at `canvases.py:1582-1601`. |

### Side-effect check for option (a)

NaN in `amp_matrix` propagates through:
- `canvases.py:1602` — already uses `np.nanmax`. Safe.
- `vmin = np.nanmin(m)` (default in `plot_or_update_heatmap`). Safe.
- `result.amplitude.min()`/`.max()` — any non-`nan*` reduction in
  downstream code would propagate NaN. **Audit needed** (likely none in
  current `_render_order_time` path, but verify before merging).

### Recommendation
**Option (a): NaN fill.** Tiny code change, big visual clarity win, but
add a focused regression test:

```python
def test_cot_zero_rpm_frames_render_as_nan_not_zero():
    # signal with deliberate zero-RPM mid-segment
    ...
    assert np.isnan(res.amplitude[mid_zero_frame_idx, :]).all()
    assert not np.isnan(res.amplitude[steady_rpm_frame_idx, :]).any()
```

---

## I3 — `time_res` is a dead field

### Symptom

```python
# order_cot.py:30 (declared)
@dataclass(frozen=True)
class COTParams:
    time_res: float = 0.05      # in seconds, hop in time domain (mapped to angle)
```

```python
# order_cot.py:112 (where it should be used, but isn't)
hop_angle = max(int(nfft * 0.25), 1)            # 75% overlap default — hardcoded
```

`compute()` never reads `params.time_res`. `main_window.py:1335` faithfully
passes `time_res=op['time_res']` from the OrderContextual UI, but it's
silently dropped. The user-facing "时间分辨率" spinbox in the inspector
appears to control COT temporal resolution but actually does nothing
when COT is selected.

### Two repair paths

#### Option A — Wire it up properly (rename to `angle_overlap`)

Conceptually, COT works in the angle domain. "Time resolution" in COT
really means "how much overlap between angle-domain frames". Rename
the field and connect it:

```python
# COTParams field
angle_overlap: float = 0.75   # fraction in [0, 0.95]

# compute() — replace the hardcoded 0.25 hop
hop_angle = max(int(nfft * (1 - params.angle_overlap)), 1)
```

UI side: add a `spin_angle_overlap` to `OrderContextual` (or repurpose the
existing `spin_time_res` to mean "angle overlap" when COT is selected —
risky, ambiguous labelling).

Cost: ~30 LOC + 1 test + UI doc update.

#### Option B — Remove the field, document the limitation

Delete `time_res` from `COTParams`. Update `main_window.py:1335` to drop
the kwarg. Add a docstring note that COT uses fixed 75% overlap in v1.

Cost: ~5 LOC; honest interface. But user can't tune the resolution.

### Impact on existing call sites

Searching the repo:
- Only one construction site in `main_window.py` (the `'cot'` branch).
- Test files (`test_order_cot.py`) construct `COTParams` 4 times with
  `time_res=0.5` or `time_res=0.05` — would need updating.

### Recommendation

**Option A.** "调时间分辨率" is a reasonable user request (controls
horizontal density of the order heatmap). Removing the field would
just leave the question "why doesn't this analyzer support time
resolution like the legacy one does?" Renaming to `angle_overlap` is
honest about what it actually controls.

UI option for clarity: when COT is selected, replace the existing
"时间分辨率" form row with a "重叠率" row (similar to the FFT view's
`spin_avg_overlap`). Show only the relevant control.

---

## I4 — `combo_dynamic` initial enable-state not seeded

### Symptom

```python
# inspector_sections.py — OrderContextual.__init__
self.combo_amp_mode.currentTextChanged.connect(
    lambda txt: self.combo_dynamic.setEnabled(txt == 'Amplitude dB')
)
# (no explicit seed call)
```

Compare with the algorithm picker which IS explicitly seeded:

```python
def _on_algo_changed(txt):
    self.spin_samples_per_rev.setEnabled('COT' in txt)
self.combo_algorithm.currentTextChanged.connect(_on_algo_changed)
_on_algo_changed(self.combo_algorithm.currentText())   # ← explicit seed
```

### Why algorithm needs seed but `combo_dynamic` doesn't (today)

- **algorithm**: default = `'频域映射'`, so `spin_samples_per_rev` should
  be **disabled**. But `QSpinBox` defaults to `enabled=True`. Without
  the explicit seed, initial state would be inconsistent.
- **amp_mode**: default = `'Amplitude dB'`, so `combo_dynamic` should be
  **enabled**. `QComboBox` defaults to `enabled=True`. Defaults coincide
  → no immediate inconsistency. **Today's code happens to be correct.**

### What the issue actually is

**Code-style consistency**, not a runtime bug. If a future change moves
the default to `combo_amp_mode='Amplitude'` (linear), the seed pattern
breaks silently — `combo_dynamic` will start enabled until the user
clicks the amp_mode combo to trigger the lambda.

### Repair (defensive)

```python
def _on_amp_mode_changed(txt):
    self.combo_dynamic.setEnabled(txt == 'Amplitude dB')
self.combo_amp_mode.currentTextChanged.connect(_on_amp_mode_changed)
_on_amp_mode_changed(self.combo_amp_mode.currentText())
```

3 lines. Prevents a class of "default-change time bomb".

### Severity reclassification

This is genuinely a **🟢 Nit, not 🟡 Important**. No current bug, only
future-proofing. Listed as Important in the original review because of
inconsistency with the algorithm-picker pattern; on reflection that's a
style argument, not a correctness one.

---

## Suggested batching for follow-up work

| Batch | Contents | Effort | Files touched |
|-------|----------|--------|---------------|
| **F1 (small, can ship together)** | I2 (NaN fill) + I3 (rename `time_res` → `angle_overlap` and wire it) + I4 (defensive seed) | ~1 hr + tests | `mf4_analyzer/signal/order_cot.py`, `mf4_analyzer/ui/main_window.py`, `mf4_analyzer/ui/inspector_sections.py`, test files |
| **F2 (medium, separate session)** | I1 (COT async worker) | 80-150 LOC | `mf4_analyzer/threading/` (or wherever `OrderWorker` lives), `mf4_analyzer/ui/main_window.py` |

F1 and F2 are non-overlapping in files (F1 doesn't touch worker code; F2
doesn't touch DSP).

If F1 ships, suggested commit subjects:
- `fix(cot): NaN-fill skipped low-RPM frames so renderer can distinguish "no data" from "zero amplitude"`
- `refactor(cot): rename time_res → angle_overlap and wire it through compute()`
- `style(order-ui): explicit seed for combo_dynamic enable state`

If F2 ships, suggested commit subject:
- `feat(cot): async COT order worker with progress/cancel/generation tracking`

Whether to actually ship F1/F2 is left for the user to decide based on
priorities. This document is the record of the analysis, not a commitment
to act.
