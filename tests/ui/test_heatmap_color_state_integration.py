"""Owning color requests survive real MainWindow render/capture transactions."""
import copy
import uuid

import numpy as np
import pytest

from mf4_analyzer.signal.order_cot import COTParams, COTResult
from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult
from mf4_analyzer.ui.main_window import MainWindow


@pytest.fixture
def color_win(qapp, qtbot, tmp_path, monkeypatch):
    """Independent real source fixture; shared UI fixtures isolate QSettings."""
    win = MainWindow()
    qtbot.addWidget(win)
    times = np.arange(1000, dtype=float) / 1000.0
    for index in range(2):
        path = tmp_path / f"color-source-{index}.csv"
        data = np.column_stack((times, 900 + 100 * np.sin(times * 20),
                                3 + np.cos(times * (30 + index))))
        np.savetxt(path, data, delimiter=",", header="time,speed,torque", comments="")
        win._load_one(str(path))
    assert len(win.files) == 2

    def unexpected_submit(*args, **kwargs):
        pytest.fail("display-only color transaction submitted DSP work")

    monkeypatch.setattr(win._analysis_jobs, "submit_batch", unexpected_submit)
    return win


def _seed(win, section):
    win.toolbar._set_mode(section)
    win._attach_files_to_active_context(list(win.files))
    manager = win.analysis_managers[section]
    state = manager.get(manager.active)
    ctx = win._analysis_ctx(section)
    ctx.apply_params({
        "amplitude_mode": "Amplitude dB" if section == "order" else "amplitude_db",
        "z_auto": False, "z_floor": -80.0, "z_ceiling": 0.0,
        "db_reference_mode": "manual", "db_reference": 1.0,
        "freq_auto": True,
    })
    state.params.update(ctx.current_params())
    fid = next(iter(win.files))
    pane = state.panes[0]
    pane.sources = [(fid, "torque")]
    pane.rpm_source = (fid, "speed") if section == "order" else None
    times = np.linspace(0.0, 0.5, 8)
    amplitude = np.linspace(0.01, 1.2, 128, dtype=np.float32)
    if section == "order":
        result = COTResult(
            times=times, orders=np.linspace(0.0, 10.0, 16),
            amplitude=amplitude.reshape(8, 16),
            params=COTParams(fs=1000.0, nfft=256, order_res=0.05),
            metadata={"frames": 8, "coverage_start": 0.0, "coverage_end": 0.5},
        )
    else:
        result = SpectrogramResult(
            times=times, frequencies=np.linspace(0.0, 200.0, 16),
            amplitude=amplitude.reshape(16, 8),
            params=SpectrogramParams(fs=1000.0, nfft=32),
            channel_name="torque", unit="N", metadata={"frames": 8},
        )
    _cache(win, section, state, result)
    return state, result


def _cache(win, section, state, result):
    for index, pane in enumerate(state.panes):
        fid, channel = pane.sources[0]
        key = win._analysis_cache_key_for_view_source(
            section, state, pane, index, fid, channel,
        )
        win.analysis_caches[section].put(key, result)


def _other(win, section, state, result, reference=10 ** 1.5):
    other = copy.deepcopy(state)
    other.view_id = uuid.uuid4().hex
    other.name = "Other color owner"
    other.params["db_reference"] = reference
    win.analysis_managers[section].views.append(other)
    _cache(win, section, other, result)
    return other


def _levels(canvas):
    assert canvas.has_result()
    return tuple(map(float, canvas._img.getLevels()))


@pytest.mark.parametrize("section", ["fft_time", "order"])
@pytest.mark.parametrize("split", [False, True], ids=["A01-single", "A03-split"])
def test_manual_color_request_survives_twenty_view_roundtrips(color_win, qapp, section, split):
    win = color_win
    first, result = _seed(win, section)
    if split:
        first.panes.append(copy.deepcopy(first.panes[0]))
        first.compare["levels_locked"] = False
        _cache(win, section, first, result)
    second = _other(win, section, first, result)
    raw = result.amplitude.copy()
    win._on_analysis_view_switched(section, 0)
    matrices = {}
    for index in [0] + [1, 0] * 20:
        win._on_analysis_switch(section, index)
        qapp.processEvents()
        page = win._analysis_page(section)
        for pane_index in range(page.pane_count()):
            canvas = page.pane_canvas(pane_index)
            assert _levels(canvas) == pytest.approx((-80.0, 0.0))
            assert canvas._slice_plot.vb.viewRange()[1] == pytest.approx((-80.0, 0.0))
            matrix_key = (index, pane_index)
            if matrix_key not in matrices:
                matrices[matrix_key] = canvas._matrix_disp.copy()
            np.testing.assert_array_equal(canvas._matrix_disp, matrices[matrix_key])
        ctx = win._analysis_ctx(section)
        assert (ctx.spin_z_floor.value(), ctx.spin_z_ceiling.value()) == (-80.0, 0.0)
        for state in (first, second):
            assert (state.params["z_floor"], state.params["z_ceiling"]) == (-80.0, 0.0)
    np.testing.assert_array_equal(result.amplitude, raw)


@pytest.mark.parametrize("section", ["fft_time", "order"])
def test_auto_reference_keeps_same_named_sources_independent(color_win, qapp, section):
    win = color_win
    first, result = _seed(win, section)
    first.params["db_reference_mode"] = "auto"
    second = _other(win, section, first, result)
    fids = list(win.files)
    for fid, reference in zip(fids, (1.0, 10 ** 1.5)):
        win.files[fid].channel_metadata = {
            "torque": {"unit": "N", "quantity": "force", "db_reference": reference},
        }
    second.panes[0].sources = [(fids[1], "torque")]
    _cache(win, section, second, result)
    win._on_analysis_view_switched(section, 0)
    for index in [1, 0] * 20:
        win._on_analysis_switch(section, index)
        qapp.processEvents()
        assert _levels(win._analysis_page(section).pane_canvas(0)) == pytest.approx((-80, 0))
        for state in (first, second):
            assert (state.params["z_floor"], state.params["z_ceiling"]) == (-80, 0)


@pytest.mark.parametrize("section", ["fft_time", "order"])
def test_reference_edit_and_capture_preserve_request_basis(color_win, qapp, section):
    """A04/A13: actual reference edits move once, including after capture."""
    win = color_win
    state, result = _seed(win, section)
    _other(win, section, state, result)
    win._on_analysis_view_switched(section, 0)
    canvas = win._analysis_page(section).pane_canvas(0)
    raw = result.amplitude.copy()
    matrix = canvas._matrix_disp.copy()
    ctx = win._analysis_ctx(section)
    ctx.spin_db_ref.setValue(10.0)
    qapp.processEvents()
    for _ in range(3):
        win._render_analysis_view_from_cache(section, state)
        assert _levels(canvas) == pytest.approx((-100, -20))
        win._capture_active_analysis_view(section, capture_sources=False)
        assert (state.params["z_floor"], state.params["z_ceiling"]) == (-80, 0)
    win._on_analysis_switch(section, 1)
    win._on_analysis_switch(section, 0)
    assert _levels(canvas) == pytest.approx((-100, -20))
    ctx.spin_db_ref.setValue(1.0)
    qapp.processEvents()
    assert _levels(canvas) == pytest.approx((-80, 0))
    np.testing.assert_array_equal(canvas._matrix_disp, matrix)
    np.testing.assert_array_equal(result.amplitude, raw)


@pytest.mark.parametrize("section", ["fft_time", "order"])
@pytest.mark.parametrize("mode", ["same-reference", "automatic", "linear", "section-entry"])
def test_color_policy_controls_are_stable(color_win, qapp, section, mode):
    win = color_win
    first, result = _seed(win, section)
    if mode == "automatic":
        first.params["z_auto"] = True
    elif mode == "linear":
        first.params["amplitude_mode"] = "Linear" if section == "order" else "amplitude"
        first.params.update(z_floor=0.1, z_ceiling=1.0)
    _other(win, section, first, result, reference=1.0 if mode == "same-reference" else 10 ** 1.5)
    win._on_analysis_view_switched(section, 0)
    windows = {}
    for index in [0, 1, 0, 1, 0]:
        win._on_analysis_switch(section, index)
        if mode == "section-entry":
            win.toolbar._set_mode("fft")
            win.toolbar._set_mode(section)
        qapp.processEvents()
        actual = _levels(win._analysis_page(section).pane_canvas(0))
        if index not in windows:
            windows[index] = actual
        assert actual == pytest.approx(windows[index])


@pytest.mark.parametrize("section", ["fft_time", "order"])
def test_capture_keeps_unedited_double_precision(color_win, section):
    win = color_win
    state, result = _seed(win, section)
    requested = (-80.123456789, 0.234567891)
    state.params.update(z_floor=requested[0], z_ceiling=requested[1])
    win._on_analysis_view_switched(section, 0)
    for _ in range(3):
        win._capture_active_analysis_view(section, capture_sources=False)
        win._render_analysis_view_from_cache(section, state)
        assert (state.params["z_floor"], state.params["z_ceiling"]) == requested
        np.testing.assert_allclose(
            _levels(win._analysis_page(section).pane_canvas(0)), requested, rtol=0, atol=1e-12,
        )


@pytest.mark.parametrize("section", ["fft_time", "order"])
@pytest.mark.parametrize("focus", [0, 1])
def test_pane_override_and_focused_projection_are_order_independent(color_win, section, focus):
    win = color_win
    state, result = _seed(win, section)
    state.panes.append(copy.deepcopy(state.panes[0]))
    state.compare["levels_locked"] = False
    state.panes[0].chart_appearances = {"heatmap": {"title": "No Z override", "cmap": "plasma"}}
    state.panes[1].chart_appearances = {"heatmap": {"z_auto": False, "z_min": -40.0, "z_max": 10.0}}
    _cache(win, section, state, result)
    win._on_analysis_view_switched(section, 0)
    page = win._analysis_page(section)
    page.set_focused_index(focus)
    expected = [(-80.0, 0.0), (-40.0, 10.0)]
    for indices in ((0, 1), (1, 0)):
        # Exercise existing single-pane render entry in both orders after the
        # whole View has acquired its owners; no test-only transaction API.
        for index in indices:
            canvas = page.pane_canvas(index)
            fid, channel = state.panes[index].sources[0]
            if section == "fft_time":
                win._render_fft_time_on(canvas, result, dict(state.params), source=(fid, channel))
            else:
                win._render_order_on(canvas, result, source=(fid, channel))
        assert [_levels(page.pane_canvas(i)) for i in range(2)] == expected
        ctx = win._analysis_ctx(section)
        assert (ctx.spin_z_floor.value(), ctx.spin_z_ceiling.value()) == expected[focus]
        assert (state.params["z_floor"], state.params["z_ceiling"]) == expected[0]


@pytest.mark.parametrize("section", ["fft_time", "order"])
def test_single_bound_user_edit_preserves_other_effective_bound_precision(color_win, qapp, section):
    win = color_win
    state, _result = _seed(win, section)
    upper = 0.234567891
    state.params.update(z_floor=-80.123456789, z_ceiling=upper)
    win._on_analysis_view_switched(section, 0)
    ctx = win._analysis_ctx(section)
    ctx.spin_db_ref.setValue(10.0)
    qapp.processEvents()
    ctx.spin_z_floor.setValue(-65.5)
    qapp.processEvents()
    assert state.params["z_floor"] == -65.5
    assert state.params["z_ceiling"] == upper - 20.0
    np.testing.assert_allclose(
        _levels(win._analysis_page(section).pane_canvas(0)),
        (-65.5, upper - 20.0), rtol=0, atol=1e-12,
    )
    win._capture_active_analysis_view(section, capture_sources=False)
    assert state.params["z_ceiling"] == upper - 20.0


@pytest.mark.parametrize("section", ["fft_time", "order"])
def test_effective_levels_outside_old_editor_limits_are_not_clamped(color_win, qapp, section):
    win = color_win
    state, _result = _seed(win, section)
    state.params.update(z_floor=-400.0, z_ceiling=-320.0)
    win._on_analysis_view_switched(section, 0)
    ctx = win._analysis_ctx(section)
    ctx.spin_db_ref.setValue(1e10)
    qapp.processEvents()
    assert _levels(win._analysis_page(section).pane_canvas(0)) == pytest.approx((-600, -520))
    assert (ctx.spin_z_floor.value(), ctx.spin_z_ceiling.value()) == (-600, -520)
    win._capture_active_analysis_view(section, capture_sources=False)
    assert (state.params["z_floor"], state.params["z_ceiling"]) == (-400, -320)


@pytest.mark.parametrize("section", ["fft_time", "order"])
@pytest.mark.parametrize("hidden", [False, True], ids=["visible-save", "hidden-save"])
def test_project_roundtrip_keeps_request_and_reference_basis(
    color_win, qapp, qtbot, tmp_path, monkeypatch, section, hidden,
):
    win = color_win
    state, result = _seed(win, section)
    requested = (-80.123456789, 0.234567891)
    state.params.update(z_floor=requested[0], z_ceiling=requested[1])
    win._on_analysis_view_switched(section, 0)
    win._analysis_ctx(section).spin_db_ref.setValue(10.0)
    qapp.processEvents()
    if hidden:
        win.toolbar._set_mode("fft")
    project = tmp_path / "manual-color.tlproj"
    win.save_project(project)
    assert project.is_file()
    assert (state.params["z_floor"], state.params["z_ceiling"]) == requested
    reopened_win = MainWindow()
    qtbot.addWidget(reopened_win)

    def unexpected_submit(*args, **kwargs):
        pytest.fail("project color restore submitted DSP work")

    def seed_restored_result(view_id):
        # Projects store source references, not DSP arrays. Substitute only
        # the scheduled compute boundary with the same deterministic result;
        # project deserialization, fid remapping and rendering stay real.
        restored_manager = reopened_win.analysis_managers[section]
        target = next(view for view in restored_manager.views if view.view_id == view_id)
        _cache(reopened_win, section, target, result)

    restore_compute = ("_recompute_restored_fft_time_view" if section == "fft_time"
                       else "_recompute_restored_order_view")
    monkeypatch.setattr(reopened_win, restore_compute, seed_restored_result)
    monkeypatch.setattr(reopened_win._analysis_jobs, "submit_batch", unexpected_submit)
    reopened_win.open_project(project)
    qapp.processEvents()
    manager = reopened_win.analysis_managers[section]
    restored = next(view for view in manager.views if view.view_id == state.view_id)
    assert (restored.params["z_floor"], restored.params["z_ceiling"]) == requested
    reopened_win.toolbar._set_mode(section)
    reopened_win._on_analysis_view_switched(section, manager.views.index(restored))
    _cache(reopened_win, section, restored, result)
    reopened_win._render_analysis_view_from_cache(section, restored)
    actual = _levels(reopened_win._analysis_page(section).pane_canvas(0))
    np.testing.assert_allclose(actual, np.asarray(requested) - 20, rtol=0, atol=1e-12)


@pytest.mark.parametrize("section", ["fft_time", "order"])
def test_comparison_focus_rebind_and_exit_keep_each_owners_levels(color_win, qapp, section):
    win = color_win
    first, result = _seed(win, section)
    second = _other(win, section, first, result)
    second.params.update(z_floor=-55.0, z_ceiling=5.0)
    win._on_analysis_view_switched(section, 0)
    expected = {first.view_id: (-80.0, 0.0), second.view_id: (-55.0, 5.0)}
    for host, peer in ((first, second), (second, first), (first, second)):
        assert win.open_comparison(section, host.view_id, peer.view_id)
        for focused in (host, peer, host, peer):
            win.focus_comparison(section, focused.view_id)
            qapp.processEvents()
            for state in (host, peer):
                canvas = win._comparison().canvas_for(section, state.view_id, 0)
                assert _levels(canvas) == pytest.approx(expected[state.view_id])
                assert (state.params["z_floor"], state.params["z_ceiling"]) == expected[state.view_id]
            ctx = win._analysis_ctx(section)
            assert (ctx.spin_z_floor.value(), ctx.spin_z_ceiling.value()) == expected[focused.view_id]
        win.close_comparison(section)


@pytest.mark.parametrize("section", ["fft_time", "order"])
def test_locked_union_does_not_replace_each_panes_request(color_win, section):
    win = color_win
    state, result = _seed(win, section)
    state.panes.append(copy.deepcopy(state.panes[0]))
    override = {"z_auto": False, "z_min": -40.0, "z_max": 10.0}
    state.panes[1].chart_appearances = {"heatmap": dict(override)}
    state.compare["levels_locked"] = True
    _cache(win, section, state, result)
    win._on_analysis_view_switched(section, 0)
    page = win._analysis_page(section)
    for index in range(2):
        assert _levels(page.pane_canvas(index)) == pytest.approx((-80, 10))
        assert page.pane_canvas(index)._slice_plot.vb.viewRange()[1] == pytest.approx((-80, 10))
    win._capture_active_analysis_view(section, capture_sources=False)
    assert (state.params["z_floor"], state.params["z_ceiling"]) == (-80, 0)
    assert state.panes[1].chart_appearances["heatmap"] == override
    state.compare["levels_locked"] = False
    win._on_analysis_view_switched(section, 0)
    assert _levels(page.pane_canvas(0)) == pytest.approx((-80, 0))
    assert _levels(page.pane_canvas(1)) == pytest.approx((-40, 10))


def _color_ownership(state):
    return (
        {key: state.params[key] for key in ("z_auto", "z_floor", "z_ceiling")},
        [copy.deepcopy(pane.heatmap_color_basis) for pane in state.panes],
        [{key: value for key, value in pane.chart_appearances.get("heatmap", {}).items()
          if key in {"z_auto", "z_min", "z_max"}} for pane in state.panes],
    )


@pytest.mark.parametrize("section", ["fft_time", "order"])
@pytest.mark.parametrize("action", ["cancel", "title-only", "apply-restore"])
def test_chart_options_respect_request_scope_and_opening_basis(
    color_win, qapp, qtbot, monkeypatch, section, action,
):
    from PyQt5.QtWidgets import QDialog
    from mf4_analyzer.ui.dialogs import ChartOptionsDialog

    win = color_win
    state, _result = _seed(win, section)
    requested = (-80.123456789, 0.234567891)
    state.params.update(z_floor=requested[0], z_ceiling=requested[1])
    win._on_analysis_view_switched(section, 0)
    ctx = win._analysis_ctx(section)
    ctx.spin_db_ref.setValue(10.0)
    qapp.processEvents()
    canvas = win._analysis_page(section).pane_canvas(0)
    opening = _color_ownership(state)
    opening_levels = _levels(canvas)

    def interact(dialog):
        qtbot.addWidget(dialog)
        assert _color_ownership(state) == opening
        if action == "cancel":
            dialog.spin_color_min.setValue(-50.0)
            dialog.spin_color_max.setValue(-10.0)
            return QDialog.Rejected
        if action == "title-only":
            dialog.edit_title.setText("Unchanged color intent")
            dialog.apply_changes()
        else:
            dialog.chk_color_auto.setChecked(False)
            dialog.spin_color_min.setValue(-50.0)
            dialog.spin_color_max.setValue(-10.0)
            dialog.apply_changes()
            assert _levels(canvas) == pytest.approx((-50, -10))
            override = state.panes[0].chart_appearances["heatmap"]
            assert (override["z_auto"], override["z_min"], override["z_max"]) == (False, -50, -10)
            assert (state.params["z_floor"], state.params["z_ceiling"]) == requested
            dialog.btn_reset.click()
        assert dialog.was_applied()
        return QDialog.Accepted

    monkeypatch.setattr(ChartOptionsDialog, "exec_", interact)
    assert canvas.open_chart_options_dialog(win) is (action != "cancel")
    if action == "title-only":
        assert state.panes[0].chart_appearances["heatmap"]["title"] == "Unchanged color intent"
    assert _color_ownership(state) == opening
    np.testing.assert_allclose(_levels(canvas), opening_levels, rtol=0, atol=1e-12)
    # Restoring an opening window must restore its anchor, not freeze the
    # then-visible numbers at the current reference as a newly entered value.
    ctx.spin_db_ref.setValue(1.0)
    qapp.processEvents()
    np.testing.assert_allclose(_levels(canvas), requested, rtol=0, atol=1e-12)


@pytest.mark.parametrize("section", ["fft_time", "order"])
@pytest.mark.parametrize("contains_z", [False, True], ids=["XY-only-preset", "Z-preset"])
def test_preset_patch_owns_only_explicit_color_fields(
    color_win, qapp, monkeypatch, section, contains_z,
):
    win = color_win
    state, result = _seed(win, section)
    state.panes.append(copy.deepcopy(state.panes[0]))
    state.compare["levels_locked"] = False
    for index, pane in enumerate(state.panes):
        pane.chart_appearances = {"heatmap": {
            "title": f"Pane {index}", "cmap": "plasma", "z_auto": False,
            "z_min": -40.0 + index, "z_max": 10.0 + index,
        }}
    _cache(win, section, state, result)
    win._on_analysis_view_switched(section, 0)
    ctx = win._analysis_ctx(section)
    ctx.spin_db_ref.setValue(10.0)
    qapp.processEvents()
    before = _color_ownership(state)
    bar = ctx.preset_bar
    monkeypatch.setattr(bar, "_confirm_axis_preservation", lambda *args, **kwargs: "preset")
    patch = ({"z_auto": False, "z_floor": -60.0, "z_ceiling": -5.0} if contains_z
             else {"x_auto": False, "x_min": 0.1, "x_max": 0.4})
    bar._write(4, "Explicit color patch" if contains_z else "Only X range", patch)
    bar._load(4)
    qapp.processEvents()
    assert bar.baseline() is not None
    if contains_z:
        assert (state.params["z_floor"], state.params["z_ceiling"]) == (-60, -5)
        for index, pane in enumerate(state.panes):
            appearance = pane.chart_appearances["heatmap"]
            assert not {"z_auto", "z_min", "z_max"}.intersection(appearance)
            assert appearance["title"] == f"Pane {index}"
            assert appearance["cmap"] == "plasma"
            assert _levels(win._analysis_page(section).pane_canvas(index)) == pytest.approx((-60, -5))
        ctx.spin_db_ref.setValue(1.0)
        qapp.processEvents()
        assert _levels(win._analysis_page(section).pane_canvas(0)) == pytest.approx((-40, 15))
    else:
        assert _color_ownership(state) == before


@pytest.mark.parametrize("section", ["fft_time", "order"])
def test_batch_current_and_remembered_preset_expand_effective_color_window(color_win, qapp, section):
    win = color_win
    state, _result = _seed(win, section)
    requested = (-80.123456789, 0.234567891)
    state.params.update(z_floor=requested[0], z_ceiling=requested[1])
    win._on_analysis_view_switched(section, 0)
    win._analysis_ctx(section).spin_db_ref.setValue(10.0)
    qapp.processEvents()
    before = _color_ownership(state)
    current = win._build_current_batch_preset()
    assert current is not None
    method = "order_time" if section == "order" else section
    win._remember_batch_preset(
        "Current effective window", method, state.panes[0].sources[0], dict(state.params),
        rpm_signal=state.panes[0].rpm_source,
        target_canvas=win._analysis_page(section).pane_canvas(0),
    )
    for preset in (current, win._last_batch_preset):
        np.testing.assert_allclose(
            (preset.params["z_floor"], preset.params["z_ceiling"]),
            np.asarray(requested) - 20.0, rtol=0, atol=1e-12,
        )
        assert "heatmap_color_basis" not in preset.params
    assert _color_ownership(state) == before

@pytest.mark.parametrize("section", ["fft_time", "order"])
def test_invalid_restored_color_request_never_keeps_another_view_picture(color_win, section):
    win = color_win
    state, result = _seed(win, section)
    _other(win, section, state, result)
    win._on_analysis_view_switched(section, 0)
    other = win.analysis_managers[section].get(1)
    other.params.update(z_floor=4.0, z_ceiling=4.0)
    win._on_analysis_switch(section, 1)
    canvas = win._analysis_page(section).pane_canvas(0)
    assert not canvas.has_result()
    assert other.params["z_floor"] == other.params["z_ceiling"] == 4.0
    assert other.panes[0].heatmap_color_basis is None


@pytest.mark.parametrize("section", ["fft_time", "order"])
def test_capture_copy_and_ultraview_keep_effective_levels_and_owned_intent(
    color_win, qapp, qtbot, monkeypatch, tmp_path, section,
):
    from PyQt5.QtGui import QImage
    from PyQt5.QtWidgets import QApplication
    from mf4_analyzer.ui.ultraview_state import UltraViewRef

    class ImageSink:
        """Exercise the real copy publisher without touching OS clipboard."""
        def __init__(self):
            self.images = []

        def setPixmap(self, pixmap):
            self.images.append(pixmap.toImage().copy())

        def setImage(self, image):
            self.images.append(image.copy())

    sink = ImageSink()
    monkeypatch.setattr(QApplication, "clipboard", staticmethod(lambda: sink))
    win = color_win
    win.resize(1200, 850)
    win.show()
    state, result = _seed(win, section)
    win._on_analysis_view_switched(section, 0)
    ctx = win._analysis_ctx(section)
    ctx.spin_db_ref.setValue(10.0)
    qapp.processEvents()
    page = win._analysis_page(section)
    canvas = page.pane_canvas(0)
    before = _color_ownership(state)
    focus = (win.chart_stack.current_mode(), win.analysis_managers[section].active,
             page.focused_index())
    matrix = canvas._matrix_disp.copy()
    raw = result.amplitude.copy()

    def unchanged():
        assert _levels(canvas) == pytest.approx((-100, -20))
        assert tuple(canvas._cbar.levels()) == pytest.approx((-100, -20))
        assert canvas._slice_plot.vb.viewRange()[1] == pytest.approx((-100, -20))
        assert _color_ownership(state) == before
        assert (win.chart_stack.current_mode(), win.analysis_managers[section].active,
                page.focused_index()) == focus
        np.testing.assert_array_equal(canvas._matrix_disp, matrix)
        np.testing.assert_array_equal(result.amplitude, raw)

    grabbed = canvas.grab_pixmap()
    assert not grabbed.isNull() and grabbed.width() > 1 and grabbed.height() > 1
    exported = tmp_path / f"{section}-effective.png"
    assert grabbed.save(str(exported))
    assert not QImage(str(exported)).isNull()
    unchanged()

    win.chart_stack._copy_card_image(None)
    assert len(sink.images) == 1 and not sink.images[0].isNull()
    unchanged()

    uv = win._ultraview
    ref = UltraViewRef(section, state.view_id)
    uv._apply_add_ref(ref)
    uv.request_visible_section_capture(section, reason="explicit-color-output-test")

    def current_preview():
        record = uv.store.get(ref)
        return (record is not None and not record.image.isNull()
                and record.captured_digest == uv.current_digest_for(ref))

    qtbot.waitUntil(current_preview, timeout=5000)
    record = uv.store.get(ref)
    assert record.image.width() > 1 and record.image.height() > 1
    assert uv.copy_card_to_clipboard(ref)
    assert len(sink.images) == 2 and sink.images[-1] == record.image
    unchanged()
