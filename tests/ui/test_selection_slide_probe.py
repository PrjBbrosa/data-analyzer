"""Deterministic contracts for scripts/probe_selection_slide.py (Plan T6)."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication


REPO = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO / "scripts" / "probe_selection_slide.py"


def _load_probe():
    spec = importlib.util.spec_from_file_location("probe_selection_slide", PROBE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def probe():
    return _load_probe()


def test_importing_probe_module_does_not_create_qapplication():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO)
    env.setdefault("TMPDIR", "/tmp")
    env.setdefault("MPLCONFIGDIR", "/tmp")
    code = r"""
import sys
from pathlib import Path
import importlib.util
from PyQt5.QtWidgets import QApplication
assert QApplication.instance() is None, "QApplication existed before import"
path = Path("scripts/probe_selection_slide.py").resolve()
spec = importlib.util.spec_from_file_location("probe_selection_slide_import_gate", path)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
assert QApplication.instance() is None, "import created QApplication"
assert set(mod.P1_REPRESENTATIVE_IDS) == {"N1", "N2", "B1", "B5", "C1", "C2"}
print("ok")
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO),
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert "ok" in completed.stdout


def test_product_code_does_not_import_this_script():
    forbidden = "probe_selection_slide"
    for path in (REPO / "mf4_analyzer").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert forbidden not in text, path


def test_scene_coverage_includes_all_p1_representative_ids(probe):
    assert probe.P1_IDS == ("N1", "N2", "B1", "B2", "B3", "B4", "B5", "B6", "C1", "C2")
    assert probe.P1_REPRESENTATIVE_IDS == ("N1", "N2", "B1", "B5", "C1", "C2")
    covered = set(probe.representative_p1_ids())
    assert covered == set(probe.P1_REPRESENTATIVE_IDS)
    assert set(probe.REPRESENTATIVE_SCENE_IDS) >= {
        "N1-empty",
        "N1-cached",
        "N2",
        "B1-phase",
        "B1-preset",
        "B5",
        "C1",
        "C2",
    }
    assert set(probe.SCENE_BUILDERS) == set(probe.REPRESENTATIVE_SCENE_IDS)
    assert probe.ACTION_TIMEOUT_S == 30.0
    assert probe.GROUP_TIMEOUT_S == 180.0
    assert probe.WARMUP_COUNT == 5
    assert probe.WARM_SAMPLE_COUNT == 40
    assert probe.POLICIES == ("off", "light")


def test_record_format_uses_null_not_zero(probe):
    rec = probe.make_raw_record(
        scene_id="N2",
        policy="light",
        source_fingerprint="abc",
        target="fft",
        signal_counts={"methodChanged": 1},
        final_state={"method": "fft"},
        platform_plugin="offscreen",
        phase="warm",
        entry_kind=probe.ENTRY_BUTTON_CLICK,
        seq=1,
        logic_only=True,
        offscreen=True,
        exposed=False,
        has_paint=False,
        animated=True,
    )
    for name in probe.TIMING_FIELDS:
        assert rec[name] is None
        assert rec[name] != 0
        assert rec["null_reasons"][name] == probe.REASON_LOGIC_ONLY
    rec_off = probe.make_raw_record(
        scene_id="N2",
        policy="off",
        source_fingerprint="abc",
        target="fft",
        signal_counts={"methodChanged": 1},
        final_state={"method": "fft"},
        platform_plugin="cocoa",
        phase="warm",
        entry_kind=probe.ENTRY_BUTTON_CLICK,
        seq=2,
        logic_only=False,
        offscreen=False,
        exposed=True,
        has_paint=True,
        animated=False,
        paint_work_ms=[1.2],
        feedback_paint_ms=8.0,
        content_ready_ms=3.0,
    )
    assert rec_off["animation_end_ms"] is None
    assert rec_off["animation_end_ms"] != 0
    assert rec_off["null_reasons"]["animation_end_ms"] == probe.REASON_NOT_APPLICABLE
    assert rec_off["feedback_paint_ms"] == 8.0
    assert rec_off["paint_work_ms"] == [1.2]


def test_timeout_is_unverified_or_fail_not_pass(probe):
    rec = probe.make_raw_record(
        scene_id="N1-empty",
        policy="light",
        source_fingerprint="abc",
        target="fft",
        signal_counts={},
        final_state={},
        platform_plugin="cocoa",
        phase="warm",
        entry_kind=probe.ENTRY_BUTTON_CLICK,
        seq=1,
        logic_only=False,
        offscreen=False,
        exposed=True,
        has_paint=False,
        animated=True,
        timed_out=True,
    )
    assert rec["status"] in {probe.STATUS_UNVERIFIED, probe.STATUS_FAIL}
    assert rec["status"] != probe.STATUS_PASS
    payload = probe.scene_status_from_records(
        [rec],
        logic_only=False,
        exposed=True,
        timed_out=True,
        error=None,
        source_changed=False,
        contract_ok=True,
    )
    assert payload["status"] in {probe.STATUS_UNVERIFIED, probe.STATUS_FAIL}
    assert payload["status"] != probe.STATUS_PASS
    assert payload["performance_status"] != probe.STATUS_PASS
    assert payload["reason"] == probe.REASON_TIMEOUT


def test_qsettings_isolation_and_cleanup(probe, tmp_path):
    token = probe.isolate_qsettings(tmp_path)
    try:
        path = probe.prove_qsettings_isolated(token)
        assert str(tmp_path) in path
        store = QSettings("MF4Analyzer", "DataAnalyzer")
        store.setValue("probe/selection_slide_marker", "isolated")
        store.sync()
        assert str(tmp_path) in str(store.fileName())
        assert "Library/Preferences" not in str(store.fileName())
        assert store.value("probe/selection_slide_marker") == "isolated"
    finally:
        token.restore()
    restored = QSettings("MF4Analyzer", "DataAnalyzer")
    assert restored.value("probe/selection_slide_marker") != "isolated" or (
        str(tmp_path) not in str(restored.fileName())
    )


def test_logic_only_offscreen_without_flag_fails(probe, qapp):
    if not probe.is_offscreen_platform(qapp):
        pytest.skip("this gate is for the offscreen test process")
    with pytest.raises(probe.PlatformPolicyError, match="offscreen"):
        probe.require_platform(logic_only=False, app=qapp)
    allowed = probe.require_platform(logic_only=True, app=qapp)
    assert allowed["allowed"] is True


def test_off_light_instance_policy_and_signal_counts(probe, qapp, tmp_path):
    output = tmp_path / "n2"
    report = probe.run_all_scenes(
        logic_only=True,
        output_dir=output,
        warmup=0,
        samples=1,
        scene_ids=["N2"],
        capture_shots=False,
        record_screen=False,
    )
    assert report["schema_version"] == 1
    policies = {item["policy"] for item in report["scenarios"]}
    assert policies == {"off", "light"}
    assert {item["id"] for item in report["scenarios"]} == {"N2"}
    for scenario in report["scenarios"]:
        assert scenario["performance_status"] != probe.STATUS_PASS
        stats = scenario["statistics"]
        for name in probe.TIMING_FIELDS:
            assert stats[name] is None
        assert stats["null_reason"] == probe.REASON_LOGIC_ONLY
        records = scenario["records"]
        assert any(rec["phase"] == "first_access" for rec in records)
        assert any(rec["phase"] == "program_restore" for rec in records)
        assert any(rec["phase"] == "warm" for rec in records)
        for rec in records:
            for name in probe.TIMING_FIELDS:
                assert rec[name] is None
                assert rec[name] != 0
                assert rec["null_reasons"][name] == probe.REASON_LOGIC_ONLY
            assert rec["entry_kind"] != "direct_call" or rec["phase"] == "program_restore"
            if rec["phase"] in {"first_access", "warm"}:
                assert rec["entry_kind"] in {
                    probe.ENTRY_BUTTON_CLICK,
                    probe.ENTRY_KEY_ACTIVATION,
                }
            if rec["phase"] == "program_restore":
                assert rec["entry_kind"] == probe.ENTRY_PROGRAM_RESTORE
        user = next(rec for rec in records if rec["phase"] == "first_access")
        program = next(rec for rec in records if rec["phase"] == "program_restore")
        assert user["signal_counts"]["methodChanged"] == 1
        assert user["signal_counts"]["methodActivated"] == 1
        assert program["signal_counts"]["methodActivated"] == 0
        assert program["signal_counts"]["methodChanged"] >= 1
        assert program["final_state"]["driver_active"] is False
        if scenario["policy"] == "off":
            assert user["final_state"]["driver_active"] is False
    dumped = json.loads((output / "selection-slide.json").read_text(encoding="utf-8"))
    assert dumped["p1_representative_ids"] == ["N2"]
    assert dumped["environment"]["logic_only"] is True


def test_c2_split_focus_signal_counts(probe, qapp, tmp_path):
    report = probe.run_all_scenes(
        logic_only=True,
        output_dir=tmp_path / "c2",
        warmup=0,
        samples=1,
        scene_ids=["C2"],
        capture_shots=False,
    )
    light = next(item for item in report["scenarios"] if item["policy"] == "light")
    user = next(rec for rec in light["records"] if rec["phase"] == "first_access")
    assert user["signal_counts"]["source_cursor_mode_changed"] == 0
    assert user["signal_counts"]["target_cursor_mode_changed"] == 1
    assert user["final_state"]["source_canvas"] == "off"
    assert user["final_state"]["target_canvas"] == "dual"
    program = next(rec for rec in light["records"] if rec["phase"] == "program_restore")
    assert program["entry_kind"] == probe.ENTRY_PROGRAM_RESTORE
    assert program["final_state"]["source_driver_active"] is False
    assert program["final_state"]["target_driver_active"] is False


def test_b5_layout_disable_does_not_animate(probe, qapp, tmp_path):
    report = probe.run_all_scenes(
        logic_only=True,
        output_dir=tmp_path / "b5",
        warmup=0,
        samples=1,
        scene_ids=["B5"],
        capture_shots=False,
    )
    light = next(item for item in report["scenarios"] if item["policy"] == "light")
    first = next(rec for rec in light["records"] if rec["phase"] == "first_access")
    assert first["target"] == "none"
    assert first["final_state"]["layout_enabled"] is False
    assert first["final_state"]["driver_active"] is False
    assert first["null_reasons"]["animation_end_ms"] == probe.REASON_LOGIC_ONLY


def test_logic_only_covers_representative_scene_ids(probe, qapp, tmp_path):
    report = probe.run_all_scenes(
        logic_only=True,
        output_dir=tmp_path / "all",
        warmup=0,
        samples=1,
        scene_ids=list(probe.REPRESENTATIVE_SCENE_IDS),
        capture_shots=False,
    )
    ids = {item["id"] for item in report["scenarios"]}
    assert ids == set(probe.REPRESENTATIVE_SCENE_IDS)
    assert set(report["p1_representative_ids"]) == set(probe.P1_REPRESENTATIVE_IDS)
    policies_by_scene = {}
    for item in report["scenarios"]:
        policies_by_scene.setdefault(item["id"], set()).add(item["policy"])
    for scene_id in probe.REPRESENTATIVE_SCENE_IDS:
        assert policies_by_scene[scene_id] == {"off", "light"}
    for scenario in report["scenarios"]:
        assert scenario["performance_status"] != probe.STATUS_PASS
        assert scenario["statistics"]["null_reason"] == probe.REASON_LOGIC_ONLY
        for rec in scenario["records"]:
            for name in probe.TIMING_FIELDS:
                assert rec[name] is None
            if rec["phase"] != "program_restore":
                assert rec["entry_kind"] in {
                    probe.ENTRY_BUTTON_CLICK,
                    probe.ENTRY_KEY_ACTIVATION,
                }
            else:
                assert rec["entry_kind"] == probe.ENTRY_PROGRAM_RESTORE
    assert QApplication.instance() is qapp


def test_clock_advanced_values_are_not_performance_fields(probe):
    rec = probe.make_raw_record(
        scene_id="B1-phase",
        policy="light",
        source_fingerprint="abc",
        target="wrapped",
        signal_counts={"choice_currentIndexChanged": 1},
        final_state={},
        platform_plugin="offscreen",
        phase="warm",
        entry_kind=probe.ENTRY_BUTTON_CLICK,
        seq=1,
        feedback_paint_ms=300.0,
        animation_end_ms=300.0,
        content_ready_ms=300.0,
        logic_only=True,
        offscreen=True,
        exposed=False,
        has_paint=False,
        animated=True,
    )
    assert rec["feedback_paint_ms"] is None
    assert rec["animation_end_ms"] is None
    assert rec["content_ready_ms"] is None
    assert rec["null_reasons"]["feedback_paint_ms"] == probe.REASON_LOGIC_ONLY
