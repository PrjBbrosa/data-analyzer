"""All-sections page-transition expansion matrix.

Production admits the five chart sections for single-pane user navigation.
Split, programmatic restore, and uncomputed cache-miss targets stay
direct-terminal.  E1–E5 cover protocol, internals, and the 20 directed
cross-section edges.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PyQt5.QtCore import QPoint, QRect, Qt
from PyQt5.QtGui import QColor, QPainter, QPixmap
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui.chart_stack import ChartStack
from mf4_analyzer.ui.chart_stack.page_transition import (
    PAGE_TRANSITION_ENABLED_SECTIONS,
    PageTransitionController,
    PresentationToken,
)
from mf4_analyzer.ui.main_window import MainWindow
from mf4_analyzer.ui_kit.motion import POLICY_LIGHT, POLICY_OFF

from tests.ui.test_view_switch_integration import (
    _fid,
    _make_loaded_window,
    _narrow_xlim,
    _set_checked,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_WINDOW_PY = _REPO_ROOT / "mf4_analyzer/ui/main_window/window.py"
_STACK_PY = _REPO_ROOT / "mf4_analyzer/ui/chart_stack/stack.py"
_LINE_CANVAS_PY = _REPO_ROOT / "mf4_analyzer/ui/pg_canvas/line_canvas.py"
_FRF_MIXIN_PY = _REPO_ROOT / "mf4_analyzer/ui/main_window/_frf_mixin.py"
_FFT_TIME_MIXIN_PY = _REPO_ROOT / "mf4_analyzer/ui/main_window/_fft_time_mixin.py"
_ORDER_MIXIN_PY = _REPO_ROOT / "mf4_analyzer/ui/main_window/_order_mixin.py"

_SECTIONS = ("time", "fft", "fft_time", "frf", "order")
_CROSS_SECTION_EDGES = tuple(
    (source, target)
    for source in _SECTIONS
    for target in _SECTIONS
    if source != target
)
_E5_INTERNAL_AND_SPLIT_TESTS = (
    "test_e1_fft_cache_hit_light_fade",
    "test_e1_fft_cache_miss_stays_direct_until_admitted",
    "test_e1_fft_preview_only_retained_path",
    "test_e1_fft_empty_state_light_fade",
    "test_e1_fft_retained_reveal_ready_path",
    "test_e3_frf_multi_subplot_internal_switch",
    "test_e3_time_and_fft_to_frf_user_navigation",
    "test_e4_heatmap_slice_and_colorbar_invalidation",
    "test_split_view_switch_is_direct_terminal",
)


def _assert_idle(controller) -> None:
    assert not controller.is_pending()
    assert not controller.is_active()
    assert controller.image_bytes() == 0


def _wait_idle(qtbot, window, timeout=2500) -> None:
    controller = window.chart_stack.page_transition()
    qtbot.waitUntil(
        lambda: (
            controller.image_bytes() == 0
            and not controller.is_active()
            and not controller.is_pending()
        ),
        timeout=timeout,
    )


def _pause_page_transition(window) -> None:
    """Setup helpers must not wait on Light fades while seeding Views."""
    window.chart_stack.cancel_page_transition("test-setup")
    window.chart_stack.set_page_transition_motion_policy(POLICY_OFF)


def _resume_page_transition(window) -> None:
    window.chart_stack.set_page_transition_motion_policy(POLICY_LIGHT)


def _install_transition_spies(monkeypatch, window):
    stack = window.chart_stack
    controller = stack.page_transition()
    begins = []
    captures = []
    orig_begin = stack.begin_page_transition
    orig_capture = controller.capture_local_endpoint

    def begin(**kwargs):
        token = orig_begin(**kwargs)
        begins.append({"kwargs": kwargs, "token": token})
        return token

    def capture(widget, *, exclude_overlay=False):
        pixmap = orig_capture(widget, exclude_overlay=exclude_overlay)
        captures.append(
            {
                "exclude_overlay": exclude_overlay,
                "null": pixmap.isNull(),
            }
        )
        return pixmap

    monkeypatch.setattr(stack, "begin_page_transition", begin)
    monkeypatch.setattr(controller, "capture_local_endpoint", capture)
    return begins, captures


def _seed_active_analysis_attachments(win, fids=None):
    mode = win.chart_stack.current_mode()
    if mode in getattr(win, "analysis_managers", {}):
        win._attach_files_to_active_context(list(fids or win.files.keys()))


def _time_terminal(win):
    state = win.view_manager.get(win.view_manager.active)
    xlim = win.canvas_time.get_visible_xlim()
    channels = tuple(
        (fid, ch) for fid, ch, _color in win.navigator.get_checked_channels()
    )
    return {
        "view_id": state.view_id,
        "active": win.view_manager.active,
        "channels": channels,
        "xlim": None if xlim is None else (float(xlim[0]), float(xlim[1])),
        "split": bool(win.chart_stack.split_active()),
        "mode": win.chart_stack.current_mode(),
    }


def _fft_terminal(win):
    mgr = win.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    pane = state.panes[0]
    canvas = win.chart_stack.page_fft.pane_canvas(0)
    entries = tuple(
        (entry.get("fid"), entry.get("channel"), entry.get("label"))
        for entry in (getattr(canvas, "_entries", None) or ())
    )
    return {
        "view_id": state.view_id,
        "active": mgr.active,
        "sources": tuple(tuple(source) for source in pane.sources),
        "time_range": pane.time_range,
        "amp_curves": len(getattr(canvas, "_amp_curves", None) or ()),
        "time_curves": len(getattr(canvas, "_time_curves", None) or ()),
        "has_result": bool(canvas.has_result()),
        "entries": entries,
        "mode": win.chart_stack.current_mode(),
    }


def _assert_time_terminals_match(actual, expected) -> None:
    assert actual["view_id"] == expected["view_id"]
    assert actual["active"] == expected["active"]
    assert actual["channels"] == expected["channels"]
    assert actual["split"] == expected["split"]
    assert actual["mode"] == expected["mode"]
    if expected["xlim"] is None:
        assert actual["xlim"] is None
        return
    assert actual["xlim"] == pytest.approx(expected["xlim"])


def _new_time_view(qtbot, qapp, window) -> int:
    before = len(window.view_manager.views)
    window._on_view_new()
    qapp.processEvents()
    qtbot.waitUntil(
        lambda: len(window.view_manager.views) == before + 1, timeout=2000,
    )
    qtbot.waitUntil(
        lambda: window.view_manager.active == before, timeout=2000,
    )
    return window.view_manager.active


def _install_compute_spies(monkeypatch, window):
    submitted = []
    computes = []
    orig_submit = window._analysis_jobs.submit_batch
    orig_compute = window._fft_compute_arrays

    def submit(section, jobs, **kwargs):
        queued = list(jobs)
        submitted.append((section, len(queued)))
        return orig_submit(section, queued, **kwargs)

    def compute(*args, **kwargs):
        computes.append(1)
        return orig_compute(*args, **kwargs)

    monkeypatch.setattr(window._analysis_jobs, "submit_batch", submit)
    monkeypatch.setattr(window, "_fft_compute_arrays", compute)
    return submitted, computes


def _host_token(host, view_id, generation) -> PresentationToken:
    return PresentationToken(
        section="time",
        view_id=view_id,
        request_generation=generation,
        host_epoch=id(host),
        rect=host.rect(),
        device_pixel_ratio=float(host.devicePixelRatioF()),
    )


def _color_frame(widget, color: str) -> QPixmap:
    pixmap = QPixmap(max(1, widget.width()), max(1, widget.height()))
    pixmap.fill(QColor(color))
    return pixmap


class _PaintSurface(QWidget):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.paints = 0
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt callback spelling
        self.paints += 1
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), QColor("#20a060"))
        finally:
            painter.end()


# ---------------------------------------------------------------------------
# E0 current production contracts
# ---------------------------------------------------------------------------

def test_production_enables_all_protocol_sections(qtbot):
    """window.py admits the five chart sections for single-pane user navigation."""
    text = _WINDOW_PY.read_text(encoding="utf-8")
    assert "PAGE_TRANSITION_ENABLED_SECTIONS" in text
    assert PAGE_TRANSITION_ENABLED_SECTIONS == _SECTIONS
    assert "begin_page_transition" not in MainWindow._on_mode_changed.__code__.co_names
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.chart_stack._page_transition_enabled_sections == frozenset(
        PAGE_TRANSITION_ENABLED_SECTIONS,
    )
    assert window.chart_stack.page_transition().motion_policy() == POLICY_LIGHT


def test_programmatic_paths_do_not_begin_page_transition(
    qtbot, qapp, loaded_csv, tmp_path, monkeypatch,
):
    """Project restore, preset apply, init, and same-target clicks stay terminal."""
    begins = []
    orig = ChartStack.begin_page_transition

    def spy(self, **kwargs):
        token = orig(self, **kwargs)
        begins.append(token)
        return token

    monkeypatch.setattr(ChartStack, "begin_page_transition", spy)

    window = MainWindow()
    qtbot.addWidget(window)
    window.resize(1400, 820)
    window.show()
    qtbot.waitExposed(window)
    window.load_file(loaded_csv)
    qapp.processEvents()
    assert begins == [], "initialization / file load must not capture a leave frame"

    window._switch_view(window.view_manager.active)
    qapp.processEvents()
    assert begins == [], "repeating the active Time View is a no-op"

    _new_time_view(qtbot, qapp, window)
    _wait_idle(qtbot, window)
    assert begins == [], "creating a View uses manager.set_active, not user-nav begin"

    window.toolbar._set_mode("fft")
    qapp.processEvents()
    _wait_idle(qtbot, window)
    begins.clear()
    _seed_active_analysis_attachments(window)
    params = dict(window.inspector.fft_ctx.current_params())
    params["overlap"] = 25 if params.get("overlap") != 25 else 50
    window.inspector.fft_ctx._apply_preset(params)
    qapp.processEvents()
    mgr = window.analysis_managers["fft"]
    window._on_analysis_switch("fft", mgr.active)
    qapp.processEvents()
    assert begins == [], "preset apply and same-target FFT clicks stay terminal"

    project = tmp_path / "e0-restore.tlproj"
    window.save_project(project)
    restored = MainWindow()
    qtbot.addWidget(restored)
    restored.show()
    qtbot.waitExposed(restored)
    restored.open_project(project)
    qapp.processEvents()
    assert begins == [], "open_project must not begin_page_transition"


def test_split_view_switch_is_direct_terminal(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    """Split is out of this wave: no leave capture, restore is the terminal layout."""
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)
    _set_checked(window, "speed")
    window.plot_time()
    qapp.processEvents()
    window._capture_current_view()
    _new_time_view(qtbot, qapp, window)
    window._attach_files_to_focused_view([fid])
    _set_checked(window, "torque")
    window.plot_time()
    qapp.processEvents()
    window._capture_current_view()
    _wait_idle(qtbot, window)

    if window.view_manager.active != 0:
        window._switch_view(0)
        qapp.processEvents()
        _wait_idle(qtbot, window)
    begins, captures = _install_transition_spies(monkeypatch, window)
    window.view_manager.set_split(1)
    qapp.processEvents()
    assert window.chart_stack.split_active() is True
    assert begins == []
    assert captures == []

    window._switch_view(1)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    assert window.view_manager.active == 1
    assert window.chart_stack.split_active() is False
    assert all(item["token"] is None for item in begins)
    assert captures == []
    _assert_idle(window.chart_stack.page_transition())


def test_ultraview_and_batch_open_are_direct_terminal(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    """Tool windows are not chart-stack handoffs; opening them must not grab."""
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    begins, captures = _install_transition_spies(monkeypatch, window)
    window.open_batch()
    qapp.processEvents()
    sheet = window._alive_tool_dialog("_batch_sheet")
    assert sheet is not None
    assert begins == []
    assert captures == []
    sheet.close()
    qapp.processEvents()

    window.open_ultraview()
    qapp.processEvents()
    uv_sheet = window._alive_tool_dialog("_ultraview_sheet")
    assert uv_sheet is not None
    assert begins == []
    assert captures == []
    uv_sheet.close()
    qapp.processEvents()
    _assert_idle(window.chart_stack.page_transition())


def test_time_single_pane_user_switch_keeps_light_and_matches_off_terminal(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    """Same production entry as test_time_tab_switch_completes_natural_fade."""
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)
    _set_checked(window, "speed")
    window.plot_time()
    qapp.processEvents()
    xlim_0 = _narrow_xlim(window, 0.20, 0.62)
    window._capture_current_view()
    view0_id = window.view_manager.get(0).view_id

    _new_time_view(qtbot, qapp, window)
    window._attach_files_to_focused_view([fid])
    _set_checked(window, "torque")
    window.plot_time()
    qapp.processEvents()
    xlim_1 = _narrow_xlim(window, 0.10, 0.55)
    window._capture_current_view()
    view1_id = window.view_manager.get(1).view_id
    _wait_idle(qtbot, window)

    if window.view_manager.active != 0:
        window.view_tabbar.switch_requested.emit(0)
        _wait_idle(qtbot, window)

    controller = window.chart_stack.page_transition()
    started, cancelled, finished = [], [], []
    controller.transition_started.connect(started.append)
    controller.transition_cancelled.connect(cancelled.append)
    controller.transition_finished.connect(finished.append)
    begins, captures = _install_transition_spies(monkeypatch, window)
    restores = []
    orig_render = window._render_view_to_canvas

    def render(*args, **kwargs):
        restores.append(1)
        return orig_render(*args, **kwargs)

    monkeypatch.setattr(window, "_render_view_to_canvas", render)

    window.view_tabbar.switch_requested.emit(1)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)

    assert cancelled == []
    assert started and finished
    assert window.view_manager.active == 1
    assert [item["token"] is not None for item in begins] == [True]
    assert captures and captures[0]["null"] is False
    assert all(item["exclude_overlay"] is False for item in captures)
    light = _time_terminal(window)
    assert light["view_id"] == view1_id
    assert light["channels"] == ((fid, "torque"),)
    assert light["xlim"] == pytest.approx(xlim_1)
    light_restores = len(restores)

    window.chart_stack.set_page_transition_motion_policy(POLICY_OFF)
    begins.clear()
    captures.clear()
    restores.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    window.view_tabbar.switch_requested.emit(0)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    off_0 = _time_terminal(window)
    assert off_0["view_id"] == view0_id
    assert off_0["channels"] == ((fid, "speed"),)
    assert off_0["xlim"] == pytest.approx(xlim_0)
    assert all(item["token"] is None for item in begins)
    assert captures == []
    assert started == [] and cancelled == [] and finished == []

    window.view_tabbar.switch_requested.emit(1)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    off_1 = _time_terminal(window)
    _assert_time_terminals_match(off_1, light)
    assert len(restores) >= light_restores
    _assert_idle(controller)


def test_uncomputed_fft_preview_switch_is_direct_terminal(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    """Preview-only / cache-miss FFT Views are not captured even when admitted."""
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    _pause_page_transition(window)
    window.toolbar._set_mode("fft")
    qapp.processEvents()
    _seed_active_analysis_attachments(window)
    fid = _fid(window)
    canvas = window.chart_stack.page_fft.pane_canvas(0)
    window.navigator.set_checked_channels([(fid, "speed")])
    qapp.processEvents()
    qtbot.waitUntil(
        lambda: (fid, "speed") in {
            (item[0], item[1]) for item in window.navigator.get_checked_channels()
        },
        timeout=2000,
    )
    if not canvas._time_curves:
        window._refresh_fft_time_preview()
        qapp.processEvents()
    qtbot.waitUntil(lambda: len(canvas._time_curves) >= 1, timeout=2000)
    submitted, computes = _install_compute_spies(monkeypatch, window)
    assert canvas.has_result() is False
    assert submitted == [] and computes == []

    window._on_analysis_new("fft")
    qapp.processEvents()
    assert window.analysis_managers["fft"].active == 1
    assert len(canvas._time_curves) == 0

    _resume_page_transition(window)
    begins, captures = _install_transition_spies(monkeypatch, window)
    window.chart_stack.page_fft.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    preview = _fft_terminal(window)
    assert preview["active"] == 0
    assert preview["amp_curves"] == 0
    assert preview["time_curves"] == 1
    assert preview["has_result"] is False
    assert begins == []
    assert captures == []
    assert submitted == [] and computes == []
    _assert_idle(window.chart_stack.page_transition())


def test_frf_and_heatmap_empty_switches_do_not_compute(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    """Empty FRF/heatmap switches may fade; they must not start compute."""
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    submitted, computes, requests = _install_frf_compute_spies(monkeypatch, window)
    _pause_page_transition(window)
    window.toolbar._set_mode("frf")
    qapp.processEvents()
    window._on_analysis_new("frf")
    qapp.processEvents()
    _resume_page_transition(window)
    controller, started, cancelled, finished = _connect_transition_lifecycle(
        window,
    )
    window.chart_stack.page_frf.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    assert window.analysis_managers["frf"].active == 0
    assert submitted == [] and computes == [] and requests == []
    for section, page in (
        ("fft_time", window.chart_stack.page_fft_time),
        ("order", window.chart_stack.page_order),
    ):
        _pause_page_transition(window)
        window.toolbar._set_mode(section)
        qapp.processEvents()
        window._on_analysis_new(section)
        qapp.processEvents()
        _resume_page_transition(window)
        started.clear()
        cancelled.clear()
        finished.clear()
        page.tabbar.switch_requested.emit(0)
        qapp.processEvents()
        _wait_idle(qtbot, window)
        assert window.analysis_managers[section].active == 0, section
    assert submitted == [] and computes == []
    _assert_idle(window.chart_stack.page_transition())


def test_queued_freeze_does_not_freeze_pending_redirect_and_thaws(
    qtbot, qapp,
):
    """Shared-layer freeze is queued; a pending successor must still paint."""
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(240, 160)
    host.show()
    qtbot.waitExposed(host)
    controller = PageTransitionController(host, policy=POLICY_LIGHT)
    surface = _PaintSurface(host)
    surface.setGeometry(host.rect())
    surface.show()
    qtbot.waitExposed(surface)
    assert surface.updatesEnabled()

    source = _host_token(host, "A", 7)
    target = _host_token(host, "B", 7)
    assert controller.begin_departure(source, _color_frame(host, "#204080"))
    assert controller.arm_target(target)
    assert controller.watch_input_targets(target, (surface,))
    assert controller.accept_target(target)
    assert surface.updatesEnabled()

    next_source = _host_token(host, "B", 8)
    next_target = _host_token(host, "C", 8)
    assert controller.begin_departure(next_source, _color_frame(host, "#d08020"))
    assert controller.arm_target(next_target)
    assert controller.watch_input_targets(next_target, (surface,))
    assert controller._target_ready is False
    qapp.processEvents()
    assert surface.updatesEnabled(), "stale freeze must not block the pending first frame"

    assert controller.accept_target(next_target)
    qapp.processEvents()
    qapp.processEvents()
    assert controller.is_active()
    assert surface.updatesEnabled() is False
    controller.cancel("e0-freeze-probe")
    assert surface.updatesEnabled()
    _assert_idle(controller)


def test_content_invalidation_listen_is_required_for_managed_canvases():
    """E1/E3/E4: FFT, FRF, and heatmap expose content+paint fences; stack requires them."""
    import inspect

    from mf4_analyzer.ui.chart_stack.stack import ChartStack as LiveStack
    from mf4_analyzer.ui.pg_canvas.frf_canvas import PgFrfCanvas
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import PgHeatmapCanvas
    from mf4_analyzer.ui.pg_canvas.line_canvas import PgLineCanvas

    request_src = inspect.getsource(LiveStack.request_page_transition_target)
    assert "presentation_content_invalidated" in request_src
    assert "target-has-no-content-fence" in request_src
    assert "if content_signal is not None:" not in request_src
    assert "page_transition_input_widgets" in request_src
    assert "presentation_paint_acknowledged" in PgLineCanvas.__dict__
    assert "presentation_content_invalidated" in PgLineCanvas.__dict__
    assert "presentation_paint_acknowledged" in PgFrfCanvas.__dict__
    assert "presentation_content_invalidated" in PgFrfCanvas.__dict__
    assert "presentation_paint_acknowledged" in PgHeatmapCanvas.__dict__
    assert "presentation_content_invalidated" in PgHeatmapCanvas.__dict__
    assert _STACK_PY.is_file() and _LINE_CANVAS_PY.is_file()


def _admit_fft_page_transition_for_test(window):
    """Ensure FFT is admitted on this window (production already includes it)."""
    window.chart_stack.set_page_transition_enabled_sections(
        PAGE_TRANSITION_ENABLED_SECTIONS,
    )
    _resume_page_transition(window)


def _admit_frf_page_transition_for_test(window, *, with_fft=False):
    """Ensure FRF is admitted on this window (production already includes it)."""
    del with_fft
    window.chart_stack.set_page_transition_enabled_sections(
        PAGE_TRANSITION_ENABLED_SECTIONS,
    )
    _resume_page_transition(window)


def _frf_result_for_file(window, fid):
    from mf4_analyzer.signal.frf import FrfEffectiveFacts, FrfResult

    fd = window.files[fid]
    time = fd.time_array
    t0, t1 = float(time[0]), float(time[-1])
    fs = float(fd.fs)
    frequency = np.array([1.0, 10.0, 20.0, 40.0])
    ones = np.ones(frequency.size)
    facts = FrfEffectiveFacts(
        requested_t_win_s=0.5,
        requested_nperseg=500,
        nperseg=500,
        nfft=500,
        noverlap=250,
        hop=250,
        segments=6,
        fs=fs,
        df=2.0,
        n_samples=len(time),
        time_start=t0,
        time_end=t1,
        window="hanning",
        periodic_window=True,
        detrend="constant",
        max_time_jitter=0.0,
        max_time_difference=0.0,
        invalid_bins=0,
    )
    return FrfResult(
        frequencies=frequency,
        transfer=(ones * 2).astype(complex),
        pxx=ones,
        pyy=ones,
        pxy=ones.astype(complex),
        coherence=ones,
        effective=facts,
    ), (t0, t1)


def _seed_frf_view_cache(window, state, fid):
    result, span = _frf_result_for_file(window, fid)
    pane = state.panes[0]
    pane.input_source = (fid, "speed")
    pane.output_source = (fid, "torque")
    pane.effective_time_range = span
    ids = list(state.attached_file_ids or ())
    if fid not in ids:
        ids.append(fid)
    state.attached_file_ids = ids
    window._refresh_analysis_candidates("frf")
    window._apply_frf_sources(state, sync_effective_facts=False)
    key = window._frf_cache_key_for_pane(state, pane)
    assert key is not None
    window.analysis_caches["frf"].put(key, result)
    return result


def _curve_n(curve) -> int:
    data = getattr(curve, "xData", None)
    if data is None:
        return 0
    return int(len(data))


def _frf_terminal(win):
    mgr = win.analysis_managers["frf"]
    state = mgr.get(mgr.active)
    pane = state.panes[0]
    canvas = win.chart_stack.page_frf.pane_canvas(0)
    return {
        "view_id": state.view_id,
        "active": mgr.active,
        "input": tuple(pane.input_source) if pane.input_source else None,
        "output": tuple(pane.output_source) if pane.output_source else None,
        "has_result": bool(canvas.has_result()),
        "state": canvas.state(),
        "mag": _curve_n(canvas._magnitude_curve),
        "phase": _curve_n(canvas._phase_curve),
        "coh": _curve_n(canvas._coherence_curve),
        "host": id(canvas._glw),
        "mode": win.chart_stack.current_mode(),
        "panes": win.chart_stack.page_frf.pane_count(),
    }


def _frf_cached_and_empty_views(qtbot, qapp, window):
    """View 0: cached FRF on one host. View 1: empty. Leaves active on 1."""
    fid = _fid(window)
    _pause_page_transition(window)
    window.toolbar._set_mode("frf")
    qapp.processEvents()
    _seed_active_analysis_attachments(window)
    mgr = window.analysis_managers["frf"]
    state = mgr.get(mgr.active)
    state.params.update(window.inspector.frf_ctx.current_params())
    _seed_frf_view_cache(window, state, fid)
    window._render_frf_view_from_cache(state)
    canvas = window.chart_stack.page_frf.pane_canvas(0)
    qtbot.waitUntil(canvas.has_result, timeout=2500)
    window._on_analysis_new("frf")
    qapp.processEvents()
    assert mgr.active == 1
    return fid, canvas


def _install_frf_compute_spies(monkeypatch, window):
    submitted, computes = _install_compute_spies(monkeypatch, window)
    requests = []
    orig_request = window._frf_coordinator.request

    def request(candidate):
        requests.append(1)
        return orig_request(candidate)

    monkeypatch.setattr(window._frf_coordinator, "request", request)
    return submitted, computes, requests


def _fft_preview_and_empty_views(qtbot, qapp, window):
    """View 0: time preview, uncomputed. View 1: empty. Leaves active on 1."""
    _pause_page_transition(window)
    window.toolbar._set_mode("fft")
    qapp.processEvents()
    _seed_active_analysis_attachments(window)
    fid = _fid(window)
    canvas = window.chart_stack.page_fft.pane_canvas(0)
    window.navigator.set_checked_channels([(fid, "speed")])
    qapp.processEvents()
    qtbot.waitUntil(
        lambda: (fid, "speed") in {
            (item[0], item[1]) for item in window.navigator.get_checked_channels()
        },
        timeout=2000,
    )
    if not canvas._time_curves:
        window._refresh_fft_time_preview()
        qapp.processEvents()
    qtbot.waitUntil(lambda: len(canvas._time_curves) >= 1, timeout=2000)
    window._on_analysis_new("fft")
    qapp.processEvents()
    assert window.analysis_managers["fft"].active == 1
    return fid, canvas


def _connect_transition_lifecycle(window):
    controller = window.chart_stack.page_transition()
    started, cancelled, finished = [], [], []
    controller.transition_started.connect(started.append)
    controller.transition_cancelled.connect(cancelled.append)
    controller.transition_finished.connect(finished.append)
    return controller, started, cancelled, finished


# ---------------------------------------------------------------------------
# E1 FFT internal View protocol (production now admits fft)
# ---------------------------------------------------------------------------

def test_e1_fft_cache_hit_light_fade(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    _fft_preview_and_empty_views(qtbot, qapp, window)
    window.chart_stack.page_fft.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    window.do_fft()
    qapp.processEvents()
    cached = _fft_terminal(window)
    assert cached["has_result"] is True
    window.chart_stack.page_fft.tabbar.switch_requested.emit(1)
    qapp.processEvents()
    submitted, computes = _install_compute_spies(monkeypatch, window)
    restores = []
    orig_restore = window._render_analysis_view_from_cache

    def restore(section, state):
        restores.append(section)
        return orig_restore(section, state)

    monkeypatch.setattr(window, "_render_analysis_view_from_cache", restore)
    _admit_fft_page_transition_for_test(window)
    controller, started, cancelled, finished = _connect_transition_lifecycle(window)
    begins, captures = _install_transition_spies(monkeypatch, window)

    window.chart_stack.page_fft.tabbar.switch_requested.emit(0)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)

    assert cancelled == []
    assert started and finished
    assert [item["token"] is not None for item in begins] == [True]
    assert captures and captures[0]["null"] is False
    assert submitted == [] and computes == []
    light = _fft_terminal(window)
    assert light == cached
    light_restores = list(restores)
    assert light_restores

    window.chart_stack.set_page_transition_motion_policy(POLICY_OFF)
    begins.clear()
    captures.clear()
    restores.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    window.chart_stack.page_fft.tabbar.switch_requested.emit(1)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    window.chart_stack.page_fft.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    assert _fft_terminal(window) == cached
    assert all(item["token"] is None for item in begins)
    assert captures == []
    assert started == [] and cancelled == [] and finished == []
    assert submitted == [] and computes == []
    assert restores == ["fft", "fft"]
    _assert_idle(controller)


def test_e1_fft_cache_miss_stays_direct_until_admitted(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    _fft_preview_and_empty_views(qtbot, qapp, window)
    submitted, computes = _install_compute_spies(monkeypatch, window)
    _admit_fft_page_transition_for_test(window)
    controller, started, cancelled, finished = _connect_transition_lifecycle(window)
    begins, captures = _install_transition_spies(monkeypatch, window)

    window.chart_stack.page_fft.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    _wait_idle(qtbot, window)

    preview = _fft_terminal(window)
    assert preview["active"] == 0
    assert preview["has_result"] is False
    assert preview["amp_curves"] == 0
    assert preview["time_curves"] >= 1
    assert begins == []
    assert captures == []
    assert submitted == [] and computes == []
    assert started == [] and finished == []
    _assert_idle(controller)


def test_e1_fft_preview_only_retained_path(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    _fft_preview_and_empty_views(qtbot, qapp, window)
    window.chart_stack.page_fft.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    canvas = window.chart_stack.page_fft.pane_canvas(0)
    content = []
    canvas.presentation_content_invalidated.connect(lambda: content.append(True))
    window._refresh_fft_time_preview()
    qapp.processEvents()
    assert content
    assert canvas.has_result() is False
    assert canvas._time_curves
    submitted, computes = _install_compute_spies(monkeypatch, window)
    restores = []
    orig_restore = window._render_analysis_view_from_cache

    def restore(section, state):
        restores.append(section)
        return orig_restore(section, state)

    monkeypatch.setattr(window, "_render_analysis_view_from_cache", restore)
    _admit_fft_page_transition_for_test(window)
    mgr = window.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    window._fft_last_render_sig = window._fft_render_signature()
    controller, started, cancelled, finished = _connect_transition_lifecycle(window)
    token = window.chart_stack.begin_page_transition(
        source_section="fft",
        source_view_id="retained-preview-source",
        target_section="fft",
        target_view_id=state.view_id,
        pane_signature=("fft", "single"),
    )
    assert token is not None
    window._enter_fft_mode()
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    assert restores == []
    assert submitted == [] and computes == []
    assert cancelled == []
    assert started and finished
    assert canvas.has_result() is False
    assert canvas._time_curves
    _assert_idle(controller)


def test_e1_fft_empty_state_light_fade(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    _fft_preview_and_empty_views(qtbot, qapp, window)
    window.chart_stack.page_fft.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    window.do_fft()
    qapp.processEvents()
    cached = _fft_terminal(window)
    assert cached["has_result"] is True
    submitted, computes = _install_compute_spies(monkeypatch, window)
    _admit_fft_page_transition_for_test(window)
    controller, started, cancelled, finished = _connect_transition_lifecycle(window)
    begins, captures = _install_transition_spies(monkeypatch, window)

    window.chart_stack.page_fft.tabbar.switch_requested.emit(1)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)

    empty = _fft_terminal(window)
    assert empty["active"] == 1
    assert empty["has_result"] is False
    assert empty["amp_curves"] == 0
    assert empty["entries"] == ()
    assert cancelled == []
    assert started and finished
    assert [item["token"] is not None for item in begins] == [True]
    assert submitted == [] and computes == []
    assert empty != cached

    window.chart_stack.set_page_transition_motion_policy(POLICY_OFF)
    begins.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    window.chart_stack.page_fft.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    window.chart_stack.page_fft.tabbar.switch_requested.emit(1)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    assert _fft_terminal(window) == empty
    assert all(item["token"] is None for item in begins)
    assert started == [] and finished == []
    _assert_idle(controller)


def test_e1_fft_retained_reveal_ready_path(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    """Ready is presentation-complete, not facts_synced_by_render."""
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    _fft_preview_and_empty_views(qtbot, qapp, window)
    window.chart_stack.page_fft.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    window.do_fft()
    qapp.processEvents()
    submitted, computes = _install_compute_spies(monkeypatch, window)
    restores = []
    orig_restore = window._render_analysis_view_from_cache

    def restore(section, state):
        restores.append(section)
        return orig_restore(section, state)

    monkeypatch.setattr(window, "_render_analysis_view_from_cache", restore)
    armed = []
    orig_request = window.chart_stack.request_page_transition_target_for

    def request(section, view_id, canvases):
        armed.append((section, view_id))
        return orig_request(section, view_id, canvases)

    monkeypatch.setattr(
        window.chart_stack, "request_page_transition_target_for", request,
    )
    _admit_fft_page_transition_for_test(window)
    mgr = window.analysis_managers["fft"]
    state = mgr.get(mgr.active)
    window._fft_last_render_sig = window._fft_render_signature()
    controller, started, cancelled, finished = _connect_transition_lifecycle(window)
    token = window.chart_stack.begin_page_transition(
        source_section="fft",
        source_view_id="retained-reveal-source",
        target_section="fft",
        target_view_id=state.view_id,
        pane_signature=("fft", "single"),
    )
    assert token is not None
    window._on_analysis_view_switched("fft", mgr.active, render=False)
    assert armed == []
    assert restores == []
    window._enter_fft_mode()
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled) or bool(armed), timeout=2500)
    _wait_idle(qtbot, window)
    assert restores == []
    assert armed == [("fft", state.view_id)]
    assert submitted == [] and computes == []
    assert cancelled == []
    assert started and finished
    _assert_idle(controller)


def _global_rect(widget) -> QRect:
    return QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size())


def _assert_overlay_spares_navigation(window) -> None:
    overlay = window.chart_stack.page_transition()._overlay
    assert overlay.isVisible()
    ov = _global_rect(overlay)
    toolbar = window.toolbar
    for button in (
        toolbar.btn_mode_time,
        toolbar.btn_mode_fft,
        toolbar.btn_mode_fft_time,
        toolbar.btn_mode_frf,
        toolbar.btn_mode_order,
    ):
        hit = _global_rect(button)
        assert not ov.intersects(hit), "overlay must not cover Section mode buttons"
    inspector = getattr(window, "inspector", None)
    if inspector is not None and inspector.isVisible():
        assert not ov.intersects(_global_rect(inspector))
    stack = window.chart_stack.stack
    assert overlay.height() < stack.height()
    plot = window.chart_stack.page_transition_plot_surface_rect()
    assert plot.contains(overlay.geometry()) or overlay.geometry() == plot
    mode = window.chart_stack.current_mode()
    if mode == "time":
        tab = window.view_tabbar
    else:
        page = {
            "fft": window.chart_stack.page_fft,
            "fft_time": window.chart_stack.page_fft_time,
            "frf": window.chart_stack.page_frf,
            "order": window.chart_stack.page_order,
        }.get(mode)
        tab = None if page is None else page.tabbar
    if tab is not None and tab.isVisible():
        assert not ov.intersects(_global_rect(tab)), (
            "overlay covers View tabs; plot-surface crop is required"
        )


def _block_page_transition_ready(window):
    orig = window.chart_stack.request_page_transition_target_for

    def blocked(section, view_id, canvases):
        return False

    window.chart_stack.request_page_transition_target_for = blocked
    return orig


def _restore_production_enabled_sections(window):
    window.chart_stack.set_page_transition_enabled_sections(
        PAGE_TRANSITION_ENABLED_SECTIONS,
    )
    _resume_page_transition(window)


def _section_terminal(win, section):
    if section == "time":
        return _time_terminal(win)
    if section == "fft":
        return _fft_terminal(win)
    if section == "frf":
        return _frf_terminal(win)
    return _heatmap_terminal(win, section)


def _assert_section_terminals_match(section, actual, expected) -> None:
    if section == "time":
        _assert_time_terminals_match(actual, expected)
        return
    assert actual == expected, section


def _assert_no_transition_residue(window) -> None:
    stack = window.chart_stack
    controller = stack.page_transition()
    _assert_idle(controller)
    assert controller._overlay.isVisible() is False
    assert controller._frozen_input_targets == []
    assert stack._page_transition_target is None
    assert stack._page_transition_ready_slots == []
    assert stack._page_transition_content_slots == []


def _ensure_section(qtbot, qapp, window, section, timeout=2500) -> None:
    if window.chart_stack.current_mode() != section:
        window.toolbar._set_mode(section)
        qapp.processEvents()
    _wait_idle(qtbot, window, timeout=timeout)


def _seed_all_section_cache_homes(qtbot, qapp, window):
    """One cached or plotted home View per section; stay single-pane."""
    _pause_page_transition(window)
    fid = _fid(window)
    _set_checked(window, "speed")
    window.plot_time()
    qapp.processEvents()
    window._capture_current_view()

    window.toolbar._set_mode("fft")
    qapp.processEvents()
    _seed_active_analysis_attachments(window)
    window.navigator.set_checked_channels([(fid, "speed")])
    qapp.processEvents()
    fft_canvas = window.chart_stack.page_fft.pane_canvas(0)
    if not fft_canvas._time_curves:
        window._refresh_fft_time_preview()
        qapp.processEvents()
    window.do_fft()
    qapp.processEvents()
    qtbot.waitUntil(fft_canvas.has_result, timeout=2500)

    window.toolbar._set_mode("frf")
    qapp.processEvents()
    _seed_active_analysis_attachments(window)
    mgr = window.analysis_managers["frf"]
    state = mgr.get(mgr.active)
    state.params.update(window.inspector.frf_ctx.current_params())
    _seed_frf_view_cache(window, state, fid)
    window._render_frf_view_from_cache(state)
    qtbot.waitUntil(
        window.chart_stack.page_frf.pane_canvas(0).has_result, timeout=2500,
    )

    window.toolbar._set_mode("fft_time")
    qapp.processEvents()
    _seed_active_analysis_attachments(window)
    mgr = window.analysis_managers["fft_time"]
    state = mgr.get(mgr.active)
    _seed_fft_time_view_cache(window, state, fid)
    window._render_analysis_view_from_cache("fft_time", state)
    qtbot.waitUntil(
        window.chart_stack.page_fft_time.pane_canvas(0).has_result, timeout=2500,
    )

    window.toolbar._set_mode("order")
    qapp.processEvents()
    _seed_active_analysis_attachments(window)
    mgr = window.analysis_managers["order"]
    state = mgr.get(mgr.active)
    _seed_order_view_cache(window, state, fid)
    window._render_analysis_view_from_cache("order", state)
    qtbot.waitUntil(
        window.chart_stack.page_order.pane_canvas(0).has_result, timeout=2500,
    )

    _restore_production_enabled_sections(window)
    window.chart_stack.set_page_transition_motion_policy(POLICY_LIGHT)
    window.toolbar._set_mode("time")
    qapp.processEvents()
    _wait_idle(qtbot, window)
    return fid


# ---------------------------------------------------------------------------
# E2 Time ↔ FFT user navigation
# ---------------------------------------------------------------------------

def test_e2_time_to_fft_and_back_user_navigation(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)
    _set_checked(window, "speed")
    window.plot_time()
    qapp.processEvents()
    xlim_time = _narrow_xlim(window, 0.20, 0.62)
    window._capture_current_view()
    time_home = _time_terminal(window)

    _fft_preview_and_empty_views(qtbot, qapp, window)
    window.chart_stack.page_fft.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    window.do_fft()
    qapp.processEvents()
    cached_fft = _fft_terminal(window)
    assert cached_fft["has_result"] is True

    begins, captures = _install_transition_spies(monkeypatch, window)
    submitted, computes = _install_compute_spies(monkeypatch, window)
    window.toolbar._set_mode("time")
    qapp.processEvents()
    _wait_idle(qtbot, window)
    _assert_time_terminals_match(_time_terminal(window), time_home)
    begins.clear()
    captures.clear()

    _admit_fft_page_transition_for_test(window)
    controller, started, cancelled, finished = _connect_transition_lifecycle(
        window,
    )
    restores = []
    orig_restore = window._render_analysis_view_from_cache

    def restore(section, state):
        restores.append(section)
        return orig_restore(section, state)

    monkeypatch.setattr(window, "_render_analysis_view_from_cache", restore)

    window.toolbar._set_mode("fft")
    _assert_overlay_spares_navigation(window)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    assert cancelled == []
    assert started and finished
    assert [item["token"] is not None for item in begins] == [True]
    assert captures and captures[0]["null"] is False
    assert submitted == [] and computes == []
    light_fft = _fft_terminal(window)
    assert light_fft == cached_fft

    begins.clear()
    captures.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    restores.clear()
    window.toolbar._set_mode("time")
    _assert_overlay_spares_navigation(window)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    assert cancelled == []
    assert started and finished
    assert [item["token"] is not None for item in begins] == [True]
    assert submitted == [] and computes == []
    light_time = _time_terminal(window)
    _assert_time_terminals_match(light_time, time_home)
    assert light_time["xlim"] == pytest.approx(xlim_time)

    window.chart_stack.set_page_transition_motion_policy(POLICY_OFF)
    begins.clear()
    captures.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    restores.clear()
    window.toolbar._set_mode("fft")
    qapp.processEvents()
    _wait_idle(qtbot, window)
    assert _fft_terminal(window) == cached_fft
    window.toolbar._set_mode("time")
    qapp.processEvents()
    _wait_idle(qtbot, window)
    _assert_time_terminals_match(_time_terminal(window), light_time)
    assert all(item["token"] is None for item in begins)
    assert captures == []
    assert started == [] and finished == []
    assert submitted == [] and computes == []

    window.chart_stack.page_fft.tabbar.switch_requested.emit(1)
    qapp.processEvents()
    window.toolbar._set_mode("fft")
    qapp.processEvents()
    _wait_idle(qtbot, window)
    empty_fft = _fft_terminal(window)
    assert empty_fft["active"] == 1
    assert empty_fft["has_result"] is False
    window.toolbar._set_mode("time")
    qapp.processEvents()
    _wait_idle(qtbot, window)

    window.chart_stack.set_page_transition_motion_policy(POLICY_LIGHT)
    begins.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    window.toolbar._set_mode("fft")
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    assert cancelled == []
    assert started and finished
    assert _fft_terminal(window) == empty_fft
    assert submitted == [] and computes == []

    window.chart_stack.set_page_transition_motion_policy(POLICY_OFF)
    window.toolbar._set_mode("time")
    qapp.processEvents()
    _wait_idle(qtbot, window)
    window.toolbar._set_mode("fft")
    qapp.processEvents()
    _wait_idle(qtbot, window)
    assert _fft_terminal(window) == empty_fft
    window.toolbar._set_mode("time")
    qapp.processEvents()
    _wait_idle(qtbot, window)

    window.chart_stack.set_page_transition_motion_policy(POLICY_LIGHT)
    window.chart_stack.page_fft.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    window.toolbar._set_mode("time")
    qapp.processEvents()
    _wait_idle(qtbot, window)
    begins.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    window.toolbar._set_mode("fft")
    token_b = window.chart_stack._page_transition_target
    fft_canvas = window.chart_stack.page_fft.pane_canvas(0)
    window.toolbar._set_mode("time")
    if token_b is not None:
        window.chart_stack._on_page_transition_target_painted(
            token_b, fft_canvas, token_b,
        )
        window.chart_stack.request_page_transition_target(
            token_b, (fft_canvas,),
        )
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    assert window.chart_stack.current_mode() == "time"
    _assert_time_terminals_match(_time_terminal(window), light_time)
    _assert_idle(controller)

    orig_ready = _block_page_transition_ready(window)
    try:
        window.toolbar._set_mode("fft")
        qtbot.waitUntil(
            lambda: window.chart_stack.page_transition().image_bytes() > 0,
            timeout=2500,
        )
        active = window.analysis_managers["fft"].active
        window._on_analysis_delete("fft", active)
        _wait_idle(qtbot, window)
        _assert_idle(controller)
        assert window.chart_stack.page_transition()._overlay.isVisible() is False

        window.toolbar._set_mode("time")
        qapp.processEvents()
        window.toolbar._set_mode("fft")
        qtbot.waitUntil(
            lambda: window.chart_stack.page_transition().image_bytes() > 0,
            timeout=2500,
        )
        window._close(fid, force=True)
        qapp.processEvents()
        _assert_idle(controller)
        assert window.chart_stack.page_transition()._overlay.isVisible() is False
    finally:
        window.chart_stack.request_page_transition_target_for = orig_ready
    assert submitted == [] and computes == []


# ---------------------------------------------------------------------------
# E3–E4 reserved names: skip until that wave is dispatched
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# E3 FRF internal View + Time/FFT ↔ FRF (this window may admit frf; production does not)
# ---------------------------------------------------------------------------

def test_e3_frf_multi_subplot_internal_switch(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    _frf_cached_and_empty_views(qtbot, qapp, window)
    window.chart_stack.page_frf.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    cached = _frf_terminal(window)
    assert cached["has_result"] is True
    assert cached["panes"] == 1
    assert cached["mag"] >= 1 and cached["phase"] >= 1 and cached["coh"] >= 1
    canvas = window.chart_stack.page_frf.pane_canvas(0)
    assert canvas._plot_magnitude.scene() is canvas._glw.scene()
    assert canvas._plot_phase.scene() is canvas._glw.scene()
    assert canvas._plot_coherence.scene() is canvas._glw.scene()
    window.chart_stack.page_frf.tabbar.switch_requested.emit(1)
    qapp.processEvents()
    submitted, computes, requests = _install_frf_compute_spies(monkeypatch, window)
    restores = []
    orig_restore = window._render_analysis_view_from_cache

    def restore(section, state):
        restores.append(section)
        return orig_restore(section, state)

    monkeypatch.setattr(window, "_render_analysis_view_from_cache", restore)
    _admit_frf_page_transition_for_test(window)
    controller, started, cancelled, finished = _connect_transition_lifecycle(window)
    begins, captures = _install_transition_spies(monkeypatch, window)

    window.chart_stack.page_frf.tabbar.switch_requested.emit(0)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)

    assert cancelled == []
    assert started and finished
    assert [item["token"] is not None for item in begins] == [True]
    assert captures and captures[0]["null"] is False
    assert submitted == [] and computes == [] and requests == []
    light = _frf_terminal(window)
    assert light == cached
    assert restores

    window.chart_stack.set_page_transition_motion_policy(POLICY_OFF)
    begins.clear()
    captures.clear()
    restores.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    window.chart_stack.page_frf.tabbar.switch_requested.emit(1)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    window.chart_stack.page_frf.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    assert _frf_terminal(window) == cached
    assert all(item["token"] is None for item in begins)
    assert captures == []
    assert started == [] and cancelled == [] and finished == []
    assert submitted == [] and computes == [] and requests == []
    assert restores == ["frf", "frf"]

    window.chart_stack.set_page_transition_motion_policy(POLICY_LIGHT)
    begins.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    window.chart_stack.page_frf.tabbar.switch_requested.emit(1)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    empty = _frf_terminal(window)
    assert empty["active"] == 1
    assert empty["has_result"] is False
    assert cancelled == []
    assert started and finished
    assert submitted == [] and computes == [] and requests == []

    window.chart_stack.set_page_transition_motion_policy(POLICY_OFF)
    window.chart_stack.page_frf.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    window.chart_stack.page_frf.tabbar.switch_requested.emit(1)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    assert _frf_terminal(window) == empty
    _assert_idle(controller)

    fid = _fid(window)
    mgr = window.analysis_managers["frf"]
    window._on_analysis_new("frf")
    qapp.processEvents()
    miss_idx = mgr.active
    miss = mgr.get(miss_idx)
    miss.attached_file_ids = [fid]
    miss.panes[0].input_source = (fid, "speed")
    miss.panes[0].output_source = (fid, "torque")
    miss.panes[0].effective_time_range = None
    window._refresh_analysis_candidates("frf")
    window._apply_frf_sources(miss, sync_effective_facts=False)
    window.chart_stack.set_page_transition_motion_policy(POLICY_LIGHT)
    window.chart_stack.page_frf.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    begins.clear()
    captures.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    window.chart_stack.page_frf.tabbar.switch_requested.emit(miss_idx)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    assert begins == []
    assert captures == []
    assert started == [] and finished == []
    assert submitted == [] and computes == [] and requests == []
    _assert_idle(controller)


def test_e3_time_and_fft_to_frf_user_navigation(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)
    _set_checked(window, "speed")
    window.plot_time()
    qapp.processEvents()
    xlim_time = _narrow_xlim(window, 0.20, 0.62)
    window._capture_current_view()
    time_home = _time_terminal(window)

    _fft_preview_and_empty_views(qtbot, qapp, window)
    window.chart_stack.page_fft.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    window.do_fft()
    qapp.processEvents()
    cached_fft = _fft_terminal(window)
    assert cached_fft["has_result"] is True

    window.toolbar._set_mode("time")
    qapp.processEvents()
    _frf_cached_and_empty_views(qtbot, qapp, window)
    window.chart_stack.page_frf.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    cached_frf = _frf_terminal(window)
    assert cached_frf["has_result"] is True
    window.toolbar._set_mode("time")
    qapp.processEvents()
    _wait_idle(qtbot, window)

    submitted, computes, requests = _install_frf_compute_spies(monkeypatch, window)
    _admit_frf_page_transition_for_test(window, with_fft=True)
    controller, started, cancelled, finished = _connect_transition_lifecycle(
        window,
    )
    begins, captures = _install_transition_spies(monkeypatch, window)

    window.toolbar._set_mode("frf")
    _assert_overlay_spares_navigation(window)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    assert cancelled == []
    assert started and finished
    assert captures and captures[0]["null"] is False
    assert submitted == [] and computes == [] and requests == []
    assert _frf_terminal(window) == cached_frf

    begins.clear()
    captures.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    window.toolbar._set_mode("time")
    _assert_overlay_spares_navigation(window)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    assert cancelled == []
    assert started and finished
    _assert_time_terminals_match(_time_terminal(window), time_home)
    assert _time_terminal(window)["xlim"] == pytest.approx(xlim_time)

    begins.clear()
    captures.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    window.toolbar._set_mode("fft")
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    assert cancelled == []
    assert started and finished
    assert _fft_terminal(window) == cached_fft

    begins.clear()
    captures.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    window.toolbar._set_mode("frf")
    _assert_overlay_spares_navigation(window)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    assert cancelled == []
    assert started and finished
    assert _frf_terminal(window) == cached_frf

    begins.clear()
    captures.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    window.toolbar._set_mode("fft")
    _assert_overlay_spares_navigation(window)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    assert cancelled == []
    assert started and finished
    assert _fft_terminal(window) == cached_fft
    assert submitted == [] and computes == [] and requests == []

    window.chart_stack.set_page_transition_motion_policy(POLICY_OFF)
    begins.clear()
    captures.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    window.toolbar._set_mode("frf")
    qapp.processEvents()
    _wait_idle(qtbot, window)
    assert _frf_terminal(window) == cached_frf
    window.toolbar._set_mode("time")
    qapp.processEvents()
    _wait_idle(qtbot, window)
    _assert_time_terminals_match(_time_terminal(window), time_home)
    assert all(item["token"] is None for item in begins)
    assert captures == []
    assert started == [] and finished == []
    assert submitted == [] and computes == [] and requests == []
    _assert_idle(controller)


def _admit_heatmap_page_transition_for_test(window, *sections):
    """Ensure heatmap sections are admitted on this window."""
    del sections
    window.chart_stack.set_page_transition_enabled_sections(
        PAGE_TRANSITION_ENABLED_SECTIONS,
    )
    _resume_page_transition(window)


def _fft_time_spec_result(channel="speed"):
    from mf4_analyzer.signal.spectrogram import SpectrogramParams, SpectrogramResult

    freqs = np.linspace(0.0, 200.0, 16)
    times = np.linspace(0.0, 0.5, 8)
    amp = np.full((16, 8), 0.2, dtype=np.float32)
    amp[4, 3] = 1.5
    return SpectrogramResult(
        times=times,
        frequencies=freqs,
        amplitude=amp,
        params=SpectrogramParams(fs=1000.0, nfft=32),
        channel_name=channel,
        unit="rpm",
        metadata={"frames": 8},
    )


def _order_cot_result():
    from mf4_analyzer.signal.order_cot import COTParams, COTResult

    times = np.linspace(0.0, 0.5, 8)
    orders = np.linspace(0.0, 10.0, 16)
    amplitude = np.full((8, 16), 0.15, dtype=float)
    amplitude[3, 5] = 1.2
    return COTResult(
        times=times,
        orders=orders,
        amplitude=amplitude,
        params=COTParams(fs=1000.0, nfft=256, order_res=0.05),
        metadata={"frames": 8},
    )


def _heatmap_terminal(win, section):
    mgr = win.analysis_managers[section]
    state = mgr.get(mgr.active)
    pane = state.panes[0]
    canvas = win._analysis_page(section).pane_canvas(0)
    return {
        "view_id": state.view_id,
        "active": mgr.active,
        "sources": tuple(tuple(source) for source in (pane.sources or ())),
        "rpm_source": (
            tuple(pane.rpm_source) if getattr(pane, "rpm_source", None) else None
        ),
        "has_result": bool(canvas.has_result()),
        "hint": str(getattr(canvas, "_empty_hint_text", "") or ""),
        "slice_dir": getattr(canvas, "_slice_dir", None),
        "collapsed": bool(getattr(canvas, "_bottom_collapsed", False)),
        "mode": win.chart_stack.current_mode(),
    }


def _attach_analysis_file(state, fid):
    ids = list(state.attached_file_ids or ())
    if fid not in ids:
        ids.append(fid)
    state.attached_file_ids = ids


def _clear_heatmap_view_sources(state):
    pane = state.panes[0]
    pane.sources = []
    pane.rpm_source = None


def _seed_fft_view_cache(window, state, fid, channel="speed"):
    pane = state.panes[0]
    pane.sources = [(fid, channel)]
    pane.rpm_source = None
    _attach_analysis_file(state, fid)
    state.params.update(window.inspector.fft_ctx.current_params())
    window._refresh_analysis_candidates("fft")
    window._apply_analysis_sources("fft", state, sync_effective_facts=False)
    key = window._analysis_cache_key("fft", fid, channel, pane_idx=0)
    freq = np.asarray([0.0, 1.0, 2.0], dtype=float)
    amp = np.asarray([1.0, 0.5, 0.25], dtype=float)
    window.analysis_caches["fft"].put(key, (freq, amp, amp ** 2))
    assert key is not None
    return key


def _seed_fft_time_view_cache(window, state, fid, channel="speed"):
    pane = state.panes[0]
    pane.sources = [(fid, channel)]
    pane.rpm_source = None
    _attach_analysis_file(state, fid)
    state.params.update(window.inspector.fft_time_ctx.current_params())
    window._refresh_analysis_candidates("fft_time")
    window._apply_analysis_sources("fft_time", state, sync_effective_facts=False)
    key = window._analysis_cache_key("fft_time", fid, channel, pane_idx=0)
    result = _fft_time_spec_result(channel)
    window.analysis_caches["fft_time"].put(key, result)
    assert key is not None
    return result


def _seed_order_view_cache(window, state, fid, *, signal="torque", rpm="speed"):
    pane = state.panes[0]
    pane.sources = [(fid, signal)]
    pane.rpm_source = (fid, rpm)
    _attach_analysis_file(state, fid)
    state.params.update(window.inspector.order_ctx.current_params())
    window._refresh_analysis_candidates("order")
    window._apply_analysis_sources("order", state, sync_effective_facts=False)
    key = window._analysis_cache_key(
        "order", fid, signal, rpm_source=pane.rpm_source, pane_idx=0,
    )
    result = _order_cot_result()
    window.analysis_caches["order"].put(key, result)
    assert key is not None
    return result


def _fft_time_cached_empty_and_miss(qtbot, qapp, window):
    """View 0 cached spectrogram, view 1 empty, view 2 sources without cache."""
    fid = _fid(window)
    _pause_page_transition(window)
    window.toolbar._set_mode("fft_time")
    qapp.processEvents()
    _seed_active_analysis_attachments(window)
    mgr = window.analysis_managers["fft_time"]
    cached_state = mgr.get(mgr.active)
    _seed_fft_time_view_cache(window, cached_state, fid)
    window._render_analysis_view_from_cache("fft_time", cached_state)
    canvas = window.chart_stack.page_fft_time.pane_canvas(0)
    qtbot.waitUntil(canvas.has_result, timeout=2500)
    window._on_analysis_new("fft_time")
    qapp.processEvents()
    empty_state = mgr.get(mgr.active)
    _clear_heatmap_view_sources(empty_state)
    window._on_analysis_new("fft_time")
    qapp.processEvents()
    miss_state = mgr.get(mgr.active)
    # Distinct from view 0's cached `speed` so this View is a true cache miss.
    miss_state.panes[0].sources = [(fid, "torque")]
    miss_state.panes[0].rpm_source = None
    _attach_analysis_file(miss_state, fid)
    window._refresh_analysis_candidates("fft_time")
    window._apply_analysis_sources("fft_time", miss_state, sync_effective_facts=False)
    assert mgr.active == 2
    return fid, canvas


def _order_cached_empty_miss_and_no_rpm(qtbot, qapp, window):
    """View 0 cached COT, view 1 empty, view 2 RPM+sources uncomputed, view 3 no RPM."""
    fid = _fid(window)
    _pause_page_transition(window)
    window.toolbar._set_mode("order")
    qapp.processEvents()
    _seed_active_analysis_attachments(window)
    mgr = window.analysis_managers["order"]
    cached_state = mgr.get(mgr.active)
    _seed_order_view_cache(window, cached_state, fid)
    window._render_analysis_view_from_cache("order", cached_state)
    canvas = window.chart_stack.page_order.pane_canvas(0)
    qtbot.waitUntil(canvas.has_result, timeout=2500)
    assert canvas._slice_dir == "y"
    window._on_analysis_new("order")
    qapp.processEvents()
    empty_state = mgr.get(mgr.active)
    _clear_heatmap_view_sources(empty_state)
    window._on_analysis_new("order")
    qapp.processEvents()
    miss_state = mgr.get(mgr.active)
    # Distinct from view 0's cached (torque, speed RPM) pair.
    miss_state.panes[0].sources = [(fid, "speed")]
    miss_state.panes[0].rpm_source = (fid, "speed")
    _attach_analysis_file(miss_state, fid)
    window._refresh_analysis_candidates("order")
    window._apply_analysis_sources("order", miss_state, sync_effective_facts=False)
    window._on_analysis_new("order")
    qapp.processEvents()
    no_rpm_state = mgr.get(mgr.active)
    no_rpm_state.panes[0].sources = [(fid, "torque")]
    no_rpm_state.panes[0].rpm_source = None
    _attach_analysis_file(no_rpm_state, fid)
    window._refresh_analysis_candidates("order")
    window._apply_analysis_sources("order", no_rpm_state, sync_effective_facts=False)
    assert mgr.active == 3
    return fid, canvas


def _install_heatmap_compute_spies(monkeypatch, window):
    submitted, computes = _install_compute_spies(monkeypatch, window)
    requests = []
    orig_request = window._fft_time_coordinator.request_batch

    def request_batch(candidates):
        requests.append(len(list(candidates or ())))
        return orig_request(candidates)

    monkeypatch.setattr(window._fft_time_coordinator, "request_batch", request_batch)
    return submitted, computes, requests


def _assert_heatmap_slice_panel_in_input_fence(window, section, label):
    canvas = window._analysis_page(section).pane_canvas(0)
    widgets = canvas.page_transition_input_widgets()
    assert canvas._slice_panel is not None, f"{label}: slice panel must exist"
    assert canvas._slice_panel in widgets, (
        f"{label}: _slice_panel must be in page-transition input freeze list"
    )


def test_e4_heatmap_slice_and_colorbar_invalidation(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid = _fid(window)
    _set_checked(window, "speed")
    window.plot_time()
    qapp.processEvents()
    time_home = _time_terminal(window)

    submitted, computes, requests = _install_heatmap_compute_spies(
        monkeypatch, window,
    )

    # ------------------------------------------------------------------
    # A. FFT vs Time (`plot_result`, no RPM)
    # ------------------------------------------------------------------
    _fft_time_cached_empty_and_miss(qtbot, qapp, window)
    page = window.chart_stack.page_fft_time
    page.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    cached_fft_time = _heatmap_terminal(window, "fft_time")
    assert cached_fft_time["has_result"] is True, "fft_time: cached spectrogram"
    assert cached_fft_time["rpm_source"] is None, "fft_time: no RPM context"
    canvas = page.pane_canvas(0)
    assert canvas._result is not None, "fft_time: plot_result path sets _result"
    _assert_heatmap_slice_panel_in_input_fence(window, "fft_time", "fft_time")

    page.tabbar.switch_requested.emit(1)
    qapp.processEvents()
    restores = []
    orig_restore = window._render_analysis_view_from_cache

    def restore(section, state):
        restores.append(section)
        return orig_restore(section, state)

    monkeypatch.setattr(window, "_render_analysis_view_from_cache", restore)
    _admit_heatmap_page_transition_for_test(window, "fft_time")
    controller, started, cancelled, finished = _connect_transition_lifecycle(
        window,
    )
    begins, captures = _install_transition_spies(monkeypatch, window)

    page.tabbar.switch_requested.emit(0)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    assert cancelled == [], "fft_time: cache-hit Light fade must finish"
    assert started and finished, "fft_time: cache-hit Light fade"
    assert [item["token"] is not None for item in begins] == [True], (
        "fft_time: admitted cache hit must capture"
    )
    assert captures and captures[0]["null"] is False, "fft_time: leave frame"
    assert submitted == [] and computes == [] and requests == [], (
        "fft_time: cache hit must not submit/compute/request"
    )
    assert _heatmap_terminal(window, "fft_time") == cached_fft_time, (
        "fft_time: cache-hit terminal"
    )
    assert "fft_time" in restores, "fft_time: restore from cache"

    slice_seen = []
    canvas.presentation_content_invalidated.connect(
        lambda: slice_seen.append("fft_time"),
    )
    canvas.set_slice_direction("y")
    canvas.set_slice_direction("x")
    canvas._set_bottom_collapsed(True)
    assert canvas._slice_panel is None or not canvas._slice_panel.isVisible()
    canvas._set_bottom_collapsed(False)
    from mf4_analyzer.ui.pg_canvas.heatmap_canvas import _HeatmapMappable
    _HeatmapMappable(canvas).set_clim(-40.0, 0.0)
    assert slice_seen, "fft_time: slice/colorbar mutations must emit content"

    window.chart_stack.set_page_transition_motion_policy(POLICY_OFF)
    begins.clear()
    captures.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    page.tabbar.switch_requested.emit(1)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    empty_fft_time = _heatmap_terminal(window, "fft_time")
    assert empty_fft_time["has_result"] is False, "fft_time: empty view"
    page.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    assert _heatmap_terminal(window, "fft_time") == cached_fft_time, (
        "fft_time: Off restore matches cache"
    )
    assert all(item["token"] is None for item in begins), "fft_time: Off no token"
    assert captures == [], "fft_time: Off no capture"

    window.chart_stack.set_page_transition_motion_policy(POLICY_LIGHT)
    begins.clear()
    captures.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    page.tabbar.switch_requested.emit(1)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    empty_fft_time = _heatmap_terminal(window, "fft_time")
    assert empty_fft_time["has_result"] is False, "fft_time: empty Light fade"
    assert cancelled == [], "fft_time: empty fade must finish"
    assert started and finished, "fft_time: empty legal hint paint-ack"
    assert submitted == [] and requests == [], "fft_time: empty must not compute"

    begins.clear()
    captures.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    page.tabbar.switch_requested.emit(2)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    miss_fft_time = _heatmap_terminal(window, "fft_time")
    assert miss_fft_time["has_result"] is False, "fft_time: uncomputed no borrow"
    assert miss_fft_time["sources"], "fft_time: uncomputed has sources"
    assert begins == [], "fft_time: uncomputed must not capture"
    assert captures == [], "fft_time: uncomputed must not grab"
    assert started == [] and finished == [], "fft_time: uncomputed direct terminal"
    assert submitted == [] and requests == [], "fft_time: uncomputed no jobs"

    page.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    window.toolbar._set_mode("time")
    qapp.processEvents()
    _wait_idle(qtbot, window)
    begins.clear()
    captures.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    window.toolbar._set_mode("fft_time")
    _assert_overlay_spares_navigation(window)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    assert cancelled == [], "fft_time: Time→FFT vs Time must finish"
    assert started and finished, "fft_time: cross-section Light fade"
    assert submitted == [] and requests == [], "fft_time: cross-section no compute"

    orig_ready = _block_page_transition_ready(window)
    page.tabbar.switch_requested.emit(1)
    qapp.processEvents()
    live_ctx = {
        "view_id": window.analysis_managers["fft_time"].get(
            window.analysis_managers["fft_time"].active
        ).view_id,
        "pane_idx": 0,
        "source": (fid, "speed"),
        "render_params": dict(window.inspector.fft_time_ctx.get_params()),
    }
    window._on_fft_time_render_requested(live_ctx, _fft_time_spec_result(), False)
    window.chart_stack.request_page_transition_target_for = orig_ready
    _wait_idle(qtbot, window)
    assert any("fft-time-live-result" in str(reason) for reason in cancelled), (
        "fft_time: async arrival must cancel overlay before plot_result"
    )
    assert page.pane_canvas(0).has_result(), (
        "fft_time: legal live result must display"
    )
    assert submitted == [] and requests == [], (
        "fft_time: injected live result must not submit a new job"
    )

    _pause_page_transition(window)
    window.toolbar._set_mode("time")
    qapp.processEvents()
    _wait_idle(qtbot, window)
    _resume_page_transition(window)

    # ------------------------------------------------------------------
    # B. Order (`plot_or_update_heatmap` + RPM / missing-RPM empty)
    # ------------------------------------------------------------------
    _order_cached_empty_miss_and_no_rpm(qtbot, qapp, window)
    page = window.chart_stack.page_order
    page.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    cached_order = _heatmap_terminal(window, "order")
    assert cached_order["has_result"] is True, "order: cached COT"
    assert cached_order["rpm_source"] == (fid, "speed"), "order: RPM context"
    canvas = page.pane_canvas(0)
    assert canvas._result is None, "order: plot_or_update_heatmap, not plot_result"
    assert canvas._slice_dir == "y", "order: default Y slice"
    _assert_heatmap_slice_panel_in_input_fence(window, "order", "order")

    page.tabbar.switch_requested.emit(1)
    qapp.processEvents()
    restores.clear()
    _admit_heatmap_page_transition_for_test(window, "order")
    controller, started, cancelled, finished = _connect_transition_lifecycle(
        window,
    )
    begins, captures = _install_transition_spies(monkeypatch, window)

    page.tabbar.switch_requested.emit(0)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    assert cancelled == [], "order: cache-hit Light fade must finish"
    assert started and finished, "order: cache-hit Light fade"
    assert [item["token"] is not None for item in begins] == [True], (
        "order: admitted cache hit must capture"
    )
    assert captures and captures[0]["null"] is False, "order: leave frame"
    assert submitted == [], "order: cache hit must not submit_batch"
    assert _heatmap_terminal(window, "order")["has_result"] is True, (
        "order: cache-hit terminal has heatmap"
    )
    assert "order" in restores, "order: restore from cache"

    slice_seen = []
    canvas.presentation_content_invalidated.connect(
        lambda: slice_seen.append("order"),
    )
    canvas.set_slice_direction("x")
    canvas.set_slice_direction("y")
    canvas._set_bottom_collapsed(True)
    canvas._set_bottom_collapsed(False)
    _HeatmapMappable(canvas).set_clim(-30.0, 0.0)
    canvas.full_reset()
    assert slice_seen, "order: slice/colorbar/clear mutations must emit content"
    window._render_analysis_view_from_cache(
        "order", window.analysis_managers["order"].get(0),
    )

    window.chart_stack.set_page_transition_motion_policy(POLICY_OFF)
    begins.clear()
    captures.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    page.tabbar.switch_requested.emit(1)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    page.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    assert all(item["token"] is None for item in begins), "order: Off no token"
    assert captures == [], "order: Off no capture"
    assert submitted == [], "order: Off no submit"

    window.chart_stack.set_page_transition_motion_policy(POLICY_LIGHT)
    begins.clear()
    captures.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    page.tabbar.switch_requested.emit(1)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    empty_order = _heatmap_terminal(window, "order")
    assert empty_order["has_result"] is False, "order: empty Light fade"
    assert cancelled == [], "order: empty fade must finish"
    assert started and finished, "order: empty legal hint paint-ack"

    begins.clear()
    captures.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    page.tabbar.switch_requested.emit(2)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    miss_order = _heatmap_terminal(window, "order")
    assert miss_order["has_result"] is False, "order: uncomputed no borrow"
    assert miss_order["rpm_source"] == (fid, "speed"), "order: uncomputed has RPM"
    assert begins == [], "order: uncomputed must not capture"
    assert captures == [], "order: uncomputed must not grab"
    assert submitted == [], "order: uncomputed no submit_batch"

    begins.clear()
    captures.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    page.tabbar.switch_requested.emit(3)
    qapp.processEvents()
    _wait_idle(qtbot, window)
    no_rpm = _heatmap_terminal(window, "order")
    assert no_rpm["has_result"] is False, "order: missing RPM empty, no borrow"
    assert no_rpm["sources"], "order: missing-RPM view still has a signal"
    assert no_rpm["rpm_source"] is None, "order: missing RPM"
    assert begins == [], "order: missing RPM must not capture"
    assert captures == [], "order: missing RPM must not grab"
    assert submitted == [], "order: missing RPM must not submit_batch"

    window.toolbar._set_mode("time")
    qapp.processEvents()
    _wait_idle(qtbot, window)
    page.tabbar.switch_requested.emit(0)
    qapp.processEvents()
    window.toolbar._set_mode("time")
    qapp.processEvents()
    _wait_idle(qtbot, window)
    begins.clear()
    captures.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    window.toolbar._set_mode("order")
    _assert_overlay_spares_navigation(window)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    assert cancelled == [], "order: Time→Order must finish"
    assert started and finished, "order: cross-section Light fade"
    assert submitted == [], "order: cross-section no submit_batch"

    orig_ready = _block_page_transition_ready(window)
    page.tabbar.switch_requested.emit(1)
    qapp.processEvents()
    live_ctx = {
        "view_id": window.analysis_managers["order"].get(
            window.analysis_managers["order"].active
        ).view_id,
        "pane_idx": 0,
        "source": (fid, "torque"),
        "analysis_key": "e4-order-live",
    }
    window._on_order_job_finished(live_ctx, _order_cot_result())
    window.chart_stack.request_page_transition_target_for = orig_ready
    _wait_idle(qtbot, window)
    assert any("order-live-result" in str(reason) for reason in cancelled), (
        "order: async arrival must cancel overlay before plot_or_update_heatmap"
    )
    assert page.pane_canvas(0).has_result(), (
        "order: legal live result must display"
    )
    assert submitted == [], "order: injected live result must not submit_batch"

    _pause_page_transition(window)
    window.toolbar._set_mode("time")
    qapp.processEvents()
    _wait_idle(qtbot, window)
    _assert_time_terminals_match(_time_terminal(window), time_home)
    _assert_idle(controller)


# ---------------------------------------------------------------------------
# E5: 20 directed cross-section edges, copy scope, leftover paths
# ---------------------------------------------------------------------------

assert len(_CROSS_SECTION_EDGES) == 20


@pytest.mark.parametrize(
    ("source", "target"),
    _CROSS_SECTION_EDGES,
    ids=[f"{source}->{target}" for source, target in _CROSS_SECTION_EDGES],
)
def test_e5_production_enables_directed_edge(source, target):
    """Collected 20 directed edges. Production admits all five sections."""
    text = _WINDOW_PY.read_text(encoding="utf-8")
    assert "PAGE_TRANSITION_ENABLED_SECTIONS" in text
    assert source != target
    production = frozenset(PAGE_TRANSITION_ENABLED_SECTIONS)
    assert source in production and target in production


def test_e5_analysis_internal_and_split_cases_remain_collected():
    names = {
        name for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    }
    missing = [name for name in _E5_INTERNAL_AND_SPLIT_TESTS if name not in names]
    assert missing == []
    assert len(_CROSS_SECTION_EDGES) == 20
    assert len(set(_CROSS_SECTION_EDGES)) == 20


def test_e5_live_result_owners_still_cancel_cover_before_plot():
    """E3/E4 async paths stay wired: drop the cover, then show the legal result."""
    frf = _FRF_MIXIN_PY.read_text(encoding="utf-8")
    fft_time = _FFT_TIME_MIXIN_PY.read_text(encoding="utf-8")
    order = _ORDER_MIXIN_PY.read_text(encoding="utf-8")
    assert 'cancel_page_transition("frf-live-result")' in frf
    assert 'cancel_page_transition("fft-time-live-result")' in fft_time
    assert 'cancel_page_transition("order-live-result")' in order
    assert "test_e4_heatmap_slice_and_colorbar_invalidation" in globals()
    assert "test_e3_frf_multi_subplot_internal_switch" in globals()


def test_e5_directed_cross_section_user_navigation_matrix(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    """One window, 20 toolbar edges: Light fade matches Off terminal."""
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    _seed_all_section_cache_homes(qtbot, qapp, window)
    submitted, computes = _install_compute_spies(monkeypatch, window)
    begins, captures = _install_transition_spies(monkeypatch, window)
    controller, started, cancelled, finished = _connect_transition_lifecycle(
        window,
    )
    submitted.clear()
    computes.clear()

    for source, target in _CROSS_SECTION_EDGES:
        label = f"{source}->{target}"
        _restore_production_enabled_sections(window)
        window.chart_stack.cancel_page_transition("e5-reset")

        window.chart_stack.set_page_transition_motion_policy(POLICY_OFF)
        _ensure_section(qtbot, qapp, window, source)
        begins.clear()
        captures.clear()
        started.clear()
        cancelled.clear()
        finished.clear()
        window.toolbar._set_mode(target)
        qapp.processEvents()
        _wait_idle(qtbot, window)
        assert window.chart_stack.current_mode() == target, label
        assert captures == [], label
        assert all(item["token"] is None for item in begins), label
        assert started == [] and finished == [], label
        off_terminal = _section_terminal(window, target)
        _assert_no_transition_residue(window)

        window.chart_stack.set_page_transition_motion_policy(POLICY_LIGHT)
        _ensure_section(qtbot, qapp, window, source)
        begins.clear()
        captures.clear()
        started.clear()
        cancelled.clear()
        finished.clear()
        window.toolbar._set_mode(target)
        _assert_overlay_spares_navigation(window)
        qtbot.waitUntil(
            lambda: bool(finished) or bool(cancelled), timeout=2500,
        )
        _wait_idle(qtbot, window)
        assert cancelled == [], label
        assert started and finished, label
        assert [item["token"] is not None for item in begins] == [True], label
        assert captures and captures[0]["null"] is False, label
        light_terminal = _section_terminal(window, target)
        _assert_section_terminals_match(target, light_terminal, off_terminal)
        _assert_no_transition_residue(window)

    assert submitted == [] and computes == []
    _restore_production_enabled_sections(window)
    window.toolbar._set_mode("time")
    qapp.processEvents()
    _wait_idle(qtbot, window)
    _assert_no_transition_residue(window)


def test_e5_abc_redirect_late_b_does_not_become_c(
    qtbot, qapp, loaded_csv,
):
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    _seed_all_section_cache_homes(qtbot, qapp, window)
    window.chart_stack.set_page_transition_enabled_sections(
        ("time", "fft", "frf"),
    )
    controller, started, cancelled, finished = _connect_transition_lifecycle(
        window,
    )
    _ensure_section(qtbot, qapp, window, "time")
    window.toolbar._set_mode("fft")
    token_b = window.chart_stack._page_transition_target
    fft_canvas = window.chart_stack.page_fft.pane_canvas(0)
    window.toolbar._set_mode("frf")
    if token_b is not None:
        window.chart_stack._on_page_transition_target_painted(
            token_b, fft_canvas, token_b,
        )
        window.chart_stack.request_page_transition_target(
            token_b, (fft_canvas,),
        )
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    assert window.chart_stack.current_mode() == "frf"
    assert _frf_terminal(window)["has_result"] is True
    _assert_no_transition_residue(window)
    _restore_production_enabled_sections(window)


def test_e5_reverse_switches_leave_no_residue(
    qtbot, qapp, loaded_csv,
):
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    _seed_all_section_cache_homes(qtbot, qapp, window)
    window.chart_stack.set_page_transition_enabled_sections(("time", "fft"))
    controller, started, cancelled, finished = _connect_transition_lifecycle(
        window,
    )
    _ensure_section(qtbot, qapp, window, "time")
    for step in range(20):
        target = "fft" if step % 2 == 0 else "time"
        started.clear()
        cancelled.clear()
        finished.clear()
        window.toolbar._set_mode(target)
        qtbot.waitUntil(
            lambda: bool(finished) or bool(cancelled), timeout=2500,
        )
        _wait_idle(qtbot, window)
        assert cancelled == [], step
        assert window.chart_stack.current_mode() == target, step
        _assert_no_transition_residue(window)
    _restore_production_enabled_sections(window)


def test_e5_close_and_open_project_leave_no_residue(
    qtbot, qapp, loaded_csv, tmp_path,
):
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    _seed_all_section_cache_homes(qtbot, qapp, window)
    window.chart_stack.set_page_transition_enabled_sections(("time", "fft"))
    reasons = []
    window.chart_stack.page_transition().transition_cancelled.connect(
        reasons.append,
    )
    _block_page_transition_ready(window)
    window.toolbar._set_mode("fft")
    qtbot.waitUntil(
        lambda: window.chart_stack.page_transition().image_bytes() > 0,
        timeout=2500,
    )
    window.close()
    qapp.processEvents()
    assert any("window-closing" in str(reason) for reason in reasons)

    restored = _make_loaded_window(qtbot, qapp, loaded_csv)
    _seed_all_section_cache_homes(qtbot, qapp, restored)
    project = tmp_path / "e5-replace.tlproj"
    restored.save_project(project)
    restored.chart_stack.set_page_transition_enabled_sections(("time", "fft"))
    orig_ready = _block_page_transition_ready(restored)
    restored.toolbar._set_mode("fft")
    qtbot.waitUntil(
        lambda: restored.chart_stack.page_transition().image_bytes() > 0,
        timeout=2500,
    )
    restored.open_project(project)
    restored.chart_stack.request_page_transition_target_for = orig_ready
    qapp.processEvents()
    _wait_idle(qtbot, restored)
    _assert_no_transition_residue(restored)
    _restore_production_enabled_sections(restored)


def _flip_inspector_window(ctx):
    params = dict(ctx.current_params())
    params["window"] = (
        "hamming" if str(params.get("window")) != "hamming" else "hanning"
    )
    ctx.apply_params(params)
    return str(params["window"])


def _flip_inspector_nfft(ctx):
    params = dict(ctx.current_params())
    current = params.get("nfft")
    params["nfft"] = 512 if current != 512 else 1024
    params["nfft_mode"] = "fixed"
    ctx.apply_params(params)
    return params["nfft"]


def _view_pin_keys(window, section, view_id):
    pins = getattr(window, "_analysis_pins", None)
    if pins is None:
        return frozenset()
    slot = (section, str(view_id), 0)
    return frozenset(pins._slots.get(slot) or ())


def _section_page(window, section):
    return {
        "fft": window.chart_stack.page_fft,
        "fft_time": window.chart_stack.page_fft_time,
        "order": window.chart_stack.page_order,
    }[section]


def _seed_section_view_cache(window, section, state, fid):
    if section == "fft":
        return _seed_fft_view_cache(window, state, fid)
    if section == "fft_time":
        return _seed_fft_time_view_cache(window, state, fid)
    return _seed_order_view_cache(window, state, fid)


def _section_ctx(window, section):
    return getattr(window.inspector, f"{section}_ctx")


def _uncomputed(window, section, state):
    return window._analysis_view_is_uncomputed(section, state)


def _prepare_cached_then_divergent_view(qtbot, qapp, window, section):
    """View 0 cached; View 1 live inspector uses a different window."""
    _pause_page_transition(window)
    window.toolbar._set_mode(section)
    qapp.processEvents()
    _seed_active_analysis_attachments(window)
    fid = _fid(window)
    mgr = window.analysis_managers[section]
    cached = mgr.get(mgr.active)
    _seed_section_view_cache(window, section, cached, fid)
    window._render_analysis_view_from_cache(section, cached)
    canvas = _section_page(window, section).pane_canvas(0)
    qtbot.waitUntil(canvas.has_result, timeout=2500)
    window._capture_active_analysis_view(section)
    assert not _uncomputed(window, section, cached)
    window._on_analysis_new(section)
    qapp.processEvents()
    leaving = mgr.get(mgr.active)
    leaving.panes[0].sources = list(cached.panes[0].sources)
    leaving.panes[0].rpm_source = getattr(cached.panes[0], "rpm_source", None)
    _attach_analysis_file(leaving, fid)
    _flip_inspector_window(_section_ctx(window, section))
    leaving.params.update(_section_ctx(window, section).current_params())
    window._apply_analysis_sources(section, leaving, sync_effective_facts=False)
    return fid, cached, leaving


@pytest.mark.parametrize("section", ("fft", "fft_time", "order"))
def test_analysis_admission_uses_target_params(
    qtbot, qapp, loaded_csv, monkeypatch, section,
):
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid, cached, leaving = _prepare_cached_then_divergent_view(
        qtbot, qapp, window, section,
    )
    del leaving
    classified = _uncomputed(window, section, cached)
    assert classified is False, "cached target must use stored params, not leaving Inspector"

    submitted, computes = _install_compute_spies(monkeypatch, window)
    restores = []
    orig_restore = window._render_analysis_view_from_cache

    def restore(sec, state):
        restores.append((sec, state.view_id))
        return orig_restore(sec, state)

    monkeypatch.setattr(window, "_render_analysis_view_from_cache", restore)
    dirty_before = window._project_dirty.is_dirty
    pins_before = _view_pin_keys(window, section, cached.view_id)
    _resume_page_transition(window)
    begins, captures = _install_transition_spies(monkeypatch, window)
    controller, started, cancelled, finished = _connect_transition_lifecycle(
        window,
    )

    _section_page(window, section).tabbar.switch_requested.emit(0)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)

    assert classified is False
    assert cancelled == []
    assert started and finished
    assert [item["token"] is not None for item in begins] == [True]
    assert captures and captures[0]["null"] is False
    assert submitted == [] and computes == []
    assert window.analysis_managers[section].active == 0
    canvas = _section_page(window, section).pane_canvas(0)
    assert canvas.has_result() is True
    pane = cached.panes[0]
    assert tuple(pane.sources[0])[:1] == (fid,)
    assert restores and restores[0][0] == section
    assert restores[0][1] == cached.view_id
    assert window._project_dirty.is_dirty == dirty_before
    pins_after = _view_pin_keys(window, section, cached.view_id)
    assert pins_after
    assert pins_before <= pins_after
    _assert_idle(controller)


def test_fft_time_admission_covers_nfft_and_range_mismatch(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    _pause_page_transition(window)
    window.toolbar._set_mode("fft_time")
    qapp.processEvents()
    _seed_active_analysis_attachments(window)
    fid = _fid(window)
    mgr = window.analysis_managers["fft_time"]
    cached = mgr.get(mgr.active)
    _seed_fft_time_view_cache(window, cached, fid)
    window._render_analysis_view_from_cache("fft_time", cached)
    qtbot.waitUntil(
        window.chart_stack.page_fft_time.pane_canvas(0).has_result,
        timeout=2500,
    )
    window._capture_active_analysis_view("fft_time")
    window._on_analysis_new("fft_time")
    qapp.processEvents()
    _flip_inspector_nfft(window.inspector.fft_time_ctx)
    mgr.get(mgr.active).panes[0].time_range = (0.0, 0.2)
    assert window._fft_time_view_is_uncomputed(cached) is False

    submitted, computes = _install_compute_spies(monkeypatch, window)
    _resume_page_transition(window)
    begins, captures = _install_transition_spies(monkeypatch, window)
    _controller, started, cancelled, finished = _connect_transition_lifecycle(
        window,
    )
    window.chart_stack.page_fft_time.tabbar.switch_requested.emit(0)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    assert cancelled == []
    assert started and finished
    assert [item["token"] is not None for item in begins] == [True]
    assert submitted == [] and computes == []
    assert window.chart_stack.page_fft_time.pane_canvas(0).has_result() is True


def test_analysis_cache_miss_then_hit_with_divergent_params(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    fid, cached, miss_state = _prepare_cached_then_divergent_view(
        qtbot, qapp, window, "fft_time",
    )
    original_window = cached.params.get("window")
    assert window._fft_time_view_is_uncomputed(cached) is False
    cached.params["window"] = (
        "hamming" if original_window != "hamming" else "hanning"
    )
    assert window._fft_time_view_is_uncomputed(cached) is True
    cached.params["window"] = original_window
    assert window._fft_time_view_is_uncomputed(cached) is False
    assert window._fft_time_view_is_uncomputed(miss_state) is True

    _seed_fft_time_view_cache(window, miss_state, fid)
    window._render_analysis_view_from_cache("fft_time", miss_state)
    qtbot.waitUntil(
        window.chart_stack.page_fft_time.pane_canvas(0).has_result,
        timeout=2500,
    )
    assert window._fft_time_view_is_uncomputed(miss_state) is False

    submitted, computes = _install_compute_spies(monkeypatch, window)
    _resume_page_transition(window)
    begins, captures = _install_transition_spies(monkeypatch, window)
    _controller, started, cancelled, finished = _connect_transition_lifecycle(
        window,
    )
    window.chart_stack.page_fft_time.tabbar.switch_requested.emit(0)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    assert cancelled == []
    assert started and finished
    begins.clear()
    captures.clear()
    started.clear()
    cancelled.clear()
    finished.clear()
    window.chart_stack.page_fft_time.tabbar.switch_requested.emit(1)
    qtbot.waitUntil(lambda: bool(finished) or bool(cancelled), timeout=2500)
    _wait_idle(qtbot, window)
    assert cancelled == []
    assert started and finished
    assert [item["token"] is not None for item in begins] == [True]
    assert submitted == [] and computes == []


def test_page_transition_presentation_admitted_is_shared(qapp, qtbot):
    cs = ChartStack()
    qtbot.addWidget(cs)
    cs.set_page_transition_enabled_sections(PAGE_TRANSITION_ENABLED_SECTIONS)
    cs.set_page_transition_motion_policy(POLICY_LIGHT)
    assert cs.page_transition_presentation_admitted("fft_time", "fft_time")
    assert cs.page_transition_presentation_admitted("time", "fft")
    cs.set_page_transition_motion_policy(POLICY_OFF)
    assert not cs.page_transition_presentation_admitted("fft_time", "fft_time")
    cs.set_page_transition_motion_policy(POLICY_LIGHT)
    cs.set_page_transition_enabled_sections(("time",))
    assert not cs.page_transition_presentation_admitted("fft_time", "fft_time")


def test_off_admission_does_not_prepare_signal(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    _prepare_cached_then_divergent_view(qtbot, qapp, window, "fft_time")
    prepared = []
    original = window._fft_time_effective_params_for_source

    def prepare(*args, **kwargs):
        prepared.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(window, "_fft_time_effective_params_for_source", prepare)
    window.chart_stack.set_page_transition_motion_policy(POLICY_OFF)
    assert not window.chart_stack.page_transition().motion_policy().interpolates()
    assert window._should_begin_analysis_page_transition("fft_time", 0) is False
    assert prepared == [], "motion admission must be cheap when OFF"

    window.toolbar._set_mode("time")
    qapp.processEvents()
    prepared.clear()
    assert window._should_begin_cross_section_page_transition(
        "time", "fft_time",
    ) is False
    assert prepared == []

    window.chart_stack.set_page_transition_motion_policy(POLICY_LIGHT)
    window.chart_stack.set_page_transition_enabled_sections(("time",))
    prepared.clear()
    window.toolbar._set_mode("fft_time")
    qapp.processEvents()
    assert window._should_begin_analysis_page_transition("fft_time", 0) is False
    assert prepared == []


def test_split_and_programmatic_admission_skip_prepare(
    qtbot, qapp, loaded_csv, monkeypatch,
):
    window = _make_loaded_window(qtbot, qapp, loaded_csv)
    _prepare_cached_then_divergent_view(qtbot, qapp, window, "fft_time")
    prepared = []
    original = window._fft_time_effective_params_for_source

    def prepare(*args, **kwargs):
        prepared.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(window, "_fft_time_effective_params_for_source", prepare)
    _resume_page_transition(window)
    window._opening_project = True
    assert window._should_begin_analysis_page_transition("fft_time", 0) is False
    assert prepared == []
    window._opening_project = False
    window.toolbar._set_mode("time")
    qapp.processEvents()
    fid = _fid(window)
    _set_checked(window, "speed")
    window.plot_time()
    qapp.processEvents()
    window._capture_current_view()
    _new_time_view(qtbot, qapp, window)
    window._attach_files_to_focused_view([fid])
    if window.view_manager.active != 0:
        window._switch_view(0)
        qapp.processEvents()
    window.view_manager.set_split(1)
    qapp.processEvents()
    assert window.chart_stack.split_active() is True
    prepared.clear()
    assert window._should_begin_cross_section_page_transition(
        "time", "fft_time",
    ) is False
    assert prepared == []


@pytest.mark.skip(reason="E0: acquisition cockpit is a separate window; Windows/macOS cockpit not in this offscreen matrix")
def test_e0_acquisition_path_direct_terminal_runtime():
    raise AssertionError("acquisition runtime not in E0 offscreen matrix")
