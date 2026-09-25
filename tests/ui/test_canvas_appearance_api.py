"""Canvas appearance public API: stable identity, snapshot, apply, repair."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PyQt5.QtCore import QCoreApplication

from mf4_analyzer.ui.chart_appearance_model import (
    REASON_AMBIGUOUS_IDENTITY,
    REASON_MERGED_CURVE_KEY,
    REASON_MISSING_IDENTITY,
    REASON_UNKNOWN_HANDLE,
    appearance_binding_key,
    appearance_channel_key,
    appearance_group_key,
    binding_appearance_ref,
    channel_appearance_ref,
    companion_appearance_ref,
)
from mf4_analyzer.ui.pg_canvas._shared import _view_state_channel_key


REPO_ROOT = Path(__file__).resolve().parents[2]
_APPEARANCE_MODEL_IMPORT_TIMEOUT_S = 30


def _pg_canvas(qapp):
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(800, 400)
    canvas.show()
    QCoreApplication.processEvents()
    return canvas


def _t(n=64):
    return np.linspace(0.0, 1.0, n, dtype=np.float64)


def _row(
    name,
    *,
    fid="f1",
    channel=None,
    visible=True,
    y=None,
    t=None,
    color="#f00",
    unit="Nm",
    meta=None,
    binding_id=None,
    companion_of=None,
):
    t = _t() if t is None else t
    y = np.sin(t) if y is None else y
    payload = {}
    if companion_of is not None:
        if isinstance(companion_of, tuple) and len(companion_of) == 2:
            src_fid, src_ch = companion_of
        else:
            src_fid, src_ch = fid, companion_of
        payload["companion_of"] = src_ch
        payload["dash"] = True
        payload["appearance_ref"] = companion_appearance_ref(src_fid, src_ch)
    elif binding_id is not None:
        payload["appearance_ref"] = binding_appearance_ref(binding_id)
    else:
        payload["appearance_ref"] = channel_appearance_ref(fid, channel or name)
    if meta:
        payload.update(meta)
    return (name, visible, t, y, color, unit, fid, payload)


def test_chart_appearance_model_subprocess_import_survives_qt_poison():
    script = r"""
import json
import sys

sys.modules["PyQt5"] = None
sys.modules["PyQt5.QtCore"] = None
sys.modules["pyqtgraph"] = None
try:
    import PyQt5  # noqa: F401
except ModuleNotFoundError:
    pass
else:
    print(json.dumps({"error": "poison_ineffective"}))
    raise SystemExit(2)
import mf4_analyzer.ui.chart_appearance_model as model
blocked = sorted(
    name for name in sys.modules
    if name == "PyQt5"
    or name.startswith("PyQt5.")
    or name == "pyqtgraph"
    or name.startswith("pyqtgraph.")
)
# Poisoned names stay as None; a real import would replace them with modules.
real = [
    name for name in blocked
    if sys.modules.get(name) is not None
]
print(json.dumps({
    "ok": True,
    "channel": model.appearance_channel_key("f1", "torque"),
    "real_qt": real,
}))
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=_APPEARANCE_MODEL_IMPORT_TIMEOUT_S,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["real_qt"] == []
    assert payload["channel"] == appearance_channel_key("f1", "torque")


def test_same_fid_two_bindings_resolve_to_explicit_binding_keys(qapp):
    canvas = _pg_canvas(qapp)
    t = _t()
    rows = [
        _row("TolA", fid="f1", binding_id="rec-a", t=t, y=np.full_like(t, 1.0)),
        _row("TolB", fid="f1", binding_id="rec-b", t=t, y=np.full_like(t, 2.0), color="#0a0"),
    ]
    canvas.plot_channels(rows, mode="subplot")
    qapp.processEvents()
    assert len(canvas.axes_list) == 2
    first = canvas.appearance_target_for_handle(canvas.axes_list[0])
    second = canvas.appearance_target_for_handle(canvas.axes_list[1])
    assert first.available is True
    assert second.available is True
    assert first.encoded_key == appearance_binding_key("rec-a")
    assert second.encoded_key == appearance_binding_key("rec-b")
    assert first.encoded_key != second.encoded_key


def test_same_display_name_different_fids_resolve_to_channel_keys(qapp):
    canvas = _pg_canvas(qapp)
    t = _t()
    rows = [
        _row("Force", fid="f1", channel="torque", t=t, y=np.sin(t)),
        _row("Force", fid="f2", channel="torque", t=t, y=np.cos(t), color="#0a0"),
    ]
    canvas.plot_channels(rows, mode="subplot")
    qapp.processEvents()
    assert len(canvas.axes_list) == 2
    first = canvas.appearance_target_for_handle(canvas.axes_list[0])
    second = canvas.appearance_target_for_handle(canvas.axes_list[1])
    assert first.available is True
    assert second.available is True
    assert first.encoded_key == appearance_channel_key("f1", "torque")
    assert second.encoded_key == appearance_channel_key("f2", "torque")


def test_companion_curve_returns_exact_source_pair(qapp):
    canvas = _pg_canvas(qapp)
    t = _t()
    primary = _row("torque", fid="f1", channel="torque", t=t)
    companion = _row(
        "torque (LP 50Hz)",
        fid="f1",
        t=t,
        y=np.sin(t) * 0.5,
        companion_of=("f1", "torque"),
    )
    canvas.plot_channels([primary, companion], mode="subplot")
    qapp.processEvents()
    ck = _view_state_channel_key("f1", "torque (LP 50Hz)")
    assert canvas.companion_source_key(ck) == ("f1", "torque")
    target = canvas.appearance_target_for_handle(canvas.axes_list[0])
    assert target.available is True
    assert target.encoded_key == appearance_channel_key("f1", "torque")


def test_shared_x_snapshot_reads_master_scale(qapp):
    canvas = _pg_canvas(qapp)
    t = _t()
    rows = [
        _row("a", fid="f1", channel="a", t=t, y=np.sin(t)),
        _row("b", fid="f1", channel="b", t=t, y=np.cos(t), color="#0a0"),
    ]
    canvas.plot_channels(rows, mode="overlay")
    qapp.processEvents()
    assert canvas._x_master_handle is not None
    master = canvas._x_master_handle
    master.set_xscale("log")
    left = canvas.snapshot_chart_appearance(canvas.axes_list[0])
    right = canvas.snapshot_chart_appearance(canvas.axes_list[1])
    assert left.shares_x is True
    assert right.shares_x is True
    assert left.owns_xlabel is True
    assert right.owns_xlabel is True
    assert left.x_scale == "log"
    assert right.x_scale == "log"
    assert left.target.encoded_key == appearance_channel_key("f1", "a")
    assert right.target.encoded_key == appearance_channel_key("f1", "b")


def test_grouped_handle_prefers_group_key(qapp):
    canvas = _pg_canvas(qapp)
    t = _t()
    rows = [
        _row("a", fid="f1", channel="a", t=t, meta={"axis_group": 7}),
        _row("b", fid="f1", channel="b", t=t, color="#0a0", meta={"axis_group": 7}),
    ]
    canvas.plot_channels(rows, mode="overlay")
    qapp.processEvents()
    assert len(canvas.axes_list) == 1
    target = canvas.appearance_target_for_handle(canvas.axes_list[0])
    assert target.available is True
    assert target.encoded_key == appearance_group_key(7)


def test_legacy_six_and_seven_tuple_rows_draw_but_identity_is_unavailable(qapp):
    canvas = _pg_canvas(qapp)
    t = _t()
    six = ("legacy6", True, t, np.sin(t), "#f00", "Nm")
    seven = ("legacy7", True, t, np.cos(t), "#0a0", "Nm", "f2")
    canvas.plot_channels([six, seven], mode="subplot")
    qapp.processEvents()
    assert len(canvas.axes_list) == 2
    first = canvas.appearance_target_for_handle(canvas.axes_list[0])
    second = canvas.appearance_target_for_handle(canvas.axes_list[1])
    assert first.available is False
    assert second.available is False
    assert first.encoded_key == ""
    assert second.encoded_key == ""
    assert first.reason == REASON_MISSING_IDENTITY
    assert second.reason == REASON_MISSING_IDENTITY


def test_apply_does_not_emit_user_modified_signal(qapp):
    canvas = _pg_canvas(qapp)
    canvas.plot_channels([_row("a", fid="f1", channel="a")], mode="subplot")
    qapp.processEvents()
    seen = []
    canvas.chart_options_applied.connect(lambda *args: seen.append(args))
    handle = canvas.axes_list[0]
    canvas.apply_chart_appearance({
        "x_scale": "linear",
        "axes": [{
            "handle": handle,
            "title": "Applied",
            "y_label": "Nm",
            "y_scale": "linear",
            "grid": False,
        }],
    })
    snap = canvas.snapshot_chart_appearance(handle)
    assert snap.title == "Applied"
    assert snap.y_label == "Nm"
    assert snap.grid is False
    assert seen == []


def test_log_repair_keeps_decade_whose_viewbox_starts_at_zero(qapp):
    """Engineering 1…100 is ViewBox 0…2. Repair must not autoscale that away."""
    canvas = _pg_canvas(qapp)
    y = np.linspace(1.0, 100.0, 64)
    canvas.plot_channels(
        [_row("a", fid="f1", channel="a", y=y)], mode="subplot",
    )
    qapp.processEvents()
    handle = canvas.axes_list[0]
    handle.set_yscale("log")
    assert handle.set_engineering_ylim(1.0, 100.0) is True
    before = handle.get_ylim()
    calls = []
    original = handle.autoscale

    def _record(axis="both"):
        calls.append(axis)
        return original(axis=axis)

    handle.autoscale = _record
    canvas.repair_chart_appearance_ranges({
        "x_scale": "linear",
        "axes": [{"handle": handle, "y_scale": "log"}],
    })
    after = handle.get_ylim()
    engineering = handle.get_engineering_ylim()
    assert calls == []
    assert after[0] == pytest.approx(before[0])
    assert after[1] == pytest.approx(before[1])
    assert engineering[0] == pytest.approx(1.0)
    assert engineering[1] == pytest.approx(100.0)
    assert after[0] == pytest.approx(0.0)
    assert after[1] == pytest.approx(2.0)


def test_apply_log_still_autoscales_non_positive_engineering_span(qapp):
    canvas = _pg_canvas(qapp)
    y = np.linspace(-5.0, 5.0, 64)
    canvas.plot_channels(
        [_row("a", fid="f1", channel="a", y=y)], mode="subplot",
    )
    qapp.processEvents()
    handle = canvas.axes_list[0]
    before_lo, _before_hi = handle.get_ylim()
    assert before_lo <= 0.0
    calls = []
    original = handle.autoscale

    def _record(axis="both"):
        calls.append(axis)
        return original(axis=axis)

    handle.autoscale = _record
    canvas.apply_chart_appearance({
        "x_scale": "linear",
        "axes": [{"handle": handle, "y_scale": "log"}],
    })
    assert "y" in calls
    after_lo, after_hi = handle.get_ylim()
    assert after_lo < after_hi
    assert math.isfinite(after_lo) and math.isfinite(after_hi)


def test_repair_does_not_settle_or_change_quiet_timer(qapp):
    canvas = _pg_canvas(qapp)
    canvas.plot_channels([_row("a", fid="f1", channel="a")], mode="subplot")
    qapp.processEvents()
    calls = []
    canvas.settle_view_restore = lambda: calls.append("settle")
    before = canvas._quality.timer.interval()
    assert before == 150
    canvas.repair_chart_appearance_ranges({
        "x_scale": "log",
        "axes": [{"handle": canvas.axes_list[0], "y_scale": "log"}],
    })
    assert calls == []
    assert canvas._quality.timer.interval() == 150


def test_selection_delta_and_cold_rebuild_share_stable_target(qapp):
    canvas = _pg_canvas(qapp)
    t = _t()
    row_a = _row("a", fid="f1", channel="torque", t=t)
    row_b = _row("b", fid="f1", channel="angle", t=t, color="#0a0")
    canvas.plot_channels([row_a, row_b], mode="subplot")
    qapp.processEvents()
    expected = appearance_channel_key("f1", "torque")
    before = canvas.appearance_target_for_handle(canvas.axes_list[0])
    assert before.encoded_key == expected
    result = canvas.try_apply_selection_delta([row_a], mode="subplot")
    assert result.get("applied") is True
    remaining = [
        handle for handle in canvas.axes_list
        if handle.plot_item is not None and handle.plot_item.isVisible()
    ]
    assert remaining
    delta_target = canvas.appearance_target_for_handle(remaining[0])
    cold = _pg_canvas(qapp)
    cold.plot_channels([row_a], mode="subplot")
    qapp.processEvents()
    cold_target = cold.appearance_target_for_handle(cold.axes_list[0])
    assert delta_target.available is True
    assert cold_target.available is True
    assert delta_target.encoded_key == expected
    assert cold_target.encoded_key == expected


def test_identity_only_metadata_change_is_not_skipped_as_same_signature(qapp):
    canvas = _pg_canvas(qapp)
    t = _t()
    y = np.sin(t)
    first = _row("TolB", fid="f1", binding_id="rec-a", t=t, y=y)
    canvas.plot_channels([first], mode="subplot")
    qapp.processEvents()
    assert canvas.appearance_target_for_handle(canvas.axes_list[0]).encoded_key == (
        appearance_binding_key("rec-a")
    )
    second = _row("TolB", fid="f1", binding_id="rec-b", t=t, y=y)
    delta = canvas.try_apply_selection_delta([second], mode="subplot")
    assert delta.get("applied") is False
    assert delta.get("reason") == "source-revision-changed"
    canvas.plot_channels([second], mode="subplot")
    qapp.processEvents()
    target = canvas.appearance_target_for_handle(canvas.axes_list[0])
    assert target.available is True
    assert target.encoded_key == appearance_binding_key("rec-b")


def test_unknown_handle_and_empty_key_are_unavailable(qapp):
    canvas = _pg_canvas(qapp)
    canvas.plot_channels([_row("a", fid="f1", channel="a")], mode="subplot")
    qapp.processEvents()
    missing = canvas.appearance_target_for_handle(object())
    assert missing.available is False
    assert missing.encoded_key == ""
    assert missing.reason == REASON_UNKNOWN_HANDLE
    canvas.clear()
    stale = canvas.appearance_target_for_handle(
        canvas.axes_list[0] if canvas.axes_list else object()
    )
    assert stale.available is False
    assert stale.encoded_key == ""


def test_merged_same_fid_same_display_record_only_is_unavailable(qapp):
    """Same composite curve key, two binding ids: do not pick a winner."""
    canvas = _pg_canvas(qapp)
    t = _t()
    rows = [
        _row("TolB", fid="f1", binding_id="rec-a", t=t, y=np.full_like(t, 1.0)),
        _row("TolB", fid="f1", binding_id="rec-b", t=t, y=np.full_like(t, 2.0), color="#0a0"),
    ]
    canvas.plot_channels(rows, mode="subplot")
    qapp.processEvents()
    assert canvas.axes_list
    reasons = set()
    for handle in canvas.axes_list:
        target = canvas.appearance_target_for_handle(handle)
        assert target.available is False
        assert target.encoded_key == ""
        reasons.add(target.reason)
    assert reasons & {REASON_MERGED_CURVE_KEY, REASON_AMBIGUOUS_IDENTITY, REASON_MISSING_IDENTITY}


def test_typed_recolor_signal_keeps_legacy_signal(qapp):
    canvas = _pg_canvas(qapp)
    canvas.plot_channels([_row("a", fid="f1", channel="torque")], mode="subplot")
    qapp.processEvents()
    legacy = []
    typed = []
    canvas.channel_color_changed.connect(lambda *args: legacy.append(args))
    canvas.appearance_color_changed.connect(lambda *args: typed.append(args))
    ck = _view_state_channel_key("f1", "a")
    canvas._sync_pg_channel_color(ck, "#123456")
    assert legacy
    assert typed == [(appearance_channel_key("f1", "torque"), "#123456")]
