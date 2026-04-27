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
    """OK 按钮在未达到可运行配置时必须 disabled (ultrareview bug_018)."""
    from PyQt5.QtWidgets import QDialogButtonBox
    from mf4_analyzer.ui.drawers.batch import BatchSheet
    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    ok = sheet._buttons.button(QDialogButtonBox.Ok)
    # Fresh dialog → not runnable
    assert ok.isEnabled() is False
    # Configure to runnable
    sheet._input_panel._file_list.add_loaded_file(0, "a.mf4", frozenset({"sig"}))
    sheet._input_panel._signal_picker.set_selected(("sig",))
    sheet._analysis_panel.set_method("fft")
    sheet._output_panel.apply_directory(str(tmp_path / "out"))
    qtbot.wait(20)
    assert ok.isEnabled() is True


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
