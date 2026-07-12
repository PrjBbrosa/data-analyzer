# dB Reference 默认值、自动解析与结果标识 — Implementation Plan

Date: 2026-07-12  
Spec: `docs/analyzer/specs/2026-07-12-db-reference-defaults-and-labeling-spec.md`  
Approved visual reference: `docs/analyzer/reviews/reports/2026-07-12-db-reference-defaults-draft.html`

## Goal

按依赖顺序实现一套 shared dB reference system：纯 resolver/formatter、版本化用户
catalog、科学计数输入、三个 Inspector compound control、Auto/Manual state、
per-source/pane render、dB/dBA/re 标签、Batch output 和 rendered visual proof。

本计划完成前不得以“按钮已出现”作为交付结论。最终必须同时通过基本操作、旧状态
兼容、缓存边界、混合 source 安全和 HTML→TraceLab Qt 视觉验收。

## Global Constraints

- 实施前完整阅读 spec 和 HTML；HTML 决定信息层级，`style.qss` 决定 Qt tokens。
- 每个非纯视觉任务先补失败测试，确认失败原因正是缺失的新契约，再写实现。
- 使用现有 PyQt5、pyqtgraph、qtawesome、QSettings；不新增第三方依赖。
- 保留 `ctx.spin_db_ref` 兼容 alias；不要一次性重命名现有 call sites。
- `db_reference` / mode / catalog revision 不得进入 compute cache keys。
- `weighting` 必须继续进入 FFT、FFT-time、Order compute keys。
- `apply_params` 的 partial-dict guard 和旧 preset missing-key 规则不得回归。
- inactive/split pane 的 source 以 `AnalysisViewState.panes[*].sources` 为事实。
- Batch/worker code 不得 import PyQt UI 或直接读取全局 QSettings；通过 immutable
  catalog snapshot 注入。
- Qt render probes 必须使用隔离 QSettings，避免污染用户真实配置。
- 不自动 commit、push 或 merge；这些动作等待用户明确授权。
- 所有 pytest 命令使用项目 venv；offscreen 命令统一：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest ...
```

## Task 0 — Baseline、Literal Checklist 与工作区保护

**Files**

- Read: spec + HTML
- Read: relevant current source/test anchors
- Do not modify product source in this task step

### Step 0.1 — Confirm scope

```bash
git status --short --branch
git diff --stat
```

Expected before implementation: approved HTML/spec/plan changes only. Preserve unrelated user
changes if the working tree changes later.

### Step 0.2 — Build literal checklist

Create an execution checklist keyed to spec A1–A15. It must explicitly include:

- `1e-12`, `1e-9`, `1e-6`, `2e-5`;
- `db_reference_mode`, `manual`, `metadata`, `user`, `system`, `generic`, `fallback`;
- `dBA`, `per-curve reference`, `20 µPa`, `dB re 1 Nm`（generic 无 ⚠）;
- manual color-level shift `20·log10(ref_old/ref_new)`;
- `nudge.db_ref_manual_default`;
- `catalog_v1`, `hidden_builtin_ids`, `prefer_channel_metadata`;
- FFT direct/cache/overlay, FFT-time/Order colorbar/slice/readout, Batch image;
- offscreen + macOS on-screen gates.

### Step 0.3 — Baseline focused suite

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_inspector.py \
  tests/ui/test_analysis_multiview_integration.py \
  tests/ui/test_pg_line_canvas.py \
  tests/ui/test_pg_heatmap_canvas.py \
  tests/test_db_conversion_convergence.py \
  tests/test_cache_key_dataclass_binding.py \
  tests/test_batch_preset_io.py \
  tests/test_project_io_analysis_views.py -q
```

Record the exact baseline count. A pre-existing failure is reported and isolated before feature
work; it is not silently absorbed into this scope.

## Task 1 — Pure Catalog、Resolver、Validation 与 Label Formatter

**Files**

- Create: `mf4_analyzer/db_reference.py`
- Create: `tests/test_db_reference.py`
- Modify only if needed to centralize an existing helper:
  `mf4_analyzer/ui/inspector_sections/_helpers.py`

### Step 1.1 — Write failing domain tests

Add tests with literal names/contracts:

```python
def test_builtin_db_reference_catalog_matches_spec_values(): ...
def test_unit_normalization_is_exact_not_substring_based(): ...
def test_resolver_priority_manual_metadata_user_system_fallback(): ...
def test_invalid_metadata_falls_through_without_crashing(): ...
def test_pa_without_sound_quantity_or_audio_hint_does_not_assume_spl(): ...
def test_unit_not_in_catalog_resolves_generic_without_warning(): ...
def test_generic_label_uses_actual_unit_and_no_warning_marker(): ...
def test_generic_empty_unit_label_is_db_re_1(): ...
def test_ambiguous_unit_only_match_is_fallback_with_warning(): ...
def test_duplicate_quantity_alias_is_rejected(): ...
def test_g_reference_is_si_acceleration_equivalent(): ...
def test_axis_formatter_emits_db_dba_20upa_and_linear_labels(): ...
def test_mixed_formatter_emits_per_curve_reference(): ...
def test_reference_validator_requires_finite_positive_value(): ...
```

Run:

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/test_db_reference.py -q
```

Expected: FAIL because the module/API does not exist.

### Step 1.2 — Implement pure types and immutable built-ins

Implement the spec types and stable IDs:

- `DbReferenceEntry`
- `ChannelReferenceFacts`
- `DbReferenceResolution`
- factory catalog constant/factory
- `normalize_unit()` and `normalize_quantity()`
- `validate_reference()`
- `resolve_db_reference()`
- `format_reference_editor()`
- `format_reference_pretty()`
- `format_amplitude_label()` / mixed-label helper
- a shared legacy-param migration helper used later by View/preset/Batch paths

Move or delegate `_helpers._normalize_unit()` to the pure implementation so unit normalization
does not fork. Preserve the public/private call shape used by preset recommendation tests.

### Step 1.3 — Green domain tests

Run Task 1 tests plus existing normalization/preset recommendation tests selected from
`tests/ui/test_inspector.py`.

## Task 2 — Versioned QSettings Store And Catalog Revision

**Files**

- Create: `mf4_analyzer/ui/db_reference_settings.py`
- Create: `tests/ui/test_db_reference_settings.py`

### Step 2.1 — Write failing isolated-store tests

Use `QSettings(path, QSettings.IniFormat)` under `tmp_path`. Tests:

```python
def test_store_first_load_uses_factory_catalog_and_metadata_preference_on(): ...
def test_store_round_trip_override_custom_hidden_and_preference(): ...
def test_modified_builtin_is_reported_as_user_override(): ...
def test_restore_removes_user_delta_but_does_not_implicitly_toggle_preference(): ...
def test_malformed_or_unknown_schema_falls_back_without_overwriting_raw_value(): ...
def test_invalid_save_is_atomic_and_keeps_previous_catalog(): ...
def test_catalog_revision_increments_only_after_successful_commit(): ...
```

Expected: FAIL because store does not exist.

### Step 2.2 — Implement store

Implement:

- exact QSettings keys from spec;
- JSON delta encode/decode (`overrides`, `custom`, `hidden_builtin_ids`);
- complete validation before write;
- `sync()` and error result;
- immutable catalog snapshot API for worker/Batch injection;
- monotonically increasing in-process `revision` after successful save/restore;
- non-destructive fallback signal/message for malformed data.

Do not let tests instantiate the user's default QSettings.

### Step 2.3 — Green store tests

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_db_reference.py tests/ui/test_db_reference_settings.py -q
```

## Task 3 — Scientific Editor、Compound Control 与 Manager Dialog

**Files**

- Create: `mf4_analyzer/ui/widgets/db_reference.py`
- Create: `mf4_analyzer/ui/db_reference_dialog.py`
- Modify: `mf4_analyzer/ui/widgets/__init__.py` only if project exports require it
- Modify: `mf4_analyzer/ui_kit/style.qss`
- Create: `tests/ui/test_db_reference_controls.py`

### Step 3.1 — Write failing widget/geometry tests

Tests must create widgets with isolated settings/service and assert:

```python
def test_scientific_reference_editor_round_trips_small_values(qtbot): ...
def test_invalid_reference_commit_restores_last_valid_without_mode_change(qtbot): ...
def test_user_edit_switches_auto_to_manual_only_on_commit(qtbot): ...
def test_compound_control_exposes_required_object_names_and_spin_alias(qtbot): ...
def test_manage_button_is_square_and_matches_editor_rendered_height(qtbot): ...
def test_auto_manual_badge_text_color_state_and_no_clipping(qtbot): ...
def test_source_line_elides_but_tooltip_keeps_full_text(qtbot): ...
def test_dialog_cancel_and_escape_leave_store_and_view_unchanged(qtbot): ...
def test_dialog_save_is_atomic_and_updates_provenance(qtbot): ...
def test_dialog_restore_uses_factory_working_copy_until_save(qtbot): ...
def test_dialog_rejects_invalid_and_duplicate_rows_inline(qtbot): ...
```

Expected: FAIL because widgets/dialog do not exist.

### Step 3.2 — Implement `ScientificReferenceSpinBox`

- subclass existing compact spinbox behavior;
- preserve no-button QSS/property contract;
- parse both decimal and scientific notation;
- compact general/scientific display;
- commit/revert behavior from spec;
- no silent `1e-12` denominator clamp.

### Step 3.3 — Implement `DbReferenceControl`

- required object names;
- `spin_db_ref`-compatible editor methods/signals;
- square `mdi.tune-vertical` button;
- visible A/M badge and source line;
- signals for manage request, mode commit and value commit;
- no direct QSettings access.

### Step 3.4 — Implement `DbReferenceDefaultsDialog`

- working-copy catalog;
- current View Auto toggle;
- metadata preference toggle;
- editable/scrollable table;
- add/delete/restore/cancel/save;
- inline validation and atomic commit;
- accessible names and standard Esc behavior.

### Step 3.5 — Add scoped QSS only

Use `#dbReferenceControl`, `#dbReferenceManageButton`, `#dbReferenceModeBadge`,
`#dbReferenceSourceLabel`, `QDialog#DbReferenceDefaultsDialog`, and dialog child object names.
Do not modify generic `QDialog`, `QToolButton`, `QLineEdit`, `QDoubleSpinBox` rules.

### Step 3.6 — Green widget tests

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_db_reference_settings.py tests/ui/test_db_reference_controls.py -q
```

## Task 4 — Integrate All Three Inspector Contexts And Param Contracts

**Files**

- Modify: `mf4_analyzer/ui/inspector_sections/_helpers.py`
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_fft.py`
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_fft_time.py`
- Modify: `mf4_analyzer/ui/inspector_sections/contextual_order.py`
- Modify: `mf4_analyzer/ui/analysis_view_bridge.py` only if explicit migration hook is needed
- Modify: `tests/ui/test_inspector.py`

### Step 4.1 — Extend existing Inspector tests first

Add/extend tests near the current dB-reference row and narrow-pane assertions:

```python
def test_all_analysis_contexts_use_shared_db_reference_compound_control(qtbot): ...
def test_db_reference_compound_row_stays_below_weighting_and_within_320px(qtbot): ...
def test_all_context_params_emit_mode_and_effective_value(qtbot): ...
def test_apply_params_missing_reference_keys_preserves_mode_value_and_weighting(qtbot): ...
def test_partial_db_reference_value_does_not_force_mode(qtbot): ...
def test_new_preset_round_trip_preserves_mode_and_value(qtbot): ...
def test_legacy_preset_value_without_mode_migrates_to_manual(qtbot): ...
def test_legacy_preset_without_reference_leaves_current_state_unchanged(qtbot): ...
```

Expected: FAIL against the numeric-only rows.

### Step 4.2 — Replace row hosts, keep alias

For each Contextual:

- instantiate shared compound control;
- expose `self.db_reference_control`;
- keep `self.spin_db_ref = control.editor`;
- add the compound root through existing `_fit_field`/form layout without widening the Inspector;
- preserve row order immediately below weighting;
- connect existing display-only rerender signals through the editor/control once, not twice.

### Step 4.3 — Extend get/current/apply/preset

- emit both mode and value;
- guard optional keys in partial apply;
- migrate full legacy preset value-without-mode to Manual;
- block signals during programmatic Auto resolution;
- do not let catalog/source updates call `_on_preset_param_changed` as if the user edited a recipe.

### Step 4.4 — Green Inspector suite

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_inspector.py tests/ui/test_db_reference_controls.py -q
```

## Task 5 — MainWindow Service、Channel Facts 与 Auto Propagation

**Files**

- Modify: `mf4_analyzer/ui/main_window/window.py`
- Modify: `mf4_analyzer/ui/main_window/_analysis_mixin.py`
- Modify: `mf4_analyzer/ui/inspector.py` if one service injection point is required
- Modify/Create tests in: `tests/ui/test_analysis_multiview_integration.py`
- Modify: `tests/test_head_hdf_loader.py` only for missing metadata validation coverage

### Step 5.1 — Write failing source/resolution tests

Add tests:

```python
def test_channel_reference_facts_reads_head_quantity_unit_and_db_reference(...): ...
def test_selected_head_channel_auto_applies_metadata_reference(...): ...
def test_metadata_preference_off_uses_user_or_system_catalog(...): ...
def test_invalid_metadata_falls_through_to_catalog(...): ...
def test_manual_view_ignores_source_and_catalog_changes(...): ...
def test_catalog_save_rerenders_visible_auto_view_without_compute(...): ...
def test_focused_pane_controls_do_not_overwrite_inactive_pane_resolution(...): ...
```

Expected: FAIL because source change currently only reads unit/preset recommendation.

### Step 5.2 — Own one shared service

MainWindow owns one settings/service instance and injects it into all three Contextual controls.
The service exposes catalog snapshot, preference, revision and change signal. Dialog openings from
any control target the focused section/View but edit the same global catalog.

### Step 5.3 — Add `ChannelReferenceFacts` adapter

Build facts from:

- `fd.channel_metadata[ch]["quantity"]`;
- `fd.channel_metadata[ch]["unit"]` or `fd.channel_units[ch]`;
- raw `fd.channel_metadata[ch]["db_reference"]`;
- `fd.is_audio_source()`.

Never read sample arrays. Missing fields become empty facts and continue safely.

### Step 5.4 — Apply source/pane changes

- Auto focused source resolves with signals blocked and refreshes control source line;
- Manual does not change;
- pane focus switch resolves that pane only;
- inactive pane/source truth comes from `PaneState`;
- service change triggers cache-backed rerender for the current Auto section and marks other Auto
  section render signatures stale without computing.

### Step 5.5 — Green integration tests

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_head_hdf_loader.py \
  tests/ui/test_analysis_multiview_integration.py \
  tests/ui/test_inspector.py -q
```

## Task 6 — FFT Per-source Conversion、Mixed Labels、Legend/Readout And Signature

**Files**

- Modify: `mf4_analyzer/ui/main_window/_fft_mixin.py`
- Modify: `mf4_analyzer/ui/main_window/window.py`
- Modify: `mf4_analyzer/ui/main_window/_analysis_mixin.py`
- Modify: `mf4_analyzer/ui/pg_canvas/line_canvas.py`
- Modify: `tests/ui/test_analysis_multiview_integration.py`
- Modify: `tests/ui/test_pg_line_canvas.py`
- Modify: `tests/test_cache_key_dataclass_binding.py`

### Step 6.1 — Write failing FFT tests

```python
def test_fft_auto_overlay_converts_each_entry_with_its_source_reference(...): ...
def test_fft_same_reference_uses_exact_axis_label(...): ...
def test_fft_mixed_reference_uses_per_curve_axis_and_entry_labels(...): ...
def test_fft_mixed_a_weighting_uses_dba_per_curve_label(...): ...
def test_fft_cached_reentry_reformats_after_catalog_change_without_compute(...): ...
def test_fft_render_signature_tracks_per_source_resolution_not_global_first_source(...): ...
def test_fft_hover_readout_discloses_each_curve_reference(...): ...
def test_db_reference_mode_and_catalog_revision_stay_out_of_compute_cache_key(): ...
```

Expected: FAIL because current `_fft_entry_from_cache()` reads one Inspector value and current axis
hard-codes `Amplitude (dB)`.

### Step 6.2 — Resolve at entry construction

For each `(fid, ch)`:

- resolve reference using current View mode and service snapshot;
- convert cached linear amp with that validated value;
- retain `amp_for_xlim` linear;
- add stable entry metadata such as `db_reference_resolution` and formatted readout suffix;
- keep the base source label separately from formatted legend/readout text.

### Step 6.3 — Format exact or mixed axis

Collect all entry identities `(value, unit)`:

- one identity → exact canonical axis;
- more than one → `Amplitude (dB[A] · per-curve reference)`;
- every curve legend/readout discloses its own `dB[A] re ...`.

Avoid duplicating the reference in the time-preview curve names.

### Step 6.4 — Fix denominator handling

Remove `max(reference, 1e-12)` as a reference coercion. Require the shared validator before
conversion and leave numerator zero protection inside the conversion helper.

### Step 6.5 — Render signature and cache proof

Include mode, service revision (Auto only), and per-source resolved identity in the render
signature/stale check. Do not touch `_fft_compute_cache_params` output.

### Step 6.6 — Green FFT tests

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_line_canvas.py \
  tests/ui/test_analysis_multiview_integration.py \
  tests/test_cache_key_dataclass_binding.py \
  tests/test_db_conversion_convergence.py -q
```

## Task 7 — FFT-vs-Time / Order Colorbar、Slice、Readout And Remarks

**Files**

- Modify: `mf4_analyzer/ui/main_window/_fft_time_mixin.py`
- Modify: `mf4_analyzer/ui/main_window/_order_mixin.py`
- Modify: `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py`
- Modify: `tests/ui/test_pg_heatmap_canvas.py`
- Modify: `tests/ui/test_analysis_multiview_integration.py`
- Modify: `tests/test_db_conversion_convergence.py`

### Step 7.1 — Write failing heatmap tests

```python
def test_fft_time_dba_colorbar_slice_and_readout_share_reference(...): ...
def test_order_db_colorbar_slice_and_readout_share_reference(...): ...
def test_heatmap_linear_a_weighted_label_never_says_dba(...): ...
def test_heatmap_two_panes_resolve_distinct_saved_sources(...): ...
def test_heatmap_reference_change_rerenders_cached_result_without_worker(...): ...
def test_heatmap_remark_z_unit_includes_db_or_dba_reference_context(...): ...
def test_heatmap_manual_levels_shift_with_reference_delta(...): ...
def test_heatmap_auto_levels_rederive_after_reference_change(...): ...
def test_heatmap_level_shift_never_clips_matrix(...): ...
```

Expected: FAIL because `heatmap_canvas.py` hard-codes `Amplitude (dB)` and `dB` in several paths.

### Step 7.2 — Pass explicit display label context

Extend heatmap render API with explicit formatted values rather than importing UI service inside
the canvas, for example:

- `amplitude_label` for slice left axis;
- `colorbar_label` via existing argument;
- `readout_unit` / reference suffix for cursor and remarks.

Store the latest display context on canvas and replace every target hard-code. Default arguments
must preserve unrelated legacy callers.

### Step 7.3 — FFT-time renderer

Resolve the pane source, create one label context, and pass the same context to colorbar, slice,
readout and remarks. Keep `db_reference` render-only and existing auto-level writeback unchanged.

### Step 7.3a — Manual color-level shift on reference change (spec 8.3.1)

When the effective reference changes for a heatmap section (Auto re-resolution or Manual commit),
shift any manual z-window by `delta = 20*log10(ref_old/ref_new)` so the tuned visual window keeps
tracking the shifted dB matrix. Auto levels simply re-derive. Never clip the data matrix as part of
this (the 2026-06-21 color-scale incident red line). Cover both FFT-time and Order paths.

### Step 7.4 — Order renderer

Preserve current external dB pre-conversion and explicit `vmin/vmax` behavior. Validate and use the
effective reference directly — this removes the `max(float(...), 1e-12)` coercion at
`_order_mixin.py:570`; pass the same label context to all visible/readout consumers.

### Step 7.5 — Green heatmap tests

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_heatmap_canvas.py \
  tests/ui/test_analysis_multiview_integration.py \
  tests/test_db_conversion_convergence.py \
  tests/test_cache_key_dataclass_binding.py -q
```

## Task 8 — AnalysisView/Preset/Project Migration

**Files**

- Modify: `mf4_analyzer/ui/analysis_view_state.py`
- Modify: `mf4_analyzer/ui/analysis_view_bridge.py` if needed
- Modify: three Contextual preset paths from Task 4
- Modify: `mf4_analyzer/ui/project_io.py` only if nested schema validation needs an explicit hook
- Modify: `tests/test_project_io_analysis_views.py`
- Modify: `tests/ui/test_analysis_multiview_integration.py`
- Modify: `tests/ui/test_inspector.py`

### Step 8.1 — Write migration tests

```python
def test_analysis_view_schema2_round_trip_preserves_db_reference_mode_and_value(): ...
def test_schema1_view_value_without_mode_migrates_to_manual(): ...
def test_schema1_view_without_reference_does_not_inject_hardcoded_value(): ...
def test_project_reopen_preserves_auto_manual_per_section_and_pane_sources(...): ...
def test_project_save_in_time_mode_does_not_replace_inactive_analysis_sources(...): ...
def test_old_preset_missing_weighting_and_reference_keys_preserves_live_state(...): ...
```

Expected: FAIL because nested schema remains 1 and no mode exists.

### Step 8.2 — Implement nested schema migration

- bump `AnalysisViewState` nested schema to 2;
- migration keys off "params has `db_reference` and no `db_reference_mode`", NOT the nested
  `schema` number — `from_dict()` currently ignores the `schema` field entirely, and that is also
  what keeps older builds able to open schema-2 projects (they apply the snapshot value
  manual-style); the bump to 2 is declarative;
- note the consequence (spec S5): because current `get_params()` always emits `db_reference`,
  ALL existing views/presets migrate to Manual; this is intended, do not "fix" it;
- migrate schema 1 value-without-mode to Manual;
- keep missing reference absent;
- do not unnecessarily bump top-level `.tlproj` schema;
- retain current fid remap and inactive-source capture behavior.

### Step 8.3 — Green persistence tests

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_project_io_analysis_views.py \
  tests/ui/test_analysis_multiview_integration.py \
  tests/ui/test_inspector.py -q
```

## Task 9 — Batch Auto Resolution And Image Label Parity

**Files**

- Modify: `mf4_analyzer/batch.py`
- Modify: `mf4_analyzer/batch_preset_io.py`
- Modify: `mf4_analyzer/ui/drawers/batch/sheet.py`
- Modify: `mf4_analyzer/ui/main_window/window.py` Batch entry points
- Modify: `tests/test_batch_runner.py`
- Modify: `tests/test_batch_preset_io.py`
- Modify: `tests/test_db_conversion_convergence.py`
- Modify: `tests/ui/test_batch_runner_thread.py` only if constructor injection affects it

### Step 9.1 — Write failing Batch tests

```python
def test_batch_runner_auto_resolves_each_target_channel_metadata_or_unit(tmp_path): ...
def test_batch_runner_accepts_immutable_catalog_snapshot_without_qsettings(tmp_path): ...
def test_batch_legacy_value_without_mode_is_manual(tmp_path): ...
def test_batch_fft_image_label_contains_exact_db_reference(tmp_path): ...
def test_batch_a_weighted_image_uses_dba_reference(tmp_path): ...
def test_batch_heatmap_image_colorbar_uses_shared_label_formatter(tmp_path): ...
def test_batch_csv_values_are_identical_across_reference_changes(tmp_path): ...
```

Expected: FAIL because Batch currently has no resolver snapshot and hard-codes generic labels.

### Step 9.2 — Inject catalog snapshot

Extend `BatchRunner.__init__` with backward-compatible optional keyword arguments:

```python
BatchRunner(
    files,
    loader=None,
    *,
    db_reference_catalog=None,
    prefer_channel_metadata=True,
)
```

Existing direct tests/callers continue to use factory catalog. MainWindow/BatchSheet pass the
current service snapshot and preference before starting the thread. Worker code receives plain
Python data only.

### Step 9.3 — Resolve per expanded task

At `(FileData, signal_name)` task execution:

- migrate params request;
- build ChannelReferenceFacts from that target;
- resolve Auto or preserve Manual;
- pass an output-param copy with effective reference + formatted label context to image builder;
- leave dataframe/CSV generation linear and unchanged.

### Step 9.4 — Replace Batch label hard-codes

Use shared formatter for FFT y label and heatmap colorbar. Keep output metadata useful for tests
(`colorbar_label`, effective reference/source) without changing exported numeric columns.

Remove the `max(db_reference, 1e-12)` reference coercions at `batch.py:943` and `batch.py:965`
(the FFT one at `_fft_mixin.py:38` is Task 6.4, the Order one at `_order_mixin.py:570` is
Task 7.4) — require the shared validator instead; Step 11.2's audit is the backstop, not the plan.

### Step 9.5 — Green Batch tests

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_batch_runner.py \
  tests/test_batch_preset_io.py \
  tests/test_db_conversion_convergence.py \
  tests/ui/test_batch_runner_thread.py -q
```

## Task 10 — HTML-to-TraceLab Visual Parity And UI Tour

**Files**

- Modify: `mf4_analyzer/ui_kit/style.qss`
- Create: `scripts/db_reference_ui_tour.py`
- Modify: `tests/ui/test_db_reference_controls.py`
- Modify: `tests/ui/test_inspector.py`
- Reference only: approved HTML

### Step 10.1 — Add deterministic tour states

The tour uses synthetic `FileData` with explicit channel metadata and isolated temporary
QSettings. It must navigate/render the nine spec states:

1. FFT Auto system acceleration;
2. FFT Manual M;
3. FFT dBA;
4. mixed FFT per-curve;
5. FFT-time dBA map + slice;
6. Order map + slice;
7. manager factory;
8. manager edited/error;
9. narrow 960px application / real Inspector width.

Tour CLI:

```bash
PYTHONPATH=. .venv/bin/python scripts/db_reference_ui_tour.py \
  --assert --shots /tmp/db-reference-offscreen
PYTHONPATH=. .venv/bin/python scripts/db_reference_ui_tour.py \
  --assert --onscreen --shots /tmp/db-reference-onscreen
```

### Step 10.2 — Structural/geometry assertions

The `--assert` path checks:

- all three object-name sets exist exactly once;
- button outer height equals editor outer height and button is square;
- compound rect stays inside the 288–320px Inspector content rect;
- source line is one line; scientific text is not elided into an unusable token;
- badge rect is fully contained and all corner pixels required by its round shape are transparent;
- dialog fits available screen and footer/table are visible;
- chart labels match literal canonical strings.

### Step 10.3 — Visual translation checklist

Compare on-screen Qt screenshots to HTML for hierarchy/proportion, while checking TraceLab token
translation:

- same editor + utility-button composition;
- same blue A / amber M status relationship;
- same quiet one-line provenance;
- same header/options/table/footer dialog structure;
- TraceLab `#1769e0`, `#dfe5ee`, white params cards, 6/7/8/12px radius rhythm;
- no foreign web typography, 40px hard-coded field, detached backing rectangle, clipped badge,
  square popup corner, or modal wider than the application.

If HTML and live app conflict on font metrics or control height, keep the HTML hierarchy but use
the live app's tokens/geometry and record the deliberate translation.

### Step 10.4 — Offscreen gate

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python \
  scripts/db_reference_ui_tour.py --assert --shots /tmp/db-reference-offscreen
```

### Step 10.5 — macOS on-screen gate

```bash
TMPDIR=/tmp PYTHONPATH=. .venv/bin/python \
  scripts/db_reference_ui_tour.py --assert --onscreen --shots /tmp/db-reference-onscreen
```

On-screen inspection is mandatory. Offscreen green alone does not satisfy visual completion.

## Task 10A — Discoverability：hints、quickref、nudge 与 tooltip

**Files**

- Modify: `mf4_analyzer/ui/hints.py`
- Modify: `mf4_analyzer/ui/quickref.py`
- Modify: `mf4_analyzer/ui/inspector_sections/_helpers.py`（现有 dB 参考 tooltip 文案）
- Modify/extend: hints/quickref 的现有测试文件（沿用其当前测试位置）

维护流程遵循项目 `/update-hints` 命令的两个面（footer + 操作速查面板）与门槛
（只覆盖非自明交互，文案 ≤18 全宽）。

### Step 10A.1 — Write failing discoverability tests

```python
def test_db_reference_nudge_gates_on_manual_default_with_resolvable_source(): ...
def test_db_reference_nudge_absent_for_auto_or_non_default_manual(): ...
def test_quickref_covers_db_reference_badge_and_manage_button(): ...
```

### Step 10A.2 — Register hint/nudge and update copy

- 注册 `nudge.db_ref_manual_default`（spec S5 门控条件），predicate 加入现有
  predicates 表，遵守现有优先级与一次性发现语义；
- quickref 目录补 A/M 徽标含义、手输切 Manual、管理按钮三个非自明交互；
- 更新 dB 参考 tooltip：解释 dB re / dBA / Auto/Manual / metadata 优先，
  不再只说“平移 dB 刻度”；
- 不为自明交互（普通输入框编辑）加提示。

### Step 10A.3 — Green discoverability tests

Run the touched hints/quickref test files plus `tests/ui/test_inspector.py`.

## Task 11 — Final Regression、Stale-Identifier Audit And Handoff

### Step 11.1 — Focused full suite

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_db_reference.py \
  tests/ui/test_db_reference_settings.py \
  tests/ui/test_db_reference_controls.py \
  tests/ui/test_inspector.py \
  tests/ui/test_analysis_multiview_integration.py \
  tests/ui/test_pg_line_canvas.py \
  tests/ui/test_pg_heatmap_canvas.py \
  tests/test_head_hdf_loader.py \
  tests/test_db_conversion_convergence.py \
  tests/test_cache_key_dataclass_binding.py \
  tests/test_project_io_analysis_views.py \
  tests/test_batch_runner.py \
  tests/test_batch_preset_io.py \
  tests/ui/test_batch_runner_thread.py -q
```

### Step 11.2 — Literal stale-string audit

```bash
rg -n "Amplitude \(dB\)|dB re|db_reference|db_reference_mode|per-curve reference|dBA" \
  mf4_analyzer tests
```

Manually classify every remaining bare `Amplitude (dB)`:

- target render path → must be removed/replaced;
- intentional default/empty state/backward compatibility test → document why it remains.

Also verify no production code calls `max(reference, 1e-12)` to coerce a validated denominator.

### Step 11.3 — Cache boundary audit

```bash
PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_cache_key_dataclass_binding.py \
  tests/ui/test_order_cache_key_params.py -q
```

Confirm reference/catalog changes record zero compute-worker dispatches; weighting changes still
produce distinct compute identities.

### Step 11.4 — Documentation/path hygiene

```bash
rg -n "docs/(data acquisition|code-reviews|report/|reports/|ui-preview|ui-previews)" docs
git diff --check
git status --short --branch
```

Only task-related source/tests/docs/render-script files may remain changed. Do not delete unrelated
artifacts or update lessons unless a genuinely recurring new failure pattern was discovered.

### Step 11.5 — Completion record

Append to spec/plan only after implementation:

- exact pytest counts/stdout;
- offscreen and macOS screenshot paths;
- actual QSettings schema version;
- any deliberate HTML→Qt translation;
- explicit statement that Artemis official factory provenance remains verified or UNKNOWN;
- any remaining unverified platform/packaging condition.

## Execution Order And Stop Gates

```text
Task 0
  → Task 1 pure contract
  → Task 2 settings
  → Task 3 widgets/dialog
  → Task 4 Inspector/state fields
  → Task 5 source facts/service
  → Task 6 FFT
  → Task 7 heatmaps
  → Task 8 project/preset migration
  → Task 9 Batch
  → Task 10 rendered parity
  → Task 10A discoverability (hints/quickref/nudge/tooltip)
  → Task 11 final regression
```

## Acceptance Coverage Map

| Spec ID | Primary implementation task | Literal proof |
| --- | --- | --- |
| A1 | Tasks 3–4 | shared object names and row-order tests for all three Contextuals |
| A2 | Tasks 3, 4, 10 | 288–320px geometry assertions + 960px rendered state |
| A3 | Tasks 1, 3 | exact round-trip tests for `1e-12`, `1e-9`, `1e-6`, `2e-5` |
| A4 | Tasks 1, 5 | resolver tests and live source switching for Pa/m/s²/m/s/m/N/g |
| A5 | Tasks 1, 2, 5 | metadata priority/preference/invalid-metadata tests |
| A6 | Tasks 2–3 | add/edit/delete/cancel/save/restore/provenance dialog tests |
| A7 | Tasks 4–6 | Manual isolation + zero-worker catalog/source-change tests |
| A8 | Tasks 2, 5–7 | service revision and cache-backed Auto rerender tests |
| A9 | Tasks 1, 6, 7, 9, 10 | literal dBA axis/colorbar/slice/readout/Batch/rendered states |
| A10 | Task 6 | per-source conversion, mixed axis, legend and hover readout tests |
| A11 | Tasks 5, 7, 8 | pane-local source resolution and focused-pane isolation tests |
| A12 | Tasks 4, 8, 9 | schema-1/preset/Batch migration and new-mode round-trip tests |
| A13 | Tasks 5–7, 11 | compute-key audit and worker-dispatch counters |
| A14 | Tasks 7, 9 | rendered copy/image labels and unchanged linear CSV tests |
| A15 | Task 10 | offscreen geometry plus macOS on-screen screenshot checklist |
| A16 | Task 7 | manual color-level shift tests (`test_heatmap_manual_levels_shift_with_reference_delta` 等) |
| A17 | Tasks 1, 10A | generic-vs-fallback resolver/label tests + nudge/quickref/tooltip tests |

Every row above must be marked with actual test names/evidence paths in the implementation
completion record. A task being “done” without its mapped A-ID proof is partial, not complete.

Stop and fix before continuing when any of these occurs:

- scientific input converts a positive supported value to zero;
- Auto uses current navigator selection instead of a pane's saved source;
- a catalog/reference change dispatches a compute worker;
- a legacy value-without-mode opens as Auto and changes the old display;
- mixed FFT uses one source's reference as the global axis;
- dBA appears on Linear output or disappears from A-weighted logarithmic output;
- Batch image and interactive labels diverge;
- a reference change leaves a manual heatmap color window un-shifted (map goes black/blank), or
  the shift is implemented by clipping the matrix;
- a unit merely absent from the catalog (`Nm`, `rpm`, `A`, `deg`, `V`…) renders warning styling
  or `⚠` instead of the neutral `generic` treatment;
- offscreen tests pass but macOS screenshot shows overflow, clipped badge, foreign modal chrome,
  or mismatch with the approved HTML hierarchy.

## Definition Of Executable

This plan is implementation-ready when every referenced existing path/symbol has been rechecked,
Tasks 1–11 retain their literal tests and gates, and no section contradicts the spec's A1–A15
matrix. It does not authorize implementation, commit, push or merge by itself; execution begins
only after the user asks to implement.

## Completion Record (2026-07-12)

Task 11 executed solo against the working tree with Tasks 0–10A (plus the two flagged-gap
follow-ups) already merged and uncommitted.

### Step 11.1 — Focused full suite (foreground, exact per the plan's command)

```
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_db_reference.py tests/ui/test_db_reference_settings.py \
  tests/ui/test_db_reference_controls.py tests/ui/test_inspector.py \
  tests/ui/test_analysis_multiview_integration.py tests/ui/test_pg_line_canvas.py \
  tests/ui/test_pg_heatmap_canvas.py tests/test_head_hdf_loader.py \
  tests/test_db_conversion_convergence.py tests/test_cache_key_dataclass_binding.py \
  tests/test_project_io_analysis_views.py tests/test_batch_runner.py \
  tests/test_batch_preset_io.py tests/ui/test_batch_runner_thread.py \
  tests/ui/test_hint_nudges.py tests/ui/test_quickref.py -q
```

stdout tail:

```
........................................................................ [ 10%]
........................................................................ [ 20%]
........................................................................ [ 30%]
........................................................................ [ 40%]
........................................................................ [ 50%]
........................................................................ [ 60%]
........................................................................ [ 70%]
........................................................................ [ 81%]
........................................................................ [ 91%]
..............................................................           [100%]
710 passed, 32 warnings in 19.10s
```

710 passed (Task 0 baseline on the original 8-file set was 522; the 16-file set — the original 8
plus `test_db_reference.py`, `test_db_reference_settings.py`, `test_db_reference_controls.py`,
`test_head_hdf_loader.py`, `test_batch_runner.py`, `test_batch_runner_thread.py`, and the Task 10A
additions `test_hint_nudges.py`/`test_quickref.py` — was 709 before the Step 11.2 fix below and
710 after, the +1 being the new guard test added in that step). Zero failures, zero errors, only
pre-existing pyqtgraph/NumPy 2.5 `DeprecationWarning`s (unrelated to this feature).

### Step 11.2 — Literal stale-string audit

`rg -n "Amplitude \(dB\)|dB re|db_reference|db_reference_mode|per-curve reference|dBA" mf4_analyzer tests`
→ 900 matches. Every bare `'Amplitude (dB)'` literal was individually classified:

**Fixed (1):** `mf4_analyzer/ui/main_window/_fft_mixin.py` `_do_fft_single` — the back-compat
"no navigator-checked sources" single-signal fallback built its amp axis label with
`'Amplitude (dB)' if amp_y == 'dB' else 'Amplitude'` and converted with the raw
`fft_params.get('db_reference', 1.0)`, bypassing both the per-source resolver
(`_resolve_db_reference_for_source`) and the shared formatter (`db_reference.format_amplitude_label`)
that the checked-source overlay path (`_fft_entry_from_cache` / `_fft_apply_amplitude_display`)
already uses. Under A-weighting this silently dropped the required `dBA` disclosure (spec A9 stop
gate: "dBA appears on Linear output or disappears from A-weighted logarithmic output") — a real,
reachable defect, not a documented default. Fixed by resolving `resolution =
self._resolve_db_reference_for_source('fft', sig_data)` and formatting via
`db_reference.format_amplitude_label(resolution, weighting=weighting, output_scale=...)`, mirroring
the multi-source path exactly. TDD: added
`tests/ui/test_inspector.py::test_fft_single_signal_fallback_amp_label_uses_a_weighted_token`
(RED confirmed against pre-fix code — `assert 'dBA' in amp_ylabel()` failed with
`'Amplitude (dB)'` — then GREEN after the fix); full `-k fft` subset of `test_inspector.py`
(88 tests) and the Step 11.1 16-file suite (710 passed) both stay green. The UI tour
(`scripts/db_reference_ui_tour.py`) always calls `navigator.set_checked_channels(...)` before
`do_fft()`, so none of its 9 rendered states exercise `_do_fft_single` — the existing Task 10
on-screen screenshots remain valid evidence, unaffected by this fix (re-ran the tour offscreen
after the fix: `[tour] all invariants passed`, all `[assert] PASS` lines unchanged).

**Kept — intentional defaults/empty-state/fallback (documented in-code, no target render path
reachable with real render context left unconverted):**
- `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py` (7 sites: `__init__` slice-axis seed line 997,
  `__init__` colorbar seed line 1061, `clear_data` colorbar/empty-state reseed line 1415,
  `_current_amplitude_axis_label` fallback line 1448, and the inline `f"Amplitude{unit} (dB re
  {db_ref:g})"` / bare `f"Amplitude{unit}"` fallback in `plot_result` lines 1765/1772) — every site
  fires ONLY when the caller omits the new `amplitude_label`/`colorbar_label` kwargs (legacy
  direct callers / pre-first-render / post-clear empty state), explicitly documented in each
  docstring/comment as reproducing "the historical … literal so legacy callers … see unchanged
  output".
- `mf4_analyzer/ui/main_window/_order_mixin.py:654` — a comment describing why
  `canvas._amplitude_mode` is pinned (feeds the heatmap canvas's own documented default above), not
  a hard-code.
- `mf4_analyzer/db_reference.py:450` — docstring quoting the forbidden pattern as the rule the code
  now enforces (spec S14).
- Test fixtures/assertions: `tests/ui/test_pg_heatmap_canvas.py` (×3), `tests/ui/test_pg_line_canvas.py`
  (explicit fixture input), `tests/ui/test_chart_stack.py` (×2, default-seed assertions), and
  `tests/test_db_conversion_convergence.py:362`
  (`test_build_export_scene_uses_shared_label_formatter`'s failure-message text documenting the
  anti-pattern it guards against — the test itself asserts `format_amplitude_label` IS used).

Two additional hand-rolled `f"dB re …"` strings surfaced by the broader `dB re` grep were checked
and are correctly out of the S14 rule's scope: `_analysis_mixin.py:46`
(`_format_db_reference_source_line`) implements the compound control's Source Line text, which
spec §10.3 mandates as its OWN literal format (`自动 · 通用默认 · dB re 1 <unit>`), distinct from
the render axis/colorbar contract; `heatmap_canvas.py:1765` is the already-classified `plot_result`
fallback above.

**Denominator-coercion check:** `rg -n "max\(reference|max\(db_reference"` across `mf4_analyzer`
finds only comments documenting the REMOVAL (`db_reference.py:192`, `batch.py:643`,
`ui/widgets/db_reference.py:86`, `_fft_mixin.py:40`) — no live `max(reference, 1e-12)` /
`max(db_reference, 1e-12)` coercion remains. `SpectrogramAnalyzer.amplitude_to_db` raises
`ValueError('db_reference must be > 0')` on a non-positive reference instead of silently
substituting one (`mf4_analyzer/signal/spectrogram.py:157-158`); the Order path's
`_order_label_resolution` explicit test-double fallback (`_order_mixin.py:548-565`) uses
`db_reference.validate_reference` + a documented constant `1.0`, not a `max()` coercion.

### Step 11.3 — Cache boundary audit

```
PYTHONPATH=. .venv/bin/python -m pytest tests/test_cache_key_dataclass_binding.py \
  tests/ui/test_order_cache_key_params.py -q
→ 11 passed in 0.38s
```

Zero-worker-dispatch proof: `test_no_display_param_on_compute_dataclasses` (db_reference/mode/
z_*/cmap are absent from `SpectrogramParams`/`COTParams`) and
`test_db_reference_mode_and_catalog_revision_stay_out_of_compute_cache_key` (black-box: feeding
`db_reference`/`db_reference_mode`/`db_reference_revision`/`catalog_revision` into
`FFTMixin._fft_compute_cache_params` proves none leak into its output dict) — together these mean
a reference/catalog change can never produce a different compute cache key, hence zero worker
dispatch. Weighting-still-changes-identity proof: `test_spectrogram_params_every_field_is_consumed_by_compute`
(asserts `params.weighting` is read by `SpectrogramAnalyzer.compute`, and `weighting` is a
`SpectrogramParams`/cache-key field) plus `test_cot_consumption_map_partitions_every_field` +
`test_cot_consumed_fields_are_actually_read_by_compute` (same proof for `COTParams`/Order); the
plain-FFT path's `_fft_compute_cache_params` (`_fft_mixin.py`) includes `'weighting'` in its keyed
output alongside `window`/`nfft`/`fs`/`avg_mode`/`avg_overlap`. So all three sections (fft,
fft_time, order) key on weighting but never on reference/mode/catalog revision.

### Step 11.4 — Documentation/path hygiene

`rg -n "docs/(data acquisition|code-reviews|report/|reports/|ui-preview|ui-previews)" docs` →
zero hits inside any 2026-07-12 (task-related) doc (spec, plan, HTML draft, lessons). No
wrong-path references to flag.

`git diff --check` → clean (exit 0, no whitespace/conflict-marker issues).

`git status --short --branch` → every `M`/`??` entry belongs to this feature (the pure
`db_reference` module + tests, the settings/dialog/widgets, the Inspector contextuals, the FFT/
Order/FFT-time mixins + `window.py`, the pg_canvas line/heatmap canvases, hints/quickref, the QSS,
the UI tour script, the spec/plan/HTML docs, and this task's own lessons files). No unrelated
modified files were present at Step 11.4 time — `findings.md`/`progress.md`/`task_plan.md` (flagged
by the task brief as pre-existing modifications to leave alone) had already been committed by a
concurrent process before this step ran (`git diff --stat -- findings.md progress.md task_plan.md`
was empty; `git log -1` for those paths resolves to `7e2400e7`), so there was nothing to leave
alone or revert — nothing was touched either way.

### QSettings and AnalysisViewState schema (verified against source, not assumed)

- `mf4_analyzer/ui/db_reference_settings.py`: `KEY_CATALOG_V1 = "analysis/db_reference/catalog_v1"`,
  `CATALOG_SCHEMA_VERSION = 1`; `hidden_builtin_ids` is a field INSIDE the `catalog_v1` JSON delta,
  not a separate QSettings key; `KEY_PREFER_CHANNEL_METADATA =
  "analysis/db_reference/prefer_channel_metadata"` is the other top-level key.
- `mf4_analyzer/ui/analysis_view_state.py`: nested `_SCHEMA = 2` (bumped from 1 by Task 8, spec
  §13 S3) — the bump is declarative only; `from_dict()` migrates off "params has `db_reference`
  and no `db_reference_mode`", not off the schema number, so an older build reading a schema-2
  project still applies the saved value Manual-style instead of erroring/dropping it.

### Offscreen + macOS on-screen screenshot evidence (Task 10, re-verified intact)

- Offscreen: `/tmp/db-reference-offscreen/` — 9 PNGs (01-fft-auto-system-acceleration.png through
  09-narrow-app-inspector.png).
- macOS on-screen: `/tmp/db-reference-onscreen/` — same 9 filenames, larger (real-DPI) captures.
- Re-ran `scripts/db_reference_ui_tour.py --assert --shots <scratch dir>` offscreen AFTER the Step
  11.2 fix: `[tour] all invariants passed`, every `[assert] PASS` line unchanged from Task 10,
  including `state9: Inspector stays within 288-320px at app width=1100 (inspector=288)` — the
  960px-resize target floors at `MainWindow.setMinimumSize(1100, 640)`
  (`mf4_analyzer/ui/main_window/window.py:73`), a pre-existing red line not touched by this task;
  the achieved narrow width is 1100px, not the literal 960px, and the tour records this as an
  explicit deliberate note rather than a failure.
- Order state 6 (`06-order-db-colorbar-slice.png`) renders as a uniformly dark-red/maroon heatmap
  (every cell pinned near the colorbar ceiling, `-10 dB re 1×10⁻⁶ N`) — visually confirmed by
  re-viewing the on-screen PNG. This is a synthetic-data artifact of the tour's fixture (a
  near-constant-amplitude force signal across the whole time/order grid at the chosen `1e-6`
  manual reference), not a color-window regression: the app's own footer copy
  ("画面发黑? 双击 colorbar 重置色阶") already covers this generically, and none of the
  reference-delta-shift assertions (state6 `[assert] PASS` lines) are affected.

### Artemis official factory provenance

Per spec §22: Artemis' own official defaults page/customer manual table for dB reference values
remains **UNKNOWN** and unverified. This does not block completion because (1) legal in-file HEAD
metadata always outranks the built-in catalog, (2) the built-ins are honestly named compatibility
defaults (ISO/HEAD-compatible), not a claim of vendor authority, (3) the catalog is user-editable/
restorable, and (4) the resolver/persistence never depend on a vendor name. No release note,
tooltip, or help page in this feature claims "Artemis official defaults" — this must remain true
for any future change to this area too.

### Known limitations

- **Split-pane unfocused footer nudge:** `_stamp_db_reference_nudge_facts` (`_analysis_mixin.py:719`)
  writes `db_reference_nudge_facts` only onto "the section's focused-pane canvas" (its own
  docstring, line 726) — a non-focused pane in a split view never gets this fact refreshed, so its
  footer nudge state can only reflect what was true the last time that pane was itself focused,
  not live source/catalog changes made while a sibling pane has focus. This mirrors the existing
  Manual-View-is-per-View (not per-pane) design and was not in scope to change.
- **`_do_fft_single` classification (Step 11.2):** now FIXED (routed through
  `_resolve_db_reference_for_source` + `db_reference.format_amplitude_label`, guarded by the new
  `test_fft_single_signal_fallback_amp_label_uses_a_weighted_token` test) rather than left as an
  open item — recorded here per the task brief's requirement to report the classification result.
