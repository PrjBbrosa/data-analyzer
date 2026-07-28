# Decomposition — Batch three-phase optimization

Top-level request: write spec/plan for three phases, then dispatch specialists.

Execution result（2026-07-28）：三阶段均已按依赖链实施。Phase 1 C1–C10 PASS；Phase 2 P1–P10 PASS；Phase 3 O1–O8、O10 PASS，O9 PARTIAL（硬杀进程后的 stale reservation 采用显式安全运维，不做可能误伤其他 owner 的自动回收）。

Current boundary summary: Batch is already a four-method pipeline (`time`, `fft`,
`fft_time`, `order_time`) with per-target dB resolution and focused tests, but the
live path still has three cross-cutting seams: `AnalysisPreset.params` is rebuilt by
several UI owners, disk loading/probing has two format dispatchers, and image export
creates Qt objects inside `BatchRunnerThread`. The implementation must therefore be
serial by integration seam, not one parallel agent per phase.

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| P1-R — Qt-free PNG renderer module with the current payload contract and compatibility tests | pyqt-ui-engineer | approved Phase-1 spec | Plot/image surface and thread-affinity behavior belong to the PyQt/rendering specialist. Own only new `mf4_analyzer/batch_render.py` and `tests/test_batch_renderer.py`; do not edit `batch.py` or batch drawer files. |
| P1-C — canonical recipe validation, output identity/atomic writes, renderer integration, and core tests | signal-processing-expert | P1-R | `batch.py` is the single compute/output integration point. Own `mf4_analyzer/batch.py`, optional pure `batch_validation.py`/`batch_output_identity.py`, `batch_preset_io.py`, and non-UI batch tests for this phase. TDD-first; preserve linear data-export semantics and lazy one-file cache. |
| P1-U — lossless current-analysis → sheet → preset round-trip and removal of stale dual-source capture | pyqt-ui-engineer | P1-C recipe-key contract | All affected surfaces are UI state/call-site wiring. Own `ui/drawers/batch/{sheet,method_buttons,input_panel,output_panel}.py`, `ui/main_window/{window,_fft_mixin,_order_mixin}.py`, and matching UI tests; do not edit `batch.py`. |
| P2-A — unified source adapter and metadata probe for every supported disk format, including multi-group identity | signal-processing-expert | Phase-1 complete | Loader/FileData semantics and group identity are data-domain logic. Own new `mf4_analyzer/io/batch_source_adapter.py` and focused adapter tests only; no UI edits and no `batch.py` integration yet. |
| P2-C — integrate source adapter, target policy, shared preset definitions, and time preprocessing into BatchRunner | signal-processing-expert | P2-A | Task expansion, resampling/decimation/filter order, Auto-NFFT and per-file availability are numerical contracts. Own `batch.py`, new pure preset/preprocess modules, and non-UI batch tests; do not edit drawer files. |
| P2-U — supported-format picker/probe, built-in/custom presets, dB Auto/Manual/effective preview, time settings, and common-vs-available selection UI | pyqt-ui-engineer | P2-C public contract | These are PyQt controls and signal/slot surfaces. Bundle all drawer edits under one owner because `sheet.py`, `input_panel.py`, `method_buttons.py`, `signal_picker.py`, and `output_panel.py` are shared integration files. |
| P3-R — exact-size raster plus SVG/PDF renderer, titles/labels/legend, and visual artifact tests | pyqt-ui-engineer | Phase-2 complete | Rendering formats and chart surface fidelity belong to the UI/rendering specialist. Own `batch_render.py` and renderer tests only; keep worker-safe, Qt-free execution. |
| P3-C — output schema, manifest, collision policies, resume/retry, checksums, and atomic integration | signal-processing-expert | P3-R | Persistence, deterministic identity, manifest schema, and resume state are algorithmic/persistence work. Own `batch.py`, `batch_preset_io.py`, optional pure manifest module, and non-UI batch tests. |
| P3-U — output-size/format/conflict controls and failed-task retry/resume UI | pyqt-ui-engineer | P3-C | Output controls and task-list lifecycle are UI surfaces. Own `output_panel.py`, `sheet.py`, `task_list.py`, `runner_thread.py`, and their UI tests; do not edit core modules. |

## Dependency and execution rule

- Strict chain: `P1-R → P1-C → P1-U → P2-A → P2-C → P2-U → P3-R → P3-C → P3-U`.
- In the shared checkout, file-mutating specialists must be serialized. Read-only
  reviewers can run in parallel. Parallel mutation is acceptable only with isolated
  worktrees and explicit pathspec staging.
- Within a phase, the renderer and UI tasks have disjoint write sets, but both consume
  a contract produced by the core task. Do not start them on guessed field names.
- A plan file's file list is a write boundary, not proof of live reachability. If a
  live call site lies outside the list, the specialist must flag it; the dispatcher
  assigns it explicitly rather than allowing scope creep.

## Minimum acceptance by phase

### Phase 1 — correctness and reproducibility

- For each method, a full current-context parameter blob survives
  `current preset → BatchSheet.apply_preset → get_preset`, including Auto NFFT,
  `t_win_s`, averaging, amplitude mode, `db_reference_mode/value`, manual RPM and
  `samples_per_rev`; legacy value-without-mode still migrates to Manual.
- `open_batch()` uses one canonical live capture, not a stale `_last_batch_preset`
  with a smaller parameter subset.
- Invalid time/axis ranges, non-positive/non-finite Fs, invalid NFFT/window, Nyquist
  violations, and impossible output configuration fail deterministically before
  compute or write.
- Output identity includes source/group/channel/method plus deterministic disambiguation;
  writes are temp-file + replace and never silently overwrite under the default policy.
- Image-only execution inside `BatchRunnerThread` creates no `QApplication`, QWidget,
  QPixmap, or other GUI-affine Qt object. Existing direct helper call sites remain
  backward compatible or receive explicit compatibility shims.

### Phase 2 — source and analysis parity

- Batch picker/probe/runner share one extension registry covering MF4/MDF, BLF,
  TDMS, CSV/FDC/ASC, XLS/XLSX, HDF, WWT, ZFD, MAT, and supported audio/video.
  Multi-group files produce stable distinct source identities; identical physical MDF
  occurrences are deduplicated without collapsing real groups.
- Built-in `频率 / 均衡 / 时间` and user `自定义` recipes use the same pure definitions
  as single analysis; no copy-pasted numeric tables in the drawer.
- FFT, FFT-time, and Order expose dB reference Auto/Manual and show the effective
  per-target value/source before run. Display-only reference never enters compute keys
  or changes linear CSV/XLSX values.
- Time preprocessing has an explicit order and tests: range → finite cleanup →
  scale/offset → mean removal → resample/decimate → filter → analysis. Actual Fs and
  any filter clamp are retained as facts.
- Target policy is explicit: strict intersection or available-per-file. Missing
  channels are skipped/recorded under the latter, not emitted as avoidable failures.

### Phase 3 — export quality and operations

- PNG presets produce exact 1920×1080, 2560×1440, and 3840×2160 pixels; custom
  width/height is bounded and tested. DPI metadata is not used as a substitute for
  pixel dimensions.
- SVG and PDF are valid non-empty vector artifacts; labels/titles include source,
  group, channel, unit, method, weighting, and dB reference where applicable.
- A versioned UTF-8 manifest records requested/effective params, source identity,
  actual Fs/NFFT, filter clamp messages, output paths, status/errors, and checksums.
- Conflict policy (`error`, `skip`, `overwrite`, `auto-number`) is deterministic.
  Resume skips only manifest-proven completed artifacts; retry-failed schedules only
  failed/cancelled items. Interrupted writes leave no final-looking partial files.

## High-risk points

- Multi-group HDF/WWT/ZFD/MAT cannot be represented truthfully by a path-only row key;
  source identity must be designed before expanding the file dialog filter.
- Disk BLF has UI-dependent DBC selection/recent mapping; "format supported" must not
  silently mean undecoded raw frames. The Phase-2 spec must state its DBC policy.
- `batch.py` currently mixes compute, persistence, and pyqtgraph scene construction.
  Replacing the renderer can break direct static-helper tests and visual labels; keep
  compatibility shims until all call sites are grepped.
- The current image path is fixed at 1120×630, and heatmap single-frame extents can
  collapse to zero width. Phase 1 fixes zero-span correctness; Phase 3 changes quality.
- Cancellation is currently observed between tasks, not necessarily inside long FFT,
  spectrogram, load, or export calls. Do not claim immediate cancellation without
  propagating and testing checkpoints in those operations.
- Existing `open_batch()` has a dead post-`exec_()==Accepted` run path while the live
  run is in `BatchSheet._on_run_clicked`; every catalog/output schema pass-through must
  be verified on the live path.

## Lessons consulted

- `docs/lessons-learned/orchestrator/2026-06-11-parallel-mutators-share-git-index-even-disjoint-files.md`
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
- `docs/lessons-learned/orchestrator/2026-07-12-plan-mapped-decomposition-misses-live-call-sites.md`
- `docs/lessons-learned/orchestrator/2026-05-15-non-dsp-algorithmic-python-routes-to-signal-processing-expert.md`
- `docs/lessons-learned/orchestrator/2026-04-28-return-type-change-needs-paired-callsite-update.md`
