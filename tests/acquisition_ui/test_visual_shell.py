"""Structural visual-shell tests for Acquisition Cockpit v3 parity."""

from __future__ import annotations

from PyQt5.QtWidgets import QAction, QLabel, QMenu, QPushButton, QToolButton, QWidget

from mf4_analyzer.acquisition_ui.main_window import (
    DBC_DISABLED_TOOLTIP,
    CockpitMainWindow,
)
from mf4_analyzer.acquisition_ui.state import HealthyPredicateResult


def _mode_buttons(window: CockpitMainWindow) -> dict[str, QPushButton]:
    segment = window.findChild(QWidget, "cockpitModeSegment")
    assert segment is not None
    return {
        button.property("cockpitMode"): button
        for button in segment.findChildren(QPushButton)
    }


def _connect(window: CockpitMainWindow) -> None:
    window.state_machine.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True, xcp_connected=True, first_frame_received=True
        )
    )


def test_toolbar_selectors_and_mode_segment_exist(qapp):
    window = CockpitMainWindow()
    try:
        a2l = window.findChild(QWidget, "cockpitSelectorA2l")
        dbc = window.findChild(QWidget, "cockpitSelectorDbc")
        output = window.findChild(QWidget, "cockpitSelectorOutput")
        segment = window.findChild(QWidget, "cockpitModeSegment")
        toolbar = window.findChild(QWidget, "cockpitToolbarBand")
        rec = window.findChild(QWidget, "cockpitRecIndicator")

        assert toolbar is not None
        assert a2l is not None
        assert dbc is not None
        assert output is not None
        assert segment is not None
        assert toolbar.minimumHeight() == 50
        assert toolbar.maximumHeight() == 50
        assert a2l.minimumHeight() == 28
        assert a2l.maximumHeight() == 28
        assert output.minimumHeight() == 28
        assert output.maximumHeight() == 28
        assert segment.minimumHeight() == 32
        assert segment.maximumHeight() == 32
        assert rec.minimumHeight() == 32
        assert rec.maximumHeight() == 32
        assert window.main_button.minimumHeight() == 36
        assert window.main_button.maximumHeight() == 36
        assert a2l.isEnabled() is True
        assert output.isEnabled() is True
        assert dbc.isEnabled() is False
        assert dbc.toolTip() == DBC_DISABLED_TOOLTIP
        assert set(_mode_buttons(window)) == {"capture", "replay", "history"}
        for selector, key_text, value_text in (
            (a2l, "A2L", "未加载"),
            (dbc, "DBC", "可选"),
            (output, "输出", window._output_dir_label),
        ):
            key_label = selector.findChild(QLabel, "cockpitSelectorKey")
            value_label = selector.findChild(QLabel, "cockpitSelectorValue")
            caret = selector.findChild(QLabel, "cockpitSelectorCaret")
            assert key_label is not None
            assert value_label is not None
            assert caret is not None
            assert key_label.text() == key_text
            assert value_label.text() == value_text
            assert caret.text() == "▾"

        tab_bar = window.mode_tabs.tabBar()
        assert tab_bar.isHidden() or tab_bar.maximumHeight() == 0
    finally:
        window.close()


def test_mode_segment_drives_hidden_tab_widget(qapp):
    window = CockpitMainWindow()
    try:
        buttons = _mode_buttons(window)

        buttons["replay"].click()
        assert window.mode_tabs.currentIndex() == 1
        assert buttons["replay"].isChecked() is True

        buttons["history"].click()
        assert window.mode_tabs.currentIndex() == 2
        assert buttons["history"].isChecked() is True

        buttons["capture"].click()
        assert window.mode_tabs.currentIndex() == 0
        assert buttons["capture"].isChecked() is True
    finally:
        window.close()


def test_main_button_visual_action_properties_follow_state(qapp):
    window = CockpitMainWindow()
    try:
        rec = window.findChild(QWidget, "cockpitRecIndicator")
        assert window.main_button.property("cockpitAction") == "connect"
        assert rec.property("recState") == "off"

        _connect(window)
        assert window.main_button.property("cockpitAction") == "record"
        assert rec.property("recState") == "off"

        window.state_machine.request_start_recording()
        assert window.main_button.property("cockpitAction") == "stop"
        assert rec.property("recState") == "recording"
    finally:
        window.close()


# ---------------------------------------------------------------------------
# P1-2 toolbar overflow + min-size — spec §S4
# ---------------------------------------------------------------------------


def test_main_window_minimum_size(qapp):
    """CockpitMainWindow must declare a minimum size of at least 960x600
    so the toolbar's primary action and REC indicator never clip off-screen
    when the user drags the window narrower than 1100px (spec §S4.2).
    """
    window = CockpitMainWindow()
    try:
        size = window.minimumSize()
        assert size.width() >= 960, (
            f"minimumSize().width() must be >= 960, got {size.width()}"
        )
        assert size.height() >= 600, (
            f"minimumSize().height() must be >= 600, got {size.height()}"
        )
    finally:
        window.close()


def _toolbar_overflow_eligible_children(window: CockpitMainWindow) -> list[QWidget]:
    """Return the toolbar's overflow-eligible direct children (spec §S4.2
    rule: every child except the REC indicator and primary main button).
    """
    toolbar = window.findChild(QWidget, "cockpitToolbarBand")
    assert toolbar is not None
    rec = window.findChild(QWidget, "cockpitRecIndicator")
    main_btn = window.main_button
    children: list[QWidget] = []
    layout = toolbar.layout()
    if layout is None:
        return children
    for i in range(layout.count()):
        item = layout.itemAt(i)
        widget = item.widget() if item is not None else None
        if widget is None:
            continue
        if widget is rec or widget is main_btn:
            continue
        # Skip the overflow chevron itself.
        if widget.objectName() == "cockpitToolbarOverflow":
            continue
        # Skip pure stretch spacers — they don't carry any user
        # affordance and so are not "hidden children" candidates.
        if widget.objectName() == "cockpitToolbarSpacer":
            continue
        children.append(widget)
    return children


def test_toolbar_overflow_at_narrow_width(qapp):
    """At 800px window width the toolbar children must not clip the right
    edge: either the overflow chevron is visible with hidden children
    mirrored into its menu, OR every child fits within the toolbar bounds
    (no child's right edge exceeds outer toolbar width). The first branch
    is the expected outcome for the 800-px forcing-function width."""
    window = CockpitMainWindow()
    try:
        window.resize(800, 600)
        window.show()
        qapp.processEvents()
        toolbar = window.findChild(QWidget, "cockpitToolbarBand")
        assert toolbar is not None
        # Window setMinimumSize(960, 600) clamps the OUTER window above
        # 800px, but the spec §S4.3 matrix explicitly lists 800 as a
        # "forcing-function test value" for the toolbar widget itself.
        # Resize the toolbar directly and re-run the overflow recompute
        # so we exercise the narrow-width branch even when the host
        # window is wider.
        toolbar.resize(800, toolbar.height() or 50)
        window._recompute_toolbar_overflow()
        qapp.processEvents()

        # Compute combined natural width of every overflow-eligible child
        # at construction time (sizeHint width is independent of
        # current visibility).
        eligible = _toolbar_overflow_eligible_children(window)
        combined = sum(max(c.sizeHint().width(), c.minimumWidth()) for c in eligible)
        # Include the always-visible REC indicator + primary button.
        rec = window.findChild(QWidget, "cockpitRecIndicator")
        main_btn = window.main_button
        always_on_w = (
            max(rec.sizeHint().width(), rec.minimumWidth())
            + max(main_btn.sizeHint().width(), main_btn.minimumWidth())
        )
        total = combined + always_on_w

        if total > 800:
            # Expected branch: overflow chevron must be visible and its
            # menu must mirror every currently-hidden eligible child by
            # text().
            overflow_btn = window.findChild(QToolButton, "cockpitToolbarOverflow")
            assert overflow_btn is not None, (
                "toolbar must expose a cockpitToolbarOverflow chevron"
            )
            assert overflow_btn.isVisible() is True, (
                "overflow chevron must be visible when toolbar content overflows"
            )
            menu = overflow_btn.menu()
            assert isinstance(menu, QMenu), (
                "overflow chevron must own a QMenu"
            )
            menu_texts = {action.text() for action in menu.actions()}
            hidden_texts: set[str] = set()
            # Composite affordances (the mode segment) have no .text()
            # of their own; map their objectName to the action label
            # the implementation assigns so the parity check is honest.
            composite_text = {
                "cockpitModeSegment": "模式",
            }
            for child in eligible:
                # Only count widgets demoted *by overflow*, not widgets
                # hidden by state (e.g. the segment marker is invisible
                # during DISCONNECTED by design). The recompute marks
                # overflow-demoted widgets with the dynamic property
                # ``cockpitOverflowHidden = True``.
                if not bool(child.property("cockpitOverflowHidden")):
                    continue
                # Recover the text label of the affordance for
                # comparison. Selectors expose a cockpitSelectorKey
                # QLabel whose text matches the affordance.
                key_label = child.findChild(QLabel, "cockpitSelectorKey")
                if key_label is not None:
                    hidden_texts.add(key_label.text())
                    continue
                # QToolButton / action-backed: use defaultAction text
                # when present, else the widget's own text.
                if isinstance(child, QToolButton):
                    action = child.defaultAction()
                    if isinstance(action, QAction):
                        hidden_texts.add(action.text())
                        continue
                    hidden_texts.add(child.text())
                    continue
                # Composite widget (e.g. mode segment) — fall back to
                # an objectName-keyed mapping.
                obj_name = child.objectName()
                if obj_name in composite_text:
                    hidden_texts.add(composite_text[obj_name])
                    continue
                hidden_texts.add(getattr(child, "text", lambda: "")())
            # Every hidden child must have a corresponding menu entry by
            # text. The menu may also include other entries for
            # always-eligible widgets, so subset rather than equality.
            assert hidden_texts.issubset(menu_texts), (
                f"hidden children {hidden_texts!r} must be mirrored into "
                f"the overflow menu {menu_texts!r}"
            )
        else:
            # Fallback branch (only valid when chrome is small enough to
            # fit): nothing clips beyond the toolbar's outer width.
            outer_right = toolbar.width()
            for child in eligible:
                if not child.isVisible():
                    continue
                right = child.geometry().right()
                assert right <= outer_right, (
                    f"toolbar child {child.objectName()!r} right={right} "
                    f"exceeds toolbar width {outer_right}"
                )
    finally:
        window.close()


def test_toolbar_mode_overflow_uses_submenu(qapp):
    """Code-review follow-up: when the mode segment is demoted into
    the overflow menu, the user must be able to choose a specific
    mode tab. Previously the menu held a single ``模式`` QAction that
    cycled through tabs via ``(currentIndex + 1) % 3`` — round-robin
    advancement with no visible current state. The action must now
    own a submenu with one entry per :data:`MODE_SEGMENTS` label.
    """
    window = CockpitMainWindow()
    try:
        window.resize(800, 600)
        window.show()
        qapp.processEvents()
        toolbar = window.findChild(QWidget, "cockpitToolbarBand")
        assert toolbar is not None
        toolbar.resize(800, toolbar.height() or 50)
        window._recompute_toolbar_overflow()
        qapp.processEvents()

        overflow_btn = window.findChild(QToolButton, "cockpitToolbarOverflow")
        assert overflow_btn is not None
        menu = overflow_btn.menu()
        assert isinstance(menu, QMenu)
        mode_action = next(
            (a for a in menu.actions() if a.text() == "模式"),
            None,
        )
        if mode_action is None:
            # Mode segment fit at this width on this platform — not a
            # failure of the submenu contract, just no demotion to
            # exercise. The companion overflow test guards the actual
            # demotion path.
            return
        sub_menu = mode_action.menu()
        assert sub_menu is not None, (
            "mode action in overflow must own a submenu of the three "
            "MODE_SEGMENTS labels — not a single cycling QAction"
        )
        sub_labels = [a.text() for a in sub_menu.actions()]
        assert sub_labels == ["采集", "回放", "历史"], (
            "expected submenu entries to match MODE_SEGMENTS labels in "
            f"order, got {sub_labels!r}"
        )

        # Click each sub-action and confirm the tab index moves to the
        # chosen value rather than advancing by one.
        for idx, sub_action in enumerate(sub_menu.actions()):
            sub_action.trigger()
            qapp.processEvents()
            assert window._mode_tabs.currentIndex() == idx, (
                f"selecting submenu entry {idx} should set mode tab "
                f"to {idx}, got {window._mode_tabs.currentIndex()}"
            )
    finally:
        window.close()


def test_toolbar_selectors_not_fixed_width(qapp):
    """Selector widgets (A2L / DBC / Output) must use a min+max width
    range, not setFixedWidth. Qt's setFixedWidth(N) collapses
    minimumWidth() and maximumWidth() to the same value N, so asserting
    `minimumWidth() < maximumWidth()` is the precise inverse of
    setFixedWidth.
    """
    window = CockpitMainWindow()
    try:
        for object_name in (
            "cockpitSelectorA2l",
            "cockpitSelectorDbc",
            "cockpitSelectorOutput",
        ):
            btn = window.findChild(QWidget, object_name)
            assert btn is not None, f"missing selector {object_name!r}"
            assert btn.minimumWidth() < btn.maximumWidth(), (
                f"selector {object_name!r} must use min+max width range "
                f"(min={btn.minimumWidth()}, max={btn.maximumWidth()}); "
                f"setFixedWidth collapses both to one value"
            )
    finally:
        window.close()
