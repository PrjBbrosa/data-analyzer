from __future__ import annotations


def _editor(qtbot):
    from mf4_analyzer.ui.drawers.batch.frf_pair_editor import FrfPairEditor

    editor = FrfPairEditor()
    qtbot.addWidget(editor)
    editor.set_channel_universe(
        ("Force", "Acceleration"),
        {"Angle": "(1/2)"},
        policy="available_per_source",
        source_count=2,
    )
    return editor


def test_pair_editor_emits_immutable_one_input_multi_output_rules(qtbot):
    from mf4_analyzer.batch_types import FrfPairRule

    editor = _editor(qtbot)
    editor.set_group_values(0, "Force", ("Acceleration", "Angle"))

    assert editor.rules() == (
        FrfPairRule("Force", ("Acceleration", "Angle")),
    )
    assert editor.validation_message() == ""
    assert "2" in editor.task_summary_text()


def test_pair_editor_blocks_self_duplicate_empty_and_supports_groups(qtbot):
    editor = _editor(qtbot)
    editor.set_group_values(0, "Force", ("Force",))
    assert "不能相同" in editor.validation_message()
    assert editor.rules() == ()

    editor.set_group_values(0, "Force", ("Acceleration",))
    editor.add_group()
    editor.set_group_values(1, "Force", ("Acceleration",))
    assert "重复" in editor.validation_message()

    editor.set_group_values(1, "Angle", ())
    assert "至少选择一个输出" in editor.validation_message()
    editor.remove_group(1)
    assert editor.group_count() == 1
    assert editor.validation_message() == ""


def test_pair_editor_hides_duplicate_invalid_summary(qtbot):
    editor = _editor(qtbot)
    editor.resize(480, 300)
    editor.show()
    qtbot.waitExposed(editor)

    assert editor._validation.text() == "配对组 1：请选择输入"
    assert editor._task_summary.isHidden()


def test_input_panel_aligns_frf_pair_label_with_target_policy(qtbot):
    """Form label shares the policy column and centers on the pair header."""
    from PyQt5.QtCore import QPoint
    from PyQt5.QtGui import QFontMetrics
    from PyQt5.QtWidgets import QLabel

    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel

    panel = InputPanel()
    qtbot.addWidget(panel)
    panel._file_list.add_loaded_file(
        ("file-a", "group-1"), "a.mf4 · group-1",
        frozenset({"Force", "Acceleration"}),
    )
    panel.set_method("frf")
    panel.resize(600, 900)
    panel.show()
    qtbot.waitExposed(panel)
    qtbot.wait(20)

    policy_label = panel._form_ref.labelForField(panel._target_policy_choice)
    pair_label = panel._target_signal_label
    group_title = panel._frf_pair_editor._groups[0].title

    assert isinstance(policy_label, QLabel)
    assert pair_label.mapTo(panel, QPoint(0, 0)).x() == policy_label.mapTo(panel, QPoint(0, 0)).x()
    # "配对组 N" sits in a taller header row with the delete button; center
    # the form label on that row instead of the card's outer top edge.
    pair_text_mid = (
        pair_label.mapTo(panel, QPoint(0, 0)).y()
        + pair_label.contentsMargins().top()
        + QFontMetrics(pair_label.font()).height() / 2
    )
    header_mid = (
        group_title.mapTo(panel, QPoint(0, 0)).y() + group_title.height() / 2
    )
    assert abs(pair_text_mid - header_mid) <= 1


def test_pair_labels_do_not_replace_source_group_runtime_identity(qtbot):
    """Portable labels stay names; neutral resolution binds composite sources."""
    from mf4_analyzer.batch_frf import resolve_frf_tasks

    editor = _editor(qtbot)
    editor.set_group_values(0, "Force", ("Acceleration",))
    plan = resolve_frf_tasks(editor.rules(), (
        {
            "source_id": "source-a", "group_identity": "group-1",
            "display_name": "same readable label",
            "channel_names": ("Force", "Acceleration"),
        },
        {
            "source_id": "source-b", "group_identity": "group-2",
            "display_name": "same readable label",
            "channel_names": ("Force", "Acceleration"),
        },
    ))

    assert tuple(
        (task.source_id, task.group_identity) for task in plan.tasks
    ) == (("source-a", "group-1"), ("source-b", "group-2"))


def test_input_panel_switches_pair_editor_without_losing_rules(qtbot):
    from mf4_analyzer.batch_types import FrfPairRule
    from mf4_analyzer.ui.drawers.batch.input_panel import InputPanel

    panel = InputPanel()
    qtbot.addWidget(panel)
    panel._file_list.add_loaded_file(
        ("file-a", "group-1"), "a.mf4 · group-1",
        frozenset({"Force", "Acceleration"}),
    )
    panel.set_method("frf")
    target_row, _role = panel._form_ref.getWidgetPosition(panel._target_stack)
    row_count = panel._form_ref.rowCount()
    panel._frf_pair_editor.set_group_values(0, "Force", ("Acceleration",))
    assert panel.frf_pair_rules() == (
        FrfPairRule("Force", ("Acceleration",)),
    )
    assert panel._signal_picker.isHidden()
    assert not panel._frf_pair_editor.isHidden()
    assert panel._form_ref.rowCount() == row_count
    assert panel._form_ref.getWidgetPosition(panel._target_stack)[0] == target_row
    panel.resize(288, 760)
    panel.show()
    qtbot.wait(20)
    assert panel._target_stack.width() > 0
    assert panel._target_stack.geometry().right() <= panel.contentsRect().right()

    panel.set_method("fft")
    panel.set_method("frf")
    assert panel.frf_pair_rules() == (
        FrfPairRule("Force", ("Acceleration",)),
    )
    assert panel._form_ref.rowCount() == row_count


def test_batch_sheet_frf_rules_round_trip_and_invalid_pair_maps_to_input(qtbot):
    from mf4_analyzer.batch_types import AnalysisPreset, FrfPairRule
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    sheet._input_panel._file_list.add_loaded_file(
        "source-a", "a.mf4", frozenset({"Force", "Acceleration"}),
    )
    sheet.apply_preset(AnalysisPreset.free_config(
        "frf", "frf", params={"render_group_by": "channel"},
        frf_pair_rules=(FrfPairRule("Force", ("Acceleration",)),),
    ))
    exported = sheet.get_preset()
    assert exported.frf_pair_rules == (
        FrfPairRule("Force", ("Acceleration",)),
    )
    assert exported.target_signals == ()
    assert sheet._analysis_panel._frf_grouping_combo.currentData() == "channel"
    assert exported.params["render_group_by"] == "channel"

    sheet._input_panel._frf_pair_editor.set_group_values(
        0, "Force", ("Force",),
    )
    issues = sheet.preflight_issues()
    assert issues[0].field == "frf_pair_rules"
    sheet._recompute_pipeline_status()
    assert sheet.strip.cards[0].stage_status == "warn"
    assert "输入" in sheet.strip.cards[0].summary_label.text()


def test_batch_sheet_narrow_frf_pair_editor_keeps_nonzero_field_geometry(qtbot):
    from PyQt5.QtWidgets import QSizePolicy
    from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet

    sheet = BatchSheet(parent=None, files={}, current_preset=None)
    qtbot.addWidget(sheet)
    sheet.resize(1040, 760)
    sheet.apply_method("frf")
    sheet.show()
    qtbot.wait(20)

    stack = sheet._input_panel._target_stack
    assert stack.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    assert stack.isVisibleTo(sheet)
    assert stack.width() >= 160
    assert sheet._input_panel._frf_pair_editor.width() == stack.width()
