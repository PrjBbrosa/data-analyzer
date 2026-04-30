def test_disk_add_triggers_probe(qtbot, tmp_path):
    from mf4_analyzer.ui.drawers.batch.input_panel import FileListWidget
    w = FileListWidget()
    qtbot.addWidget(w)
    # mock probe to return synchronously
    w._probe_signals_for = lambda path: frozenset({"sig_a", "sig_b"})
    w.add_disk_path(str(tmp_path / "fake.mf4"))
    qtbot.wait(50)
    state = w.row_state(str(tmp_path / "fake.mf4"))
    assert state in ("loaded", "probing")  # probing transient


def test_probe_failure_sets_probe_failed(qtbot, tmp_path):
    from mf4_analyzer.ui.drawers.batch.input_panel import FileListWidget
    w = FileListWidget()
    qtbot.addWidget(w)
    def fail(path):
        raise IOError("bad mf4")
    w._probe_signals_for = fail
    path = str(tmp_path / "x.mf4")
    w.add_disk_path(path)
    qtbot.wait(100)
    assert w.row_state(path) == "probe_failed"


def test_intersection_changes_emit_signal(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import FileListWidget
    w = FileListWidget()
    qtbot.addWidget(w)
    seen = []
    w.intersectionChanged.connect(seen.append)
    w.add_loaded_file(0, "a.mf4", frozenset({"sig", "rpm"}))
    w.add_loaded_file(1, "b.mf4", frozenset({"sig", "other"}))
    # Intersection should now be {"sig"}
    assert seen[-1] == frozenset({"sig"})


def test_path_pending_to_loaded_transition(qtbot, tmp_path):
    """Disk-add: state should walk path_pending → probing → loaded
    once probe completes (spec §3.2 file state machine)."""
    from mf4_analyzer.ui.drawers.batch.input_panel import FileListWidget
    w = FileListWidget()
    qtbot.addWidget(w)
    states = []
    w.stateChanged.connect(lambda path, state: states.append((path, state)))
    # Make the probe synchronous and successful
    w._probe_signals_for = lambda path: frozenset({"sig"})
    path = str(tmp_path / "x.mf4")
    w.add_disk_path(path)
    qtbot.waitUntil(lambda: w.row_state(path) == "loaded", timeout=2000)
    seen_states = [s for p, s in states if p == path]
    assert "path_pending" in seen_states
    assert "loaded" in seen_states


def test_run_disabled_while_probing(qtbot, tmp_path):
    """BatchSheet.is_runnable() must be False while any file is in
    path_pending OR probing state (spec §7).

    Two assertions: one for each state, since the user can land in either
    (path_pending = just queued, probing = worker actively reading channels_db).
    """
    from mf4_analyzer.ui.drawers.batch import BatchSheet
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    fl = sheet._input_panel._file_list

    # Need a runnable signal otherwise other panels gate is_runnable.
    fl.add_loaded_file(0, "ok.mf4", frozenset({"sig"}))
    sheet._input_panel._signal_picker.set_selected(("sig",))
    sheet._analysis_panel.set_method("fft")
    sheet._output_panel.apply_directory(str(tmp_path / "out"))
    qtbot.wait(20)
    assert sheet.is_runnable() is True   # baseline

    # path_pending blocks
    p1 = str(tmp_path / "pending.mf4")
    fl._set_row_state(p1, "path_pending")
    qtbot.wait(20)
    assert sheet.is_runnable() is False
    fl.remove_path(p1)

    # probing blocks
    p2 = str(tmp_path / "probing.mf4")
    fl._set_row_state(p2, "probing")
    qtbot.wait(20)
    assert sheet.is_runnable() is False
    fl.remove_path(p2)

    # Once cleared, runnable again
    qtbot.wait(20)
    assert sheet.is_runnable() is True


def test_pipeline_strip_recomputes_on_input_changes(qtbot):
    """Configuration changes in any panel must propagate to the strip's
    status badges (spec §3.1 ✓/⚠ logic)."""
    from mf4_analyzer.ui.drawers.batch import BatchSheet
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    # Initially all stages warn (no config)
    assert sheet.strip.cards[0].stage_status == "warn"
    # Add file + signal → INPUT goes ok
    sheet._input_panel._file_list.add_loaded_file(0, "a.mf4",
                                                   frozenset({"sig"}))
    sheet._input_panel._signal_picker.set_selected(("sig",))
    qtbot.wait(20)
    assert sheet.strip.cards[0].stage_status == "ok"


def test_run_button_disabled_until_runnable(qtbot, tmp_path):
    """运行按钮在未达到可运行配置时必须 disabled (ultrareview bug_018)."""
    from mf4_analyzer.ui.drawers.batch import BatchSheet
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    # W6 footer no longer uses QDialogButtonBox; the gated button is the
    # bare 运行 QPushButton living on the sheet as ``_btn_run``.
    run_btn = sheet._btn_run
    # Fresh dialog → not runnable
    assert run_btn.isEnabled() is False
    # Configure to runnable
    sheet._input_panel._file_list.add_loaded_file(0, "a.mf4", frozenset({"sig"}))
    sheet._input_panel._signal_picker.set_selected(("sig",))
    sheet._analysis_panel.set_method("fft")
    sheet._output_panel.apply_directory(str(tmp_path / "out"))
    qtbot.wait(20)
    assert run_btn.isEnabled() is True


def test_get_preset_includes_time_range(qtbot, tmp_path):
    """time_range 必须随 get_preset 注入 params (ultrareview bug_009)."""
    from mf4_analyzer.ui.drawers.batch import BatchSheet
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._input_panel._file_list.add_loaded_file(0, "a.mf4", frozenset({"sig"}))
    sheet._input_panel._signal_picker.set_selected(("sig",))
    sheet._analysis_panel.set_method("fft")
    sheet._output_panel.apply_directory(str(tmp_path / "out"))
    sheet.apply_time_range((2.0, 5.0))
    qtbot.wait(20)
    p = sheet.get_preset()
    assert p.params.get("time_range") == (2.0, 5.0)
    # Inverse: empty time_range field → no key
    sheet.apply_time_range(None)
    p2 = sheet.get_preset()
    assert "time_range" not in p2.params


def test_loaded_menu_uses_filename_not_fid(qtbot, tmp_path):
    """+ 已加载 菜单和文件行必须显示文件名而非合成 fid (ultrareview bug_003)."""
    import pandas as pd
    from mf4_analyzer.io import FileData
    from mf4_analyzer.ui.drawers.batch.input_panel import FileListWidget

    df = pd.DataFrame({"Time": [0.0, 1.0], "sig": [1.0, 2.0]})
    fd = FileData(tmp_path / "vehicle_run_001.mf4", df, list(df.columns), {}, idx=0)

    fl = FileListWidget(files={"f0": fd})
    qtbot.addWidget(fl)
    # Drive _add_from_files_source directly (no QMenu interaction needed)
    fl._add_from_files_source("f0", fd)
    qtbot.wait(20)
    paths = fl.loaded_disk_paths() + tuple(fl.all_loaded_paths())
    assert any("vehicle_run_001.mf4" in p for p in paths)
    # The fid string should NOT be a path
    assert "f0" not in [p for p in paths]


def test_probe_failed_row_blocks_input_ok(qtbot, tmp_path):
    """probe_failed 行必须让 INPUT card 变 warn 而不是 ok (ultrareview bug_005)."""
    from mf4_analyzer.ui.drawers.batch import BatchSheet
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    fl = sheet._input_panel._file_list
    fl.add_loaded_file(0, "ok.mf4", frozenset({"sig"}))
    sheet._input_panel._signal_picker.set_selected(("sig",))
    qtbot.wait(20)
    assert sheet.strip.cards[0].stage_status == "ok"
    # Inject a probe_failed row
    fl._set_row_state(str(tmp_path / "bad.mf4"), "probe_failed")
    qtbot.wait(20)
    assert sheet.strip.cards[0].stage_status == "warn"


def test_input_panel_rpm_uses_single_select_picker(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    p = InputPanel()
    qtbot.addWidget(p)
    p._file_list.add_loaded_file(0, "a.mf4", frozenset({"sig", "rpm_a"}))
    p._file_list.add_loaded_file(1, "b.mf4", frozenset({"sig", "rpm_a"}))
    assert isinstance(p._rpm_picker, SignalPickerPopup)
    assert p._rpm_picker._single_select is True


def test_input_panel_rpm_picker_partial_signals_visible_but_disabled(qtbot):
    """Partial-availability signals must show in the RPM picker (greyed),
    matching target-signal picker behavior. Resolves the 'RPM 通道无法选择'
    case where a candidate present in only some files used to vanish."""
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    p = InputPanel()
    qtbot.addWidget(p)
    p._file_list.add_loaded_file(0, "a.mf4", frozenset({"sig", "rpm_x"}))
    p._file_list.add_loaded_file(1, "b.mf4", frozenset({"sig"}))  # rpm_x only in 1/2
    assert "rpm_x" in p._rpm_picker.visible_items()
    assert p._rpm_picker.is_disabled("rpm_x") is True


def test_input_panel_rpm_unit_preset_sets_factor(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    p = InputPanel()
    qtbot.addWidget(p)
    p._rpm_unit_combo.setCurrentText("deg/s")
    assert abs(p._rpm_factor_spin.value() - 1.0 / 6.0) < 1e-9
    p._rpm_unit_combo.setCurrentText("rad/s")
    assert abs(p._rpm_factor_spin.value() - 60.0 / (2.0 * 3.141592653589793)) < 1e-6
    p._rpm_unit_combo.setCurrentText("rpm")
    assert p._rpm_factor_spin.value() == 1.0


def test_batch_double_spinboxes_display_compact_text_without_losing_precision(qtbot):
    """Default numeric text should not reserve width for fixed trailing zeroes."""
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    from mf4_analyzer.ui.drawers.batch.method_buttons import DynamicParamForm

    p = InputPanel()
    qtbot.addWidget(p)
    assert p._rpm_factor_spin.text() == "1.0"

    p._rpm_factor_spin.setValue(1.23456789)
    assert abs(p._rpm_factor_spin.value() - 1.23456789) < 1e-9
    assert p._rpm_factor_spin.text() == "1.23456789"

    form = DynamicParamForm()
    qtbot.addWidget(form)
    form.set_method("order_time")
    assert form._w_max_order.text() == "20.0"
    assert form._w_order_res.text() == "0.05"
    assert form._w_time_res.text() == "0.1"


def test_input_panel_rpm_manual_factor_switches_unit_to_custom(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    p = InputPanel()
    qtbot.addWidget(p)
    p._rpm_unit_combo.setCurrentText("rpm")
    p._rpm_factor_spin.setValue(0.42)
    assert p._rpm_unit_combo.currentText() == "自定义"


def test_input_panel_rpm_row_hidden_for_fft_method(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    p = InputPanel()
    qtbot.addWidget(p)
    p.set_method("fft")
    assert p._rpm_row_host.isVisibleTo(p) is False
    assert p._rpm_label_widget.isVisibleTo(p) is False


def test_input_panel_rpm_row_visible_for_order_time(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    p = InputPanel()
    qtbot.addWidget(p)
    p.set_method("order_time")
    assert p._rpm_row_host.isVisibleTo(p) is True
    assert p._rpm_label_widget.isVisibleTo(p) is True


def test_input_panel_rpm_row_hidden_for_fft_time(qtbot):
    """fft_time uses RPM-free spectrogram analysis (Phase 5)."""
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    p = InputPanel()
    qtbot.addWidget(p)
    p.set_method("fft_time")
    assert p._rpm_row_host.isVisibleTo(p) is False


def test_batch_sheet_method_change_drives_rpm_visibility(qtbot):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    sheet.show()
    sheet.apply_method("fft")
    assert sheet._input_panel._rpm_row_host.isVisibleTo(sheet) is False
    sheet.apply_method("order_time")
    assert sheet._input_panel._rpm_row_host.isVisibleTo(sheet) is True


def test_input_panel_rpm_factor_round_trips_through_preset(qtbot):
    """Export -> apply_preset -> get_preset must preserve rpm_factor.

    Regression guard for the rev-2 codex finding: Step 5.3 dropped
    rpm_factor from DynamicParamForm, so the import path needed an
    explicit ``apply_rpm_factor`` call to avoid silently resetting
    the spinbox to 1.0 on round-trip.
    """
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    sheet.apply_method("order_time")
    sheet._input_panel._rpm_unit_combo.setCurrentText("deg/s")
    exported = sheet.get_preset()
    assert abs(exported.params["rpm_factor"] - 1.0 / 6.0) < 1e-9

    # Round-trip via apply_preset on a fresh sheet
    sheet2 = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet2)
    sheet2.apply_preset(exported)
    re_exported = sheet2.get_preset()
    assert abs(re_exported.params["rpm_factor"] - 1.0 / 6.0) < 1e-9


def test_input_panel_rpm_factor_is_returned_in_params(qtbot):
    """rpm_factor lives in params (existing key) so the BatchRunner
    backend (batch.py:506,516) keeps reading it unchanged.

    Tolerance note: ``QDoubleSpinBox.setDecimals(10)`` (mandated by
    rev-2 fix #3) clamps stored precision to 1e-10, so a literal
    ``params == {"rpm_factor": 1.0 / 6.0}`` cannot hold byte-for-byte
    when ``1/6`` has ~16 significant decimal digits. The contract is
    "≤ 1e-10 precision loss" — assert that, mirroring the tolerance
    used in test_input_panel_rpm_unit_preset_sets_factor.
    """
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    p = InputPanel()
    qtbot.addWidget(p)
    p._rpm_unit_combo.setCurrentText("deg/s")
    params = p.rpm_params()
    assert set(params.keys()) == {"rpm_factor"}
    assert abs(params["rpm_factor"] - 1.0 / 6.0) < 1e-9


def test_batch_sheet_get_preset_includes_output_axis_params(qtbot):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    assert sheet._output_panel.combo_amp_unit.currentText() == "dB"
    sheet._output_panel.chk_x_auto.setChecked(False)
    sheet._output_panel.spin_x_min.setValue(1.0)
    sheet._output_panel.spin_x_max.setValue(2.0)
    sheet._output_panel.chk_y_auto.setChecked(False)
    sheet._output_panel.spin_y_min.setValue(3.0)
    sheet._output_panel.spin_y_max.setValue(4.0)
    sheet._output_panel.chk_z_auto.setChecked(False)
    sheet._output_panel.spin_z_floor.setValue(-40.0)
    sheet._output_panel.spin_z_ceiling.setValue(-5.0)
    sheet._output_panel.combo_amp_unit.setCurrentText("Linear")

    params = sheet.get_preset().params

    assert params["x_auto"] is False
    assert params["x_min"] == 1.0
    assert params["x_max"] == 2.0
    assert params["y_auto"] is False
    assert params["y_min"] == 3.0
    assert params["y_max"] == 4.0
    assert params["z_auto"] is False
    assert params["z_floor"] == -40.0
    assert params["z_ceiling"] == -5.0
    assert params["amplitude_mode"] == "amplitude"


def test_batch_sheet_apply_preset_restores_output_axis_params(qtbot):
    from mf4_analyzer.batch import AnalysisPreset
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    preset = AnalysisPreset.free_config(
        name="axis",
        method="order_time",
        target_signals=("sig",),
        params={
            "x_auto": False, "x_min": 1.0, "x_max": 2.0,
            "y_auto": False, "y_min": 3.0, "y_max": 4.0,
            "z_auto": False, "z_floor": -40.0, "z_ceiling": -5.0,
            "amplitude_mode": "amplitude",
        },
    )

    sheet.apply_preset(preset)

    assert sheet._output_panel.chk_x_auto.isChecked() is False
    assert sheet._output_panel.spin_x_min.value() == 1.0
    assert sheet._output_panel.spin_x_max.value() == 2.0
    assert sheet._output_panel.chk_y_auto.isChecked() is False
    assert sheet._output_panel.spin_y_min.value() == 3.0
    assert sheet._output_panel.spin_y_max.value() == 4.0
    assert sheet._output_panel.chk_z_auto.isChecked() is False
    assert sheet._output_panel.spin_z_floor.value() == -40.0
    assert sheet._output_panel.spin_z_ceiling.value() == -5.0
    assert sheet._output_panel.combo_amp_unit.currentText() == "Linear"


def test_picker_excludes_time_column(qtbot, tmp_path):
    """Time 列必须从 picker 候选信号中排除 (ultrareview bug_001)."""
    import pandas as pd
    from mf4_analyzer.io import FileData
    from mf4_analyzer.ui.drawers.batch import BatchSheet

    df = pd.DataFrame({"Time": [0.0, 1.0], "vibration_x": [0.1, 0.2]})
    fd = FileData(tmp_path / "a.mf4", df, list(df.columns), {}, idx=0)
    sheet = BatchSheet(None, files={"f0": fd})
    qtbot.addWidget(sheet)
    sheet._input_panel._file_list._add_from_files_source("f0", fd)
    qtbot.wait(20)
    visible = sheet._input_panel._signal_picker.visible_items()
    assert "vibration_x" in visible
    assert "Time" not in visible and "time" not in visible
