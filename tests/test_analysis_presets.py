from dataclasses import FrozenInstanceError
import subprocess
import sys

import pytest


EXPECTED_FFT = {
    "torque": {
        "window": "flattop",
        "nfft": "自动",
        "t_win_s": 2.5,
        "overlap": 75,
        "amp_y": "dB",
        "avg_mode": "线性平均",
        "avg_overlap": 75,
    },
    "vibration": {
        "window": "hanning",
        "nfft": "自动",
        "t_win_s": 1.5,
        "overlap": 50,
        "amp_y": "dB",
        "avg_mode": "线性平均",
        "avg_overlap": 50,
    },
    "transient": {
        "window": "hanning",
        "nfft": "自动",
        "t_win_s": 0.6,
        "overlap": 75,
        "amp_y": "dB",
        "avg_mode": "峰值保持",
        "avg_overlap": 75,
    },
}

EXPECTED_ORDER = {
    "torque": {
        "max_order": 20,
        "order_res": 0.05,
        "time_res": 0.10,
        "nfft": "自动",
        "samples_per_rev": 256,
        "amplitude_mode": "Amplitude dB",
    },
    "vibration": {
        "max_order": 50,
        "order_res": 0.10,
        "time_res": 0.05,
        "nfft": "自动",
        "samples_per_rev": 512,
        "amplitude_mode": "Amplitude dB",
    },
    "transient": {
        "max_order": 30,
        "order_res": 0.25,
        "time_res": 0.02,
        "nfft": "自动",
        "samples_per_rev": 256,
        "amplitude_mode": "Amplitude dB",
    },
}


def _params_by_key(method):
    from mf4_analyzer.analysis_presets import list_builtin_presets

    return {item.key: item.params_copy() for item in list_builtin_presets(method)}


def test_provider_has_canonical_methods_and_stable_slot_order():
    from mf4_analyzer.analysis_presets import (
        BUILTIN_PRESET_KEYS,
        SUPPORTED_ANALYSIS_METHODS,
        list_builtin_presets,
    )

    assert SUPPORTED_ANALYSIS_METHODS == ("fft", "fft_time", "order_time", "time")
    assert BUILTIN_PRESET_KEYS == ("torque", "vibration", "transient")
    for method in SUPPORTED_ANALYSIS_METHODS:
        assert tuple(p.key for p in list_builtin_presets(method)) == BUILTIN_PRESET_KEYS


def test_fft_and_order_values_match_the_existing_contextual_contract():
    assert _params_by_key("fft") == EXPECTED_FFT
    assert _params_by_key("order_time") == EXPECTED_ORDER
    assert all("window" not in patch for patch in EXPECTED_ORDER.values())


def test_fft_time_values_match_existing_full_contextual_contract():
    presets = _params_by_key("fft_time")

    assert presets["torque"] == {
        "window": "flattop",
        "nfft": "自动",
        "nfft_mode": "auto",
        "t_win_s": 2.5,
        "overlap": 75,
        "amplitude_mode": "Amplitude dB",
        "remove_mean": True,
        "freq_auto": True,
        "freq_min": 0.0,
        "freq_max": 0.0,
        "dynamic": "Auto",
        "cmap": "viridis",
        "x_auto": True,
        "x_min": 0.0,
        "x_max": 0.0,
        "y_auto": True,
        "y_min": 0.0,
        "y_max": 0.0,
        "z_auto": True,
        "z_floor": -40.0,
        "z_ceiling": 0.0,
    }
    assert presets["vibration"]["window"] == "hanning"
    assert presets["vibration"]["t_win_s"] == 1.5
    assert presets["vibration"]["overlap"] == 50
    assert presets["vibration"]["cmap"] == "turbo"
    assert presets["vibration"]["z_floor"] == -40.0
    assert presets["transient"]["t_win_s"] == 0.6
    assert presets["transient"]["overlap"] == 75
    assert presets["transient"]["z_floor"] == -30.0


def test_time_contract_only_enables_time_and_only_declares_preprocess():
    presets = {p.key: p for p in __import__(
        "mf4_analyzer.analysis_presets", fromlist=["list_builtin_presets"]
    ).list_builtin_presets("time")}

    assert presets["torque"].enabled is False
    assert presets["vibration"].enabled is False
    assert presets["transient"].enabled is True
    assert presets["torque"].params_copy() == {}
    assert presets["vibration"].params_copy() == {}
    assert presets["transient"].params_copy() == {
        "time_preprocess": {
            "scale": 1.0,
            "offset": 0.0,
            "remove_mean": False,
            "sample_mode": "original",
            "target_fs": None,
            "decimation_factor": 1,
        }
    }


def test_records_and_nested_params_are_immutable_but_each_lookup_is_fresh():
    from mf4_analyzer.analysis_presets import get_builtin_preset

    first = get_builtin_preset("time", "transient")
    second = get_builtin_preset("time", "transient")

    assert first is not second
    assert first.params is not second.params
    with pytest.raises(FrozenInstanceError):
        first.key = "changed"
    with pytest.raises(TypeError):
        first.params["time_preprocess"] = {}
    with pytest.raises(TypeError):
        first.params["time_preprocess"]["scale"] = 2.0
    copy = first.params_copy()
    copy["time_preprocess"]["scale"] = 2.0
    assert second.params["time_preprocess"]["scale"] == 1.0


def test_alias_get_and_unit_recommendation_contract():
    from mf4_analyzer.analysis_presets import (
        get_builtin_preset,
        recommend_builtin_preset,
        resolve_builtin_preset_alias,
    )

    assert resolve_builtin_preset_alias("fft_time", "diagnostic") == "vibration"
    assert resolve_builtin_preset_alias("fft_time", "amplitude_accuracy") == "torque"
    assert resolve_builtin_preset_alias("fft_time", "high_frequency") == "transient"
    assert get_builtin_preset("fft_time", "diagnostic").key == "vibration"
    assert recommend_builtin_preset("Nm") == "torque"
    assert recommend_builtin_preset("m/s^2") == "vibration"
    assert recommend_builtin_preset("kg") == "vibration"
    assert recommend_builtin_preset(None) == "vibration"


def test_builtin_patches_never_own_runtime_output_or_db_state():
    from mf4_analyzer.analysis_presets import (
        SUPPORTED_ANALYSIS_METHODS,
        list_builtin_presets,
    )

    forbidden = {
        "source", "signal", "source_ids", "source_paths", "file_ids",
        "file_paths", "outputs", "output_dir", "conflict_policy",
        "weighting", "db_reference", "db_reference_mode",
    }
    for method in SUPPORTED_ANALYSIS_METHODS:
        for preset in list_builtin_presets(method):
            assert forbidden.isdisjoint(preset.params)


def test_unknown_method_or_key_is_explicit():
    from mf4_analyzer.analysis_presets import get_builtin_preset, list_builtin_presets

    with pytest.raises(ValueError, match="unsupported analysis method"):
        list_builtin_presets("order")
    with pytest.raises(KeyError):
        get_builtin_preset("fft", "missing")


def test_provider_import_does_not_load_pyqt():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import mf4_analyzer.analysis_presets; "
                "raise SystemExit(any(name.startswith('PyQt5') for name in sys.modules))"
            ),
        ],
        check=False,
    )
    assert result.returncode == 0
