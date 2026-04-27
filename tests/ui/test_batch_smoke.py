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


def test_batch_smoke_fft_time_fixes_combined(qtbot, tmp_path):
    """Drives the dialog through: pick fft_time, RPM row hides; add a
    loaded file with multiple signals; pick first one then grow to four;
    assert the picker's sizeHint width does not scale with chip count
    (issue-1 contract) while height does grow (chips stack vertically).

    NOTE: we measure ``_signal_picker.sizeHint()`` rather than
    ``sheet.width()`` because the dialog itself is fixed by
    ``resize(1080, 760)`` and would not change regardless of picker
    behavior — that assertion would silently pass even if the bug
    returned. The picker-level sizeHint is the honest contract.
    """
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    sheet.show()

    # Pick fft_time -> RPM row hides
    sheet.apply_method("fft_time")
    assert sheet._input_panel._rpm_row_host.isVisibleTo(sheet) is False

    # Add a fake loaded file with five available signals so 1- and 4-chip
    # selections are both valid.
    sheet._input_panel._file_list.add_loaded_file(
        0, "x.mf4", frozenset({"sig1", "sig2", "sig3", "sig4", "sig5"}),
    )
    qtbot.wait(20)  # let _refresh_signal_universe propagate

    # 1-chip baseline
    sheet._input_panel._signal_picker.set_selected(("sig1",))
    qtbot.wait(20)
    one_w = sheet._input_panel._signal_picker.sizeHint().width()
    one_h = sheet._input_panel._signal_picker.sizeHint().height()

    # Grow to 4 chips
    sheet._input_panel._signal_picker.set_selected(
        ("sig1", "sig2", "sig3", "sig4"),
    )
    qtbot.wait(20)
    four_w = sheet._input_panel._signal_picker.sizeHint().width()
    four_h = sheet._input_panel._signal_picker.sizeHint().height()

    # Width must NOT scale with chip count (issue-1 contract).
    assert four_w == one_w
    # Height grows with chip count, capped by the chip-scroll's
    # MAX_VISIBLE_ROWS height (Step 2.3 sets _chip_scroll.maxHeight=96).
    assert four_h >= one_h
