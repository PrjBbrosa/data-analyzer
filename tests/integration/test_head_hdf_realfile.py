"""HEAD HDF real-file grouping / NaN-drop / amplitude — explicit sample input.

Default suite does not read customer HDF. Synthetic grouping/NaN/RPM owners
live in ``tests/test_head_hdf_loader.py``. Supply this file via
``TRACELAB_HEAD_HDF_SAMPLE`` or ``TRACELAB_REALFILE_ROOT``. Required gate:
``TRACELAB_REQUIRE_REALFILE=1``. Amplitude oracles come from the verified
manifest baseline window, never a ``> 0`` stand-in.
"""
from __future__ import annotations

import numpy as np
import pytest

from mf4_analyzer.io.loader import DataLoader
from tests.realfile_corpus import CorpusSupplyError, resolve_realfile_sample


def _hdf_sample():
    try:
        return resolve_realfile_sample("head-hdf-260417-ripple")
    except CorpusSupplyError as exc:
        if exc.optional:
            pytest.skip(str(exc))
        pytest.fail(str(exc))


def test_real_file_groups_and_counts():
    entry, path = _hdf_sample()
    groups = DataLoader.load_hdf(str(path))
    suff = {g["label_suffix"] for g in groups}
    expected = set(entry["expected_suffixes"])
    absent = set(entry["absent_suffixes"])
    assert expected <= suff
    assert suff.isdisjoint(absent), f"dropped-rate groups still present: {suff & absent}"

    fast = next(g for g in groups if g["label_suffix"] == "24x")
    assert any(c == "L" for c in fast["channels"])
    assert len(fast["data"]) == entry["fast_length"]
    slow = next(g for g in groups if g["label_suffix"] == "1x")
    assert len(slow["data"]) == entry["slow_length"]

    dropped = fast["source_metadata"].get("dropped_channels") or []
    dropped_names = {item.get("name") for item in dropped}
    assert entry["dropped_channel_name"] in dropped_names

    baseline = entry.get("amplitude_baseline")
    if not baseline:
        pytest.skip(
            "UNAUDITED HEAD HDF amplitude/unit: manifest has no verified "
            "baseline window for this sample"
        )
    channel = baseline["channel"]
    values = fast["data"][channel].to_numpy()
    assert fast["units"][channel] == baseline["unit"]
    assert len(values) == baseline["n"]
    assert values[0] == pytest.approx(baseline["first"], rel=0, abs=1e-12)
    assert float(np.nanmin(values)) == pytest.approx(baseline["min"], rel=0, abs=1e-12)
    assert float(np.nanmax(values)) == pytest.approx(baseline["max"], rel=0, abs=1e-12)
    assert float(np.nanmax(np.abs(values))) == pytest.approx(
        baseline["absmax"], rel=0, abs=1e-12
    )
