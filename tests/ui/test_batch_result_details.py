"""Batch footer result-details overlay (plan T4 B1/B2)."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtWidgets import QApplication, QPushButton

from mf4_analyzer.batch import BatchItemResult, BatchRunResult, RenderGroupResult
from mf4_analyzer.ui.drawers.batch.result_details import (
    EMPTY_DETAIL_MESSAGE,
    BatchResultDetailsPanel,
    ResultDetailRow,
    format_row_clipboard,
    project_result_rows,
    result_has_detail_payload,
)
from mf4_analyzer.ui.drawers.batch.sheet import BatchSheet
from mf4_analyzer.ui_kit import load_stylesheet
from mf4_analyzer.ui_kit import dialog_geometry


def _item(**kwargs) -> BatchItemResult:
    values = dict(
        method="fft",
        file_id=0,
        file_name="a.mf4",
        signal="sig",
        status="done",
    )
    values.update(kwargs)
    return BatchItemResult(**values)


def _result(**kwargs) -> BatchRunResult:
    values = dict(status="done")
    values.update(kwargs)
    return BatchRunResult(**values)


def _silence_finish(monkeypatch, sheet) -> list:
    from mf4_analyzer.ui.drawers.batch import sheet as sheet_module

    monkeypatch.setattr(
        sheet_module.QMessageBox, "information", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        sheet_module.QMessageBox, "warning", lambda *a, **k: None,
    )
    opened = []
    monkeypatch.setattr(sheet, "_open_artifact_location", opened.append)
    return opened


def _finish(sheet, result) -> None:
    sheet._on_runner_finished_with_result(result)
    sheet._running = True
    sheet.lock_editing()
    sheet._on_thread_finished()


def _open_details(sheet) -> BatchResultDetailsPanel:
    assert sheet._btn_result_details.isEnabled()
    sheet._btn_result_details.click()
    panel = sheet._result_details
    assert panel.isVisibleTo(sheet)
    return panel


class TestProjectResultRows:
    def test_row_key_uses_generation_and_task_id(self):
        result = _result(items=[
            _item(task_id="t-a", file_id="id-a"),
            _item(task_id="t-b", file_id="id-b", file_name="a.mf4"),
        ])
        rows = project_result_rows(result, generation=4)
        assert rows[0].row_key == (4, "t-a")
        assert rows[1].row_key == (4, "t-b")
        assert rows[0].file_id == "id-a"
        assert rows[1].file_id == "id-b"

    def test_missing_task_id_uses_item_index_not_name(self):
        result = _result(items=[
            _item(task_id="", file_name="same.mf4", message="one"),
            _item(task_id="", file_name="same.mf4", message="two", file_id=1),
        ])
        rows = project_result_rows(result, generation=2)
        assert rows[0].row_key == (2, 0)
        assert rows[1].row_key == (2, 1)
        assert rows[0].message == "one"
        assert rows[1].message == "two"
        assert rows[0].file_id != rows[1].file_id

    def test_same_basename_different_file_id_stay_distinct(self):
        result = _result(items=[
            _item(
                task_id="left", file_id="src-1", file_name="same.mf4",
                status="failed", message="err-left",
            ),
            _item(
                task_id="right", file_id="src-2", file_name="same.mf4",
                status="done", message="ok-right",
            ),
        ])
        rows = project_result_rows(result, generation=1)
        assert len(rows) == 2
        assert {row.file_id for row in rows} == {"src-1", "src-2"}
        by_id = {row.file_id: row for row in rows}
        assert by_id["src-1"].message == "err-left"
        assert by_id["src-2"].message == "ok-right"

    def test_does_not_mutate_dto_and_row_is_frozen(self):
        item = _item(task_id="t", warnings=["keep"], message="orig")
        result = _result(items=[item])
        rows = project_result_rows(result, generation=0)
        item.warnings.append("extra")
        item.message = "changed"
        assert rows[0].warnings == ("keep",)
        assert rows[0].message == "orig"
        with pytest.raises(FrozenInstanceError):
            rows[0].status = "failed"

    def test_empty_message_uses_placeholder_unknown_status_kept(self):
        result = _result(items=[
            _item(task_id="t", status="weird-status", message=""),
        ])
        rows = project_result_rows(result, generation=1)
        assert rows[0].status == "weird-status"
        assert rows[0].message == EMPTY_DETAIL_MESSAGE

    def test_none_result_is_empty(self):
        assert project_result_rows(None, generation=9) == ()
        assert result_has_detail_payload(None) is False

    def test_zero_items_blocked_and_warnings_are_run_level(self):
        result = _result(
            status="blocked",
            items=[],
            blocked=["no output directory"],
            warnings=["backend missing"],
        )
        rows = project_result_rows(result, generation=5)
        assert len(rows) == 2
        assert all(row.file_name == "" for row in rows)
        assert {row.message for row in rows} == {
            "no output directory", "backend missing",
        }
        assert result_has_detail_payload(result) is True

    def test_render_group_failure_is_separate_and_not_index_paired(self):
        items = [
            _item(
                task_id="t1", file_id="f1", file_name="b.mf4",
                group_identity="g-b",
                image_path="/tmp/g-a.png",
                data_path="/tmp/b.csv",
            ),
            _item(
                task_id="t0", file_id="f0", file_name="a.mf4",
                group_identity="g-a",
                image_path="/tmp/g-a.png",
            ),
        ]
        groups = [
            RenderGroupResult(
                group_id="g-a", status="failed",
                image_path="/tmp/g-a.png",
                message="group image failed",
            ),
            RenderGroupResult(
                group_id="g-b", status="done",
                image_path="/tmp/g-b.png",
            ),
        ]
        rows = project_result_rows(
            _result(items=items, render_groups=groups), generation=7,
        )
        item_rows = [row for row in rows if len(row.row_key) == 2]
        group_rows = [row for row in rows if row.row_key[1:2] == ("group",)]
        assert [row.group_identity for row in item_rows] == ["g-b", "g-a"]
        assert all(row.image_path is None for row in item_rows)
        assert item_rows[0].data_path == "/tmp/b.csv"
        by_group = {row.group_identity: row for row in group_rows}
        assert by_group["g-a"].status == "failed"
        assert by_group["g-a"].image_path == "/tmp/g-a.png"
        assert by_group["g-a"].message == "group image failed"
        assert by_group["g-b"].status == "done"
        assert by_group["g-a"].row_key == (7, "group", "g-a")

    def test_cancelled_skipped_resumed_and_degraded_are_projected(self):
        result = _result(items=[
            _item(task_id="c", status="cancelled", message="batch cancelled"),
            _item(task_id="s", status="skipped", message="existing"),
            _item(task_id="r", status="resumed", message="checksum ok"),
            _item(
                task_id="d", status="done", message="",
                warnings=["axis rebuilt"],
                degraded_reason="image backend unavailable",
            ),
        ])
        rows = project_result_rows(result, generation=1)
        assert [row.status for row in rows] == [
            "cancelled", "skipped", "resumed", "done",
        ]
        degraded = rows[3]
        assert EMPTY_DETAIL_MESSAGE in degraded.message
        assert "axis rebuilt" in degraded.warnings
        assert "image backend unavailable" in degraded.warnings


def test_panel_default_selects_first_failed_then_skipped(qtbot):
    panel = BatchResultDetailsPanel()
    qtbot.addWidget(panel)
    panel.set_result(_result(items=[
        _item(task_id="ok", status="done", message="fine"),
        _item(task_id="skip", status="skipped", message="no pair"),
        _item(task_id="bad", status="failed", message="write failed"),
    ]), generation=1)
    selected = panel.selected_row()
    assert selected is not None
    assert selected.row_key[1] == "bad"
    assert "失败" in panel._status.text()
    assert panel._status.property("tone") == "error"
    assert "write failed" in panel._message.text()

    panel.set_result(_result(items=[
        _item(task_id="ok", status="done"),
        _item(task_id="skip", status="skipped", message="no pair"),
    ]), generation=2)
    assert panel.selected_row().row_key[1] == "skip"
    assert panel._status.property("tone") == "skip"
    assert "跳过" in panel._status.text()


def test_panel_copy_uses_clipboard_of_selected_row_only(qtbot):
    panel = BatchResultDetailsPanel()
    qtbot.addWidget(panel)
    panel.set_result(_result(items=[
        _item(
            task_id="a", status="failed", file_name="left.mf4",
            source_identity="src-a", input_signal="in", output_signal="out",
            message="boom-a", warnings=["w-a"],
        ),
        _item(task_id="b", status="done", file_name="right.mf4", message="ok-b"),
    ]), generation=1)
    QApplication.clipboard().setText("")
    panel._btn_copy.click()
    text = QApplication.clipboard().text()
    assert "boom-a" in text
    assert "src-a" in text
    assert "in" in text
    assert "out" in text
    assert "w-a" in text
    assert "ok-b" not in text
    assert "right.mf4" not in text


def test_format_row_clipboard_is_local_text_only():
    row = ResultDetailRow(
        row_key=(1, "t"),
        file_id="id",
        source_identity="src",
        file_name="a.mf4",
        method="frf",
        signal="out / in",
        input_signal="in",
        output_signal="out",
        status="failed",
        message="PermissionError: denied",
        warnings=("w1",),
        data_path=None,
        image_path=None,
        group_identity="",
    )
    text = format_row_clipboard(row)
    assert "PermissionError: denied" in text
    assert "http" not in text.lower()


class TestSheetResultDetails:
    def test_finished_callback_enables_entry_and_per_item_reasons(
        self, qtbot, monkeypatch,
    ):
        sheet = BatchSheet(None, files={})
        qtbot.addWidget(sheet)
        _silence_finish(monkeypatch, sheet)
        result = _result(
            status="partial",
            items=[
                _item(task_id="ok", status="done", message="wrote png"),
                _item(
                    task_id="bad", file_id=1, file_name="b.mf4",
                    status="failed", message="disk full",
                ),
            ],
        )
        _finish(sheet, result)
        assert not sheet._task_list.isVisible()
        assert sheet.layout().indexOf(sheet._task_list) == -1
        panel = _open_details(sheet)
        assert panel.selected_row().message == "disk full"
        panel._list.setCurrentRow(0)
        assert "wrote png" in panel._message.text()
        assert sheet._btn_result_details.text() == "查看详情"

    def test_none_result_does_not_keep_previous_rows(self, qtbot, monkeypatch):
        sheet = BatchSheet(None, files={})
        qtbot.addWidget(sheet)
        _silence_finish(monkeypatch, sheet)
        _finish(sheet, _result(items=[_item(task_id="t", message="old")]))
        _open_details(sheet)
        _finish(sheet, None)
        assert not sheet._btn_result_details.isEnabled()
        assert not sheet._result_details.isVisibleTo(sheet)
        assert sheet._result_details.rows() == ()

    def test_zero_items_blocked_enables_details(self, qtbot, monkeypatch):
        sheet = BatchSheet(None, files={})
        qtbot.addWidget(sheet)
        _silence_finish(monkeypatch, sheet)
        _finish(sheet, _result(
            status="blocked", items=[], blocked=["missing output dir"],
        ))
        panel = _open_details(sheet)
        assert "missing output dir" in panel._message.text()

    def test_new_run_start_hides_and_bumps_generation(
        self, qtbot, tmp_path, monkeypatch,
    ):
        from mf4_analyzer.batch import BatchOutputPreview, BatchRunner
        from mf4_analyzer.ui.drawers.batch.runner_thread import BatchRunnerThread

        monkeypatch.setattr(BatchRunnerThread, "start", lambda self, *a, **k: None)
        monkeypatch.setattr(
            BatchRunner, "preview_outputs",
            lambda *a, **k: BatchOutputPreview(
                task_count=1, artifact_count=0, conflict_count=0,
                image_format="png", image_width=1920, image_height=1080,
                image_dpi=144, conflict_policy="auto_number",
            ),
        )
        sheet = BatchSheet(None, files={})
        qtbot.addWidget(sheet)
        _silence_finish(monkeypatch, sheet)
        sheet._input_panel._file_list.add_loaded_file(
            "s1", "one.mf4", frozenset({"sig"}),
        )
        sheet.apply_signals(("sig",))
        sheet._output_panel.apply_directory(str(tmp_path))
        first = _result(items=[_item(task_id="old", message="first-run")])
        _finish(sheet, first)
        generation = sheet._result_generation
        _open_details(sheet)
        sheet._on_run_clicked()
        try:
            assert sheet._last_result is None
            assert sheet._result_generation == generation + 1
            assert not sheet._result_details.isVisibleTo(sheet)
            assert sheet._result_details.rows() == ()
            assert not sheet._btn_result_details.isEnabled()
            second = _result(items=[_item(task_id="new", message="second-run")])
            _finish(sheet, second)
            panel = _open_details(sheet)
            assert "second-run" in panel._message.text()
            assert "first-run" not in panel._message.text()
            assert panel.rows()[0].row_key[0] == sheet._result_generation
        finally:
            if sheet._running:
                sheet.unlock_editing()

    def test_config_edit_labels_previous_and_blocked_run_keeps_it(
        self, qtbot, tmp_path, monkeypatch,
    ):
        sheet = BatchSheet(None, files={})
        qtbot.addWidget(sheet)
        _silence_finish(monkeypatch, sheet)
        sheet._input_panel._file_list.add_loaded_file(
            "s1", "one.mf4", frozenset({"sig"}),
        )
        sheet.apply_signals(("sig",))
        sheet._output_panel.apply_directory(str(tmp_path))
        result = _result(items=[_item(task_id="t", message="keep-me")])
        _finish(sheet, result)
        panel = _open_details(sheet)
        assert panel.caption_text() == "本次运行结果"
        sheet.apply_method("fft")
        assert panel.caption_text() == "上次运行结果"
        sheet.apply_signals(())
        assert not sheet.is_runnable()
        sheet._on_run_clicked()
        assert sheet._last_result is result
        assert "keep-me" in panel._message.text()
        assert panel.caption_text() == "上次运行结果"

    def test_no_streaming_details_during_run(self, qtbot, monkeypatch):
        from mf4_analyzer.batch import BatchProgressEvent

        sheet = BatchSheet(None, files={})
        qtbot.addWidget(sheet)
        _silence_finish(monkeypatch, sheet)
        sheet._running = True
        sheet.lock_editing()
        try:
            sheet._on_runner_progress(BatchProgressEvent(
                kind="task_failed", task_index=1, total=1, error="mid-run",
            ))
            assert not sheet._btn_result_details.isEnabled()
            assert not sheet._result_details.isVisibleTo(sheet)
        finally:
            sheet.unlock_editing()

    def test_deleted_artifact_toasts_and_does_not_open(
        self, qtbot, tmp_path, monkeypatch,
    ):
        sheet = BatchSheet(None, files={})
        qtbot.addWidget(sheet)
        opened = _silence_finish(monkeypatch, sheet)
        artifact = tmp_path / "out.png"
        artifact.write_bytes(b"png")
        _finish(sheet, _result(items=[
            _item(task_id="t", image_path=str(artifact), message="ok"),
        ]))
        panel = _open_details(sheet)
        assert panel._btn_image.isVisibleTo(panel)
        artifact.unlink()
        panel._btn_image.click()
        assert opened == []
        assert "文件已移动或删除" in sheet._last_toast_text

    def test_artifact_button_only_for_paths_in_this_result(
        self, qtbot, tmp_path, monkeypatch,
    ):
        sheet = BatchSheet(None, files={})
        qtbot.addWidget(sheet)
        opened = _silence_finish(monkeypatch, sheet)
        data = tmp_path / "a.csv"
        data.write_text("x")
        _finish(sheet, _result(items=[
            _item(task_id="t", data_path=str(data), image_path=None),
        ]))
        panel = _open_details(sheet)
        assert panel._btn_data.isVisibleTo(panel)
        assert not panel._btn_image.isVisibleTo(panel)
        panel._btn_data.click()
        assert opened == [str(data)]

    def test_permission_error_is_not_classified(self, qtbot, monkeypatch):
        sheet = BatchSheet(None, files={})
        qtbot.addWidget(sheet)
        _silence_finish(monkeypatch, sheet)
        _finish(sheet, _result(items=[
            _item(
                task_id="t", status="failed",
                message="PermissionError: [Errno 13] denied",
            ),
        ]))
        panel = _open_details(sheet)
        assert panel._btn_output.isVisibleTo(panel)
        assert panel._btn_output.text() == "查看输出目录设置"
        texts = [btn.text() for btn in panel.findChildren(QPushButton)]
        assert not any("权限" in text for text in texts)
        assert not any("重试" in text or "重跑" in text for text in texts)

    def test_frf_locate_disabled_after_method_switch(
        self, qtbot, monkeypatch,
    ):
        sheet = BatchSheet(None, files={})
        qtbot.addWidget(sheet)
        _silence_finish(monkeypatch, sheet)
        sheet._input_panel._file_list.add_loaded_file(
            "s1", "one.mf4", frozenset({"in", "out"}),
        )
        sheet.apply_method("frf")
        sheet._input_panel._frf_pair_editor.set_group_values(0, "in", ("out",))
        _finish(sheet, _result(items=[
            _item(
                method="frf", task_id="t", status="skipped",
                input_signal="in", output_signal="out",
                message="来源 's2' 的 FRF pair input='in', output='out' 缺少通道 in",
            ),
        ]))
        locate_kind = sheet._locate_kind
        panel = _open_details(sheet)
        assert panel._btn_frf.isVisibleTo(panel)
        assert panel._btn_frf.isEnabled()
        assert panel._btn_frf.text() == "检查信号配对"
        panel._btn_frf.click()
        assert sheet._locate_kind == locate_kind
        sheet.apply_method("time")
        assert not panel._btn_frf.isEnabled()
        assert "方法" in panel._frf_reason.text()

    def test_escape_closes_details_not_sheet(self, qtbot, monkeypatch):
        sheet = BatchSheet(None, files={})
        qtbot.addWidget(sheet)
        sheet.show()
        _silence_finish(monkeypatch, sheet)
        _finish(sheet, _result(items=[_item(task_id="t", message="reason")]))
        panel = _open_details(sheet)
        qtbot.keyClick(sheet, Qt.Key_Escape)
        assert not panel.isVisibleTo(sheet)
        assert sheet.isVisible()
        assert sheet.focusWidget() is sheet._btn_result_details
        qtbot.keyClick(sheet, Qt.Key_Escape)
        qtbot.wait(20)
        assert not sheet.isVisible()

    def test_long_diagnostics_wrap_and_keep_actions(
        self, qapp, qtbot, monkeypatch,
    ):
        monkeypatch.setattr(
            dialog_geometry, "resolve_available_rect",
            lambda **kwargs: dialog_geometry.IntRect(0, 0, 1920, 1080),
        )
        old = qapp.styleSheet()
        try:
            load_stylesheet(qapp)
            sheet = BatchSheet(None, files={})
            qtbot.addWidget(sheet)
            _silence_finish(monkeypatch, sheet)
            sheet.resize(1080, 760)
            sheet.show()
            qtbot.wait(20)
            message = "诊断：" + ("很长的原因，" * 80)
            _finish(sheet, _result(items=[
                _item(task_id="t", status="failed", message=message),
            ]))
            panel = _open_details(sheet)
            qtbot.wait(20)
            assert panel._message.wordWrap()
            assert panel._message.heightForWidth(panel._message.width()) >= 32
            action_br = panel._actions.mapTo(
                panel, panel._actions.rect().bottomRight(),
            )
            assert panel.rect().contains(action_br)
            assert panel._btn_copy.isVisibleTo(panel)
            assert panel._btn_copy.height() >= panel._btn_copy.minimumSizeHint().height()
            assert sheet._footer_host.height() == 50
        finally:
            sheet.close()
            qapp.setStyleSheet(old)

    def test_1080x760_overlay_keeps_footer_and_columns(
        self, qapp, qtbot, monkeypatch,
    ):
        monkeypatch.setattr(
            dialog_geometry, "resolve_available_rect",
            lambda **kwargs: dialog_geometry.IntRect(0, 0, 1920, 1080),
        )
        old = qapp.styleSheet()
        try:
            load_stylesheet(qapp)
            sheet = BatchSheet(None, files={})
            qtbot.addWidget(sheet)
            _silence_finish(monkeypatch, sheet)
            sheet.resize(1080, 760)
            sheet.show()
            qtbot.wait(20)
            widths = (
                sheet._input_scroll.width(),
                sheet._analysis_scroll.width(),
                sheet._output_scroll.width(),
            )
            _finish(sheet, _result(items=[
                _item(task_id="t", status="failed", message="x"),
            ]))
            panel = _open_details(sheet)
            qtbot.wait(20)
            assert sheet.width() == 1080
            assert sheet.height() <= 760
            assert sheet._footer_host.height() == 50
            assert not sheet._task_list.isVisible()
            work_h = sheet._detail_host.height()
            assert panel.height() == min(240, int(work_h * 0.45))
            assert panel.geometry().y() + panel.height() == sheet._footer_host.geometry().y()
            assert panel.width() == sheet.width()
            assert (
                sheet._input_scroll.width(),
                sheet._analysis_scroll.width(),
                sheet._output_scroll.width(),
            ) == widths
            available = sum(widths)
            expected = (0.29, 0.39, 0.32)
            for width, ratio in zip(widths, expected):
                assert abs(width - available * ratio) <= 6
            assert panel._splitter.orientation() == Qt.Horizontal
            sheet.resize(640, 760)
            qtbot.wait(20)
            assert panel._splitter.orientation() == Qt.Vertical
            list_bottom = panel._list.mapTo(
                panel, panel._list.rect().bottomLeft(),
            ).y()
            body_top = panel._body_host.mapTo(
                panel, QPoint(0, 0),
            ).y()
            assert list_bottom <= body_top + 4
        finally:
            sheet.close()
            qapp.setStyleSheet(old)

    def test_close_drops_callbacks(self, qtbot, monkeypatch):
        from PyQt5 import sip

        sheet = BatchSheet(None, files={})
        qtbot.addWidget(sheet)
        _silence_finish(monkeypatch, sheet)
        _finish(sheet, _result(items=[_item(task_id="t")]))
        panel = sheet._result_details
        sheet.close()
        if not sip.isdeleted(panel):
            assert panel.rows() == ()
