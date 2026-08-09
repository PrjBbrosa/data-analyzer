import pytest
from mf4_analyzer.ui.inspector_sections.time_filter import FilterPanel
from mf4_analyzer.signal.filters import FilterSpec


def test_lowpass_spec(qtbot):
    p = FilterPanel(); qtbot.addWidget(p)
    p.set_kind("低通"); p.set_cutoff(120.0); p.set_order(6)
    s = p.filter_spec()
    assert s.kind == "low" and s.cutoff == 120.0 and s.order == 6


def test_bandpass_uses_two_cutoffs(qtbot):
    p = FilterPanel(); qtbot.addWidget(p)
    p.show()  # isVisible() reflects ancestor visibility; show() before query
    qtbot.waitExposed(p)
    p.set_kind("带通"); p.set_band(100.0, 2000.0)
    s = p.filter_spec()
    assert s.kind == "band" and s.cutoff_lo == 100.0 and s.cutoff_hi == 2000.0
    # the dual-cutoff row is visible, single-cutoff row hidden
    assert p._band_row.isVisible() and not p._single_row.isVisible()


def test_show_flags_default_on(qtbot):
    p = FilterPanel(); qtbot.addWidget(p)
    assert p.show_original() is True and p.show_filtered() is True


def test_no_zero_phase_control(qtbot):
    p = FilterPanel(); qtbot.addWidget(p)
    assert not hasattr(p, "chk_zero_phase")


def test_filter_editors_share_one_field_column(qtbot):
    """类型、截止和阶数 must have matching left/right editor geometry."""
    p = FilterPanel(); qtbot.addWidget(p)
    p.resize(360, 260)
    p.show()
    qtbot.waitExposed(p)

    editors = (p.combo_kind, p.spin_cut, p.combo_order)
    left_edges = {editor.geometry().left() for editor in editors}
    right_edges = {editor.geometry().right() for editor in editors}
    assert len(left_edges) == 1
    assert len(right_edges) == 1


# --- Task 4: 卡片重组 + 挂载 结构断言 ---------------------------------------

def test_inspector_mounts_filter_panel_in_range_card(qtbot):
    from mf4_analyzer.ui.inspector import Inspector
    insp = Inspector(); qtbot.addWidget(insp)
    # filter_panel is exposed on the Inspector.
    assert hasattr(insp, "filter_panel")
    # 横坐标卡 与 时间范围·滤波卡 are two distinct containers.
    assert insp._xaxis_card is not insp._range_filter_card
    # The filter panel lives INSIDE card ② (时间范围·滤波), not card ①.
    assert insp.filter_panel.parent() is insp._range_filter_card
    # Walk the ancestor chain to confirm containment in the range card.
    anc = insp.filter_panel
    found = False
    while anc is not None:
        if anc is insp._range_filter_card:
            found = True
            break
        anc = anc.parent()
    assert found
    # The filter panel is NOT inside the xaxis card.
    anc = insp.filter_panel
    while anc is not None:
        assert anc is not insp._xaxis_card
        anc = anc.parent()


def test_inspector_filter_disabled_by_default(qtbot):
    from mf4_analyzer.ui.inspector import Inspector
    insp = Inspector(); qtbot.addWidget(insp)
    # Filtering is explicit opt-in: a freshly built inspector must not filter.
    assert insp.filter_panel.is_enabled() is False
