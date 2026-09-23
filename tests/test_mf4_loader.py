from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.io.loader import (
    DataLoader,
    _prepare_mdf_time_series,
    prepare_shared_time_series,
)
from mf4_analyzer.io.source_adapters import SourceAdapterRegistry
from mf4_analyzer.ui.drawers.batch.input_panel import _default_probe_signals_for
from tests._helpers.mf4_factory import (
    write_conversion_unit_mf4,
    write_signal_groups_mf4,
    write_single_channel_mf4,
    write_source_path_mf4,
)


def test_load_mf4_deduplicates_source_path_aliases(tmp_path):
    mf4 = write_source_path_mf4(
        tmp_path / "alias.mf4",
        channels=(("sig", "V", "A_side", (1.0, 2.0, 3.0, 4.0)),),
    )

    df, channels, units = DataLoader.load_mf4(str(mf4))

    assert "sig" in channels
    assert "A_side.sig" not in channels
    assert channels.count("sig") == 1
    assert "sig" in df.columns
    assert units["sig"] == "V"


def test_batch_probe_deduplicates_source_path_aliases(tmp_path):
    mf4 = write_source_path_mf4(
        tmp_path / "alias.mf4",
        channels=(("sig", "V", "A_side", (1.0, 2.0, 3.0, 4.0)),),
    )

    channels = _default_probe_signals_for(str(mf4))

    assert "sig" in channels
    assert "A_side.sig" not in channels


def test_load_mf4_keeps_source_path_when_short_name_is_ambiguous(tmp_path):
    mf4 = write_source_path_mf4(
        tmp_path / "ambiguous.mf4",
        channels=(
            ("sig", "V", "ECU1", (1.0, 2.0, 3.0, 4.0)),
            ("sig", "V", "ECU2", (5.0, 6.0, 7.0, 8.0)),
        ),
    )

    df, channels, units = DataLoader.load_mf4(str(mf4))

    assert "sig" not in channels
    assert "ECU1.sig" in channels
    assert "ECU2.sig" in channels
    assert df["ECU1.sig"].tolist() == pytest.approx([1.0, 2.0, 3.0, 4.0])
    assert df["ECU2.sig"].tolist() == pytest.approx([5.0, 6.0, 7.0, 8.0])
    assert units["ECU1.sig"] == "V"
    assert units["ECU2.sig"] == "V"


def test_load_mf4_reads_unit_from_conversion_block(tmp_path):
    mf4 = write_conversion_unit_mf4(
        tmp_path / "conv_unit.mf4", name="trq", unit="Nm"
    )

    df, channels, units = DataLoader.load_mf4(str(mf4))

    assert "trq" in channels
    assert units["trq"] == "Nm"
    assert df["trq"].tolist() == pytest.approx([1.0, 2.0, 3.0, 4.0])


def test_load_mf4_prefers_signal_unit_over_conversion(tmp_path):
    mf4 = write_single_channel_mf4(tmp_path / "chan_unit.mf4", name="v", unit="V")

    _df, _channels, units = DataLoader.load_mf4(str(mf4))

    assert units["v"] == "V"


def test_prepare_shared_time_series_keeps_last_duplicate():
    tied = prepare_shared_time_series(
        [0.0, 0.01, 0.01, 0.03],
        [0.0, 1.0, 5.0, 9.0],
    )
    assert tied is not None
    assert tied[0].tolist() == pytest.approx([0.0, 0.01, 0.03])
    assert tied[1].tolist() == pytest.approx([0.0, 5.0, 9.0])
    _prepared, facts = _prepare_mdf_time_series(
        [0.0, 0.01, 0.01, 0.03],
        [0.0, 1.0, 5.0, 9.0],
    )
    assert facts["duplicate_time_removed"] == 1
    assert prepare_shared_time_series([0.0, 1.0], [1.0]) is None


def test_prepare_shared_time_series_rejects_clock_reset():
    result = prepare_shared_time_series(
        [0, 1, 2, 0, 1, 2], [10, 11, 12, 20, 21, 22],
    )
    assert result is None
    _prepared, facts = _prepare_mdf_time_series(
        [0, 1, 2, 0, 1, 2], [10, 11, 12, 20, 21, 22],
    )
    assert facts["skip_reason"] == "time-regression"
    assert facts["time_regression_count"] >= 1


@pytest.mark.parametrize("dtype", [np.int16, np.float32, np.float64])
def test_prepare_counts_adjacent_duplicates(dtype):
    samples = np.array([0, 1, 5, 9], dtype=dtype)
    prepared, facts = _prepare_mdf_time_series(
        [0.0, 0.01, 0.01, 0.03], samples,
    )
    assert prepared is not None
    assert prepared[1].tolist() == pytest.approx([0.0, 5.0, 9.0])
    assert facts["duplicate_time_removed"] == 1


def test_prepare_keeps_nan_sample_at_duplicate_time():
    prepared, facts = _prepare_mdf_time_series(
        [0.0, 1.0, 1.0], [1.0, 2.0, np.nan],
    )
    assert prepared is not None
    assert np.isnan(prepared[1][-1])
    assert facts["duplicate_time_removed"] == 1


def test_prepare_rejects_empty_nonfinite_mismatch_and_bad_shape():
    empty, empty_facts = _prepare_mdf_time_series([], [])
    assert empty is None and empty_facts["skip_reason"] == "empty"

    gone, gone_facts = _prepare_mdf_time_series([np.nan, np.inf], [1.0, 2.0])
    assert gone is None and gone_facts["skip_reason"] == "unusable-time"
    assert gone_facts["nonfinite_time_removed"] == 2

    trimmed, trimmed_facts = _prepare_mdf_time_series(
        [0.0, np.nan, 1.0], [1.0, 9.0, 2.0],
    )
    assert trimmed is not None
    assert trimmed[0].tolist() == pytest.approx([0.0, 1.0])
    assert trimmed[1].tolist() == pytest.approx([1.0, 2.0])
    assert trimmed_facts["nonfinite_time_removed"] == 1

    mismatch, mismatch_facts = _prepare_mdf_time_series([0.0, 1.0], [1.0])
    assert mismatch is None and mismatch_facts["skip_reason"] == "length-mismatch"

    grid, grid_facts = _prepare_mdf_time_series([0.0, 1.0], np.ones((2, 2)))
    assert grid is None and grid_facts["skip_reason"] == "non-1d"

    imag, imag_facts = _prepare_mdf_time_series(
        [0.0, 1.0], np.array([1 + 2j, 3 + 4j]),
    )
    assert imag is None and imag_facts["skip_reason"] == "non-1d"

    reset_after_gap, reset_facts = _prepare_mdf_time_series(
        [0.0, np.nan, 1.0, 0.5], [1.0, 2.0, 3.0, 4.0],
    )
    assert reset_after_gap is None
    assert reset_facts["skip_reason"] == "time-regression"


def test_load_mf4_keeps_duplicate_timestamps_for_int_and_float(tmp_path):
    mf4 = write_signal_groups_mf4(
        tmp_path / "duplicate-time.mf4",
        [
            [(
                "long",
                np.array([10, 10, 10, 10], dtype=np.float32),
                [0.0, 0.01, 0.02, 0.03],
                "V",
            )],
            [(
                "short",
                np.array([0, 1, 5, 9], dtype=np.int16),
                [0.0, 0.01, 0.01, 0.03],
                "Nm",
            )],
        ],
    )

    df, channels, units = DataLoader.load_mf4(str(mf4))

    assert channels == ["Time", "long", "short"]
    assert units["short"] == "Nm"
    row = df.loc[np.isclose(df["Time"], 0.02)].iloc[0]
    assert row["short"] == pytest.approx(7.0)
    assert df.attrs["source_metadata"]["skipped_channels"] == []


def test_load_mf4_rejects_a_backward_time_step(tmp_path):
    mf4 = write_signal_groups_mf4(
        tmp_path / "backward.mf4",
        [
            [("clock", [0.0, 0.0, 0.0, 0.0], [0.0, 1.0, 2.0, 3.0])],
            [("wound", [1.0, 4.0, 2.0, 3.0], [0.0, 3.0, 1.0, 2.0])],
        ],
    )

    df, channels, _units = DataLoader.load_mf4(str(mf4))

    assert "wound" not in channels
    assert df["clock"].tolist() == pytest.approx([0.0, 0.0, 0.0, 0.0])
    skipped = df.attrs["source_metadata"]["skipped_channels"]
    assert {"name": "wound", "reason": "time-regression"} in skipped


def test_load_mf4_interpolates_when_sample_counts_match(tmp_path):
    mf4 = write_signal_groups_mf4(
        tmp_path / "same-count.mf4",
        [
            [("anchor", [0.0, 0.0, 0.0], [0.0, 1.0, 2.0])],
            [("other", [0.0, 0.0, 30.0], [0.0, 1.0, 3.0])],
        ],
    )

    df, _channels, _units = DataLoader.load_mf4(str(mf4))

    row = df.loc[np.isclose(df["Time"], 2.0)].iloc[0]
    assert row["other"] == pytest.approx(15.0)


def test_load_mf4_reports_non_numeric_channels(tmp_path):
    mf4 = write_signal_groups_mf4(
        tmp_path / "mixed.mf4",
        [
            [("sig", [1.0, 2.0, 3.0], [0.0, 0.01, 0.02], "V")],
            [("Comment", np.array([b"a", b"b"]), [0.0, 0.01])],
        ],
    )

    df, channels, _units = DataLoader.load_mf4(str(mf4))

    assert "sig" in channels
    assert "Comment" not in channels
    skipped = df.attrs["source_metadata"]["skipped_channels"]
    assert skipped == [{"name": "Comment", "reason": "non-numeric"}]
    loaded = SourceAdapterRegistry.default().adapter_for("mixed.mf4").load_sources(
        str(mf4)
    )
    assert loaded[0].metadata["skipped_channels"] == skipped
    assert loaded[0].file_data.source_metadata["skipped_channels"] == skipped


def test_load_mf4_reports_reference_range_loss(tmp_path):
    path = write_signal_groups_mf4(tmp_path / "coverage.mf4", [
        [("fast", [0, 1, 2, 3, 4], [0, 0.25, 0.5, 0.75, 1])],
        [("slow", [10, 20, 30], [0, 5, 10])],
    ])
    frame, channels, _units = DataLoader.load_mf4(str(path))
    meta = frame.attrs["source_metadata"]
    assert frame["Time"].tolist() == pytest.approx([0, 0.25, 0.5, 0.75, 1])
    assert "slow" in channels
    item = next(
        entry for entry in meta["mf4_alignment"]["channels"]
        if entry["physical_occurrence"] == [1, 1]
    )
    assert item["name"] == "slow"
    assert item["input_range"] == [0, 10]
    assert item["outside_reference_count"] == 2
    assert item["alignment"] == "linear"
    assert meta["mf4_alignment"]["output_range"] == [0, 1]
    assert any("时间范围" in text for text in meta["warnings"])
    loaded = SourceAdapterRegistry.default().adapter_for(str(path)).load_sources(str(path))
    assert loaded[0].metadata["mf4_alignment"]["policy"] == "shared-longest-axis-v1"
    assert loaded[0].file_data.source_metadata["warnings"]
    _assert_plain_metadata(loaded[0].metadata["mf4_alignment"])


def test_load_mf4_counts_endpoint_fill_and_skips_no_overlap(tmp_path):
    path = write_signal_groups_mf4(tmp_path / "edges.mf4", [
        [("fast", [0, 1, 2, 3, 4], [0, 0.25, 0.5, 0.75, 1])],
        [("late", [7, 8, 9], [0.5, 0.75, 1])],
        [("far", [1, 2, 3], [20, 21, 22])],
        [("touch", [4, 5], [1, 2])],
    ])
    frame, channels, _units = DataLoader.load_mf4(str(path))
    items = {
        entry["name"]: entry
        for entry in frame.attrs["source_metadata"]["mf4_alignment"]["channels"]
    }
    assert "far" not in channels
    assert items["far"]["skip_reason"] == "no-time-overlap"
    assert items["late"]["endpoint_fill_count"] == 2
    assert frame.loc[np.isclose(frame["Time"], 0.0), "late"].iloc[0] == pytest.approx(7)
    assert "touch" in channels
    assert items["touch"]["alignment"] == "linear"


def test_load_mf4_identical_clock_has_no_resample_warning(tmp_path):
    path = write_signal_groups_mf4(tmp_path / "same.mf4", [
        [("a", [1, 2, 3], [0, 1, 2])],
        [("b", [4, 5, 6], [0, 1, 2])],
    ])
    frame, _channels, _units = DataLoader.load_mf4(str(path))
    meta = frame.attrs["source_metadata"]
    assert frame["b"].tolist() == pytest.approx([4, 5, 6])
    assert meta["warnings"] == []
    kinds = {
        entry["name"]: entry["alignment"]
        for entry in meta["mf4_alignment"]["channels"]
    }
    assert kinds == {"a": "identity", "b": "identity"}


def test_load_mf4_single_samples_share_one_row_or_fail(tmp_path):
    same = write_signal_groups_mf4(tmp_path / "same-point.mf4", [
        [("a", [1.0], [0.0])],
        [("b", [2.0], [0.0])],
    ])
    frame, channels, _units = DataLoader.load_mf4(str(same))
    assert channels == ["Time", "a", "b"]
    assert frame["Time"].tolist() == pytest.approx([0.0])
    assert frame["a"].tolist() == pytest.approx([1.0])
    assert frame["b"].tolist() == pytest.approx([2.0])

    mixed = write_signal_groups_mf4(tmp_path / "mixed-point.mf4", [
        [("multi", [1, 2, 3], [0, 1, 2])],
        [("dot", [9], [1.0])],
    ])
    frame, channels, _units = DataLoader.load_mf4(str(mixed))
    assert "dot" not in channels
    assert {"name": "dot", "reason": "single-sample"} in (
        frame.attrs["source_metadata"]["skipped_channels"]
    )

    split = write_signal_groups_mf4(tmp_path / "split-point.mf4", [
        [("a", [1.0], [0.0])],
        [("b", [2.0], [10.0])],
    ])
    with pytest.raises(ValueError, match="单点通道时间不一致"):
        DataLoader.load_mf4(str(split))


def test_load_mf4_all_time_regressions_name_the_channels(tmp_path):
    path = write_signal_groups_mf4(tmp_path / "reset.mf4", [
        [("wound", [1, 2, 3], [0, 2, 1])],
    ])
    with pytest.raises(ValueError, match="wound"):
        DataLoader.load_mf4(str(path))


def test_load_mf4_read_errors_stay_on_the_physical_channel(monkeypatch):
    from types import SimpleNamespace

    from asammdf.blocks.utils import MdfException

    class _Channel:
        def __init__(self, name, kind=0, sync=0):
            self.name = name
            self.channel_type = kind
            self.sync_type = sync
            self.unit = ""
            self.conversion = None
            self.source = None

    class _Fake:
        def __init__(self):
            self.version = "4.10"
            self.closed = False
            self.calls = []
            self.groups = [
                SimpleNamespace(channels=[
                    _Channel("t", 2, 1), _Channel("bad"),
                ]),
                SimpleNamespace(channels=[
                    _Channel("t", 2, 1), _Channel("good"),
                ]),
            ]
            self.channels_db = {
                "t": [(0, 0), (1, 0)],
                "bad": [(0, 1)],
                "good": [(1, 1)],
            }

        def get(self, *args, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("group") == 0:
                raise MdfException("bad block")
            if kwargs.get("group") == 1:
                return SimpleNamespace(
                    samples=np.array([1.0, 2.0]),
                    timestamps=np.array([0.0, 1.0]),
                    unit="V",
                )
            raise AssertionError(f"unexpected read {args} {kwargs}")

        def close(self):
            self.closed = True

    fake = _Fake()
    monkeypatch.setattr(
        "mf4_analyzer.io.loader.ensure_mdf", lambda: (lambda _path: fake),
    )
    frame, channels, _units = DataLoader.load_mf4("physical.mf4")
    assert fake.closed
    assert "good" in channels
    assert "bad" not in channels
    assert all("group" in call for call in fake.calls)
    assert {"name": "bad", "reason": "unreadable"} in (
        frame.attrs["source_metadata"]["skipped_channels"]
    )

    class _Boom(_Fake):
        def get(self, *args, **kwargs):
            raise RuntimeError("programming error")

    boom = _Boom()
    monkeypatch.setattr(
        "mf4_analyzer.io.loader.ensure_mdf", lambda: (lambda _path: boom),
    )
    with pytest.raises(RuntimeError, match="programming error"):
        DataLoader.load_mf4("physical.mf4")
    assert boom.closed


def _assert_plain_metadata(value):
    if isinstance(value, dict):
        for item in value.values():
            _assert_plain_metadata(item)
        return
    if isinstance(value, list):
        for item in value:
            _assert_plain_metadata(item)
        return
    assert type(value) in {str, int, float, bool, type(None)}
