# tests/ui/test_project_session.py
import pytest

from mf4_analyzer import app_meta


def test_app_meta_constants():
    assert app_meta.APP_VERSION == "v7.9.4"
    assert app_meta.WINDOW_TITLE == "TraceLab v7.9.4"
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


def test_open_project_auto_recomputes_source_bearing_analysis_views(
        qapp, tmp_path, monkeypatch):
    """Recompute-on-open: a saved project stores each analysis view's params +
    sources but NOT the numeric results, so opening it must auto-recompute every
    view that has sources (and leave source-less views alone)."""
    from mf4_analyzer.ui.main_window import MainWindow
    csv_a = tmp_path / "a.csv"; _write_csv(csv_a)
    proj = tmp_path / "s.tlproj"

    mw = MainWindow()
    mw._load_one(str(csv_a))
    fid = next(iter(mw.files))
    # Give the Order view a source while the app is in 'time' mode — save then
    # preserves these sources (capture_sources only re-reads the navigator for
    # the CURRENT mode). The FFT view is left source-less.
    mw.analysis_managers['order'].get(0).panes[0].sources = [(fid, 'rpm')]
    mw.save_project(proj)

    mw2 = MainWindow()
    recomputed = []
    monkeypatch.setattr(
        type(mw2), '_recompute_analysis_section',
        lambda self, section: recomputed.append(section),
    )
    mw2.open_project(proj)
    # Recompute is deferred via QTimer.singleShot so it never pops a modal
    # mid-open; pump the event loop to let the queued dispatch run.
    qapp.processEvents()

    assert 'order' in recomputed, "source-bearing Order view must auto-recompute"
    assert 'fft' not in recomputed, "source-less FFT view must NOT recompute"


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
