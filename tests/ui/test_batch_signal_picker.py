def test_picker_emits_selection_on_check(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    p = SignalPickerPopup(available_signals=["sig_a", "sig_b", "sig_c"])
    qtbot.addWidget(p)
    received = []
    p.selectionChanged.connect(lambda tup: received.append(tup))
    p.set_selected(("sig_a",))
    assert received[-1] == ("sig_a",)


def test_picker_search_filters_list(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    p = SignalPickerPopup(available_signals=["vibration_x", "vibration_y", "temp"])
    qtbot.addWidget(p)
    p.set_search_text("vib")
    visible = p.visible_items()
    assert "vibration_x" in visible
    assert "temp" not in visible


def test_picker_marks_partial_signals_grey(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    p = SignalPickerPopup(
        available_signals=["sig_a"],
        partially_available={"sig_b": "(2/3)"},
    )
    qtbot.addWidget(p)
    assert p.is_disabled("sig_b") is True
    assert "(2/3)" in p.label_for("sig_b")


def test_picker_popup_collapses_on_escape(qtbot):
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    p = SignalPickerPopup(available_signals=["a", "b"])
    qtbot.addWidget(p)
    p.show_popup()
    assert p.is_popup_visible() is True
    qtbot.keyClick(p._popup, Qt.Key_Escape)
    assert p.is_popup_visible() is False


def test_picker_popup_collapses_on_focus_out(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    p = SignalPickerPopup(available_signals=["a", "b"])
    qtbot.addWidget(p)
    p.show_popup()
    assert p.is_popup_visible() is True
    p._popup.clearFocus()  # simulate click-away
    qtbot.wait(50)
    assert p.is_popup_visible() is False
