"""Deterministic contracts for scripts/probe_interaction_motion.py (Plan T5)."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from PyQt5.QtCore import QSettings
from PyQt5.QtWidgets import QApplication


REPO = Path(__file__).resolve().parents[2]
PROBE_PATH = REPO / "scripts" / "probe_interaction_motion.py"


def _load_probe():
    spec = importlib.util.spec_from_file_location("probe_interaction_motion", PROBE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def probe():
    return _load_probe()


def test_product_and_old_probe_do_not_import_this_script():
    forbidden = "probe_interaction_motion"
    for path in (REPO / "mf4_analyzer").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert forbidden not in text, path
    old = (REPO / "scripts" / "probe_view_switch_quality.py").read_text(encoding="utf-8")
    assert forbidden not in old
    new = PROBE_PATH.read_text(encoding="utf-8")
    assert "import probe_view_switch_quality" not in new
    assert "from scripts" not in new
    assert "_time_mainwindow_section_round_trip" not in new


def test_event_attribution_interleaved(probe):
    session = probe.ActionSession()
    first = session.begin(probe.ENTRY_TAB_CLICK, "view:a", t_input=1.0)
    session.finish_callback(first, t=1.01)
    second = session.begin(probe.ENTRY_TAB_CLICK, "view:b", t_input=1.02)
    session.finish_callback(second, t=1.03)
    paint_b = session.note_paint("view:b", 1.04, 1.05)
    paint_a = session.note_paint("view:a", 1.06, 1.07)
    stray = session.note_paint("view:other", 1.08, 1.09)
    assert paint_b.action_seq == second.seq
    assert paint_a.action_seq == first.seq
    assert stray.action_seq is None
    assert [item.seq for item in session.paints_for(first)] == [paint_a.seq]
    assert [item.seq for item in session.paints_for(second)] == [paint_b.seq]


def test_metrics_null_without_paint_or_exposed(probe):
    session = probe.ActionSession()
    action = session.begin(probe.ENTRY_TAB_CLICK, "view:a", t_input=2.0)
    session.note_identity(action, "view:a", t=2.01)
    session.note_xlim(action, t=2.02)
    session.note_ylim(action, t=2.03)
    session.note_settle(action, t=2.04)
    session.finish_callback(action, t=2.015)
    stats = probe.publish_statistics(
        session, [action], logic_only=False, exposed=False, has_real_paint=False
    )
    for name in probe.TIMING_FIELDS:
        assert stats[name] is None
    assert stats["null_reason"] == probe.REASON_NOT_EXPOSED
    stats = probe.publish_statistics(
        session, [action], logic_only=False, exposed=True, has_real_paint=False
    )
    assert stats["feedback_paint_ms"] is None
    assert stats["stable_paint_ms"] is None
    assert stats["paint_work_ms"] is None
    assert stats["null_reason"] == probe.REASON_NO_PAINT
    contract = probe.derive_action_contract(session, action)
    assert contract["feedback_paint_ms"] is None
    assert contract["stable_paint_ms"] is None
    assert contract["content_ready_ms"] is not None


def test_content_ready_after_final_xy_and_identity(probe):
    session = probe.ActionSession()
    action = session.begin(probe.ENTRY_TAB_CLICK, "view:target", t_input=3.0)
    session.note_xlim(action, t=3.01)
    session.note_ylim(action, t=3.02)
    session.note_settle(action, t=3.03)
    assert action.content_ready_ms is None
    session.note_identity(action, "view:other", t=3.04)
    assert action.content_ready_ms is None
    session.note_identity(action, "view:target", t=3.05)
    assert action.content_ready_t == pytest.approx(3.05)
    assert action.content_ready_ms == pytest.approx(50.0)
    later = session.note_paint("view:target", 3.06, 3.07)
    assert later.after_content_ready is True
    early = session.note_paint("view:target", 3.04, 3.041)
    # A paint that started before content_ready is not the stable frame.
    assert early.after_content_ready is False
    contract = probe.derive_action_contract(session, action)
    assert contract["stable_paint_ms"] == pytest.approx(70.0)


def test_cached_scenario_records_zero_compute(probe):
    session = probe.ActionSession()
    init = session.begin(probe.ENTRY_TOOLBAR_BUTTON, "mode:fft", require_geometry=False, require_cache=True)
    session.note_compute_submit(init)
    session.discard(init)
    assert session.compute_submits == 1
    session.compute_submits = 0
    sampled = session.begin(
        probe.ENTRY_TOOLBAR_BUTTON, "mode:fft",
        require_geometry=False, require_cache=True, t_input=4.0,
    )
    session.note_identity(sampled, "mode:fft", t=4.01)
    session.note_cache(sampled, True, t=4.02)
    session.finish_callback(sampled, t=4.011)
    assert sampled.compute_submits == 0
    assert session.compute_submits == 0
    payload = probe._scenario_payload(
        probe.SCENARIO_M02_CACHED,
        session,
        config={"sampling_compute_submits": session.compute_submits},
        entry_kind=probe.ENTRY_TOOLBAR_BUTTON,
        phase="warm",
        logic_only=True,
        exposed=False,
        source_changed=False,
        init_ms=12.0,
        final_state={"sampling_compute_submits": 0},
    )
    assert payload["compute_submits"] == 0
    assert payload["config"]["sampling_compute_submits"] == 0


def test_exception_and_source_change_unverified(probe):
    session = probe.ActionSession()
    action = session.begin(probe.ENTRY_TAB_CLICK, "view:a", t_input=5.0)
    session.note_error(action, RuntimeError("boom"))
    payload = probe._scenario_payload(
        "M01-small",
        session,
        config={},
        entry_kind=probe.ENTRY_TAB_CLICK,
        phase="warm",
        logic_only=True,
        exposed=False,
        source_changed=False,
        init_ms=None,
        final_state={},
    )
    assert payload["status"] == probe.STATUS_UNVERIFIED
    assert payload["performance_status"] == probe.STATUS_UNVERIFIED
    assert payload["reason"] == probe.REASON_EXCEPTION

    session = probe.ActionSession()
    action = session.begin(probe.ENTRY_TAB_CLICK, "view:a", t_input=5.0)
    session.note_identity(action, "view:a", t=5.01)
    payload = probe._scenario_payload(
        "M01-small",
        session,
        config={},
        entry_kind=probe.ENTRY_TAB_CLICK,
        phase="warm",
        logic_only=True,
        exposed=False,
        source_changed=True,
        init_ms=None,
        final_state={},
    )
    assert payload["status"] == probe.STATUS_UNVERIFIED
    assert payload["reason"] == probe.REASON_SOURCE_CHANGED


def test_logic_only_never_outputs_performance_pass(probe, tmp_path, qapp):
    args = argparse.Namespace(
        logic_only=True,
        output=str(tmp_path / "samples.json"),
        output_dir=str(tmp_path),
        record_screen=False,
        warmup=0,
        samples=1,
        scenario=[],
        skip_cold=True,
        cold_one=False,
    )
    report = probe.cmd_samples(args)
    assert report["schema_version"] == 1
    assert set(report) >= {
        "schema_version",
        "environment",
        "source_snapshot_before",
        "source_snapshot_after",
        "scenarios",
        "errors",
    }
    assert probe.performance_status_is_pass(report) is False
    for scenario in report["scenarios"]:
        assert scenario["performance_status"] != probe.STATUS_PASS
        assert scenario["status"] != probe.STATUS_PASS or scenario.get("statistics", {}).get("null_reason")
        stats = scenario["statistics"]
        for name in probe.TIMING_FIELDS:
            assert stats[name] is None
        assert stats["null_reason"] in {
            probe.REASON_LOGIC_ONLY,
            "motion_demo_unavailable",
        }
    dumped = json.loads((tmp_path / "samples.json").read_text(encoding="utf-8"))
    assert dumped["schema_version"] == 1
    assert probe.performance_status_is_pass(dumped) is False


def test_offscreen_without_logic_only_fails(probe, qapp):
    if not probe.is_offscreen_platform(qapp):
        pytest.skip("this gate is for the offscreen test process")
    with pytest.raises(probe.PlatformPolicyError, match="offscreen"):
        probe.require_platform(logic_only=False, app=qapp)
    allowed = probe.require_platform(logic_only=True, app=qapp)
    assert allowed["allowed"] is True


def test_paint_interval_not_applicable_without_animation(probe):
    session = probe.ActionSession()
    session.animation_active = False
    action = session.begin(probe.ENTRY_TAB_CLICK, "view:a", t_input=6.0)
    session.note_paint("view:a", 6.01, 6.012)
    session.note_paint("view:a", 6.02, 6.022)
    stats = probe.publish_statistics(
        session, [action], logic_only=False, exposed=True, has_real_paint=True
    )
    assert stats["paint_interval_ms"] is None
    assert stats["paint_interval_reason"] == probe.REASON_NOT_APPLICABLE
    session.animation_active = True
    action = session.begin(probe.ENTRY_TAB_CLICK, "view:b", t_input=7.0)
    session.note_paint("view:b", 7.01, 7.012, animation_active=True)
    session.note_paint("view:b", 7.03, 7.032, animation_active=True)
    stats = probe.publish_statistics(
        session, [action], logic_only=False, exposed=True, has_real_paint=True
    )
    assert stats["paint_interval_ms"] is not None
    assert stats["paint_interval_ms"]["n"] == 1


def test_direct_call_is_separated(probe):
    session = probe.ActionSession()
    click = session.begin(probe.ENTRY_TAB_CLICK, "view:a", t_input=8.0)
    direct = session.begin(probe.ENTRY_DIRECT_CALL, "view:a", t_input=8.1)
    assert click in session.actions
    assert direct in session.direct_call_actions
    assert direct not in session.actions
    payload = probe._scenario_payload(
        "M01-small",
        session,
        config={},
        entry_kind=probe.ENTRY_TAB_CLICK,
        phase="warm",
        logic_only=True,
        exposed=False,
        source_changed=False,
        init_ms=None,
        final_state={},
    )
    assert payload["events"][0]["entry_kind"] == probe.ENTRY_TAB_CLICK
    assert payload["direct_call_events"][0]["entry_kind"] == probe.ENTRY_DIRECT_CALL


def test_qsettings_isolation_includes_nativeformat(probe, tmp_path):
    token = probe.isolate_qsettings(tmp_path)
    try:
        path = probe.prove_qsettings_isolated(token)
        assert str(tmp_path) in path
        store = QSettings("MF4Analyzer", "DataAnalyzer")
        store.setValue("files/recent_v1", "must-not-touch-user-store")
        store.sync()
        assert str(tmp_path) in str(store.fileName())
        assert "Library/Preferences" not in str(store.fileName())
    finally:
        token.restore()


def test_abba_uses_independent_hosts(probe):
    hosts = []

    class Host:
        def __init__(self, mode):
            self.mode = mode

        def run_sample(self, _sample_id):
            return None

    def factory(mode):
        host = Host(mode)
        hosts.append(host)
        return host

    closed = []
    scenarios = probe.run_sample_abba(
        logic_only=True,
        host_factory=factory,
        teardown_host=closed.append,
    )
    assert [item.mode for item in hosts] == ["current", "light", "light", "current"]
    assert len({id(item) for item in hosts}) == 4
    assert closed == hosts
    assert len(scenarios) == 4
    assert all(item["performance_status"] != probe.STATUS_PASS for item in scenarios)


def test_fixture_matches_spec(probe):
    small = probe.make_synthetic_arrays(2, 10_000, 1000.0, dense=False)
    channels, names, summary = small
    assert names == ("方向盘扭矩", "电机转速")
    assert summary["fs"] == 1000.0
    assert summary["unit"] == "Nm"
    assert channels["Time"].dtype.kind == "f"
    assert len(channels["Time"]) == 10_000
    dense = probe.make_synthetic_arrays(8, 1_000, 20_000.0, dense=True)
    assert dense[2]["seed"] == 20260905
    assert len(dense[1]) == 8
    again = probe.make_synthetic_arrays(8, 1_000, 20_000.0, dense=True)
    assert (dense[0][dense[1][0]] == again[0][again[1][0]]).all()


def test_schema_and_timeout_constants(probe):
    report = probe.empty_report(logic_only=True, error="x")
    assert report["schema_version"] == 1
    assert report["errors"] == ["x"]
    assert report["environment"]["presentation_timestamp_available"] is False
    assert probe.ACTION_TIMEOUT_S == 30.0
    assert probe.GROUP_TIMEOUT_S == 180.0
    assert probe.INIT_TIMEOUT_S == 30.0
    assert probe.WARMUP_COUNT == 5
    assert probe.WARM_SAMPLE_COUNT == 40
    assert probe.COLD_PROCESS_COUNT == 5


def test_mainwindow_tab_toolbar_and_cached_compute(probe, qtbot, qapp, tmp_path):
    sheet = QApplication.instance().styleSheet()
    window, token = probe.create_isolated_mainwindow(tmp_path)
    qtbot.addWidget(window)
    wraps = None
    heartbeat = None
    try:
        window.show()
        qapp.processEvents()
        session = probe.ActionSession()
        wraps = probe.MethodWraps()
        heartbeat = probe.Heartbeat(session)
        heartbeat.start(window)
        probe.attach_switch_observers(window, session, wraps)
        fid, names, _summary = probe.register_fixture(window, probe.SCENARIO_M01_SMALL)
        probe.prepare_two_time_views(qapp, window, fid, names)
        assert len(window.view_manager.views) >= 2
        budget = probe.TimeoutBudget()
        first = probe.run_one_view_switch(
            qapp, window, session, target_index=0, budget=budget
        )
        assert first.entry_kind == probe.ENTRY_TAB_CLICK
        assert first.target_identity.startswith("view:")

        fft = probe.run_one_mode_switch(
            qapp, window, session,
            mode="fft",
            budget=budget,
            entry_kind=probe.ENTRY_TOOLBAR_BUTTON,
            require_cache=False,
        )
        assert fft.entry_kind == probe.ENTRY_TOOLBAR_BUTTON
        assert "fft" in session.mode_changed_calls
        assert window.chart_stack.current_mode() == "fft"

        probe.prime_fft_sources(window, fid, names)
        session.compute_submits = 0
        params = window.inspector.fft_ctx.compute_params()
        _t, sig, fs = window._get_sig()
        if sig is None:
            arrays, _names, _summary = probe.make_synthetic_arrays(1, 1024, 1000.0)
            sig = arrays["方向盘扭矩"]
            fs = 1000.0
        window._fft_compute_arrays(sig, fs, params)
        assert session.compute_submits >= 1
        session.compute_submits = 0
        for action in session.actions:
            action.compute_submits = 0
        back = probe.run_one_mode_switch(
            qapp, window, session,
            mode="time",
            budget=budget,
            entry_kind=probe.ENTRY_TOOLBAR_BUTTON,
            require_cache=False,
        )
        again = probe.run_one_mode_switch(
            qapp, window, session,
            mode="fft",
            budget=budget,
            entry_kind=probe.ENTRY_TOOLBAR_BUTTON,
            require_cache=True,
        )
        assert back.compute_submits == 0
        assert again.compute_submits == 0
        assert session.compute_submits == 0
        direct = probe.run_one_mode_switch(
            qapp, window, session,
            mode="time",
            budget=budget,
            entry_kind=probe.ENTRY_DIRECT_CALL,
            require_cache=False,
        )
        assert direct in session.direct_call_actions
    finally:
        probe.teardown_probe(
            app=qapp,
            window=window,
            heartbeat=heartbeat,
            wraps=wraps,
            destroy_window=False,
        )
        token.restore()
        QApplication.instance().setStyleSheet(sheet)
