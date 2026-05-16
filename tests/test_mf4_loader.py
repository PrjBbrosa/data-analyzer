from __future__ import annotations

import numpy as np
import pytest
from asammdf import MDF, Signal
from asammdf.blocks.source_utils import Source

from mf4_analyzer.io.loader import DataLoader
from mf4_analyzer.ui.drawers.batch.input_panel import _default_probe_signals_for


def _write_source_path_mf4(path, channels):
    timestamps = np.asarray((0.0, 0.01, 0.02, 0.03), dtype=float)
    signals = []
    for name, unit, source_path, samples in channels:
        signals.append(
            Signal(
                samples=np.asarray(samples, dtype=float),
                timestamps=timestamps,
                name=name,
                unit=unit,
                source=Source(
                    name="",
                    path=source_path,
                    comment="",
                    source_type=Source.SOURCE_ECU,
                    bus_type=Source.BUS_TYPE_CAN,
                ),
            )
        )
    mdf = MDF(version="4.10")
    mdf.append(signals)
    mdf.save(str(path), overwrite=True)
    mdf.close()
    return path


def test_load_mf4_deduplicates_source_path_aliases(tmp_path):
    mf4 = _write_source_path_mf4(
        tmp_path / "alias.mf4",
        (("sig", "V", "A_side", (1.0, 2.0, 3.0, 4.0)),),
    )

    df, channels, units = DataLoader.load_mf4(str(mf4))

    assert "sig" in channels
    assert "A_side.sig" not in channels
    assert channels.count("sig") == 1
    assert "sig" in df.columns
    assert units["sig"] == "V"


def test_batch_probe_deduplicates_source_path_aliases(tmp_path):
    mf4 = _write_source_path_mf4(
        tmp_path / "alias.mf4",
        (("sig", "V", "A_side", (1.0, 2.0, 3.0, 4.0)),),
    )

    channels = _default_probe_signals_for(str(mf4))

    assert "sig" in channels
    assert "A_side.sig" not in channels


def test_load_mf4_keeps_source_path_when_short_name_is_ambiguous(tmp_path):
    mf4 = _write_source_path_mf4(
        tmp_path / "ambiguous.mf4",
        (
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
