"""The footer's left rotation must not lead with the same hint on every open.

The pool ordering still leads with the high-weight anchor (Ctrl/Shift + 滚轮),
but the card enters the lap at a persisted, round-robin *start offset* that
advances each session — so a fresh open shows a different gesture first instead
of always the wheel-zoom anchor.
"""
import numpy as np
from PyQt5.QtCore import QCoreApplication, QSettings

from mf4_analyzer.ui import hints
from mf4_analyzer.ui.chart_stack.cards import TimeChartCard
from mf4_analyzer.ui.pg_canvas.canvas import TimeDomainCanvasPG


def test_next_rotation_start_round_robins_and_persists(tmp_path):
    path = str(tmp_path / "r.ini")
    s = QSettings(path, QSettings.IniFormat)
    assert hints.next_rotation_start(s) == 0
    assert hints.next_rotation_start(s) == 1
    assert hints.next_rotation_start(s) == 2
    # A new handle on the same store keeps counting (persisted across sessions).
    s2 = QSettings(path, QSettings.IniFormat)
    assert hints.next_rotation_start(s2) == 3


def test_next_rotation_start_tolerates_garbage_value(tmp_path):
    s = QSettings(str(tmp_path / "r2.ini"), QSettings.IniFormat)
    s.setValue(hints.ROTATION_START_KEY, "not-an-int")
    s.sync()
    assert hints.next_rotation_start(s) == 0  # resets cleanly, no crash


def _rows(n):
    t = np.linspace(0.0, 10.0, 4000)
    return [
        (f"ch{i}", True, t, np.sin(t * (i + 1)), "#1769e0", "u", f"fid-{i}")
        for i in range(n)
    ]


def test_card_enters_lap_at_persisted_offset_not_the_anchor(qapp, qtbot, tmp_path):
    s = QSettings(str(tmp_path / "r3.ini"), QSettings.IniFormat)
    s.setValue(hints.ROTATION_START_KEY, 1)  # pre-seed: start one past the anchor
    s.sync()

    canvas = TimeDomainCanvasPG()
    card = TimeChartCard(canvas)
    qtbot.addWidget(card)
    card.set_hint_settings(s)
    card.set_plot_mode("subplot")
    canvas.plot_channels(_rows(2), mode="subplot")
    QCoreApplication.processEvents()

    pool = card._rotation_candidates()
    assert len(pool) >= 2
    assert pool[0].id.startswith("anchor.")             # anchor still leads pool
    # …but the card enters at offset 1, so it does NOT lead with the anchor.
    # (The left slot elides on a narrow card, so assert on the index + that the
    # shown text is not the wheel-zoom anchor rather than the full string.)
    assert card._context_hint_index == 1 % len(pool)
    assert not card._hint_context.text().startswith("Ctrl")


def test_two_sessions_start_on_different_hints(qapp, qtbot, tmp_path):
    path = str(tmp_path / "r4.ini")

    def first_shown():
        s = QSettings(path, QSettings.IniFormat)
        canvas = TimeDomainCanvasPG()
        card = TimeChartCard(canvas)
        qtbot.addWidget(card)
        card.set_hint_settings(s)
        card.set_plot_mode("subplot")
        canvas.plot_channels(_rows(2), mode="subplot")
        QCoreApplication.processEvents()
        return card._hint_context.text()

    # Two consecutive "opens" against the same persisted store advance the
    # offset, so the first-shown hint differs between them.
    assert first_shown() != first_shown()
