from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.io import FileData
from mf4_analyzer.signal.frf import FrfEffectiveFacts, FrfResult
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui.main_window._frf_mixin import FrfPreflightError
from mf4_analyzer.ui.time_xaxis import CustomXAxisSpec


def _window_with_pair(qtbot, *, n=2000, fs=1000.0):
    win = MainWindow()
    qtbot.addWidget(win)
    time = np.arange(n, dtype=float) / fs
    frame = pd.DataFrame(
        {
            "input": np.sin(2 * np.pi * 20.0 * time),
            "output": 2.0 * np.sin(2 * np.pi * 20.0 * time - 0.2),
        }
    )
    fid = "source-a"
    win.files[fid] = FileData(
        "source-a.csv",
        frame,
        list(frame.columns),
        {"input": "N", "output": "m/s2"},
        fs=fs,
    )
    win.files[fid].time_array = time
    win.view_manager.get(win.view_manager.active).attached_file_ids = [fid]
    state = win.analysis_managers["frf"].get(0)
    state.panes[0].input_source = (fid, "input")
    state.panes[0].output_source = (fid, "output")
    win._update_combos()
    win.inspector.frf_ctx.set_input_source((fid, "input"))
    win.inspector.frf_ctx.set_output_source((fid, "output"))
    return win, fid, state, time


def _result(time, fs, *, segments=6, warnings=()):
    frequency = np.array([0.0, 10.0, 20.0])
    facts = FrfEffectiveFacts(
        requested_t_win_s=0.5,
        requested_nperseg=500,
        nperseg=500,
        nfft=500,
        noverlap=250,
        hop=250,
        segments=segments,
        fs=fs,
        df=2.0,
        n_samples=len(time),
        time_start=float(time[0]),
        time_end=float(time[-1]),
        window="hanning",
        periodic_window=True,
        detrend="constant",
        max_time_jitter=0.0,
        max_time_difference=0.0,
        invalid_bins=0,
    )
    return FrfResult(
        frequencies=frequency,
        transfer=np.array([1.0, 2.0, 2.0], dtype=complex),
        pxx=np.ones(3),
        pyy=np.ones(3),
        pxy=np.ones(3, dtype=complex),
        coherence=np.ones(3),
        effective=facts,
        warnings=tuple(warnings),
    )


def _seed_frf_cache(win, state, pane_idx, result):
    """Put ``result`` where a completed run for this pane would have left it."""
    pane = state.panes[pane_idx]
    pane.effective_time_range = (
        float(result.effective.time_start),
        float(result.effective.time_end),
    )
    key = win._frf_cache_key_for_pane(state, pane)
    assert key is not None
    win.analysis_caches["frf"].put(key, result)
    return key


def test_main_window_builds_directional_frf_cache_and_coordinator(qtbot):
    win = MainWindow()
    qtbot.addWidget(win)

    assert "frf" in win.analysis_caches
    assert win._frf_coordinator._cache is win.analysis_caches["frf"]
    assert win.canvas_frf is win.chart_stack.canvas_frf


def test_global_tick_density_updates_all_frf_panes(qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    page = win.chart_stack.page_frf
    calls = []
    monkeypatch.setattr(
        page.pane_canvas(0), "set_tick_density",
        lambda x, y: calls.append((x, y)),
    )

    win._update_all_tick_density_pair(14, 9)

    assert calls == [(14, 9)]


def test_frf_scope_refresh_keeps_out_of_scope_pair_visible_and_pane_synced(qtbot):
    """The current TimeDomain View leaves no hidden UI/pane pair mismatch."""
    win, _fid, state, _time = _window_with_pair(qtbot)
    ctx = win.inspector.frf_ctx

    win.view_manager.get(win.view_manager.active).attached_file_ids = []
    win._update_combos()

    assert ctx.pair() == (("source-a", "input"), ("source-a", "output"))
    assert state.panes[0].input_source == ("source-a", "input")
    assert state.panes[0].output_source == ("source-a", "output")
    assert "当前时域 View 外" in ctx.combo_input.currentText()
    assert not ctx.btn_compute.isEnabled()
    assert "当前时域 View" in ctx.validation_message()


def test_frf_candidate_forwards_both_real_times_and_one_physical_mask(
    qtbot, monkeypatch
):
    win, fid, state, time = _window_with_pair(qtbot)
    win.inspector.frf_ctx.spin_t_win.setValue(0.5)
    state.params["range_mode"] = "manual"
    state.panes[0].time_range = (0.25, 1.25)
    captured = {}

    def fake_compute(input_values, output_values, **kwargs):
        captured.update(
            input_values=np.asarray(input_values),
            output_values=np.asarray(output_values),
            input_time=np.asarray(kwargs["input_time"]),
            output_time=np.asarray(kwargs["output_time"]),
            fs=kwargs["fs"],
        )
        return _result(kwargs["input_time"], kwargs["fs"])

    monkeypatch.setattr(
        "mf4_analyzer.ui.main_window._frf_mixin.compute_frf", fake_compute
    )
    candidate = win._build_frf_candidate(state, 0)
    candidate["job"](SimpleNamespace(
        cancelled=lambda: False,
        progress=SimpleNamespace(emit=lambda *_args: None),
    ))

    expected = (time >= 0.25) & (time <= 1.25)
    assert np.array_equal(captured["input_time"], time[expected])
    assert np.array_equal(captured["output_time"], time[expected])
    assert captured["input_values"].shape == captured["output_values"].shape
    assert candidate["time_range"] == (
        float(time[expected][0]),
        float(time[expected][-1]),
    )
    assert candidate["view_id"] == state.view_id
    assert candidate["pane_idx"] == 0
    assert candidate["input_unit"] == "N"
    assert candidate["output_unit"] == "m/s2"


def test_frf_manual_range_ignores_time_jitter_outside_selected_samples(qtbot):
    win, fid, state, time = _window_with_pair(qtbot)
    jittered = time.copy()
    jittered[1500:] += 0.1
    win.files[fid].time_array = jittered
    win.inspector.frf_ctx.spin_t_win.setValue(0.5)
    state.params["range_mode"] = "manual"
    state.panes[0].time_range = (0.1, 0.9)

    candidate = win._build_frf_candidate(state, 0)

    assert candidate["time_range"] == (0.1, 0.9)


def test_frf_manual_range_auto_rebuilds_time_jitter_inside_selected_samples(qtbot):
    win, fid, state, time = _window_with_pair(qtbot)
    jittered = time.copy()
    jittered[500:] += 0.1
    win.files[fid].time_array = jittered
    win.files[fid]._time_source = "column"
    win.inspector.frf_ctx.spin_t_win.setValue(0.5)
    state.params["range_mode"] = "manual"
    state.panes[0].time_range = (0.1, 0.9)

    candidate = win._build_frf_candidate(state, 0)

    lo, hi = candidate["time_range"]
    assert 0.1 <= lo <= hi <= 0.9
    assert win.files[fid]._time_source == "manual"
    assert win.files[fid].is_time_axis_uniform()
    assert float(win.files[fid].fs) == pytest.approx(
        win.files[fid].suggested_fs_from_time_axis()
    )


def test_frf_preflight_rejects_uniform_but_generated_timebase(qtbot):
    win, _fid, state, _time = _window_with_pair(qtbot)
    win.files[state.panes[0].input_source[0]]._time_source = "generated"

    with pytest.raises(FrfPreflightError, match="真实时间轴"):
        win._build_frf_candidate(state, 0)


@pytest.mark.parametrize(
    "time_values, message",
    [
        (None, "真实时间轴"),
        (np.zeros((2, 2)), "一维"),
    ],
)
def test_frf_preflight_reports_missing_or_non_vector_timebase(
    qtbot, time_values, message
):
    win, _fid, state, _time = _window_with_pair(qtbot)
    fd = win.files[state.panes[0].input_source[0]]
    fd.time_array = time_values

    with pytest.raises(FrfPreflightError, match=message):
        win._build_frf_candidate(state, 0)


def test_main_window_loaded_source_ids_are_canonical_strings(qtbot, tmp_path):
    path = tmp_path / "source.csv"
    pd.DataFrame({"time": [0.0, 0.1], "signal": [1.0, 2.0]}).to_csv(
        path, index=False
    )
    win = MainWindow()
    qtbot.addWidget(win)
    win._load_one(str(path))

    assert win.files
    assert all(isinstance(fid, str) for fid in win.files)


def test_frf_capture_keeps_directional_roles_and_three_y_ranges(qtbot):
    win, fid, state, _time = _window_with_pair(qtbot)
    canvas = win.chart_stack.page_frf.pane_canvas(0)
    result = _result(np.arange(2000) / 1000.0, 1000.0)
    canvas.set_result(result)
    canvas.set_xlim(5.0, 20.0)
    canvas.set_ylim("magnitude", -30.0, 10.0)
    canvas.set_ylim("phase", -180.0, 180.0)
    canvas.set_ylim("coherence", 0.0, 1.0)

    win._capture_active_analysis_view("frf")

    pane = state.panes[0]
    assert pane.sources == []
    assert pane.input_source == (fid, "input")
    assert pane.output_source == (fid, "output")
    assert set(pane.ylims) == {"magnitude", "phase", "coherence"}
    assert pane.xlim is not None


def test_frf_cursor_mode_is_pane_local_and_restores_across_view_switches(qtbot):
    """The shared frequency toolbar must not leak A/B mode by focus or View."""
    win, _fid, state, _time = _window_with_pair(qtbot)
    page = win.chart_stack.page_frf
    assert state.add_pane() is True
    page.enter_split()

    first_card = page._cards[0]
    first_card.set_cursor_mode("dual")
    assert state.panes[0].cursor_mode == "dual"
    assert state.panes[1].cursor_mode == "off"

    page.set_focused_index(1)
    assert first_card._cursor_buttons["off"].isChecked()
    assert page._cards[0].cursor_mode() == "dual"
    assert page._cards[1].cursor_mode() == "off"

    manager = win.analysis_managers["frf"]
    other_idx = manager.new_view()
    manager.set_active(other_idx)
    assert page.pane_count() == 1
    assert page._cards[0].cursor_mode() == "off"

    manager.set_active(0)
    assert page.pane_count() == 2
    assert page._cards[0].cursor_mode() == "dual"
    assert page._cards[1].cursor_mode() == "off"


def test_frf_main_window_runs_shared_worker_and_renders_result(qtbot):
    win, _fid, _state, _time = _window_with_pair(qtbot, n=4000)
    win.inspector.frf_ctx.spin_t_win.setValue(0.5)

    assert win.do_frf() is True
    canvas = win.chart_stack.page_frf.pane_canvas(0)
    qtbot.waitUntil(canvas.has_result, timeout=3000)
    qtbot.waitUntil(
        lambda: not win._analysis_jobs.is_running("frf"), timeout=3000
    )

    assert canvas._result.effective.segments >= 2
    assert win._analysis_jobs.progress_token("frf") is None


def test_candidate_keeps_requested_snapshot_separate_from_effective_samples(qtbot):
    win, _fid, state, _time = _window_with_pair(qtbot)
    win.inspector.frf_ctx.spin_t_win.setValue(0.5)
    state.params["range_mode"] = "manual"
    pane = state.panes[0]
    pane.time_range = (0.2504, 1.2496)

    candidate = win._build_frf_candidate(state, 0)

    assert pane.time_range == (0.2504, 1.2496)
    assert candidate["time_range"] == (0.251, 1.249)


def test_view_wide_compute_change_invalidates_every_pane(qtbot, monkeypatch):
    win, _fid, state, _time = _window_with_pair(qtbot)
    win._on_analysis_split("frf", True)
    invalidated = []
    monkeypatch.setattr(
        win._frf_coordinator,
        "invalidate_pane",
        lambda view_id, pane_idx: invalidated.append((view_id, pane_idx)),
    )

    win._on_frf_compute_params_changed({"t_win_s": 0.25})

    assert invalidated == [(state.view_id, 0), (state.view_id, 1)]
    page = win.chart_stack.page_frf
    assert page.pane_canvas(0).state() == "stale"
    assert page.pane_canvas(1).state() == "stale"


def test_delete_frf_analysis_view_invalidates_its_pending_panes(qtbot, monkeypatch):
    win, _fid, state, _time = _window_with_pair(qtbot)
    state.add_pane()
    win.analysis_managers["frf"].new_view()
    win.analysis_managers["frf"].set_active(0)
    invalidated = []
    monkeypatch.setattr(
        win._frf_coordinator,
        "invalidate_pane",
        lambda view_id, pane_idx: invalidated.append((view_id, pane_idx)),
    )

    win._on_analysis_delete("frf", 0)

    assert invalidated == [(state.view_id, 0), (state.view_id, 1)]


def test_display_change_does_not_invalidate_and_completion_uses_latest_params(
    qtbot, monkeypatch
):
    win, _fid, state, time = _window_with_pair(qtbot)
    canvas = win.chart_stack.page_frf.pane_canvas(0)
    invalidated = []
    rendered = []
    monkeypatch.setattr(
        win._frf_coordinator,
        "invalidate_pane",
        lambda view_id, pane_idx: invalidated.append((view_id, pane_idx)),
    )
    monkeypatch.setattr(
        canvas,
        "set_result",
        lambda result, *, display_params=None, context=None: rendered.append(
            dict(display_params or {})
        ),
    )

    win._on_frf_display_params_changed({"magnitude_scale": "linear"})
    win._on_frf_render_requested(
        {
            "view_id": state.view_id,
            "pane_idx": 0,
            "render_params": {"magnitude_scale": "db"},
        },
        _result(time, 1000.0),
        False,
    )

    assert invalidated == []
    assert rendered[-1]["magnitude_scale"] == "linear"


def test_view_in_time_reuses_exact_directional_pair_and_range(qtbot):
    win, fid, state, _time = _window_with_pair(qtbot)
    pane = state.panes[0]
    pane.time_range = (0.25, 1.25)
    state.params["range_mode"] = "manual"

    first = win._view_frf_pair_in_time_domain()
    win.view_manager.rename(first, "用户自定义名字")
    second = win._view_frf_pair_in_time_domain()
    assert first == second
    assert len(win.view_manager.views) == 2
    dedicated = win.view_manager.get(first)
    assert dedicated.name == "用户自定义名字"
    assert dedicated.checked == [(fid, "input"), (fid, "output")]
    assert dedicated.xlim == (0.25, 1.25)
    assert CustomXAxisSpec.from_axis_opts(
        dedicated.axis_opts.get("x_axis")
    ).mode == "time"

    state.panes[0].input_source = (fid, "output")
    state.panes[0].output_source = (fid, "input")
    third = win._view_frf_pair_in_time_domain()
    assert third != first
    assert win.view_manager.get(third).checked == [
        (fid, "output"),
        (fid, "input"),
    ]

    state.panes[0].input_source = (fid, "input")
    state.panes[0].output_source = (fid, "output")
    state.panes[0].time_range = (0.3, 1.25)
    fourth = win._view_frf_pair_in_time_domain()
    assert fourth not in {first, third}


def test_view_in_time_uses_common_effective_sample_crop_before_compute(qtbot):
    win, _fid, state, _time = _window_with_pair(qtbot)
    state.params["range_mode"] = "manual"
    state.panes[0].time_range = (0.2504, 1.2496)

    target = win._view_frf_pair_in_time_domain()

    assert target >= 0
    assert win.view_manager.get(target).xlim == (0.251, 1.249)


def test_view_in_time_rejects_cross_source_pair_without_creating_view(
    qtbot, monkeypatch
):
    win, _fid, state, time = _window_with_pair(qtbot)
    frame = pd.DataFrame({"output": np.cos(2 * np.pi * 20.0 * time)})
    win.files["source-b"] = FileData(
        "source-b.csv", frame, ["output"], {"output": "m/s2"}, fs=1000.0
    )
    win.files["source-b"].time_array = time
    state.panes[0].output_source = ("source-b", "output")
    messages = []
    monkeypatch.setattr(
        win, "toast", lambda message, level="info": messages.append((message, level))
    )
    before = len(win.view_manager.views)

    assert win._view_frf_pair_in_time_domain() == -1

    assert len(win.view_manager.views) == before
    assert any("同一个逻辑来源" in message for message, _level in messages)


def test_view_in_time_rejects_range_without_common_samples(qtbot, monkeypatch):
    win, _fid, state, _time = _window_with_pair(qtbot)
    state.params["range_mode"] = "manual"
    state.panes[0].time_range = (5.0, 6.0)
    messages = []
    monkeypatch.setattr(
        win, "toast", lambda message, level="info": messages.append((message, level))
    )

    assert win._view_frf_pair_in_time_domain() == -1

    assert any("共同" in message for message, _level in messages)


def test_restored_frf_view_dispatches_every_complete_pane_without_live_capture(
    qtbot, monkeypatch
):
    win, fid, state, _time = _window_with_pair(qtbot)
    state.add_pane()
    state.panes[1].input_source = (fid, "input")
    state.panes[1].output_source = (fid, "output")
    built = []
    requested = []
    monkeypatch.setattr(
        win,
        "_capture_active_analysis_view",
        lambda *_args, **_kwargs: pytest.fail("restore must not capture live combos"),
    )

    def fake_build(candidate_state, pane_idx, *, force=False):
        built.append((candidate_state.view_id, pane_idx, force))
        return {"view_id": candidate_state.view_id, "pane_idx": pane_idx}

    monkeypatch.setattr(win, "_build_frf_candidate", fake_build)
    monkeypatch.setattr(
        win._frf_coordinator,
        "request",
        lambda candidate: requested.append(candidate) or True,
    )

    win._recompute_restored_frf_view(state.view_id)

    assert built == [(state.view_id, 0, False), (state.view_id, 1, False)]
    assert [candidate["pane_idx"] for candidate in requested] == [0, 1]


def test_restore_pending_uses_stable_view_id_across_reorder(qapp, qtbot, monkeypatch):
    win, _fid, _state, _time = _window_with_pair(qtbot)
    manager = win.analysis_managers["frf"]
    target_idx = manager.new_view()
    target = manager.get(target_idx)
    target.panes[0].input_source = ("source-a", "input")
    target.panes[0].output_source = ("source-a", "output")
    win._analysis_restore_pending = {("frf", target.view_id)}
    dispatched = []
    monkeypatch.setattr(
        win,
        "_recompute_restored_frf_view",
        lambda view_id: dispatched.append(view_id),
    )

    win._render_analysis_view_from_cache("frf", target)
    manager.reorder(target_idx, 0)
    qapp.processEvents()

    assert dispatched == [target.view_id]


def test_frf_mode_does_not_enter_heatmap_levels_or_db_reference(qtbot, monkeypatch):
    win = MainWindow()
    qtbot.addWidget(win)
    touched = []
    monkeypatch.setattr(
        win, "_stamp_db_reference_nudge_facts", lambda section: touched.append(section)
    )

    win._on_mode_changed("frf")

    assert touched == []


def test_frf_file_invalidation_clears_pair_and_coordinator(qtbot, monkeypatch):
    win, fid, state, _time = _window_with_pair(qtbot)
    invalidated = []
    monkeypatch.setattr(
        win._frf_coordinator, "invalidate_fid", lambda value: invalidated.append(value)
    )

    win._remove_file_from_all_analysis_views(fid)
    win._invalidate_all_analysis_caches_for_fid(fid)

    pane = state.panes[0]
    assert pane.input_source is None and pane.output_source is None
    assert invalidated == [fid]


def test_project_restore_recomputes_directional_frf_pair(
    qapp, qtbot, tmp_path, monkeypatch
):
    time = np.arange(2000, dtype=float) / 1000.0
    csv_path = tmp_path / "pair.csv"
    pd.DataFrame({
        "time": time,
        "input": np.sin(2 * np.pi * 10 * time),
        "output": np.sin(2 * np.pi * 10 * time - 0.1),
    }).to_csv(csv_path, index=False)
    project = tmp_path / "pair.tlproj"

    source = MainWindow()
    qtbot.addWidget(source)
    source._load_one(str(csv_path))
    old_fid = next(iter(source.files))
    pane = source.analysis_managers["frf"].get(0).panes[0]
    pane.input_source = (old_fid, "input")
    pane.output_source = (old_fid, "output")
    # Use the real toolbar/card path: saving captures live controls back to
    # state, so a bare field assignment would intentionally be overwritten.
    source.chart_stack.page_frf._cards[0].set_cursor_mode("single")
    source.save_project(project)

    restored = MainWindow()
    qtbot.addWidget(restored)
    recomputed = []
    monkeypatch.setattr(
        restored,
        "_recompute_restored_frf_view",
        lambda view_id: recomputed.append(view_id),
    )
    restored.open_project(project)
    qapp.processEvents()

    new_fid = next(iter(restored.files))
    restored_pane = restored.analysis_managers["frf"].get(0).panes[0]
    assert restored_pane.input_source == (new_fid, "input")
    assert restored_pane.output_source == (new_fid, "output")
    assert restored_pane.cursor_mode == "single"
    restored.toolbar._set_mode("frf")
    assert restored.chart_stack.page_frf._cards[0].cursor_mode() == "single"
    assert restored.analysis_managers["frf"].get(0).view_id in recomputed


def test_project_restore_dispatches_each_complete_frf_pane(
    qapp, qtbot, tmp_path, monkeypatch
):
    time = np.arange(4000, dtype=float) / 1000.0
    csv_path = tmp_path / "split-pair.csv"
    pd.DataFrame({
        "time": time,
        "input": np.sin(2 * np.pi * 10 * time),
        "output": np.sin(2 * np.pi * 10 * time - 0.1),
    }).to_csv(csv_path, index=False)
    project = tmp_path / "split-pair.tlproj"

    source = MainWindow()
    qtbot.addWidget(source)
    source._load_one(str(csv_path))
    old_fid = next(iter(source.files))
    state = source.analysis_managers["frf"].get(0)
    state.panes[0].input_source = (old_fid, "input")
    state.panes[0].output_source = (old_fid, "output")
    assert state.add_pane() is True
    state.panes[1].input_source = (old_fid, "input")
    state.panes[1].output_source = (old_fid, "output")
    source.save_project(project)

    restored = MainWindow()
    qtbot.addWidget(restored)
    requested = []
    monkeypatch.setattr(
        restored._frf_coordinator,
        "request",
        lambda candidate: requested.append(candidate) or True,
    )
    restored.open_project(project)
    qapp.processEvents()

    restored_state = restored.analysis_managers["frf"].get(0)
    assert [candidate["pane_idx"] for candidate in requested] == [0, 1]
    assert {candidate["view_id"] for candidate in requested} == {
        restored_state.view_id
    }


def test_project_restore_does_not_relabel_generated_axis_as_real(
    qapp, qtbot, tmp_path, monkeypatch
):
    csv_path = tmp_path / "generated.csv"
    pd.DataFrame({
        "input": np.arange(4000, dtype=float),
        "output": np.arange(4000, dtype=float) * 2.0,
    }).to_csv(csv_path, index=False)
    project = tmp_path / "generated.tlproj"

    source = MainWindow()
    qtbot.addWidget(source)
    source._load_one(str(csv_path))
    old_fid = next(iter(source.files))
    assert source.files[old_fid]._time_source == "generated"
    pane = source.analysis_managers["frf"].get(0).panes[0]
    pane.input_source = (old_fid, "input")
    pane.output_source = (old_fid, "output")
    source.save_project(project)

    restored = MainWindow()
    qtbot.addWidget(restored)
    monkeypatch.setattr(restored, "_recompute_analysis_section", lambda _section: None)
    restored.open_project(project)
    qapp.processEvents()

    new_fid = next(iter(restored.files))
    assert restored.files[new_fid]._time_source == "generated"
    with pytest.raises(FrfPreflightError, match="真实时间轴"):
        restored._build_frf_candidate(
            restored.analysis_managers["frf"].get(0), 0
        )


def test_project_restore_preserves_explicit_manual_time_axis(
    qapp, qtbot, tmp_path, monkeypatch
):
    csv_path = tmp_path / "manual.csv"
    pd.DataFrame({
        "input": np.arange(4000, dtype=float),
        "output": np.arange(4000, dtype=float) * 2.0,
    }).to_csv(csv_path, index=False)
    project = tmp_path / "manual.tlproj"

    source = MainWindow()
    qtbot.addWidget(source)
    source._load_one(str(csv_path))
    old_fid = next(iter(source.files))
    source.files[old_fid].rebuild_time_axis(2000.0)
    assert source.files[old_fid]._time_source == "manual"
    source.save_project(project)

    restored = MainWindow()
    qtbot.addWidget(restored)
    monkeypatch.setattr(restored, "_recompute_analysis_section", lambda _section: None)
    restored.open_project(project)
    qapp.processEvents()

    new_fid = next(iter(restored.files))
    assert restored.files[new_fid]._time_source == "manual"
    assert restored.files[new_fid].fs == pytest.approx(2000.0)


def test_frf_completion_publishes_resident_effective_facts_and_warnings(qtbot):
    """spec §5.3/§13: a real low-segment run must leave a resident warning."""
    from mf4_analyzer.signal.frf import FrfParams, compute_frf

    win, fid, state, time = _window_with_pair(qtbot)
    win.toolbar._set_mode("frf")
    ctx = win.inspector.frf_ctx
    # 2000 samples @ 1 kHz with 1 s segments and no overlap = exactly 2 segments.
    ctx.apply_params({"t_win_s": 1.0, "overlap": 0.0}, emit_changes=True)
    frame = win.files[fid].data
    result = compute_frf(
        frame["input"].to_numpy(),
        frame["output"].to_numpy(),
        fs=1000.0,
        params=FrfParams(**ctx.compute_params()),
        input_time=time,
        output_time=time,
    )
    assert result.effective.segments == 2
    assert any("2 complete segments" in warning for warning in result.warnings)
    _seed_frf_cache(win, state, 0, result)

    assert win.do_frf() is False  # served synchronously from the cache

    facts = ctx.effective_facts_text()
    assert "实际 Fs" in facts and "1000 Hz" in facts
    assert "完整段数" in facts
    assert "有效时间范围" in facts
    assert "最大时间抖动" in facts
    assert "无效频点" in facts
    assert "only 2 complete segments" in ctx.effective_warnings_text()
    assert not ctx.effective_facts_is_stale()


def test_frf_fresh_and_cached_renders_both_fill_the_inspector_facts(qtbot):
    win, _fid, state, time = _window_with_pair(qtbot)
    ctx = win.inspector.frf_ctx

    for cache_hit in (False, True):
        ctx.clear_effective_facts()
        win._on_frf_render_requested(
            {"view_id": state.view_id, "pane_idx": 0},
            _result(
                time,
                1000.0,
                segments=2,
                warnings=(
                    "statistical stability is low: only 2 complete segments",
                ),
            ),
            cache_hit,
        )

        assert "完整段数" in ctx.effective_facts_text()
        assert "only 2 complete segments" in ctx.effective_warnings_text()


def test_frf_display_only_change_leaves_the_effective_facts_untouched(qtbot):
    win, _fid, state, time = _window_with_pair(qtbot)
    ctx = win.inspector.frf_ctx
    win._on_frf_render_requested(
        {"view_id": state.view_id, "pane_idx": 0}, _result(time, 1000.0), False
    )
    before = ctx.effective_facts_text()
    assert before

    win._on_frf_display_params_changed({"magnitude_scale": "linear"})

    assert ctx.effective_facts_text() == before
    assert not ctx.effective_facts_is_stale()


def test_frf_compute_param_change_marks_the_effective_facts_stale(qtbot):
    win, _fid, state, time = _window_with_pair(qtbot)
    ctx = win.inspector.frf_ctx
    win._on_frf_render_requested(
        {"view_id": state.view_id, "pane_idx": 0}, _result(time, 1000.0), False
    )

    win._on_frf_compute_params_changed({"t_win_s": 1.0})

    facts = ctx.effective_facts_text()
    assert ctx.effective_facts_is_stale()
    assert "（已过期）" in facts
    assert "完整段数" in facts  # the previous numbers stay readable


def test_frf_focus_switch_follows_each_panes_effective_facts(qtbot):
    win, fid, state, time = _window_with_pair(qtbot)
    ctx = win.inspector.frf_ctx
    page = win.chart_stack.page_frf
    state.add_pane()
    page.enter_split()
    state.panes[1].input_source = (fid, "input")
    state.panes[1].output_source = (fid, "output")
    _seed_frf_cache(win, state, 0, _result(time, 1000.0))
    win._on_frf_render_requested(
        {"view_id": state.view_id, "pane_idx": 0}, _result(time, 1000.0), True
    )
    assert "完整段数" in ctx.effective_facts_text()

    page.set_focused_index(1)
    assert ctx.effective_facts_text() == ""  # pane 1 never computed

    page.set_focused_index(0)
    assert "完整段数" in ctx.effective_facts_text()


def test_switching_to_a_frf_view_without_results_clears_the_facts_card(qtbot):
    win, _fid, state, time = _window_with_pair(qtbot)
    ctx = win.inspector.frf_ctx
    win._on_frf_render_requested(
        {"view_id": state.view_id, "pane_idx": 0}, _result(time, 1000.0), False
    )
    assert ctx.effective_facts_text()

    manager = win.analysis_managers["frf"]
    manager.set_active(manager.new_view())

    assert ctx.effective_facts_text() == ""
