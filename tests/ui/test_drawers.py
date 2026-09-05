"""Tests for drawer/sheet/popover migrations."""
import numpy as np
from types import SimpleNamespace


class FakeFD:
    filename = "x.mf4"
    channels = ['a', 'b']

    def __init__(self):
        self.channel_units = {}

    class _Data:
        columns = ['a', 'b']
        values = None

    data = _Data()
    time_array = np.linspace(0, 1, 10)

    def get_signal_channels(self):
        return ['a', 'b']


def test_channel_editor_drawer_constructs(qapp):
    from mf4_analyzer.ui.drawers.channel_editor_drawer import ChannelEditorDrawer
    drawer = ChannelEditorDrawer(
        parent=None, files={"f1": FakeFD()}, active_fid="f1"
    )
    assert drawer is not None
    # The dialog exposes the currently-selected fid so the drawer's applied
    # signal can report which file was edited.
    assert drawer._inner.current_fid == "f1"


def test_channel_editor_drawer_switch_file_resets_edit(qapp):
    from mf4_analyzer.ui.drawers.channel_editor_drawer import ChannelEditorDrawer

    fd1, fd2 = FakeFD(), FakeFD()
    drawer = ChannelEditorDrawer(
        parent=None, files={"f1": fd1, "f2": fd2}, active_fid="f1"
    )
    inner = drawer._inner
    inner.new_channels["scratch"] = (np.zeros(10), "")
    # Switch the top file combo to f2 → in-flight edit must reset and the
    # active fid must follow.
    idx = inner.combo_file.findData("f2")
    inner.combo_file.setCurrentIndex(idx)
    assert inner.current_fid == "f2"
    assert inner.new_channels == {}
    assert inner.removed_channels == set()


class _LongNameFD(FakeFD):
    """FakeFD whose channels include a long name that would be cropped by the
    old 178px cap, to exercise the fill-the-row + tooltip behavior."""

    _CHS = ["nominalSteerTorque_xds16", "shortB"]

    def get_signal_channels(self):
        return list(self._CHS)

    class _Data:
        columns = ["nominalSteerTorque_xds16", "shortB"]
        values = None

    data = _Data()


def test_channel_editor_inputs_fill_row_no_right_gutter(qapp, qtbot):
    """The source/A/B combos and the file combo must EXPAND to fill the
    panel width (no 178px cap, no ghost-column gutter on the right). After
    the 2026-06-03 fill pass, inputs are ``QSizePolicy.Expanding`` with the
    input grid column stretched, so their resolved width tracks the panel
    inner width rather than sitting at the old 178px cap.

    422cbc87 added a pinnable ``?`` on the single-op parameter row (same
    cell as the expression editor). The row still fills to combo_src's
    right edge; ``spin_p`` itself stops at the badge, by design.
    """
    from PyQt5.QtCore import QCoreApplication
    from PyQt5.QtWidgets import QSizePolicy
    from mf4_analyzer.ui.drawers.channel_editor_drawer import ChannelEditorDrawer
    from mf4_analyzer.ui_kit import load_stylesheet

    old_sheet = qapp.styleSheet()
    load_stylesheet(qapp)
    try:
        drawer = ChannelEditorDrawer(
            parent=None, files={"f1": _LongNameFD()}, active_fid="f1"
        )
        qtbot.addWidget(drawer)
        drawer.resize(drawer.PANEL_WIDTH, 560)
        drawer.show()
        qtbot.waitExposed(drawer)
        QCoreApplication.processEvents()

        inner = drawer._inner
        for combo in (inner.combo_src, inner.combo_a, inner.combo_b, inner.combo_file):
            # Horizontal policy is Expanding (fill), not Fixed (cap).
            assert combo.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding, (
                f"{combo.objectName() or type(combo).__name__} should Expand to fill "
                f"the row, got {combo.sizePolicy().horizontalPolicy()}"
            )
            # No leftover 178px maximum-width cap (Qt's default 'no cap' sentinel).
            assert combo.maximumWidth() >= 16777215, (
                f"input still capped at maximumWidth={combo.maximumWidth()} — the old "
                f"178px cap must be removed so long names are not cropped"
            )

        # Resolved width: the source combo fills the row — clearly past the
        # retired 178px cap, and a large fraction of the panel inner width
        # (panel 336 minus 2×12px content margins ≈ 312), with no big right
        # gutter. The label column ("源") takes only a small slice.
        inner_w = drawer.PANEL_WIDTH - 24
        assert inner.combo_src.width() > 178, (
            f"combo_src.width()={inner.combo_src.width()} — must exceed the retired "
            f"178px cap so long names are not cropped"
        )
        assert inner.combo_src.width() >= 0.6 * inner_w, (
            f"combo_src.width()={inner.combo_src.width()} should fill most of the "
            f"~{inner_w}px inner width (>= {0.6 * inner_w:.0f}px); a smaller value "
            f"means a right-side gutter is still eating the row"
        )

        def right_in_drawer(widget):
            top_left = widget.mapTo(drawer, widget.rect().topLeft())
            return top_left.x() + widget.width()

        expected_right = right_in_drawer(inner.combo_src)
        # Full-width inputs still share combo_src's right edge. ``spin_p`` is
        # no longer one of them: 422cbc87 put a pinnable ``?`` in the same
        # grid cell (18px badge + 6px spacing), matching the expression row.
        for widget in (
            inner.combo_file,
            inner.combo_op,
            inner._param_row,
            inner.btn_param_help,
            inner.combo_a,
            inner.combo_op2,
            inner.combo_b,
            inner.edit_name2,
            inner.list_export,
        ):
            assert abs(right_in_drawer(widget) - expected_right) <= 1, (
                f"{widget.objectName() or type(widget).__name__} right edge "
                f"{right_in_drawer(widget)} should align with input column "
                f"right edge {expected_right}"
            )
        # The spin fills the cell up to the badge, not past it.
        param_inset = (
            inner.btn_param_help.width()
            + inner._param_row.layout().spacing()
        )
        assert abs(
            right_in_drawer(inner.spin_p) - (expected_right - param_inset)
        ) <= 1, (
            f"spin_p right edge {right_in_drawer(inner.spin_p)} should sit "
            f"{param_inset}px left of the input column ({expected_right}) "
            f"so the parameter ? badge owns the trailing edge"
        )
    finally:
        qapp.setStyleSheet(old_sheet)


def test_channel_editor_combos_have_full_name_tooltip(qapp, qtbot):
    """Hover tooltip on the source/A/B combos shows the full current channel
    name, so a name cropped by the box width is still readable on hover."""
    from PyQt5.QtCore import QCoreApplication
    from mf4_analyzer.ui.drawers.channel_editor_drawer import ChannelEditorDrawer

    drawer = ChannelEditorDrawer(
        parent=None, files={"f1": _LongNameFD()}, active_fid="f1"
    )
    qtbot.addWidget(drawer)
    inner = drawer._inner
    QCoreApplication.processEvents()

    # Initial selection (first channel) gets a seeded tooltip even though
    # signals were blocked during the populate refill.
    for combo in (inner.combo_src, inner.combo_a, inner.combo_b):
        assert combo.toolTip() == "nominalSteerTorque_xds16", (
            f"{type(combo).__name__} initial tooltip={combo.toolTip()!r} should "
            f"be the full current channel name"
        )

    # Changing the selection updates the tooltip via currentTextChanged.
    inner.combo_src.setCurrentText("shortB")
    QCoreApplication.processEvents()
    assert inner.combo_src.toolTip() == "shortB"


def test_export_sheet_constructs(qapp):
    from mf4_analyzer.ui.drawers.export_sheet import ExportSheet
    sheet = ExportSheet(parent=None, chs=["speed", "torque"])
    assert sheet.get_selected() == ["speed", "torque"]  # default all-checked
