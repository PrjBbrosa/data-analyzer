# Decomposition — batch-blocks-redesign Wave 5

**Date:** 2026-04-27
**Top-level request:** Execute Wave 5 of the batch-blocks-redesign plan
— author the five new detail-panel widget modules
(`signal_picker.py`, `method_buttons.py`, `input_panel.py`,
`analysis_panel.py`, `output_panel.py`) under
`mf4_analyzer/ui/drawers/batch/`, replace the W4 placeholder body of
`sheet.py` with a real wired BatchSheet that exposes the full
accessor/mutator surface listed in plan §Wave 5 (method /
selected_signals / rpm_channel / time_range / file_ids / file_paths /
params / output_dir / export_data / export_image / data_format /
signals_marked_unavailable + apply_*), implement
`is_runnable()` and `_recompute_pipeline_status()`, and add three new
test files (`test_batch_signal_picker.py`,
`test_batch_method_buttons.py`, `test_batch_input_panel.py`).

**Mode:** plan
**Plan file:** `docs/superpowers/plans/2026-04-27-batch-blocks-redesign.md`
(§Wave 5, lines 1445–1801)
**Spec file:** `docs/superpowers/specs/2026-04-26-batch-blocks-redesign-design.md`
(§3.1 整体布局, §3.2 INPUT, §3.3 ANALYSIS, §3.4 OUTPUT)

## Routing rationale

Wave 5 is purely PyQt5 widget authoring + signal/slot wiring + Qt event
plumbing (popup focus-out, ESC, QThreadPool probe, dynamic QFormLayout
re-render). There is no numerical pipeline change (W1+W2 closed),
no preset IO (W3 closed), no package relocation/import-graph rewire
(W4 closed). Per the specialist roster, every keyword in the request
(`PyQt`, `widget`, `dialog`, `signal/slot`, `chips`, `popup`,
`QListWidget`, `QFormLayout`, `QThreadPool`, `state machine`,
`pipeline strip status`, `font`, `label`) maps unambiguously to
`pyqt-ui-engineer`. `signal-processing-expert` is not appropriate
because the only `MDF`/`channels_db` touch is a metadata-only probe
that returns to the UI thread (no analysis, no resampling, no FFT);
`refactor-architect` is not appropriate because the work creates new
files in an existing package, with no relocations/renames of existing
modules.

The plan supplies near-verbatim test source for steps 1, 3, 5 (and
two additional regression tests in step 5: `is_runnable()` gating and
pipeline-strip recompute on input change). The widget bodies are
specified by reference to spec §3.2/§3.3/§3.4 with no verbatim source
— specialist authors them. This is appropriate work for a UI engineer.

Folding the five new widget modules + sheet.py rewire + three test
files into one specialist envelope mirrors W1/W2/W3/W4's
single-envelope shape (Codex-approved each time) and avoids the
move-then-tighten cross-specialist rework pattern documented in
`orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`.
Splitting "create panel widgets" from "wire them into sheet.py" across
two specialists would also race the same `sheet.py` shared-file
concern from
`orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`.

The brief enumerates a forbidden-files list per
`orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
and requires the specialist to return `symbols_touched` plus a
`forbidden_symbols_check` self-attestation. It also explicitly cites
`signal-processing/2026-04-27-plan-verbatim-source-must-reconcile-with-recent-removals.md`
as the trigger for the THREE-not-FOUR method buttons reconciliation.

## Plan-vs-reality reconciliations forced into the brief

1. **MethodButtonGroup must expose exactly 3 buttons, not 4.**
   `cfb301b refactor(batch): drop order_rpm method` removed the entire
   `order_rpm` chain from `_run_one`, and `BatchRunner.SUPPORTED_METHODS`
   is now `{'fft', 'order_time', 'order_track'}` (verified live at
   `mf4_analyzer/batch.py:157`). `tests/test_batch_runner.py:433-440`
   pins this as a regression invariant
   (`test_supported_methods_excludes_removed_order_rpm`). Plan §Wave 5
   line 1470 lists 4 methods (plan-write snapshot predates the removal);
   spec §3.3 method-vs-field table also has an `order_rpm` column. The
   brief requires the specialist to verify
   `BatchRunner.SUPPORTED_METHODS` first, expose only those three
   methods in `MethodButtonGroup`, and IGNORE the `order_rpm` row of
   the spec §3.3 table when implementing `DynamicParamForm`. This is
   the second application of the
   `plan-verbatim-source-must-reconcile-with-recent-removals` lesson.

2. **Plan §Step 7 OutputPanel git reference is stale.** Plan says
   `git show HEAD~5:mf4_analyzer/ui/drawers/batch_sheet.py` — but
   batch_sheet.py was deleted in commit `ad28d29` (W4), and HEAD has
   advanced since plan-write so HEAD~5 no longer points to a commit
   where that file exists. The brief gives the correct recipe:
   `git show ad28d29~1:mf4_analyzer/ui/drawers/batch_sheet.py`
   (verified — that path returns the pre-W4 single-file UI with the
   output group at lines ~50-69 the plan references).

3. **Investigate `tests/ui/test_inspector.py::test_fft_contextual_fields_fill_column_under_qss` (line 916).**
   W4 specialist flagged this as a pre-existing assertion failure
   unrelated to W4. The user delegated investigation to W5. The
   specialist gets explicit latitude: triage in <10 min and fix if
   trivially attributable to a recent QSS / Inspector layout change
   un-related to batch UI; otherwise capture root-cause hypothesis +
   reproduction in the return JSON's `flagged` and `notes` for
   W6/W8 follow-up. The brief is explicit that this MUST NOT block
   W5's main deliverables.

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| W5: Author five new panel widgets under `mf4_analyzer/ui/drawers/batch/` (`signal_picker.py` — `SignalPickerPopup` chips display + `QPushButton` trigger + floating `QFrame` popup with `QLineEdit` search + `QListWidget` of `QCheckBox` items, `partially_available` items have `Qt.ItemIsEnabled` cleared and a "(N/M)" hint, `selectionChanged(tuple[str,...])` signal, `set_selected`/`set_available`/`set_partially_available`/`show_popup`/`hide_popup`/`is_popup_visible`/`visible_items`/`is_disabled`/`label_for`/`set_search_text` API, ESC + focus-out-on-popup hides popup; `method_buttons.py` — `MethodButtonGroup` exposing exactly **3** toggle buttons (`fft`, `order_time`, `order_track`; verified against `BatchRunner.SUPPORTED_METHODS`) emitting `methodChanged(str)` plus `set_method`/`current_method` accessors, AND `DynamicParamForm` (lives in same file) re-rendering a QFormLayout per spec §3.3 minus the `order_rpm` column — fields: window/nfft for all three; max_order/order_res/time_res/rpm_factor for `order_time`; max_order/target_order/rpm_factor for `order_track` — plus `set_method`, `get_params() -> dict`, `apply_params`, `visible_field_names() -> set[str]`; `input_panel.py` — `FileListWidget` (state machine row states `loaded`/`path_pending`/`probing`/`probe_failed`; "+ 已加载" sub-menu and "+ 磁盘…" QFileDialog buttons; `_probe_signals_for(path)` hook overridable in tests, default uses QThreadPool worker that opens `MDF(path).channels_db.keys()` then closes; signals `filesChanged()`, `intersectionChanged(frozenset[str])`, `stateChanged(str path, str state)`; methods `add_loaded_file(fid, path, channels)`, `add_disk_path(path)`, `remove_path(path)`, `_set_row_state(path, state)`, `row_state(path)`, `loaded_file_ids() -> tuple`, `loaded_disk_paths() -> tuple[str,...]`, `current_intersection() -> frozenset[str]`) AND `InputPanel(QWidget)` aggregating `_file_list: FileListWidget`, `_signal_picker: SignalPickerPopup`, RPM channel `QComboBox`, time-range `QLineEdit` (parses "a,b" or empty), with `changed` signal fanning out from all four sub-controls plus method-aware accessors `selected_signals`, `rpm_channel`, `time_range`, `apply_*` mutators; `analysis_panel.py` — `AnalysisPanel(QWidget)` composing `MethodButtonGroup` + `DynamicParamForm`, `methodChanged` re-emit, `paramsChanged` re-emit (debounced via the form), `set_method`, `current_method`, `get_params`, `apply_method`, `apply_params`; `output_panel.py` — `OutputPanel(QWidget)` mirroring pre-W4 batch_sheet output group (recoverable via `git show ad28d29~1:mf4_analyzer/ui/drawers/batch_sheet.py` lines 50-69 — directory `QLineEdit` + "选择…" `QPushButton` opening `QFileDialog.getExistingDirectory`, default `~/Desktop/mf4_batch_output`; `chk_data` / `chk_image` checkboxes; format `QComboBox` with `csv`/`xlsx`), with `changed` signal, `directory()`/`export_data()`/`export_image()`/`data_format()` accessors, `apply_outputs(BatchOutput)` and `apply_directory(str)`); replace `mf4_analyzer/ui/drawers/batch/sheet.py` placeholder body with a fully wired `BatchSheet` exposing the EXACT public surface listed in plan §Wave 5 lines 1494-1522 (`method`, `selected_signals`, `rpm_channel`, `time_range`, `file_ids`, `file_paths`, `params`, `output_dir`, `export_data`, `export_image`, `data_format`, `signals_marked_unavailable`, plus `apply_method`, `apply_signals`, `apply_rpm_channel`, `apply_time_range`, `apply_params`, `apply_outputs`, `apply_files`, `apply_preset`); `BatchSheet.is_runnable() -> bool` true iff (no row in `path_pending` or `probing`) AND (≥1 file in `loaded`) AND (≥1 selected signal) AND (method set) AND (output_dir set); `BatchSheet._recompute_pipeline_status()` subscribes to `_input_panel.changed`, `_input_panel._file_list.filesChanged`, `_input_panel._file_list.intersectionChanged`, `_input_panel._signal_picker.selectionChanged`, `_analysis_panel.methodChanged`, `_analysis_panel.paramsChanged`, `_output_panel.changed`, and updates `self.strip.set_stage(0/1/2, status, summary)` with INPUT status `ok` only when ≥1 loaded file AND ≥1 selected signal AND no `path_pending`/`probing`/`probe_failed`, ANALYSIS status `ok` when method chosen AND no missing required params, OUTPUT status `ok` when directory set AND at least one of `export_data`/`export_image` checked; `BatchSheet.get_preset()` returns `dataclasses.replace(AnalysisPreset.free_config(name=<sheet_name_or_'batch'>, method=self.method(), target_signals=self.selected_signals(), rpm_channel=self.rpm_channel(), params=self.params(), outputs=BatchOutput(directory=self.output_dir(), export_data=self.export_data(), export_image=self.export_image(), data_format=self.data_format())), file_ids=self.file_ids(), file_paths=self.file_paths())`; `BatchSheet.signals_marked_unavailable()` returns `tuple(s for s in self.selected_signals() if s not in self._input_panel._file_list.current_intersection())`; preserve W4 toolbar (3 disabled buttons), PipelineStrip + 1080×760 size + Cancel/运行 footer; preserve `BatchSheet(parent, files, current_preset=None)` constructor signature; ALL 4-dot relative imports (`from ....batch import AnalysisPreset, BatchOutput`); add three new test files at the paths in the plan with the test bodies verbatim from plan lines 1530-1741, and ensure internal access expressions `sheet._input_panel._file_list`, `sheet._input_panel._signal_picker`, `sheet._analysis_panel`, `sheet._output_panel` resolve to those exact attributes; investigate `tests/ui/test_inspector.py::test_fft_contextual_fields_fill_column_under_qss` (in <10 min) and either fix or document root cause in return JSON | `pyqt-ui-engineer` | (none — W4 already merged + Codex-approved; W5 stands alone) | Pure PyQt5 widget authoring + signal/slot wiring + popup focus-out + state-machine UI + dynamic-form re-render. No numerical pipeline. Single-specialist envelope same shape as W1-W4. Plan supplies verbatim test source; widget bodies are spec-driven not plan-verbatim, which is exactly the surface a UI engineer owns. Forbidden-files + symbols_touched + forbidden_symbols_check self-attestation per silent-boundary-leak lesson. Three explicit plan-vs-reality reconciliations baked into the brief (3 methods not 4; correct git reference for OutputPanel; inspector test triage). |

## Lessons consulted

- `docs/lessons-learned/README.md` — reflection protocol.
- `docs/lessons-learned/LESSONS.md` — master index.
- `docs/lessons-learned/.state.yml` — cadence (17 / 0; no prune due, threshold ≥20).
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md` — supports keeping all five new widget modules + sheet.py rewire + tests in one specialist envelope.
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md` — drives the explicit forbidden-files list and the `symbols_touched`/`forbidden_symbols_check` reporting requirements embedded in the brief.
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md` — confirms NOT to fan W5 out across multiple parallel specialists (sheet.py is the shared write target).
- `docs/lessons-learned/signal-processing/2026-04-27-plan-verbatim-source-must-reconcile-with-recent-removals.md` — applied a second time to W5 specifically: 3-not-4 method buttons; ignore `order_rpm` row of spec §3.3.
- `docs/lessons-learned/pyqt-ui/2026-04-26-popover-accept-deactivate-race.md` — direct guidance for `SignalPickerPopup` (popup-style frameless QFrame; ESC + focus-out close path; offscreen-test gotcha around `WindowDeactivate` not synthesised under qtbot — for SignalPicker we use `_popup.clearFocus()` per the plan-verbatim test, but the lesson's `_is_closing` guard idiom should still apply if popup ever auto-rejects).
- `docs/lessons-learned/pyqt-ui/2026-04-25-qthread-wait-deadlocks-queued-quit.md` — relevant guard for the QThreadPool probe path: tests inject `_probe_signals_for` to make the call synchronous so we never hit a `wait()` deadlock; production async path uses `QRunnable` (no `wait()`).
- `docs/lessons-learned/pyqt-ui/2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md` — directly applicable to `DynamicParamForm`: every per-method field swap must seed initial state once at the end of `set_method` (don't rely on a downstream signal to hide rows for the first method shown).
- `docs/lessons-learned/orchestrator/decompositions/2026-04-27-batch-blocks-wave4.md` — confirms W4 envelope shape; W5 mirrors it with 9 files instead of 5.

## Notes

- Windows pytest invocation: `.venv\Scripts\python.exe -m pytest tests/ui/test_batch_signal_picker.py tests/ui/test_batch_method_buttons.py tests/ui/test_batch_input_panel.py tests/ui/test_batch_smoke.py -v --basetemp=.pytest-tmp -p no:cacheprovider`. Fall back to `py -3 -m pytest ...` only if `.venv` is missing (W4 specialist confirmed system py.exe PyQt5 is broken).
- The plan's Step 10 `git commit` block is rewritten in the brief to "do NOT commit yet — main Claude commits after Phase 3 aggregation" per the executor split.
- The plan's Wave 5 acceptance bullet 2 (manual smoke: open the dialog, add a real `.mf4`, see probe complete + signals appear) is rewritten in the brief to "main Claude is responsible for any manual GUI smoke; specialist does NOT need to launch the app".
- Forbidden-files list embedded in the brief: `mf4_analyzer/batch.py` (W1+W2), `mf4_analyzer/batch_preset_io.py` (W3), `tests/test_batch_runner.py`, `tests/test_batch_preset_dataclass.py`, `tests/test_batch_preset_io.py`, `mf4_analyzer/ui/drawers/batch/__init__.py` (W4 — already correctly re-exports `BatchSheet`), `mf4_analyzer/ui/drawers/batch/pipeline_strip.py` (W4 — only touch if a clearly broken behaviour blocks W5; otherwise hands-off), `tests/ui/test_batch_smoke.py` (W4); plus the W6/W7 territory: `task_list.py`, `runner_thread.py`, `toolbar.py` (none exist yet — must NOT create).
- 4-dot relative-import callout: new modules live at `mf4_analyzer/ui/drawers/batch/<module>.py` (4 levels below package root). `from ....batch import AnalysisPreset, BatchOutput` — same depth as W4's `sheet.py`. A wrong dot count surfaces immediately as `ImportError` at test import.
- No `superpowers:brainstorming` invocation — request is unambiguous (plan supplies test source verbatim; widget bodies have spec-level direction; user already triaged plan-vs-reality drift in the prompt).
- No `superpowers:writing-plans` invocation — only one specialist dispatch (the dispatch >3 threshold is about specialist count, not subtask scope; W5's 9-file scope is plan-driven and no further plan artefact would help).
- `superpowers:using-superpowers` honored at orchestrator startup as required.
