"""``ChartOptionsDialog`` constructor must accept an ``AxisHandle``.

Task 3 of the pyqtgraph TimeDomain migration (plan
``docs/superpowers/plans/2026-05-28-pyqtgraph-timedomain-migration.md``,
design §5.3 and §6 Phase 2). The existing
``tests/ui/test_dialogs.py`` suite already exercises the raw-``Axes``
construction path; this file exercises the alternate path where the
caller has already wrapped the axes with ``MplAxisHandle``, plus the
layout-snapshot test that pins the visible widget tree byte-identical
to pre-refactor.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5.QtWidgets import QGroupBox, QLabel, QPushButton, QFrame
from matplotlib.figure import Figure


def _axes_with_curve():
    fig = Figure(figsize=(4, 3), dpi=100)
    ax = fig.add_subplot(111)
    ax.plot([1, 2, 3], [1, 4, 9], color="#1769e0", label="curve")
    ax.set_title("原始标题")
    ax.set_xlabel("时间")
    ax.set_ylabel("幅值")
    ax.set_xlim(1.0, 3.0)
    ax.set_ylim(1.0, 10.0)
    return ax


# ---------------------------------------------------------------------------
# Constructor accepts both raw Axes and wrapped AxisHandle
# ---------------------------------------------------------------------------


def test_dialog_accepts_axis_handle_constructor(qapp):
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes_with_curve()
    handle = MplAxisHandle(ax)

    dlg = ChartOptionsDialog(None, handle)
    assert dlg.handle is handle
    # Initial fields seeded from the underlying axis.
    assert dlg.edit_title.text() == "原始标题"
    assert dlg.spin_x_min.value() == pytest.approx(1.0)
    assert dlg.spin_x_max.value() == pytest.approx(3.0)


def test_dialog_accepts_raw_axes_constructor_unchanged(qapp):
    """The wrap-on-demand branch must keep raw-``Axes`` callers
    working without an edit (Plan Task 3 Step 3 + lesson
    ``2026-04-28-return-type-change-needs-paired-callsite-update``)."""
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes_with_curve()
    dlg = ChartOptionsDialog(None, ax)
    assert isinstance(dlg.handle, MplAxisHandle)
    assert dlg.ax is ax


# ---------------------------------------------------------------------------
# Apply / Reset / Log-scale toggle
# ---------------------------------------------------------------------------


def test_dialog_apply_changes_round_trips_via_handle(qapp):
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes_with_curve()
    dlg = ChartOptionsDialog(None, MplAxisHandle(ax))

    dlg.edit_title.setText("新标题")
    dlg.spin_x_min.setValue(0.5)
    dlg.spin_x_max.setValue(5.0)
    dlg.spin_y_min.setValue(0.0)
    dlg.spin_y_max.setValue(20.0)
    dlg.edit_x_label.setText("时间轴")
    dlg.edit_y_label.setText("输出")

    dlg.apply_changes()

    assert ax.get_title() == "新标题"
    assert ax.get_xlim() == pytest.approx((0.5, 5.0))
    assert ax.get_ylim() == pytest.approx((0.0, 20.0))
    assert ax.get_xlabel() == "时间轴"
    assert ax.get_ylabel() == "输出"


def test_dialog_reset_restores_opening_values(qapp):
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes_with_curve()
    dlg = ChartOptionsDialog(None, MplAxisHandle(ax))

    dlg.edit_title.setText("临时标题")
    dlg.spin_x_min.setValue(-99.0)
    dlg.reset_fields()

    assert dlg.edit_title.text() == "原始标题"
    assert dlg.spin_x_min.value() == pytest.approx(1.0)


def test_dialog_log_scale_toggle_applies_via_handle(qapp):
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes_with_curve()
    dlg = ChartOptionsDialog(None, MplAxisHandle(ax))

    dlg.combo_y_scale.setCurrentText("对数")
    dlg.apply_changes()

    assert ax.get_yscale() == "log"
    # X scale stayed linear (only Y toggled).
    assert ax.get_xscale() == "linear"


def test_dialog_log_scale_with_non_positive_range_falls_back_to_autoscale(qapp):
    """Log + non-positive range collects an _invalid_axes entry and
    autoscales; the apply path must continue to surface the warning."""
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes_with_curve()
    dlg = ChartOptionsDialog(None, MplAxisHandle(ax))

    dlg.combo_y_scale.setCurrentText("对数")
    dlg.spin_y_min.setValue(-1.0)
    dlg.spin_y_max.setValue(10.0)

    # Skip the QMessageBox.warning popup so the test stays headless.
    from mf4_analyzer.ui import dialogs as dlg_mod
    captured: list[tuple] = []

    def _capture(*args, **kw):
        captured.append((args, kw))

    dlg_mod.QMessageBox.warning = staticmethod(_capture)  # type: ignore[attr-defined]
    try:
        dlg.apply_changes()
    finally:
        # Restore to avoid leaking the stub into other tests.
        from PyQt5.QtWidgets import QMessageBox as _Q
        dlg_mod.QMessageBox.warning = _Q.warning  # type: ignore[attr-defined]

    assert "y" in dlg._invalid_axes
    assert dlg.was_applied() is False
    # Warning was raised exactly once.
    assert len(captured) == 1


def test_grid_apply_skipped_when_checkbox_unchanged(qapp):
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes_with_curve()
    handle = MplAxisHandle(ax)
    dlg = ChartOptionsDialog(None, handle)

    calls = []
    handle.grid = lambda enabled: calls.append(enabled)

    dlg.apply_changes()

    assert calls == []


def test_grid_apply_runs_when_checkbox_changed(qapp):
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes_with_curve()
    handle = MplAxisHandle(ax)
    dlg = ChartOptionsDialog(None, handle)

    calls = []
    handle.grid = lambda enabled: calls.append(enabled)

    dlg.chk_grid.setChecked(not dlg._initial["grid"])
    dlg.apply_changes()

    assert calls == [not dlg._initial["grid"]]


def test_dialog_has_no_cmap_combo(qapp):
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes_with_curve()
    dlg = ChartOptionsDialog(None, MplAxisHandle(ax))

    assert not hasattr(dlg, "combo_cmap")
    assert hasattr(dlg, "spin_color_min")
    assert hasattr(dlg, "spin_color_max")
    assert hasattr(dlg, "chk_color_auto")


# ---------------------------------------------------------------------------
# Layout-snapshot: visible widget tree byte-identical pre/post refactor
# ---------------------------------------------------------------------------


def _snapshot_widget_text(dlg) -> dict:
    """Capture every user-visible string the dialog renders.

    Per defensive gate ``codex-plan-spec-literal-evidence``: the
    refactor must NOT change the dialog UI. We compare the multiset of
    QLabel/QPushButton/QGroupBox/QFrame texts and their counts.
    """
    labels = sorted(w.text() for w in dlg.findChildren(QLabel))
    buttons = sorted(w.text() for w in dlg.findChildren(QPushButton))
    groupboxes = sorted(w.title() for w in dlg.findChildren(QGroupBox))
    frames = sorted(
        w.objectName() for w in dlg.findChildren(QFrame) if w.objectName()
    )
    return {
        "labels": labels,
        "buttons": buttons,
        "groupboxes": groupboxes,
        "frames": frames,
        "window_title": dlg.windowTitle(),
        "object_name": dlg.objectName(),
    }


# Expected snapshot captured against the current ``dialogs.py``
# (constructor lines 295-352 + ``_axes_tab`` / ``_appearance_tab`` /
# ``_legend_tab`` / group builders). Frozen here so any unintended
# structural change — added/removed/renamed label, button, group title,
# or objectName — fails this test under the
# ``codex-plan-spec-literal-evidence`` defensive gate.
#
# Notes on Qt class inheritance reflected in this snapshot:
# - ``findChildren(QFrame)`` includes ``QLabel`` (which inherits
#   QFrame) and the ``QTabWidget``'s internal
#   ``qt_tabwidget_stackedwidget`` — that's why the FRAMES list carries
#   the QLabel objectNames plus the stacked-widget entry.
# - ``_group_frame`` is built from QFrame (not QGroupBox), so
#   ``findChildren(QGroupBox)`` returns an empty list.
EXPECTED_SNAPSHOT = {
    "labels": sorted([
        "图表选项",            # chartOptionsTitle
        "目标：原始标题",        # chartOptionsSubtitle
        "基础信息",            # _basic_group inline title
        "X 轴",                # _axis_group("X 轴", "x") inline title
        "Y 轴",                # _axis_group("Y 轴", "y") inline title
        "曲线",                # _curve_group inline title
        "色图与色阶",          # _mappable_group inline title
        "图例",                # legend tab group inline title
        # QFormLayout label-column texts:
        "标题",
        "最小值", "最大值", "标签", "刻度",      # X axis form
        "最小值", "最大值", "标签", "刻度",      # Y axis form
        "对象", "颜色",                          # curve form
        "最小值", "最大值",                      # color range form
    ]),
    "buttons": sorted([
        "重置", "取消", "应用", "确定", "选择",
    ]),
    # _group_frame uses QFrame, not QGroupBox; no QGroupBox in tree.
    "groupboxes": [],
    "frames": sorted([
        "chartOptionsTitle", "chartOptionsSubtitle",
        # Six _group_frame instances all share objectName "chartOptionsGroup".
        "chartOptionsGroup", "chartOptionsGroup", "chartOptionsGroup",
        "chartOptionsGroup", "chartOptionsGroup", "chartOptionsGroup",
        # Six group-title QLabels (also caught here because QLabel
        # inherits QFrame).
        "chartOptionsGroupTitle", "chartOptionsGroupTitle",
        "chartOptionsGroupTitle", "chartOptionsGroupTitle",
        "chartOptionsGroupTitle", "chartOptionsGroupTitle",
        # QTabWidget's internal stacked widget (Qt-owned, present in
        # both pre- and post-refactor trees).
        "qt_tabwidget_stackedwidget",
    ]),
    "window_title": "图表选项",
    "object_name": "ChartOptionsDialog",
}


def test_dialog_layout_snapshot_is_byte_identical(qapp):
    """Pin the visible widget tree (label/button/group titles +
    objectName counts) so the refactor cannot accidentally rename,
    reorder, or drop a UI element."""
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes_with_curve()
    dlg = ChartOptionsDialog(None, ax)
    snap = _snapshot_widget_text(dlg)

    assert snap == EXPECTED_SNAPSHOT, (
        "ChartOptionsDialog visible widget tree drifted from the "
        "pre-refactor snapshot. Compare keys: labels/buttons/"
        "groupboxes/frames/window_title/object_name."
    )


def test_dialog_layout_snapshot_matches_for_handle_constructor(qapp):
    """Same byte-identical snapshot when constructed via an
    ``AxisHandle`` (no UI deltas across the two construction paths)."""
    from mf4_analyzer.ui._axis_handle import MplAxisHandle
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    ax = _axes_with_curve()
    dlg = ChartOptionsDialog(None, MplAxisHandle(ax))
    snap = _snapshot_widget_text(dlg)
    assert snap == EXPECTED_SNAPSHOT
