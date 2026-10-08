"""Sequence-level contracts for shared cursor cards, using painted documents.

These are production-widget probes. Actual canvas signal wiring is separately
covered by the native ChartStack probe; pin title helpers are not that evidence.
"""
from dataclasses import replace

import pytest
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui.chart_stack.cursor_pill import CursorPill
from mf4_analyzer.ui.chart_stack.cursor_display import (
    build_cursor_presentation, build_fft_cursor_presentation,
    build_frf_cursor_presentation, frf_live_primary_html,
    pin_live_primary_html, pin_primary_html,
)
from mf4_analyzer.ui.cursor_display_model import (
    CursorDisplayBranch, CursorDisplayChannel, CursorDisplayOptions,
    FrequencyCursorChannel, FrfCursorPoint, FrfCursorSample, FrfLiveCursorFacts,
)
from mf4_analyzer.ui.pinned_cursor_state import PinnedCursorIntent
from mf4_analyzer.ui_kit import load_stylesheet


CHANNELS = tuple(
    CursorDisplayChannel(
        identity=str(i), source_label="", channel_label=name, color=color,
        unit_suffix="Nm", current_value=value, min_value=1.86,
        max_value=1.90, avg_value=1.88, delta=.04,
    )
    for i, name, color, value in (
        (1, "TorqueA", "#00aa9b", 1.869),
        (2, "TorqueB", "#004ae6", 1.896),
    )
)


@pytest.fixture
def card(qapp, qtbot):
    old_style = qapp.styleSheet()
    load_stylesheet(qapp)
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(900, 640)
    host.show()
    pill = CursorPill(host)
    pill.set_pin_role("pinned")
    pill.set_ordinal(3)
    yield host, pill
    host.close()
    qapp.setStyleSheet(old_style)


def _project(domain="time", mode="single", mini=True, channels=CHANNELS, x=31.581):
    if domain in {"time", "channel"}:
        if domain == "channel" and channels is CHANNELS:
            channels = tuple(replace(c, branches=(
                CursorDisplayBranch("X↑", current_value=c.current_value,
                                    min_value=1.86, max_value=1.90,
                                    avg_value=1.88, delta_value=.04),
                CursorDisplayBranch("X↓", current_value=2.187,
                                    min_value=2.10, max_value=2.20,
                                    avg_value=2.15, delta_value=-.10),
            )) for c in channels)
        return build_cursor_presentation(
            channels, CursorDisplayOptions(), cursor_mode=mode,
            x_mode="time" if domain == "time" else "custom", mini=mini,
        )
    if domain == "frequency":
        return build_fft_cursor_presentation(tuple(
            FrequencyCursorChannel(
                identity=c.identity, source_label="", channel_label=c.channel_label,
                unit_suffix=c.unit_suffix, value=c.current_value,
                a_value=1.86, b_value=1.90, delta_ab=.04,
            ) for c in channels
        ), cursor_mode=mode, mini=mini)
    sample = _frf_sample(mode, x)
    return build_frf_cursor_presentation(sample, mini=mini)


def _frf_sample(mode, x):
    return FrfCursorSample(
        frequency_hz=x, magnitude=1.8, phase_deg=20, coherence=.8,
        magnitude_unit="Nm/N",
        a=FrfCursorPoint(x, 1.8, 20, .8) if mode == "dual" else None,
        b=FrfCursorPoint(32, 1.9, 21, .9) if mode == "dual" else None,
        delta_frequency_hz=32-x, delta_magnitude=.1,
        delta_phase_deg=1, delta_coherence=.1,
    )


def _update(qapp, pill, x=31.581, *, domain="time", mode="single", mini=True,
            channels=CHANNELS, role="pinned"):
    intent = PinnedCursorIntent(
        record_id="sequence", ordinal=3, mode=mode, domain=domain,
        x=x, ax=x, bx=32, x_unit="s" if domain == "time" else
        "Nm" if domain == "channel" else "Hz",
    )
    if role == "pinned":
        title = pin_primary_html(intent)
    elif domain == "frf":
        title = frf_live_primary_html(FrfLiveCursorFacts(mode=mode, sample=_frf_sample(mode, x)))
    else:
        title = pin_live_primary_html(domain, mode, intent)
    # The structured publication builds the primary and body in one layout pass.
    pill._primary_original = title
    pill.set_display_projection(_project(domain, mode, mini, channels, x))
    pill.show()
    qapp.processEvents()
    return pill.width(), pill.height(), pill.visible_channel_count()


def _assert_painted_bounds(pill):
    for label in (pill._primary, pill._detail):
        if not label.isVisible():
            continue
        doc = label.document
        doc.size()
        block = doc.begin()
        while block.isValid():
            origin = doc.documentLayout().blockBoundingRect(block).topLeft()
            layout = block.layout()
            for i in range(layout.lineCount()):
                bounds = layout.lineAt(i).naturalTextRect().translated(origin)
                if block.text():
                    assert bounds.left() >= -1, (block.text(), bounds)
                    assert bounds.right() <= label.contentsRect().width()+1, (block.text(), bounds, label.contentsRect())
                    assert bounds.bottom() <= label.contentsRect().height()+1, (block.text(), bounds, label.contentsRect())
            block = block.next()
    assert pill.width() <= pill.safe_rect().width()
    assert pill.height() <= pill.safe_rect().height()


@pytest.mark.parametrize("domain", ["time", "channel", "frequency", "frf"])
@pytest.mark.parametrize("mode", ["single", "dual"])
@pytest.mark.parametrize("mini", [True, False], ids=["mini", "full"])
@pytest.mark.parametrize("role", ["pinned", "live"])
def test_coordinates_retain_geometry_after_bounded_growth(qapp, card, domain, mode, mini, role):
    _host, pill = card
    pill.set_pin_role(role)
    if role == "live":
        pill.set_live_hint("按 P 固定当前读数")
    values = [31.581, 31.5925, 9.9999, 10.0001, -.0001, 0, 1e5, 1e-5, 32.]
    for x in values:
        _update(qapp, pill, x, domain=domain, mode=mode, mini=mini, role=role)
        _assert_painted_bounds(pill)
    settled = pill.size()
    for x in reversed(values):
        _update(qapp, pill, x, domain=domain, mode=mode, mini=mini, role=role)
        assert pill.size() == settled
        _assert_painted_bounds(pill)


@pytest.mark.parametrize("height", [130, 145, 160])
def test_short_host_does_not_oscillate_visible_channels(qapp, card, height):
    host, pill = card
    host.resize(900, height)
    states = [_update(qapp, pill, x) for x in [31.581, 31.5925] * 4]
    assert len(set(states)) == 1, states
    _assert_painted_bounds(pill)


@pytest.mark.parametrize("change", ["branches", "diagnostic", "exponent"])
def test_transient_body_changes_do_not_shrink_or_leave_stale_text(qapp, card, change):
    _host, pill = card
    short = CHANNELS
    if change == "branches":
        short = tuple(replace(c, branches=(CursorDisplayBranch("X↑", current_value=1.869),)) for c in CHANNELS)
        long = tuple(replace(c, branches=c.branches + (CursorDisplayBranch("X↓", current_value=9.876),)) for c in short)
    elif change == "diagnostic":
        long = tuple(replace(c, diagnostic="区间内无数据") for c in short)
    else:
        long = tuple(replace(c, current_value=-1.234e-308) for c in short)
    domain = "channel" if change == "branches" else "time"
    _update(qapp, pill, domain=domain, channels=short)
    _update(qapp, pill, domain=domain, channels=long)
    grown = pill.size()
    for channels in [short, long, short]:
        _update(qapp, pill, domain=domain, channels=channels)
        assert pill.size() == grown
        _assert_painted_bounds(pill)
    text = pill._detail.document.toPlainText()
    assert "X↓" not in text and "9.876" not in text
    assert "区间内无数据" not in text
    assert "1.234e-308" not in text


def test_clear_releases_size_retention(qapp, card):
    _host, pill = card
    initial = _update(qapp, pill)
    wide = tuple(replace(c, current_value=-1.234e-308) for c in CHANNELS)
    _update(qapp, pill, channels=wide)
    assert pill.width() > initial[0]
    pill.clear()
    assert _update(qapp, pill) == initial


def test_mode_and_host_changes_start_a_fresh_layout(qapp, card):
    host, pill = card
    _update(qapp, pill, channels=tuple(replace(c, current_value=-1.234e-308) for c in CHANNELS))
    # Changing the display mode discards transient width history.
    _update(qapp, pill, mini=False)
    fresh_full = pill.size()
    pill.clear()
    _update(qapp, pill, mini=False)
    assert pill.size() == fresh_full
    # A reduced host must re-budget actual content instead of retaining overflow.
    host.resize(400, 145)
    _update(qapp, pill)
    _assert_painted_bounds(pill)
    assert pill.height() <= pill.safe_rect().height()


@pytest.mark.parametrize("setting", ["channel_set", "fields", "font", "host"])
def test_structural_settings_release_previous_value_envelope(qapp, card, setting):
    host, pill = card
    wide = tuple(replace(c, current_value=-1.234e-308, min_value=-1.234e-308,
                         max_value=-1.234e-308, avg_value=-1.234e-308, delta=-1.234e-308)
                 for c in CHANNELS)
    _update(qapp, pill, mode="dual", mini=False, channels=wide)
    channels = CHANNELS[:1] if setting == "channel_set" else CHANNELS
    options = CursorDisplayOptions(show_min_value=False, show_max_value=False) if setting == "fields" else CursorDisplayOptions()
    if setting == "font":
        font = pill._detail.font()
        font.setFamily("Courier")
        pill._detail.setFont(font)
    elif setting == "host":
        host.resize(520, 260)
    projection = build_cursor_presentation(channels, options, cursor_mode="dual", x_mode="time", mini=False)
    title = pin_primary_html(PinnedCursorIntent(record_id="sequence", ordinal=3, mode="dual", domain="time", ax=31., bx=32., x_unit="s"))
    pill._primary_original = title
    pill.set_display_projection(projection)
    pill.show()
    qapp.processEvents()
    after_change = pill.size()
    _assert_painted_bounds(pill)
    pill.clear()
    pill._primary_original = title
    pill.set_display_projection(projection)
    pill.show()
    qapp.processEvents()
    assert pill.size() == after_change
    _assert_painted_bounds(pill)


def test_custom_x_no_available_branches_does_not_retain_previous_readings(qapp, card):
    _host, pill = card
    _update(qapp, pill, domain="channel")
    assert pill.visible_channel_count() == 2
    assert "X↑" in pill._detail.document.toPlainText()
    unavailable = tuple(replace(c, branches=(), current_value=None) for c in CHANNELS)
    _update(qapp, pill, domain="channel", channels=unavailable)
    assert pill.visible_channel_count() == 0
    text = pill._detail.document.toPlainText()
    assert "X↑" not in text and "X↓" not in text
    assert "1.869" not in text and "2.187" not in text
    _assert_painted_bounds(pill)


def test_first_show_does_not_discard_initial_branch_size(qapp, card):
    _host, pill = card
    # The first publication precedes show(): style/font polishing must already
    # participate in its structure signature, or the next sample resets it.
    first = _update(qapp, pill, domain="channel")
    one_branch = tuple(replace(c, branches=(
        CursorDisplayBranch("X↑", current_value=1.869),
    )) for c in CHANNELS)
    for channels in (one_branch, CHANNELS, one_branch):
        assert _update(qapp, pill, domain="channel", channels=channels) == first
        _assert_painted_bounds(pill)
