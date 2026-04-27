from PyQt5.QtCore import Qt
from mf4_analyzer.ui.widgets.searchable_combo import SearchableComboBox


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
    assert cb.completer().model() is cb.model()
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
