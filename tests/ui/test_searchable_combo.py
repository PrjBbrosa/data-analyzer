from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QStyleOptionViewItem
from mf4_analyzer.ui.widgets.searchable_combo import (
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
    assert first_model is not None  # original kept alive but unused


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
from mf4_analyzer.ui.widgets.searchable_combo import SearchableComboBox


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
