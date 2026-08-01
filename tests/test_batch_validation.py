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
        conflict_policy="rename",
        resume_policy="filename",
    )

    issues = validate_outputs(container(values))
    fields = {issue.field for issue in issues}

    assert fields.isdisjoint({
        "image_format", "image_size", "image_width", "image_height",
        "image_pixels", "image_dpi",
    })
    assert {"conflict_policy", "resume_policy"} <= fields


def test_validate_outputs_collects_independent_phase3_image_issues():
    issues = validate_outputs(_phase3_outputs(
        image_format="webp",
        image_size="custom",
        image_width=True,
        image_height="1080",
        image_dpi=144.5,
    ))

    assert {
        "image_format", "image_width", "image_height", "image_dpi",
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


def test_validate_order_recipe_checks_explicit_rpm_mode_and_order_limit():
    manual_missing = validate_recipe(
        "order_time",
        {"rpm_mode": "manual", "manual_rpm": 0.0},
    )
    channel_missing = validate_recipe(
        "order_time",
        {"rpm_mode": "channel"},
        rpm_channel="",
        rpm_signal=None,
    )
    order_above_nyquist = validate_task(
        "order_time",
        {"rpm_mode": "manual", "manual_rpm": 3000.0, "max_order": 20.0},
        fs=1000.0,
        sample_count=1024,
    )

    assert any(issue.field == "manual_rpm" for issue in manual_missing)
    assert any(issue.field == "rpm_channel" for issue in channel_missing)
    assert any(issue.field == "max_order" and issue.code == "above_order_nyquist"
               for issue in order_above_nyquist)


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
