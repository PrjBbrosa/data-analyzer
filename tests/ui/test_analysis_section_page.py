"""AnalysisSectionPage: pane container structure + focus + split + link."""
import numpy as np
import pytest

from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QVBoxLayout

from mf4_analyzer.ui.analysis_section_page import AnalysisSectionPage
from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas
from mf4_analyzer.ui.view_state import ViewManager
from mf4_analyzer.ui.analysis_view_state import AnalysisViewState
from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult


def _make_manager():
    return ViewManager(state_factory=AnalysisViewState)


class _FakeCard:
    """Card stub: AnalysisSectionPage only needs .canvas and QWidget-ness."""
    def __new__(cls):
        from PyQt5.QtWidgets import QWidget
        w = QWidget()
        w.setObjectName("chartCard")
        w.canvas = PgHeatmapCanvas(w)
        return w


class _FakeLineCard:
    """Line-canvas card variant (FFT section): canvas has no ._plot/_img."""
    def __new__(cls):
        from PyQt5.QtWidgets import QWidget
        w = QWidget()
        w.setObjectName("chartCard")
        w.canvas = PgLineCanvas(w)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(w.canvas)
        return w


class _FakeSliceCard:
    """Real layout wrapper for FFT-vs-Time geometry assertions."""

    def __new__(cls):
        from PyQt5.QtWidgets import QWidget
        w = QWidget()
        w.setObjectName("chartCard")
        w.canvas = PgHeatmapCanvas(w, with_slice=True)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(w.canvas)
        return w


@pytest.fixture
def page(qapp):
    mgr = _make_manager()
    p = AnalysisSectionPage(
        section='order',
        manager=mgr,
        card_factory=lambda: _FakeCard(),
    )
    p.resize(800, 500)
    p.show()  # 见教训：QSplitter.setSizes 前需 show()+resize
    yield p
    p.deleteLater()


@pytest.fixture
def line_page(qapp):
    mgr = _make_manager()
    p = AnalysisSectionPage(
        section='fft',
        manager=mgr,
        card_factory=lambda: _FakeLineCard(),
    )
    p.resize(800, 500)
    p.show()
    yield p
    p.deleteLater()


@pytest.fixture
def slice_page(qapp):
    mgr = _make_manager()
    p = AnalysisSectionPage(
        section='fft_time',
        manager=mgr,
        card_factory=lambda: _FakeSliceCard(),
    )
    p.resize(1200, 700)
    p.show()
    qapp.processEvents()
    yield p
    p.deleteLater()


def test_compare_row_has_bar_chrome_like_time_dock(page):
    """The analysis View-tab row reads as a real bar (like the time-domain
    #timeViewBottomDock): a light background + 1px top divider, painted by an
    explicit styled background rather than the old translucent/transparent row."""
    row = page._compare_row
    # No longer translucent (that suppressed any background fill).
    assert not row.testAttribute(Qt.WA_TranslucentBackground)
    from mf4_analyzer.ui.analysis_section_page import _COMPARE_ROW_QSS
    assert "#fbfcff" in _COMPARE_ROW_QSS
    assert "border-top" in _COMPARE_ROW_QSS


def test_starts_with_one_pane(page):
    assert page.pane_count() == 1
    assert page.focused_index() == 0


def test_enter_exit_split(page):
    page.enter_split()
    assert page.pane_count() == 2
    page.exit_split()
    assert page.pane_count() == 1
    assert page.focused_index() == 0


def test_set_focus(page):
    page.enter_split()
    page.set_focused_index(1)
    assert page.focused_index() == 1


def test_previous_focused_index_tracks_focus_change(page):
    page.enter_split()
    assert page.focused_index() == 0
    assert page.previous_focused_index() == 0
    page.set_focused_index(1)
    assert page.previous_focused_index() == 0
    assert page.focused_index() == 1
    page.set_focused_index(0)
    assert page.previous_focused_index() == 1
    assert page.focused_index() == 0


def test_x_link_toggle(page):
    page.enter_split()
    page.set_linked(True)
    vb0 = page.pane_canvas(0)._plot.vb
    vb1 = page.pane_canvas(1)._plot.vb
    assert vb1.linkedView(vb1.XAxis) is vb0
    page.set_linked(False)
    assert vb1.linkedView(vb1.XAxis) is None


def test_heatmap_link_locks_both_axes(page):
    """Heatmaps compare on BOTH axes (spec §6.1)."""
    page.enter_split()
    page.set_linked(True)
    vb0 = page.pane_canvas(0)._plot.vb
    vb1 = page.pane_canvas(1)._plot.vb
    assert vb1.linkedView(vb1.YAxis) is vb0
    page.set_linked(False)
    assert vb1.linkedView(vb1.YAxis) is None


def test_line_set_linked_no_attribute_error(line_page):
    """PgLineCanvas has _plot_amp/_plot_time, NOT _plot — set_linked must not
    AttributeError, and the amp row's X axis must be linked (X only, no Y)."""
    line_page.enter_split()
    line_page.set_linked(True)  # would AttributeError on a naive ._plot.vb
    vb0 = line_page.pane_canvas(0)._plot_amp.vb
    vb1 = line_page.pane_canvas(1)._plot_amp.vb
    assert vb1.linkedView(vb1.XAxis) is vb0
    # Line sections do NOT Y-link (only heatmaps do).
    assert vb1.linkedView(vb1.YAxis) is None
    line_page.set_linked(False)
    assert vb1.linkedView(vb1.XAxis) is None


def _line_entry(label, *, color="#2563eb", scale=1.0):
    freq = np.linspace(0.0, 200.0, 128)
    time = np.linspace(0.0, 1.0, 160)
    return {
        "label": label,
        "freq": freq,
        "amp": np.sin(freq / 25.0) * scale,
        "time": time,
        "signal": np.cos(time * 10.0) * scale,
        "color": color,
    }


def test_analysis_split_hides_real_card_hint_bars(qtbot, qapp):
    from mf4_analyzer.ui.chart_stack import ChartStack

    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.resize(1000, 620)
    cs.show()
    qtbot.waitExposed(cs)
    cs.set_mode("fft")
    page = cs.page_fft

    page.enter_split()
    qapp.processEvents()

    assert all(card._hint_bar.isHidden() for card in page._cards)

    page.exit_split()
    qapp.processEvents()

    assert page._cards[0]._hint_bar.isVisible()


def test_split_fft_line_plot_areas_align(line_page, qapp):
    """FFT compare panes should align both rows' data rects."""
    line_page.enter_split()
    qapp.processEvents()

    line_page.pane_canvas(0).plot_spectra(
        [_line_entry("short", scale=1.0)],
        xlim=(0.0, 200.0),
        amp_label="Amplitude",
        title="FFT - short",
    )
    line_page.pane_canvas(1).plot_spectra(
        [_line_entry(
            "very_long_channel_name_for_alignment_probe",
            color="#64748b",
            scale=1000.0,
        )],
        xlim=(0.0, 200.0),
        amp_label="Amplitude (x0.001)",
        title="FFT - very_long_channel_name_for_alignment_probe",
    )
    for _ in range(3):
        qapp.processEvents()

    c0 = line_page.pane_canvas(0)
    c1 = line_page.pane_canvas(1)
    amp0 = c0._plot_amp.vb.sceneBoundingRect()
    amp1 = c1._plot_amp.vb.sceneBoundingRect()
    time0 = c0._plot_time.vb.sceneBoundingRect()
    time1 = c1._plot_time.vb.sceneBoundingRect()

    assert amp0.left() == pytest.approx(amp1.left(), abs=1.0)
    assert amp0.width() == pytest.approx(amp1.width(), abs=1.0)
    assert time0.left() == pytest.approx(time1.left(), abs=1.0)
    assert time0.width() == pytest.approx(time1.width(), abs=1.0)
    assert time0.left() == pytest.approx(amp0.left(), abs=1.0)
    assert time0.right() == pytest.approx(amp0.right(), abs=1.0)
    assert time1.left() == pytest.approx(amp1.left(), abs=1.0)
    assert time1.right() == pytest.approx(amp1.right(), abs=1.0)


def test_split_fft_overlay_does_not_shrink_peer_time_preview(line_page, qapp):
    """Solution A: the time-preview overlay Y-axes are a PER-PANE feature.

    Adding overlay sources to ONE pane must NOT inset the OTHER pane's
    time-preview ViewBox. Regression guard for the double-counted right
    reserve: the global-max ``time_right_reserve`` (spacer + overlay axes of
    the busiest pane) used to be pushed onto every pane's right SPACER while
    the overlay axes still occupied their own layout columns — shrinking
    both panes' plot areas.
    """
    line_page.enter_split()
    qapp.processEvents()

    # Pane 0: three sources → two colour-coded overlay right axes.
    line_page.pane_canvas(0).plot_spectra(
        [_line_entry("a", color="#2563eb"),
         _line_entry("b", color="#22c55e"),
         _line_entry("c", color="#f59e0b")],
        xlim=(0.0, 200.0), amp_label="Amplitude", title="multi",
    )
    # Pane 1: single source → no overlay axis.
    line_page.pane_canvas(1).plot_spectra(
        [_line_entry("solo", color="#64748b")],
        xlim=(0.0, 200.0), amp_label="Amplitude", title="solo",
    )
    line_page.sync_heatmap_layouts()
    for _ in range(3):
        qapp.processEvents()

    c0 = line_page.pane_canvas(0)
    c1 = line_page.pane_canvas(1)
    assert len(c0._time_overlay_axes) == 2
    assert len(c1._time_overlay_axes) == 0

    amp1 = c1._plot_amp.vb.sceneBoundingRect()
    time0 = c0._plot_time.vb.sceneBoundingRect()
    time1 = c1._plot_time.vb.sceneBoundingRect()

    # The overlay-free pane keeps its time-preview ViewBox aligned with its
    # OWN amp right edge — it is NOT inset by the other pane's overlay axes.
    assert time1.right() == pytest.approx(amp1.right(), abs=1.5)
    assert time1.width() == pytest.approx(amp1.width(), abs=2.0)
    # And it is genuinely wider than the pane that carries two overlay axes.
    assert time1.width() > time0.width() + 5.0


def test_click_pane_sets_focus(page):
    """eventFilter: a mouse press on pane 1 makes it the focused pane."""
    page.enter_split()
    assert page.focused_index() == 0
    card1 = page._cards[1]
    ev = QMouseEvent(
        QEvent.MouseButtonPress,
        QPointF(5, 5),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    page.eventFilter(card1, ev)
    assert page.focused_index() == 1


def test_focus_signal_emitted(page):
    received = []
    page.focus_changed.connect(received.append)
    page.enter_split()
    page.set_focused_index(1)
    assert received == [1]


# -- V8: locked color levels -----------------------------------------------
def _plot_heat(canvas, peak):
    mm = np.ones((4, 5))
    mm[2, 3] = peak
    canvas.plot_or_update_heatmap(
        matrix=mm, x_extent=(0, 10), y_extent=(0, 8),
        amplitude_mode='amplitude', z_auto=True)


def _slice_result(channel, *, fmax, scale=1.0, unit='g'):
    freqs = np.linspace(0.0, float(fmax), 64)
    times = np.linspace(0.0, 2.0, 20)
    amp = (
        np.random.RandomState(int(scale * 10)).rand(64, 20).astype(np.float32)
        + 0.01
    ) * float(scale)
    return SpectrogramResult(
        times=times,
        frequencies=freqs,
        amplitude=amp,
        params=SpectrogramParams(fs=10000.0, nfft=128),
        channel_name=channel,
        unit=unit,
        metadata={'frames': 20},
    )


def test_split_fft_time_heatmap_and_slice_plot_areas_align(slice_page, qapp):
    """Split FFT-vs-Time must align data plot areas, not just card widths.

    The left pane uses short labels; the right pane forces wider frequency
    ticks and a long title. Before layout synchronization, pyqtgraph gives
    the two pane-internal PlotItems different axis/title reserves, so the
    main heatmaps and the slice rows no longer line up.
    """
    slice_page.enter_split()
    qapp.processEvents()

    slice_page.pane_canvas(0).plot_result(
        _slice_result('short', fmax=500.0, scale=1.0),
        amplitude_mode='amplitude_db',
        z_auto=True,
    )
    slice_page.pane_canvas(1).plot_result(
        _slice_result(
            'very_long_channel_name_for_alignment_probe',
            fmax=5000.0,
            scale=1000.0,
            unit='m/s^2',
        ),
        amplitude_mode='amplitude_db',
        z_auto=True,
    )
    for _ in range(3):
        qapp.processEvents()

    c0 = slice_page.pane_canvas(0)
    c1 = slice_page.pane_canvas(1)
    main0 = c0._plot.vb.sceneBoundingRect()
    main1 = c1._plot.vb.sceneBoundingRect()
    slice0 = c0._slice_plot.vb.sceneBoundingRect()
    slice1 = c1._slice_plot.vb.sceneBoundingRect()

    assert main0.left() == pytest.approx(main1.left(), abs=1.0)
    assert main0.width() == pytest.approx(main1.width(), abs=1.0)
    assert slice0.left() == pytest.approx(slice1.left(), abs=1.0)
    assert slice0.width() == pytest.approx(slice1.width(), abs=1.0)
    for canvas, main_rect, slice_rect in (
        (c0, main0, slice0),
        (c1, main1, slice1),
    ):
        assert slice_rect.left() == pytest.approx(main_rect.left(), abs=1.0)
        assert slice_rect.right() == pytest.approx(main_rect.right(), abs=1.0)
        assert canvas._glw.ci.geometry().width() <= canvas._glw.width() + 1.0


def test_levels_lock_syncs_both_heatmaps(page):
    page.enter_split()
    for i, peak in ((0, 100.0), (1, 50.0)):
        _plot_heat(page.pane_canvas(i), peak)
    page.set_levels_locked(True)
    lo0, hi0 = page.pane_canvas(0)._img.getLevels()
    lo1, hi1 = page.pane_canvas(1)._img.getLevels()
    assert (lo0, hi0) == (lo1, hi1)
    # combined auto range = min/max across BOTH matrices
    assert hi0 == pytest.approx(100.0) and lo0 == pytest.approx(1.0)


def test_levels_drag_propagates_when_locked(page):
    page.enter_split()
    for i in (0, 1):
        _plot_heat(page.pane_canvas(i), 100.0)
    page.set_levels_locked(True)
    page.pane_canvas(0)._cbar.setLevels((5.0, 60.0))   # simulate user drag…
    # …emit like a drag (M2: setLevels is silent; sigLevelsChanged only on
    # interactive region drag). _on_cbar_levels relays to canvas.levels_changed.
    page.pane_canvas(0)._cbar.sigLevelsChanged.emit(page.pane_canvas(0)._cbar)
    # _img.getLevels() returns an ndarray in pg 0.14.0 — unpack to scalars
    # before approx-comparing (an ndarray == tuple yields an array and the
    # bare assert would raise ambiguous-truth).
    lo1, hi1 = page.pane_canvas(1)._img.getLevels()
    assert (lo1, hi1) == (pytest.approx(5.0), pytest.approx(60.0))


def test_levels_unlock_disconnects_propagation(page):
    page.enter_split()
    for i in (0, 1):
        _plot_heat(page.pane_canvas(i), 100.0)
    page.set_levels_locked(True)
    page.set_levels_locked(False)
    # After unlock, a drag on pane 0 must NOT touch pane 1.
    before = tuple(page.pane_canvas(1)._img.getLevels())
    page.pane_canvas(0)._cbar.setLevels((5.0, 60.0))
    page.pane_canvas(0)._cbar.sigLevelsChanged.emit(page.pane_canvas(0)._cbar)
    assert tuple(page.pane_canvas(1)._img.getLevels()) == before


def test_repeated_lock_does_not_multiconnect(page):
    """Re-locking must disconnect first so one drag fires propagation once.

    The propagation handler ``_on_locked_levels_changed`` blocks the
    downstream colorbar signals (so pane 1's own ``levels_changed`` never
    re-fires), making the final ``_img`` value idempotent and unable to
    reveal a multi-connect. Count handler invocations directly instead: a
    single simulated drag must call it exactly once no matter how many
    times the lock was (re)applied."""
    page.enter_split()
    for i in (0, 1):
        _plot_heat(page.pane_canvas(i), 100.0)
    calls = []
    orig = page._on_locked_levels_changed
    page._on_locked_levels_changed = (
        lambda lo, hi: (calls.append((lo, hi)), orig(lo, hi))[1])
    page.set_levels_locked(True)
    page.set_levels_locked(True)  # idempotent re-lock
    page.set_levels_locked(True)
    page.pane_canvas(0)._cbar.setLevels((7.0, 70.0))
    page.pane_canvas(0)._cbar.sigLevelsChanged.emit(page.pane_canvas(0)._cbar)
    # Exactly one propagation despite three locks (disconnect-before-connect).
    assert len(calls) == 1
    lo1, hi1 = page.pane_canvas(1)._img.getLevels()
    assert (lo1, hi1) == (pytest.approx(7.0), pytest.approx(70.0))


# -- V11 Step 0: split combined export -------------------------------------
def _non_white_pixels(pixmap):
    """Count pixels that are not pure white in the pixmap (proxy for content)."""
    img = pixmap.toImage()
    count = 0
    w, h = img.width(), img.height()
    # Sample a coarse grid to stay fast on a 2x bitmap.
    for y in range(0, h, max(1, h // 60)):
        for x in range(0, w, max(1, w // 60)):
            if img.pixel(x, y) & 0x00FFFFFF != 0x00FFFFFF:
                count += 1
    return count


def test_grab_combined_single_pane_matches_pane_width(page):
    """Single pane: grab_combined_pixmap == pane_canvas(0).grab_pixmap width."""
    _plot_heat(page.pane_canvas(0), 100.0)
    page.repaint()
    solo = page.pane_canvas(0).grab_pixmap(scale=2.0)
    combined = page.grab_combined_pixmap(scale=2.0)
    assert combined is not None and not combined.isNull()
    assert combined.width() == solo.width()


def test_grab_combined_split_is_wider_than_single(page):
    """Split: composited width exceeds a single pane's grab (both panes drawn)."""
    page.enter_split()
    for i in (0, 1):
        _plot_heat(page.pane_canvas(i), 100.0)
    page.repaint()
    solo = page.pane_canvas(0).grab_pixmap(scale=2.0)
    combined = page.grab_combined_pixmap(scale=2.0)
    assert combined is not None and not combined.isNull()
    # Two panes + gutter → strictly wider than one pane.
    assert combined.width() > solo.width()
    # Roughly twice as wide (allow gutter + rounding slack).
    assert combined.width() >= 2 * solo.width() - 8


def test_grab_combined_split_has_content_not_all_white(page):
    """The composited bitmap must carry rendered heatmap pixels, not be blank."""
    page.enter_split()
    for i in (0, 1):
        _plot_heat(page.pane_canvas(i), 100.0)
    page.repaint()
    combined = page.grab_combined_pixmap(scale=2.0)
    assert _non_white_pixels(combined) > 0


def test_grab_combined_line_section_split(line_page):
    """FFT (line) section also composites: split width > single pane width."""
    line_page.enter_split()
    line_page.repaint()
    solo = line_page.pane_canvas(0).grab_pixmap(scale=2.0)
    combined = line_page.grab_combined_pixmap(scale=2.0)
    assert combined is not None and not combined.isNull()
    assert combined.width() > solo.width()


# -- V8: compare toggle buttons --------------------------------------------
def test_compare_toggled_signal_x_linked(page):
    """联动缩放 toggle emits compare_toggled('x_linked', bool) on edge."""
    page.enter_split()
    received = []
    page.compare_toggled.connect(lambda k, on: received.append((k, on)))
    page.btn_link.setChecked(False)
    page.btn_link.setChecked(True)
    assert received == [('x_linked', False), ('x_linked', True)]


def test_heatmap_compare_defaults_lock_levels_on(page):
    assert page.btn_lock_levels.isChecked() is True


def test_compare_toggled_signal_levels_locked(page):
    """锁定色阶 toggle emits compare_toggled('levels_locked', bool)."""
    page.enter_split()
    for i in (0, 1):
        _plot_heat(page.pane_canvas(i), 100.0)
    received = []
    page.compare_toggled.connect(lambda k, on: received.append((k, on)))
    page.btn_lock_levels.setChecked(False)
    page.btn_lock_levels.setChecked(True)
    assert received == [('levels_locked', False), ('levels_locked', True)]


def test_levels_lock_button_hidden_for_line_section(line_page):
    """FFT line section has no _img/_cbar → 锁定色阶 button stays hidden."""
    line_page.enter_split()
    assert not line_page.btn_lock_levels.isVisible()
    # 联动缩放 applies to all sections.
    assert line_page.btn_link.isVisible()


def test_compare_buttons_hidden_in_single_pane(page):
    """Both toggles only matter in split; hidden/disabled when one pane."""
    assert not page.btn_link.isVisible()
    assert not page.btn_lock_levels.isVisible()
    page.enter_split()
    assert page.btn_link.isVisible()
    page.exit_split()
    assert not page.btn_link.isVisible()


def test_set_compare_buttons_no_edge_emit(page):
    """Programmatic sync (sync_compare_buttons) must NOT emit compare_toggled
    (state→button, not button→state)."""
    page.enter_split()
    received = []
    page.compare_toggled.connect(lambda k, on: received.append((k, on)))
    page.sync_compare_buttons(x_linked=False, levels_locked=True)
    assert received == []
    assert page.btn_link.isChecked() is False


def test_analysis_tabbar_uses_active_pane_split_controls(page):
    labels = page.tabbar.split_action_labels()
    assert labels['split'] == "添加对比窗格"
    assert labels['replace'] == "添加对比窗格"
    assert labels['clear'] == "关闭对比窗格"
    assert page.tabbar.split_action_mode() == "active_pane"

    assert not page.tabbar._split_clear.isVisible()
    page.enter_split()
    page.tabbar.refresh_split_controls()
    assert page.tabbar._split_clear.isVisible()
    assert page.tabbar._split_clear.text() == "✕ 关闭对比窗格"
    assert page.tabbar._split_clear.toolTip() == "关闭当前 View 的对比窗格"
