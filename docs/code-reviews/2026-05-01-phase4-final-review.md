## Test Suite Result
passed - 492 passed, 81 warnings.

## Criterion 1 — Interface Contract Consistency
FAIL - All three handlers reset in the right value order, but the signal contract is not consistent.

- OrderContextual sets `chk_z_auto` before resetting the range at `mf4_analyzer/ui/inspector_sections.py:2144-2146`, and FFTTimeContextual does the same at `mf4_analyzer/ui/inspector_sections.py:2689-2691`. However neither handler blocks `chk_z_auto`, `spin_z_floor`, or `spin_z_ceiling`, and neither emits one terminal aggregate signal inside the function (`mf4_analyzer/ui/inspector_sections.py:2133-2147`, `mf4_analyzer/ui/inspector_sections.py:2678-2692`). That means the two inspector handlers can emit child `toggled`/`valueChanged` events from the three setters rather than exactly one end-of-reset signal.
- OutputPanel does coalesce the reset: it blocks exactly `chk_z_auto`, `spin_z_floor`, and `spin_z_ceiling` at `mf4_analyzer/ui/drawers/batch/output_panel.py:179-187`, syncs enabled state at `mf4_analyzer/ui/drawers/batch/output_panel.py:188`, then emits one `changed` signal at `mf4_analyzer/ui/drawers/batch/output_panel.py:189`. The tests assert the one-emission contract at `tests/ui/test_batch_output_panel.py:35-49` and `tests/ui/test_batch_output_panel.py:66-76`.
- Unit-label/current-text updates are decoupled from range reset on programmatic preset paths: Order blocks the combo signal but still sets the combo index at `mf4_analyzer/ui/inspector_sections.py:2221-2223`, FFTTime does the same at `mf4_analyzer/ui/inspector_sections.py:2980-2982`, and OutputPanel does the same at `mf4_analyzer/ui/drawers/batch/output_panel.py:266-270`. Tests assert the combo text changed while preset Z values survived at `tests/ui/test_inspector.py:1951-1965`, `tests/ui/test_inspector.py:2529-2540`, and `tests/ui/test_batch_output_panel.py:143-148`.

## Criterion 2 — z_range_for Single Authority
PASS - Production grep found a single executable authority.

`rg -n "Z_RANGE_DEFAULTS|def z_range_for|z_range_for\(" mf4_analyzer tests` returned the only definitions in `mf4_analyzer/ui/_axis_defaults.py:22-34`, plus the three production call sites at `mf4_analyzer/ui/inspector_sections.py:2143`, `mf4_analyzer/ui/inspector_sections.py:2688`, and `mf4_analyzer/ui/drawers/batch/output_panel.py:178`. The imports are from the shared module at `mf4_analyzer/ui/inspector_sections.py:37` and `mf4_analyzer/ui/drawers/batch/output_panel.py:25`.

## Criterion 3 — Test Coverage Matrix
| P1 issue | W | test name(s) | strong RED? (Y/N) |
|---|---|---|---|
| P7-L1 / P7-L1' inspector dB/Linear unit toggle keeps stale Z range (`docs/code-reviews/2026-05-01-recent-prs-deep-review.md:16-19`) | W1 | `test_order_contextual_unit_toggle_resets_z_range` (`tests/ui/test_inspector.py:1809-1853`); `test_order_contextual_unit_toggle_same_unit_idempotent` (`tests/ui/test_inspector.py:1856-1879`); `test_fft_time_contextual_unit_toggle_resets_z_range` (`tests/ui/test_inspector.py:2433-2465`) | Y - bodies plant stale ranges, trigger the handler, and assert new-unit defaults, so the old "only set z_auto" handler fails. |
| P8-L1 Batch OUTPUT unit toggle preserves stale manual Z range (`docs/code-reviews/2026-05-01-recent-prs-deep-review.md:60-63`) | W2 | `test_batch_output_panel_unit_toggle_resets_z_range_db_to_linear` (`tests/ui/test_batch_output_panel.py:20-49`); `test_batch_output_panel_unit_toggle_resets_z_range_linear_to_db` (`tests/ui/test_batch_output_panel.py:53-76`); `test_batch_output_panel_apply_axis_params_does_not_trigger_reset` (`tests/ui/test_batch_output_panel.py:79-157`) | Y - the first two fail against the old combo-only `changed.emit()` behavior; the third fails if preset apply lets the reset handler run. |
| P10-L2 ChartOptionsDialog log scale accepts non-positive limits (`docs/code-reviews/2026-05-01-recent-prs-deep-review.md:89-92`) | W3 | `test_chart_options_log_axis_rejects_non_positive` (`tests/ui/test_dialogs.py:152-192`); `test_chart_options_log_axis_warning_blocks_close` (`tests/ui/test_dialogs.py:195-232`); `test_chart_options_log_axis_positive_range_applies` (`tests/ui/test_dialogs.py:235-264`); `test_chart_options_log_axis_positive_range_ok_button_accepts` (`tests/ui/test_dialogs.py:267-322`) | Y - the invalid-range tests assert `set_ylim` is skipped, `_invalid_axes` records the axis, warning fires once, and OK does not accept. |

## Criterion 4 — apply_axis_params Call-Site Audit
PASS - Production grep found two call sites, both inside `BatchSheet.apply_preset`.

- `current_single` path: `mf4_analyzer/ui/drawers/batch/sheet.py:324-338`.
- `free_config` path: `mf4_analyzer/ui/drawers/batch/sheet.py:340-349`.

The only newly suppressed signal is the combo's programmatic `currentTextChanged` during `OutputPanel.apply_axis_params` at `mf4_analyzer/ui/drawers/batch/output_panel.py:261-270`. `BatchSheet` listens to `OutputPanel.changed` for pipeline recompute at `mf4_analyzer/ui/drawers/batch/sheet.py:162`, but its OUTPUT badge/run gating reads only directory/export/data-format state at `mf4_analyzer/ui/drawers/batch/sheet.py:216-228`, not axis params. The only visible caller-side behavioral adjustment is the test reorder that sets the unit before manual Z values at `tests/ui/test_batch_input_panel.py:339-344`.

## Criterion 5 — ChartOptionsDialog Isolation
PASS - The diff in `mf4_analyzer/ui/dialogs.py` is contained to `ChartOptionsDialog`.

Other dialog classes in the file are `ChannelEditorDialog` at `mf4_analyzer/ui/dialogs.py:35`, `ExportDialog` at `mf4_analyzer/ui/dialogs.py:212`, and `AxisEditDialog` at `mf4_analyzer/ui/dialogs.py:240`; the zero-context diff hunks only touch `ChartOptionsDialog` additions/edits at `mf4_analyzer/ui/dialogs.py:305`, `mf4_analyzer/ui/dialogs.py:596-640`, `mf4_analyzer/ui/dialogs.py:645-664`, and `mf4_analyzer/ui/dialogs.py:749-755`. `_invalid_axes` is an instance attribute initialized on `ChartOptionsDialog` at `mf4_analyzer/ui/dialogs.py:305`, and `_apply_axis` is a `ChartOptionsDialog` method at `mf4_analyzer/ui/dialogs.py:645`, so the new validation is not shared through inheritance or helper calls with the other dialog classes.

## Criterion 6 — Scope Containment
PASS - No unexpected files found in the working-tree scope check.

Requested command `git diff --name-only main HEAD` returned no paths because these Phase 4 changes are working-tree/untracked changes, not committed changes on `HEAD`. The working-tree scope before this review report was created was limited to the expected files: tracked modifications in `mf4_analyzer/ui/dialogs.py`, `mf4_analyzer/ui/drawers/batch/output_panel.py`, `mf4_analyzer/ui/inspector_sections.py`, `tests/ui/test_batch_input_panel.py`, `tests/ui/test_dialogs.py`, and `tests/ui/test_inspector.py`; untracked additions in `docs/code-reviews/2026-05-01-recent-prs-deep-review.md`, `docs/code-reviews/2026-05-01-w1-rereview.md`, `docs/lessons-learned/orchestrator/decompositions/2026-05-01-codex-review-fixes.md`, `docs/superpowers/plans/2026-05-01-codex-review-fixes.md`, `docs/superpowers/specs/2026-05-01-codex-review-fixes-design.md`, `mf4_analyzer/ui/_axis_defaults.py`, and `tests/ui/test_batch_output_panel.py`. Unexpected files: none.

## Criterion 7 — Documentation Alignment
FAIL - The code matches the intended fixes, but the spec/plan text still has stale or unevidenced items.

- Spec §2.2 says invalid log limits `return False` at `docs/superpowers/specs/2026-05-01-codex-review-fixes-design.md:94-99`; the implementation does not return a status from `_apply_axis`. It records `_invalid_axes`, autoscale-falls-back, and returns `None` through `mf4_analyzer/ui/dialogs.py:645-664`, with aggregation in `apply_changes` at `mf4_analyzer/ui/dialogs.py:595-640`.
- Spec §2.4 says validation is only triggered by the "应用" button / `self._apply_clicked` at `docs/superpowers/specs/2026-05-01-codex-review-fixes-design.md:130-132`; actual wiring has Apply call `apply_changes` and OK call `_accept_with_apply` at `mf4_analyzer/ui/dialogs.py:343-346`, and `_accept_with_apply` also validates by calling `apply_changes` at `mf4_analyzer/ui/dialogs.py:749-755`.
- Spec §2.3 says the warning lists the invalid X/Y axes at `docs/superpowers/specs/2026-05-01-codex-review-fixes-design.md:128`; actual warning text is generic and does not enumerate `self._invalid_axes` at `mf4_analyzer/ui/dialogs.py:633-637`.
- Plan exit criteria are only partially evidenced by the live suite. The pytest criterion at `docs/superpowers/plans/2026-05-01-codex-review-fixes.md:139` is satisfied by `492 passed`, but the plan also requires W1+W2+W3 codex verdict pass, `.state.yml` increment, final READY verdict, and final report path in notes at `docs/superpowers/plans/2026-05-01-codex-review-fixes.md:138-142`. Current `.state.yml` still shows `top_level_completions: 34` at `docs/lessons-learned/.state.yml:2`, and the changed docs only include a W1 re-review verdict at `docs/code-reviews/2026-05-01-w1-rereview.md:340-344`.

## Criterion 8 — P1 Coverage Completeness
| P1 item | addressed by | test coverage | verdict |
|---|---|---|---|
| P7-L1 inspector unit toggle keeps stale Z range (`docs/code-reviews/2026-05-01-recent-prs-deep-review.md:16-19`) | W1 | Order reset tests at `tests/ui/test_inspector.py:1809-1853`; same-unit idempotency at `tests/ui/test_inspector.py:1856-1879`; FFTTime reset tests at `tests/ui/test_inspector.py:2433-2465`; preset-signal guards at `tests/ui/test_inspector.py:1910-2016` and `tests/ui/test_inspector.py:2492-2580` | Covered with strong RED tests, not happy-path only. |
| P8-L1 Batch OUTPUT unit toggle keeps stale Z range (`docs/code-reviews/2026-05-01-recent-prs-deep-review.md:60-63`) | W2 | OutputPanel dB->Linear and Linear->dB reset tests at `tests/ui/test_batch_output_panel.py:20-76`; preset apply guard at `tests/ui/test_batch_output_panel.py:79-157` | Covered with strong RED tests, not happy-path only. |
| P10-L2 ChartOptionsDialog log scale accepts non-positive limits (`docs/code-reviews/2026-05-01-recent-prs-deep-review.md:89-92`) | W3 | Invalid-range rejection at `tests/ui/test_dialogs.py:152-192`; warning/keep-open path at `tests/ui/test_dialogs.py:195-232`; positive paths at `tests/ui/test_dialogs.py:235-322` | Covered with invalid-path RED tests plus positive regression coverage. |

## Summary
- FAIL Criterion 1: Inspector unit-toggle handlers are not signal-coalesced; either update the contract to explicitly exempt inspector handlers, or block `chk_z_auto`/Z spins and emit one explicit owner-level signal after reset with regression coverage.
- FAIL Criterion 7: Update spec §2.2/§2.4/§2.3 wording to match the `_invalid_axes` collector + Apply/OK validation flow, and either complete or revise the plan exit-criteria evidence for W2/W3 codex gates, `.state.yml`, and final report notes.

## VERDICT
VERDICT: BLOCK — Criterion 1, Criterion 7
