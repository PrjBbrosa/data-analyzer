# Decomposition — Batch UI fixes + FFT-vs-Time integration

**Date:** 2026-04-27
**Plan:** `docs/superpowers/plans/2026-04-27-batch-ui-fixes-and-fft-vs-time.md` (rev 2, approved with minor revisions; cosmetic minors already inlined)
**Mode:** plan (wave-aware decomposition; main Claude dispatches one wave at a time and gates on codex/code-reviewer fallback approval before advancing)

## Wave structure

User-supplied wave map (from rev 2 review section "squad wave 建议") is
authoritative. Within each wave, tasks remain in the order given by the
plan's Phase numbering; main Claude must run them sequentially because
later tasks in the same phase write tests that depend on earlier-task
implementation symbols (e.g., Step 5.4b round-trip test needs the
spinbox + apply_rpm_factor that Step 4.3 / 5.4 introduced).

## Subtask table

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| W1 — Phase 1 + 2: signal_picker.py chip refactor + single_select | pyqt-ui-engineer | — | Pure PyQt surface change in `signal_picker.py` only; chip layout, ClickableFrame, single_select keyword. No backend touch. UI keyword (chip/picker/popup) → pyqt-ui per roster. |
| W2 — Phase 3 + 4: input_panel.py RPM picker + factor + visibility wiring + sheet.py methodChanged hookup | pyqt-ui-engineer | W1 (uses new `single_select` kw) | UI form composition (QDoubleSpinBox + QComboBox + form-row visibility via takeRow/insertRow). Needs `single_select` API from W1. Two files (`input_panel.py`, `sheet.py`) in one specialist brief — same expert, same wave: no cross-specialist rework risk; serializing within one brief avoids same-file commit-collision lesson. |
| W3a — Phase 5: batch.py SUPPORTED_METHODS + fft_time dispatch + dataframe + image (incl. 64MB ceiling per-item failure) | signal-processing-expert | W2 (UI must already accept fft_time as a method choice in BatchSheet — sheet wires methodChanged into input_panel.set_method which now treats fft_time as RPM-free) | Backend method dispatch + spectrogram analyzer wiring + long-format dataframe + dB image render. Computation keywords (FFT, spectrogram, amplitude, dataframe) → signal-processing-expert per roster. Solo specialist for `batch.py`; no rework risk against W3b. |
| W3b — Phase 6: method_buttons.py fft_time button + overlap/remove_mean widgets + sheet.py _METHOD_LABELS entry | pyqt-ui-engineer | W3a (UI button only makes sense once backend accepts the method, otherwise smoke-clicks would send users to a `else: raise` path) | UI surface change (button, QCheckBox, QDoubleSpinBox, label dict). NOTE: sheet.py also touched in W2. Same specialist, same file across waves is allowed per design — but the brief MUST enumerate forbidden symbols from W2 (`set_method` wiring, `apply_preset` rpm_factor injection) so the cross-wave overlap stays at the symbol level even though it appears at the file level. Cite `refactor-then-ui-same-file-boundary-disjoint` lesson. |
| W4 — Phase 7: end-to-end smoke combining all three fixes | pyqt-ui-engineer | W1, W2, W3a, W3b | Single tests/ui file append exercising the integrated dialog. Pure test-only file; no production code touched. UI keyword (smoke, dialog, BatchSheet) → pyqt-ui. |

## Cross-wave file overlap (intentional, audited)

| File | Wave touches | Specialists | Rework class |
|---|---|---|---|
| `mf4_analyzer/ui/drawers/batch/signal_picker.py` | W1 only | pyqt-ui | none |
| `mf4_analyzer/ui/drawers/batch/input_panel.py` | W2 only | pyqt-ui | none |
| `mf4_analyzer/ui/drawers/batch/sheet.py` | W2, W3b | pyqt-ui both waves | **disjoint-symbol overlap** — W2 owns `methodChanged → input_panel.set_method` wire + `get_preset` rpm_factor injection + `apply_preset` rpm_factor restore; W3b owns `_METHOD_LABELS` dict only. Forbidden-symbol list in W3b brief: must NOT touch `methodChanged`, `get_preset`, `apply_preset`, `_input_panel.set_method`. Per `refactor-then-ui-same-file-boundary-disjoint` this is OK as long as the brief enumerates forbidden methods. |
| `mf4_analyzer/ui/drawers/batch/method_buttons.py` | W2 (drop `rpm_factor` from `_METHOD_FIELDS`) and W3b (add fft_time to `_METHODS` / `_METHOD_FIELDS` + new widgets) | pyqt-ui both waves | **same-expert, sequential, same dict** — `_METHOD_FIELDS` is touched by both. Cite `parallel-same-file-drawer-task-collision` only as a non-issue here (sequential, gated on codex approval between waves; no parallel git-add race). |
| `mf4_analyzer/batch.py` | W3a only | signal-processing | none |

No cross-wave specialist swap on the SAME symbol. The disjoint-symbol overlap is the dominant pattern; mitigation is verbal forbidden-symbol enumeration in the brief, not waving rework detection off.

## Wave gating (mandatory, per user instructions)

Between every consecutive wave pair (W1 → W2, W2 → W3a, W3a → W3b, W3b → W4) main Claude MUST:

1. Collect specialist return JSON with full required fields (`ui_verified`, `tests_run`, `tests_before`, `tests_after`, `files_changed`, `lessons_added`).
2. Run codex review (`codex` CLI) of the wave's diff. If codex unavailable, fall back to `superpowers:code-reviewer` agent.
3. Block on `approved` (or `approved with minor revisions` where the minors are inlined). If `needs revision`, return the wave to the same specialist with the review report attached; do NOT advance until green.

W3a → W3b is a wave boundary in the user's spec even though both are in the same "Wave 3" label, because the specialist changes (signal-processing → pyqt-ui). Treat it as a sub-wave gate: codex-review the W3a diff before launching W3b.

## TDD cadence inside each wave

Plan is already structured red→implement→green→commit per task (Steps X.1 / X.2 / X.3 / X.4 / X.5). Specialist briefs MUST quote this discipline verbatim and require the specialist to report `tests_before` (red count) and `tests_after` (green count) per task in their return JSON.

## Lessons consulted (paths read in step 4)

- `docs/lessons-learned/README.md`
- `docs/lessons-learned/LESSONS.md`
- `docs/lessons-learned/.state.yml`
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`
- `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md`
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
- `docs/lessons-learned/pyqt-ui/2026-04-26-conditional-visibility-init-sync-and-paired-field-children.md`
