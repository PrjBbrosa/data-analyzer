from __future__ import annotations
import json
import pytest

from mf4_analyzer.batch import AnalysisPreset, BatchOutput
from mf4_analyzer.batch_preset_io import (
    save_preset_to_json, load_preset_from_json, UnsupportedPresetVersion,
)
from mf4_analyzer.batch_types import FrfPairRule


def _basic_preset():
    return AnalysisPreset.free_config(
        name="vib", method="fft",
        target_signals=("vibration_x", "vibration_y"),
        rpm_channel="",
        params={"window": "hanning", "nfft": 1024},
        outputs=BatchOutput(export_data=True, export_image=True, data_format="csv"),
    )


def test_round_trip_preserves_recipe(tmp_path):
    p1 = _basic_preset()
    path = tmp_path / "p.json"
    save_preset_to_json(p1, path)
    p2 = load_preset_from_json(path)
    assert p2.name == p1.name
    assert p2.method == p1.method
    assert p2.target_signals == p1.target_signals
    assert p2.params == p1.params
    assert p2.outputs.export_data is p1.outputs.export_data
    assert p2.outputs.data_format == p1.outputs.data_format


def test_phase3_batch_output_defaults_are_backward_compatible_and_safe():
    outputs = BatchOutput()

    assert outputs.image_format == "png"
    assert outputs.image_size == "1920x1080"
    assert outputs.image_width == 1920
    assert outputs.image_height == 1080
    assert outputs.image_dpi == 144
    assert outputs.image_background == "white"
    assert outputs.image_line_width == pytest.approx(1.5)
    assert outputs.conflict_policy == "auto_number"
    assert outputs.write_manifest is True
    assert outputs.resume_policy == "none"


def test_phase3_output_settings_round_trip_through_preset_json(tmp_path):
    preset = AnalysisPreset.free_config(
        name="phase3 outputs",
        method="fft",
        target_signals=("sig",),
        params={"window": "hanning", "nfft": 1024},
        outputs=BatchOutput(
            export_data=False,
            export_image=True,
            data_format="xlsx",
            image_format="png",
            image_size="custom",
            image_width=2304,
            image_height=1296,
            image_dpi=192,
            image_background="transparent",
            image_line_width=1.5,
            conflict_policy="overwrite",
            write_manifest=False,
            resume_policy="manifest",
        ),
    )
    path = tmp_path / "phase3.json"

    save_preset_to_json(preset, path)
    loaded = load_preset_from_json(path)

    assert loaded.outputs == preset.outputs


@pytest.mark.parametrize("legacy_format", ("pdf", "svg"))
def test_legacy_vector_preset_migrates_to_png_with_transient_audit(
    tmp_path, legacy_format,
):
    path = tmp_path / f"legacy-{legacy_format}.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "name": "legacy vector",
        "method": "fft",
        "target_signals": ["sig"],
        "params": {"window": "hanning", "nfft": 1024},
        "outputs": {
            "export_data": True,
            "export_image": True,
            "data_format": "csv",
            "image_format": legacy_format,
            "image_line_width": 1.0,
        },
    }), encoding="utf-8")

    loaded = load_preset_from_json(path)

    assert loaded.outputs.image_format == "png"
    assert loaded.outputs.requested_image_format == legacy_format
    assert loaded.outputs.image_line_width == pytest.approx(1.0)
    assert loaded.outputs.migration_warnings == (
        f"旧预设图像格式 {legacy_format.upper()} 已迁移为 PNG；本次仅输出 PNG。",
    )

    canonical = tmp_path / "canonical.json"
    save_preset_to_json(loaded, canonical)
    raw = json.loads(canonical.read_text(encoding="utf-8"))
    assert raw["outputs"]["image_format"] == "png"
    assert "requested_image_format" not in raw["outputs"]
    assert "migration_warnings" not in raw["outputs"]
    reloaded = load_preset_from_json(canonical)
    assert reloaded.outputs.requested_image_format is None
    assert reloaded.outputs.migration_warnings == ()


def test_legacy_manual_rpm_preset_migrates_with_warning_and_drops_fields(
    tmp_path,
):
    """Design 2026-08-03 D-C1: batch order analysis no longer supports manual
    RPM. Loading an old preset JSON that requested it must drop both fields
    (not carry them as unrecognized future data) and surface a migration
    warning, exactly as the legacy image-format migration does."""
    path = tmp_path / "legacy-manual-rpm.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "name": "legacy manual rpm",
        "method": "order_time",
        "target_signals": ["sig"],
        "params": {
            "window": "hanning",
            "max_order": 40.0,
            "rpm_mode": "manual",
            "manual_rpm": 1500.0,
        },
        "outputs": {
            "export_data": True,
            "export_image": True,
            "data_format": "csv",
            "image_format": "png",
        },
    }), encoding="utf-8")

    loaded = load_preset_from_json(path)

    assert "rpm_mode" not in loaded.params
    assert "manual_rpm" not in loaded.params
    assert loaded.params["max_order"] == 40.0
    assert loaded.outputs.migration_warnings == (
        "旧预设的手动 RPM 已移除；批处理阶次分析需要指定 RPM 通道。",
    )

    canonical = tmp_path / "canonical.json"
    save_preset_to_json(loaded, canonical)
    raw = json.loads(canonical.read_text(encoding="utf-8"))
    assert "rpm_mode" not in raw["params"]
    assert "manual_rpm" not in raw["params"]
    reloaded = load_preset_from_json(canonical)
    assert reloaded.outputs.migration_warnings == ()


def test_legacy_channel_rpm_mode_preset_migrates_without_warning(tmp_path):
    """Discarding rpm_mode="channel" changes nothing observable -- channel
    was always the only mode the runner honored -- so no warning fires."""
    path = tmp_path / "legacy-channel-rpm.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "name": "legacy channel rpm",
        "method": "order_time",
        "target_signals": ["sig"],
        "rpm_channel": "rpm",
        "params": {"window": "hanning", "rpm_mode": "channel"},
        "outputs": {
            "export_data": True,
            "export_image": True,
            "data_format": "csv",
            "image_format": "png",
        },
    }), encoding="utf-8")

    loaded = load_preset_from_json(path)

    assert "rpm_mode" not in loaded.params
    assert loaded.outputs.migration_warnings == ()


@pytest.mark.parametrize("illegal_format", ("pdf", "svg"))
def test_new_vector_preset_cannot_be_saved_as_if_it_were_legacy(
    tmp_path, illegal_format,
):
    preset = AnalysisPreset.free_config(
        name="new illegal",
        method="fft",
        target_signals=("sig",),
        outputs=BatchOutput(image_format=illegal_format),
    )

    with pytest.raises(ValueError, match="unsupported batch image_format"):
        save_preset_to_json(preset, tmp_path / "illegal.json")


def test_legacy_output_json_without_phase3_fields_migrates_to_defaults(tmp_path):
    path = tmp_path / "legacy-output.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "name": "legacy",
        "method": "fft",
        "target_signals": ["sig"],
        "params": {"window": "hanning", "nfft": 1024},
        "outputs": {
            "export_data": True,
            "export_image": True,
            "data_format": "csv",
        },
    }), encoding="utf-8")

    loaded = load_preset_from_json(path)

    assert loaded.outputs == BatchOutput()


@pytest.mark.parametrize("method", ("fft", "fft_time", "order_time"))
def test_round_trip_preserves_weighting_for_supported_methods(tmp_path, method):
    preset = AnalysisPreset.free_config(
        name=f"{method} weighted",
        method=method,
        target_signals=("vibration_x",),
        rpm_channel="rpm" if method == "order_time" else "",
        params={"window": "hanning", "nfft": 1024, "weighting": "A"},
        outputs=BatchOutput(export_data=True, export_image=True, data_format="csv"),
    )
    path = tmp_path / f"{method}.json"

    save_preset_to_json(preset, path)
    loaded = load_preset_from_json(path)

    assert loaded.method == method
    assert loaded.params["weighting"] == "A"


def test_fft_amplitude_definition_round_trips_through_preset_json(tmp_path):
    preset = AnalysisPreset.free_config(
        name="FFT RMS",
        method="fft",
        target_signals=("sig",),
        params={"amplitude_definition": "rms"},
    )
    path = tmp_path / "fft-rms.json"

    save_preset_to_json(preset, path)
    loaded = load_preset_from_json(path)

    assert loaded.params["amplitude_definition"] == "rms"


def test_serialization_whitelist(tmp_path):
    """Even if runtime/sentinel fields are injected, JSON must not contain them."""
    from dataclasses import replace
    p = replace(
        _basic_preset(),
        file_ids=(1, 2),
        file_paths=("/tmp/a.mf4",),
        signal=(0, "x"),  # forced, illegal for free_config but tolerated by dataclass
        rpm_signal=(0, "rpm"),
        target_pairs=((0, "x"),),
        source_ids=("source-a",),
        source_paths=("/tmp/a.mf4",),
        signal_pattern="vib.*",
    )
    path = tmp_path / "p.json"
    save_preset_to_json(p, path)
    raw = json.loads(path.read_text())
    for forbidden in (
        "file_ids", "file_paths", "source_ids", "source_paths", "signal",
        "rpm_signal", "target_pairs", "signal_pattern",
    ):
        assert forbidden not in raw, f"{forbidden} leaked into JSON"
    # output dir never present (BatchOutput has no directory field; just verify)
    assert "directory" not in raw["outputs"]


def test_target_policy_round_trips_but_runtime_source_scope_does_not(tmp_path):
    from dataclasses import replace

    preset = replace(
        _basic_preset(),
        target_policy="available_per_source",
        source_ids=("source-a",),
        source_paths=("/tmp/a.hdf",),
    )
    path = tmp_path / "policy.json"

    save_preset_to_json(preset, path)
    loaded = load_preset_from_json(path)

    assert loaded.target_policy == "available_per_source"
    assert loaded.source_ids == ()
    assert loaded.source_paths == ()


def test_schema_version_written_as_1(tmp_path):
    path = tmp_path / "p.json"
    save_preset_to_json(_basic_preset(), path)
    raw = json.loads(path.read_text())
    assert raw["schema_version"] == 1


def test_missing_schema_version_treated_as_v1(tmp_path):
    """For back-compat with hand-written presets / fixtures."""
    path = tmp_path / "p.json"
    path.write_text(json.dumps({
        "name": "x", "method": "fft", "target_signals": ["sig"],
        "rpm_channel": "", "params": {"window": "hanning", "nfft": 1024},
        "outputs": {"export_data": True, "export_image": True, "data_format": "csv"},
    }))
    p = load_preset_from_json(path)
    assert p.method == "fft"
    assert p.target_signals == ("sig",)


def test_legacy_batch_preset_value_without_mode_migrates_to_manual(tmp_path):
    """Spec §13 S4: a legacy preset JSON with ``db_reference`` but no
    ``db_reference_mode`` migrates to Manual on load -- same rule as the
    View/preset migration (S2/S3), applied uniformly to Batch presets."""
    path = tmp_path / "legacy_ref.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "name": "legacy ref", "method": "fft",
        "target_signals": ["sig"], "rpm_channel": "",
        "params": {"window": "hanning", "nfft": 1024, "db_reference": 2e-5},
        "outputs": {"export_data": True, "export_image": True, "data_format": "csv"},
    }), encoding="utf-8")

    preset = load_preset_from_json(path)

    assert preset.params["db_reference"] == 2e-5
    assert preset.params["db_reference_mode"] == "manual"


def test_batch_preset_without_reference_key_stays_unmigrated(tmp_path):
    """No ``db_reference`` key at all -> no mode is injected (S4 negative case)."""
    p1 = _basic_preset()
    path = tmp_path / "p.json"
    save_preset_to_json(p1, path)

    p2 = load_preset_from_json(path)

    assert "db_reference" not in p2.params
    assert "db_reference_mode" not in p2.params


def test_unknown_schema_version_rejected(tmp_path):
    path = tmp_path / "p.json"
    path.write_text(json.dumps({
        "schema_version": 2,
        "name": "x", "method": "fft", "target_signals": [],
        "params": {}, "outputs": {},
    }))
    with pytest.raises(UnsupportedPresetVersion):
        load_preset_from_json(path)


def test_corrupt_json_raises(tmp_path):
    path = tmp_path / "p.json"
    path.write_text("{not json")
    with pytest.raises(ValueError):
        load_preset_from_json(path)


def test_round_trip_preserves_chinese_signal_names(tmp_path):
    """CJK characters must survive write/read on Windows where the default
    locale encoding (cp1252/cp936) is not UTF-8. ensure_ascii=False in
    json.dumps is only coherent when paired with an explicit utf-8 file
    write — otherwise we get UnicodeEncodeError or mojibake.
    """
    preset = AnalysisPreset.free_config(
        name="振动批处理",
        method="fft",
        target_signals=("振动_x", "转速"),
        rpm_channel="转速",
        params={"window": "hanning", "nfft": 1024, "备注": "中文参数"},
        outputs=BatchOutput(export_data=True, export_image=True, data_format="csv"),
    )
    path = tmp_path / "preset_zh.json"

    # Write must not raise UnicodeEncodeError under any platform default.
    save_preset_to_json(preset, path)

    # On-disk bytes must be valid UTF-8 and contain the literal CJK glyphs
    # (proves ensure_ascii=False survived the file write — i.e., we did not
    # transcode through cp1252 / cp936 / mbcs).
    raw_bytes = path.read_bytes()
    decoded = raw_bytes.decode("utf-8")
    assert "振动批处理" in decoded
    assert "振动_x" in decoded
    assert "转速" in decoded
    assert "中文参数" in decoded

    # Round-trip read returns the same Chinese strings (not mojibake).
    loaded = load_preset_from_json(path)
    assert loaded.name == "振动批处理"
    assert loaded.target_signals == ("振动_x", "转速")
    assert loaded.rpm_channel == "转速"
    assert loaded.params["备注"] == "中文参数"


def test_frf_pair_rules_round_trip_in_schema_v1_preserving_user_order(tmp_path):
    preset = AnalysisPreset.free_config(
        name="FRF pairs",
        method="frf",
        frf_pair_rules=(
            FrfPairRule("cmd_b", ("out_2", "out_1")),
            FrfPairRule("cmd_a", ("out_3",)),
        ),
        params={"estimator": "H1", "coherence_threshold": 0.8},
    )
    path = tmp_path / "frf.json"

    save_preset_to_json(preset, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    loaded = load_preset_from_json(path)

    assert raw["schema_version"] == 1
    assert raw["frf_pair_rules"] == [
        {"input_channel": "cmd_b", "output_channels": ["out_2", "out_1"]},
        {"input_channel": "cmd_a", "output_channels": ["out_3"]},
    ]
    assert loaded.frf_pair_rules == preset.frf_pair_rules
    assert not hasattr(loaded, "resolved_frf_tasks")


def test_frf_runtime_resolution_never_leaks_into_portable_json(tmp_path):
    preset = AnalysisPreset.free_config(
        name="FRF",
        method="frf",
        frf_pair_rules=(FrfPairRule("cmd", ("actual",)),),
    )
    # Deliberately inject an accidental transient attribute: the serializer is
    # whitelist-based and must still ignore it.
    preset.resolved_frf_tasks = (("source-a", "cmd", "actual"),)
    path = tmp_path / "frf.json"

    save_preset_to_json(preset, path)
    raw = json.loads(path.read_text(encoding="utf-8"))

    assert "frf_pair_rules" in raw
    assert "resolved_frf_tasks" not in raw


def test_handwritten_frf_db_reference_is_dropped_with_migration_warning(tmp_path):
    path = tmp_path / "frf-db-reference.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "name": "FRF",
        "method": "frf",
        "frf_pair_rules": [
            {"input_channel": "cmd", "output_channels": ["actual"]}
        ],
        "params": {
            "estimator": "h1",
            "db_reference": 2e-5,
            "db_reference_mode": "manual",
        },
        "outputs": {},
    }), encoding="utf-8")

    loaded = load_preset_from_json(path)

    assert "db_reference" not in loaded.params
    assert "db_reference_mode" not in loaded.params
    assert any("FRF" in warning for warning in loaded.outputs.migration_warnings)


def test_malformed_frf_pair_rule_is_rejected_instead_of_silently_dropped(tmp_path):
    path = tmp_path / "invalid-frf-rule.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "method": "frf",
        "frf_pair_rules": ["not-an-object"],
        "params": {},
        "outputs": {},
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="frf_pair_rules"):
        load_preset_from_json(path)
