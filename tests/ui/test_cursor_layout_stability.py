"""Continuous value updates must not repack the painted cursor card."""
import pytest
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui.chart_stack.cursor_display import build_cursor_presentation, pin_primary_html
from mf4_analyzer.ui.chart_stack.cursor_pill import CursorPill
from mf4_analyzer.ui.cursor_display_model import CursorDisplayChannel, CursorDisplayOptions
from mf4_analyzer.ui.pinned_cursor_state import PinnedCursorIntent
from mf4_analyzer.ui_kit import load_stylesheet


@pytest.fixture
def card(qapp, qtbot):
    old_style = qapp.styleSheet()
    load_stylesheet(qapp)
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(900, 640)
    host.show()
    pill = CursorPill(host)
    pill.set_pin_role('pinned')
    pill.set_ordinal(3)
    yield host, pill
    host.close()
    qapp.setStyleSheet(old_style)


def render(pill, t, *, diagnostic='', mini=True, value=1.869):
    channels = tuple(CursorDisplayChannel(
        identity=str(i), source_label='', channel_label=f'Torque{i}',
        color='#00aa9b', unit_suffix='Nm', current_value=value,
        diagnostic=diagnostic,
    ) for i in range(2))
    intent = PinnedCursorIntent(record_id='probe', ordinal=3, mode='single',
                                domain='time', x_unit='s', presentation='mini',
                                panel_expanded=True, x=t)
    pill._primary_original = pin_primary_html(intent)
    pill.set_display_projection(build_cursor_presentation(
        channels, CursorDisplayOptions(), cursor_mode='single', x_mode='time', mini=mini))
    pill.show()


@pytest.mark.parametrize('height', [640, 145])
def test_screenshot_coordinates_keep_header_size_and_visible_rows(card, qapp, height):
    host, pill = card
    host.resize(900, height)
    observations = []
    for t in [31.5810, 31.5925] * 4:
        render(pill, t)
        qapp.processEvents()
        observations.append((pill.size(), pill._primary.height(), pill.visible_channel_count()))
        assert f'{t:.4f}' in pill._primary.document.toPlainText()
    assert all(observation == observations[0] for observation in observations)
    assert pill._primary.document.begin().text() == 'P3'


def test_transient_diagnostics_release_text_but_not_geometry(card, qapp):
    _host, pill = card
    render(pill, 31.581)
    qapp.processEvents()
    original = pill.size()
    render(pill, 31.581, diagnostic='No data at cursor')
    qapp.processEvents()
    expanded = pill.size()
    assert expanded.height() > original.height()
    render(pill, 31.581)
    qapp.processEvents()
    assert pill.size() == expanded
    assert 'No data at cursor' not in pill._detail.document.toPlainText()
    pill.clear()
    render(pill, 31.581)
    qapp.processEvents()
    assert pill.size() == original


def test_structure_reset_releases_retained_width(card, qapp):
    _host, pill = card
    render(pill, 31.581, value=-1.234e-208)
    qapp.processEvents()
    wide = pill.width()
    render(pill, 31.581)
    qapp.processEvents()
    assert pill.width() == wide
    render(pill, 31.581, mini=False)
    render(pill, 31.581)
    qapp.processEvents()
    assert pill.width() < wide


def test_live_same_precision_coordinates_keep_width_from_first_frame(card, qapp):
    _host, pill = card
    pill.set_pin_role('live')
    pill.set_live_hint('按 P 固定当前读数')
    channels = (CursorDisplayChannel(identity='a', source_label='', channel_label='Nm',
                                    color='#00aa9b', unit_suffix='Nm', current_value=1.869),)
    projection = build_cursor_presentation(channels, CursorDisplayOptions(),
                                          cursor_mode='single', x_mode='time', mini=True)
    sizes = []
    for t in [31.5810, 31.5925] * 4:
        pill._primary_original = f't=<b>{t:.4f}s</b>'
        pill.set_display_projection(projection)
        pill.show()
        qapp.processEvents()
        sizes.append(pill.size())
        assert f'{t:.4f}' in pill._primary.document.toPlainText()
    assert all(size == sizes[0] for size in sizes)


def test_first_projection_retains_geometry_across_show_polish(card, qapp):
    _host, pill = card
    # New pins receive their projection before show(). The initial size is
    # already visible when the next cursor sample removes a transient row.
    render(pill, 31.581, diagnostic='No data at cursor')
    qapp.processEvents()
    initial = pill.size()
    render(pill, 31.581)
    qapp.processEvents()
    assert pill.size() == initial
    assert 'No data at cursor' not in pill._detail.document.toPlainText()
