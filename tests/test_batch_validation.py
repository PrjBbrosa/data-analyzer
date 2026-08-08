from __future__ import annotations

from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from mf4_analyzer.batch_validation import (
    guard_filter_params,
    validate_outputs,
    validate_recipe,
    validate_task,
)


def test_validate_outputs_requires_at_least_one_selected_output():
    issues = validate_outputs(SimpleNamespace(
        export_data=False,
        export_image=False,
        data_format="csv",
    ))

    assert any(issue.field == "outputs" for issue in issues)


@pytest.mark.parametrize("data_format", ("", "xls", "parquet"))
def test_validate_outputs_rejects_unsupported_enabled_data_format(data_format):
    issues = validate_outputs(SimpleNamespace(
        export_data=True,
        export_image=False,
        data_format=data_format,
    ))

    assert any(issue.field == "data_format" for issue in issues)


def test_validate_outputs_ignores_data_format_when_only_image_is_enabled():
    issues = validate_outputs(SimpleNamespace(
        export_data=False,
        export_image=True,
        data_format="parquet",
    ))

    assert not any(issue.field == "data_format" for issue in issues)


def _phase3_outputs(**overrides):
    values = {
        "export_data": True,
        "export_image": True,
        "data_format": "csv",
        "image_format": "png",
        "image_size": "1920x1080",
        "image_width": 1920,
        "image_height": 1080,
        "image_dpi": 144,
        "image_background": "white",
        "image_line_width": 1.0,
        "conflict_policy": "auto_number",
        "resume_policy": "none",
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize("container", (dict, lambda values: SimpleNamespace(**values)))
@pytest.mark.parametrize(
    ("overrides", "expected_fields"),
    (
        ({"image_format": "webp"}, {"image_format"}),
        ({"image_format": "pdf"}, {"image_format"}),
        ({"image_format": "svg"}, {"image_format"}),
        ({"image_size": "retina"}, {"image_size"}),
        (
            {"image_size": "custom", "image_width": 319},
            {"image_width"},
        ),
        (
            {"image_size": "custom", "image_height": 16_385},
            {"image_height"},
        ),
        (
            {
                "image_size": "custom",
                "image_width": 10_000,
                "image_height": 10_000,
            },
            {"image_pixels"},
        ),
        ({"image_dpi": 35}, {"image_dpi"}),
        ({"image_background": "paper"}, {"image_background"}),
        ({"image_line_width": True}, {"image_line_width"}),
        ({"image_line_width": float("inf")}, {"image_line_width"}),
        ({"image_line_width": 0.49}, {"image_line_width"}),
        ({"image_line_width": 4.01}, {"image_line_width"}),
        ({"conflict_policy": "rename"}, {"conflict_policy"}),
        ({"resume_policy": "filename"}, {"resume_policy"}),
    ),
)
def test_validate_outputs_covers_phase3_fields_for_mapping_and_duck_object(
    container, overrides, expected_fields,
):
    values = _phase3_outputs(**overrides)

    issues = validate_outputs(container(values))

    assert expected_fields <= {issue.field for issue in issues}


@pytest.mark.parametrize("container", (dict, lambda values: SimpleNamespace(**values)))
def test_validate_outputs_ignores_disabled_image_fields_but_keeps_operations(
    container,
):
    values = _phase3_outputs(
        export_image=False,
        image_format="webp",
        image_size="retina",
        image_width=-1,
        image_height=-1,
        image_dpi=0,
        image_background="paper",
        image_line_width=0.1,
        conflict_policy="rename",
        resume_policy="filename",
    )

    issues = validate_outputs(container(values))
    fields = {issue.field for issue in issues}

    assert fields.isdisjoint({
        "image_format", "image_size", "image_width", "image_height",
        "image_pixels", "image_dpi",
        "image_background", "image_line_width",
    })
    assert {"conflict_policy", "resume_policy"} <= fields


def test_validate_outputs_collects_independent_phase3_image_issues():
    issues = validate_outputs(_phase3_outputs(
        image_format="webp",
        image_size="custom",
        image_width=True,
        image_height="1080",
        image_dpi=144.5,
        image_background="paper",
        image_line_width=True,
    ))

    assert {
        "image_format", "image_width", "image_height", "image_dpi",
        "image_background", "image_line_width",
    } <= {issue.field for issue in issues}


def test_validate_outputs_accepts_phase3_defaults_and_size_aliases():
    for image_size in (
        "1080p", "fullhd", "1920x1080",
        "2k", "qhd", "2560x1440",
        "4k", "uhd", "3840x2160",
    ):
        assert validate_outputs(_phase3_outputs(image_size=image_size)) == ()


def test_image_output_validation_does_not_import_renderer_or_matplotlib():
    code = """
import sys
from mf4_analyzer.batch_validation import validate_outputs

issues = validate_outputs({
    'export_data': True,
    'export_image': True,
    'data_format': 'csv',
    'image_format': 'png',
    'image_size': '1920x1080',
    'image_dpi': 144,
    'conflict_policy': 'auto_number',
    'resume_policy': 'none',
})
assert issues == ()
assert 'mf4_analyzer.batch_render' not in sys.modules
assert not any(name == 'matplotlib' or name.startswith('matplotlib.')
               for name in sys.modules)
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "window",
    ("hann", "hanning", "hamming", "blackman", "bartlett", "kaiser", "flattop"),
)
def test_validate_recipe_accepts_windows_supported_by_canonical_factory(window):
    issues = validate_recipe("fft", {"window": window})

    assert not any(issue.field == "window" for issue in issues)


@pytest.mark.parametrize("x_channel", (None, "", "   "))
def test_channel_x_requires_nonempty_channel(x_channel):
    issues = validate_recipe(
        "time",
        {"x_source": "channel", "x_channel": x_channel},
    )

    assert any(
        issue.field == "x_channel" and issue.code == "required"
        for issue in issues
    )
    assert not any(
        issue.field == "x_channel"
        for issue in validate_recipe("time", {"x_source": "time"})
    )


@pytest.mark.parametrize(
    ("params", "field"),
    (
        ({"render_group_by": "file"}, "render_group_by"),
        (
            {"render_group_by": "source", "render_layout": "grid"},
            "render_layout",
        ),
        ({"x_source": "distance"}, "x_source"),
        ({"x_source": "time", "x_origin": "middle"}, "x_origin"),
    ),
)
def test_time_render_recipe_rejects_invalid_active_modes(params, field):
    issues = validate_recipe("time", params)

    assert any(issue.field == field for issue in issues)


@pytest.mark.parametrize(
    "statistics",
    (
        {"enabled": True, "range_mode": "custom", "x_min": 2, "x_max": 1, "metrics": ["max"]},
        {"enabled": True, "range_mode": "full", "metrics": []},
        {"enabled": True, "range_mode": "future", "metrics": ["max"]},
    ),
)
def test_time_chart_statistics_validation_is_preflight_only(statistics):
    issues = validate_recipe("time", {"chart_statistics": statistics})
    assert any(issue.field == "chart_statistics" for issue in issues)


@pytest.mark.parametrize("method", ("fft", "fft_time", "order_time"))
def test_validate_recipe_rejects_unknown_analysis_window(method):
    issues = validate_recipe(method, {"window": "rectangular"})

    assert any(issue.field == "window" for issue in issues)


@pytest.mark.parametrize("value", ("", "power", "peak-to-peak", None))
def test_validate_fft_recipe_rejects_invalid_amplitude_definition(value):
    issues = validate_recipe("fft", {"amplitude_definition": value})

    assert any(issue.field == "amplitude_definition" for issue in issues)


@pytest.mark.parametrize("value", ("native", "peak", "rms", "RMS"))
def test_validate_fft_recipe_accepts_amplitude_definition(value):
    issues = validate_recipe("fft", {"amplitude_definition": value})

    assert not any(issue.field == "amplitude_definition" for issue in issues)


@pytest.mark.parametrize(
    "time_range",
    (
        (2.0, 1.0),
        (1.0, 1.0),
        (float("nan"), 2.0),
        (0.0, float("inf")),
        (1.0,),
        "1,2",
    ),
)
def test_validate_recipe_rejects_invalid_time_range_with_field(time_range):
    issues = validate_recipe("fft", {"time_range": time_range})

    assert any(issue.field == "time_range" for issue in issues)


@pytest.mark.parametrize(
    ("params", "field"),
    (
        ({"fs": 0.0}, "fs"),
        ({"fs": float("nan")}, "fs"),
        ({"nfft_mode": "fixed", "nfft": None}, "nfft"),
        ({"nfft_mode": "fixed", "nfft": 1}, "nfft"),
        ({"x_auto": False, "x_min": 10.0, "x_max": 10.0}, "x_range"),
        ({"y_auto": False, "y_min": 1.0, "y_max": -1.0}, "y_range"),
        ({"z_auto": False, "z_floor": -5.0, "z_ceiling": -5.0}, "z_range"),
    ),
)
def test_validate_recipe_rejects_invalid_scalar_contracts(params, field):
    issues = validate_recipe("fft", params)

    assert any(issue.field == field for issue in issues)


@pytest.mark.parametrize("method", ("fft_time", "order_time"))
def test_slice_validation_is_spectrogram_only_and_skipped_when_disabled(method):
    issues_when_absent = validate_recipe(method, {})
    issues_when_disabled = validate_recipe(
        method,
        {"slice": {"enabled": False, "axis": "bogus", "positions": [1, 2, 3, 4, 5]}},
    )

    assert not any(issue.field == "slice" for issue in issues_when_absent)
    assert not any(issue.field == "slice" for issue in issues_when_disabled)
    # slice is not a recognized field on non-spectrogram methods, so an
    # invalid payload there must not surface as a slice issue.
    assert not any(
        issue.field == "slice"
        for issue in validate_recipe(
            "time", {"slice": {"enabled": True, "axis": "bogus", "positions": []}},
        )
    )


@pytest.mark.parametrize("method", ("fft_time", "order_time"))
def test_slice_validation_rejects_non_mapping_slice(method):
    issues = validate_recipe(method, {"slice": ["enabled", True]})

    assert any(
        issue.field == "slice" and issue.code == "invalid_slice"
        for issue in issues
    )


@pytest.mark.parametrize("method", ("fft_time", "order_time"))
def test_slice_validation_rejects_unsupported_axis(method):
    issues = validate_recipe(
        method,
        {"slice": {"enabled": True, "axis": "frequency", "positions": [5.0]}},
    )

    assert any(
        issue.field == "slice" and issue.code == "invalid_slice_axis"
        for issue in issues
    )


@pytest.mark.parametrize(
    "positions",
    (
        "5,15",
        ["1.5", "2.5"],
        [float("nan")],
        [float("inf")],
        [True],
    ),
)
@pytest.mark.parametrize("method", ("fft_time", "order_time"))
def test_slice_validation_rejects_invalid_positions_shape_or_values(method, positions):
    issues = validate_recipe(
        method,
        {"slice": {"enabled": True, "axis": "time", "positions": positions}},
    )

    assert any(
        issue.field == "slice" and issue.code == "invalid_slice_positions"
        for issue in issues
    )


@pytest.mark.parametrize("method", ("fft_time", "order_time"))
def test_slice_validation_accepts_finite_int_and_float_positions(method):
    issues = validate_recipe(
        method,
        {"slice": {"enabled": True, "axis": "time", "positions": [1.5, 2]}},
    )

    assert not any(issue.field == "slice" for issue in issues)


@pytest.mark.parametrize("method", ("fft_time", "order_time"))
def test_slice_validation_rejects_negative_y_axis_positions(method):
    issues = validate_recipe(
        method,
        {"slice": {"enabled": True, "axis": "y", "positions": [-5.0, 10.0]}},
    )

    assert any(
        issue.field == "slice" and issue.code == "invalid_slice_positions"
        for issue in issues
    )
    # A negative position on the time axis is not out-of-range at preflight
    # (no data is loaded yet); only the axis == "y" case is restricted.
    assert not any(
        issue.field == "slice"
        for issue in validate_recipe(
            method,
            {"slice": {"enabled": True, "axis": "time", "positions": [-5.0, 10.0]}},
        )
    )


@pytest.mark.parametrize("method", ("fft_time", "order_time"))
def test_slice_validation_rejects_more_than_four_positions(method):
    issues = validate_recipe(
        method,
        {"slice": {"enabled": True, "axis": "time", "positions": [1, 2, 3, 4, 5]}},
    )

    assert any(
        issue.field == "slice" and issue.code == "too_many_slice_positions"
        for issue in issues
    )
    assert not any(
        issue.field == "slice"
        for issue in validate_recipe(
            method,
            {"slice": {"enabled": True, "axis": "time", "positions": [1, 2, 3, 4]}},
        )
    )


@pytest.mark.parametrize("method", ("fft_time", "order_time"))
def test_slice_validation_requires_at_least_one_position_when_enabled(method):
    issues = validate_recipe(
        method,
        {"slice": {"enabled": True, "axis": "time", "positions": []}},
    )

    assert any(
        issue.field == "slice" and issue.code == "slice_positions_required"
        for issue in issues
    )


def test_slice_validation_does_not_check_out_of_range_positions():
    # Preflight has no loaded data to check bounds against; out-of-range
    # positions are clamped at render time (design D12), not rejected here.
    issues = validate_recipe(
        "fft_time",
        {"slice": {"enabled": True, "axis": "time", "positions": [1_000_000.0]}},
    )

    assert not any(issue.field == "slice" for issue in issues)


def test_validate_task_rejects_invalid_effective_fs_and_nyquist():
    invalid_fs = validate_task("fft", {}, fs=float("inf"), sample_count=32)
    above_nyquist = validate_task(
        "fft",
        {"x_auto": False, "x_min": 0.0, "x_max": 600.0},
        fs=1000.0,
        sample_count=32,
    )

    assert any(issue.field == "fs" for issue in invalid_fs)
    assert any(issue.field == "x_range" and issue.code == "above_nyquist"
               for issue in above_nyquist)


def test_fft_time_nyquist_uses_frequency_y_axis_not_time_x_axis():
    time_axis_is_not_frequency = validate_task(
        "fft_time",
        {"x_auto": False, "x_min": 0.0, "x_max": 600.0},
        fs=1000.0,
        sample_count=32,
    )
    frequency_above_nyquist = validate_task(
        "fft_time",
        {"y_auto": False, "y_min": 0.0, "y_max": 600.0},
        fs=1000.0,
        sample_count=32,
    )

    assert not any(issue.code == "above_nyquist" for issue in time_axis_is_not_frequency)
    assert any(issue.field == "y_range" and issue.code == "above_nyquist"
               for issue in frequency_above_nyquist)


def test_validate_task_rejects_time_range_with_fewer_than_two_samples():
    time = np.array([0.0, 0.1, 0.2])

    issues = validate_task(
        "time",
        {"time_range": (0.05, 0.15)},
        fs=10.0,
        sample_count=len(time),
        time=time,
    )

    assert any(issue.field == "time_range" and issue.code == "too_few_samples"
               for issue in issues)


def test_validate_order_recipe_no_longer_checks_retired_manual_rpm_fields():
    """Manual RPM is removed (design 2026-08-03 D-C1): ``rpm_mode``/
    ``manual_rpm`` are retired batch fields.  ``normalize_batch_params``
    drops both before a real run ever sees them, so ``validate_recipe`` no
    longer recognizes either key -- not even to flag an invalid manual
    value.  A missing RPM source is instead caught by the pre-existing
    "rpm channel is required" runtime check in ``_rpm_values``."""
    issues = validate_recipe(
        "order_time",
        {"rpm_mode": "manual", "manual_rpm": 0.0},
        rpm_channel="",
        rpm_signal=None,
    )

    assert not any(
        issue.field in {"manual_rpm", "rpm_channel"} for issue in issues
    )


def test_validate_order_task_order_limit_ignores_retired_manual_rpm():
    """``max_order`` vs. order-Nyquist is still enforced via loaded RPM
    values (see test_validate_order_task_uses_loaded_rpm_for_order_nyquist);
    a stale ``manual_rpm`` in params must no longer feed that check."""
    order_above_nyquist = validate_task(
        "order_time",
        {"rpm_mode": "manual", "manual_rpm": 3000.0, "max_order": 20.0},
        fs=1000.0,
        sample_count=1024,
    )

    assert not any(
        issue.field == "max_order" and issue.code == "above_order_nyquist"
        for issue in order_above_nyquist
    )


def test_validate_order_task_uses_loaded_rpm_for_order_nyquist():
    issues = validate_task(
        "order_time",
        {"max_order": 10.0},
        fs=1000.0,
        sample_count=4,
        rpm_values=np.array([3000.0, 4000.0, 5000.0, 6000.0]),
    )

    assert any(issue.field == "max_order" and issue.code == "above_order_nyquist"
               for issue in issues)


def test_guard_filter_params_preserves_nyquist_clamp_warning_and_effective_spec():
    effective, warnings = guard_filter_params(
        {
            "filter": {
                "enabled": True,
                "spec": {"kind": "low", "order": 4, "cutoff": 900.0},
            }
        },
        fs=1000.0,
    )

    assert warnings and "钳制" in warnings[0]
    assert 0.0 < effective["filter"]["spec"]["cutoff"] < 500.0


def test_validate_frf_recipe_accepts_complete_owned_parameters():
    issues = validate_recipe("frf", {
        "estimator": "h1",
        "window": "hanning",
        "periodic_window": True,
        "t_win_s": 2.0,
        "overlap": 0.5,
        "nfft_mode": "fixed",
        "nfft": 2048,
        "detrend": "constant",
        "magnitude_scale": "db",
        "frequency_scale": "log",
        "phase_mode": "unwrapped",
        "coherence_threshold": 0.8,
        "fade_low_coherence": True,
        "render_group_by": "channel",
    })

    assert issues == ()


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        ("estimator", "h3", "unsupported_estimator"),
        ("t_win_s", 0.0, "invalid_segment_duration"),
        ("overlap", 1.0, "invalid_overlap"),
        ("coherence_threshold", 1.1, "invalid_coherence_threshold"),
        ("magnitude_scale", "power", "unsupported_magnitude_scale"),
        ("frequency_scale", "octave", "unsupported_frequency_scale"),
        ("phase_mode", "delay", "unsupported_phase_mode"),
        ("detrend", True, "unsupported_detrend"),
        ("render_group_by", "pair", "unsupported_grouping"),
    ),
)
def test_validate_frf_recipe_rejects_invalid_owned_parameter(field, value, code):
    issues = validate_recipe("frf", {field: value})
    assert any(issue.field == field and issue.code == code for issue in issues)


@pytest.mark.parametrize("mode", ("auto", "自动"))
def test_validate_frf_rejects_explicit_nfft_in_auto_mode(mode):
    issues = validate_recipe("frf", {"nfft_mode": mode, "nfft": 1024})
    assert any(issue.code == "nfft_not_allowed_in_auto" for issue in issues)


@pytest.mark.parametrize("mode", ("manual", "fixed", "固定", "手动"))
def test_validate_frf_manual_nfft_requires_positive_integer(mode):
    missing = validate_recipe("frf", {"nfft_mode": mode})
    invalid = validate_recipe("frf", {"nfft_mode": mode, "nfft": 1.5})

    assert any(issue.code == "manual_nfft_required" for issue in missing)
    assert any(issue.code == "invalid_nfft" for issue in invalid)


def test_validate_frf_rejects_unknown_nfft_mode():
    issues = validate_recipe("frf", {"nfft_mode": "largest"})
    assert any(issue.code == "unsupported_nfft_mode" for issue in issues)


def test_validate_frf_uses_core_auto_nfft_default_when_mode_is_absent():
    issues = validate_recipe("frf", {})
    assert not any(issue.field in {"nfft_mode", "nfft"} for issue in issues)
