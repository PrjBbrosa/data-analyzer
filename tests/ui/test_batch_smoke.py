import pytest


def test_batch_sheet_pure_degraded_partial_is_not_reported_as_failure(
    qtbot, monkeypatch,
):
    from mf4_analyzer.batch import BatchRunResult
    from mf4_analyzer.ui.drawers.batch import sheet as sheet_module
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    widget = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(widget)
    widget.show()
    messages = []
    monkeypatch.setattr(
        sheet_module.QMessageBox,
        "information",
        lambda _parent, title, text: messages.append(("information", title, text)),
    )
    monkeypatch.setattr(
        sheet_module.QMessageBox,
        "warning",
        lambda _parent, title, text: messages.append(("warning", title, text)),
    )

    widget._show_result_toast(BatchRunResult(
        status="partial",
        degraded_count=2,
        warnings=["图片/PDF 导出后端不可用，本次仅导出数据文件"],
    ))

    assert messages == [(
        "information",
        "批处理降级完成",
        "完成，共 2 个任务仅导出数据文件。",
    )]


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
    assert the picker's sizeHint never scales with chip count. The approved
    inline-search design is a fixed single row: hidden selections use ``+N``
    instead of stacking vertically.

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
    # selections are both valid. fid=1 (not 0) — 0 is falsy and would be
    # silently dropped by any future ``if fid:`` check on the runner side.
    sheet._input_panel._file_list.add_loaded_file(
        1, "x.mf4", frozenset({"sig1", "sig2", "sig3", "sig4", "sig5"}),
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

    # Neither dimension may scale with chip count: the field stays one line.
    assert four_w == one_w
    assert four_h == one_h
    assert sheet._input_panel._signal_picker._overflow_label.text() == "+3"


def test_batch_sheet_time_filter_preset_round_trip(qtbot, tmp_path):
    import numpy as np
    import pandas as pd
    from mf4_analyzer.batch import AnalysisPreset
    from mf4_analyzer.io import FileData
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    t = np.arange(64, dtype=float) / 64.0
    df = pd.DataFrame({"Time": t, "sig": np.sin(2 * np.pi * 5 * t)})
    fd = FileData(tmp_path / "x.csv", df, list(df.columns), {}, idx=0, fs=64.0)
    sheet = BatchSheet(None, files={0: fd})
    qtbot.addWidget(sheet)
    preset = AnalysisPreset.free_config(
        name="time",
        method="time",
        target_signals=("sig",),
        params={
            "time_range": (0.1, 0.5),
            "filter": {
                "enabled": True,
                "spec": {"kind": "low", "order": 4, "cutoff": 10.0},
                "show_original": True,
                "show_filtered": True,
            },
        },
    )

    sheet.apply_preset(preset)
    got = sheet.get_preset()

    assert got.method == "time"
    assert got.params["time_range"] == (0.1, 0.5)
    assert got.params["filter"]["enabled"] is True
    assert got.params["filter"]["spec"]["kind"] == "low"
    assert got.params["filter"]["show_filtered"] is True


def test_full_time_preset_with_sparse_params_resets_all_time_render_state(qtbot):
    from mf4_analyzer.batch import AnalysisPreset
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet.apply_method("time")
    form = sheet._analysis_panel._param_form
    form.set_x_channel_candidates(("speed",), {})
    sheet.apply_params({
        "render_group_by": "source",
        "render_layout": "subplot",
        "x_source": "channel",
        "x_channel": "speed",
        "x_origin": "absolute",
    })
    assert form._pending_x_channel == "speed"

    # Exercise both bits of transient channel state before the full recipe
    # boundary.  A normalized preset with no sparse deviations represents all
    # five canonical defaults, not an incremental patch.
    form.set_x_channel_candidates(("rpm",), {"speed": "(1/2)"})
    assert "speed" in form.x_channel_validation_message()

    sheet.apply_preset(AnalysisPreset.free_config(
        name="defaults",
        method="time",
        target_signals=(),
        params={},
    ))

    assert form._w_render_group_by.currentData() == "none"
    assert form._w_render_layout.currentData() == "overlay"
    assert form._w_x_source.currentData() == "time"
    assert form._w_x_channel.currentData() == ""
    assert form._w_x_origin.currentData() == "zero"
    assert form._pending_x_channel == ""
    assert form.x_channel_validation_message() == ""
    assert form.get_params() == {}


def _time_file_data(
    tmp_path, name, *, speed_unit="", speed_metadata_unit="",
    channels=("target", "speed"),
):
    import numpy as np
    import pandas as pd

    from mf4_analyzer.io import FileData

    values = np.arange(8, dtype=float)
    data = {"Time": values / 8.0}
    for offset, channel in enumerate(channels, start=1):
        data[channel] = values + offset
    units = {"speed": speed_unit} if speed_unit else {}
    metadata = (
        {"speed": {"unit": speed_metadata_unit}}
        if speed_metadata_unit else {}
    )
    return FileData(
        tmp_path / name,
        pd.DataFrame(data),
        list(data),
        units,
        channel_metadata=metadata,
    )


def test_sheet_universe_wires_analysis_candidates_and_clears_stale_x(
    qtbot, tmp_path,
):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    first = _time_file_data(tmp_path, "one.csv", speed_unit="rpm")
    second = _time_file_data(
        tmp_path, "two.csv", channels=("target", "other"),
    )
    sheet = BatchSheet(None, files={"s1": first, "s2": second})
    qtbot.addWidget(sheet)
    sheet.apply_files(("s1",), ())
    sheet.apply_method("time")
    sheet.apply_params({"x_source": "channel", "x_channel": "speed"})

    form = sheet._analysis_panel._param_form
    assert form.get_params() == {
        "x_source": "channel", "x_channel": "speed",
    }

    sheet.apply_files(("s1", "s2"), ())

    partial_index = form._w_x_channel.findData("speed")
    assert partial_index >= 0
    assert form._w_x_channel.model().item(partial_index).isEnabled() is False
    assert form.get_params() == {"x_source": "channel"}
    assert "speed" in form.x_channel_validation_message()


def test_sheet_time_x_preflight_uses_metadata_then_units_and_fails_mixed(
    qtbot, tmp_path,
):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    first = _time_file_data(
        tmp_path, "one.csv", speed_unit="ignored", speed_metadata_unit="rpm",
    )
    second = _time_file_data(tmp_path, "two.csv", speed_unit="rpm")
    sheet = BatchSheet(None, files={"s1": first, "s2": second})
    qtbot.addWidget(sheet)
    sheet.apply_files(("s1", "s2"), ())
    sheet.apply_signals(("target",))
    sheet.apply_method("time")
    sheet.apply_params({"x_source": "channel", "x_channel": "speed"})

    assert not any(
        issue.code == "mixed_x_units" for issue in sheet.preflight_issues()
    )
    assert (
        sheet._output_panel._axis_row_parts["x"]["label"].text()
        == "speed (rpm)"
    )

    second_row = sheet._input_panel._file_list._rows["s2"]
    second_row.units["speed"] = "deg"
    sheet._input_panel._refresh_signal_universe()

    issues = sheet.preflight_issues()
    assert any(
        issue.field == "x_channel" and issue.code == "mixed_x_units"
        for issue in issues
    )
    assert sheet._output_panel._axis_row_parts["x"]["label"].text() == "speed"
    assert "rpm" not in sheet._output_panel._axis_row_parts["x"]["label"].text()


def test_sheet_time_x_empty_unit_is_a_real_cross_source_unit_fact(qtbot, tmp_path):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    first = _time_file_data(tmp_path, "one.csv")
    second = _time_file_data(tmp_path, "two.csv", speed_unit="rpm")
    sheet = BatchSheet(None, files={"s1": first, "s2": second})
    qtbot.addWidget(sheet)
    sheet.apply_files(("s1", "s2"), ())
    sheet.apply_signals(("target",))
    sheet.apply_method("time")
    sheet.apply_params({"x_source": "channel", "x_channel": "speed"})

    assert any(
        issue.field == "x_channel" and issue.code == "mixed_x_units"
        for issue in sheet.preflight_issues()
    )
    assert sheet._output_panel._axis_row_parts["x"]["label"].text() == "speed"

    second_row = sheet._input_panel._file_list._rows["s2"]
    second_row.units["speed"] = ""
    sheet._input_panel._refresh_signal_universe()

    assert not any(
        issue.code == "mixed_x_units" for issue in sheet.preflight_issues()
    )
    assert sheet._output_panel._axis_row_parts["x"]["label"].text() == "speed"


def test_sheet_channel_x_without_selection_has_field_issue(qtbot, tmp_path):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    source = _time_file_data(tmp_path, "one.csv", speed_unit="rpm")
    sheet = BatchSheet(None, files={"s1": source})
    qtbot.addWidget(sheet)
    sheet.apply_files(("s1",), ())
    sheet.apply_signals(("target",))
    sheet.apply_method("time")
    sheet.apply_params({"x_source": "channel"})

    assert any(
        issue.field == "x_channel" and issue.code == "required"
        for issue in sheet.preflight_issues()
    )


def test_time_analysis_form_fits_288px_after_repeated_dependency_toggles(
    qapp, qtbot,
):
    from pathlib import Path

    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QScrollArea

    from mf4_analyzer.ui.drawers.batch.analysis_panel import AnalysisPanel

    old_stylesheet = qapp.styleSheet()
    scroll = None
    try:
        qapp.setStyleSheet(
            Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
        )
        panel = AnalysisPanel()
        panel._param_form.set_x_channel_candidates(
            ("engine_speed_channel_name_that_is_deliberately_very_long",), {}
        )
        panel.apply_method("time")
        form = panel._param_form
        long_channel = "engine_speed_channel_name_that_is_deliberately_very_long"
        form._w_render_group_by.setCurrentIndex(
            form._w_render_group_by.findData("source")
        )
        form._w_x_source.setCurrentIndex(
            form._w_x_source.findData("channel")
        )
        form._w_x_channel.setCurrentIndex(
            form._w_x_channel.findData(long_channel)
        )
        scroll = QScrollArea()
        qtbot.addWidget(scroll)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(panel)
        scroll.resize(288, 640)
        scroll.show()
        qtbot.wait(20)

        def assert_visible_channel_geometry():
            assert form._w_x_channel.isVisibleTo(panel) is True
            assert form._w_x_channel.currentData() == long_channel
            assert scroll.horizontalScrollBar().maximum() == 0
            assert panel.minimumSizeHint().width() <= scroll.viewport().width()
            for widget in form._widgets.values():
                if widget.isVisibleTo(panel) and form._form.indexOf(widget) >= 0:
                    right = widget.mapTo(panel, widget.rect().topRight()).x()
                    assert right < panel.width()

        assert_visible_channel_geometry()

        for _ in range(2):
            form._w_render_group_by.setCurrentIndex(
                form._w_render_group_by.findData("none")
            )
            form._w_x_source.setCurrentIndex(
                form._w_x_source.findData("time")
            )
            form._w_render_group_by.setCurrentIndex(
                form._w_render_group_by.findData("source")
            )
            form._w_x_source.setCurrentIndex(
                form._w_x_source.findData("channel")
            )
            form._w_x_channel.setCurrentIndex(
                form._w_x_channel.findData(long_channel)
            )
        qtbot.wait(20)

        assert_visible_channel_geometry()
    finally:
        if scroll is not None:
            scroll.close()
        qapp.setStyleSheet(old_stylesheet)


@pytest.mark.parametrize(
    ("method", "params", "rpm_signal"),
    (
        (
            "fft",
            {
                "fs": 48000.0,
                "window": "flattop",
                "nfft": None,
                "nfft_mode": "auto",
                "t_win_s": 0.25,
                "overlap": 0.5,
                "avg_mode": "welch",
                "avg_overlap": 75,
                "amp_y": "Linear",
                "amplitude_mode": "amplitude",
                "weighting": "A",
                "db_reference_mode": "auto",
                "db_reference": 2e-5,
            },
            None,
        ),
        (
            "fft_time",
            {
                "fs": 12000.0,
                "window": "kaiser",
                "nfft": None,
                "nfft_mode": "auto",
                "t_win_s": 0.1,
                "overlap": 0.75,
                "remove_mean": False,
                "amplitude_mode": "amplitude_db",
                "weighting": "A",
                "db_reference_mode": "manual",
                "db_reference": 1e-6,
            },
            None,
        ),
        (
            "order_time",
            {
                "fs": 4096.0,
                "window": "bartlett",
                "nfft": None,
                "nfft_mode": "auto",
                "max_order": 36.0,
                "order_res": 0.025,
                "time_res": 0.2,
                "rpm_mode": "manual",
                "manual_rpm": 1800.0,
                "samples_per_rev": 2048,
                "rpm_factor": 1.0,
                "amplitude_mode": "Amplitude dB",
                "db_reference_mode": "auto",
                "db_reference": 1.0,
            },
            ("rpm-file", "rpm"),
        ),
    ),
)
def test_current_single_full_recipe_round_trip_preserves_hidden_intent(
    qtbot, method, params, rpm_signal,
):
    from mf4_analyzer.batch import AnalysisPreset
    from mf4_analyzer.batch_recipe import normalize_batch_params
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    preset = AnalysisPreset.from_current_single(
        name="current",
        method=method,
        signal=("f1", "sig"),
        rpm_signal=rpm_signal,
        rpm_channel="rpm" if rpm_signal else "",
        params=params,
    )
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)

    sheet.apply_preset(preset)
    got = sheet.get_preset()

    assert got.source == "current_single"
    assert got.signal == ("f1", "sig")
    assert got.rpm_signal == rpm_signal
    assert normalize_batch_params(got.params, method) == normalize_batch_params(
        params, method
    )


def test_current_single_converts_to_free_config_only_after_scope_expands(qtbot):
    from mf4_analyzer.batch import AnalysisPreset
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    preset = AnalysisPreset.from_current_single(
        name="current", method="fft", signal=("f1", "sig"),
        params={"window": "hanning", "nfft": 1024},
    )
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet.apply_preset(preset)

    assert sheet.get_preset().source == "current_single"

    sheet._input_panel._file_list.add_loaded_file(
        "f2", "f2", frozenset({"sig", "other"})
    )
    sheet._input_panel.apply_signals(("sig", "other"))
    expanded = sheet.get_preset()

    assert expanded.source == "free_config"
    assert expanded.file_ids == ("f1", "f2")
    assert expanded.target_signals == ("sig", "other")


def test_current_single_signal_replacement_remains_exact_single_scope(qtbot):
    from mf4_analyzer.batch import AnalysisPreset
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    preset = AnalysisPreset.from_current_single(
        name="current", method="fft", signal=("f1", "sig"),
        params={"window": "hanning", "nfft": 1024},
    )
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet.apply_preset(preset)

    sheet._input_panel.apply_signals(("replacement",))
    replaced = sheet.get_preset()

    assert replaced.source == "current_single"
    assert replaced.signal == ("f1", "replacement")


def test_exact_time_pairs_survive_unedited_sheet_without_cartesian_expansion(qtbot):
    import dataclasses

    from mf4_analyzer.batch import AnalysisPreset
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    preset = AnalysisPreset.free_config(
        name="current time",
        method="time",
        target_signals=("A", "B"),
        params={"time_range": (0.0, 1.0)},
    )
    preset = dataclasses.replace(
        preset,
        file_ids=("f1", "f2"),
        target_pairs=(("f1", "A"), ("f2", "B")),
    )
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)

    sheet.apply_preset(preset)
    got = sheet.get_preset()

    assert got.target_pairs == (("f1", "A"), ("f2", "B"))
    assert sheet._build_dry_run_preview() == [
        ("f1", "A", "time"),
        ("f2", "B", "time"),
    ]


def test_preflight_rejects_invalid_recipe_fields(qtbot, tmp_path):
    from mf4_analyzer.batch import AnalysisPreset
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    preset = AnalysisPreset.free_config(
        name="bad",
        method="fft",
        target_signals=("sig",),
        params={"fs": 0.0, "window": "hanning", "nfft": 1024},
    )
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._input_panel._file_list.add_loaded_file(
        "f1", "f1", frozenset({"sig"})
    )
    sheet._output_panel.apply_directory(str(tmp_path / "out"))
    sheet.apply_preset(preset)

    assert sheet.is_runnable() is False
    assert any(issue.field == "fs" for issue in sheet.preflight_issues())
    assert sheet.strip.cards[1].summary_label.text() == "FFT · 采样率无效"
    assert sheet._footer_task_summary.text() == "请检查采样率"


def test_available_policy_dry_run_uses_source_ids_without_cartesian_missing_pairs(
    qtbot,
):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    fl = sheet._input_panel._file_list
    fl.add_loaded_file("s1", "same.hdf", frozenset({"A", "B"}))
    fl.add_loaded_file("s2", "same.hdf", frozenset({"A", "C"}))
    sheet._input_panel.apply_target_policy("available_per_source")
    sheet.apply_signals(("B", "C"))

    preset = sheet.get_preset()
    assert preset.source_ids == ("s1", "s2")
    assert preset.source_paths == ("same.hdf", "same.hdf")
    assert preset.target_policy == "available_per_source"
    assert sheet._build_dry_run_preview() == [
        (fl._rows["s1"].label, "B", "fft"),
        (fl._rows["s2"].label, "C", "fft"),
    ]
    assert sheet.signals_marked_unavailable() == ()


def test_common_policy_dry_run_only_lists_true_intersection(qtbot):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    fl = sheet._input_panel._file_list
    fl.add_loaded_file("s1", "one.hdf", frozenset({"A", "B"}))
    fl.add_loaded_file("s2", "two.hdf", frozenset({"A", "C"}))
    sheet.apply_signals(("A", "B"))

    assert sheet.signals_marked_unavailable() == ("B",)
    assert sheet._build_dry_run_preview() == [
        (fl._rows["s1"].label, "A", "fft"),
        (fl._rows["s2"].label, "A", "fft"),
    ]


def test_exact_source_pairs_keep_exact_policy_and_parallel_scope(qtbot):
    import dataclasses

    from mf4_analyzer.batch import AnalysisPreset
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    preset = AnalysisPreset.free_config(
        "exact", "time", target_signals=("A", "B"), target_policy="exact_pairs",
    )
    preset = dataclasses.replace(
        preset,
        source_ids=("s1", "s2"),
        source_paths=("/tmp/groups.hdf", "/tmp/groups.hdf"),
        target_pairs=(("s1", "A"), ("s2", "B")),
    )
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet.apply_preset(preset)

    got = sheet.get_preset()
    assert got.target_policy == "exact_pairs"
    assert got.target_pairs == (("s1", "A"), ("s2", "B"))
    assert got.source_ids == ("s1", "s2")
    assert got.source_paths == ("/tmp/groups.hdf", "/tmp/groups.hdf")
    assert len(sheet._build_dry_run_preview()) == 2

    sheet._input_panel._file_list._rows["s1"].channels = frozenset({"A"})
    sheet._input_panel._file_list._rows["s2"].channels = frozenset({"C"})
    assert sheet.signals_marked_unavailable() == ("B",)


def test_builtin_analysis_preset_does_not_change_scope_output_or_db(qtbot, tmp_path):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._input_panel._file_list.add_loaded_file(
        "s1", "a.csv", frozenset({"sig"}),
    )
    sheet.apply_signals(("sig",))
    sheet._output_panel.apply_directory(str(tmp_path / "out"))
    sheet._output_panel.apply_reference_params({
        "db_reference_mode": "manual", "db_reference": 3.5,
    })
    before_scope = (sheet.source_ids(), sheet.source_paths(), sheet.selected_signals())
    before_output = (
        sheet.output_dir(), sheet.export_data(), sheet.export_image(), sheet.data_format(),
    )

    sheet._analysis_panel._preset_buttons["torque"].click()

    assert (sheet.source_ids(), sheet.source_paths(), sheet.selected_signals()) == before_scope
    assert (
        sheet.output_dir(), sheet.export_data(), sheet.export_image(), sheet.data_format(),
    ) == before_output
    ref = sheet._output_panel.reference_params()
    assert ref["db_reference_mode"] == "manual"
    assert ref["db_reference"] == pytest.approx(3.5)


@pytest.mark.parametrize("width", (288, 320))
def test_batch_columns_fit_supported_narrow_widths(qtbot, width):
    from mf4_analyzer.ui.drawers.batch.analysis_panel import AnalysisPanel
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    from mf4_analyzer.ui.drawers.batch.output_panel import OutputPanel

    for panel_type in (InputPanel, AnalysisPanel, OutputPanel):
        panel = panel_type()
        qtbot.addWidget(panel)
        panel.resize(width, 650)
        panel.show()
        qtbot.wait(5)

        assert panel.minimumSizeHint().width() <= width
        assert panel.width() <= width

        panel.close()


def test_batch_sheet_respects_1080x760_with_production_qss(qapp, qtbot):
    from pathlib import Path

    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    old_stylesheet = qapp.styleSheet()
    try:
        qapp.setStyleSheet(
            Path("mf4_analyzer/ui_kit/style.qss").read_text(encoding="utf-8")
        )
        sheet = BatchSheet(None, files={})
        qtbot.addWidget(sheet)
        file_list = sheet._input_panel._file_list
        file_list.add_loaded_file("s1", "one.hdf", frozenset({"A", "B"}))
        file_list.add_loaded_file("s2", "two.hdf", frozenset({"A", "C"}))
        sheet._input_panel.apply_target_policy("available_per_source")
        sheet.apply_signals(("B", "C"))
        sheet.resize(1080, 760)
        sheet.show()
        qtbot.wait(20)

        assert sheet.width() == 1080
        assert sheet.height() <= 760
        picker = sheet._input_panel._signal_picker
        assert picker.height() >= picker.sizeHint().height()
        assert not sheet._task_list.isVisible()
        assert sheet._footer_host.height() == 54
        assert sheet._footer_progress.isVisible()
        assert sheet._footer_status.isVisible()
    finally:
        sheet.close()
        qapp.setStyleSheet(old_stylesheet)


def test_sheet_migrates_legacy_outputs_to_the_compact_contract(qtbot):
    from mf4_analyzer.batch import BatchOutput
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    outputs = BatchOutput(
        export_data=True,
        export_image=True,
        data_format="xlsx",
        image_format="svg",
        image_size="custom",
        image_width=3210,
        image_height=1234,
        image_dpi=222,
        conflict_policy="skip",
        write_manifest=False,
        resume_policy="manifest",
    )
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet.apply_outputs(outputs)
    sheet._resume_manifest_path = "/runtime/resume.json"

    compact = sheet.get_preset().outputs
    assert compact.data_format == "xlsx"
    assert compact.image_format == "png"
    assert (compact.image_width, compact.image_height) == (1920, 1080)
    assert compact.conflict_policy == "auto_number"
    assert compact.resume_policy == "none"
    exported = sheet._build_preset_for_export()
    assert exported.outputs == compact
    assert not hasattr(exported, "resume_manifest")
    assert not hasattr(exported, "retry_failed_manifest")


def test_sheet_output_preview_uses_batch_runner_core_facts(qtbot, tmp_path):
    import numpy as np
    import pandas as pd

    from mf4_analyzer.batch import BatchOutput
    from mf4_analyzer.io import FileData
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    t = np.arange(128, dtype=float) / 128.0
    fd = FileData(
        tmp_path / "source.csv",
        pd.DataFrame({"Time": t, "sig": np.sin(2 * np.pi * 8 * t)}),
        ["Time", "sig"], {}, idx=0, fs=128.0,
    )
    sheet = BatchSheet(None, files={0: fd})
    qtbot.addWidget(sheet)
    sheet.apply_files((0,), ())
    sheet.apply_signals(("sig",))
    sheet.apply_method("fft")
    sheet.apply_params({"window": "hanning", "nfft": 128})
    sheet.apply_outputs(BatchOutput(
        export_data=True,
        export_image=True,
        image_format="svg",
        image_size="2560x1440",
        conflict_policy="skip",
    ))
    sheet._output_panel.apply_directory(str(tmp_path / "out"))
    sheet._recompute_pipeline_status()

    preview = sheet._output_panel.output_preview_text()
    assert "1 任务" in preview
    assert "2 文件" in preview
    assert "PNG 1920×1080" in preview
    assert "auto_number" in preview


def test_sheet_resume_retry_manifest_selection_is_runtime_only(
    qtbot, tmp_path, monkeypatch,
):
    from PyQt5.QtWidgets import QFileDialog

    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    resume_path = tmp_path / "resume.json"
    retry_path = tmp_path / "retry.json"
    choices = iter(((str(resume_path), ""), (str(retry_path), "")))
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *args, **kwargs: next(choices),
    )
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)

    sheet._output_panel._btn_resume.click()
    assert sheet._resume_manifest_path == str(resume_path)
    assert sheet._retry_failed_manifest_path is None
    assert sheet.get_preset().outputs.resume_policy == "none"
    assert resume_path.name in sheet._output_panel._operation_status.text()

    sheet._output_panel._btn_retry_failed.click()
    assert sheet._resume_manifest_path is None
    assert sheet._retry_failed_manifest_path == str(retry_path)
    assert sheet.get_preset().outputs.resume_policy == "none"
    assert retry_path.name in sheet._output_panel._operation_status.text()
    assert not sheet._output_panel._operation_status.isVisible()
    assert not hasattr(sheet.get_preset(), "retry_failed_manifest")


@pytest.mark.parametrize(
    "field",
    ("image_dpi", "image_background", "image_line_width"),
)
def test_sheet_routes_output_validation_issues_to_output_stage(
    qtbot, monkeypatch, field,
):
    from mf4_analyzer.batch_validation import ValidationIssue
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    issue = ValidationIssue(
        field, "invalid_output_option", "image output option is invalid",
    )
    monkeypatch.setattr(sheet, "preflight_issues", lambda: (issue,))

    sheet._recompute_pipeline_status()

    assert field not in sheet.strip.cards[1].summary_label.text()
    assert sheet.strip.cards[2].stage_status == "warn"
    assert field not in sheet.strip.cards[2].summary_label.text()
    assert sheet.strip.cards[2].summary_label.text() == "导出设置待完善"


def test_sheet_lock_includes_toolbar_and_output_operations(qtbot):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    sheet.lock_editing()

    assert not sheet._btn_fill_from_current.isEnabled()
    assert not sheet._btn_import_preset.isEnabled()
    assert not sheet._btn_export_preset.isEnabled()
    assert not sheet._output_panel._btn_resume.isEnabled()
    assert not sheet._output_panel._btn_retry_failed.isEnabled()

    sheet.unlock_editing()
    assert not sheet._btn_fill_from_current.isEnabled()
    assert sheet._btn_import_preset.isEnabled()
    assert sheet._btn_export_preset.isEnabled()
    assert sheet._output_panel._btn_resume.isEnabled()
    assert sheet._output_panel._btn_retry_failed.isEnabled()


def test_sheet_opens_artifact_location_only_after_explicit_row_activation(
    qtbot, tmp_path, monkeypatch,
):
    from PyQt5.QtGui import QDesktopServices

    from mf4_analyzer.batch import BatchProgressEvent
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    opened = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl", lambda url: opened.append(url) or True,
    )
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._task_list.apply_dry_run([("a.mf4", "sig", "fft")], 1)
    artifact = tmp_path / "result.png"
    sheet._task_list.on_event(BatchProgressEvent(
        kind="task_done", task_index=1, total=1, image_path=str(artifact),
    ))

    assert opened == []
    sheet._task_list._on_item_activated(sheet._task_list._items[0])
    assert len(opened) == 1
    assert opened[0].toLocalFile() == str(tmp_path)
