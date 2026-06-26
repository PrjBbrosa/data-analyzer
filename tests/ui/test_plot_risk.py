from types import SimpleNamespace

import numpy as np
import pandas as pd

from mf4_analyzer.io.file_data import FileData
from mf4_analyzer.ui.plot_risk import PlotRiskLevel, estimate_time_overlay_risk


def _fake_file(columns, *, n=100, time_array=None):
    if time_array is None:
        time_array = np.arange(n, dtype=float)
    return SimpleNamespace(
        time_array=time_array,
        data=SimpleNamespace(columns=tuple(columns)),
    )


def _estimate(
    checked,
    files,
    *,
    mode="overlay",
    time_range=None,
    filter_enabled=False,
    show_original=True,
    show_filtered=True,
):
    return estimate_time_overlay_risk(
        checked=checked,
        files=files,
        mode=mode,
        time_range=time_range,
        filter_enabled=filter_enabled,
        show_original=show_original,
        show_filtered=show_filtered,
    )


def test_small_overlay_is_ok():
    files = {0: _fake_file(("a", "b"), n=100)}
    risk = _estimate(
        [(0, "a", "#1f77b4"), (0, "b", "#ff7f0e")],
        files,
        filter_enabled=False,
    )

    assert risk.level is PlotRiskLevel.OK
    assert risk.channel_count == 2
    assert risk.series_count == 2
    assert risk.sample_total == 200
    assert risk.is_warning is False


def test_channel_count_can_warn():
    channels = tuple(f"ch{i}" for i in range(5))
    files = {0: _fake_file(channels)}
    risk = _estimate([(0, ch, "#1f77b4") for ch in channels], files)

    assert risk.level is PlotRiskLevel.WARNING
    assert any("通道" in reason for reason in risk.reasons)


def test_danger_sample_volume_uses_post_range_count():
    n = 6_000_000
    files = {
        0: _fake_file(
            ("sig",),
            time_array=np.linspace(0.0, 1.0, n, endpoint=False, dtype=float),
        )
    }
    checked = [(0, "sig", "#1f77b4")]

    full = _estimate(checked, files)
    narrow = _estimate(checked, files, time_range=(0.0, 0.001))

    assert full.level is PlotRiskLevel.DANGER
    assert full.sample_total == n
    assert narrow.level is PlotRiskLevel.OK
    assert narrow.sample_total < 1_000_000


def test_filter_companion_trace_increases_series_count():
    channels = tuple(f"ch{i}" for i in range(6))
    files = {0: _fake_file(channels)}
    risk = _estimate(
        [(0, ch, "#1f77b4") for ch in channels],
        files,
        filter_enabled=True,
        show_original=True,
        show_filtered=True,
    )

    assert risk.series_count == 12
    assert risk.level is PlotRiskLevel.DANGER


def test_non_overlay_returns_ok_for_overlay_specific_thresholds():
    n = 6_000_000
    files = {0: _fake_file(("sig",), time_array=np.arange(n, dtype=float))}
    risk = _estimate([(0, "sig", "#1f77b4")], files, mode="subplot")

    assert risk.level is PlotRiskLevel.OK
    assert risk.is_warning is False


def test_non_overlay_does_not_touch_file_data():
    class ExplodingFile:
        @property
        def data(self):
            raise AssertionError("non-overlay must not inspect file data")

        @property
        def time_array(self):
            raise AssertionError("non-overlay must not inspect sample arrays")

    risk = _estimate(
        [(0, "sig", "#1f77b4")],
        {0: ExplodingFile()},
        mode="subplot",
        time_range=(1.0, 2.0),
    )

    assert risk.level is PlotRiskLevel.OK
    assert risk.channel_count == 0
    assert risk.sample_total == 0


def test_reversed_range_is_normalized():
    files = {
        0: _fake_file(
            ("sig",),
            time_array=np.arange(10, dtype=float),
        )
    }

    risk = _estimate([(0, "sig", "#1f77b4")], files, time_range=(4.0, 2.0))

    assert risk.sample_total == 3


def test_non_monotonic_time_axis_uses_mask_fallback():
    files = {
        0: _fake_file(
            ("sig",),
            time_array=np.array([0.0, 5.0, 2.0, 3.0, 9.0]),
        )
    }

    risk = _estimate([(0, "sig", "#1f77b4")], files, time_range=(2.0, 5.0))

    assert risk.sample_total == 3


def test_missing_file_or_channel_is_skipped():
    files = {0: _fake_file(("present",), n=50)}

    risk = _estimate(
        [
            (0, "present", "#1f77b4"),
            (0, "missing", "#ff7f0e"),
            (1, "present", "#2ca02c"),
        ],
        files,
    )

    assert risk.channel_count == 1
    assert risk.series_count == 1
    assert risk.sample_total == 50


def test_filter_visibility_off_still_counts_one_series_per_channel():
    files = {0: _fake_file(("sig",), n=50)}

    risk = _estimate(
        [(0, "sig", "#1f77b4")],
        files,
        filter_enabled=True,
        show_original=False,
        show_filtered=False,
    )

    assert risk.series_count == 1


def test_real_filedata_shape_is_supported():
    n = 6_000_000
    df = pd.DataFrame({"sig": np.zeros(n, dtype=np.float32)})
    fd = FileData("demo.mf4", df, ["sig"], {"sig": ""}, idx=0)

    risk = _estimate([(0, "sig", "#1f77b4")], {0: fd})

    assert risk.level is PlotRiskLevel.DANGER
    assert risk.channel_count == 1
    assert risk.sample_total == n
