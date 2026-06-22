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
