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


def _hdf_sample(sample_id="head-hdf-260417-ripple"):
    try:
        return resolve_realfile_sample(sample_id)
    except CorpusSupplyError as exc:
        if exc.optional:
            pytest.skip(str(exc))
        pytest.fail(str(exc))


def _assert_sampling(group, spec):
    meta = group["source_metadata"]
    time = group["data"]["Time"].to_numpy()
    dt = 1.0 / spec["fs_hz"]
    assert meta["sampling_rule"]
    assert meta["fs"] == pytest.approx(spec["fs_hz"])
    assert meta["n_samples"] == spec["n_samples"]
    assert len(time) == spec["n_samples"]
    if len(time) >= 2:
        assert time[1] - time[0] == pytest.approx(dt)
        assert time[-1] == pytest.approx((spec["n_samples"] - 1) * dt)


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
    sampling = entry["expected_sampling"]
    assert fast["source_metadata"]["sampling_rule"] == sampling["sampling_rule"]
    assert fast["source_metadata"]["slot_count"] == sampling["slot_count"]
    assert fast["source_metadata"]["n_samples"] * fast["source_metadata"]["dt"] == pytest.approx(
        sampling["coverage_s"]
    )
    for suffix, spec in sampling["groups"].items():
        _assert_sampling(next(g for g in groups if g["label_suffix"] == suffix), spec)


def test_real_simultaneous_file_uses_header_delta():
    """Structural expectation from the file header. Not a HEAD Companion certificate."""
    entry, path = _hdf_sample("head-hdf-20260924-simultaneous")
    groups = DataLoader.load_hdf(str(path))
    assert {g["label_suffix"] for g in groups} == set(entry["expected_suffixes"])
    sampling = entry["expected_sampling"]
    group = groups[0]
    assert group["source_metadata"]["sampling_rule"] == "simultaneous"
    assert group["source_metadata"]["fs"] != pytest.approx(2000.0)
    assert group["source_metadata"]["n_samples"] * group["source_metadata"]["dt"] == pytest.approx(
        sampling["coverage_s"]
    )
    _assert_sampling(group, sampling["groups"]["1x"])


def test_official_head_hdf_time_basis_is_explicit():
    """Structure checks must not be recorded as an official time-base acceptance."""
    from tests.realfile_corpus import read_realfile_manifest

    hdf = [
        sample for sample in read_realfile_manifest()["samples"]
        if sample.get("format") == "head-hdf"
    ]
    assert hdf
    for sample in hdf:
        basis = sample.get("official_time_basis")
        assert basis in {"pending", "verified"}
        if basis == "verified":
            assert str(sample.get("official_software") or "").strip()
            assert str(sample.get("official_evidence_sha256") or "").strip()
