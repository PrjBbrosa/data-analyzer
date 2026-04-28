# Decomposition — Remove `order_track` Feature End-to-End

**Date:** 2026-04-28
**User request (verbatim, original phrasing):** "移除阶次追踪模块，不需要。"
**Confirmed scope (post-clarification):** Remove the entire order-tracking feature
from UI, signal, batch, and tests. Includes `signal/order.py`'s
`OrderTrackResult` dataclass + `extract_order_track_result` method + the legacy
`extract_order_track` shim, plus the `target_order` field on
`OrderAnalysisParams`. Batch presets containing `order_track` should be
gracefully ignored on load (whitelist filter), not crash.

**Visual anchor (from user screenshot):** Inspector right pane —
`QGroupBox("阶次跟踪")` containing `spin_to` (目标阶次 QDoubleSpinBox) +
`btn_ok` (QPushButton "阶次跟踪") must disappear in its entirety. The
preceding `btn_ot` ("时间-阶次") button stays.

## Missed-keyword note (per CLAUDE.md "Missed triggers")

The original user message "移除阶次追踪模块，不需要。" did not match any squad
routing keyword, but the change spans UI + signal + batch + tests — identical
in nature to the 2026-04-26 `order_rpm` removal (5 commits across 4 layers).
Recommendation logged in this audit: **add "整条链路" / "移除...模块" / "删除...特性"
to the routing keyword set** so cross-layer feature deletions auto-route.

## Precedent

The `order_rpm` removal (2026-04-26, baseline 06d17a8 + commits 20a8ccf,
10d3f1a → 4af101c) is the direct precedent: identical 4-layer slice. We mirror
its commit-shape (signal first, UI relays, main_window dispatcher, batch +
tests last) but bundle adjacent layers when commit-collision risk is zero.

## Decomposition

| subtask | expert | depends_on | rationale |
|---|---|---|---|
| S1-signal-strip-order-track | signal-processing-expert | (none) | Owns `mf4_analyzer/signal/order.py` and `signal/__init__.py`. Deletes `OrderTrackResult` dataclass, `extract_order_track_result` static method, the legacy `extract_order_track` thin wrapper, and the `target_order` field on `OrderAnalysisParams`. Bundles `tests/test_order_analysis.py` cleanup (drop track-only tests; `compute_time_order_result` invariant test loses its track half) — same specialist, same domain, no cross-file race. Emits the new public API surface. |
| S2-ui-inspector-and-relay | pyqt-ui-engineer | S1 | Owns the visible widget removal: `inspector_sections.py` (delete `QGroupBox("阶次跟踪")`, `spin_to`, `btn_ok`, `btn_ok.clicked.connect`, `target_order=` line in `_collect_preset`, `target_order` branch in `_apply_preset`, `target_order()` getter; update the "时间-阶次 / 阶次跟踪" comment; fold `_collect_preset`/`_apply_preset` so `target_order` no longer round-trips). Also `inspector.py` (`order_track_requested` signal declaration line 43 + relay line 131). Plus `tests/ui/test_inspector.py` track assertions (lines 74, 82). Bundled because all three live in the inspector's signal contract — splitting into 3 specialists would parallelise same-relay edits. |
| S3-main-window-dispatcher-and-canvas-comments | pyqt-ui-engineer | S2 | Owns `mf4_analyzer/ui/main_window.py`: delete `do_order_track` (1373-1398), `_render_order_track` (1542-1608), `'track'` kind branch in `OrderWorker.run` (124-128), `_order_track_pending_rpm` field + comment (181-185), the `inspector.order_track_requested.connect(self.do_order_track)` wire (298), the `_render_order_track(result)` dispatch (1485), and the `_remember_batch_preset("当前阶次跟踪", "order_track", ...)` call (1592-1608). ALSO `mf4_analyzer/ui/canvases.py` comment-only updates: lines 168, 218 (build_envelope docstring), line 1588 (heatmap rebuild docstring). Bundled because the canvas changes are pure-comment touches that depend on knowing main_window no longer renders track — cheaper than a separate refactor pass. |
| S4-batch-runner-and-batch-ui-and-tests | refactor-architect | S1 | Mechanical multi-file removal: `mf4_analyzer/batch.py` (`SUPPORTED_METHODS` line 157 → drop `order_track`; `_run_one` `elif method == 'order_track'` branch line 416-418; `_compute_order_track_dataframe` static method 530-536; `'order_track'` image_payload kind 581-584; `target_order` line in `_order_params` 478; **add a whitelist filter on preset load** so legacy presets carrying `method=order_track` are dropped gracefully). `mf4_analyzer/ui/drawers/batch/`: `method_buttons.py` (line 4 docstring, line 29 tuple, line 86 `_METHOD_FIELDS["order_track"]`, lines 110/154-160/210-211/236 `target_order` widget — delete the entire `_w_target_order` block since no remaining method uses it), `sheet.py` line 40 mapping, `input_panel.py` line 48 `_RPM_USING_METHODS` set. Tests: `tests/test_batch_runner.py` lines 105-130 (delete `test_free_config_order_track_preset_selects_matching_signals`); update line 433 test docstring + line 440-441 SUPPORTED_METHODS assertion `{"fft", "order_time", "fft_time"}`. `tests/ui/test_batch_method_buttons.py` line 35 `set_method("order_track")`. Refactor-architect because it is multi-file mechanical removal across four batch layers + tests + adding one whitelist guard — same specialist owned the original `order_rpm` removal of the same shape (commit cfb301b). |
| S5-canvases-test-rename | pyqt-ui-engineer | S3, S4 | The test `tests/ui/test_canvases_envelope.py::test_plot_canvas_heatmap_to_track_to_heatmap_no_colorbar_ghost` is a colorbar-ghost regression whose 2-subplot setup happens to mirror the order_track shape. Keep its assertion logic; rename to `test_plot_canvas_heatmap_to_2subplot_to_heatmap_no_colorbar_ghost` and rewrite the docstring/comments (lines 11, 51, 138-152) to remove order_track references. Pyqt-ui-engineer because it is canvas-test maintenance, not signal logic. Tail-task because it depends on the order_track surface being fully gone (otherwise the test could regress and stay green by accident). |

## Boundary discipline (forbidden symbols per subtask)

To prevent the silent-boundary-leak pattern (lessons:
`orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`),
each specialist's brief explicitly enumerates forbidden symbols.

- **S1 (signal):** MUST NOT touch `compute_time_order_result`, `OrderTimeResult`,
  `OrderAnalyzer.__init__` body unrelated to track. MUST NOT touch UI files,
  `batch.py`, or any drawer file.
- **S2 (inspector):** MUST NOT touch `main_window.py`, `canvases.py`, `batch.py`,
  any drawer file, or any signal file. Must keep `btn_ot` ("时间-阶次") fully
  intact.
- **S3 (main_window):** MUST NOT touch `inspector_sections.py`, `inspector.py`,
  `signal/order.py`, `batch.py`, or drawers. Allowed in `canvases.py`: ONLY
  comments (no class/def edits, no plotting-logic changes).
- **S4 (batch):** MUST NOT touch `signal/order.py`, `inspector_sections.py`,
  `inspector.py`, `main_window.py`, or `canvases.py`. Tests touched are
  enumerated above; do not touch `tests/ui/test_inspector.py` or
  `tests/test_order_analysis.py`.
- **S5 (canvases-test):** MUST NOT touch `canvases.py` itself, `main_window.py`,
  `inspector*.py`, `batch.py`, `signal/order.py`, or any drawer.

## Sequencing rationale

S1 must precede S2/S4 because deleting `OrderTrackResult` /
`extract_order_track_result` / `OrderAnalysisParams.target_order` makes
those imports unresolvable; downstream specialists need the import errors to
guide their cleanup. S2 must precede S3 so that the
`order_track_requested` signal is gone before main_window unwires it (the
reverse order would error on `disconnect`-style cleanups). S4 can run in
parallel with S2+S3 (different files; no shared file with either) — but per
`orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`,
verify no shared-file overlap. S5 is strictly tail-task.

**Parallelization plan for main Claude:**
- Wave A: S1 alone.
- Wave B: S2 + S4 in parallel (different files: inspector vs batch).
- Wave C: S3 alone (depends on S2; touches main_window which S4 didn't).
- Wave D: S5 alone (tail).

## Lessons consulted

- `docs/lessons-learned/README.md` — reflection protocol.
- `docs/lessons-learned/LESSONS.md` — index sweep.
- `docs/lessons-learned/.state.yml` — cadence position 33/21 (no prune
  trigger; 33 - 21 = 12 < 20).
- `docs/lessons-learned/signal-processing/2026-04-27-plan-verbatim-source-must-reconcile-with-recent-removals.md`
  — DIRECT precedent. The `order_rpm` removal forgot to drop `order_rpm`
  from `SUPPORTED_METHODS`; this run must update the assertion in
  `test_batch_runner.py` line 440 to match the new live set
  `{"fft", "order_time", "fft_time"}` AND drop track from the dispatcher
  in the same commit so the gate-vs-handler invariant stays strict.
- `docs/lessons-learned/orchestrator/2026-04-22-move-then-tighten-causes-cross-specialist-rework.md`
  — Inform: bundle mechanical edits with the body-creator's brief. Applied
  in S3 (canvas comments folded into main_window task) and S2 (inspector
  test edit folded into the relay-removal task).
- `docs/lessons-learned/orchestrator/2026-04-24-refactor-then-ui-same-file-boundary-disjoint.md`
  — Inform: enumerate forbidden symbols per brief. Applied above.
- `docs/lessons-learned/orchestrator/2026-04-24-parallel-same-file-drawer-task-collision.md`
  — Inform: don't parallelise tasks that share a file. S2 + S4 share NO
  file; S3 + S4 share NO file; safe to fan out.
- `docs/lessons-learned/orchestrator/2026-04-25-silent-boundary-leak-bypasses-rework-detection.md`
  — Inform: each specialist must report `symbols_touched` and main Claude
  should grep forbidden symbols against the diff before review.

## Acceptance criteria (main Claude verifies after S5)

1. `grep -rE "order_track|OrderTrackResult|extract_order_track|target_order|_order_track_pending_rpm|_render_order_track|order_track_requested|do_order_track" mf4_analyzer/ tests/` returns ONLY:
   - tests/test_order_analysis.py if the existing `target_order` references inside `compute_time_order_result` tests use it as a local variable name (acceptable — no API contract).
   - Any matches in lessons-learned/ (out of scope).
2. `pytest tests/` is fully green.
3. Inspector visual smoke (offscreen): the order contextual page no longer
   renders a "阶次跟踪" group; "时间-阶次" button still present and clickable.
4. Batch sheet smoke: the method-button row no longer offers `order_track`;
   loading a legacy preset with `method=order_track` is silently ignored
   (no crash, no zombie row).

## Rework-risk pre-check (orchestrator self-audit)

Cross-subtask file overlap matrix (after Wave-D bundle plan):

|  | signal/order.py | tests/test_order_analysis.py | inspector_sections.py | inspector.py | tests/ui/test_inspector.py | main_window.py | canvases.py | batch.py | drawers/batch/* | tests/test_batch_runner.py | tests/ui/test_batch_method_buttons.py | tests/ui/test_canvases_envelope.py |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S1 | X | X |  |  |  |  |  |  |  |  |  |  |
| S2 |  |  | X | X | X |  |  |  |  |  |  |  |
| S3 |  |  |  |  |  | X | X (comments) |  |  |  |  |  |
| S4 |  |  |  |  |  |  |  | X | X |  X | X |  |
| S5 |  |  |  |  |  |  |  |  |  |  |  | X |

**No file appears in two subtasks**, so rework detection should fire ZERO
mechanical hits. If it fires, the orchestrator missed something — investigate
before writing a rework lesson.
