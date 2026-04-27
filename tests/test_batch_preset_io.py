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


def test_serialization_whitelist(tmp_path):
    """Even if runtime/sentinel fields are injected, JSON must not contain them."""
    from dataclasses import replace
    p = replace(
        _basic_preset(),
        file_ids=(1, 2),
        file_paths=("/tmp/a.mf4",),
        signal=(0, "x"),  # forced, illegal for free_config but tolerated by dataclass
        rpm_signal=(0, "rpm"),
        signal_pattern="vib.*",
    )
    path = tmp_path / "p.json"
    save_preset_to_json(p, path)
    raw = json.loads(path.read_text())
    for forbidden in ("file_ids", "file_paths", "signal", "rpm_signal",
                      "signal_pattern"):
        assert forbidden not in raw, f"{forbidden} leaked into JSON"
    # output dir never present (BatchOutput has no directory field; just verify)
    assert "directory" not in raw["outputs"]


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
