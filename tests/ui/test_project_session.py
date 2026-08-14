# tests/ui/test_project_session.py
import pytest

from mf4_analyzer import app_meta


def test_app_meta_constants():
    assert app_meta.APP_VERSION == "v7.9.9"
    assert app_meta.WINDOW_TITLE == "TraceLab v7.9.9"
    assert app_meta.RELEASE_URL.startswith("https://")


def test_window_title_uses_app_meta(qapp):
    from mf4_analyzer.ui.main_window import MainWindow
    mw = MainWindow()
    assert mw.windowTitle() == app_meta.WINDOW_TITLE


import csv
import json


def _write_csv(path, n=40):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "rpm"])
        for i in range(n):
            w.writerow([i / 100.0, float(i)])


def _write_frf_csv(path, n=2_000):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "input", "output"])
        for i in range(n):
            w.writerow([i / 1_000.0, float(i % 13), float((i + 3) % 17)])


def _drain_analysis_restore(qapp, win, rounds=80):
    """Pump the one-View-per-tick restore queue until the bar is released."""
    for _ in range(rounds):
        qapp.processEvents()
        queue = getattr(win, "_analysis_restore_queue", None) or []
        token = win._analysis_jobs.progress_token("restore")
        busy = any(
            win._analysis_jobs.is_busy(section)
            for section in ("fft_time", "order", "frf")
        )
        if not queue and token is None and not busy:
            return
    raise AssertionError("analysis restore did not finish")


def test_save_project_writes_file(qapp, tmp_path):
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui import project_io as pio
    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    mw = MainWindow()
    mw._load_one(str(csv_a))
    mw.view_manager.rename(0, "主视图")
    proj = tmp_path / "s.tlproj"
    mw.save_project(proj)

    doc = pio.load_project_from_json(proj)
    assert [f.path_abs for f in doc.files] == [str(csv_a.resolve())]
    assert doc.files[0].path_rel == "a.csv"
    assert doc.views[0]["name"] == "主视图"
    assert doc.current_mode == "time"


def test_open_project_roundtrip(qapp, tmp_path):
    from mf4_analyzer.ui.main_window import MainWindow
    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    csv_b = tmp_path / "b.csv"; _write_csv(csv_b)
    proj = tmp_path / "s.tlproj"

    mw = MainWindow()
    mw._load_one(str(csv_a))
    mw._load_one(str(csv_b))
    mw.view_manager.rename(0, "主视图")
    mw.save_project(proj)

    mw2 = MainWindow()
    mw2.open_project(proj)
    assert [fd.filename for fd in mw2.files.values()] == ["a.csv", "b.csv"]
    assert mw2.view_manager.views[0].name == "主视图"
    assert mw2.chart_stack.current_mode() == "time"


def test_open_project_migrates_legacy_frf_range_to_explicit_seconds(qapp, tmp_path):
    from mf4_analyzer.ui.main_window import MainWindow

    csv_a = tmp_path / "frf.csv"
    project = tmp_path / "legacy-frf-range.tlproj"
    _write_frf_csv(csv_a)
    window = MainWindow()
    window._load_one(str(csv_a))
    fid = next(iter(window.files))
    pane = window.analysis_managers["frf"].get(0).panes[0]
    pane.input_source = (fid, "input")
    pane.output_source = (fid, "output")
    pane.time_range = (0.25, 0.75)
    window.save_project(project)

    payload = json.loads(project.read_text(encoding="utf-8"))
    payload["current_mode"] = "frf"
    frf_view = payload["analysis_views"]["frf"]["views"][0]
    frf_view["schema"] = 5
    frf_view["params"]["range_mode"] = "current_time"
    frf_view["panes"][0]["time_range"] = [0.25, 0.75]
    frf_view["panes"][0]["source_time_view_id"] = "legacy-time-view"
    project.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    restored = MainWindow()
    restored.open_project(project)

    assert restored.inspector.top.range_enabled()
    assert restored.inspector.top.range_values() == (0.25, 0.75)
    restored_pane = restored.analysis_managers["frf"].get(0).panes[0]
    assert restored_pane.time_range == (0.25, 0.75)
    assert restored_pane.source_time_view_id is None

    rewritten = tmp_path / "rewritten.tlproj"
    restored.save_project(rewritten)
    rewritten_frf = json.loads(rewritten.read_text(encoding="utf-8"))[
        "analysis_views"
    ]["frf"]["views"][0]
    assert "range_mode" not in rewritten_frf["params"]
    assert "source_time_view_id" not in rewritten_frf["panes"][0]


def test_project_roundtrip_preserves_per_source_name_xaxis(qapp, tmp_path):
    from mf4_analyzer.ui import project_io as pio
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui.time_xaxis import CustomXAxisSpec

    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    project = tmp_path / "logical-x.tlproj"
    window = MainWindow()
    window._load_one(str(csv_a))
    window._custom_xaxis_spec = CustomXAxisSpec(
        mode="channel",
        resolver="per_source_name",
        source_fid=None,
        channel="rpm",
        label="Speed",
    )
    window._custom_xaxis_fid = None
    window._custom_xaxis_ch = None
    window._custom_xlabel = "Speed"
    window._capture_current_view()

    window.save_project(project)
    saved = pio.load_project_from_json(project)

    assert saved.views[0]["axis_opts"]["x_axis"] == {
        "mode": "channel",
        "resolver": "per_source_name",
        "fid": None,
        "channel": "rpm",
        "label": "Speed",
    }

    restored = MainWindow()
    restored.open_project(project)

    assert restored._custom_xaxis_spec == CustomXAxisSpec(
        mode="channel",
        resolver="per_source_name",
        source_fid=None,
        channel="rpm",
        label="Speed",
    )


def test_open_project_migrates_legacy_xaxis_to_remapped_exact_source(
    qapp, tmp_path,
):
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui.time_xaxis import CustomXAxisSpec

    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    project = tmp_path / "legacy-x.tlproj"
    window = MainWindow()
    window._load_one(str(csv_a))
    old_fid = next(iter(window.files))
    window.save_project(project)
    payload = json.loads(project.read_text(encoding="utf-8"))
    payload["views"][0].setdefault("axis_opts", {})["x_axis"] = {
        "mode": "channel",
        "fid": old_fid,
        "channel": "rpm",
        "label": "Legacy speed",
    }
    project.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    restored = MainWindow()
    restored.open_project(project)
    new_fid = next(iter(restored.files))

    assert restored._custom_xaxis_spec == CustomXAxisSpec(
        mode="channel",
        resolver="exact_source",
        source_fid=new_fid,
        channel="rpm",
        label="Legacy speed",
    )


def test_project_roundtrip_restores_timedomain_attached_file_subset(
    qapp, tmp_path
):
    from mf4_analyzer.ui.main_window import MainWindow

    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    csv_b = tmp_path / "b.csv"; _write_csv(csv_b)
    project = tmp_path / "subset.tlproj"
    window = MainWindow()
    window._load_one(str(csv_a))
    window._load_one(str(csv_b))
    _fid_a, fid_b = list(window.files)
    window.view_manager.get(0).attached_file_ids = [fid_b]
    window._project_view_controls(0)

    window.save_project(project)
    restored = MainWindow()
    restored.open_project(project)
    qapp.processEvents()

    restored_b = next(
        fid for fid, fd in restored.files.items() if fd.filename == "b.csv"
    )
    restored_a = next(
        fid for fid, fd in restored.files.items() if fd.filename == "a.csv"
    )
    assert restored.view_manager.get(0).attached_file_ids == [restored_b]
    assert restored.navigator.get_attached_file_ids() == [restored_b]
    assert restored.channel_list._file_items[restored_a].isHidden()
    assert not restored.channel_list._file_items[restored_b].isHidden()


def test_project_roundtrip_preserves_explicit_empty_view(qapp, tmp_path):
    from mf4_analyzer.ui.main_window import MainWindow

    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    project = tmp_path / "empty.tlproj"
    window = MainWindow()
    window._load_one(str(csv_a))
    window.view_manager.get(0).attached_file_ids = []
    window._project_view_controls(0)
    window.save_project(project)

    restored = MainWindow()
    restored.open_project(project)
    restored.show()
    qapp.processEvents()

    assert restored.view_manager.get(0).attached_file_ids == []
    assert restored.navigator.get_attached_file_ids() == []
    assert restored.channel_list.empty_state.isVisible()


def test_legacy_project_without_attachment_field_attaches_restored_files(
    qapp, tmp_path
):
    from mf4_analyzer.ui.main_window import MainWindow

    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    csv_b = tmp_path / "b.csv"; _write_csv(csv_b)
    project = tmp_path / "legacy.tlproj"
    window = MainWindow()
    window._load_one(str(csv_a))
    window._load_one(str(csv_b))
    window.save_project(project)
    payload = json.loads(project.read_text(encoding="utf-8"))
    for view in payload["views"]:
        view.pop("attached_file_ids", None)
    project.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    restored = MainWindow()
    restored.open_project(project)

    assert restored.view_manager.get(0).attached_file_ids == list(restored.files)
    assert restored.navigator.get_attached_file_ids() == list(restored.files)


def test_project_roundtrip_restores_timedomain_hidden_channels(qapp, tmp_path):
    from mf4_analyzer.ui.main_window import MainWindow

    csv_a = tmp_path / "a.csv"
    _write_csv(csv_a)
    proj = tmp_path / "visibility.tlproj"

    mw = MainWindow()
    mw._load_one(str(csv_a))
    fid = next(iter(mw.files))
    mw.navigator.set_checked_channels([(fid, "rpm")])
    mw.navigator.set_hidden_channels([(fid, "rpm")])
    mw._capture_current_view()
    mw.save_project(proj)

    restored = MainWindow()
    restored.open_project(proj)
    qapp.processEvents()

    restored_fid = next(iter(restored.files))
    assert restored.view_manager.get(0).hidden_channels == [
        (restored_fid, "rpm")
    ]
    assert restored.navigator.get_hidden_channels() == [(restored_fid, "rpm")]
    assert restored.canvas_time.axes_list == []
    assert restored.canvas_time._empty_hint_text == (
        "已选择 1 个通道，当前均已隐藏"
    )


def test_project_roundtrip_restores_time_filter_state(qapp, tmp_path):
    from mf4_analyzer.signal.filters import FilterSpec
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui import project_io as pio

    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    proj = tmp_path / "s.tlproj"

    mw = MainWindow()
    mw._load_one(str(csv_a))
    panel = mw.inspector.filter_panel
    panel.set_enabled(True)
    panel.set_kind("带通")
    panel.set_band(5.0, 30.0)
    panel.set_order(6)
    panel.chk_orig.setChecked(False)
    panel.chk_filt.setChecked(True)
    mw.save_project(proj)

    doc = pio.load_project_from_json(proj)
    assert doc.filter == {
        "enabled": True,
        "spec": FilterSpec("band", order=6, cutoff_lo=5.0, cutoff_hi=30.0).to_dict(),
        "show_original": False,
        "show_filtered": True,
    }

    mw2 = MainWindow()
    mw2.open_project(proj)
    restored = mw2.inspector.filter_panel
    assert restored.is_enabled() is True
    assert restored.filter_spec() == FilterSpec(
        "band", order=6, cutoff_lo=5.0, cutoff_hi=30.0
    )
    assert restored.show_original() is False
    assert restored.show_filtered() is True


def test_save_project_in_fft_mode_preserves_time_view_scope(qapp, tmp_path):
    """A1: saving while FFT is active must not overwrite Time View 1.

    ``_capture_focused_view`` used to read the analysis-projected navigator and
    write its attachments/checked/colors into the focused time View — corrupting
    the ``.tlproj``. Guard lives inside ``_capture_focused_view`` itself.
    """
    from mf4_analyzer.ui.main_window import MainWindow

    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    csv_b = tmp_path / "b.csv"; _write_csv(csv_b)
    proj = tmp_path / "a1-scope.tlproj"

    mw = MainWindow()
    mw._load_one(str(csv_a))
    mw._load_one(str(csv_b))
    fid_a, fid_b = list(mw.files)

    tv = mw.view_manager.get(0)
    tv.attached_file_ids = [fid_a]
    tv.checked = [(fid_a, "rpm")]
    tv.colors = {(fid_a, "rpm"): "#ff0000"}
    mw._project_view_controls(0)

    mw.chart_stack.set_mode("fft")
    mw.inspector.set_mode("fft")
    fft_state = mw.analysis_managers["fft"].get(0)
    fft_state.attached_file_ids = [fid_b]
    mw._project_analysis_attachments("fft", fft_state)

    expected_attached = list(tv.attached_file_ids)
    expected_checked = list(tv.checked)
    expected_colors = dict(tv.colors)

    mw.save_project(proj)

    tv_after = mw.view_manager.get(0)
    assert tv_after.attached_file_ids == expected_attached
    assert tv_after.checked == expected_checked
    assert tv_after.colors == expected_colors

    doc = json.loads(proj.read_text(encoding="utf-8"))
    saved_view = doc["views"][0]
    assert saved_view["attached_file_ids"] == expected_attached
    assert [tuple(row) for row in saved_view["checked"]] == expected_checked


def test_open_project_restores_non_time_mode_consistently(qapp, tmp_path):
    # Reopening a project saved in a non-time mode must leave the chart,
    # the toolbar segment, and the inspector all agreeing on that mode —
    # not just the chart canvas (regression guard for the open_project
    # mode-restore path going through toolbar._set_mode).
    from mf4_analyzer.ui.main_window import MainWindow
    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    proj = tmp_path / "s.tlproj"

    mw = MainWindow()
    mw._load_one(str(csv_a))
    mw.chart_stack.set_mode("fft")
    mw.save_project(proj)

    mw2 = MainWindow()
    mw2.open_project(proj)
    assert mw2.chart_stack.current_mode() == "fft"
    assert mw2.toolbar.current_mode() == "fft"
    assert "频谱 · View 1" in mw2.navigator.channel_list.empty_state.text()


def test_open_project_keeps_analysis_empty_owner_after_time_view_restore(
        qapp, tmp_path):
    """The final Time-view restore must not overwrite a visible analysis owner."""
    from mf4_analyzer.ui.main_window import MainWindow
    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    proj = tmp_path / "analysis-owner.tlproj"

    mw = MainWindow()
    mw._load_one(str(csv_a))
    assert mw.view_manager.new_view() == 1
    mw.toolbar._set_mode("frf")
    assert mw.analysis_managers["frf"].new_view() == 1
    mw.save_project(proj)

    mw2 = MainWindow()
    mw2.open_project(proj)

    assert mw2.chart_stack.current_mode() == "frf"
    assert mw2.view_manager.active == 1
    assert mw2.analysis_managers["frf"].active == 1
    assert "FRF · View 2" in mw2.navigator.channel_list.empty_state.text()


def test_open_project_auto_recomputes_source_bearing_analysis_views(
        qapp, tmp_path, monkeypatch):
    """Recompute-on-open: a saved project stores each analysis view's params +
    sources but NOT the numeric results, so opening it must auto-recompute every
    view that has sources (and leave source-less views alone)."""
    from mf4_analyzer.ui.analysis_view_state import AnalysisViewState, PaneState
    from mf4_analyzer.ui.main_window import MainWindow
    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    proj = tmp_path / "s.tlproj"

    mw = MainWindow()
    mw._load_one(str(csv_a))
    fid = next(iter(mw.files))
    # Give the Order view a source while the app is in 'time' mode — save then
    # preserves these sources (capture_sources only re-reads the navigator for
    # the CURRENT mode). Seed two FFT views so open must dispatch both, not
    # only the active tab. Mutate the manager list directly so set_active
    # cannot rewrite the shared Time/FFT navigator mid-setup.
    mw.analysis_managers['order'].get(0).panes[0].sources = [(fid, 'rpm')]
    fft_mgr = mw.analysis_managers['fft']
    fft_mgr.get(0).panes[0].sources = [(fid, 'rpm')]
    fft_mgr.get(0).attached_file_ids = [fid]
    fft_mgr.views.append(AnalysisViewState(
        name="FFT 2",
        tab_color=fft_mgr.get(0).tab_color,
        panes=[PaneState(sources=[(fid, 'rpm')])],
        attached_file_ids=[fid],
    ))
    mw.save_project(proj)

    mw2 = MainWindow()
    recomputed = []
    monkeypatch.setattr(
        type(mw2), '_recompute_restored_analysis_view',
        lambda self, section, view_id: recomputed.append((section, view_id)),
    )
    mw2.open_project(proj)
    assert recomputed == []
    assert mw2._analysis_jobs.progress_token("restore") is not None
    assert "恢复分析" in (mw2._compute_progress._full_label or "")
    assert len(mw2._analysis_restore_queue) == 3
    _drain_analysis_restore(qapp, mw2)

    sections = {section for section, _view_id in recomputed}
    assert 'order' in sections, "source-bearing Order view must auto-recompute"
    fft_ids = [view_id for section, view_id in recomputed if section == 'fft']
    assert len(fft_ids) == 2, "every source-bearing FFT View must recompute"
    assert set(fft_ids) == {v.view_id for v in mw2.analysis_managers['fft'].views}
    assert 'fft_time' not in sections, "source-less FFT-vs-Time must NOT recompute"
    assert mw2._analysis_jobs.progress_token("restore") is None


def test_open_project_recomputes_inactive_fft_view_without_clicking_compute(
        qapp, tmp_path, qtbot):
    """Opening a project must refill every FFT View's cache so switching tabs
    shows the restored spectrum without pressing 计算."""
    from mf4_analyzer.ui.analysis_view_state import AnalysisViewState, PaneState
    from mf4_analyzer.ui.main_window import MainWindow
    csv_a = tmp_path / "a.csv"
    _write_csv(csv_a, n=256)
    proj = tmp_path / "multi_fft.tlproj"

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._load_one(str(csv_a))
    fid = next(iter(mw.files))
    fft_mgr = mw.analysis_managers["fft"]
    fft_mgr.get(0).panes[0].sources = [(fid, "rpm")]
    fft_mgr.get(0).attached_file_ids = [fid]
    fft_mgr.views.append(AnalysisViewState(
        name="FFT 2",
        tab_color=fft_mgr.get(0).tab_color,
        panes=[PaneState(sources=[(fid, "rpm")])],
        attached_file_ids=[fid],
    ))
    mw.save_project(proj)

    mw2 = MainWindow()
    qtbot.addWidget(mw2)
    mw2.open_project(proj)
    _drain_analysis_restore(qapp, mw2)

    fft_mgr2 = mw2.analysis_managers["fft"]
    assert len(fft_mgr2.views) == 2
    mw2.toolbar._set_mode("fft")
    qapp.processEvents()
    canvas = mw2.chart_stack.page_fft.pane_canvas(0)
    assert len(canvas._amp_curves) >= 1
    other = 1 - fft_mgr2.active
    fft_mgr2.set_active(other)
    qapp.processEvents()
    assert len(canvas._amp_curves) >= 1


def test_fft_inspector_signal_is_saved_and_recomputed_on_open(
        qapp, tmp_path, qtbot):
    """Inspector 单信号 (no navigator ticks) must persist as pane.sources so
    reopen can recompute instead of showing an empty '未选通道' chart."""
    from mf4_analyzer.ui.main_window import MainWindow
    csv_a = tmp_path / "a.csv"
    _write_csv(csv_a, n=256)
    proj = tmp_path / "fft_single.tlproj"

    mw = MainWindow()
    qtbot.addWidget(mw)
    mw._load_one(str(csv_a))
    fid = next(iter(mw.files))
    mw.toolbar._set_mode("fft")
    mw._attach_files_to_active_context([fid])
    mw.navigator.set_checked_channels([])
    mw.inspector.fft_ctx.set_signal_candidates([("rpm", (fid, "rpm"))])
    mw.inspector.fft_ctx.combo_sig.setCurrentIndex(0)
    mw._capture_active_analysis_view("fft")
    assert mw.analysis_managers["fft"].get(0).panes[0].sources == [(fid, "rpm")]
    mw.save_project(proj)

    mw2 = MainWindow()
    qtbot.addWidget(mw2)
    mw2.open_project(proj)
    _drain_analysis_restore(qapp, mw2)
    restored = mw2.analysis_managers["fft"].get(0).panes[0].sources
    assert restored and restored[0][1] == "rpm"
    mw2.toolbar._set_mode("fft")
    qapp.processEvents()
    canvas = mw2.chart_stack.page_fft.pane_canvas(0)
    assert len(canvas._amp_curves) >= 1


def test_open_project_multi_group_hdf_no_duplication(qapp, tmp_path):
    """Regression: a 2-group .hdf must reload as 2 groups (not 4) on open_project.

    Bug: open_project called _load_one once per ProjectFileRef, so a 2-group
    .hdf with 2 refs → 2× _load_one → 4 groups. The fix deduplicates by path
    and assigns new fids in order from a single _load_one call.
    """
    import numpy as np
    from tests._helpers.head_hdf_factory import write_head_hdf
    from mf4_analyzer.ui.main_window import MainWindow

    n_scans = 8
    fast_samples = np.arange(n_scans * 2, dtype=float)  # factor 2, label_suffix "2x"
    slow_samples = np.arange(n_scans, dtype=float) * 5.0  # factor 1, label_suffix "1x"
    hdf = write_head_hdf(
        tmp_path / "synth.hdf",
        n_scans=n_scans,
        start_of_data=4096,
        channels=[
            {"name": "Accel", "factor": 2, "quantity": "acceleration",
             "unit": "m/s^2", "calibration": 1.0, "samples": fast_samples},
            {"name": "Speed", "factor": 1, "quantity": "speed of rotation",
             "unit": "deg/s", "calibration": 1.0, "samples": slow_samples},
        ],
    )

    mw = MainWindow()
    mw._load_one(str(hdf))
    assert len(mw.files) == 2, "sanity: _load_one of a 2-group .hdf must yield 2 FileData"
    assert mw.view_manager.get(0).attached_file_ids == list(mw.files)

    proj = tmp_path / "multi.tlproj"
    mw.save_project(proj)

    mw2 = MainWindow()
    mw2.open_project(proj)

    # THE regression: buggy code gives 4 (two _load_one calls × 2 groups each)
    assert len(mw2.files) == 2, (
        f"expected 2 groups after roundtrip, got {len(mw2.files)} — "
        "likely double-load bug in open_project"
    )
    suffixes = {fd.label_suffix for fd in mw2.files.values()}
    assert suffixes == {"2x", "1x"}, f"wrong label_suffixes after roundtrip: {suffixes}"
    assert mw2.view_manager.get(0).attached_file_ids == list(mw2.files)
    for fid, fd in mw2.files.items():
        assert fd.fs > 0, f"fid {fid} has non-positive fs={fd.fs}"


def test_project_roundtrip_restores_blf_dbc_binding_without_picker(
        qapp, tmp_path, monkeypatch):
    pytest.importorskip("can", reason="python-can not installed (win32-gated)")
    pytest.importorskip("cantools", reason="cantools not installed")

    from PyQt5.QtCore import QSettings
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui import project_io as pio
    from tests._helpers.blf_factory import write_sample_blf, write_two_message_dbc

    settings = QSettings(str(tmp_path / "recent-dbc.ini"), QSettings.IniFormat)
    settings.clear()
    monkeypatch.setattr(
        MainWindow,
        "_blf_dbc_settings",
        lambda self: settings,
        raising=False,
    )

    dbc_dir = tmp_path / "dbc"
    dbc_dir.mkdir()
    dbc = write_two_message_dbc(dbc_dir / "bus.dbc")
    blf = write_sample_blf(tmp_path / "log.blf", n=5)
    proj = tmp_path / "s.tlproj"

    mw = MainWindow()
    monkeypatch.setattr(
        mw,
        "_ask_open_blf_dbc_dialog",
        lambda *args, **kwargs: True,
        raising=False,
    )
    monkeypatch.setattr(mw, "_prompt_blf_dbc", lambda path: [str(dbc)])
    mw._load_one(str(blf))
    mw.save_project(proj)

    doc = pio.load_project_from_json(proj)
    assert doc.files[0].dbc_refs

    settings.clear()
    settings.sync()

    mw2 = MainWindow()
    monkeypatch.setattr(
        mw2,
        "_ask_open_blf_dbc_dialog",
        lambda *args, **kwargs: False,
        raising=False,
    )

    def fail_if_picker_opens(path):
        raise AssertionError("project DBC binding should load without re-picking")

    monkeypatch.setattr(mw2, "_prompt_blf_dbc", fail_if_picker_opens)
    mw2.open_project(proj)

    assert len(mw2.files) == 1
    fd = next(iter(mw2.files.values()))
    assert "EngineSpeed" in fd.channels
    assert fd.source_metadata["dbc_paths"] == [str(dbc.resolve())]


def test_open_project_skips_missing(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    from PyQt5.QtWidgets import QMessageBox
    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    csv_b = tmp_path / "b.csv"; _write_csv(csv_b)
    proj = tmp_path / "s.tlproj"

    mw = MainWindow()
    mw._load_one(str(csv_a))
    mw._load_one(str(csv_b))
    mw.save_project(proj)
    csv_b.unlink()  # make one file missing

    warned = {}
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warned.setdefault("hit", True))
    mw2 = MainWindow()
    mw2.open_project(proj)
    assert [fd.filename for fd in mw2.files.values()] == ["a.csv"]
    assert warned.get("hit") is True
    health = mw2._project_restore_health
    assert health.degraded is True
    assert health.missing_paths
    assert health.missing_old_fids


def test_degraded_project_save_clears_health_after_confirm(qapp, tmp_path, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    from PyQt5.QtWidgets import QMessageBox

    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    csv_b = tmp_path / "b.csv"; _write_csv(csv_b)
    proj = tmp_path / "s.tlproj"

    mw = MainWindow()
    mw._load_one(str(csv_a))
    mw._load_one(str(csv_b))
    mw.save_project(proj)
    csv_b.unlink()

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    restored = MainWindow()
    restored.open_project(proj)
    assert restored._project_restore_health.degraded is True

    confirmed = []
    monkeypatch.setattr(
        restored,
        "_confirm_degraded_project_save",
        lambda *a, **k: confirmed.append(True) or True,
    )
    out = tmp_path / "rewritten.tlproj"
    assert restored.save_project(out) is True
    assert confirmed == [True]
    assert restored._project_restore_health.degraded is False
    assert out.is_file()


def test_project_roundtrip_preserves_per_channel_ylims(qapp, tmp_path):
    """A3: ylims keys embed fid; remap_view_fids must rewrite them on reopen.

    Same-window reopen advances ``_fc`` so the remapped fid differs from the
    saved one — the only way this assertion stays red until remapping lands.
    """
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui.pg_canvas._shared import _view_state_channel_key

    csv_a = tmp_path / "a.csv"
    _write_csv(csv_a, n=200)
    proj = tmp_path / "ylims-roundtrip.tlproj"

    mw = MainWindow()
    mw.resize(1200, 800)
    mw.show()
    qapp.processEvents()
    mw._load_one(str(csv_a))
    old_fid = next(iter(mw.files))
    mw.navigator.set_checked_channels([(old_fid, "rpm")])
    mw.plot_time()
    qapp.processEvents()

    plotted = mw.canvas_time.get_visible_ylims()
    assert plotted, "expected rpm subplot after plot_time"
    # ylims keys use the on-canvas display name (``[short] channel``), not the
    # bare navigator channel id — take the live key rather than reconstructing.
    old_key = next(iter(plotted))
    assert json.loads(old_key)[0] == old_fid
    lo, hi = plotted[old_key]
    span = hi - lo if hi > lo else 1.0
    saved_ylim = (lo + span * 0.2, hi - span * 0.2)
    mw.canvas_time.restore_visible_ylims({old_key: saved_ylim})
    qapp.processEvents()
    assert mw.canvas_time.get_visible_ylims()[old_key] == pytest.approx(saved_ylim)
    mw._capture_current_view()
    assert mw.view_manager.get(0).ylims[old_key] == pytest.approx(saved_ylim)
    mw.save_project(proj)

    payload = json.loads(proj.read_text(encoding="utf-8"))
    assert old_key in payload["views"][0]["ylims"]
    assert payload["views"][0]["ylims"][old_key] == pytest.approx(list(saved_ylim))

    mw.open_project(proj)
    qapp.processEvents()

    new_fid = next(iter(mw.files))
    assert new_fid != old_fid
    _, channel_name = json.loads(old_key)
    new_key = _view_state_channel_key(new_fid, channel_name)
    assert old_key not in mw.view_manager.get(0).ylims
    assert mw.view_manager.get(0).ylims.get(new_key) == pytest.approx(saved_ylim)
    assert mw.canvas_time.get_visible_ylims().get(new_key) == pytest.approx(
        saved_ylim
    )


def test_viewstate_from_dict_skips_degenerate_ylims_and_xlim():
    """B6: residual / non-finite pairs must not resurrect a pathological window."""
    from mf4_analyzer.ui.view_state import ViewState
    from mf4_analyzer.ui_kit.ticks_math import _DEGENERATE_SPAN_RATIO

    mid = 35.0
    residue = mid * _DEGENERATE_SPAN_RATIO * 0.5
    ok_key = '["f0","ok"]'
    bad_key = '["f0","residue"]'
    nan_key = '["f0","nan"]'
    flat_key = '["f0","flat"]'

    state = ViewState.from_dict({
        "name": "V",
        "tab_color": "#2d7ff9",
        "xlim": [mid - residue / 2.0, mid + residue / 2.0],
        "ylims": {
            ok_key: [-10.0, 10.0],
            bad_key: [mid - residue / 2.0, mid + residue / 2.0],
            nan_key: [float("nan"), 1.0],
            flat_key: [5.0, 5.0],
        },
    })

    assert state.xlim is None
    assert state.ylims == {ok_key: (-10.0, 10.0)}


def test_file_removal_drops_ylims_for_closed_fid():
    """A3: close-file cleanup must scrub composite ylims keys for removed fids."""
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui.pg_canvas._shared import _view_state_channel_key
    from mf4_analyzer.ui.view_state import ViewState

    keep = _view_state_channel_key("f2", "speed")
    drop = _view_state_channel_key("f1", "speed")
    state = ViewState(
        name="Scoped",
        tab_color="#2d7ff9",
        attached_file_ids=["f1", "f2"],
        checked=[("f1", "speed"), ("f2", "speed")],
        ylims={
            drop: (-1.0, 1.0),
            keep: (-2.0, 2.0),
        },
    )

    MainWindow._filter_time_view_state_for_removed_fids(state, {"f1"})

    assert drop not in state.ylims
    assert state.ylims == {keep: (-2.0, 2.0)}


def test_load_wwt_toasts_skipped_channels(qapp, tmp_path, monkeypatch):
    """D3: WWT skipped_channels must surface as a warning toast (HDF template)."""
    import numpy as np

    from mf4_analyzer.ui.main_window import MainWindow
    from tests.test_wwt_format import _make_header, _make_record

    n = 120
    vals = np.arange(n, dtype=np.float64)
    body = _make_record(b"Zeit", n, name=b"Time", unit=b"s")
    body += _make_record(b"Real", n, name=b"Weg", unit=b"mm", payload=vals.tobytes())
    # n mismatch → skipped
    body += _make_record(b"Real", 6, name=b"Tol_oben", unit=b"mm",
                         payload=np.zeros(6, dtype=np.float64).tobytes())
    p = tmp_path / "skip.wwt"
    p.write_bytes(_make_header(3) + body)

    mw = MainWindow()
    toasts = []
    monkeypatch.setattr(mw, "toast", lambda msg, level="info": toasts.append((msg, level)))
    mw._load_one(str(p))

    warn = [(m, lv) for m, lv in toasts if lv == "warning"]
    assert any("未导入" in m and "Tol_oben" in m for m, _ in warn), toasts


def test_load_zfd_estimated_fs_toasts_estimate_wording(qapp, tmp_path, monkeypatch):
    """A4 exit: fs_estimated=True must toast with an explicit 估算 label."""
    from mf4_analyzer.ui.main_window import MainWindow
    from tests.test_zfd_format import _write_minimal_zfd

    p = _write_minimal_zfd(tmp_path / "est.zfd", dt=7200.0, count=4)
    mw = MainWindow()
    toasts = []
    monkeypatch.setattr(mw, "toast", lambda msg, level="info": toasts.append((msg, level)))
    mw._load_one(str(p))

    warn = [(m, lv) for m, lv in toasts if lv == "warning"]
    assert any("估算" in m for m, _ in warn), toasts


def test_load_hdf_toasts_renamed_channels_summary(qapp, tmp_path, monkeypatch):
    """D4: silent [idx] renames must toast a single summary after load."""
    import numpy as np

    from mf4_analyzer.ui.main_window import MainWindow
    from tests._helpers.head_hdf_factory import write_head_hdf

    n = 4
    dup = lambda s: {
        "name": "Com_Motor_Torque", "factor": 1, "quantity": "torque",
        "unit": "Nm", "calibration": 1.0, "samples": s,
    }
    hdf = write_head_hdf(
        tmp_path / "dup.hdf", n_scans=n, delta=1.0, start_of_data=4096,
        channels=[dup(np.zeros(n)), dup(np.arange(n, dtype=float))])

    mw = MainWindow()
    toasts = []
    monkeypatch.setattr(mw, "toast", lambda msg, level="info": toasts.append((msg, level)))
    mw._load_one(str(hdf))

    warn = [(m, lv) for m, lv in toasts if lv == "warning"]
    assert any(m == "1 个通道重名，已加序号区分" for m, _ in warn), toasts


def test_load_mat_toasts_skipped_vars(qapp, tmp_path, monkeypatch):
    """D3: MAT skipped_vars must toast like HDF dropped_channels."""
    import numpy as np
    from scipy.io import savemat

    from mf4_analyzer.ui.main_window import MainWindow

    p = tmp_path / "skip.mat"
    savemat(str(p), {
        "t": np.arange(8, dtype=float) * 0.001,
        "sig": np.arange(8, dtype=float),
        "notes": np.array(["hello"]),
    })
    mw = MainWindow()
    toasts = []
    monkeypatch.setattr(mw, "toast", lambda msg, level="info": toasts.append((msg, level)))
    mw._load_one(str(p))

    warn = [(m, lv) for m, lv in toasts if lv == "warning"]
    assert any("变量未导入" in m and "notes" in m for m, _ in warn), toasts


def test_toast_io_load_diagnostics_dedupes_file_level_dropped_across_groups(
    qapp, monkeypatch,
):
    """HDF dropped/renamed lists are file-level and copied into every raster group.

    Three groups × two dropped channels must toast 「2 个」 once, not 「6 个」.
    """
    from mf4_analyzer.ui.main_window import MainWindow

    mw = MainWindow()
    toasts = []
    monkeypatch.setattr(
        mw, "toast", lambda msg, level="info": toasts.append((msg, level)),
    )
    smeta = {
        "dropped_channels": [
            {"name": "CAN 1@SQuadriga", "reason": "non-FLOAT32: UINT32"},
            {"name": "Label", "reason": "all-NaN"},
        ],
        "renamed_channels": [
            {"original": "Speed", "renamed": "Speed [2]"},
        ],
    }
    mw._toast_io_load_diagnostics(smeta, smeta, smeta)

    warn = [m for m, lv in toasts if lv == "warning"]
    dropped = [m for m in warn if "未导入" in m]
    renamed = [m for m in warn if "重名" in m]
    assert dropped == ["2 个通道未导入：CAN 1@SQuadriga、Label"], toasts
    assert renamed == ["1 个通道重名，已加序号区分"], toasts


def test_toast_io_load_diagnostics_surfaces_and_dedupes_source_warnings(
    qapp, monkeypatch,
):
    """F5: HDF factor warnings live in smeta['warnings']; toast them once."""
    from mf4_analyzer.ui.main_window import MainWindow

    mw = MainWindow()
    toasts = []
    monkeypatch.setattr(
        mw, "toast", lambda msg, level="info": toasts.append((msg, level)),
    )
    warning = "通道 2 (SP) 的 factor 未在 ch order 中声明，已按 1 估算"
    smeta = {"warnings": [warning]}
    mw._toast_io_load_diagnostics(smeta, smeta, smeta)

    warn = [m for m, lv in toasts if lv == "warning"]
    assert warn.count(warning) == 1, toasts


def test_load_hdf_toasts_assumed_factor_warning(qapp, tmp_path, monkeypatch):
    """F5: loading an HDF with an assumed factor must toast the A5 warning."""
    from mf4_analyzer.ui.main_window import MainWindow
    from tests.test_head_hdf_loader import _write_hdf_with_extra_channel_def

    hdf = _write_hdf_with_extra_channel_def(tmp_path / "assumed_factor.hdf")
    mw = MainWindow()
    toasts = []
    monkeypatch.setattr(
        mw, "toast", lambda msg, level="info": toasts.append((msg, level)),
    )
    mw._load_one(str(hdf))

    warn = [m for m, lv in toasts if lv == "warning"]
    assert any("factor" in m.lower() and "估算" in m for m in warn), toasts


def test_load_zfd_toasts_renamed_channels_summary(qapp, tmp_path, monkeypatch):
    """F5: ZFD in-group [marker_id] renames must toast like HDF/WWT/TDMS."""
    from mf4_analyzer.ui.main_window import MainWindow
    from tests.test_zfd_format import _write_zfd_duplicate_names

    zfd = _write_zfd_duplicate_names(tmp_path / "dup.zfd")
    mw = MainWindow()
    toasts = []
    monkeypatch.setattr(
        mw, "toast", lambda msg, level="info": toasts.append((msg, level)),
    )
    mw._load_one(str(zfd))

    warn = [m for m, lv in toasts if lv == "warning"]
    assert any(m == "1 个通道重名，已加序号区分" for m in warn), toasts


def test_close_all_cancel_keeps_ultraview_board(qapp, qtbot, monkeypatch):
    from mf4_analyzer.ui.main_window import MainWindow
    from mf4_analyzer.ui.ultraview_state import UltraViewRef, add_ref, membership_set

    mw = MainWindow()
    qtbot.addWidget(mw)
    uv = mw._ultraview
    view_id = str(mw.view_manager.get(0).view_id)
    add_ref(uv.board, UltraViewRef("time", view_id))
    uv.board.name = "会话保留"
    mw.files["f1"] = object()
    mw.navigator.add_file = lambda *a, **kw: None
    mw.navigator.remove_file = lambda *a, **kw: None
    monkeypatch.setattr(mw, "_confirm_global_file_close", lambda *a, **k: False)

    mw.close_all()

    assert "f1" in mw.files
    assert uv.board.name == "会话保留"
    assert UltraViewRef("time", view_id) in membership_set(uv.board)
