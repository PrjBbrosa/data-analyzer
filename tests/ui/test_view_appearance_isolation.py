"""Round-2 View isolation: chart-options appearance on the production path."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mf4_analyzer.ui.dialogs import ChartOptionsDialog
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.view_state import (
    ViewState,
    _encode_channel_key,
    appearance_binding_key,
    appearance_channel_key,
    appearance_group_key,
    inherit_chart_appearance_for_group_change,
    is_reusable_blank_view,
)
from mf4_analyzer.ui.widgets import MultiFileChannelWidget

from tests.ui.test_view_state_isolation import (
    _enable_lowpass,
    _fid,
    _flush,
    _make_loaded_window,
    _new_attached_view,
    _save_canvas_png,
    _set_checked,
    _wait_time_view_idle,
)


def _apply_chart_options(window, canvas, handle, monkeypatch, **fields):
    captured = {}

    def fake_edit(parent, axis_handle):
        dlg = ChartOptionsDialog(parent, axis_handle)
        captured["dlg"] = dlg
        if "title" in fields:
            dlg.edit_title.setText(fields["title"])
        if "x_label" in fields:
            dlg.edit_x_label.setText(fields["x_label"])
        if "y_label" in fields:
            dlg.edit_y_label.setText(fields["y_label"])
        if "x_scale" in fields:
            dlg.combo_x_scale.setCurrentText(
                "对数" if fields["x_scale"] == "log" else "线性"
            )
        if "y_scale" in fields:
            dlg.combo_y_scale.setCurrentText(
                "对数" if fields["y_scale"] == "log" else "线性"
            )
        if "grid" in fields:
            dlg.chk_grid.setChecked(bool(fields["grid"]))
        if "curve_index" in fields:
            dlg.combo_curve.setCurrentIndex(int(fields["curve_index"]))
        if "curve_color" in fields:
            dlg.edit_curve_color.setText(fields["curve_color"])
        if "y_auto" in fields:
            dlg.chk_y_auto.setChecked(bool(fields["y_auto"]))
        if "y_min" in fields:
            dlg.spin_y_min.setValue(float(fields["y_min"]))
        if "y_max" in fields:
            dlg.spin_y_max.setValue(float(fields["y_max"]))
        dlg.apply_changes()
        return bool(dlg.was_applied())

    monkeypatch.setattr(
        "mf4_analyzer.ui._axis_interaction.edit_chart_options_dialog",
        fake_edit,
    )
    assert canvas._open_chart_options_for_handle(handle) is True
    return captured.get("dlg")


def _torque_handle(window):
    canvas = window.canvas_time
    assert canvas.axes_list
    return canvas, canvas.axes_list[0]


def test_chart_options_title_log_grid_survive_replot_and_view_switch(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    _set_checked(w, "torque")
    w.chart_stack.set_plot_mode("subplot")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    fid = _fid(w)

    _apply_chart_options(
        w, canvas, handle, monkeypatch,
        title="ViewA标题",
        y_label="扭矩覆盖",
        y_scale="log",
        grid=False,
        y_auto=False,
        y_min=40.0,
        y_max=70.0,
    )
    _flush(qapp)
    assert "ViewA标题" in handle.get_title()
    assert "扭矩覆盖" in handle.get_ylabel()
    assert handle.get_yscale() == "log"
    assert handle.is_grid_enabled() is False
    appearance = w.view_manager.get(0).chart_appearance
    spec = appearance["axes"].get(appearance_channel_key(fid, "torque")) or {}
    assert spec.get("title") == "ViewA标题" or "ViewA标题" in str(spec.get("title"))
    assert spec.get("y_scale") == "log"
    assert spec.get("grid") is False

    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    assert "ViewA标题" in handle.get_title()
    assert "扭矩覆盖" in handle.get_ylabel()
    assert handle.get_yscale() == "log"
    assert handle.is_grid_enabled() is False

    _new_attached_view(w, qapp, fid)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas_b, handle_b = _torque_handle(w)
    _apply_chart_options(
        w, canvas_b, handle_b, monkeypatch,
        title="ViewB标题",
        y_label="B轴",
        y_scale="linear",
        grid=True,
    )
    _flush(qapp)

    w._switch_view(0)
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    assert "ViewA标题" in handle.get_title()
    assert "扭矩覆盖" in handle.get_ylabel()
    assert handle.get_yscale() == "log"
    assert handle.is_grid_enabled() is False
    assert "ViewB标题" not in handle.get_title()


def test_chart_options_x_label_writes_through_custom_x(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    _apply_chart_options(
        w, canvas, handle, monkeypatch, x_label="Elapsed",
    )
    _flush(qapp)
    spec = w.view_manager.get(0).axis_opts.get("x_axis") or {}
    assert spec.get("label") == "Elapsed"
    assert w._custom_xlabel == "Elapsed"
    assert "chart_appearance" in w.view_manager.get(0).to_dict()
    assert "x_label" not in (w.view_manager.get(0).chart_appearance or {})

    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    assert "Elapsed" in handle.get_xlabel()


def test_ordinary_chart_options_recolor_stays_view_owned(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    _apply_chart_options(
        w, canvas, handle, monkeypatch, curve_color="#123456",
    )
    _flush(qapp)
    assert w.view_manager.get(0).colors[(fid, "torque")].lower() == "#123456"

    _new_attached_view(w, qapp, fid)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas_b, handle_b = _torque_handle(w)
    _apply_chart_options(
        w, canvas_b, handle_b, monkeypatch, curve_color="#abcdef",
    )
    _flush(qapp)

    w._switch_view(0)
    _wait_time_view_idle(qtbot, w)
    colors = w.navigator.get_channel_colors()
    assert colors[(fid, "torque")].lower() == "#123456"


def test_filter_companion_recolor_is_view_owned(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    _set_checked(w, "torque")
    _enable_lowpass(w, 50.0)
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    lines = handle.get_lines()
    assert len(lines) >= 2
    companion_index = next(
        i for i, line in enumerate(lines)
        if "(" in (line.get_label() or "")
    )
    _apply_chart_options(
        w, canvas, handle, monkeypatch,
        curve_index=companion_index,
        curve_color="#aa00aa",
    )
    _flush(qapp)
    encoded = _encode_channel_key((fid, "torque"))
    appearance = w.view_manager.get(0).chart_appearance
    assert appearance["companion_colors"][encoded].lower() == "#aa00aa"
    assert (fid, "torque") not in w.view_manager.get(0).colors or (
        w.view_manager.get(0).colors.get((fid, "torque"), "").lower() != "#aa00aa"
    )

    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    companion = next(
        line for line in handle.get_lines()
        if "(" in (line.get_label() or "")
    )
    assert companion.get_color().lower() == "#aa00aa"


def test_duplicate_and_save_reopen_keep_chart_appearance(
    qtbot, qapp, loaded_csv, monkeypatch, tmp_path,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    _apply_chart_options(
        w, canvas, handle, monkeypatch,
        title="保存标题",
        y_scale="log",
        grid=False,
        y_auto=False,
        y_min=40.0,
        y_max=70.0,
    )
    _flush(qapp)
    w._on_view_duplicate(0)
    _flush(qapp)
    assert w.view_manager.active == 1
    copy_state = w.view_manager.get(1)
    orig = w.view_manager.get(0)
    assert copy_state.chart_appearance["axes"]
    assert orig.chart_appearance["axes"]
    _wait_time_view_idle(qtbot, w)
    canvas_copy, handle_copy = _torque_handle(w)
    _apply_chart_options(
        w, canvas_copy, handle_copy, monkeypatch,
        title="副本标题",
        y_scale="linear",
        grid=True,
    )
    _flush(qapp)
    w._switch_view(0)
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    assert "保存标题" in handle.get_title()
    assert handle.get_yscale() == "log"

    proj = tmp_path / "appearance.tlproj"
    w.save_project(proj)
    restored = MainWindow()
    qtbot.addWidget(restored)
    restored.open_project(proj)
    qapp.processEvents()
    restored._switch_view(0)
    _wait_time_view_idle(qtbot, restored)
    _set_checked(restored, "torque")
    restored.plot_time()
    _wait_time_view_idle(qtbot, restored)
    _canvas, handle = _torque_handle(restored)
    assert "保存标题" in handle.get_title()
    assert handle.get_yscale() == "log"
    assert handle.is_grid_enabled() is False


def test_chart_options_restore_drops_withdrawn_title_on_reopen(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    opening = handle.get_title()

    def fake_edit(parent, axis_handle):
        dlg = ChartOptionsDialog(parent, axis_handle)
        dlg.edit_title.setText("撤回标题")
        dlg.chk_y_auto.setChecked(False)
        dlg.spin_y_min.setValue(40.0)
        dlg.spin_y_max.setValue(70.0)
        dlg.apply_changes()
        assert "撤回标题" in axis_handle.get_title()
        dlg.btn_reset.click()
        assert "撤回标题" not in axis_handle.get_title()
        return bool(dlg.was_applied())

    monkeypatch.setattr(
        "mf4_analyzer.ui._axis_interaction.edit_chart_options_dialog",
        fake_edit,
    )
    assert canvas._open_chart_options_for_handle(handle) is True
    _flush(qapp)
    assert "撤回标题" not in str(w.view_manager.get(0).chart_appearance)
    assert w._project_dirty.is_dirty is True
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    _canvas, handle = _torque_handle(w)
    assert handle.get_title() == opening
    assert "撤回标题" not in handle.get_title()

    fid = _fid(w)
    _new_attached_view(w, qapp, fid)
    w._switch_view(0)
    _wait_time_view_idle(qtbot, w)
    _canvas, handle = _torque_handle(w)
    assert "撤回标题" not in handle.get_title()


def test_unfocused_chart_options_restore_does_not_stamp_the_other_pane(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    _apply_chart_options(
        w, canvas, handle, monkeypatch, title="主图标题", y_scale="log",
    )
    _flush(qapp)
    _new_attached_view(w, qapp, fid)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    w._switch_view(0)
    _flush(qapp)
    w.view_manager.set_split(1)
    _flush(qapp)
    w.chart_stack.set_focused_card(w.chart_stack._time_card)
    _flush(qapp)
    secondary = w.chart_stack.secondary_canvas()
    assert secondary is not None and secondary.axes_list

    def fake_edit(parent, axis_handle):
        dlg = ChartOptionsDialog(parent, axis_handle)
        dlg.edit_title.setText("分屏临时")
        dlg.apply_changes()
        dlg.btn_reset.click()
        assert "分屏临时" not in axis_handle.get_title()
        return bool(dlg.was_applied())

    monkeypatch.setattr(
        "mf4_analyzer.ui._axis_interaction.edit_chart_options_dialog",
        fake_edit,
    )
    assert secondary._open_chart_options_for_handle(secondary.axes_list[0]) is True
    _flush(qapp)
    primary = w.view_manager.get(0).chart_appearance
    compare = w.view_manager.get(1).chart_appearance
    pkey = appearance_channel_key(fid, "torque")
    assert (primary.get("axes") or {}).get(pkey, {}).get("y_scale") == "log"
    assert "主图标题" in str((primary.get("axes") or {}).get(pkey, {}).get("title"))
    assert "分屏临时" not in str(compare)
    assert "分屏临时" not in secondary.axes_list[0].get_title()


def test_split_unfocused_chart_options_do_not_stamp_focused_view(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    _apply_chart_options(
        w, canvas, handle, monkeypatch, title="主图标题", y_scale="log",
    )
    _flush(qapp)

    _new_attached_view(w, qapp, fid)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    w._switch_view(0)
    _flush(qapp)
    w.view_manager.set_split(1)
    _flush(qapp)
    w.chart_stack.set_focused_card(w.chart_stack._time_card)
    _flush(qapp)

    secondary = w.chart_stack.secondary_canvas()
    assert secondary is not None
    assert secondary.axes_list
    _apply_chart_options(
        w, secondary, secondary.axes_list[0], monkeypatch,
        title="分屏标题",
        y_scale="linear",
    )
    _flush(qapp)
    primary = w.view_manager.get(0).chart_appearance
    compare = w.view_manager.get(1).chart_appearance
    pkey = appearance_channel_key(fid, "torque")
    assert (primary.get("axes") or {}).get(pkey, {}).get("y_scale") == "log"
    assert (compare.get("axes") or {}).get(pkey, {}).get("title") in (
        "分屏标题",
        None,
    ) or "分屏标题" in str((compare.get("axes") or {}).get(pkey, {}).get("title"))


def test_offscreen_appearance_pngs_and_axis_values(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    evidence = Path(".state/view-state-isolation")
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    _set_checked(w, "torque")
    w.chart_stack.set_plot_mode("subplot")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    w.resize(1100, 700)
    canvas, handle = _torque_handle(w)
    _apply_chart_options(
        w, canvas, handle, monkeypatch,
        title="A外观",
        y_scale="log",
        grid=False,
        y_auto=False,
        y_min=40.0,
        y_max=70.0,
    )
    _flush(qapp)
    _save_canvas_png(
        qtbot, qapp, w.canvas_time, evidence / "round2-view-a.png",
    )
    fid = _fid(w)
    _new_attached_view(w, qapp, fid)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas_b, handle_b = _torque_handle(w)
    _apply_chart_options(
        w, canvas_b, handle_b, monkeypatch,
        title="B外观",
        y_scale="linear",
        grid=True,
    )
    _flush(qapp)
    _save_canvas_png(
        qtbot, qapp, w.canvas_time, evidence / "round2-view-b.png",
    )
    w._switch_view(0)
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    _save_canvas_png(
        qtbot, qapp, w.canvas_time, evidence / "round2-view-a-after-b.png",
    )
    assert "A外观" in handle.get_title()
    assert handle.get_yscale() == "log"
    assert handle.is_grid_enabled() is False
    lo, hi = handle.get_ylim()
    assert lo > 0 and hi > lo


def test_dissolving_coaxis_group_does_not_steal_sibling_group_appearance():
    """F-V1-1: group1={A,B} grid off, group2={C,D} log; dissolve A.

    Surviving C/D must keep log and must not inherit group1's grid-off,
    even if a leftover ``["g","1"]`` spec is still sitting in axes.
    """
    prev = {
        _encode_channel_key(("f1", "A")): "1",
        _encode_channel_key(("f1", "B")): "1",
        _encode_channel_key(("f1", "C")): "2",
        _encode_channel_key(("f1", "D")): "2",
    }
    new = {
        _encode_channel_key(("f1", "C")): "2",
        _encode_channel_key(("f1", "D")): "2",
    }
    appearance = {
        "x_scale": "linear",
        "axes": {
            appearance_group_key("1"): {"grid": False},
            appearance_group_key("2"): {"y_scale": "log"},
        },
        "companion_colors": {},
    }

    tree = MultiFileChannelWidget()
    tree.merge_axis_group([("f1", "A"), ("f1", "B")])
    tree.merge_axis_group([("f1", "C"), ("f1", "D")])
    tree.split_axis_group([("f1", "A")])
    assert tree.axis_group_for("f1", "C") == 2
    assert tree.axis_group_for("f1", "D") == 2
    assert tree.axis_group_for("f1", "A") is None
    assert tree.axis_group_for("f1", "B") is None

    got = inherit_chart_appearance_for_group_change(appearance, prev, new)
    axes = got["axes"]
    assert appearance_group_key("1") not in axes
    g2 = axes.get(appearance_group_key("2")) or {}
    assert g2.get("y_scale") == "log"
    assert g2.get("grid") is not False
    for channel in ("C", "D"):
        spec = axes.get(appearance_channel_key("f1", channel)) or {}
        assert spec.get("grid") is not False


def test_group_merge_without_member_specs_does_not_stamp_default_appearance():
    """F-V2-9: empty member specs must not mint linear/grid-on group keys."""
    new = {
        _encode_channel_key(("f1", "a")): "1",
        _encode_channel_key(("f1", "b")): "1",
    }
    got = inherit_chart_appearance_for_group_change({}, {}, new)
    assert got["axes"] == {}
    blank = ViewState(name="View 1", tab_color="#2d7ff9", chart_appearance=got)
    assert is_reusable_blank_view(blank) is True


def test_record_only_appearance_key_matches_binding_id_not_first_fid():
    """F-V2-5: two WWT record-only curves on the same fid must not alias."""
    from types import SimpleNamespace

    from mf4_analyzer.ui.chart_appearance_model import (
        available_binding_target,
        unavailable_target,
    )
    from mf4_analyzer.ui.main_window._view_mixin import ViewMixin

    handle = SimpleNamespace(axis_group=None)

    class _Canvas:
        def appearance_target_for_handle(self, axis):
            if axis is handle:
                return available_binding_target("rec-b")
            return unavailable_target("missing-identity")

    class _Host:
        _appearance_key_for_handle = ViewMixin._appearance_key_for_handle

    key = _Host()._appearance_key_for_handle(
        _Canvas(), handle, SimpleNamespace(curve_bindings=()),
    )
    assert key == appearance_binding_key("rec-b")


def test_unavailable_appearance_key_does_not_guess_first_fid_or_prefix():
    from types import SimpleNamespace

    from mf4_analyzer.ui.chart_appearance_model import unavailable_target
    from mf4_analyzer.ui.main_window._view_mixin import ViewMixin

    handle = SimpleNamespace(axis_group=None)

    class _Canvas:
        def appearance_target_for_handle(self, axis):
            return unavailable_target("ambiguous-identity")

        def companion_source_key(self, curve_key):
            return None

    class _Fd:
        def __init__(self):
            self.data = SimpleNamespace(columns=["torque"])

        def get_prefixed_channel(self, ch):
            return ch

    class _Host:
        files = {"f1": _Fd()}
        _appearance_key_for_handle = ViewMixin._appearance_key_for_handle
        _resolve_companion_source_key = ViewMixin._resolve_companion_source_key

    host = _Host()
    key = host._appearance_key_for_handle(
        _Canvas(), handle, SimpleNamespace(curve_bindings=()),
    )
    assert key == ""
    source = host._resolve_companion_source_key(
        _Canvas(), "f1", "torque (低通 50Hz)",
    )
    assert source is None


def test_companion_source_uses_canvas_facade_identity():
    from mf4_analyzer.ui.main_window._view_mixin import ViewMixin

    class _Canvas:
        def companion_source_key(self, curve_key):
            assert "torque (LP 50Hz)" in str(curve_key)
            return ("f1", "torque")

    class _Host:
        files = {}
        _resolve_companion_source_key = ViewMixin._resolve_companion_source_key

    source = _Host()._resolve_companion_source_key(
        _Canvas(), "f1", "torque (LP 50Hz)",
    )
    assert source == ("f1", "torque")


def test_unavailable_target_does_not_apply_sibling_axis_spec():
    from types import SimpleNamespace

    from mf4_analyzer.ui.chart_appearance_model import (
        available_channel_target,
        unavailable_target,
    )
    from mf4_analyzer.ui.main_window._view_mixin import ViewMixin
    from mf4_analyzer.ui.view_state import normalize_chart_appearance

    wanted = object()
    other = object()
    applied = []

    class _Canvas:
        axes_list = [wanted, other]

        def appearance_target_for_handle(self, handle):
            if handle is wanted:
                return available_channel_target("f1", "torque")
            return unavailable_target("ambiguous-identity")

        def apply_chart_appearance(self, specs):
            applied.append(specs)

    key = appearance_channel_key("f1", "torque")
    sibling = appearance_channel_key("f1", "speed")
    state = SimpleNamespace(chart_appearance=normalize_chart_appearance({
        "x_scale": "linear",
        "axes": {
            key: {"title": "Wanted", "y_scale": "log"},
            sibling: {"title": "Other source", "y_scale": "log"},
        },
    }))

    class _Host:
        _appearance_key_for_handle = ViewMixin._appearance_key_for_handle
        _apply_view_chart_appearance = ViewMixin._apply_view_chart_appearance

    _Host()._apply_view_chart_appearance(state, _Canvas())
    assert applied
    axes = applied[0]["axes"]
    by_handle = {item["handle"]: item for item in axes}
    assert by_handle[wanted]["title"] == "Wanted"
    assert by_handle[wanted]["y_scale"] == "log"
    assert by_handle[other].get("title") != "Other source"
    assert by_handle[other].get("title") != "Wanted"
    assert by_handle[other].get("y_scale") == "linear"


def test_legacy_six_tuple_rows_still_plot_with_empty_mixin_key(qapp):
    from types import SimpleNamespace

    from PyQt5.QtCore import QCoreApplication

    from mf4_analyzer.ui.main_window._view_mixin import ViewMixin
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    t = np.linspace(0.0, 1.0, 32)
    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 320)
    canvas.show()
    QCoreApplication.processEvents()
    canvas.plot_channels(
        [("legacy6", True, t, t.copy(), "#f00", "Nm")],
        mode="subplot",
    )
    QCoreApplication.processEvents()
    assert canvas.axes_list
    class _Host:
        _appearance_key_for_handle = ViewMixin._appearance_key_for_handle

    key = _Host()._appearance_key_for_handle(
        canvas, canvas.axes_list[0], SimpleNamespace(curve_bindings=()),
    )
    assert key == ""


def test_project_schema_is_unchanged_by_appearance_migration():
    from mf4_analyzer.ui.project_io import SCHEMA_VERSION

    assert SCHEMA_VERSION == 4


def test_canvas_appearance_api_uses_binding_id_for_same_fid_records(qapp):
    """Owner API: two same-fid record-only rows map to explicit binding keys."""
    from PyQt5.QtCore import QCoreApplication

    from mf4_analyzer.ui.chart_appearance_model import binding_appearance_ref
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    t = np.linspace(0.0, 1.0, 32)

    def _row(name, binding_id, color):
        return (
            name, True, t, t.copy(), color, "mm", "f1",
            {"appearance_ref": binding_appearance_ref(binding_id)},
        )

    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 320)
    canvas.show()
    QCoreApplication.processEvents()
    canvas.plot_channels(
        [_row("TolA", "rec-a", "#ff0000"), _row("TolB", "rec-b", "#00ff00")],
        mode="subplot",
    )
    QCoreApplication.processEvents()
    assert canvas.appearance_target_for_handle(canvas.axes_list[0]).encoded_key == (
        appearance_binding_key("rec-a")
    )
    assert canvas.appearance_target_for_handle(canvas.axes_list[1]).encoded_key == (
        appearance_binding_key("rec-b")
    )


def test_split_unfocused_recolor_keeps_focused_navigator_colors(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    """F-V2-2: non-focused split recolor writes state.colors, not navigator."""
    w = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(w)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    canvas, handle = _torque_handle(w)
    _apply_chart_options(
        w, canvas, handle, monkeypatch, curve_color="#111111",
    )
    _flush(qapp)
    assert w.view_manager.get(0).colors[(fid, "torque")].lower() == "#111111"

    _new_attached_view(w, qapp, fid)
    _set_checked(w, "torque")
    w.plot_time()
    _wait_time_view_idle(qtbot, w)
    w._switch_view(0)
    _flush(qapp)
    w.view_manager.set_split(1)
    _flush(qapp)
    w.chart_stack.set_focused_card(w.chart_stack._time_card)
    _flush(qapp)

    secondary = w.chart_stack.secondary_canvas()
    assert secondary is not None
    assert secondary.axes_list
    _apply_chart_options(
        w, secondary, secondary.axes_list[0], monkeypatch,
        curve_color="#abcdef",
    )
    _flush(qapp)
    nav_color = w.navigator.get_channel_colors().get((fid, "torque"), "")
    assert nav_color.lower() == "#111111"
    assert w.view_manager.get(0).colors[(fid, "torque")].lower() == "#111111"
    assert w.view_manager.get(1).colors[(fid, "torque")].lower() == "#abcdef"
