from dataclasses import FrozenInstanceError
import subprocess
import sys

import pytest


# Display-axis keys every fft / order_time preset now carries so applying a
# preset also restores the axis windows (previously only fft_time did).  The
# ranges are neutral placeholders — auto is on, so the numbers are inert until
# the user disables auto.
_AUTO_XY_AXES = {
    "x_auto": True,
    "x_min": 0.0,
    "x_max": 0.0,
    "y_auto": True,
    "y_min": 0.0,
    "y_max": 0.0,
}

EXPECTED_FFT = {
    "torque": {
        "window": "flattop",
        "nfft": "自动",
        "t_win_s": 2.5,
        "overlap": 75,
        "amp_y": "dB",
        "avg_mode": "线性平均",
        "avg_overlap": 75,
        **_AUTO_XY_AXES,
    },
    "vibration": {
        "window": "hanning",
        "nfft": "自动",
        "t_win_s": 1.5,
        "overlap": 50,
        "amp_y": "dB",
        "avg_mode": "线性平均",
        "avg_overlap": 50,
        **_AUTO_XY_AXES,
    },
    "transient": {
        "window": "hanning",
        "nfft": "自动",
        "t_win_s": 0.6,
        "overlap": 75,
        "amp_y": "dB",
        "avg_mode": "峰值保持",
        "avg_overlap": 75,
        **_AUTO_XY_AXES,
    },
}

# The order-map colour scale rides along with amplitude_mode="Amplitude dB":
# -50..-10 dB is the panel's own first-open window, so a preset that pins the
# scale would have to state the same numbers it already shows.
_ORDER_Z_AXIS = {
    "z_auto": True,
    "z_floor": -50.0,
    "z_ceiling": -10.0,
}

EXPECTED_ORDER = {
    "torque": {
        "max_order": 20,
        "order_res": 0.05,
        "time_res": 0.10,
        "nfft": "自动",
        "samples_per_rev": 256,
        "amplitude_mode": "Amplitude dB",
        "window": "flattop",
        **_AUTO_XY_AXES,
        **_ORDER_Z_AXIS,
    },
    "vibration": {
        "max_order": 50,
        "order_res": 0.10,
        "time_res": 0.05,
        "nfft": "自动",
        "samples_per_rev": 512,
        "amplitude_mode": "Amplitude dB",
        "window": "hanning",
        **_AUTO_XY_AXES,
        **_ORDER_Z_AXIS,
    },
    "transient": {
        "max_order": 30,
        "order_res": 0.25,
        "time_res": 0.02,
        "nfft": "自动",
        "samples_per_rev": 256,
        "amplitude_mode": "Amplitude dB",
        "window": "hanning",
        **_AUTO_XY_AXES,
        **_ORDER_Z_AXIS,
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

    assert SUPPORTED_ANALYSIS_METHODS == ("fft", "fft_time", "frf", "order_time")
    assert BUILTIN_PRESET_KEYS == ("torque", "vibration", "transient")
    for method in ("fft", "fft_time", "order_time"):
        assert tuple(p.key for p in list_builtin_presets(method)) == BUILTIN_PRESET_KEYS


def test_frf_has_method_specific_names_and_reproducible_defaults():
    from mf4_analyzer.analysis_presets import list_builtin_presets

    presets = list_builtin_presets("frf")
    assert tuple(p.key for p in presets) == ("robust", "low_frequency", "fast")
    assert tuple(p.display_name for p in presets) == ("稳健", "低频", "快速")
    assert tuple(p.slot for p in presets) == (1, 2, 3)
    assert [p.params["t_win_s"] for p in presets] == [2.0, 8.0, 0.5]
    assert [p.params["overlap"] for p in presets] == [0.5, 0.75, 0.5]
    for preset in presets:
        assert preset.params["estimator"] == "h1"
        assert preset.params["window"] == "hanning"
        assert preset.params["nfft_mode"] == "auto"
        assert preset.params["nfft"] is None
        assert preset.params["frequency_scale"] == "log"
        assert preset.params["phase_mode"] == "unwrapped"


def test_fft_and_order_values_match_the_existing_contextual_contract():
    assert _params_by_key("fft") == EXPECTED_FFT
    assert _params_by_key("order_time") == EXPECTED_ORDER


def test_order_time_window_is_aligned_with_fft_and_fft_time():
    # C2: order_time presets now declare `window`, matching fft / fft_time
    # one-to-one (torque -> flattop, vibration/transient -> hanning). This
    # is a deliberate behavior change: applying the order "frequency"
    # (torque) preset switches the live window from hanning to flattop,
    # for both single-file analysis and batch (analysis_presets is shared).
    order_presets = _params_by_key("order_time")
    assert order_presets["torque"]["window"] == "flattop"
    assert order_presets["vibration"]["window"] == "hanning"
    assert order_presets["transient"]["window"] == "hanning"
    for key in ("torque", "vibration", "transient"):
        assert order_presets[key]["window"] == EXPECTED_FFT[key]["window"]


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
    assert presets["vibration"]["z_floor"] == -40.0
    assert presets["transient"]["t_win_s"] == 0.6
    assert presets["transient"]["overlap"] == 75
    assert presets["transient"]["z_floor"] == -30.0


def test_time_has_no_builtin_analysis_presets():
    from mf4_analyzer.analysis_presets import get_builtin_preset, list_builtin_presets

    with pytest.raises(ValueError, match="unsupported analysis method"):
        list_builtin_presets("time")
    with pytest.raises(ValueError, match="unsupported analysis method"):
        get_builtin_preset("time", "transient")


def test_no_builtin_preset_carries_a_colormap():
    """内建预设不得携带 ``cmap``。

    色图由图表选项实时决定：FFT-vs-Time 面板恒定发 ``_FIXED_CMAP``、应用预设时
    显式跳过预设里的 cmap，批处理参数表单没有色图控件。fft_time 三个预设过去
    各带一个（torque=viridis、vibration/transient=turbo），全程无人消费，只会
    让人以为换预设能换配色。这条守卫防止它被「补全」回来。
    """
    from mf4_analyzer.analysis_presets import (
        SUPPORTED_ANALYSIS_METHODS, list_builtin_presets,
    )

    for method in SUPPORTED_ANALYSIS_METHODS:
        for preset in list_builtin_presets(method):
            assert "cmap" not in preset.params, (
                f"{method}/{preset.key} 又带上了 cmap"
            )


def test_chart_methods_carry_display_axis_ranges_and_frf_does_not():
    """有轴控件的方法必须带全套轴键，没轴控件的 frf 必须不带。

    坐标轴显示上下限属于预设：控件真实存在、Inspector 与批处理输出面板都消费，
    预设不带就等于「换预设不还原坐标轴」，用户手动改过的窗口会跨预设残留。
    FRF 面板没有轴 spin 控件，给它加轴键就变成第二类幽灵键。
    """
    from mf4_analyzer.analysis_presets import list_builtin_presets

    xy_keys = {"x_auto", "x_min", "x_max", "y_auto", "y_min", "y_max"}
    z_keys = {"z_auto", "z_floor", "z_ceiling"}
    for method in ("fft", "fft_time", "order_time"):
        for preset in list_builtin_presets(method):
            assert xy_keys <= set(preset.params), (method, preset.key)
            # 只有热图方法有色阶；一维 FFT 的幅值窗口就是 Y 轴。
            has_z = method != "fft"
            assert (z_keys <= set(preset.params)) is has_z, (method, preset.key)
    for preset in list_builtin_presets("frf"):
        assert not (xy_keys | z_keys) & set(preset.params), preset.key


def test_records_and_nested_params_are_immutable_but_each_lookup_is_fresh():
    from mf4_analyzer.analysis_presets import get_builtin_preset

    first = get_builtin_preset("fft", "transient")
    second = get_builtin_preset("fft", "transient")

    assert first is not second
    assert first.params is not second.params
    with pytest.raises(FrozenInstanceError):
        first.key = "changed"
    with pytest.raises(TypeError):
        first.params["t_win_s"] = 2.0
    copy = first.params_copy()
    copy["t_win_s"] = 2.0
    assert second.params["t_win_s"] == 0.6


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
    assert recommend_builtin_preset("N·m") == "torque"
    assert recommend_builtin_preset("m/s^2") == "vibration"
    assert recommend_builtin_preset("g") == "vibration"
    # ``bar`` is a torque-family pressure alias, not an unknown unit.
    assert recommend_builtin_preset("bar") == "torque"
    assert recommend_builtin_preset("kg") is None
    assert recommend_builtin_preset("") is None
    assert recommend_builtin_preset(None) is None
    assert recommend_builtin_preset("rpm") is None


def test_builtin_patches_never_own_runtime_output_or_db_state():
    from mf4_analyzer.analysis_presets import (
        SUPPORTED_ANALYSIS_METHODS,
        list_builtin_presets,
    )

    forbidden = {
        "source", "signal", "source_ids", "source_paths", "file_ids",
        "file_paths", "outputs", "output_dir", "conflict_policy",
        "weighting", "db_reference", "db_reference_mode",
        # 幽灵键，同 cmap：FRF 面板没有对应控件，compute_params 把它们硬编码成
        # True / "constant"，apply_params 连读都不读，而三条预设取值全同——
        # 换预设永远改不了它们。批处理配方里的同名字段是活的，不受这条影响。
        "periodic_window", "detrend",
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
