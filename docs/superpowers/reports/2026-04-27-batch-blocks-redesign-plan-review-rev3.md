## Verdict
needs revision before execution

NF-1 is resolved, but NF-2 remains partial because the `BatchSheet.is_runnable()` coverage names probing while only forcing a `path_pending` row.

## NF-1 Status
resolved

Evidence: in `**Public BatchSheet / panel accessors**`, the W5 contract now includes `def signals_marked_unavailable(self) -> tuple[str, ...]: ...`. The W7 apply-preset test calls the same zero-argument method and asserts a tuple result: `assert sheet.signals_marked_unavailable() == ("absent_signal",)`.

## NF-2 Status
partial

- W5 picker: ESC key collapse + focus-out collapse: resolved — §Wave 5 adds `def test_picker_popup_collapses_on_escape(qtbot):` with `qtbot.keyClick(p._popup, Qt.Key_Escape)` and `assert p.is_popup_visible() is False`, plus `def test_picker_popup_collapses_on_focus_out(qtbot):` with `p._popup.clearFocus()` and the same hidden assertion.
- W5 input panel: path_pending -> loaded transition: resolved — §Wave 5 adds `def test_path_pending_to_loaded_transition(qtbot, tmp_path):` and the docstring says `Disk-add: state should walk path_pending → probing → loaded once probe completes`.
- W5 input panel: BatchSheet.is_runnable() False while probing: partial — §Wave 5 adds `def test_run_disabled_while_probing(qtbot, tmp_path):` and a docstring saying `BatchSheet.is_runnable() must be False while any file is in path_pending or probing state`, but the body only forces `fl._set_row_state(str(tmp_path / "pending.mf4"), "path_pending")` before `assert sheet.is_runnable() is False`.
- W5 input panel: PipelineStrip status recomputation: resolved — §Wave 5 adds `def test_pipeline_strip_recomputes_on_input_changes(qtbot):` and asserts `sheet.strip.cards[0].stage_status == "warn"` before file/signal changes, then `assert sheet.strip.cards[0].stage_status == "ok"` after them.
- W6 runner thread: sheet-level cancel button -> unlock UI: resolved — §Wave 6 adds `def test_sheet_cancel_button_unlocks_editing(qtbot, tmp_path):`, calls `sheet._on_cancel_clicked()  # 中断 button handler`, waits for `_running is False`, and asserts `_input_panel`, `_analysis_panel`, and `_output_panel` are enabled.

## Carry-forward from rev-2 (F7, F8)
F7: partial — most missing UI coverage is now present, but the probing-disabled test still only sets `path_pending`, the self-review still says `§8 test plan → tests created in Waves 1-6` even though W7 creates `tests/ui/test_batch_toolbar.py`, and the closest large-file probe text is only manual `add a real .mf4 from disk`, not the 5GB probe smoke called out in rev 2.

F8: resolved — the W5 accessor contract now lists `def signals_marked_unavailable(self) -> tuple[str, ...]: ...`, and W7 calls that exact method in `assert sheet.signals_marked_unavailable() == ("absent_signal",)`.

## New Findings
None.

## Summary
Rev 3 fixes the W5/W7 unavailable-signal API mismatch. The remaining issue is targeted: add an explicit `probing` state assertion for `BatchSheet.is_runnable()` and clean up the carry-forward §8/self-review residue before execution.
