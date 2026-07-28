from __future__ import annotations
import json
import pytest

from mf4_analyzer.batch import AnalysisPreset, BatchOutput
from mf4_analyzer.batch_preset_io import (
    save_preset_to_json, load_preset_from_json, UnsupportedPresetVersion,
)


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
            image_format="svg",
            image_size="custom",
            image_width=2304,
            image_height=1296,
            image_dpi=192,
            conflict_policy="overwrite",
            write_manifest=False,
            resume_policy="manifest",
        ),
    )
    path = tmp_path / "phase3.json"

    save_preset_to_json(preset, path)
    loaded = load_preset_from_json(path)

    assert loaded.outputs == preset.outputs


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
