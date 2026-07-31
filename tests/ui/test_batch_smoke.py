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

    # Width must NOT scale with chip count (issue-1 contract).
    assert four_w == one_w
    # Height grows with chip count, capped by the chip-scroll's
    # MAX_VISIBLE_ROWS height (Step 2.3 sets _chip_scroll.maxHeight=96).
    assert four_h >= one_h


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
    assert "fs" in sheet.strip.cards[1].summary_label.text()


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
        task_list = sheet._task_list
        assert not task_list._body.isVisible()
        assert task_list.height() <= 42

        task_list.apply_dry_run(
            [(f"{index}.hdf", "A", "fft") for index in range(20)],
            outputs_per_task=2,
        )
        qtbot.wait(10)
        assert task_list._body.isVisible()
        assert task_list._body.height() <= 120
        assert task_list.height() <= 162
    finally:
        sheet.close()
        qapp.setStyleSheet(old_stylesheet)


def test_sheet_round_trips_full_outputs_without_runtime_manifest_paths(qtbot):
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

    assert sheet.get_preset().outputs == outputs
    exported = sheet._build_preset_for_export()
    assert exported.outputs == outputs
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
    assert "SVG 2560×1440" in preview
    assert "skip" in preview


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
    assert sheet.get_preset().outputs.resume_policy == "manifest"
    assert resume_path.name in sheet._output_panel._operation_status.text()

    sheet._output_panel._btn_retry_failed.click()
    assert sheet._resume_manifest_path is None
    assert sheet._retry_failed_manifest_path == str(retry_path)
    assert sheet.get_preset().outputs.resume_policy == "none"
    assert retry_path.name in sheet._output_panel._operation_status.text()
    assert not hasattr(sheet.get_preset(), "retry_failed_manifest")


def test_sheet_routes_output_validation_issues_to_output_stage(
    qtbot, monkeypatch,
):
    from mf4_analyzer.batch_validation import ValidationIssue
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    issue = ValidationIssue(
        "image_dpi", "invalid_dpi", "image dpi is invalid",
    )
    monkeypatch.setattr(sheet, "preflight_issues", lambda: (issue,))

    sheet._recompute_pipeline_status()

    assert "image_dpi" not in sheet.strip.cards[1].summary_label.text()
    assert sheet.strip.cards[2].stage_status == "warn"
    assert "image_dpi" in sheet.strip.cards[2].summary_label.text()


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
