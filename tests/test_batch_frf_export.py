from __future__ import annotations

from types import SimpleNamespace
import threading

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.batch_compute import (
    BatchFrfDataError,
    FRF_EXPORT_COLUMNS,
    compute_prepared_frf,
    prepare_frf_task,
)
from mf4_analyzer.batch_types import _BatchCancelled
from mf4_analyzer.signal.frf import FrfResult


def _file_data(*, fs=100.0, samples=400, time_source="column"):
    time = np.arange(samples, dtype=float) / fs
    command = np.sin(2.0 * np.pi * 5.0 * time)
    response = 2.0 * command
    return SimpleNamespace(
        data=pd.DataFrame({"command": command, "response": response}),
        time_array=time,
        fs=fs,
        _time_source=time_source,
        channel_units={"command": "V", "response": "N"},
        channel_metadata={},
    )


def _params(**updates):
    params = {
        "estimator": "h1",
        "window": "hanning",
        "periodic_window": True,
        "t_win_s": 0.5,
        "overlap": 0.5,
        "nfft_mode": "auto",
        "detrend": "none",
    }
    params.update(updates)
    return params


def test_batch_frf_adapter_exports_fixed_numeric_columns_and_raw_result():
    prepared = prepare_frf_task(
        _file_data(), "command", "response", _params(),
    )
    computed = compute_prepared_frf(prepared)

    assert tuple(computed.dataframe.columns) == FRF_EXPORT_COLUMNS
    assert isinstance(computed.result, FrfResult)
    assert np.iscomplexobj(computed.result.transfer)
    assert np.iscomplexobj(computed.result.pxy)
    assert all(dtype.kind in "fc" for dtype in computed.dataframe.dtypes)
    np.testing.assert_allclose(
        computed.dataframe["transfer_real"].to_numpy()[1:6], 2.0,
        atol=1e-10,
    )
    assert computed.input_unit == "V"
    assert computed.output_unit == "N"


def test_batch_frf_preflight_applies_one_physical_time_mask_to_both_channels():
    prepared = prepare_frf_task(
        _file_data(),
        "command",
        "response",
        _params(time_range=(1.0, 2.5)),
    )

    assert prepared.input_values.shape == prepared.output_values.shape
    assert prepared.input_time.shape == prepared.output_time.shape
    np.testing.assert_array_equal(prepared.input_time, prepared.output_time)
    assert prepared.input_time[0] == pytest.approx(1.0)
    assert prepared.input_time[-1] == pytest.approx(2.5)


def test_batch_frf_preflight_rejects_missing_or_invented_timebase():
    generated = _file_data(time_source="generated")
    missing = _file_data()
    missing.time_array = None

    with pytest.raises(ValueError, match="真实时间轴"):
        prepare_frf_task(generated, "command", "response", _params())
    with pytest.raises(ValueError, match="真实时间轴"):
        prepare_frf_task(missing, "command", "response", _params())


def test_batch_frf_preflight_auto_rebuilds_time_length_uniformity_without_truncation():
    wrong_length = _file_data()
    wrong_length.time_array = wrong_length.time_array[:-1]
    jittered = _file_data()
    jittered.time_array = jittered.time_array.copy()
    jittered.time_array[100:] += 0.02

    with pytest.raises(ValueError, match="same length|等长"):
        prepare_frf_task(wrong_length, "command", "response", _params())
    prepared = prepare_frf_task(jittered, "command", "response", _params())
    assert prepared.warnings
    assert "自动重建" in prepared.warnings[0]
    assert "relative_jitter=" in prepared.warnings[0]
    np.testing.assert_allclose(
        np.diff(prepared.input_time),
        np.full(prepared.input_time.size - 1, 1.0 / prepared.fs),
        rtol=0,
        atol=1e-12,
    )


def test_batch_frf_preflight_rejects_insufficient_complete_segments():
    with pytest.raises(ValueError, match="2 complete segments|2 个完整段"):
        prepare_frf_task(
            _file_data(samples=60),
            "command",
            "response",
            _params(t_win_s=0.5, overlap=0.0),
        )


def test_batch_frf_preflight_classifies_oversized_manual_nfft_as_data_error():
    with pytest.raises(BatchFrfDataError, match="temporary complex.*64 MiB"):
        prepare_frf_task(
            _file_data(),
            "command",
            "response",
            _params(nfft_mode="manual", nfft=4_194_304),
        )


def test_batch_frf_preflight_does_not_reclassify_programming_planner_value_error(
    monkeypatch,
):
    import mf4_analyzer.batch_compute as batch_compute_module

    def defect(*args, **kwargs):
        raise ValueError("unexpected request planner contract defect")

    monkeypatch.setattr(batch_compute_module, "plan_frf_request", defect)

    with pytest.raises(ValueError, match="unexpected request planner") as raised:
        prepare_frf_task(
            _file_data(), "command", "response", _params(),
        )
    assert not isinstance(raised.value, BatchFrfDataError)


def test_batch_frf_compute_cancellation_uses_batch_taxonomy():
    prepared = prepare_frf_task(
        _file_data(), "command", "response", _params(),
    )
    token = threading.Event()
    token.set()

    with pytest.raises(_BatchCancelled, match="FRF"):
        compute_prepared_frf(prepared, cancel_token=token)


def test_batch_frf_maps_cancelled_and_overflow_by_exception_type(monkeypatch):
    """D11: adapters catch FrfCancelled / FrfSpectralOverflow by type.

    A RuntimeError/ValueError that merely *says* the old message must not be
    remapped — that was the fragile string-equality path.
    """
    from mf4_analyzer import batch_compute as batch_compute_module
    from mf4_analyzer.signal.frf import FrfCancelled, FrfSpectralOverflow

    prepared = prepare_frf_task(
        _file_data(), "command", "response", _params(),
    )

    def raise_cancelled(*_a, **_k):
        raise FrfCancelled()

    monkeypatch.setattr(batch_compute_module, "compute_frf", raise_cancelled)
    with pytest.raises(_BatchCancelled, match="cancelled during FRF"):
        compute_prepared_frf(prepared)

    def raise_overflow(*_a, **_k):
        raise FrfSpectralOverflow()

    monkeypatch.setattr(batch_compute_module, "compute_frf", raise_overflow)
    with pytest.raises(BatchFrfDataError, match="spectral accumulation overflow"):
        compute_prepared_frf(prepared)

    def raise_lookalike_runtime(*_a, **_k):
        raise RuntimeError("FRF computation cancelled")

    monkeypatch.setattr(batch_compute_module, "compute_frf", raise_lookalike_runtime)
    with pytest.raises(RuntimeError, match="FRF computation cancelled") as raised:
        compute_prepared_frf(prepared)
    assert not isinstance(raised.value, _BatchCancelled)

    def raise_lookalike_value(*_a, **_k):
        raise ValueError(
            "spectral accumulation overflow; rescale the input signals"
        )

    monkeypatch.setattr(batch_compute_module, "compute_frf", raise_lookalike_value)
    with pytest.raises(ValueError, match="spectral accumulation overflow") as raised:
        compute_prepared_frf(prepared)
    assert not isinstance(raised.value, BatchFrfDataError)


def test_batch_frf_time_range_discards_outside_nonfinite_and_time_glitches():
    fd = _file_data()
    fd.data.loc[0, "command"] = np.nan
    fd.data.loc[len(fd.data) - 1, "response"] = np.inf
    fd.time_array = fd.time_array.copy()
    fd.time_array[0] = np.nan
    fd.time_array[-1] = -10.0

    prepared = prepare_frf_task(
        fd,
        "command",
        "response",
        _params(time_range=(1.0, 2.5)),
    )

    assert np.isfinite(prepared.input_values).all()
    assert np.isfinite(prepared.output_values).all()
    assert np.isfinite(prepared.input_time).all()
    assert prepared.input_time[0] == pytest.approx(1.0)
    assert prepared.input_time[-1] == pytest.approx(2.5)


@pytest.mark.parametrize("kind", ("signal", "time"))
def test_batch_frf_time_range_handles_glitch_inside_selected_interval(kind):
    fd = _file_data()
    selected_index = 150
    if kind == "signal":
        fd.data.loc[selected_index, "command"] = np.nan
        with pytest.raises(BatchFrfDataError, match="non-finite"):
            prepare_frf_task(
                fd,
                "command",
                "response",
                _params(time_range=(1.0, 2.5)),
            )
        return

    fd.time_array = fd.time_array.copy()
    fd.time_array[selected_index] += 0.002
    prepared = prepare_frf_task(
        fd,
        "command",
        "response",
        _params(time_range=(1.0, 2.5)),
    )
    assert prepared.warnings
    assert "自动重建" in prepared.warnings[0]
    assert np.isfinite(prepared.input_time).all()
    np.testing.assert_allclose(
        np.diff(prepared.input_time),
        np.full(prepared.input_time.size - 1, 1.0 / prepared.fs),
        rtol=0,
        atol=1e-12,
    )


def test_batch_frf_adapter_does_not_reclassify_programming_compute_value_error(
    monkeypatch,
):
    import mf4_analyzer.batch_compute as batch_compute_module

    prepared = prepare_frf_task(
        _file_data(), "command", "response", _params(),
    )

    def defect(*args, **kwargs):
        raise ValueError("unexpected compute shape contract defect")

    monkeypatch.setattr(batch_compute_module, "compute_frf", defect)

    with pytest.raises(ValueError, match="unexpected compute") as raised:
        compute_prepared_frf(prepared)
    assert not isinstance(raised.value, BatchFrfDataError)


def test_batch_frf_adapter_does_not_reclassify_dataframe_value_error(monkeypatch):
    import mf4_analyzer.batch_compute as batch_compute_module

    prepared = prepare_frf_task(
        _file_data(), "command", "response", _params(),
    )

    def defect(*args, **kwargs):
        raise ValueError("unexpected DataFrame column contract defect")

    monkeypatch.setattr(batch_compute_module.pd, "DataFrame", defect)

    with pytest.raises(ValueError, match="unexpected DataFrame") as raised:
        compute_prepared_frf(prepared)
    assert not isinstance(raised.value, BatchFrfDataError)
