"""Pure comparable-value contract for preset baselines (no QApplication)."""
from mf4_analyzer.ui.inspector_sections.preset_state import (
    apply_keep_ranges,
    build_preset_baseline,
    diff_preset_state,
    incompatible_amplitude_axes,
    infer_preset_baseline,
    manual_axis_conflicts,
    normalize_preset_params,
    validate_preset_baseline,
    values_match,
)


def _fft_collect(**overrides):
    base = dict(
        window="hanning",
        nfft="自动",
        nfft_mode="auto",
        t_win_s=1.5,
        overlap=50,
        avg_mode="线性平均",
        avg_overlap=50,
        amp_y="dB",
        db_reference_mode="auto",
        db_reference=1.0,
        autoscale=True,
        x_auto=True,
        x_min=0.0,
        x_max=0.0,
        y_auto=True,
        y_min=0.0,
        y_max=0.0,
        remark=False,
    )
    base.update(overrides)
    return base


def test_a1_manual_axis_change_is_axis_only():
    baseline = _fft_collect()
    current = _fft_collect(x_auto=False, autoscale=False, x_min=1.0, x_max=5.0)
    diff = diff_preset_state("fft", baseline, current)
    assert diff.params_differ is False
    assert diff.axes_differ is True


def test_a2_window_change_is_params_only():
    baseline = _fft_collect()
    current = _fft_collect(window="flattop")
    diff = diff_preset_state("fft", baseline, current)
    assert diff.params_differ is True
    assert diff.axes_differ is False


def test_a3_hidden_auto_limits_do_not_diff():
    baseline = _fft_collect(x_min=0.0, x_max=10.0)
    current = _fft_collect(x_min=3.0, x_max=9.0)
    diff = diff_preset_state("fft", baseline, current)
    assert diff.axes_differ is False
    assert diff.params_differ is False


def test_aliases_map_once_and_are_not_param_diffs():
    current = _fft_collect()
    aliased = dict(current)
    aliased.pop("x_auto")
    aliased["autoscale"] = True
    diff = diff_preset_state("fft", current, aliased)
    assert diff.params_differ is False
    assert diff.axes_differ is False
    assert "autoscale" not in normalize_preset_params("fft", aliased)


def test_fft_time_freq_and_dynamic_aliases():
    payload = {
        "window": "hanning",
        "nfft": "自动",
        "nfft_mode": "auto",
        "t_win_s": 1.5,
        "overlap": 50,
        "amplitude_mode": "Amplitude dB",
        "db_reference_mode": "auto",
        "freq_auto": False,
        "freq_min": 2.0,
        "freq_max": 20.0,
        "dynamic": "40 dB",
        "cmap": "viridis",
        "remove_mean": True,
    }
    norm = normalize_preset_params("fft_time", payload)
    assert norm["y_auto"] is False
    assert norm["y_min"] == 2.0
    assert norm["y_max"] == 20.0
    assert norm["z_auto"] is False
    assert norm["z_floor"] == -40.0
    assert "cmap" not in norm
    assert "remove_mean" not in norm
    assert "dynamic" not in norm


def test_numeric_tolerance_and_bool_is_not_int():
    assert values_match(75, 75.0)
    assert values_match(0.05, 0.05 + 1e-13)
    assert not values_match(0.05, 0.0501)
    assert not values_match(True, 1)
    assert not values_match(1, True)


def test_auto_nfft_ignores_effective_integer():
    baseline = _fft_collect(nfft="自动", nfft_mode="auto", nfft_effective=2048)
    current = _fft_collect(nfft="自动", nfft_mode="auto", nfft_effective=8192)
    diff = diff_preset_state("fft", baseline, current)
    assert diff.params_differ is False
    assert "nfft" not in normalize_preset_params("fft", baseline)


def test_auto_db_reference_ignores_resolved_value():
    baseline = _fft_collect(db_reference_mode="auto", db_reference=1.0)
    current = _fft_collect(db_reference_mode="auto", db_reference=9.9)
    diff = diff_preset_state("fft", baseline, current)
    assert diff.params_differ is False


def test_manual_db_reference_compares_value():
    baseline = _fft_collect(db_reference_mode="manual", db_reference=1.0)
    current = _fft_collect(db_reference_mode="manual", db_reference=2.0)
    diff = diff_preset_state("fft", baseline, current)
    assert diff.params_differ is True


def test_unknown_keys_fail_closed():
    baseline = _fft_collect()
    current = _fft_collect(mystery_knob=1)
    diff = diff_preset_state("fft", baseline, current)
    assert diff.params_differ is True
    assert "mystery_knob" in diff.unknown_keys


def test_empty_intersection_is_not_a_match():
    current = _fft_collect()
    assert infer_preset_baseline(
        "fft", current, {1: {"unrelated_key": 7}, 4: None},
    ) is None


def test_partial_payload_does_not_infer_baseline():
    current = _fft_collect()
    assert infer_preset_baseline(
        "fft", current, {2: {"window": "hanning", "overlap": 50}},
    ) is None


def test_frf_never_reports_axis_conflicts():
    current = {
        "estimator": "h1",
        "window": "hanning",
        "t_win_s": 2.0,
        "overlap": 0.5,
        "nfft_mode": "auto",
        "nfft": None,
        "magnitude_scale": "db",
        "frequency_scale": "log",
        "phase_mode": "unwrapped",
        "coherence_threshold": 0.8,
        "fade_low_coherence": True,
        "periodic_window": True,
        "detrend": "constant",
        "x_auto": False,
        "x_min": 1,
        "x_max": 2,
    }
    target = dict(current, t_win_s=8.0, x_auto=True)
    diff = diff_preset_state("frf", current, target)
    assert diff.axes_differ is False
    assert manual_axis_conflicts("frf", current, target) == []
    assert incompatible_amplitude_axes("frf", current, target) == []


def test_unit_change_marks_incompatible_amplitude_axis():
    fft_cur = _fft_collect(amp_y="dB", y_auto=False, y_min=-80.0, y_max=0.0)
    fft_tgt = _fft_collect(amp_y="Linear", y_auto=True)
    assert incompatible_amplitude_axes("fft", fft_cur, fft_tgt) == ["y"]

    tf_cur = {
        "amplitude_mode": "Amplitude dB",
        "db_reference_mode": "auto",
        "z_auto": False,
        "z_floor": -40.0,
        "z_ceiling": 0.0,
        "x_auto": True,
        "y_auto": True,
    }
    tf_tgt = dict(tf_cur, amplitude_mode="Amplitude")
    assert incompatible_amplitude_axes("fft_time", tf_cur, tf_tgt) == ["z"]
    assert incompatible_amplitude_axes("order", tf_cur, tf_tgt) == ["z"]


def test_keep_ranges_merges_x_and_autoresets_incompatible_y():
    current = _fft_collect(
        amp_y="dB",
        x_auto=False, autoscale=False, x_min=1.0, x_max=5.0,
        y_auto=False, y_min=-90.0, y_max=-10.0,
    )
    target = _fft_collect(amp_y="Linear", x_auto=True, y_auto=True, window="flattop")
    merged = apply_keep_ranges("fft", current, target)
    assert merged["window"] == "flattop"
    assert merged["x_auto"] is False
    assert merged["x_min"] == 1.0
    assert merged["x_max"] == 5.0
    assert merged["y_auto"] is True
    assert merged["amp_y"] == "Linear"


def test_manual_conflict_ignores_unused_auto_limits_on_target():
    current = _fft_collect(x_auto=False, autoscale=False, x_min=1.0, x_max=5.0)
    target = _fft_collect(x_auto=True, x_min=99.0, x_max=100.0)
    assert manual_axis_conflicts("fft", current, target) == ["x"]
    same = _fft_collect(x_auto=False, autoscale=False, x_min=1.0, x_max=5.0)
    assert manual_axis_conflicts("fft", current, same) == []


def test_validate_and_infer_baselines():
    current = _fft_collect()
    assert validate_preset_baseline({"kind": "fft"}) is None
    assert validate_preset_baseline("nope") is None
    good = build_preset_baseline("fft", 2, "均衡", current)
    assert validate_preset_baseline(good)["slot"] == 2
    assert validate_preset_baseline(good, expected_kind="order") is None
    custom = build_preset_baseline("test_kind", 1, "频率", current)
    assert validate_preset_baseline(custom, expected_kind="test_kind")["slot"] == 1
    assert validate_preset_baseline(custom) is None

    two = {
        1: dict(current),
        2: dict(current),
        4: None,
    }
    inferred = infer_preset_baseline("fft", current, two, {1: "频率", 2: "均衡"})
    assert inferred["slot"] == 1
    assert inferred["display_name"] == "频率"
    assert inferred["params"] == current
    inferred["params"]["overlap"] = 1
    assert current["overlap"] == 50

    assert infer_preset_baseline("fft", current, {4: None}) is None
    assert infer_preset_baseline("fft", current, {4: {}}) is None
