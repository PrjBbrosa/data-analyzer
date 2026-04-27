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


def test_focus_to_search_keeps_popup_open(qtbot):
    """点击 popup 内部搜索框时 popup 必须保持打开 (ultrareview bug_015)."""
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    p = SignalPickerPopup(available_signals=["sig_a", "sig_b"])
    qtbot.addWidget(p)
    p.show_popup()
    assert p.is_popup_visible() is True
    p._search.setFocus()
    qtbot.wait(50)
    assert p.is_popup_visible() is True   # popup stays open while search is focused


def test_set_partially_available_keeps_selection_marked_unavailable(qtbot):
    """加入一个不全包含选中信号的文件后，选中的信号应保持在 _selected 里
    并 emit selectionChanged，以便 BatchSheet.signals_marked_unavailable 起作用
    (ultrareview bug_002)."""
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    p = SignalPickerPopup(available_signals=["sig_a", "sig_b"])
    qtbot.addWidget(p)
    p.set_selected(("sig_a",))
    received = []
    p.selectionChanged.connect(lambda tup: received.append(tup))
    # File B now joins; sig_a only in 1 of 2 → moves to partial
    p.set_available(["sig_b"])
    p.set_partially_available({"sig_a": "(1/2)"})
    # sig_a stays selected — visible as red chip / marked unavailable downstream
    assert "sig_a" in p._selected
    # set_partially_available didn't change _selected, so it should NOT have emitted again
    # set_available didn't change _selected either (we kept sig_a) — also no emit
    assert received == []   # no spurious emit when selection didn't actually change

    # But if a name that's truly gone (neither available nor partial) → drop + emit
    p.set_available(["sig_b"])
    p.set_partially_available({})  # sig_a now nowhere
    assert "sig_a" not in p._selected
    assert received and received[-1] == ()
