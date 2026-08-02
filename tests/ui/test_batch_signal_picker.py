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


def test_picker_search_lives_in_popup_not_trigger(qtbot):
    """方案 A：搜索职责搬进弹层，收起态触发器不再接受文本输入。"""
    from PyQt5.QtWidgets import QLineEdit
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    p = SignalPickerPopup(available_signals=["vibration_x", "temp"])
    qtbot.addWidget(p)

    assert p._popup.isAncestorOf(p._search)
    assert not p._trigger.isAncestorOf(p._search)
    assert p._trigger.findChildren(QLineEdit) == []


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


def test_popup_search_takes_focus_on_open(qtbot):
    """方案 A 的前提：打开弹层即聚焦搜索框，用户点开后可直接打字。"""
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    p = SignalPickerPopup(available_signals=["sig_a", "sig_b"])
    qtbot.addWidget(p)
    p.show_popup()
    qtbot.wait(20)
    assert p.is_popup_visible() is True
    assert p._search.hasFocus() is True   # no second click needed to search
    qtbot.keyClicks(p._search, "sig_b")
    assert p.visible_items() == ["sig_b"]
    assert p.is_popup_visible() is True   # typing must not close the popup


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


def test_picker_display_summarizes_selected_items_that_do_not_fit(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    names = tuple(f"Rte_very_long_signal_name_{index:02d}_xds16" for index in range(20))
    p = SignalPickerPopup(available_signals=names)
    qtbot.addWidget(p)
    p.resize(288, 60)
    p.show()
    p.set_selected(names)
    qtbot.wait(20)

    assert p._summary_label.text() != ""
    assert p._overflow_label.isVisibleTo(p)
    assert p._overflow_label.text() == f"+{len(names) - 1}"
    tooltip = p._trigger.toolTip()
    for name in names:
        assert name in tooltip


def test_picker_display_stays_single_line_and_inside_narrow_host(qtbot):
    from PyQt5.QtCore import QPoint
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    names = tuple(f"Rte_channel_{index:02d}_with_a_long_name" for index in range(20))
    p = SignalPickerPopup(available_signals=names)
    qtbot.addWidget(p)
    p.resize(288, 60)
    p.show()
    p.set_selected(names)
    qtbot.wait(20)

    frame = p._trigger
    assert p.width() == 288
    assert p.height() == 38
    assert frame.width() <= p.width()
    assert frame.sizeHint().height() <= 44
    for child in (p._summary_label, p._overflow_label, p._arrow_button):
        if not child.isVisibleTo(p):
            continue
        top_left = child.mapTo(frame, QPoint(0, 0))
        assert top_left.x() >= 0
        assert top_left.x() + child.width() <= frame.width()


def test_picker_unchecking_in_popup_unselects_signal(qtbot):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QCheckBox
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    p = SignalPickerPopup(available_signals=["a", "b"])
    qtbot.addWidget(p)
    p.set_selected(("a", "b"))
    received = []
    p.selectionChanged.connect(lambda tup: received.append(tup))

    box_a = next(
        p._list.itemWidget(p._list.item(i))
        for i in range(p._list.count())
        if p._list.item(i).data(Qt.UserRole) == "a"
    )
    assert isinstance(box_a, QCheckBox)
    box_a.setChecked(False)

    assert "a" not in p.selected()
    assert received[-1] == ("b",)


def test_picker_display_clicking_empty_area_opens_popup(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup
    from PyQt5.QtCore import QPoint, Qt
    p = SignalPickerPopup(available_signals=["a"])
    qtbot.addWidget(p)
    p.show()
    qtbot.mouseClick(p._trigger, Qt.LeftButton, pos=QPoint(5, 5))
    assert p.is_popup_visible() is True


def test_picker_trigger_opens_on_space_and_enter(qtbot):
    """触发器是按钮语义，不是输入框：Space / Enter 展开，可打印字符不响应。"""
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    p = SignalPickerPopup(available_signals=["a", "b"])
    qtbot.addWidget(p)
    p.show()
    qtbot.wait(20)

    qtbot.keyClick(p._trigger, Qt.Key_Space)
    assert p.is_popup_visible() is True
    p.hide_popup()

    qtbot.keyClick(p._trigger, Qt.Key_Return)
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


# ---------------------------------------------------------------------------
# Option A regressions — one per confirmed symptom
# ---------------------------------------------------------------------------
def test_picker_arrow_uses_drawn_icon_not_text_glyph(qtbot):
    """症状 01：箭头曾是 "⌄" 字符压在蓝色实底方块上，渲染粗糙。"""
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    p = SignalPickerPopup(available_signals=["a"])
    qtbot.addWidget(p)

    assert p._arrow_button.text() == ""
    assert not p._arrow_button.icon().isNull()
    collapsed = p._arrow_button.icon().cacheKey()

    p.show_popup()
    assert p._arrow_button.text() == ""
    assert not p._arrow_button.icon().isNull()
    assert p._arrow_button.icon().cacheKey() != collapsed   # flips on expand

    p.hide_popup()
    assert p._arrow_button.icon().cacheKey() == collapsed


def test_picker_trigger_has_sunken_resting_background(qtbot):
    """症状 02：#fff 底落在浅色面板上，静止态看不出可点。"""
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    p = SignalPickerPopup(available_signals=["a"])
    qtbot.addWidget(p)

    resting = p._trigger.styleSheet()
    assert "#eef2f7" in resting          # sunken against the panel
    assert "#e8edf4" in resting          # hover is a distinct third state
    assert "#fff" not in resting

    p.show_popup()
    expanded = p._trigger.styleSheet()
    assert "#fff" in expanded
    assert "#1769e0" in expanded

    p.hide_popup()
    assert p._trigger.styleSheet() == resting


def test_picker_trigger_geometry_is_stable_across_search(qtbot):
    """症状 03 / 04：搜索曾把 chips 全部隐藏，收起态元素来回位移。"""
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    names = tuple(f"Rte_channel_{index:02d}_with_a_long_name" for index in range(20))
    p = SignalPickerPopup(available_signals=names)
    qtbot.addWidget(p)
    p.resize(288, 38)
    p.show()
    p.set_selected(names)
    qtbot.wait(20)

    watched = (p._summary_label, p._overflow_label, p._arrow_button)
    before = [child.geometry() for child in watched]
    summary_before = p._summary_label.text()

    p.set_search_text("channel_19")
    qtbot.wait(20)
    assert p.visible_items() == [names[19]]      # the query really did filter

    after = [child.geometry() for child in watched]
    assert after == before
    assert p._summary_label.text() == summary_before

    p.set_search_text("")
    qtbot.wait(20)
    assert [child.geometry() for child in watched] == before


def test_picker_popup_is_at_least_420_wide(qtbot):
    """症状 05：弹层原来只有 max(280, 触发器宽)，长名在列表里同样被切。"""
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    p = SignalPickerPopup(available_signals=["a", "b"])
    qtbot.addWidget(p)
    p.resize(288, 38)
    p.show()
    p.show_popup()
    qtbot.wait(20)

    assert p._popup.width() >= 420
    assert p._popup.width() > p._trigger.width()
    # 「直接在上方原通道框输入」的提示语随搜索框进弹层一并消失
    assert not hasattr(p, "_search_hint")


def test_picker_summary_elides_in_middle(qtbot):
    """摘要用 ElideMiddle，头尾片段同时可见（尾缀区分同名通道）。"""
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    name = "Rte_ActRetPlausi_mActiveReturnMotorTorque_xds16"
    p = SignalPickerPopup(available_signals=[name])
    qtbot.addWidget(p)
    p.resize(288, 38)
    p.show()
    p.set_selected((name,))
    qtbot.wait(20)

    text = p._summary_label.text()
    assert text != name          # it really is elided at this width
    assert "…" in text
    assert text.startswith(name[:4])
    assert text.endswith("_xds16")


def test_picker_popup_select_all_adds_filtered_matches(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    p = SignalPickerPopup(
        available_signals=["vib_x", "vib_y", "temp_a", "temp_b"],
    )
    qtbot.addWidget(p)
    p.set_selected(("temp_a",))
    p.set_search_text("vib")
    assert p._select_all_button.text() == "全选 2 条"

    p._select_all_button.click()

    # union: the pre-existing pick survives, both matches join
    assert set(p.selected()) == {"temp_a", "vib_x", "vib_y"}
    assert "temp_b" not in p.selected()
    assert p._foot_stats.text() == "已选 3 · 匹配 2"

    p._clear_button.click()
    assert p.selected() == ()
    assert p._clear_button.isEnabled() is False


def test_picker_popup_select_all_skips_disabled_partials(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    p = SignalPickerPopup(
        available_signals=["vib_x"],
        partially_available={"vib_y": "(1/2)"},
    )
    qtbot.addWidget(p)
    assert p.is_disabled("vib_y") is True

    p._select_all_button.click()

    assert p.selected() == ("vib_x",)   # the greyed partial is not swept in


def test_picker_single_select_hides_select_all(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    rpm = SignalPickerPopup(available_signals=["a", "b"], single_select=True)
    qtbot.addWidget(rpm)
    rpm.show_popup()
    qtbot.wait(20)
    assert rpm._select_all_button.isVisibleTo(rpm._popup) is False
    assert rpm._clear_button.isVisibleTo(rpm._popup) is True

    multi = SignalPickerPopup(available_signals=["a", "b"])
    qtbot.addWidget(multi)
    multi.show_popup()
    qtbot.wait(20)
    assert multi._select_all_button.isVisibleTo(multi._popup) is True


def test_picker_popup_shows_empty_state_when_nothing_matches(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    p = SignalPickerPopup(available_signals=["vib_x", "vib_y"])
    qtbot.addWidget(p)
    p.show_popup()
    p.set_search_text("no_such_channel")
    qtbot.wait(20)

    assert p.visible_items() == []
    assert p._empty_label.isVisibleTo(p._popup) is True
    assert p._select_all_button.isEnabled() is False
    assert p._foot_stats.text() == "已选 0 · 匹配 0"


def test_picker_popup_clears_search_when_closed(qtbot):
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    p = SignalPickerPopup(available_signals=["vib_x", "temp"])
    qtbot.addWidget(p)
    p.show_popup()
    p.set_search_text("vib")
    assert p.visible_items() == ["vib_x"]

    p.hide_popup()
    qtbot.wait(20)

    assert p._search.text() == ""
    assert set(p.visible_items()) == {"vib_x", "temp"}


def test_picker_popup_surface_carries_the_background(qtbot):
    """The rounded shell sets WA_TranslucentBackground, which makes the
    popup's own qss background a no-op — on a real screen the list area showed
    the panel behind it while every offscreen test stayed green. An inner
    surface must paint the fill and the radius instead (CLAUDE.md's
    "WA_TranslucentBackground 会让本体 QSS 失效 → 需内部子 widget 兜底")."""
    from PyQt5.QtCore import Qt
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    p = SignalPickerPopup(available_signals=["a", "b"])
    qtbot.addWidget(p)

    assert p._surface.parent() is p._popup
    assert "background:#fff" in p._surface.styleSheet()
    assert p._surface.testAttribute(Qt.WA_StyledBackground)
    # The shell must NOT claim to paint a fill it cannot actually draw.
    assert "background:#fff" not in p._popup.styleSheet()
    # Everything the user sees sits on the surface, not on the shell.
    for child in (p._search, p._list, p._empty_label, p._foot):
        assert p._surface.isAncestorOf(child)


def test_picker_popup_caps_visible_rows(qtbot):
    """A long channel list must scroll rather than grow the popup to fill the
    screen (25 channels wanted ~554px of rows)."""
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    names = [f"Rte_Module{i:02d}_mLongChannelName_xds16" for i in range(25)]
    p = SignalPickerPopup(available_signals=names)
    qtbot.addWidget(p)
    p.show_popup()
    qtbot.wait(20)

    assert p._list.height() < p._list_content_height()
    assert p._list.height() <= p._row_budget()
    assert p._list.verticalScrollBar().maximum() > 0


def test_picker_popup_geometry_is_stable_across_filtering(qtbot):
    """Popup size/position are measured once per opening and then held.

    A popup whose height tracked the filter also re-decided whether to open
    upwards, so typing made the whole panel jump — reported from a real
    macOS run after the option-A rewrite.
    """
    from mf4_analyzer.ui.drawers.batch.signal_picker import SignalPickerPopup

    names = [f"Rte_Module{i:02d}_mLongChannelName_xds16" for i in range(25)]
    p = SignalPickerPopup(available_signals=names)
    qtbot.addWidget(p)
    p.show_popup()
    qtbot.wait(20)

    seen = set()
    for query in ("", "Module0", "zzz-no-match", "", "Module1", ""):
        p.set_search_text(query)
        qtbot.wait(10)
        seen.add((p._popup.height(), p._popup.pos().x(), p._popup.pos().y()))

    assert len(seen) == 1, seen
