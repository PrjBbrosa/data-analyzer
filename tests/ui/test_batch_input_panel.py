import pytest


class _Ready:
    status = "ready"
    reason = ""
    is_ready = True


class _Limited:
    status = "limited"
    reason = "需要 DBC 解码"
    is_ready = False


class _Adapter:
    key = "hdf"
    display_name = "HEAD HDF"
    probe_cost = "full"


class _Registry:
    file_dialog_glob = "*.hdf *.csv"

    def __init__(self, descriptors=(), availability=None):
        self._descriptors = tuple(descriptors)
        self._availability = availability or _Ready()

    def adapter_for(self, _path):
        return _Adapter()

    def availability_for(self, _path, context=None):
        return self._availability

    def probe_sources(self, _path, *, context=None):
        return self._descriptors


def test_legacy_probe_helper_delegates_to_registry_and_unions_groups():
    from mf4_analyzer.io.source_adapters import SourceDescriptor
    from mf4_analyzer.ui.drawers.batch.input_panel import (
        _default_probe_signals_for,
    )

    calls = []

    class Registry(_Registry):
        def probe_sources(self, path, *, context=None):
            calls.append((path, context))
            return self._descriptors

    descriptors = (
        SourceDescriptor(
            source_id="g1", source_path="groups.hdf", group_id="g1",
            display_name="groups.hdf · g1", channel_names=("A", "B"),
            units={}, fs=None, metadata={},
        ),
        SourceDescriptor(
            source_id="g2", source_path="groups.hdf", group_id="g2",
            display_name="groups.hdf · g2", channel_names=("B", "C"),
            units={}, fs=None, metadata={},
        ),
    )
    context = {"dbc_path": "vehicle.dbc"}

    channels = _default_probe_signals_for(
        "groups.hdf", source_registry=Registry(descriptors),
        source_context=context,
    )

    assert channels == frozenset({"A", "B", "C"})
    assert calls == [("groups.hdf", context)]


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


def test_disk_dialog_uses_shared_registry_filter_and_generic_title(
    qtbot, monkeypatch,
):
    from mf4_analyzer.ui.drawers.batch import input_panel

    seen = {}

    def choose(_parent, title, _directory, file_filter):
        seen.update(title=title, file_filter=file_filter)
        return [], ""

    monkeypatch.setattr(input_panel.QFileDialog, "getOpenFileNames", choose)
    w = input_panel.FileListWidget(source_registry=_Registry())
    qtbot.addWidget(w)
    w._open_disk_dialog()

    assert seen["title"] == "选择数据文件"
    assert "*.hdf *.csv" in seen["file_filter"]
    assert "MF4 files" not in seen["file_filter"]


def test_registry_probe_expands_one_path_into_source_id_rows(qtbot, tmp_path):
    from mf4_analyzer.io.source_adapters import SourceDescriptor
    from mf4_analyzer.ui.drawers.batch.input_panel import FileListWidget

    path = str(tmp_path / "groups.hdf")
    descriptors = tuple(
        SourceDescriptor(
            source_id=f"source-{group}", source_path=path, group_id=group,
            display_name=f"groups.hdf · {group}", channel_names=(signal,),
            units={signal: "m/s2"}, fs=1000.0,
            metadata={"probe_cost": "full"},
        )
        for group, signal in (("g1", "A"), ("g2", "B"))
    )
    w = FileListWidget(source_registry=_Registry(descriptors))
    qtbot.addWidget(w)
    w.add_disk_path(path)
    qtbot.waitUntil(lambda: len(w.loaded_source_ids()) == 2, timeout=2000)

    assert set(w._rows) == {"source-g1", "source-g2"}
    assert w.source_paths() == (path, path)
    assert w._rows["source-g1"].group_id == "g1"
    assert "full probe" in w._rows["source-g1"].label
    assert w._rows["source-g1"].availability == "ready"


def test_limited_source_row_exposes_reason_and_never_runs_probe(qtbot, tmp_path):
    from mf4_analyzer.ui.drawers.batch.input_panel import (
        FileListWidget, STATE_UNAVAILABLE,
    )

    w = FileListWidget(
        source_registry=_Registry(availability=_Limited()),
    )
    qtbot.addWidget(w)
    called = []
    w._probe_signals_for = lambda path: called.append(path)
    path = str(tmp_path / "capture.blf")
    w.add_disk_path(path)
    qtbot.wait(30)

    assert w.row_state(path) == STATE_UNAVAILABLE
    row = next(iter(w._rows.values()))
    assert "需要 DBC 解码" in row.label
    assert "需要 DBC 解码" in row._item.toolTip()
    assert called == []


def test_inline_file_manager_keeps_a_250px_viewport_for_all_row_counts(qtbot):
    """Input controls below the file viewport must not move with row count."""
    from PyQt5.QtCore import QPoint
    from PyQt5.QtWidgets import QLabel

    from mf4_analyzer.ui.drawers.batch.input_panel import (
        BATCH_INLINE_FILE_MANAGER_HEIGHT, InputPanel,
    )

    panel = InputPanel()
    qtbot.addWidget(panel)
    panel.resize(360, 700)
    panel.show()
    qtbot.wait(20)

    target_title = next(
        label for label in panel.findChildren(QLabel) if label.text() == "目标"
    )
    target_y = target_title.mapTo(panel, QPoint(0, 0)).y()

    for index in range(8):
        if index in {0, 1, 4}:
            assert panel._file_manager_host.height() == BATCH_INLINE_FILE_MANAGER_HEIGHT
            assert panel._file_list.height() == panel._file_manager_host.contentsRect().height()
            assert target_title.mapTo(panel, QPoint(0, 0)).y() == target_y
        panel._file_list.add_loaded_file(
            f"source-{index}", f"/tmp/source-{index}.mf4", frozenset({"A"}),
        )
        qtbot.wait(5)

    assert panel._file_manager_host.height() == BATCH_INLINE_FILE_MANAGER_HEIGHT
    assert target_title.mapTo(panel, QPoint(0, 0)).y() == target_y
    file_scroll = panel._file_list._list.verticalScrollBar()
    assert file_scroll.maximum() > file_scroll.minimum()


def test_file_list_forwards_boundary_wheel_to_outer_input_pane(qtbot):
    """The nested list must not trap scrolling once it reaches an endpoint."""
    from PyQt5.QtCore import QPoint, QPointF, Qt
    from PyQt5.QtGui import QWheelEvent
    from PyQt5.QtWidgets import QApplication

    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet.resize(1080, 400)
    sheet.show()
    qtbot.wait(20)

    file_list = sheet._input_panel._file_list
    for index in range(8):
        file_list.add_loaded_file(
            f"source-{index}", f"/tmp/source-{index}.mf4", frozenset({"A"}),
        )
    qtbot.wait(20)

    inner = file_list._list.verticalScrollBar()
    outer = sheet._input_scroll.verticalScrollBar()
    assert inner.maximum() > inner.minimum()
    assert outer.maximum() > outer.minimum()

    def wheel(delta: int) -> QWheelEvent:
        viewport = file_list._list.viewport()
        pos = QPointF(viewport.rect().center())
        event = QWheelEvent(
            pos, QPointF(viewport.mapToGlobal(viewport.rect().center())),
            QPoint(), QPoint(0, delta), Qt.NoButton, Qt.NoModifier,
            Qt.NoScrollPhase, False,
        )
        QApplication.sendEvent(viewport, event)
        return event

    inner.setValue(inner.maximum())
    outer.setValue(outer.minimum())
    down = wheel(-120)
    assert down.isAccepted()
    assert outer.value() > outer.minimum()

    inner.setValue(inner.minimum())
    outer.setValue(outer.maximum())
    up = wheel(120)
    assert up.isAccepted()
    assert outer.value() < outer.maximum()


def test_target_policy_switches_common_intersection_to_selectable_union(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel

    panel = InputPanel()
    qtbot.addWidget(panel)
    panel._file_list.add_loaded_file("s1", "a.csv", frozenset({"A", "only_a"}))
    panel._file_list.add_loaded_file("s2", "b.csv", frozenset({"A", "only_b"}))

    assert panel.target_policy() == "common"
    assert panel._signal_picker.is_disabled("only_a") is True

    panel.apply_target_policy("available_per_source")
    assert panel._signal_picker.is_disabled("only_a") is False
    panel.apply_signals(("only_a", "only_b"))
    assert panel.selected_signals() == ("only_a", "only_b")
    assert panel.source_ids() == ("s1", "s2")
    assert panel.source_paths() == ("a.csv", "b.csv")


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


def test_input_panel_emits_exact_common_and_partial_channel_universe(qtbot):
    """Removing the public universe signal would leave Analysis stale."""
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel

    panel = InputPanel()
    qtbot.addWidget(panel)
    seen = []
    panel.channelUniverseChanged.connect(
        lambda common, partial: seen.append((common, partial))
    )

    panel._file_list.add_loaded_file(
        "s1", "a.csv", frozenset({"shared", "only_a"}),
    )
    panel._file_list.add_loaded_file(
        "s2", "b.csv", frozenset({"shared", "only_b"}),
    )

    assert seen[-1] == (
        ("shared",),
        {"only_a": "(1/2)", "only_b": "(1/2)"},
    )


def test_one_file_mutation_emits_one_channel_universe_change(qtbot):
    """One FileList mutation must not refresh the same universe twice."""
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel

    panel = InputPanel()
    qtbot.addWidget(panel)
    seen = []
    panel.channelUniverseChanged.connect(
        lambda common, partial: seen.append((common, partial))
    )

    panel._file_list.add_loaded_file(
        "s1", "a.csv", frozenset({"rpm", "shared"}),
    )
    assert seen == [(('rpm', 'shared'), {})]

    panel._file_list.add_loaded_file(
        "s2", "b.csv", frozenset({"shared", "temperature"}),
    )
    assert seen == [
        (("rpm", "shared"), {}),
        (
            ("shared",),
            {"rpm": "(1/2)", "temperature": "(1/2)"},
        ),
    ]


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
    # Signal-driven pipeline status is intentionally debounced.
    qtbot.waitUntil(
        lambda: sheet.strip.cards[0].stage_status == "ok", timeout=1000,
    )
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
    # Run-button state follows the debounced pipeline transaction.
    qtbot.waitUntil(run_btn.isEnabled, timeout=1000)
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


@pytest.mark.parametrize(
    ("text", "message_part"),
    (
        ("broken", "两个"),
        ("2,1", "小于"),
        ("1,1", "小于"),
        ("nan,2", "有限"),
        ("0,inf", "有限"),
    ),
)
def test_invalid_time_range_text_blocks_run_with_field_error(
    qtbot, tmp_path, text, message_part,
):
    from mf4_analyzer.ui.drawers.batch import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._input_panel._file_list.add_loaded_file(
        0, "a.mf4", frozenset({"sig"})
    )
    sheet._input_panel._signal_picker.set_selected(("sig",))
    sheet._output_panel.apply_directory(str(tmp_path / "out"))
    sheet._analysis_panel._source_interval_mode.setCurrentIndex(1)
    sheet._analysis_panel._source_interval_edit.setText(text)

    assert sheet.time_range() is None
    assert sheet.is_runnable() is False
    assert "源数据区间" in sheet._time_range_error()
    assert message_part in sheet._time_range_error()


def test_empty_time_range_remains_valid_full_segment(qtbot, tmp_path):
    from mf4_analyzer.ui.drawers.batch import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._input_panel._file_list.add_loaded_file(
        0, "a.mf4", frozenset({"sig"})
    )
    sheet._input_panel._signal_picker.set_selected(("sig",))
    sheet._output_panel.apply_directory(str(tmp_path / "out"))
    assert sheet._analysis_panel._source_interval_mode.currentData() == "all"

    assert sheet._time_range_error() == ""
    assert sheet.is_runnable() is True


def test_no_selected_output_blocks_run(qtbot, tmp_path):
    from mf4_analyzer.ui.drawers.batch import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._input_panel._file_list.add_loaded_file(
        0, "a.mf4", frozenset({"sig"})
    )
    sheet._input_panel._signal_picker.set_selected(("sig",))
    sheet._output_panel.apply_directory(str(tmp_path / "out"))
    sheet._output_panel._chk_data.setChecked(False)
    sheet._output_panel._chk_image.setChecked(False)

    assert sheet.is_runnable() is False
    assert any(issue.field == "outputs" for issue in sheet.preflight_issues())


def test_order_channel_mode_requires_rpm_selection_before_run(qtbot, tmp_path):
    from mf4_analyzer.ui.drawers.batch import BatchSheet

    sheet = BatchSheet(None, files={})
    qtbot.addWidget(sheet)
    sheet._input_panel._file_list.add_loaded_file(
        0, "a.mf4", frozenset({"sig", "rpm"})
    )
    sheet._input_panel._signal_picker.set_selected(("sig",))
    sheet.apply_method("order_time")
    sheet._output_panel.apply_directory(str(tmp_path / "out"))

    assert sheet.is_runnable() is False
    assert any(issue.field == "rpm_channel" for issue in sheet.preflight_issues())
    expected_summary = "阶次 · RPM 通道未配置"
    # Method changes refresh the pipeline only after their dependent panels settle.
    qtbot.waitUntil(
        lambda: sheet.strip.cards[1].summary_label.text() == expected_summary,
        timeout=1000,
    )
    assert sheet.strip.cards[1].summary_label.text() == expected_summary
    assert sheet._footer_task_summary.text() == "请选择 RPM 通道"

    sheet._input_panel.apply_rpm_channel("rpm")

    assert sheet.is_runnable() is True


def test_free_order_preset_binds_unique_cross_source_rpm(qtbot, tmp_path):
    """A partial RPM choice must retain its logical source for COT.

    This catches the multi-rate HDF case where ``Left`` is in a wideband
    logical source and ``Com_RPS_Speed_DV`` only exists in the low-rate
    logical source.  Without the source pair, BatchRunner looks for RPM in
    the Left source and rejects the task instead of interpolating it.
    """
    import numpy as np
    import pandas as pd

    from mf4_analyzer.batch import BatchRunner
    from mf4_analyzer.io import FileData
    from mf4_analyzer.ui.drawers.batch import BatchSheet

    target = FileData(
        tmp_path / "noise.csv",
        pd.DataFrame({
            "time": [0.0, 0.25, 0.5],
            "Left": [1.0, 2.0, 3.0],
        }),
        ["time", "Left"],
        {},
    )
    speed = FileData(
        tmp_path / "speed.csv",
        pd.DataFrame({
            "time": [0.0, 0.5],
            "Com_RPS_Speed_DV": [1000.0, 2000.0],
        }),
        ["time", "Com_RPS_Speed_DV"],
        {},
    )
    files = {"noise": target, "speed": speed}
    sheet = BatchSheet(None, files=files)
    qtbot.addWidget(sheet)
    file_list = sheet._input_panel._file_list
    file_list.add_loaded_file("noise", str(target.filepath), frozenset({"Left"}))
    file_list.add_loaded_file(
        "speed", str(speed.filepath), frozenset({"Com_RPS_Speed_DV"}),
    )
    sheet.apply_method("order_time")
    sheet._input_panel.apply_target_policy("available_per_source")
    sheet.apply_signals(("Left",))
    sheet.apply_rpm_channel("Com_RPS_Speed_DV")

    preset = sheet.get_preset()

    assert preset.rpm_signal == ("speed", "Com_RPS_Speed_DV")
    runner = BatchRunner(files)
    assert list(runner._expand_tasks(preset)) == [("noise", "Left")]
    np.testing.assert_allclose(
        runner._rpm_values(target, preset, target_source_id="noise"),
        [1000.0, 1500.0, 2000.0],
    )


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
    # Wait for the coalesced input-stage refresh, not a timing guess.
    qtbot.waitUntil(
        lambda: sheet.strip.cards[0].stage_status == "ok", timeout=1000,
    )
    assert sheet.strip.cards[0].stage_status == "ok"
    # Inject a probe_failed row
    fl._set_row_state(str(tmp_path / "bad.mf4"), "probe_failed")
    # The failure signal schedules the same debounced status refresh.
    qtbot.waitUntil(
        lambda: sheet.strip.cards[0].stage_status == "warn", timeout=1000,
    )
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


def test_rpm_picker_follows_the_same_policy_as_the_target_picker(qtbot):
    """A part-of-the-sources RPM channel is legitimate under per-source.

    ``BatchRunner._rpm_values`` resamples a cross-source RPM onto the target's
    time base with ``np.interp``, so pinning the RPM picker to unselectable
    contradicted the runner and left the row permanently grey.
    """
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel

    panel = InputPanel()
    qtbot.addWidget(panel)
    panel._file_list.add_loaded_file(0, "a.mf4", frozenset({"sig", "rpm_x"}))
    panel._file_list.add_loaded_file(1, "b.mf4", frozenset({"sig"}))

    assert panel.target_policy() == "common"
    assert panel._rpm_picker.is_disabled("rpm_x") is True
    assert panel._signal_picker.is_disabled("rpm_x") is True

    panel.apply_target_policy("available_per_source")

    assert panel._rpm_picker.is_disabled("rpm_x") is False
    assert panel._signal_picker.is_disabled("rpm_x") is False
    panel.apply_rpm_channel("rpm_x")
    assert panel.rpm_channel() == "rpm_x"


def test_relax_request_from_a_picker_switches_the_policy_once(qtbot):
    """The picker reports; the panel — which owns the state — decides."""
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel

    panel = InputPanel()
    qtbot.addWidget(panel)
    panel._file_list.add_loaded_file(0, "a.mf4", frozenset({"only_a"}))
    panel._file_list.add_loaded_file(1, "b.mf4", frozenset({"only_b"}))
    changes = []
    panel.changed.connect(lambda: changes.append(1))

    assert panel._signal_picker.is_relax_notice_visible() is True
    panel._signal_picker._relax_button.click()

    assert panel.target_policy() == "available_per_source"
    assert changes, "switching the policy must re-emit changed"
    assert panel._signal_picker.is_disabled("only_a") is False
    assert panel._signal_picker.is_relax_notice_visible() is False

    # Idempotent: a second request cannot flip the policy back or re-emit.
    before = len(changes)
    panel._on_relax_policy_requested()
    assert panel.target_policy() == "available_per_source"
    assert len(changes) == before


def test_rpm_picker_relax_request_reaches_the_same_handler(qtbot):
    """Both pickers share one policy, so either may raise the request."""
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel

    panel = InputPanel()
    qtbot.addWidget(panel)
    panel._file_list.add_loaded_file(0, "a.mf4", frozenset({"only_a"}))
    panel._file_list.add_loaded_file(1, "b.mf4", frozenset({"only_b"}))

    assert panel._rpm_picker.is_relax_notice_visible() is True
    panel._rpm_picker._relax_button.click()

    assert panel.target_policy() == "available_per_source"
    assert panel._rpm_picker.is_disabled("only_a") is False


def test_batch_rpm_coefficient_has_its_own_aligned_form_row(qtbot):
    """Order keeps the coefficient readable instead of squeezing it into RPM."""
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    sheet.resize(1080, 760)
    sheet.show()
    sheet.apply_method("order_time")
    qtbot.wait(20)

    panel = sheet._input_panel
    assert panel._target_stack.geometry().x() == panel._rpm_row_host.geometry().x()
    assert panel._rpm_factor_spin.isVisibleTo(sheet)
    assert not hasattr(panel, "_rpm_unit_combo")
    assert panel._rpm_factor_spin.geometry().x() == panel._target_stack.geometry().x()
    assert panel._rpm_factor_spin.geometry().y() > panel._rpm_row_host.geometry().y()
    assert panel._rpm_factor_spin.width() == panel._target_stack.width()
    assert panel._rpm_picker.width() == panel._target_stack.width()


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


def test_input_panel_rpm_factor_stays_explicit_when_channel_changes(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    p = InputPanel()
    qtbot.addWidget(p)
    p._rpm_factor_spin.setValue(0.42)
    p.apply_rpm_channel("speed_signal")
    assert p._rpm_factor_spin.value() == 0.42


def test_input_panel_rpm_row_hidden_for_fft_method(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    p = InputPanel()
    qtbot.addWidget(p)
    p.set_method("fft")
    assert p._rpm_row_host.isVisibleTo(p) is False
    assert p._rpm_label_widget.isVisibleTo(p) is False
    assert p._rpm_factor_spin.isVisibleTo(p) is False
    assert p._rpm_factor_label_widget.isVisibleTo(p) is False


def test_input_panel_rpm_row_visible_for_order_time(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    p = InputPanel()
    qtbot.addWidget(p)
    p.set_method("order_time")
    assert p._rpm_row_host.isVisibleTo(p) is True
    assert p._rpm_label_widget.isVisibleTo(p) is True
    assert p._rpm_factor_spin.isVisibleTo(p) is True
    assert p._rpm_factor_label_widget.isVisibleTo(p) is True


def test_input_panel_rpm_row_hidden_for_fft_time(qtbot):
    """fft_time uses RPM-free spectrogram analysis (Phase 5)."""
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    p = InputPanel()
    qtbot.addWidget(p)
    p.set_method("fft_time")
    assert p._rpm_row_host.isVisibleTo(p) is False
    assert p._rpm_factor_spin.isVisibleTo(p) is False


def test_batch_sheet_method_change_drives_rpm_visibility(qtbot):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    sheet.show()
    sheet.apply_method("fft")
    assert sheet._input_panel._rpm_row_host.isVisibleTo(sheet) is False
    assert sheet._input_panel._rpm_factor_spin.isVisibleTo(sheet) is False
    sheet.apply_method("order_time")
    assert sheet._input_panel._rpm_row_host.isVisibleTo(sheet) is True
    assert sheet._input_panel._rpm_factor_spin.isVisibleTo(sheet) is True


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
    sheet._input_panel._rpm_factor_spin.setValue(1.0 / 6.0)
    exported = sheet.get_preset()
    assert abs(exported.params["rpm_factor"] - 1.0 / 6.0) < 1e-9

    # Round-trip via apply_preset on a fresh sheet
    sheet2 = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet2)
    sheet2.apply_preset(exported)
    re_exported = sheet2.get_preset()
    assert abs(re_exported.params["rpm_factor"] - 1.0 / 6.0) < 1e-9


def test_batch_sheet_preserves_hidden_preset_params(qtbot):
    from mf4_analyzer.batch import AnalysisPreset
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    preset = AnalysisPreset.free_config(
        name="hidden",
        method="fft",
        target_signals=("sig",),
        params={
            "window": "hamming",
            "nfft": 2048,
            "weighting": "A",
            "db_reference": 2.5,
            "avg_mode": "rms",
            "avg_overlap": 0.25,
        },
    )
    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)

    sheet.apply_preset(preset)
    out = sheet.get_preset().params

    assert out["weighting"] == "A"
    assert out["db_reference"] == 2.5
    assert out["avg_mode"] == "rms"
    assert out["avg_overlap"] == 0.25


def test_batch_sheet_visible_params_override_passthrough(qtbot):
    from mf4_analyzer.batch import AnalysisPreset
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    preset = AnalysisPreset.free_config(
        name="override",
        method="fft",
        target_signals=("sig",),
        params={"window": "hanning", "nfft": 1024, "weighting": "A"},
    )
    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)

    sheet.apply_preset(preset)
    sheet.apply_params({"window": "blackman", "nfft": 4096})
    out = sheet.get_preset().params

    assert out["window"] == "blackman"
    assert out["nfft"] == 4096
    assert out["weighting"] == "A"


def test_batch_sheet_method_change_filters_irrelevant_passthrough(qtbot):
    from mf4_analyzer.batch import AnalysisPreset
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    preset = AnalysisPreset.free_config(
        name="fft hidden",
        method="fft",
        target_signals=("sig",),
        params={
            "window": "hanning",
            "nfft": 1024,
            "weighting": "A",
            "db_reference": 1.0,
            "avg_mode": "rms",
            "avg_overlap": 0.25,
        },
    )
    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)

    sheet.apply_preset(preset)
    sheet.apply_method("order_time")
    out = sheet.get_preset().params

    assert out["weighting"] == "A"
    assert out["db_reference"] == 1.0
    assert "avg_mode" not in out
    assert "avg_overlap" not in out


def test_input_panel_rpm_factor_is_returned_in_params(qtbot):
    """rpm_factor lives in params (existing key) so the BatchRunner
    backend (batch.py:506,516) keeps reading it unchanged.

    Tolerance note: ``QDoubleSpinBox.setDecimals(10)`` (mandated by
    rev-2 fix #3) clamps stored precision to 1e-10, so a literal
    ``params == {"rpm_factor": 1.0 / 6.0}`` cannot hold byte-for-byte
    when ``1/6`` has ~16 significant decimal digits. The contract is
    "≤ 1e-10 precision loss" — assert that, mirroring the tolerance
    used by the preset round-trip assertion above.
    """
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    p = InputPanel()
    qtbot.addWidget(p)
    p._rpm_factor_spin.setValue(1.0 / 6.0)
    params = p.rpm_params()
    assert set(params.keys()) == {"rpm_factor"}
    assert abs(params["rpm_factor"] - 1.0 / 6.0) < 1e-9


def test_batch_sheet_get_preset_includes_output_axis_params(qtbot):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    assert sheet._output_panel.combo_amp_unit.currentText() == "dB"
    # Per spec §1.4, switching ``combo_amp_unit`` resets ``z_auto`` and the
    # z-range spins to the new unit's defaults. To verify that the user's
    # *manual* axis-range entries round-trip into the preset, set the unit
    # FIRST, then enter manual ranges; otherwise the unit-toggle would wipe
    # the z-range we just typed in.
    sheet._output_panel.combo_amp_unit.setCurrentText("Linear")
    sheet._output_panel.chk_x_auto.setChecked(False)
    sheet._output_panel.spin_x_min.setValue(1.0)
    sheet._output_panel.spin_x_max.setValue(2.0)
    sheet._output_panel.chk_y_auto.setChecked(False)
    sheet._output_panel.spin_y_min.setValue(3.0)
    sheet._output_panel.spin_y_max.setValue(4.0)
    sheet._output_panel.chk_z_auto.setChecked(False)
    sheet._output_panel.spin_z_floor.setValue(-40.0)
    sheet._output_panel.spin_z_ceiling.setValue(-5.0)

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


def test_batch_order_time_defaults_use_single_order_z_range(qtbot):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)

    assert sheet._output_panel.chk_z_auto.isChecked() is True
    assert sheet._output_panel.spin_z_floor.value() == -80.0
    assert sheet._output_panel.spin_z_ceiling.value() == 0.0

    sheet.apply_method("order_time")
    params = sheet.get_preset().params

    assert sheet._output_panel.chk_z_auto.isChecked() is False
    assert sheet._output_panel.spin_z_floor.value() == -50.0
    assert sheet._output_panel.spin_z_ceiling.value() == -10.0
    assert params["z_auto"] is False
    assert params["z_floor"] == -50.0
    assert params["z_ceiling"] == -10.0
    assert params["amplitude_mode"] == "amplitude_db"


def test_batch_order_time_defaults_do_not_clobber_manual_z_range(qtbot):
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    sheet.apply_method("order_time")
    sheet._output_panel.chk_z_auto.setChecked(False)
    sheet._output_panel.spin_z_floor.setValue(-40.0)
    sheet._output_panel.spin_z_ceiling.setValue(-5.0)

    sheet.apply_method("fft_time")
    sheet.apply_method("order_time")

    assert sheet._output_panel.chk_z_auto.isChecked() is False
    assert sheet._output_panel.spin_z_floor.value() == -40.0
    assert sheet._output_panel.spin_z_ceiling.value() == -5.0


def test_batch_method_defaults_restore_generic_z_range_when_leaving_order(qtbot):
    from PyQt5.QtCore import Qt

    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    buttons = sheet._analysis_panel._method_group._buttons

    qtbot.mouseClick(buttons["order_time"], Qt.LeftButton)
    assert sheet._output_panel.chk_z_auto.isChecked() is False
    assert sheet._output_panel.spin_z_floor.value() == -50.0
    assert sheet._output_panel.spin_z_ceiling.value() == -10.0

    qtbot.mouseClick(buttons["fft"], Qt.LeftButton)

    assert sheet._output_panel.chk_z_auto.isChecked() is True
    assert sheet._output_panel.spin_z_floor.value() == -80.0
    assert sheet._output_panel.spin_z_ceiling.value() == 0.0


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


def test_frf_pair_editor_reuses_searchable_signal_pickers(qtbot):
    from mf4_analyzer.ui.drawers.batch.frf_pair_editor import FrfPairEditor
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    command = "Rte_ActRet_mActiveReturnMotorTorq4Check_xds16"
    response = "Rte_ESChkPlausi_mESMotorTorque_xds16"
    other = "Rte_MosfetTemperatureCalculation_cPCBTemp_xds16"
    editor = FrfPairEditor()
    qtbot.addWidget(editor)
    editor.set_channel_universe(
        (command, response, other), {}, policy="common", source_count=2,
    )
    editor.resize(288, 160)
    editor.show()
    qtbot.wait(20)

    group = editor._groups[0]
    assert isinstance(group.input_picker, SignalPickerPopup)
    assert isinstance(group.output_picker, SignalPickerPopup)
    assert group.input_picker.width() > 140
    assert group.output_picker.width() > 140

    group.input_picker.set_selected((command,))
    group.output_picker.set_selected((response, other))
    assert editor.rules()[0].input_channel == command
    assert editor.rules()[0].output_channels == (response, other)

    group.output_picker.show_popup()
    assert group.output_picker._popup.width() >= 420
    assert group.output_picker.label_for(response) == response


def test_batch_input_filter_params_round_trip(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel

    panel = InputPanel(None, files={})
    qtbot.addWidget(panel)
    params = {
        "enabled": True,
        "spec": {
            "kind": "band",
            "order": 6,
            "cutoff_lo": 20.0,
            "cutoff_hi": 80.0,
        },
        "show_original": False,
        "show_filtered": True,
    }

    panel.apply_filter_params(params)

    got = panel.filter_params()
    assert got["enabled"] is True
    assert got["spec"]["kind"] == "band"
    assert got["spec"]["order"] == 6
    assert got["spec"]["cutoff_lo"] == 20.0
    assert got["spec"]["cutoff_hi"] == 80.0
    assert got["show_original"] is False
    assert got["show_filtered"] is True


def test_batch_filter_row_uses_panel_style_switch(qtbot):
    from PyQt5.QtWidgets import QCheckBox

    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel
    from mf4_analyzer.ui.widgets.pill_switch import PillSwitch

    panel = InputPanel(None, files={})
    qtbot.addWidget(panel)

    label = panel._form_ref.labelForField(panel._filter_panel)
    assert label is None

    enabled_checks = [
        chk for chk in panel._filter_panel.findChildren(QCheckBox)
        if chk.text() == "启用滤波"
    ]
    assert enabled_checks == []

    assert isinstance(panel._filter_panel._enable_switch, PillSwitch)
    assert panel._filter_panel._enable_switch.accessibleName() == "滤波"

    panel.show()
    qtbot.wait(20)
    switch_top = panel._filter_panel._enable_switch.mapTo(
        panel._filter_panel, panel._filter_panel._enable_switch.rect().topLeft()
    ).y()
    summary_top = panel._filter_panel._summary_row.mapTo(
        panel._filter_panel, panel._filter_panel._summary_row.rect().topLeft()
    ).y()
    assert abs(summary_top - switch_top) <= 8
    assert panel._filter_panel._settings.isHidden() is True

    panel._filter_panel._enable_switch.setChecked(True)
    assert panel._filter_panel._settings.isVisibleTo(panel) is True


def test_batch_filter_time_output_toggles_only_visible_for_time(qtbot):
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel

    panel = InputPanel(None, files={})
    qtbot.addWidget(panel)

    panel.set_method("fft")
    assert panel._filter_panel.time_output_options_visible() is False

    panel.set_method("time")
    assert panel._filter_panel.time_output_options_visible() is False

    panel._filter_panel._enable_switch.setChecked(True)
    assert panel._filter_panel.time_output_options_visible() is True


def test_order_target_picker_does_not_reserve_hidden_frf_editor_height(qtbot):
    """阶次目标信号行只应占收起态 picker 的一行高度。"""
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel

    panel = InputPanel(None, files={})
    qtbot.addWidget(panel)
    panel.resize(560, 760)
    panel.show()
    panel.set_method("order_time")
    qtbot.wait(20)

    assert panel._signal_picker.isVisibleTo(panel) is True
    assert panel._frf_pair_editor.isVisibleTo(panel) is False
    assert panel._target_stack.height() == panel._signal_picker.height()
