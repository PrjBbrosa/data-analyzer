"""Tests for ``mf4_analyzer.ui.drawers.batch.output_panel.OutputPanel``.

W2 of the 2026-05-01 codex-review-fixes plan adds a unit-toggle reset
contract to ``combo_amp_unit`` mirroring the W1 inspector behaviour: the
old unit's numeric Z range must NOT bleed into the new unit. See spec
§1.2 / §1.4 / §1.5.
"""
from __future__ import annotations

import pytest
from PyQt5.QtCore import QPoint, QRect, Qt
from PyQt5.QtGui import QGuiApplication, QValidator
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import (
    QGroupBox, QPushButton, QScrollArea, QStyle, QStyleOptionSlider, QWidget,
)


def _make_panel(qtbot):
    from mf4_analyzer.ui.drawers.batch.output_panel import OutputPanel
    panel = OutputPanel()
    qtbot.addWidget(panel)
    return panel


def _anchor_screen_geometry(anchor: QWidget) -> QRect:
    center = anchor.mapToGlobal(anchor.rect().center())
    screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
    assert screen is not None
    return screen.availableGeometry()


def _assert_popup_inside_screen(popover, available: QRect) -> None:
    frame = popover.frameGeometry()
    assert frame.left() >= available.left() + 8
    assert frame.right() <= available.right() - 8
    assert frame.top() >= available.top() + 8
    assert frame.bottom() <= available.bottom() - 8


def test_batch_output_panel_axis_settings_uses_inspector_layout(qtbot):
    """Batch OUTPUT should use the same roomy axis layout as inspectors."""
    panel = _make_panel(qtbot)

    assert set(panel._axis_row_parts) == {"x", "y", "z"}
    assert panel.findChild(QWidget, "axisHeaderRow") is not None

    z_parts = panel._axis_row_parts["z"]
    # The amplitude unit is deliberately independent from the heatmap-only
    # colour-scale row: FFT line plots still need it when that row is hidden.
    assert z_parts["unit"] is None
    assert panel._amplitude_unit_row is not None
    assert panel.combo_amp_unit.parent() is panel._amplitude_unit_row
    assert panel._axis_row_parts["x"]["label"].minimumWidth() >= 72

    assert z_parts["stack"].currentWidget() is z_parts["summary_page"]
    assert z_parts["summary"].text() == "自动色阶"

    panel.apply_method_defaults("fft_time")
    panel.chk_z_auto.setChecked(False)

    assert z_parts["stack"].currentWidget() is z_parts["manual_page"]
    assert z_parts["spin_min"].isVisibleTo(panel) is True
    assert z_parts["spin_max"].isVisibleTo(panel) is True

    panel.resize(360, 420)
    panel.show()
    qtbot.wait(20)
    unit_top = panel._amplitude_unit_row.mapTo(panel, QPoint(0, 0)).y()
    range_top = z_parts["range_host"].mapTo(panel, QPoint(0, 0)).y()
    # The stable amplitude unit control sits before the heatmap-only Z row.
    assert unit_top < range_top


def test_batch_output_panel_axis_settings_uses_compact_bordered_card(qtbot):
    panel = _make_panel(qtbot)

    group = next(
        gb for gb in panel.findChildren(QGroupBox)
        if gb.property("batchAxisCard") is True
    )

    style = group.styleSheet()
    assert "border: 1px solid #c8d4e3" in style
    assert "border: none" not in style
    assert "background-color: #ffffff" in style
    assert group.title() == "坐标范围"
    assert group.property("batchAxisCard") is True
    assert panel.testAttribute(Qt.WA_StyledBackground) is True
    assert "QWidget#BatchOutputPanel" in panel.styleSheet()
    assert "background-color: #ffffff" in panel.styleSheet()


def test_batch_output_panel_order_time_axis_labels_match_inspector(qtbot):
    panel = _make_panel(qtbot)

    panel.apply_method_defaults("order_time")

    x_parts = panel._axis_row_parts["x"]
    y_parts = panel._axis_row_parts["y"]
    assert x_parts["label"].text() == "时间 (X):"
    assert x_parts["summary"].text() == "全时段"
    assert y_parts["label"].text() == "阶次 (Y):"
    assert y_parts["summary"].text() == "0 → 最大阶次"


def test_batch_output_panel_time_axis_labels(qtbot):
    panel = _make_panel(qtbot)

    panel.apply_method_defaults("time")

    x_parts = panel._axis_row_parts["x"]
    y_parts = panel._axis_row_parts["y"]
    assert x_parts["label"].text() == "时间 (X):"
    assert x_parts["summary"].text() == "全时段"
    assert y_parts["label"].text() == "幅值 (Y):"
    assert y_parts["summary"].text() == "自动范围"
    assert panel._z_axis_row.isHidden() is True
    assert panel._amplitude_unit_row.isHidden() is True


def test_batch_output_panel_keeps_amplitude_unit_visible_for_spectral_methods(qtbot):
    panel = _make_panel(qtbot)

    for method in ("fft", "fft_time", "order_time"):
        panel.apply_method_defaults(method)
        assert panel._amplitude_unit_row.isHidden() is False

    panel.apply_method_defaults("fft")
    panel.combo_amp_unit.setCurrentText("Linear")
    panel.apply_method_defaults("time")
    assert panel._amplitude_unit_row.isHidden() is True

    panel.apply_method_defaults("fft")
    assert panel._amplitude_unit_row.isHidden() is False
    assert panel.combo_amp_unit.currentText() == "Linear"


def test_axis_ranges_are_cached_per_method_without_cross_unit_bleed(qtbot):
    panel = _make_panel(qtbot)

    panel.chk_x_auto.setChecked(False)
    panel.spin_x_min.setValue(5.0)
    panel.spin_x_max.setValue(800.0)

    panel.apply_method_defaults("time")
    assert panel.chk_x_auto.isChecked() is True
    panel.chk_x_auto.setChecked(False)
    panel.spin_x_min.setValue(1.0)
    panel.spin_x_max.setValue(2.0)

    panel.apply_method_defaults("fft")
    assert panel.chk_x_auto.isChecked() is False
    assert panel.spin_x_min.value() == 5.0
    assert panel.spin_x_max.value() == 800.0

    panel.apply_method_defaults("time")
    assert panel.spin_x_min.value() == 1.0
    assert panel.spin_x_max.value() == 2.0


def test_batch_output_x_axis_context_is_presentation_only(qtbot):
    """A synchronized X label must not dirty the portable output recipe."""
    panel = _make_panel(qtbot)
    panel.apply_method_defaults("time")
    changed = []
    panel.changed.connect(lambda: changed.append(True))

    panel.set_x_axis_context(label="Time", unit="s")
    assert panel._axis_row_parts["x"]["label"].text() == "Time (s)"

    panel.set_x_axis_context(label="engine_speed", unit="rpm")
    assert panel._axis_row_parts["x"]["label"].text() == "engine_speed (rpm)"
    assert panel.spin_x_min.suffix() == " rpm"
    assert panel.spin_x_max.suffix() == " rpm"
    assert changed == []


def test_batch_output_panel_unit_toggle_resets_z_range_db_to_linear(qtbot):
    """dB → Linear: floor/ceiling reset to (0, 1), z_auto re-enabled,
    spinboxes disabled, ``changed`` emitted exactly once.

    Pins all five §1.2 invariants plus the W2 emit-once mitigation
    (§5 风险 OutputPanel emits).
    """
    panel = _make_panel(qtbot)
    # Default unit is dB; lock a manual dB range first.
    assert panel.combo_amp_unit.currentText() == "dB"
    panel.chk_z_auto.setChecked(False)
    panel.spin_z_floor.setValue(-30.0)
    panel.spin_z_ceiling.setValue(0.0)

    # Counter from now (drop pre-toggle emits).
    emits = []
    panel.changed.connect(lambda: emits.append(1))

    panel.combo_amp_unit.setCurrentText("Linear")

    # §1.2 invariants
    assert panel.chk_z_auto.isChecked() is True
    assert panel.spin_z_floor.value() == 0.0
    assert panel.spin_z_ceiling.value() == 1.0
    assert panel.spin_z_floor.isEnabled() is False
    assert panel.spin_z_ceiling.isEnabled() is False

    # §5 risk mitigation: emit-once (not 3+ from chk + spin + spin + combo).
    assert len(emits) == 1, (
        f"changed should emit once on unit toggle, got {len(emits)}"
    )


def test_batch_output_panel_unit_toggle_resets_z_range_linear_to_db(qtbot):
    """Reverse direction: Linear → dB resets floor/ceiling to (-30, 0)."""
    panel = _make_panel(qtbot)
    # Switch to Linear first (without asserting reset behaviour here —
    # that is covered by the dB→Linear test). Block the combo signal so
    # this setup does NOT pre-trigger the W2 reset handler.
    panel.combo_amp_unit.blockSignals(True)
    panel.combo_amp_unit.setCurrentText("Linear")
    panel.combo_amp_unit.blockSignals(False)
    panel.chk_z_auto.setChecked(False)
    panel.spin_z_floor.setValue(0.2)
    panel.spin_z_ceiling.setValue(0.9)

    emits = []
    panel.changed.connect(lambda: emits.append(1))

    panel.combo_amp_unit.setCurrentText("dB")

    assert panel.chk_z_auto.isChecked() is True
    assert panel.spin_z_floor.value() == -30.0
    assert panel.spin_z_ceiling.value() == 0.0
    assert panel.spin_z_floor.isEnabled() is False
    assert panel.spin_z_ceiling.isEnabled() is False
    assert len(emits) == 1


def test_batch_output_panel_apply_axis_params_does_not_trigger_reset(qtbot):
    """Preset load via ``apply_axis_params`` MUST NOT trigger the
    unit-toggle reset handler — otherwise the user's persisted
    ``z_floor`` / ``z_ceiling`` get wiped to the defaults the moment a
    preset comes back from disk.

    This is the strong RED case for §1.5 边界: the handler is wired
    on user-driven ``currentTextChanged``, but ``setCurrentIndex`` from
    a programmatic preset loader must round-trip the user's numbers
    intact AND must NOT fire the W2 reset handler (otherwise the
    handler emits ``changed`` and dirties the batch preset for an
    operation the user did not initiate).

    Strong-RED proof: removing the ``blockSignals(True/False)`` wrap
    around ``combo_amp_unit.setCurrentIndex`` in ``apply_axis_params``
    causes ``_on_amp_unit_changed`` to fire on the cross-unit preset
    apply, which both (a) emits a spurious ``changed`` and (b) the
    handler runs ``self.changed.emit()`` — bringing the assertion
    ``len(emits) == 0`` below to FAIL. Verified locally during W2
    development.
    """
    panel = _make_panel(qtbot)
    # First preset: stays on dB but pins a non-default range.
    params = {
        "x_auto": False, "x_min": 1.0, "x_max": 2.0,
        "y_auto": False, "y_min": 3.0, "y_max": 4.0,
        "z_auto": False, "z_floor": -50.0, "z_ceiling": -10.0,
        "amplitude_mode": "amplitude_db",
    }
    panel.apply_axis_params(params)

    assert panel.chk_z_auto.isChecked() is False
    assert panel.spin_z_floor.value() == -50.0
    assert panel.spin_z_ceiling.value() == -10.0
    assert panel.combo_amp_unit.currentText() == "dB"

    # Second preset: Linear unit + custom ranges. This is the cross-unit
    # apply that WOULD trip ``_on_amp_unit_changed`` if combo's
    # ``setCurrentIndex`` were not wrapped in ``blockSignals``.
    params2 = {
        "z_auto": False, "z_floor": 0.05, "z_ceiling": 0.75,
        "amplitude_mode": "amplitude",
    }

    # Counter: the W2 reset handler MUST NOT run during a programmatic
    # preset load. We replace ``_on_amp_unit_changed`` with a counter so
    # we can detect whether ``combo_amp_unit.setCurrentIndex`` slipped
    # past ``blockSignals`` (which would re-trigger the dB↔Linear reset
    # and clobber the preset's z_floor/z_ceiling).
    handler_calls = []
    real_handler = panel._on_amp_unit_changed

    def _spy(text):
        handler_calls.append(text)
        return real_handler(text)
    panel._on_amp_unit_changed = _spy
    # Re-wire so the spy actually receives the signal — the original
    # connection captured the bound method by reference.
    try:
        panel.combo_amp_unit.currentTextChanged.disconnect(real_handler)
    except TypeError:
        pass
    panel.combo_amp_unit.currentTextChanged.connect(_spy)

    panel.apply_axis_params(params2)

    assert panel.combo_amp_unit.currentText() == "Linear"
    assert panel.chk_z_auto.isChecked() is False
    assert panel.spin_z_floor.value() == pytest.approx(0.05)
    assert panel.spin_z_ceiling.value() == pytest.approx(0.75)
    # Strong-RED pin: handler must not run on programmatic combo set.
    # Verified: removing blockSignals around setCurrentIndex causes
    # this to be ['Linear'] (1 call) and the per-W2 reset clobbers
    # spin_z_floor/ceiling to (-30, 0) instead of (0.05, 0.75).
    assert handler_calls == [], (
        "_on_amp_unit_changed must not fire on programmatic preset "
        f"apply; got calls={handler_calls!r} — combo_amp_unit."
        "setCurrentIndex likely missing blockSignals wrap."
    )


def test_batch_output_panel_manual_y_range_accepts_negative_values(qtbot):
    panel = _make_panel(qtbot)

    panel.chk_y_auto.setChecked(False)
    panel.spin_y_min.setValue(-120.0)
    panel.spin_y_max.setValue(-20.0)

    assert panel.spin_y_min.value() == -120.0
    assert panel.spin_y_max.value() == -20.0
    assert panel.axis_params()["y_min"] == -120.0


def test_batch_output_panel_manual_x_range_accepts_typed_negative_values(qtbot):
    """A channel on X (rack travel) is signed, so "-" must be typeable.

    A ``QDoubleSpinBox`` with ``minimum == 0`` rejects "-" in ``validate()``,
    which silently swallows the keystroke instead of showing an error, so this
    asserts the range rather than only the resulting value.
    """
    panel = _make_panel(qtbot)
    panel.apply_method_defaults("time")
    panel.set_x_axis_context(label="Weg", unit="mm")

    assert panel.spin_x_min.minimum() < 0.0
    assert panel.spin_x_max.minimum() < 0.0
    assert panel.spin_x_min.validate("-100.0 mm", 0)[0] != QValidator.Invalid

    panel.chk_x_auto.setChecked(False)
    panel.spin_x_min.setValue(-100.0)
    panel.spin_x_max.setValue(-10.0)

    assert panel.axis_params()["x_min"] == -100.0
    assert panel.axis_params()["x_max"] == -10.0

    # The reported symptom was specifically about typing: "-" first, then the
    # digits refused to land. validate() alone would still pass if some future
    # input mask or key handler swallowed the sign, so drive real key events.
    for spin, typed in ((panel.spin_x_min, "-100.5"), (panel.spin_x_max, "-80")):
        spin.setFocus()
        spin.selectAll()
        QTest.keyClick(spin, Qt.Key_Delete)
        QTest.keyClicks(spin, typed)
        QTest.keyClick(spin, Qt.Key_Return)
        assert spin.value() == pytest.approx(float(typed)), (
            f"typing {typed!r} landed as {spin.text()!r}"
        )

    assert panel.axis_params()["x_min"] == pytest.approx(-100.5)


def test_batch_output_render_style_round_trips_and_reports_changes(qtbot):
    from mf4_analyzer.batch_render_style import MAX_FONT_SCALE, RenderStyle

    panel = _make_panel(qtbot)
    default = RenderStyle()

    assert panel.render_style_params() == default.as_params()

    with qtbot.waitSignal(panel.changed, timeout=500):
        panel._on_render_style_changed(
            RenderStyle(tick_density_x=24, tick_density_y=16, font_scale=1.5)
        )
    assert panel.render_style_params() == {
        "tick_density_x": 24,
        "tick_density_y": 16,
        "font_scale": 1.5,
    }
    assert "24" in panel._render_style_summary.text()
    assert "150%" in panel._render_style_summary.text()

    # Partial apply: an absent key keeps its current value.
    panel.apply_render_style_params({"tick_density_x": 9})
    assert panel.render_style_params() == {
        "tick_density_x": 9,
        "tick_density_y": 16,
        "font_scale": 1.5,
    }
    # A hand-edited recipe must never abort a run: out-of-range clamps,
    # non-numeric falls back to the default.
    panel.apply_render_style_params({"font_scale": 99.0})
    assert panel.render_style_params()["font_scale"] == MAX_FONT_SCALE
    panel.apply_render_style_params({"font_scale": "huge"})
    assert panel.render_style_params()["font_scale"] == default.font_scale


def test_batch_output_render_style_button_opens_a_popover(qtbot):
    from mf4_analyzer.batch_render_style import RenderStyle

    panel = _make_panel(qtbot)
    button = panel.findChild(QPushButton, "batchRenderStyleButton")
    assert button is not None
    assert button.isVisibleTo(panel)

    panel._on_render_style_clicked()
    popover = panel._render_style_popover
    assert popover is not None
    assert popover.style() == RenderStyle()

    with qtbot.waitSignal(panel.changed, timeout=500):
        popover.set_style(RenderStyle(tick_density_x=8, tick_density_y=6), emit=True)
    assert panel.render_style_params()["tick_density_x"] == 8

    # Re-applying from a preset keeps the open popover in sync.
    panel.apply_render_style_params({"tick_density_x": 24, "tick_density_y": 16})
    assert popover.style().tick_density_x == 24


def test_batch_render_style_popover_clamps_to_anchor_screen_edges_and_reopens(
    qtbot,
):
    """Real Qt geometry: both screen corners stay in-bounds and stable."""
    from mf4_analyzer.ui.drawers.batch.render_style_popover import (
        RenderStylePopover,
    )

    host = QWidget()
    host.resize(64, 44)
    anchor = QPushButton("刻度", host)
    anchor.resize(48, 28)
    anchor.move(8, 8)
    qtbot.addWidget(host)
    popover = RenderStylePopover(host)
    qtbot.addWidget(popover)

    available = _anchor_screen_geometry(host)
    host.move(available.left(), available.top())
    host.show()
    qtbot.wait(20)
    popover.show_at(anchor)
    qtbot.wait(20)
    _assert_popup_inside_screen(popover, _anchor_screen_geometry(anchor))
    assert popover.frameGeometry().top() >= anchor.mapToGlobal(
        anchor.rect().bottomLeft()
    ).y()
    popover.hide()

    host.move(
        available.right() - host.width() + 1,
        available.bottom() - host.height() + 1,
    )
    qtbot.wait(20)
    popover.show_at(anchor)
    qtbot.wait(20)
    anchor_top = anchor.mapToGlobal(anchor.rect().topLeft()).y()
    _assert_popup_inside_screen(popover, _anchor_screen_geometry(anchor))
    assert popover.frameGeometry().bottom() + 4 < anchor_top

    positions = []
    for _unused in range(3):
        popover.hide()
        popover.show_at(anchor)
        qtbot.wait(10)
        positions.append(popover.pos())
    assert positions == [positions[0]] * 3


def test_batch_render_style_popover_clamps_negative_screen_when_neither_side_fits(
    qtbot, monkeypatch,
):
    """The fallback geometry path is deterministic on a negative monitor."""
    from mf4_analyzer.ui.drawers.batch.render_style_popover import (
        RenderStylePopover,
    )

    host = QWidget()
    host.resize(64, 44)
    anchor = QPushButton("刻度", host)
    anchor.resize(48, 28)
    anchor.move(0, 8)
    qtbot.addWidget(host)
    popover = RenderStylePopover(host)
    qtbot.addWidget(popover)
    popover.adjustSize()
    available = QRect(-1200, 40, 600, popover.height() + 32)
    host.move(available.left() + 2, available.center().y() - host.height() // 2)
    host.show()
    qtbot.wait(20)
    monkeypatch.setattr(
        popover, "_available_geometry_for", lambda _anchor: available,
    )

    popover.show_at(anchor)
    qtbot.wait(20)

    _assert_popup_inside_screen(popover, available)
    assert popover.frameGeometry().left() == available.left() + 8
    assert popover.frameGeometry().top() == (
        available.bottom() - 8 - popover.height() + 1
    )


def test_batch_output_render_style_popover_closes_when_host_moves_or_resizes(qtbot):
    panel = _make_panel(qtbot)
    panel.resize(430, 720)
    panel.show()
    qtbot.wait(20)

    panel._on_render_style_clicked()
    popover = panel._render_style_popover
    assert popover.isVisible()
    assert panel._btn_render_style.isChecked()

    panel.move(panel.pos() + QPoint(30, 0))
    qtbot.wait(20)
    assert not popover.isVisible()
    assert not panel._btn_render_style.isChecked()

    panel._on_render_style_clicked()
    assert popover.isVisible()
    panel.resize(440, 720)
    qtbot.wait(20)
    assert not popover.isVisible()
    assert not panel._btn_render_style.isChecked()


def test_batch_output_render_style_popover_closes_when_output_pane_scrolls(qtbot):
    from mf4_analyzer.ui.drawers.batch.output_panel import OutputPanel

    scroll = QScrollArea()
    content = QWidget()
    content.resize(430, 1200)
    panel = OutputPanel(content)
    panel.setGeometry(0, 0, 420, 720)
    scroll.setWidget(content)
    scroll.resize(360, 300)
    qtbot.addWidget(scroll)
    scroll.show()
    qtbot.wait(20)

    anchor = panel._btn_render_style
    scroll.ensureWidgetVisible(anchor)
    qtbot.wait(20)
    panel._on_render_style_clicked()
    popover = panel._render_style_popover
    assert popover.isVisible()

    bar = scroll.verticalScrollBar()
    target = min(bar.maximum(), bar.value() + 30)
    assert target > bar.value()
    bar.setValue(target)
    qtbot.wait(20)

    assert not popover.isVisible()
    assert not panel._btn_render_style.isChecked()


@pytest.mark.parametrize(
    ("slider_name", "spin_name", "param_name"),
    (
        ("_slider_x", "_spin_x", "tick_density_x"),
        ("_slider_y", "_spin_y", "tick_density_y"),
        ("_slider_font", "_spin_font", "font_scale"),
    ),
)
def test_batch_render_style_sliders_drag_and_sync_to_recipe(
    qtbot, slider_name, spin_name, param_name,
):
    panel = _make_panel(qtbot)
    panel.resize(430, 720)
    panel.show()
    panel._on_render_style_clicked()
    popover = panel._render_style_popover
    popover.show()
    qtbot.wait(20)

    slider = getattr(popover, slider_name)
    spin = getattr(popover, spin_name)
    start = slider.value()
    emissions = []
    panel.changed.connect(lambda: emissions.append(panel.render_style()))
    option = QStyleOptionSlider()
    slider.initStyleOption(option)
    handle = slider.style().subControlRect(
        QStyle.CC_Slider, option, QStyle.SC_SliderHandle, slider,
    )
    target = QPoint(slider.width() - 5, handle.center().y())

    QTest.mousePress(slider, Qt.LeftButton, pos=handle.center())
    QTest.mouseMove(slider, target, delay=10)
    QTest.mouseRelease(slider, Qt.LeftButton, pos=target)
    qtbot.wait(20)

    assert slider.value() != start
    assert spin.value() == slider.value()
    assert len(emissions) == 1
    expected = slider.value() / 100.0 if param_name == "font_scale" else slider.value()
    assert panel.render_style_params()[param_name] == pytest.approx(expected)
    assert str(slider.value()) in panel._render_style_summary.text()

    popover.hide()
    panel._on_render_style_clicked()
    qtbot.wait(20)
    assert getattr(popover, slider_name).value() == slider.value()
    assert getattr(popover, spin_name).value() == slider.value()


def test_batch_output_db_reference_auto_manual_round_trip_and_legacy(qtbot):
    panel = _make_panel(qtbot)

    panel.apply_reference_params({
        "db_reference_mode": "manual", "db_reference": 2e-5,
    })
    got = panel.reference_params()
    assert got["db_reference_mode"] == "manual"
    assert got["db_reference"] == pytest.approx(2e-5)

    panel.apply_reference_params({"db_reference_mode": "auto"})
    got = panel.reference_params()
    assert got["db_reference_mode"] == "auto"
    assert got["db_reference"] == pytest.approx(2e-5)

    panel.apply_reference_params({"db_reference": 1e-6}, legacy=True)
    got = panel.reference_params()
    assert got["db_reference_mode"] == "manual"
    assert got["db_reference"] == pytest.approx(1e-6)


def test_batch_output_effective_preview_uses_shared_dba_formatter(qtbot):
    from types import SimpleNamespace

    panel = _make_panel(qtbot)
    rows = (
        SimpleNamespace(
            state="loaded", source_id="s1", channels=frozenset({"acc"}),
            units={"acc": "m/s2"}, metadata={},
        ),
        SimpleNamespace(
            state="loaded", source_id="s2", channels=frozenset({"acc"}),
            units={"acc": "m/s2"}, metadata={},
        ),
    )
    panel.update_effective_preview(
        rows, ("acc",), weighting="A", target_policy="common",
    )

    text = panel.effective_preview_text()
    assert "2×system" in text
    assert "dBA re" in text


def test_batch_output_preview_waits_while_probe_is_pending(qtbot):
    from types import SimpleNamespace

    panel = _make_panel(qtbot)
    panel.update_effective_preview(
        (SimpleNamespace(state="probing"),), ("acc",), weighting="None",
        target_policy="common",
    )
    assert panel.effective_preview_text() == "等待来源信息"


def test_batch_output_exact_preview_excludes_missing_pair_targets(qtbot):
    from types import SimpleNamespace

    panel = _make_panel(qtbot)
    rows = (
        SimpleNamespace(
            state="loaded", source_id="s1", channels=frozenset({"A"}),
            units={"A": "Pa"}, metadata={},
        ),
        SimpleNamespace(
            state="loaded", source_id="s2", channels=frozenset({"C"}),
            units={"C": "Pa"}, metadata={},
        ),
    )

    panel.update_effective_preview(
        rows, ("A", "B"), target_policy="exact_pairs",
        target_pairs=(("s1", "A"), ("s2", "B")),
    )

    assert panel.effective_preview_text().startswith("1 个目标：")


def test_batch_output_import_migrates_to_the_fixed_interactive_contract(qtbot):
    from mf4_analyzer.batch import BatchOutput

    panel = _make_panel(qtbot)
    outputs = BatchOutput(
        export_data=False,
        export_image=True,
        data_format="xlsx",
        image_format="png",
        image_size="custom",
        image_width=3210,
        image_height=1870,
        image_dpi=288,
        image_background="transparent",
        image_line_width=1.5,
        conflict_policy="overwrite",
        write_manifest=False,
        resume_policy="manifest",
    )

    panel.apply_outputs(outputs)

    compact = panel.get_outputs()
    assert compact.export_data is False
    assert compact.export_image is True
    assert compact.data_format == "xlsx"
    assert compact.image_format == "png"
    assert (compact.image_width, compact.image_height) == (1920, 1080)
    assert compact.conflict_policy == "auto_number"
    assert compact.write_manifest is True
    assert compact.resume_policy == "none"
    assert panel.export_data() is outputs.export_data
    assert panel.export_image() is outputs.export_image
    assert panel.data_format() == "xlsx"


def test_batch_output_hides_advanced_controls_and_has_no_recovery_surface(qtbot):
    panel = _make_panel(qtbot)

    assert panel._output_settings.isHidden()
    assert not panel._btn_output_settings.isVisible()
    assert not hasattr(panel, "resumeRequested")
    assert not hasattr(panel, "retryFailedRequested")
    assert not hasattr(panel, "_btn_resume")
    assert not hasattr(panel, "_btn_retry_failed")
    assert "PNG 1920×1080" in panel._output_summary.text()
    assert "冲突自动编号" in panel._output_summary.text()

    panel._btn_output_settings.click()
    assert panel._output_settings.isHidden()


def test_batch_output_summary_stays_fixed_after_legacy_import(qtbot):
    from mf4_analyzer.batch import BatchOutput

    panel = _make_panel(qtbot)
    panel.apply_outputs(BatchOutput(
        data_format="xlsx",
        image_format="png",
        image_size="2560x1440",
        image_background="dark",
        image_line_width=2.0,
    ))

    summary = panel._output_summary.text()
    assert "XLSX" in summary
    assert "PNG 1920×1080" in summary
    assert "SVG" not in summary
    assert "2560×1440" not in summary


def test_batch_output_uses_the_canonical_line_width(qtbot):
    from mf4_analyzer.batch import BatchOutput

    panel = _make_panel(qtbot)
    panel.apply_outputs(BatchOutput(image_line_width=3.25))

    assert panel.get_outputs().image_line_width == pytest.approx(1.5)
    assert panel._combo_image_line_width.isHidden()


def test_batch_output_checkboxes_only_choose_fixed_artifacts(qtbot):
    from mf4_analyzer.batch import BatchOutput

    panel = _make_panel(qtbot)
    panel._chk_image.setChecked(False)
    outputs = panel.get_outputs()
    assert outputs.export_image is False
    assert outputs.export_data is True
    assert (outputs.image_width, outputs.image_height) == (1920, 1080)
    assert panel._combo_image_format.isHidden()
    assert panel._combo_image_size.isHidden()


def test_batch_output_panel_fits_288px_column(qtbot):
    panel = _make_panel(qtbot)
    panel.resize(288, 900)
    panel.show()
    qtbot.wait(5)

    assert panel.minimumSizeHint().width() <= 288
    assert panel.width() <= 288


def test_batch_output_fixed_contract_fits_288px_column(qtbot):
    panel = _make_panel(qtbot)
    panel.resize(288, 1200)
    panel.show()
    qtbot.wait(20)

    assert panel.minimumSizeHint().width() <= 288
    assert panel._output_summary.width() <= panel.width()


def test_export_card_lays_out_at_usable_width(qtbot):
    """导出内容 card must not collapse — guard the two causes, not the pixels.

    On the native macOS style the card rendered at width 0, taking the
    数据文件 / 图片 checkboxes (6px, labels elided away) and the summary line
    with it. Two things were needed, and a policy matrix over both platforms
    shows why this test asserts properties rather than only widths:

        style        Ignored+default  Ignored+Grow  Expanding+default  both
        fusion            287             287             287          287
        macintosh           0             283             146          283

    Under offscreen/fusion the bug does not reproduce at all, so a width-only
    assertion would have passed before the fix and guards nothing. The growth
    policy below is platform-independent and is the actual fix.

    Note the card's own ``Ignored`` horizontal policy is NOT the culprit and
    must stay: it is what keeps the panel's minimumSizeHint at zero for the
    288px column contract, and it already carries ExpandFlag, so the field
    grows the moment the form's growth policy permits it.
    """
    from PyQt5.QtWidgets import QFormLayout, QSizePolicy, QStyle
    from mf4_analyzer.ui.drawers.batch.output_panel import OutputPanel

    panel = OutputPanel()
    qtbot.addWidget(panel)
    card = next(
        w for w in panel.findChildren(QWidget)
        if w.objectName() == "BatchExportCard"
    )

    # macOS defaults QFormLayout to FieldsStayAtSizeHint, which parks the
    # field at its sizeHint — 0 for an Ignored policy — instead of filling
    # the column.
    assert panel._output_form.fieldGrowthPolicy() == QFormLayout.ExpandingFieldsGrow
    # The narrow-column contract must survive the fix.
    assert card.sizePolicy().horizontalPolicy() == QSizePolicy.Ignored
    assert panel.minimumSizeHint().width() <= 288

    for width in (384, 300):
        panel.resize(width, 640)
        panel.show()
        qtbot.wait(20)
        assert card.width() > 0, width
        # Room for both labels plus the gap between them.
        assert card.width() >= (
            panel._chk_data.sizeHint().width()
            + panel._chk_image.sizeHint().width()
        ), (width, card.width())
        # Labels must not be elided away. In the failure mode the checkboxes
        # were 6px and 5px — indicator only, every glyph gone. A little
        # squeeze in the narrow column is fine; losing the text is not.
        indicator = panel._chk_data.style().pixelMetric(
            QStyle.PM_IndicatorWidth, None, panel._chk_data,
        )
        assert panel._chk_data.width() > indicator * 2, (
            width, panel._chk_data.width(), indicator,
        )
        assert panel._chk_image.width() > indicator * 2
        # ...and must not overlap each other.
        data_right = panel._chk_data.geometry().right()
        assert panel._chk_image.geometry().left() > data_right, (
            width, panel._chk_data.geometry(), panel._chk_image.geometry(),
        )
        assert panel._output_summary.width() > 0
