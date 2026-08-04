from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

import mf4_analyzer.batch_recipe as batch_recipe
from mf4_analyzer.batch_recipe import (
    COMMON_PARAM_FIELDS,
    KNOWN_PARAM_FIELDS,
    METHOD_PARAM_FIELDS,
    compatible_param_fields,
    normalize_analysis_preset,
    normalize_batch_params,
    recipe_fingerprint,
)
from mf4_analyzer.batch_validation import validate_recipe


def test_time_render_defaults_are_removed_from_normalized_params():
    defaults = {
        "render_group_by": "none",
        "render_layout": "overlay",
        "x_source": "time",
        "x_channel": "",
        "x_origin": "zero",
    }

    assert batch_recipe.TIME_RENDER_DEFAULTS == defaults
    assert normalize_batch_params(defaults, "time") == {}
    assert recipe_fingerprint(defaults, "time") == recipe_fingerprint(
        {}, "time",
    )


def test_chart_statistics_are_time_only_canonical_and_fingerprinted():
    raw = {
        "chart_statistics": {
            "enabled": True, "range_mode": "custom", "x_min": np.int64(-2),
            "x_max": np.float32(3), "metrics": ["mean", "max", "mean"],
        }
    }
    normalized = normalize_batch_params(raw, "time")
    assert normalized["chart_statistics"] == {
        "enabled": True, "range_mode": "custom", "x_min": -2.0,
        "x_max": 3.0, "metrics": ["max", "mean"],
    }
    assert recipe_fingerprint(raw, "time") != recipe_fingerprint({}, "time")
    assert normalize_batch_params(raw, "fft") == {}


@pytest.mark.parametrize(
    ("params", "baseline"),
    (
        ({"render_group_by": "source"}, {}),
        (
            {"render_group_by": "source", "render_layout": "subplot"},
            {"render_group_by": "source"},
        ),
        ({"x_source": "channel", "x_channel": "rpm"}, {}),
        ({"x_origin": "absolute"}, {}),
    ),
)
def test_time_render_nondefaults_change_fingerprint(params, baseline):
    assert set(params) <= METHOD_PARAM_FIELDS["time"]
    assert recipe_fingerprint(params, "time") != recipe_fingerprint(
        baseline, "time",
    )


@pytest.mark.parametrize("method", ("fft", "fft_time", "order_time"))
def test_time_render_fields_are_removed_from_every_non_time_method(method):
    render_fields = {
        "render_group_by": "channel",
        "render_layout": "subplot",
        "x_source": "channel",
        "x_channel": "rpm",
        "x_origin": "absolute",
    }

    assert normalize_batch_params(render_fields, method) == {}
    assert recipe_fingerprint(render_fields, method) == recipe_fingerprint(
        {}, method,
    )


def test_time_render_inactive_fields_are_removed_before_fingerprinting():
    assert normalize_batch_params(
        {"render_group_by": "none", "render_layout": "subplot"},
        "time",
    ) == {}
    assert normalize_batch_params(
        {"x_source": "time", "x_channel": "rpm"},
        "time",
    ) == {}
    assert normalize_batch_params(
        {
            "x_source": "channel",
            "x_channel": "rpm",
            "x_origin": "absolute",
        },
        "time",
    ) == {"x_source": "channel", "x_channel": "rpm"}


@pytest.mark.parametrize(
    ("method", "params"),
    (
        (
            "time",
            {
                "fs": np.float64(1024),
                "time_range": (1, np.float32(2.5)),
                "filter": {"enabled": np.bool_(True), "spec": {"cutoff": np.float64(50)}},
                "x_auto": False,
                "x_min": np.float64(1),
                "x_max": np.float64(2.5),
            },
        ),
        (
            "fft",
            {
                "window": "flattop",
                "nfft": None,
                "nfft_mode": "auto",
                "t_win_s": np.float64(0.5),
                "overlap": np.float32(0.25),
                "avg_mode": "Welch",
                "avg_overlap": np.int64(75),
                "amplitude_definition": "rms",
                "amp_y": "Linear",
                "amplitude_mode": "amplitude",
                "db_reference": np.float64(2e-5),
                "db_reference_mode": "auto",
            },
        ),
        (
            "fft_time",
            {
                "window": "hanning",
                "nfft": np.int64(2048),
                "nfft_mode": "fixed",
                "t_win_s": np.float64(0.25),
                "overlap": np.float64(0.75),
                "remove_mean": np.bool_(True),
                "weighting": "A",
            },
        ),
        (
            "order_time",
            {
                "window": "hanning",
                "nfft": None,
                "nfft_mode": "auto",
                "max_order": np.float64(40),
                "order_res": np.float32(0.1),
                "time_res": np.float64(0.2),
                "samples_per_rev": np.int64(256),
                "rpm_factor": np.float64(60),
                "rpm_signal": (7, "RPM"),
            },
        ),
    ),
)
def test_normalize_batch_params_preserves_complete_method_recipe(method, params):
    normalized = normalize_batch_params(params, method)

    assert set(normalized) == set(params)
    assert normalized == normalize_batch_params(normalized, method)
    assert not any(isinstance(value, np.generic) for value in normalized.values())
    if "time_range" in normalized:
        assert normalized["time_range"] == [1.0, 2.5]
    if "rpm_signal" in normalized:
        assert normalized["rpm_signal"] == [7, "RPM"]


def test_normalize_batch_params_preserves_unknown_fields_recursively():
    normalized = normalize_batch_params(
        {
            "window": "hanning",
            "future_option": {
                "curve": (np.int64(1), [np.float32(2.5)]),
                "enabled": np.bool_(True),
            },
        },
        "fft",
    )

    assert normalized["future_option"] == {
        "curve": [1, [2.5]],
        "enabled": True,
    }


def test_normalize_batch_params_drops_only_known_incompatible_fields():
    normalized = normalize_batch_params(
        {
            "window": "hanning",
            "manual_rpm": 1500.0,
            "samples_per_rev": 256,
            "future_order_like_option": "keep because it is unknown",
        },
        "fft",
    )

    assert normalized == {
        "window": "hanning",
        "future_order_like_option": "keep because it is unknown",
    }


def test_amplitude_definition_is_fft_only_and_normalized_to_frozen_value():
    assert normalize_batch_params(
        {"amplitude_definition": " RMS "}, "fft",
    )["amplitude_definition"] == "rms"
    assert "amplitude_definition" not in normalize_batch_params(
        {"amplitude_definition": "peak"}, "fft_time",
    )


def test_amplitude_definition_changes_recipe_compute_signature():
    peak = recipe_fingerprint(
        {"amplitude_definition": "peak"}, "fft",
        source_identity="source", group_identity="group", channel_identity="sig",
    )
    rms = recipe_fingerprint(
        {"amplitude_definition": "rms"}, "fft",
        source_identity="source", group_identity="group", channel_identity="sig",
    )

    assert peak != rms


def test_normalize_batch_params_migrates_legacy_db_reference_to_manual():
    legacy = normalize_batch_params({"db_reference": np.float64(2e-5)}, "fft")
    current = normalize_batch_params(
        {"db_reference": 1.0, "db_reference_mode": "auto"},
        "fft",
    )

    assert legacy == {"db_reference": 2e-5, "db_reference_mode": "manual"}
    assert current == {"db_reference": 1.0, "db_reference_mode": "auto"}


def test_legacy_manual_rpm_is_dropped_and_warns_with_matching_fingerprint():
    """Design 2026-08-03 D-C1: batch order analysis no longer supports manual
    RPM. A legacy recipe that requested it must (1) lose both fields on
    normalization, (2) surface a migration warning, and (3) fingerprint
    identically to an equivalent recipe that never had them -- so a resumed
    run recognizes the outputs as the same task, not a stale one."""
    legacy = {
        "window": "hanning",
        "max_order": 40.0,
        "rpm_mode": "manual",
        "manual_rpm": 1000.0,
    }
    baseline = {"window": "hanning", "max_order": 40.0}

    normalized = normalize_batch_params(legacy, "order_time")

    assert "rpm_mode" not in normalized
    assert "manual_rpm" not in normalized
    assert normalized == baseline
    assert batch_recipe.legacy_manual_rpm_warning(legacy, "order_time") == (
        batch_recipe.LEGACY_MANUAL_RPM_WARNING
    )
    assert recipe_fingerprint(legacy, "order_time") == recipe_fingerprint(
        baseline, "order_time",
    )


@pytest.mark.parametrize("rpm_mode", ("channel", "通道", "", None))
def test_legacy_channel_rpm_mode_is_dropped_silently(rpm_mode):
    """Discarding rpm_mode="channel" (or an absent rpm_mode) changes nothing
    observable -- channel was always the only mode that mattered at
    runtime -- so it must NOT produce a migration warning."""
    legacy = {"window": "hanning"}
    if rpm_mode is not None:
        legacy = {**legacy, "rpm_mode": rpm_mode}
    baseline = {"window": "hanning"}

    normalized = normalize_batch_params(legacy, "order_time")

    assert "rpm_mode" not in normalized
    assert normalized == baseline
    assert batch_recipe.legacy_manual_rpm_warning(legacy, "order_time") is None
    assert recipe_fingerprint(legacy, "order_time") == recipe_fingerprint(
        baseline, "order_time",
    )


@pytest.mark.parametrize("method", ("time", "fft", "fft_time"))
def test_retired_rpm_fields_are_dropped_for_every_method(method):
    """rpm_mode/manual_rpm belonged only to order_time's field set, but they
    stay in KNOWN_PARAM_FIELDS globally (design D-C1), so any method drops
    them via the ordinary known-but-incompatible-field rule."""
    normalized = normalize_batch_params(
        {"rpm_mode": "manual", "manual_rpm": 1000.0}, method,
    )

    assert normalized == {}


def test_legacy_manual_rpm_warning_is_order_time_only():
    # A stray rpm_mode="manual" left over on a non-order_time method (e.g.
    # after a method switch) must not be reported: the warning is specific
    # to the removed batch order-analysis feature.
    assert batch_recipe.legacy_manual_rpm_warning(
        {"rpm_mode": "manual", "manual_rpm": 1000.0}, "fft",
    ) is None
    assert batch_recipe.legacy_manual_rpm_warning(None, "order_time") is None


@pytest.mark.parametrize("method", ("fft_time", "order_time"))
def test_slice_field_is_compatible_only_with_spectrogram_methods(method):
    assert "slice" in METHOD_PARAM_FIELDS[method]


@pytest.mark.parametrize("method", ("time", "fft"))
def test_slice_field_is_removed_from_non_spectrogram_methods(method):
    raw = {
        "slice": {"enabled": True, "axis": "time", "positions": [5.0, 15.0]},
    }

    assert "slice" not in METHOD_PARAM_FIELDS[method]
    assert normalize_batch_params(raw, method) == {}
    assert recipe_fingerprint(raw, method) == recipe_fingerprint({}, method)


@pytest.mark.parametrize("method", ("fft_time", "order_time"))
def test_disabled_slice_is_dropped_and_fingerprint_is_unchanged(method):
    raw = {
        "slice": {"enabled": False, "axis": "time", "positions": [5.0, 15.0]},
    }

    normalized = normalize_batch_params(raw, method)

    assert "slice" not in normalized
    assert recipe_fingerprint(raw, method) == recipe_fingerprint({}, method)


@pytest.mark.parametrize("method", ("fft_time", "order_time"))
def test_enabled_slice_survives_normalization_and_changes_fingerprint(method):
    raw = {
        "slice": {"enabled": True, "axis": "y", "positions": [620.0, 1240.0]},
    }

    normalized = normalize_batch_params(raw, method)

    assert normalized["slice"] == {
        "enabled": True,
        "axis": "y",
        "positions": [620.0, 1240.0],
    }
    assert recipe_fingerprint(raw, method) != recipe_fingerprint({}, method)


@pytest.mark.parametrize("method", ("fft_time", "order_time"))
def test_slice_positions_are_sorted_and_deduplicated_for_fingerprint_stability(
    method,
):
    unsorted = {
        "slice": {"enabled": True, "axis": "time", "positions": [15, 5, 15]},
    }
    sorted_unique = {
        "slice": {"enabled": True, "axis": "time", "positions": [5, 15]},
    }

    normalized_unsorted = normalize_batch_params(unsorted, method)
    normalized_sorted = normalize_batch_params(sorted_unique, method)

    assert normalized_unsorted["slice"]["positions"] == [5.0, 15.0]
    assert normalized_unsorted == normalized_sorted
    assert recipe_fingerprint(unsorted, method) == recipe_fingerprint(
        sorted_unique, method,
    )


def test_slice_axis_is_lowercased_and_positions_are_floats():
    normalized = normalize_batch_params(
        {
            "slice": {
                "enabled": True,
                "axis": " Y ",
                "positions": [np.int64(5), np.float32(15.5)],
            },
        },
        "fft_time",
    )

    assert normalized["slice"] == {
        "enabled": True,
        "axis": "y",
        "positions": [5.0, 15.5],
    }


@pytest.mark.parametrize("method", ("fft_time", "order_time"))
def test_validated_slice_positions_survive_normalization(method):
    raw = {
        "slice": {"enabled": True, "axis": "time", "positions": [1.5, 2]},
    }

    assert not validate_recipe(method, raw)
    assert normalize_batch_params(raw, method)["slice"]["positions"]

    string_positions = {
        "slice": {"enabled": True, "axis": "time", "positions": ["1.5", "2.5"]},
    }
    assert any(
        issue.code == "invalid_slice_positions"
        for issue in validate_recipe(method, string_positions)
    )
    assert not normalize_batch_params(string_positions, method)["slice"]["positions"]


def test_normalize_batch_params_does_not_fill_missing_ui_defaults():
    assert normalize_batch_params({"window": "flattop"}, "fft") == {
        "window": "flattop"
    }
    assert normalize_batch_params({}, "fft_time") == {}


@pytest.mark.parametrize("method", sorted(batch_recipe.SUPPORTED_RECIPE_METHODS))
def test_render_style_fields_are_common_typed_and_fingerprinted(method):
    """Tick density and text scale belong to every method and to the fingerprint.

    They change the exported image bytes, so two recipes differing only in
    them are not interchangeable artifacts.
    """
    params = {"tick_density_x": 24, "tick_density_y": 16, "font_scale": 1.5}
    for field in params:
        assert field in compatible_param_fields(method)

    normalized = normalize_batch_params(
        {"tick_density_x": 24.0, "tick_density_y": 16, "font_scale": 1}, method,
    )
    assert normalized["tick_density_x"] == 24.0
    assert isinstance(normalized["tick_density_y"], int)
    assert isinstance(normalized["font_scale"], float)

    assert recipe_fingerprint(
        normalize_batch_params(params, method), method
    ) != recipe_fingerprint(normalize_batch_params({}, method), method)


def test_compatible_field_schema_is_method_aware_and_complete():
    assert COMMON_PARAM_FIELDS <= compatible_param_fields("time")
    assert METHOD_PARAM_FIELDS["fft"] <= compatible_param_fields("fft")
    # Manual RPM is retired (design 2026-08-03 D-C1): no method owns these
    # fields any more, but they stay in KNOWN_PARAM_FIELDS on purpose so an
    # old recipe's rpm_mode/manual_rpm is discarded rather than kept around
    # as unrecognized future data.
    assert "manual_rpm" not in compatible_param_fields("order_time")
    assert "rpm_mode" not in compatible_param_fields("order_time")
    assert "manual_rpm" not in compatible_param_fields("fft")
    assert KNOWN_PARAM_FIELDS == (
        COMMON_PARAM_FIELDS
        | frozenset().union(*METHOD_PARAM_FIELDS.values())
        | batch_recipe._RETIRED_PARAM_FIELDS
    )
    assert batch_recipe._RETIRED_PARAM_FIELDS == {"rpm_mode", "manual_rpm"}


def test_normalize_analysis_preset_is_duck_typed_and_json_safe():
    preset = SimpleNamespace(
        name="current FFT",
        method="fft",
        source="current_single",
        params={"nfft": np.int64(2048), "nfft_mode": "fixed"},
        outputs=SimpleNamespace(
            export_data=np.bool_(True),
            export_image=np.bool_(False),
            data_format="csv",
        ),
        signal=(3, "acc"),
        rpm_signal=None,
        signal_pattern="",
        rpm_channel="",
        target_signals=("acc",),
        target_pairs=((3, "acc"),),
        source_ids=("source-a",),
        source_paths=("/tmp/a.hdf",),
        target_policy="available_per_source",
        file_ids=(3,),
        file_paths=(),
    )

    normalized = normalize_analysis_preset(preset)

    assert normalized["method"] == "fft"
    assert normalized["params"] == {"nfft": 2048, "nfft_mode": "fixed"}
    assert normalized["outputs"] == {
        "export_data": True,
        "export_image": False,
        "data_format": "csv",
        "image_format": "png",
        "image_size": "1920x1080",
        "image_width": 1920,
        "image_height": 1080,
        "image_dpi": 144,
        "image_background": "white",
        "image_line_width": 1.5,
        "conflict_policy": "auto_number",
        "write_manifest": True,
        "resume_policy": "none",
        "requested_image_format": None,
        "migration_warnings": [],
    }
    assert normalized["signal"] == [3, "acc"]
    assert normalized["target_signals"] == ["acc"]
    assert normalized["target_pairs"] == [[3, "acc"]]
    assert normalized["source_ids"] == ["source-a"]
    assert normalized["source_paths"] == ["/tmp/a.hdf"]
    assert normalized["target_policy"] == "available_per_source"
    assert normalized["file_ids"] == [3]


def test_normalize_analysis_preset_mapping_preserves_unknown_top_level_fields():
    normalized = normalize_analysis_preset(
        {
            "method": "time",
            "params": {"future_param": (1, 2)},
            "future_scope": {"ids": (np.int64(4),)},
        }
    )

    assert normalized == {
        "method": "time",
        "params": {"future_param": [1, 2]},
        "future_scope": {"ids": [4]},
    }


def test_recipe_fingerprint_is_order_independent_and_sequence_stable():
    first = recipe_fingerprint(
        {"window": "hanning", "time_range": (1, np.float64(2))},
        "fft",
        source_identity="/a/run.mf4",
        group_identity="group-1",
        channel_identity="acc",
    )
    reordered = recipe_fingerprint(
        {"time_range": [1.0, 2.0], "window": "hanning"},
        "fft",
        source_identity="/a/run.mf4",
        group_identity="group-1",
        channel_identity="acc",
    )

    assert first == reordered
    assert len(first) == 64


def test_recipe_fingerprint_changes_for_semantic_recipe_or_identity_change():
    base = recipe_fingerprint(
        {"nfft": 1024, "nfft_mode": "fixed"},
        "fft",
        source_identity="source-a",
        channel_identity="acc",
    )

    assert base != recipe_fingerprint(
        {"nfft": 2048, "nfft_mode": "fixed"},
        "fft",
        source_identity="source-a",
        channel_identity="acc",
    )
    assert base != recipe_fingerprint(
        {"nfft": 1024, "nfft_mode": "fixed"},
        "fft",
        source_identity="source-b",
        channel_identity="acc",
    )


def test_phase3_output_normalization_isomorphic_for_object_and_mapping():
    legacy_object = SimpleNamespace(
        export_data=True,
        export_image=False,
        data_format="csv",
    )
    legacy_mapping = {
        "export_data": True,
        "export_image": False,
        "data_format": "csv",
    }

    object_recipe = normalize_analysis_preset({
        "method": "fft",
        "params": {"nfft": 64},
        "outputs": legacy_object,
    })
    mapping_recipe = normalize_analysis_preset({
        "method": "fft",
        "params": {"nfft": 64},
        "outputs": legacy_mapping,
    })

    assert object_recipe == mapping_recipe
    assert object_recipe["outputs"]["image_format"] == "png"
    assert object_recipe["outputs"]["image_width"] == 1920
    assert object_recipe["outputs"]["image_background"] == "white"
    assert object_recipe["outputs"]["image_line_width"] == 1.5
    assert object_recipe["outputs"]["write_manifest"] is True


def test_run_recipe_fingerprint_includes_artifact_output_facts_not_operations():
    defaults = {
        "export_data": True,
        "export_image": True,
        "data_format": "csv",
        "image_format": "png",
        "image_size": "1920x1080",
        "image_width": 1920,
        "image_height": 1080,
        "image_dpi": 144,
        "image_background": "white",
        "image_line_width": 1.5,
        "conflict_policy": "auto_number",
        "write_manifest": True,
        "resume_policy": "none",
    }
    base = recipe_fingerprint({"nfft": 64}, "fft", outputs=defaults)

    assert base != recipe_fingerprint(
        {"nfft": 64}, "fft", outputs={**defaults, "image_dpi": 192},
    )
    with pytest.raises(ValueError, match="image_format must be png"):
        recipe_fingerprint(
            {"nfft": 64}, "fft",
            outputs={**defaults, "image_format": "svg"},
        )
    assert base != recipe_fingerprint(
        {"nfft": 64}, "fft", outputs={**defaults, "image_background": "dark"},
    )
    assert base != recipe_fingerprint(
        {"nfft": 64}, "fft", outputs={**defaults, "image_line_width": 2.0},
    )
    assert base == recipe_fingerprint(
        {"nfft": 64},
        "fft",
        outputs={
            **defaults,
            "conflict_policy": "overwrite",
            "resume_policy": "manifest",
        },
    )


def test_legacy_output_fingerprint_equals_explicit_phase3_defaults():
    legacy = {
        "export_data": True,
        "export_image": True,
        "data_format": "csv",
    }
    explicit = {
        **legacy,
        "image_format": "png",
        "image_size": "1920x1080",
        "image_width": 1920,
        "image_height": 1080,
        "image_dpi": 144,
        "image_background": "white",
        "image_line_width": 1.5,
        "conflict_policy": "auto_number",
        "write_manifest": True,
        "resume_policy": "none",
    }

    assert recipe_fingerprint(
        {"nfft": 64}, "fft", outputs=legacy,
    ) == recipe_fingerprint(
        {"nfft": 64}, "fft", outputs=explicit,
    )


def test_migration_provenance_does_not_change_png_artifact_fingerprint():
    native_png = {
        "export_data": True,
        "export_image": True,
        "data_format": "csv",
        "image_format": "png",
    }
    migrated_pdf = {
        **native_png,
        "requested_image_format": "pdf",
        "migration_warnings": [
            "旧预设图像格式 PDF 已迁移为 PNG；本次仅输出 PNG。"
        ],
    }

    assert recipe_fingerprint(
        {"nfft": 64}, "fft", outputs=native_png,
    ) == recipe_fingerprint(
        {"nfft": 64}, "fft", outputs=migrated_pdf,
    )


def test_normalizers_reject_ambiguous_inputs():
    with pytest.raises(ValueError, match="unsupported batch method"):
        normalize_batch_params({}, "order_track")
    with pytest.raises(TypeError, match="mapping"):
        normalize_batch_params([("nfft", 1024)], "fft")
    with pytest.raises(ValueError, match="method"):
        normalize_analysis_preset({"params": {}})
