"""Project restoration restores intent, never grants a compute request."""

import json

import numpy as np
import pandas as pd
import pytest

from mf4_analyzer.ui.main_window import MainWindow


def _has_result(window, section):
    canvas = window._analysis_page(section).pane_canvas(0)
    if section == "fft":
        return bool(canvas._amp_curves)
    return canvas.has_result()


@pytest.mark.parametrize("section", ["fft", "fft_time", "order", "frf"])
@pytest.mark.parametrize("computed", [False, True], ids=["draft", "computed"])
@pytest.mark.parametrize("legacy", [False, True], ids=["current", "legacy"])
def test_project_reopen_requires_explicit_compute(
    qapp, qtbot, tmp_path, monkeypatch, section, computed, legacy,
):
    time = np.arange(4096, dtype=float) / 1024.0
    source_path = tmp_path / "signal.csv"
    pd.DataFrame({
        "time": time,
        "speed": np.full(time.shape, 1200.0),
        "input": np.sin(2 * np.pi * 40 * time),
        "output": 2 * np.sin(2 * np.pi * 40 * time - .2),
    }).to_csv(source_path, index=False)
    window = MainWindow()
    qtbot.addWidget(window)
    window._load_one(str(source_path))
    fid = next(iter(window.files))
    window.toolbar._set_mode(section)
    window._attach_files_to_active_context([fid])
    ctx = window._analysis_ctx(section)
    if section == "frf":
        ctx.set_input_source((fid, "input"))
        ctx.set_output_source((fid, "output"))
    else:
        window._echo_combo_signal(ctx.combo_sig, (fid, "output"))
        if section == "order":
            window._echo_combo_signal(ctx.combo_rpm, (fid, "speed"))
        else:
            ctx.apply_params({"nfft": 256})
    button_name = {"fft": "btn_fft", "order": "btn_ot"}.get(section, "btn_compute")
    if computed:
        getattr(ctx, button_name).click()
        qtbot.waitUntil(
            lambda: _has_result(window, section)
            and not window._analysis_jobs.is_running(section), timeout=20000,
        )
    else:
        assert not _has_result(window, section)
    path = tmp_path / "intent.tlproj"
    assert window.save_project(path)
    if legacy:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["schema_version"] = 3
        for block in payload["analysis_views"].values():
            for view in block["views"]:
                view["schema"] = 5
                view.pop("attached_file_ids", None)
                view.pop("preset_baseline", None)
                for pane in view["panes"]:
                    for key in ("viewport_origin", "pinned_cursors", "heatmap_color_basis"):
                        pane.pop(key, None)
        path.write_text(json.dumps(payload), encoding="utf-8")

    restored = MainWindow()
    qtbot.addWidget(restored)
    requests = []
    original_batch = restored._analysis_jobs.submit_batch
    original_frf = restored._frf_coordinator.request
    original_restore = restored._recompute_restored_analysis_view
    from mf4_analyzer.signal.fft import FFTAnalyzer
    original_fft = FFTAnalyzer.compute_fft

    def batch(*args, **kwargs):
        requests.append("batch")
        return original_batch(*args, **kwargs)

    def frf(*args, **kwargs):
        requests.append("frf")
        return original_frf(*args, **kwargs)

    def restore(*args, **kwargs):
        requests.append("restore")
        return original_restore(*args, **kwargs)

    def fft(*args, **kwargs):
        requests.append("fft")
        return original_fft(*args, **kwargs)

    monkeypatch.setattr(restored._analysis_jobs, "submit_batch", batch)
    monkeypatch.setattr(restored._frf_coordinator, "request", frf)
    monkeypatch.setattr(restored, "_recompute_restored_analysis_view", restore)
    monkeypatch.setattr(FFTAnalyzer, "compute_fft", fft)
    restored.open_project(path)
    # Drain queued callbacks, including mode-entry and deferred restore timers.
    qtbot.wait(100)
    restored.toolbar._set_mode("time")
    restored.toolbar._set_mode(section)
    qtbot.wait(100)
    assert requests == []
    assert not restored._analysis_restore_pending
    assert restored._analysis_jobs.progress_token("restore") is None
    assert not _has_result(restored, section)
    pane = restored.analysis_managers[section].get(0).panes[0]
    if section == "frf":
        assert pane.input_source[1] == "input"
        assert pane.output_source[1] == "output"
    else:
        assert pane.sources[0][1] == "output"
        if section == "order":
            assert pane.rpm_source[1] == "speed"

    # Restored intent remains actionable through the real compute control.
    getattr(restored._analysis_ctx(section), button_name).click()
    qtbot.waitUntil(
        lambda: _has_result(restored, section)
        and not restored._analysis_jobs.is_running(section), timeout=20000,
    )
