import pytest

from PyQt5.QtCore import Qt, QVariant
from PyQt5.QtWidgets import QStyleOptionViewItem
from mf4_analyzer.ui_kit.widgets.searchable_combo import (
    SearchableComboBox,
    _highlight_char_indexes,
)


def test_basic_construction(qapp):
    cb = SearchableComboBox()
    cb.addItems(["Speed", "Torque", "Rte_RPS_nRotorSpeed_xds16"])
    assert cb.count() == 3
    assert cb.isEditable()
    assert cb.completer() is not None


def test_completer_is_substring_caseinsensitive(qapp):
    cb = SearchableComboBox()
    cb.addItems(["Rte_TAS_mTorsionBarTorque_xds16",
                 "Rte_RPS_nRotorSpeed_xds16",
                 "Speed_command"])
    comp = cb.completer()
    assert comp.filterMode() == Qt.MatchContains
    assert comp.caseSensitivity() == Qt.CaseInsensitive


def test_completer_model_rebinds_after_addItems(qapp):
    cb = SearchableComboBox()
    cb.addItems(["A", "B"])
    first_model = cb.completer().model()
    cb.clear()
    cb.addItems(["C", "D", "E"])
    assert cb.count() == 3
    assert cb.completer().model() is not None
    assert cb._proxy_model.sourceModel() is cb.model()
    assert first_model is not None  # original kept alive but unused


def test_candidate_rows_use_full_metadata_and_batch_syncs_once(qapp, monkeypatch):
    """Candidate no-ops require every rendered role to agree.

    The batch remains transparent to Qt's model signals, but its expensive
    completer/popup synchronization is deferred to the outermost exit.
    """
    cb = SearchableComboBox()
    rows = [
        ("[one] speed", ("file-1", "speed")),
        ("[one] torque", ("file-1", "torque")),
    ]
    sync_calls = []
    real_sync = cb._sync_popup_geometry
    monkeypatch.setattr(
        cb, "_sync_popup_geometry", lambda: sync_calls.append("sync"),
    )

    emitted_rows = []
    cb.model().rowsInserted.connect(
        lambda _parent, first, last: emitted_rows.append((first, last))
    )
    assert cb.replace_candidate_rows(rows) is True
    assert emitted_rows == [(0, 0), (1, 1)]
    assert sync_calls == ["sync"]

    sync_calls.clear()
    assert cb.replace_candidate_rows(rows) is False
    assert sync_calls == []

    assert not cb.candidate_rows_match([
        ("[renamed] speed", ("file-1", "speed")),
        rows[1],
    ])
    assert not cb.candidate_rows_match([
        (rows[0][0], ("file-2", "speed")),
        rows[1],
    ])

    cb.setItemData(0, "stale tooltip", Qt.ToolTipRole)
    assert cb.replace_candidate_rows(rows) is True
    assert cb.itemData(0, Qt.ToolTipRole) == rows[0][0]
    assert sync_calls == ["sync"]

    # The display text, identity and tooltip now agree, but a non-default
    # role does not: this must rebuild instead of treating a stale row as
    # equivalent.
    sync_calls.clear()
    cb.setItemData(0, "stale detail", Qt.WhatsThisRole)
    assert cb.replace_candidate_rows(rows) is True
    assert cb.itemData(0, Qt.WhatsThisRole) is None
    assert sync_calls == ["sync"]
    monkeypatch.setattr(cb, "_sync_popup_geometry", real_sync)


def test_candidate_none_placeholder_matches_qt_storage_and_rebuilds_only_on_real_changes(
    qapp,
):
    """None placeholders are an invalid QVariant, not a stored UserRole."""
    cb = SearchableComboBox()
    rows = (
        ("请选择通道", None),
        ("[source-a] signal", ("file-a", "signal")),
        ("[source-a] rpm", ("file-a", "rpm")),
    )
    inserted = []
    removed = []

    def record_insert(_parent, first, last):
        inserted.append((first, last))

    def record_remove(_parent, first, last):
        removed.append((first, last))

    cb.model().rowsInserted.connect(record_insert)
    cb.model().rowsRemoved.connect(record_remove)

    assert cb.replace_candidate_rows(rows) is True
    assert cb.itemData(0, Qt.UserRole) is None
    assert int(Qt.UserRole) not in cb.model().itemData(cb.model().index(0, 0))

    inserted.clear()
    removed.clear()
    cb.setCurrentIndex(1)
    assert cb.replace_candidate_rows(rows) is False
    assert inserted == []
    assert removed == []
    assert cb.currentData() == ("file-a", "signal")

    def assert_one_rebuild(changed_rows):
        before_inserted = len(inserted)
        before_removed = len(removed)
        assert cb.replace_candidate_rows(changed_rows) is True
        assert len(inserted) > before_inserted
        assert len(removed) > before_removed
        after_inserted = len(inserted)
        after_removed = len(removed)
        assert cb.replace_candidate_rows(changed_rows) is False
        assert len(inserted) == after_inserted
        assert len(removed) == after_removed

    # Composite source identity and candidate order are both part of the
    # rendered row contract, despite the unchanged display label.
    source_changed = (
        rows[0],
        ("[source-a] signal", ("file-b", "signal")),
        rows[2],
    )
    assert_one_rebuild(source_changed)
    assert_one_rebuild((source_changed[0], source_changed[2], source_changed[1]))

    # An actually stored, extra role is still a real difference and must not
    # be hidden by the None-placeholder normalization.
    cb.setItemData(1, "stale detail", Qt.WhatsThisRole)
    assert_one_rebuild((source_changed[0], source_changed[2], source_changed[1]))
    assert cb.itemData(1, Qt.WhatsThisRole) is None

    # Empty display labels still have DisplayRole, but Qt does not retain the
    # empty tooltip written by the normal addItem path.
    empty_label = SearchableComboBox()
    empty_rows = (("", ("file-empty", "signal")),)
    assert empty_label.replace_candidate_rows(empty_rows) is True
    assert int(Qt.ToolTipRole) not in empty_label.model().itemData(
        empty_label.model().index(0, 0)
    )
    assert empty_label.replace_candidate_rows(empty_rows) is False

    invalid_variant = SearchableComboBox()
    invalid_rows = (("invalid QVariant", QVariant()),)
    assert invalid_variant.replace_candidate_rows(invalid_rows) is True
    assert int(Qt.UserRole) not in invalid_variant.model().itemData(
        invalid_variant.model().index(0, 0)
    )
    assert invalid_variant.replace_candidate_rows(invalid_rows) is False


def test_nested_candidate_batch_rebinds_after_exception_without_swallowing(qapp):
    cb = SearchableComboBox()
    with pytest.raises(RuntimeError, match="model failure"):
        with cb.candidate_batch():
            cb.clear()
            with cb.candidate_batch():
                cb.addItem("speed", ("file-1", "speed"))
            raise RuntimeError("model failure")

    assert cb._proxy_model.sourceModel() is cb.model()
    assert cb.completer().model() is cb._proxy_model


def test_currentIndexChanged_signal_still_fires(qapp, qtbot):
    cb = SearchableComboBox()
    cb.addItems(["A", "B", "C"])
    captured = []
    cb.currentIndexChanged.connect(lambda i: captured.append(i))
    cb.setCurrentIndex(2)
    assert captured == [2]


def test_drop_in_compatible_setCurrentText(qapp):
    cb = SearchableComboBox()
    cb.addItems(["alpha", "beta", "gamma"])
    cb.setCurrentText("beta")
    assert cb.currentText() == "beta"
    assert cb.currentIndex() == 1


def test_fuzzy_completer_tokenizes_query_and_ignores_separators(qapp):
    cb = SearchableComboBox()
    target = "[T08_YuanDi_FOC_Cur] Rte_TAS_mTorsionWheel_Nm"
    cb.addItems([
        target,
        "[T08_YuanDi_FOC_Cur] Rte_RPS_nRotorSpeed_xds16",
        "[Recorder_2026-04-2] AppCtrl_ES_DistanceRollingCounter_u16",
    ])

    cb.lineEdit().setText("tas torsion")

    model = cb.completer().model()
    matches = [
        model.index(row, 0).data(Qt.DisplayRole)
        for row in range(model.rowCount())
    ]
    assert target in matches
    assert all("RotorSpeed" not in str(match) for match in matches)


def test_fuzzy_match_tokens_are_colored_in_delegate_runs(qapp):
    text = "Rte_TAS_mTorsionBarTorque_xds16"
    highlighted = _highlight_char_indexes(text, "tas toqu")

    tas_positions = [text.index("TAS") + i for i in range(3)]
    assert all(pos in highlighted for pos in tas_positions)
    torque_start = text.index("Torque")
    # "toqu" is a fuzzy subsequence inside Torque, so the visible matching
    # characters should still be marked for blue drawing.
    for offset in (0, 1, 3, 4):
        assert torque_start + offset in highlighted


def test_fuzzy_completer_popup_uses_two_line_delegate_ten_rows_and_tooltips(qapp):
    cb = SearchableComboBox()
    full = "[T08_YuanDi_FOC_Cur] BASC_00_01_01_B_01_02:iMC_ConstZeroDealMode_mdu8"
    cb.addItem(full)
    cb.resize(260, 36)
    cb.show()
    qapp.processEvents()

    assert cb.maxVisibleItems() == 10
    assert cb.itemData(0, Qt.ToolTipRole) == full

    option = QStyleOptionViewItem()
    index = cb.model().index(0, 0)
    combo_delegate = cb.view().itemDelegate()
    completer_delegate = cb.completer().popup().itemDelegate()
    assert combo_delegate.sizeHint(option, index).height() >= 40
    assert completer_delegate.sizeHint(option, index).height() >= 40

    cb.showPopup()
    qapp.processEvents()
    assert cb.view().maximumWidth() == cb.width()
    assert cb.completer().popup().maximumWidth() == cb.width()
    assert cb.view().maximumHeight() <= combo_delegate.sizeHint(option, index).height() * 10 + 8
    cb.hidePopup()


from mf4_analyzer.ui.inspector_sections import (
    TimeContextual, FFTContextual, OrderContextual, FFTTimeContextual,
)
from mf4_analyzer.ui_kit.widgets.searchable_combo import SearchableComboBox


def test_inspector_channel_combos_are_searchable(qapp):
    # FFTContextual.combo_sig
    fft = FFTContextual()
    assert isinstance(fft.combo_sig, SearchableComboBox), \
        "FFTContextual.combo_sig must be SearchableComboBox"
    # OrderContextual.combo_sig and combo_rpm
    order = OrderContextual()
    assert isinstance(order.combo_sig, SearchableComboBox)
    assert isinstance(order.combo_rpm, SearchableComboBox)
    # FFTTimeContextual.combo_sig
    fftt = FFTTimeContextual()
    assert isinstance(fftt.combo_sig, SearchableComboBox)


def test_highlight_and_split_are_cached_by_text_query():
    """E9: paint-path helpers must memoize on (text, query)."""
    from mf4_analyzer.ui_kit.widgets.searchable_combo import (
        _highlight_char_indexes,
        _split_combo_label,
    )

    _highlight_char_indexes.cache_clear()
    _split_combo_label.cache_clear()
    text = "Rte_TAS_mTorsionBarTorque_xds16"
    a = _highlight_char_indexes(text, "tas")
    b = _highlight_char_indexes(text, "tas")
    assert a == b
    assert _highlight_char_indexes.cache_info().hits >= 1

    m1, meta1 = _split_combo_label("[src] head:channel")
    m2, meta2 = _split_combo_label("[src] head:channel")
    assert (m1, meta1) == (m2, meta2)
    assert _split_combo_label.cache_info().hits >= 1


def test_delegate_exposes_class_level_colors():
    from mf4_analyzer.ui_kit.widgets.searchable_combo import _TwoLineChannelDelegate

    assert _TwoLineChannelDelegate._MAIN_COLOR.name() == "#111827"
    assert _TwoLineChannelDelegate._HIGHLIGHT_COLOR.name() == "#0b73e7"
