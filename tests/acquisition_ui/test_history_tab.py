"""Standalone HistoryTab tests for the Acquisition Cockpit polish wave."""

from __future__ import annotations

import json
from pathlib import Path

from PyQt5.QtCore import QItemSelectionModel, Qt
from PyQt5.QtWidgets import QLabel

from mf4_analyzer.acquisition_ui.history_tab import HistoryTab


def _write_manifest(tmp_path: Path, entries: list[dict]) -> Path:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({"version": 1, "entries": entries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path


def _base_entries() -> list[dict]:
    return [
        {
            "id": "rec_a",
            "path": "files/rec_a.mf4",
            "sets": ["dev", "hot"],
            "path_kind": "local",
            "vehicle": "CarA",
            "platform": "P1",
            "scenario": "urban",
            "issue_tags": ["drop"],
            "required": False,
        },
        {
            "id": "rec_b",
            "path": "files/rec_b.mf4",
            "sets": ["dev"],
            "path_kind": "local",
            "vehicle": "CarB",
            "platform": "P2",
            "scenario": "rural",
            "required": False,
        },
        {
            "id": "rec_c",
            "path": "files/rec_c.mf4",
            "sets": ["qa"],
            "path_kind": "lfs",
            "vehicle": "CarA",
            "platform": "P1",
            "scenario": "dyno",
            "issue_tags": ["xcp"],
            "required": False,
        },
    ]


def _prepare_manifest(tmp_path: Path) -> Path:
    files_dir = tmp_path / "files"
    files_dir.mkdir()
    (files_dir / "rec_a.mf4").write_bytes(b"a" * 128)
    (files_dir / "rec_b.mf4").write_bytes(b"b" * 256)
    (files_dir / "rec_c.mf4").write_bytes(b"c" * 64)
    return _write_manifest(tmp_path, _base_entries())


def _cell(tab: HistoryTab, row: int, column: int) -> str:
    model = tab.table_view.model()
    return str(model.data(model.index(row, column)))


def _row_for_id(tab: HistoryTab, entry_id: str) -> int:
    model = tab.table_view.model()
    for row in range(model.rowCount()):
        if _cell(tab, row, 0) == entry_id:
            return row
    raise AssertionError(f"row not found for {entry_id!r}")


def test_history_tab_loads_manifest(qapp, tmp_path):
    manifest_path = _prepare_manifest(tmp_path)

    tab = HistoryTab(manifest_path=manifest_path, resolve_async=False)
    try:
        model = tab.table_view.model()
        assert model.rowCount() == 3
        assert [_cell(tab, row, 0) for row in range(model.rowCount())] == [
            "rec_c",
            "rec_b",
            "rec_a",
        ]
        headers = [
            model.headerData(col, Qt.Horizontal)
            for col in range(model.columnCount())
        ]
        assert "vehicle" in headers
        vehicle_values = {
            tab.vehicle_filter.itemText(i) for i in range(tab.vehicle_filter.count())
        }
        assert vehicle_values >= {
            "全部",
            "CarA",
            "CarB",
        }
        statuses = {_cell(tab, row, 8) for row in range(model.rowCount())}
        assert statuses == {"本地", "LFS"}
    finally:
        tab.close()


def test_history_tab_double_click_opens_in_analyzer(qapp, tmp_path):
    manifest_path = _prepare_manifest(tmp_path)
    tab = HistoryTab(manifest_path=manifest_path, resolve_async=False)
    opened: list[str] = []
    tab.analyzer_open_requested.connect(opened.append)
    try:
        row = _row_for_id(tab, "rec_a")
        index = tab.table_view.model().index(row, 0)

        tab.table_view.doubleClicked.emit(index)
        qapp.processEvents()

        assert opened == [str((tmp_path / "files" / "rec_a.mf4").resolve())]
    finally:
        tab.close()


def test_history_tab_context_menu_open_emits_analyzer_request(qapp, tmp_path):
    manifest_path = _prepare_manifest(tmp_path)
    tab = HistoryTab(manifest_path=manifest_path, resolve_async=False)
    opened: list[str] = []
    tab.analyzer_open_requested.connect(opened.append)
    try:
        row = _row_for_id(tab, "rec_b")
        index = tab.table_view.model().index(row, 0)
        tab.table_view.setCurrentIndex(index)
        tab.table_view.selectionModel().select(index, QItemSelectionModel.Rows)

        assert tab.open_current_entry() is True

        assert opened == [str((tmp_path / "files" / "rec_b.mf4").resolve())]
    finally:
        tab.close()


def test_history_tab_filter_by_vehicle(qapp, tmp_path):
    manifest_path = _prepare_manifest(tmp_path)
    tab = HistoryTab(manifest_path=manifest_path, resolve_async=False)
    try:
        tab.vehicle_filter.setCurrentText("CarA")
        qapp.processEvents()

        model = tab.table_view.model()
        assert model.rowCount() == 2
        assert {_cell(tab, row, 1) for row in range(model.rowCount())} == {"CarA"}
    finally:
        tab.close()


def test_history_tab_default_async_resolution_completes(qapp, tmp_path):
    manifest_path = _prepare_manifest(tmp_path)

    tab = HistoryTab(manifest_path=manifest_path)
    try:
        assert tab.wait_for_resolutions(timeout_ms=1000) is True
        model = tab.table_view.model()
        assert {_cell(tab, row, 8) for row in range(model.rowCount())} == {
            "本地",
            "LFS",
        }
    finally:
        tab.close()


def test_history_tab_missing_path_is_not_fatal(qapp, tmp_path):
    manifest_path = _write_manifest(
        tmp_path,
        [
            {
                "id": "missing_local",
                "path": "files/does_not_exist.mf4",
                "sets": ["dev"],
                "path_kind": "local",
                "vehicle": "CarA",
                "required": False,
            }
        ],
    )

    tab = HistoryTab(manifest_path=manifest_path, resolve_async=False)
    opened: list[str] = []
    tab.analyzer_open_requested.connect(opened.append)
    try:
        assert tab.table_view.model().rowCount() == 1
        assert _cell(tab, 0, 8) == "缺失"
        assert _cell(tab, 0, 7) == "n/a"

        index = tab.table_view.model().index(0, 0)
        tab.table_view.doubleClicked.emit(index)
        qapp.processEvents()

        assert opened == []
    finally:
        tab.close()


def test_history_tab_missing_manifest_shows_empty_state(qapp, tmp_path):
    tab = HistoryTab(
        manifest_path=tmp_path / "missing_manifest.json",
        resolve_async=False,
    )
    try:
        assert tab.table_view.model().rowCount() == 0
        assert tab.empty_label.text() == "未找到 manifest"
        assert tab.open_current_entry() is False
    finally:
        tab.close()


def test_filter_labels_are_localized(qtbot):
    tab = HistoryTab()
    qtbot.addWidget(tab)
    labels = [lab.text() for lab in tab.findChildren(QLabel)]
    for cn in ("车辆", "场景", "存储", "数据集"):
        assert cn in labels
    for en in ("vehicle", "scenario", "path_kind", "set"):
        assert en not in labels


def test_issue_tags_bar_hidden_when_no_tags(qtbot):
    tab = HistoryTab()
    qtbot.addWidget(tab)
    assert not tab._tag_bar.isVisible()
