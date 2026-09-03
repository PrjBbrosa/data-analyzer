"""Per-curve XY binding JSON, remap, resolution, and shape errors."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.ui.project_io import collect_dropped_time_refs, remap_view_fids
from mf4_analyzer.ui.time_curve_bindings import (
    BoundTimePlotResult,
    TimeCurveBinding,
    TimeDataRef,
    bound_time_plot_rows,
    filter_curve_bindings,
    migrate_legacy_channel_bindings,
    prune_channel_axis_groups_for_live_files,
    prune_hidden_curve_binding_ids,
    remap_curve_bindings,
    resolve_time_curve_binding,
    resolve_time_data_ref,
)
from mf4_analyzer.ui.view_state import ViewState


def _sample_binding() -> TimeCurveBinding:
    return TimeCurveBinding(
        binding_id="window-6-record-18",
        y_ref=TimeDataRef(kind="wwt_record", fid="f1", record_index=18),
        x_ref=TimeDataRef(kind="wwt_record", fid="f1", record_index=17),
        display_name="Rack Force [KN]",
        unit="KN",
        color="#000080",
        axis_id="window-6-axis-18",
        y_range=(0.0, 18.0),
        y_tick_interval=1.0,
        y_grid_interval=None,
        line_width_mm=0.2,
        line_style="line",
    )


def test_time_curve_binding_roundtrip_equals_original():
    channel_ref = TimeDataRef(kind="channel", fid="f1", channel="Rack Force")
    record_ref = TimeDataRef(kind="wwt_record", fid="f1", record_index=17)
    binding = _sample_binding()
    assert TimeDataRef.from_dict(channel_ref.to_dict()) == channel_ref
    assert TimeDataRef.from_dict(record_ref.to_dict()) == record_ref
    assert TimeCurveBinding.from_dict(binding.to_dict()) == binding


def test_channel_and_wwt_record_ref_invariants():
    with pytest.raises(ValueError, match="channel ref"):
        TimeDataRef(kind="channel", fid="f1", channel="A", record_index=1)
    with pytest.raises(ValueError, match="wwt_record ref"):
        TimeDataRef(kind="wwt_record", fid="f1", record_index=1, channel="A")
    with pytest.raises(ValueError, match="wwt_record ref"):
        TimeDataRef(kind="wwt_record", fid="f1", channel=None, record_index=None)


def test_resolver_returns_exact_arrays_and_structured_issues():
    x = np.linspace(-1.0, 1.0, 8)
    y = np.arange(8, dtype=np.float64)
    files = {
        "f1": SimpleNamespace(
            data=pd.DataFrame({"Rack Force": y, "Time": np.arange(8.0)}),
            source_metadata={
                "wwt_record_store": {17: x, 18: y},
            },
            time_array=np.arange(8.0) / 1000.0,
        )
    }
    channel_ref = TimeDataRef(kind="channel", fid="f1", channel="Rack Force")
    values, issue = resolve_time_data_ref(channel_ref, files)
    assert issue is None
    np.testing.assert_array_equal(values, y)

    record_ref = TimeDataRef(kind="wwt_record", fid="f1", record_index=17)
    values, issue = resolve_time_data_ref(record_ref, files)
    assert issue is None
    np.testing.assert_array_equal(values, x)
    assert values is not files["f1"].time_array

    missing_owner, issue = resolve_time_data_ref(
        TimeDataRef(kind="channel", fid="gone", channel="Rack Force"), files
    )
    assert missing_owner is None and issue.code == "missing_owner"

    missing_ch, issue = resolve_time_data_ref(
        TimeDataRef(kind="channel", fid="f1", channel="nope"), files
    )
    assert missing_ch is None and issue.code == "missing_channel"

    missing_rec, issue = resolve_time_data_ref(
        TimeDataRef(kind="wwt_record", fid="f1", record_index=99), files
    )
    assert missing_rec is None and issue.code == "missing_record"

    binding = _sample_binding()
    x_out, y_out, issue = resolve_time_curve_binding(binding, files)
    assert issue is None
    np.testing.assert_array_equal(x_out, x)
    np.testing.assert_array_equal(y_out, y)

    files["f1"].source_metadata["wwt_record_store"][17] = np.linspace(-1.0, 1.0, 5)
    x_out, y_out, issue = resolve_time_curve_binding(binding, files)
    assert x_out is None and y_out is None
    assert issue.code == "unaligned"
    assert issue.detail == "5,8"
    assert "min(" not in issue.detail


def test_remap_and_filter_bindings_drop_missing_owners():
    binding = _sample_binding()
    remapped = remap_curve_bindings([binding], {"f1": "f9"})
    assert remapped[0].x_ref.fid == "f9"
    assert remapped[0].y_ref.fid == "f9"
    assert remap_curve_bindings([binding], {}) == []

    mixed = TimeCurveBinding(
        binding_id="mixed",
        y_ref=TimeDataRef(kind="channel", fid="f1", channel="Rack Force"),
        x_ref=TimeDataRef(kind="wwt_record", fid="f1", record_index=17),
        display_name="Rack Force",
        unit="N",
        color="#000080",
        axis_id="a",
        y_range=(0.0, 1.0),
        y_tick_interval=None,
        y_grid_interval=None,
        line_width_mm=0.2,
        line_style="line",
    )
    kept = filter_curve_bindings(
        [binding, mixed], removed_channels={("f1", "Rack Force")}
    )
    assert kept == [binding]
    dropped = filter_curve_bindings([binding, mixed], removed_fids={"f1"})
    assert dropped == []


def test_viewstate_json_roundtrip_and_project_remap_keep_bindings():
    binding = _sample_binding()
    state = ViewState(
        name="WinWert 1",
        tab_color="#2d7ff9",
        attached_file_ids=["f1"],
        curve_bindings=[binding],
    )
    restored = ViewState.from_dict(state.to_dict())
    assert restored.curve_bindings == [binding]

    malformed = ViewState.from_dict({
        "name": "V",
        "tab_color": "#2d7ff9",
        "curve_bindings": [{"not": "a binding"}, binding.to_dict()],
    })
    assert malformed.curve_bindings == [binding]
    assert ViewState.from_dict({
        "name": "V",
        "tab_color": "#2d7ff9",
    }).curve_bindings == []

    payload = remap_view_fids([state.to_dict()], {"f1": "f9"})[0]
    remapped = ViewState.from_dict(payload)
    assert remapped.curve_bindings[0].x_ref.fid == "f9"
    assert remapped.curve_bindings[0].y_ref.fid == "f9"

    dropped = collect_dropped_time_refs([state.to_dict()], {})
    assert ("", "f1", "binding:x") in dropped or any(
        item[2] == "binding:x" for item in dropped
    )
    assert any(item[2] == "binding:y" for item in dropped)


def _channel_binding(
    *,
    fid="f1",
    y_channel="ChanY",
    x_channel="ChanX",
    binding_id="bind-y",
    display_name="ChanY",
) -> TimeCurveBinding:
    return TimeCurveBinding(
        binding_id=binding_id,
        y_ref=TimeDataRef(kind="channel", fid=fid, channel=y_channel),
        x_ref=TimeDataRef(kind="channel", fid=fid, channel=x_channel),
        display_name=display_name,
        unit="N",
        color="#000080",
        axis_id="axis-y",
        y_range=(-1.0, 1.0),
        y_tick_interval=1.0,
        y_grid_interval=None,
        line_width_mm=0.2,
        line_style="line",
    )


def _record_binding(
    *,
    fid="f1",
    y_index=2,
    x_index=1,
    binding_id="bind-rec",
    display_name="TolY",
) -> TimeCurveBinding:
    return TimeCurveBinding(
        binding_id=binding_id,
        y_ref=TimeDataRef(kind="wwt_record", fid=fid, record_index=y_index),
        x_ref=TimeDataRef(kind="wwt_record", fid=fid, record_index=x_index),
        display_name=display_name,
        unit="mm",
        color="#ff0000",
        axis_id="axis-rec",
        y_range=(0.0, 1.0),
        y_tick_interval=0.2,
        y_grid_interval=None,
        line_width_mm=0.2,
        line_style="line",
    )


def _owner(
    *,
    n=8,
    y_name="ChanY",
    x_name="ChanX",
    records=None,
    y_values=None,
    x_values=None,
    extra=None,
    time_array=None,
):
    y_values = np.arange(n, dtype=np.float64) if y_values is None else np.asarray(y_values)
    x_values = (
        np.linspace(-1.0, 1.0, n, dtype=np.float64)
        if x_values is None else np.asarray(x_values)
    )
    data = {x_name: x_values, y_name: y_values}
    if extra:
        data.update(extra)
    return SimpleNamespace(
        data=pd.DataFrame(data),
        source_metadata={"wwt_record_store": records or {}},
        time_array=(
            np.arange(n, dtype=np.float64) if time_array is None
            else np.asarray(time_array)
        ),
    )


def test_legacy_channel_binding_migrates_only_after_live_custom_x_proof():
    ordinary = _channel_binding()
    record_only = _record_binding(binding_id="record-only")
    state = ViewState(
        name="Legacy WWT",
        tab_color="#2d7ff9",
        axis_opts={
            "x_axis": {
                "mode": "channel",
                "resolver": "per_source_name",
                "fid": None,
                "channel": "ChanX",
                "label": "Travel",
            },
        },
        curve_bindings=[ordinary, record_only],
        hidden_curve_binding_ids=[ordinary.binding_id, record_only.binding_id],
    )
    files = {
        "f1": _owner(
            records={
                1: np.linspace(-2.0, 2.0, 8),
                2: np.linspace(0.0, 1.0, 8),
            },
        ),
    }

    migrated = migrate_legacy_channel_bindings(state, files)

    assert migrated == [ordinary.binding_id]
    assert state.checked == [("f1", "ChanY")]
    assert state.colors[("f1", "ChanY")] == ordinary.color
    assert state.ylims['["f1","ChanY"]'] == ordinary.y_range
    assert "channel_axis_groups" not in state.axis_opts
    assert state.curve_bindings == [record_only]
    assert state.hidden_curve_binding_ids == [record_only.binding_id]


def test_legacy_binding_migration_filters_singleton_axis_groups():
    ordinary = _channel_binding()
    state = ViewState(
        name="Legacy WWT",
        tab_color="#2d7ff9",
        axis_opts={
            "x_axis": {
                "mode": "channel",
                "resolver": "per_source_name",
                "fid": None,
                "channel": "ChanX",
            },
        },
        curve_bindings=[ordinary],
    )

    assert migrate_legacy_channel_bindings(state, {"f1": _owner()}) == [
        ordinary.binding_id,
    ]
    assert "channel_axis_groups" not in state.axis_opts


def test_legacy_channel_binding_stays_exact_when_current_x_is_not_identical():
    binding = _channel_binding(x_channel="OtherX")
    state = ViewState(
        name="Legacy WWT",
        tab_color="#2d7ff9",
        axis_opts={
            "x_axis": {
                "mode": "channel",
                "resolver": "per_source_name",
                "fid": None,
                "channel": "ChanX",
                "label": "Travel",
            },
        },
        curve_bindings=[binding],
    )
    files = {"f1": _owner(extra={"OtherX": np.arange(8, dtype=float)})}

    assert migrate_legacy_channel_bindings(state, files) == []
    assert state.checked == []
    assert state.curve_bindings == [binding]


def test_legacy_channel_binding_stays_exact_when_another_binding_claims_its_y():
    ordinary = _channel_binding(binding_id="ordinary")
    exceptional = TimeCurveBinding(
        binding_id="exceptional",
        y_ref=ordinary.y_ref,
        x_ref=TimeDataRef(kind="wwt_record", fid="f1", record_index=1),
        display_name="ChanY exact",
        unit="N",
        color="#f00",
        axis_id="axis-exact",
        y_range=(-1.0, 1.0),
    )
    state = ViewState(
        name="Legacy WWT",
        tab_color="#2d7ff9",
        axis_opts={
            "x_axis": {
                "mode": "channel",
                "resolver": "per_source_name",
                "fid": None,
                "channel": "ChanX",
            },
        },
        curve_bindings=[ordinary, exceptional],
    )
    files = {"f1": _owner(records={1: np.linspace(-1.0, 1.0, 8)})}

    assert migrate_legacy_channel_bindings(state, files) == []
    assert state.checked == []
    assert state.curve_bindings == [ordinary, exceptional]


def test_live_restore_prunes_axis_groups_for_missing_channels_only():
    state = ViewState(
        name="Legacy WWT",
        tab_color="#2d7ff9",
        axis_opts={
            "channel_axis_groups": {
                '["f1","ChanY"]': "axis-y",
                '["f1","gone"]': "axis-gone",
            },
        },
    )

    prune_channel_axis_groups_for_live_files(state, {"f1": _owner()})

    assert state.axis_opts["channel_axis_groups"] == {
        '["f1","ChanY"]': "axis-y",
    }


def _stub_wwt_ui(mw, monkeypatch, accept=True):
    monkeypatch.setattr(mw._wwt_import, "_ask_layout", lambda *a, **k: accept)
    monkeypatch.setattr(mw, "plot_time", lambda *a, **k: None)
    monkeypatch.setattr(mw, "_apply_active_view", lambda *a, **k: None)


def _load_synthetic_wwt(mw, monkeypatch, path):
    _stub_wwt_ui(mw, monkeypatch, accept=True)
    mw._load_one(str(path))


def test_missing_record_x_does_not_fallback_to_time_y(qapp, tmp_path, monkeypatch):
    """An explicitly exceptional X failure must not fall back to Time-Y."""
    from dataclasses import replace

    from mf4_analyzer.ui.main_window import MainWindow
    from tests._helpers import wwt_factory as wwt

    path = wwt.channel_xy_with_auxiliaries(tmp_path / "xy.wwt")
    mw = MainWindow()
    _load_synthetic_wwt(mw, monkeypatch, path)
    qapp.processEvents()

    view = mw.view_manager.get(mw.view_manager.active)
    assert view.curve_bindings == []
    y_fid, y_channel = view.checked[0]
    binding = _channel_binding(fid=y_fid, y_channel=y_channel)
    broken = replace(
        binding,
        x_ref=TimeDataRef(
            kind="wwt_record", fid=y_fid, record_index=999,
        ),
    )
    view.curve_bindings = [broken]
    assert mw.channel_list.get_file_data(y_fid) is not None

    bind_result = bound_time_plot_rows([broken], mw.files)
    rows, issues, claimed = bind_result
    assert isinstance(bind_result, BoundTimePlotResult)
    assert claimed is bind_result.claimed_channel_keys
    assert (y_fid, y_channel) in bind_result.claimed_channel_keys
    assert (y_fid, y_channel) not in bind_result.successful_channel_keys
    assert any(issue.code == "missing_record" for issue in issues)
    assert rows == []

    result = mw._build_time_plot_data(
        checked=[(y_fid, y_channel, "#000080")],
        range_enabled=False,
    )
    assert any(issue.code == "missing_record" for issue in result.issues)
    assert (y_fid, y_channel) in result.attempted_channel_keys
    assert (y_fid, y_channel) not in result.successful_channel_keys
    fd = mw.files[y_fid]
    prefixed = fd.get_prefixed_channel(y_channel)
    time_y = [row for row in result.rows if row[0] == prefixed]
    assert time_y == [], [row[0] for row in result.rows]


def test_unchecking_ordinary_channel_backed_y_follows_view_checked_set(
    qapp, tmp_path, monkeypatch,
):
    """Ordinary WWT channels use the same checked path as a normal View."""
    from mf4_analyzer.ui.main_window import MainWindow
    from tests._helpers import wwt_factory as wwt

    path = wwt.channel_xy_with_auxiliaries(tmp_path / "xy.wwt")
    mw = MainWindow()
    _load_synthetic_wwt(mw, monkeypatch, path)
    qapp.processEvents()

    view = mw.view_manager.get(mw.view_manager.active)
    assert view.curve_bindings == []
    y_key = view.checked[0]
    assert y_key[1] == wwt.CHAN_Y

    hidden = mw._build_time_plot_data(checked=[], range_enabled=False)
    assert hidden.rows == []
    assert y_key not in hidden.successful_channel_keys

    shown = mw._build_time_plot_data(
        checked=[(y_key[0], y_key[1], view.colors[y_key])],
        range_enabled=False,
    )
    assert y_key in shown.successful_channel_keys
    fd = mw.files[y_key[0]]
    prefixed = fd.get_prefixed_channel(y_key[1])
    matching = [row for row in shown.rows if row[0] == prefixed]
    assert len(matching) == 1
    assert len(matching[0]) == 7


def test_missing_record_x_claims_channel_y_without_row():
    from dataclasses import replace

    y_key = ("f1", "ChanY")
    binding = replace(
        _channel_binding(),
        x_ref=TimeDataRef(kind="wwt_record", fid="f1", record_index=999),
    )
    files = {"f1": _owner()}
    result = bound_time_plot_rows(
        [binding], files, checked_channel_keys={y_key},
    )
    rows, issues, claimed = result
    assert rows == []
    assert any(issue.code == "missing_record" for issue in issues)
    assert claimed == {y_key}
    assert result.successful_channel_keys == set()


def test_unaligned_xy_claims_channel_y_without_row():
    from dataclasses import replace

    y_key = ("f1", "ChanY")
    binding = replace(
        _channel_binding(),
        x_ref=TimeDataRef(kind="wwt_record", fid="f1", record_index=1),
    )
    files = {
        "f1": _owner(n=8, records={1: np.linspace(-1.0, 1.0, 5)}),
    }
    result = bound_time_plot_rows(
        [binding], files, checked_channel_keys={y_key},
    )
    assert result.rows == []
    assert any(issue.code == "unaligned" for issue in result.issues)
    assert y_key in result.claimed_channel_keys
    assert y_key not in result.successful_channel_keys


def test_unchecked_channel_backed_y_is_claimed_as_inactive():
    y_key = ("f1", "ChanY")
    binding = _channel_binding()
    files = {"f1": _owner()}
    result = bound_time_plot_rows(
        [binding], files, checked_channel_keys=set(),
    )
    assert result.rows == []
    assert result.issues == []
    assert y_key in result.claimed_channel_keys
    assert y_key not in result.successful_channel_keys


def test_record_only_y_plots_without_checked_identity():
    binding = _record_binding()
    x = np.linspace(-10.0, 10.0, 16)
    y = np.linspace(0.2, 0.8, 16)
    files = {
        "f1": _owner(n=8, records={1: x, 2: y}),
    }
    result = bound_time_plot_rows(
        [binding], files, checked_channel_keys=set(),
    )
    assert len(result.rows) == 1
    assert result.issues == []
    assert result.claimed_channel_keys == set()
    assert result.successful_channel_keys == set()
    np.testing.assert_array_equal(result.rows[0][2], x)
    np.testing.assert_array_equal(result.rows[0][3], y)
    assert result.rows[0][7]["axis_group"] == binding.axis_id
    assert "native_xy_full_range" not in result.rows[0][7]
    assert binding.y_ref.kind == "wwt_record"


def test_unclaimed_checked_channel_appends_time_y(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    from tests._helpers import wwt_factory as wwt

    path = wwt.channel_xy_with_auxiliaries(tmp_path / "xy.wwt")
    mw = MainWindow()
    _load_synthetic_wwt(mw, monkeypatch, path)
    qapp.processEvents()

    view = mw.view_manager.get(mw.view_manager.active)
    assert view.curve_bindings == []
    y_fid, y_channel = view.checked[0]
    fd = mw.files[y_fid]
    extra = next(
        name for name in fd.get_signal_channels()
        if name != y_channel
    )
    extra_key = (y_fid, extra)
    result = mw._build_time_plot_data(
        checked=[
            (y_fid, y_channel, view.colors[(y_fid, y_channel)]),
            (y_fid, extra, "#ff0000"),
        ],
        range_enabled=False,
    )
    assert {row[6] for row in result.rows} == {y_fid}
    prefixed_extra = fd.get_prefixed_channel(extra)
    time_y = [row for row in result.rows if row[0] == prefixed_extra]
    assert len(time_y) == 1
    assert extra_key in result.successful_channel_keys
    assert extra_key not in bound_time_plot_rows(
        view.curve_bindings, mw.files,
        checked_channel_keys={(y_fid, y_channel), extra_key},
    ).claimed_channel_keys


def test_acquisition_mask_aligns_channel_backed_xy():
    n = 8
    time_axis = np.arange(n, dtype=np.float64)
    x_values = np.arange(n, dtype=np.float64) * 10.0
    y_values = np.arange(n, dtype=np.float64)
    binding = _channel_binding()
    files = {
        "f1": _owner(
            n=n, x_values=x_values, y_values=y_values, time_array=time_axis,
        )
    }
    result = bound_time_plot_rows(
        [binding], files, range_lo=2.0, range_hi=4.0,
        checked_channel_keys={("f1", "ChanY")},
    )
    assert len(result.rows) == 1
    np.testing.assert_array_equal(result.rows[0][2], np.array([20.0, 30.0, 40.0]))
    np.testing.assert_array_equal(result.rows[0][3], np.array([2.0, 3.0, 4.0]))
    assert result.rows[0][2].shape == result.rows[0][3].shape
    assert binding.y_ref.kind == "channel"
    assert "native_xy_full_range" not in result.rows[0][7]


def test_duplicate_display_names_use_composite_identity():
    shared_name = "Force"
    left = _channel_binding(
        fid="f1", binding_id="left", display_name=shared_name,
    )
    right = _channel_binding(
        fid="f2", binding_id="right", display_name=shared_name,
    )
    files = {
        "f1": _owner(y_values=np.arange(8, dtype=np.float64)),
        "f2": _owner(y_values=np.arange(8, dtype=np.float64) + 100.0),
    }
    result = bound_time_plot_rows(
        [left, right], files, checked_channel_keys={("f1", "ChanY")},
    )
    assert result.claimed_channel_keys == {("f1", "ChanY"), ("f2", "ChanY")}
    assert result.successful_channel_keys == {("f1", "ChanY")}
    assert len(result.rows) == 1
    assert result.rows[0][6] == "f1"
    np.testing.assert_array_equal(result.rows[0][3], np.arange(8, dtype=np.float64))


def test_record_only_gap_binding_preserves_nan_and_array_length(tmp_path):
    from mf4_analyzer.io.wwt_document import load_wwt_document
    from tests._helpers import wwt_factory as wwt

    loaded = load_wwt_document(wwt.record_only_gap_curves(tmp_path / "gap.wwt"))
    records = {record.name: record for record in loaded.document.records}
    group = loaded.groups[0]
    owner = SimpleNamespace(
        data=group["data"],
        source_metadata=group["source_metadata"],
        time_array=np.asarray(group["data"]["Time"]),
    )
    binding = _record_binding(
        x_index=records[wwt.GAP_X].index,
        y_index=records[wwt.GAP_Y_SPEED].index,
        display_name=wwt.GAP_Y_SPEED,
    )

    result = bound_time_plot_rows([binding], {"f1": owner})

    assert result.issues == []
    assert len(result.rows) == 1
    x_values, y_values = result.rows[0][2:4]
    assert x_values.shape == y_values.shape == (7,)
    assert np.isnan(y_values[[2, 5]]).all()
    np.testing.assert_array_equal(
        np.delete(y_values, [2, 5]),
        np.array([60.0, 90.0, 60.0, 90.0, 60.0]),
    )


def test_channel_backed_binding_prefers_tracelab_channel_color():
    binding = _channel_binding(display_name="ChanY [N]")
    key = (binding.y_ref.fid, binding.y_ref.channel)

    result = bound_time_plot_rows(
        [binding],
        {"f1": _owner()},
        checked_channel_keys={key},
        channel_colors={key: "#13a36b"},
    )

    assert len(result.rows) == 1
    assert result.rows[0][4] == "#13a36b"
    assert result.rows[0][0] == "ChanY"


def test_channel_backed_binding_uses_winwert_color_without_navigator_override():
    binding = _channel_binding(display_name="ChanY [N]")
    key = (binding.y_ref.fid, binding.y_ref.channel)

    result = bound_time_plot_rows(
        [binding],
        {"f1": _owner()},
        checked_channel_keys={key},
    )

    assert len(result.rows) == 1
    assert result.rows[0][4] == "#000080"


def test_record_only_binding_keeps_compatibility_color():
    binding = _record_binding()
    x = np.linspace(-10.0, 10.0, 16)
    y = np.linspace(0.2, 0.8, 16)

    result = bound_time_plot_rows(
        [binding],
        {"f1": _owner(records={1: x, 2: y})},
        channel_colors={("f1", "ChanY"): "#13a36b"},
    )

    assert len(result.rows) == 1
    assert result.rows[0][4] == "#ff0000"
    assert result.rows[0][4] == binding.color


def test_hidden_record_only_binding_is_skipped_without_issue_or_claim():
    hidden = _record_binding(binding_id="hide-me", display_name="TolY")
    channel = _channel_binding()
    files = {"f1": _owner()}
    shown = bound_time_plot_rows(
        [hidden, channel],
        files,
        checked_channel_keys={("f1", "ChanY")},
    )
    assert any(issue.binding_id == "hide-me" for issue in shown.issues)

    skipped = bound_time_plot_rows(
        [hidden, channel],
        files,
        checked_channel_keys={("f1", "ChanY")},
        hidden_binding_ids={"hide-me"},
    )
    assert skipped.issues == []
    assert len(skipped.rows) == 1
    assert skipped.rows[0][0] == "ChanY"
    assert skipped.claimed_channel_keys == {("f1", "ChanY")}
    assert prune_hidden_curve_binding_ids(
        ["hide-me", "gone", "hide-me"],
        [hidden, channel],
    ) == ["hide-me"]
