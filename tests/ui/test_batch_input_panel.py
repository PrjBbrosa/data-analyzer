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
