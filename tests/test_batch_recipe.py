from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from mf4_analyzer.batch_recipe import (
    COMMON_PARAM_FIELDS,
    KNOWN_PARAM_FIELDS,
    METHOD_PARAM_FIELDS,
    compatible_param_fields,
    normalize_analysis_preset,
    normalize_batch_params,
    recipe_fingerprint,
)


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
                "rpm_mode": "manual",
                "manual_rpm": np.float64(1500),
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


def test_normalize_batch_params_does_not_fill_missing_ui_defaults():
    assert normalize_batch_params({"window": "flattop"}, "fft") == {
        "window": "flattop"
    }
    assert normalize_batch_params({}, "fft_time") == {}


def test_compatible_field_schema_is_method_aware_and_complete():
    assert COMMON_PARAM_FIELDS <= compatible_param_fields("time")
    assert METHOD_PARAM_FIELDS["fft"] <= compatible_param_fields("fft")
    assert "manual_rpm" in compatible_param_fields("order_time")
    assert "manual_rpm" not in compatible_param_fields("fft")
    assert KNOWN_PARAM_FIELDS == COMMON_PARAM_FIELDS | frozenset().union(
        *METHOD_PARAM_FIELDS.values()
    )


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
        "conflict_policy": "auto_number",
        "write_manifest": True,
        "resume_policy": "none",
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
        "conflict_policy": "auto_number",
        "write_manifest": True,
        "resume_policy": "none",
    }
    base = recipe_fingerprint({"nfft": 64}, "fft", outputs=defaults)

    assert base != recipe_fingerprint(
        {"nfft": 64}, "fft", outputs={**defaults, "image_dpi": 192},
    )
    assert base != recipe_fingerprint(
        {"nfft": 64}, "fft", outputs={**defaults, "image_format": "svg"},
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
        "conflict_policy": "auto_number",
        "write_manifest": True,
        "resume_policy": "none",
    }

    assert recipe_fingerprint(
        {"nfft": 64}, "fft", outputs=legacy,
    ) == recipe_fingerprint(
        {"nfft": 64}, "fft", outputs=explicit,
    )


def test_normalizers_reject_ambiguous_inputs():
    with pytest.raises(ValueError, match="unsupported batch method"):
        normalize_batch_params({}, "order_track")
    with pytest.raises(TypeError, match="mapping"):
        normalize_batch_params([("nfft", 1024)], "fft")
    with pytest.raises(ValueError, match="method"):
        normalize_analysis_preset({"params": {}})
