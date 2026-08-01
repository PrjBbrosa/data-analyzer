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


def test_picker_search_lives_in_original_field_not_popup(qtbot):
    from PyQt5.QtWidgets import QLineEdit
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    p = SignalPickerPopup(available_signals=["vibration_x", "temp"])
    qtbot.addWidget(p)

    assert p._display_frame.isAncestorOf(p._search)
    assert not p._popup.isAncestorOf(p._search)
    assert p._popup.findChildren(QLineEdit) == []


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


def test_focus_to_inline_search_keeps_popup_open(qtbot):
    """原通道框内的搜索输入获得焦点时，候选 popup 必须保持打开。"""
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


def test_signal_chip_emits_remove_signal(qtbot):
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalChip
    chip = SignalChip("sig_a")
    qtbot.addWidget(chip)
    received = []
    chip.removeRequested.connect(received.append)
    qtbot.mouseClick(chip._remove_btn, Qt.LeftButton)
    assert received == ["sig_a"]


def test_signal_chip_label_truncates_long_name(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalChip
    long_name = "A_side.Rte." + "x" * 200
    chip = SignalChip(long_name, max_label_chars=40)
    qtbot.addWidget(chip)
    assert chip._label.toolTip() == long_name
    assert len(chip._label.text()) <= 41  # 40 + ellipsis "…"
    assert chip._label.text().endswith("…")


def test_picker_display_summarizes_selected_items_that_do_not_fit(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import (
        SignalPickerPopup, SignalChip,
    )
    names = tuple(f"Rte_very_long_signal_name_{index:02d}_xds16" for index in range(20))
    p = SignalPickerPopup(available_signals=names)
    qtbot.addWidget(p)
    p.resize(288, 60)
    p.show()
    p.set_selected(names)
    qtbot.wait(20)

    chips = p._display_frame.findChildren(SignalChip)
    visible_chips = [chip for chip in chips if not chip.isHidden()]
    assert 1 <= len(visible_chips) <= 2
    assert p._overflow_label.isVisibleTo(p)
    assert p._overflow_label.text() == f"+{len(names) - len(visible_chips)}"
    assert names[-1] in p._overflow_label.toolTip()


def test_picker_display_stays_single_line_and_inside_narrow_host(qtbot):
    from PyQt5.QtCore import QPoint
    from mf4_analyzer.ui.drawers.batch.signal_picker import (
        SignalChip, SignalPickerPopup,
    )

    names = tuple(f"Rte_channel_{index:02d}_with_a_long_name" for index in range(20))
    p = SignalPickerPopup(available_signals=names)
    qtbot.addWidget(p)
    p.resize(288, 60)
    p.show()
    p.set_selected(names)
    qtbot.wait(20)

    frame = p._display_frame
    assert p.width() == 288
    assert p.height() == 38
    assert frame.width() <= p.width()
    assert frame.sizeHint().height() <= 44
    visible_children = [
        *[chip for chip in frame.findChildren(SignalChip) if chip.isVisibleTo(p)],
        p._overflow_label,
        p._search,
        p._arrow_button,
    ]
    for child in visible_children:
        if not child.isVisibleTo(p):
            continue
        top_left = child.mapTo(frame, QPoint(0, 0))
        assert top_left.x() >= 0
        assert top_left.x() + child.width() <= frame.width()


def test_picker_active_search_uses_original_field_width(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import (
        SignalChip, SignalPickerPopup,
    )

    names = tuple(f"Rte_channel_{index:02d}_with_a_long_name" for index in range(20))
    p = SignalPickerPopup(available_signals=names)
    qtbot.addWidget(p)
    p.set_selected(names)
    p.resize(288, 38)
    p.show()
    p.set_search_text("channel_19")
    qtbot.wait(20)

    assert p.width() == 288
    assert p._search.text() == "channel_19"
    assert p._search.width() >= 200
    assert not p._overflow_label.isVisibleTo(p)
    assert not any(
        chip.isVisibleTo(p)
        for chip in p._display_frame.findChildren(SignalChip)
    )


def test_picker_display_chip_remove_unselects_signal(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import (
        SignalPickerPopup, SignalChip,
    )
    p = SignalPickerPopup(available_signals=["a", "b"])
    qtbot.addWidget(p)
    p.set_selected(("a", "b"))
    received = []
    p.selectionChanged.connect(lambda tup: received.append(tup))
    chip_a = next(c for c in p._display_frame.findChildren(SignalChip)
                  if c.name() == "a")
    chip_a._remove_btn.click()
    assert "a" not in p.selected()
    assert received[-1] == ("b",)


def test_picker_display_clicking_empty_area_opens_popup(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    from PyQt5.QtCore import QPoint, Qt
    p = SignalPickerPopup(available_signals=["a"])
    qtbot.addWidget(p)
    p.show()
    qtbot.mouseClick(p._display_frame, Qt.LeftButton, pos=QPoint(5, 5))
    assert p.is_popup_visible() is True


def test_picker_single_select_replaces_previous_selection(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    p = SignalPickerPopup(
        available_signals=["a", "b", "c"], single_select=True,
    )
    qtbot.addWidget(p)
    received = []
    p.selectionChanged.connect(lambda tup: received.append(tup))
    p.set_selected(("a",))
    assert p.selected() == ("a",)
    p.set_selected(("b",))
    assert p.selected() == ("b",)
    # Setting two should be normalized to the first only.
    p.set_selected(("a", "c"))
    assert p.selected() == ("a",)


def test_picker_single_select_checking_unchecks_others(qtbot):
    from PyQt5.QtWidgets import QCheckBox
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    from PyQt5.QtCore import Qt
    p = SignalPickerPopup(
        available_signals=["a", "b"], single_select=True,
    )
    qtbot.addWidget(p)
    # Find each row's checkbox and toggle them in order
    boxes: dict[str, QCheckBox] = {}
    for i in range(p._list.count()):
        item = p._list.item(i)
        cb = p._list.itemWidget(item)
        boxes[item.data(Qt.UserRole)] = cb
    boxes["a"].setChecked(True)
    assert p.selected() == ("a",)
    boxes["b"].setChecked(True)
    assert p.selected() == ("b",)
    assert boxes["a"].isChecked() is False  # auto-unchecked


def test_picker_popup_rounded_corners_have_no_square_frame(qtbot):
    """The dropdown is a Qt.Popup QFrame with an 8px-rounded surface. A
    top-level popup whose background is opaque shows a square frame outside
    the radius — assert the translucent-background box-leak fix."""
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    p = SignalPickerPopup(available_signals=["a", "b"])
    qtbot.addWidget(p)
    flags = p._popup.windowFlags()
    assert bool(flags & Qt.Popup), "SignalPickerPopup must retain Qt.Popup click-away behavior"
    assert bool(flags & Qt.FramelessWindowHint)
    assert bool(flags & Qt.NoDropShadowWindowHint)
    assert p._popup.testAttribute(Qt.WA_TranslucentBackground), (
        "SignalPickerPopup 圆角需配 WA_TranslucentBackground,否则留方框"
    )
    assert p._popup.testAttribute(Qt.WA_StyledBackground), (
        "SignalPickerPopup must let its rounded QSS surface paint on the "
        "translucent shell"
    )
    assert p._popup.frameShape() == p._popup.NoFrame
