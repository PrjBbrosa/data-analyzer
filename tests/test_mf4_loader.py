from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.io.loader import DataLoader, prepare_shared_time_series
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


def test_prepare_shared_time_series_repairs_ties_and_reversals():
    tied = prepare_shared_time_series(
        [0.0, 0.01, 0.01, 0.03],
        [0.0, 1.0, 5.0, 9.0],
    )
    assert tied is not None
    assert tied[0].tolist() == pytest.approx([0.0, 0.01, 0.03])
    assert tied[1].tolist() == pytest.approx([0.0, 5.0, 9.0])

    reversed_time = prepare_shared_time_series(
        [0.0, 0.03, 0.01, 0.02],
        [1.0, 4.0, 2.0, 3.0],
    )
    assert reversed_time is not None
    assert reversed_time[0].tolist() == pytest.approx([0.0, 0.01, 0.02, 0.03])
    assert reversed_time[1].tolist() == pytest.approx([1.0, 2.0, 3.0, 4.0])
    assert prepare_shared_time_series([0.0, 1.0], [1.0]) is None


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


def test_load_mf4_keeps_a_backward_time_step(tmp_path):
    mf4 = write_signal_groups_mf4(
        tmp_path / "backward.mf4",
        [
            [("clock", [0.0, 0.0, 0.0, 0.0], [0.0, 1.0, 2.0, 3.0])],
            [("wound", [1.0, 4.0, 2.0, 3.0], [0.0, 3.0, 1.0, 2.0])],
        ],
    )

    df, channels, _units = DataLoader.load_mf4(str(mf4))

    assert "wound" in channels
    assert df["wound"].tolist() == pytest.approx([1.0, 2.0, 3.0, 4.0])


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
