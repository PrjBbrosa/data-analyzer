from __future__ import annotations

import pytest

from mf4_analyzer.io.loader import DataLoader
from mf4_analyzer.ui.drawers.batch.input_panel import _default_probe_signals_for
from tests._helpers.mf4_factory import write_source_path_mf4


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
