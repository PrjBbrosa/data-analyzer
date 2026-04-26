"""Inspector right-side empty-band — splitter stretch-factor verification.

The 2026-04-26 first-pass fix added ``Inspector.setMaximumWidth(376)`` at
``mf4_analyzer/ui/inspector.py:67``. That alone is insufficient: without
``QSplitter.setStretchFactor`` calls, when the window grows beyond the
default 1450px, QSplitter distributes the extra width proportionally to
the current sizes (250:900:360). Even though the Inspector widget renders
only 376px wide, the splitter still allocates the splitter "slot" wider
than 376 — surplus inside that slot looks like an empty column on the
right.

This test pins the assertion at the splitter slot level (not just at
the widget's painted width) so the regression is caught even if a future
change relaxes ``Inspector.setMaximumWidth`` and re-introduces unbounded
growth in the slot.
"""
from PyQt5.QtWidgets import QSplitter

from mf4_analyzer.ui.inspector import _INSPECTOR_CONTENT_MAX_WIDTH
from mf4_analyzer.ui.main_window import MainWindow


_INSPECTOR_SLOT_CAP = _INSPECTOR_CONTENT_MAX_WIDTH + 16  # 376


def test_inspector_splitter_slot_stays_capped_at_wide_window(qapp, qtbot):
    """At an extra-wide 2400px window, the inspector splitter slot must
    not exceed _INSPECTOR_CONTENT_MAX_WIDTH + 16 (376). The chart_stack
    slot must absorb the surplus.

    Without setStretchFactor, sizes() at 2400px width gives roughly
    [394, 1417, 568] (proportional growth: 2400 * 360/1510 ~ 572 for the
    inspector slot, slightly off due to handle widths) — that is the
    pre-fix red state. With setStretchFactor(2, 0) on the inspector slot,
    growth is funneled to chart_stack and the inspector stays around 360.
    """
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(2400, 900)
    win.show()
    qtbot.waitExposed(win)
    qtbot.wait(50)

    # The central widget contains exactly one QSplitter.
    splitters = win.findChildren(QSplitter)
    assert len(splitters) >= 1, "MainWindow must contain a QSplitter"
    splitter = splitters[0]
    assert splitter.count() == 3, (
        f"expected 3-pane splitter, got {splitter.count()} panes"
    )

    sizes = splitter.sizes()
    assert len(sizes) == 3

    # 1. Inspector slot must not exceed the cap. This is the slot width
    # (what QSplitter allocates), NOT inspector.width() — the widget can
    # paint narrower than its slot, leaving a visible empty band that the
    # widget-level cap cannot eliminate.
    assert sizes[2] <= _INSPECTOR_SLOT_CAP, (
        f"inspector splitter slot must not exceed {_INSPECTOR_SLOT_CAP}; "
        f"got {sizes[2]} (navigator={sizes[0]}, chart={sizes[1]}). "
        "Likely cause: missing splitter.setStretchFactor(2, 0)."
    )

    # 2. The chart pane must absorb the surplus. At 2400px window, the
    # chart slot should comfortably exceed 1500px. Pre-fix it would be
    # ~1417 (proportional) — strict > 1500 keeps the assertion red on
    # the broken state and green on the fixed state.
    assert sizes[1] >= 1500, (
        f"chart_stack should absorb extra width at a 2400px window; "
        f"got {sizes[1]} (navigator={sizes[0]}, inspector={sizes[2]}). "
        "Likely cause: missing splitter.setStretchFactor(1, 1)."
    )


def test_inspector_widget_max_width_still_present(qapp, qtbot):
    """Belt-and-braces — the widget-level setMaximumWidth(376) at
    inspector.py:67 must remain in place. Removing it would let any
    future regression in stretch factors silently re-stretch the
    Inspector widget itself."""
    win = MainWindow()
    qtbot.addWidget(win)
    # The Inspector widget itself must be capped at the same slot ceiling.
    assert win.inspector.maximumWidth() == _INSPECTOR_SLOT_CAP, (
        f"Inspector.maximumWidth() expected {_INSPECTOR_SLOT_CAP}, "
        f"got {win.inspector.maximumWidth()}. The 2026-04-26 first-pass "
        "fix at inspector.py:67 may have been reverted."
    )


def test_inspector_splitter_navigator_pinned_at_wide_window(qapp, qtbot):
    """Belt-and-braces using a different signal — the navigator pane is
    NOT capped by a max-width, so without setStretchFactor(0, 0) it
    grows proportionally with window size at large widths. With the
    fix, it stays close to its 250px initial size regardless of window
    width.

    On a 2400px window:
      - pre-fix (no stretch factors): navigator ~ 2400 * 250/1510 = ~397
      - post-fix (stretch=0,1,0):     navigator stays at ~250

    This assertion catches the absence of setStretchFactor calls even
    when the inspector slot itself happens to be capped by the
    Inspector.setMaximumWidth propagation in some Qt builds.
    """
    win = MainWindow()
    qtbot.addWidget(win)
    win.resize(2400, 900)
    win.show()
    qtbot.waitExposed(win)
    qtbot.wait(50)

    splitter = win.findChildren(QSplitter)[0]
    sizes = splitter.sizes()
    # Navigator must stay near its 250px initial size, NOT scale up to ~400.
    # 320 is a safe upper bound: it's well above 250 (allowing layout slack)
    # and well below the ~397 the pre-fix proportional growth would produce.
    assert sizes[0] <= 320, (
        f"navigator splitter slot grew to {sizes[0]} at 2400px window — "
        "expected <= 320 (i.e. close to its 250px initial size). "
        "Likely cause: missing splitter.setStretchFactor(0, 0). Without "
        f"it, growth distributes proportionally (would give ~397). "
        f"sizes={sizes}"
    )
