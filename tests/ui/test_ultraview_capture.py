"""UltraView presentation digest, stable capture, and PreviewStore publish."""
from __future__ import annotations

import ast
import gc
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QObject, QPoint, pyqtSignal
from PyQt5.QtGui import QColor, QPixmap
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QWidget

from mf4_analyzer.ui.analysis_view_state import AnalysisViewState, PaneState
from mf4_analyzer.ui.chart_stack.ultraview.page import UltraViewPage
from mf4_analyzer.ui.main_window._state_holders import AnalysisPinBook
from mf4_analyzer.ui.main_window._view_mixin import ViewMixin
from mf4_analyzer.ui.main_window.ultraview_coordinator import (
    UltraViewCoordinator,
    _DIGEST_RETRY_LIMIT,
    _IDLE_CAPTURE_MS,
    hide_transient_overlays,
    read_markup_revision,
)
from mf4_analyzer.ui.ultraview_state import UltraViewRef, add_ref, presentation_digest
from mf4_analyzer.ui.view_state import ViewManager, ViewState

_COORDINATOR_PATH = (
    Path(__file__).resolve().parents[2]
    / "mf4_analyzer"
    / "ui"
    / "main_window"
    / "ultraview_coordinator.py"
)
_FORBIDDEN_SOURCE_NAMES = (
    "do_fft",
    "do_fft_time",
    "do_frf",
    "do_order_time",
    "_render_analysis_view_from_cache",
    "_apply_active_analysis_context",
    "_plot_time_on_canvas",
    "_analysis_restore_pending",
    "time.sleep",
    "sleep(",
)


def _flush(turns: int = 4) -> None:
    for _ in range(turns):
        QCoreApplication.processEvents()


def _ref(view_id: str = "view-a", section: str = "time") -> UltraViewRef:
    return UltraViewRef(section, view_id)


class _VisItem:
    def __init__(self, visible: bool = True, value: float | None = None) -> None:
        self._visible = visible
        self._value = value

    def isVisible(self) -> bool:
        return self._visible

    def hide(self) -> None:
        self._visible = False

    def show(self) -> None:
        self._visible = True

    def value(self):
        return self._value


class FakeCanvas(QWidget):
    cursor_info = pyqtSignal(str)
    dual_cursor_info = pyqtSignal(str)
    visible_range_changed = pyqtSignal()
    markup_revision_changed = pyqtSignal()

    def __init__(self, color: str = "#123456") -> None:
        super().__init__()
        self.resize(64, 48)
        self.show()
        self._interaction_state = "idle"
        self._refresh_pending = False
        self._quality_state = "green"
        self.markup_revision = 0
        self.grab_calls = 0
        self._fill = QColor(color)
        self._cursor_item = _VisItem(True, value=0.25)
        self._armed_item = _VisItem(True, value=1.0)
        self._remark_item = _VisItem(True)
        self._scale_box = _VisItem(True)
        self._cursor = SimpleNamespace(
            dual=False,
            ax=None,
            bx=None,
            _cursor_line_items=[self._cursor_item],
            _cursor_a_items=[self._armed_item],
        )
        self._plot = SimpleNamespace(vb=SimpleNamespace(rbScaleBox=self._scale_box))
        self.cursor_visible_at_grab = None
        self.armed_visible_at_grab = None
        self.remark_visible_at_grab = None
        self.scale_box_visible_at_grab = None
        self._has_result = True

    def has_result(self) -> bool:
        return bool(self._has_result)

    def quality_status(self):
        count = getattr(self, "_curve_count", None)
        if count is None:
            count = 1 if self._has_result else 0
        status = {"state": self._quality_state, "curve_count": int(count)}
        path = getattr(self, "_render_path", None)
        if path:
            status["render_path"] = path
        raster_count = getattr(self, "_high_raster_curve_count", None)
        if raster_count is not None:
            status["high_raster_curve_count"] = int(raster_count)
        return status

    def grab_pixmap(self, scale: float = 1.0) -> QPixmap:
        self.grab_calls += 1
        self.cursor_visible_at_grab = self._cursor_item.isVisible()
        self.armed_visible_at_grab = self._armed_item.isVisible()
        self.remark_visible_at_grab = self._remark_item.isVisible()
        self.scale_box_visible_at_grab = self._scale_box.isVisible()
        pix = QPixmap(max(self.width(), 16), max(self.height(), 16))
        pix.fill(self._fill)
        return pix

    def restore_visible_xlim(self, xlim) -> None:
        return None

    def restore_visible_ylims(self, ylims) -> None:
        return None

    def set_tick_density(self, x, y) -> None:
        return None


class FakePage(QWidget):
    def __init__(self, panes: list[FakeCanvas]) -> None:
        super().__init__()
        self._panes = list(panes)
        self.combined_calls = 0
        self.resize(96, 48)
        self.show()

    def pane_count(self) -> int:
        return len(self._panes)

    def pane_canvas(self, idx: int):
        return self._panes[idx]

    def grab_combined_pixmap(self, scale: float = 1.0) -> QPixmap:
        self.combined_calls += 1
        pix = QPixmap(48, 24)
        pix.fill(QColor("#334455"))
        return pix


class FakeWindow(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.view_manager = ViewManager()
        self.files = {}
        self.analysis_managers = {}
        self._analysis_pins = AnalysisPinBook()
        self.pages = {}
        self.canvas_time = None
        self.chart_stack = None
        self._analysis_jobs = None
        self._filter = {
            "enabled": False,
            "spec": {},
            "show_original": True,
            "show_filtered": False,
        }
        self.restore_calls = 0
        self.plot_time_calls = 0

    def _project_filter_payload(self):
        return dict(self._filter)

    def _analysis_page(self, section):
        return self.pages.get(section)

    def _render_analysis_view_from_cache(self, *args, **kwargs):
        self.restore_calls += 1

    def _plot_time_on_canvas(self, *args, **kwargs):
        self.plot_time_calls += 1
        return True

    def do_fft(self, *args, **kwargs):
        raise AssertionError("preview path must not compute FFT")

    def do_fft_time(self, *args, **kwargs):
        raise AssertionError("preview path must not compute FFT-vs-Time")

    def do_frf(self, *args, **kwargs):
        raise AssertionError("preview path must not compute FRF")

    def do_order_time(self, *args, **kwargs):
        raise AssertionError("preview path must not compute Order")


class _FakeBridge:
    def apply_controls_from_state(self, state, host, canvas) -> None:
        return None


class _FakeStack:
    def __init__(self, mode: str = "time") -> None:
        self._mode = mode
        self._split = False
        self._secondary = None

    def cursor_pill_snapshot(self):
        return None

    def restore_cursor_pill_snapshot(self, snapshot) -> None:
        return None

    def clear_cursor_pill(self) -> None:
        return None

    def current_mode(self) -> str:
        return self._mode

    def split_active(self) -> bool:
        return self._split

    def secondary_canvas(self):
        return self._secondary

    def focused_canvas(self):
        return None


class _TimeHost(ViewMixin):
    def __init__(self, coord, manager, canvas, stack) -> None:
        self._ultraview = coord
        self.view_manager = manager
        self.canvas_time = canvas
        self.chart_stack = stack
        self._view_bridge = _FakeBridge()
        self._focused_view_idx = None
        self._applying_view = False
        self.defer_flags = []
        self.plot_calls = 0

    def _plot_time_on_canvas(self, canvas, *, update_primary_ui, defer_first_frame):
        self.plot_calls += 1
        self.defer_flags.append(bool(defer_first_frame))
        if defer_first_frame:
            canvas._quality_state = "red"
            canvas._refresh_pending = True
        return True

    def _project_view_controls(self, idx) -> None:
        return None

    def _render_analysis_view_from_cache(self, *args, **kwargs):
        raise AssertionError("time render must not restore analysis cache")


class _Column:
    def __init__(self, values) -> None:
        self.values = values


class _Table:
    def __init__(self, columns: dict) -> None:
        self.columns = list(columns)
        self._columns = columns

    def __getitem__(self, key):
        return _Column(self._columns[key])


def _file_data(time_axis, channels: dict):
    return SimpleNamespace(data=_Table(channels), time_array=time_axis)


def _make_coord(window=None):
    host = window if window is not None else FakeWindow()
    coord = UltraViewCoordinator(host, parent=host)
    return host, coord


def test_presentation_digest_pixel_affecting_field_matrix(qapp):
    window, coord = _make_coord()
    manager = window.view_manager
    state = manager.get(0)
    state.view_id = "view-a"
    state.name = "Alpha"
    state.tab_color = "#111111"
    state.cursor_mode = "single"
    state.attached_file_ids = ["f1"]
    state.checked = [("f1", "torque")]
    state.hidden_channels = []
    state.colors = {("f1", "torque"): "#1769e0"}
    state.plot_mode = "subplot"
    state.xlim = (0.0, 1.0)
    state.ylims = {"torque": (-1.0, 1.0)}
    state.axis_opts = {"tick_density": {"x": 6, "y": 6}}
    time_axis = np.linspace(0.0, 1.0, 16)
    values = np.arange(16, dtype=np.float64)
    window.files["f1"] = _file_data(time_axis, {"torque": values})
    ref = _ref("view-a")

    baseline = coord.current_digest_for(ref)
    assert baseline is not None

    state.name = "Renamed"
    state.tab_color = "#abcdef"
    assert coord.current_digest_for(ref) == baseline
    state.cursor_mode = "dual"
    assert coord.current_digest_for(ref) != baseline
    state.cursor_mode = "single"
    assert coord.current_digest_for(ref) == baseline

    state.plot_mode = "overlay"
    assert coord.current_digest_for(ref) != baseline
    state.plot_mode = "subplot"
    assert coord.current_digest_for(ref) == baseline

    state.xlim = (0.0, 2.0)
    assert coord.current_digest_for(ref) != baseline
    state.xlim = (0.0, 1.0)

    window._filter["enabled"] = True
    window._filter["spec"] = {"kind": "low", "cutoff": 40.0}
    assert coord.current_digest_for(ref) != baseline
    window._filter["enabled"] = False
    window._filter["spec"] = {}

    canvas = FakeCanvas()
    coord.bind_canvas(canvas, ref)
    canvas.markup_revision = 3
    assert coord.current_digest_for(ref) != baseline
    canvas.markup_revision = 0
    assert coord.current_digest_for(ref) == baseline

    reread = coord.current_digest_for(ref)
    assert reread == baseline

    derived = values * 2.0
    window.files["f1"] = _file_data(time_axis, {"torque": values, "derived": derived})
    state.checked = [("f1", "torque"), ("f1", "derived")]
    added = coord.current_digest_for(ref)
    assert added != baseline

    replaced = np.arange(16, dtype=np.float64) + 8.0
    window.files["f1"] = _file_data(time_axis, {"torque": replaced, "derived": derived})
    state.checked = [("f1", "torque")]
    assert coord.current_digest_for(ref) != baseline

    window.files["f1"] = _file_data(time_axis, {"torque": values})
    deleted = coord.current_digest_for(ref)
    assert deleted == baseline

    fft_manager = ViewManager(state_factory=AnalysisViewState)
    window.analysis_managers["fft"] = fft_manager
    fft_state = fft_manager.get(0)
    fft_state.view_id = "fft-a"
    fft_state.params = {"nfft": 1024, "window": "hann"}
    fft_state.compare = {"x_linked": True, "levels_locked": True}
    fft_state.panes = [PaneState(sources=[("f1", "torque")], xlim=(0.0, 200.0))]
    key = ("fft", "k1")
    window._analysis_pins.add("fft", "fft-a", 0, key)
    page = FakePage([FakeCanvas()])
    window.pages["fft"] = page
    fft_ref = _ref("fft-a", "fft")
    result = object()
    coord.notify_result_stored("fft", "fft-a", 0, key, result)
    fft_baseline = coord.current_digest_for(fft_ref)
    assert fft_baseline is not None
    coord.notify_result_stored("fft", "fft-a", 0, key, result)
    assert coord.current_digest_for(fft_ref) == fft_baseline
    coord.notify_result_stored("fft", "fft-a", 0, key, object())
    assert coord.current_digest_for(fft_ref) != fft_baseline
    fft_state.params = {"nfft": 2048, "window": "hann"}
    assert coord.current_digest_for(fft_ref) != fft_baseline
    canvas.deleteLater()
    page.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_time_switch_captures_old_binding_before_deferred_render(qapp):
    window, coord = _make_coord()
    manager = window.view_manager
    state_a = manager.get(0)
    state_a.view_id = "view-a"
    idx_b = manager.new_view()
    state_b = manager.get(idx_b)
    state_b.view_id = "view-b"
    state_b.xlim = (0.2, 0.8)

    canvas = FakeCanvas("#112233")
    stack = _FakeStack()
    host = _TimeHost(coord, manager, canvas, stack)
    ref_a = _ref("view-a")
    ref_b = _ref("view-b")
    coord.bind_canvas(canvas, ref_a)

    host._render_view_to_canvas(idx_b, canvas, update_primary_ui=True)
    _flush()

    assert host.defer_flags == [True]
    record_a = coord.store.get(ref_a)
    assert record_a is not None
    assert record_a.image is not None
    assert coord.store.get(ref_b) is None
    assert coord.bound_ref_for(canvas) == ref_b
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_replot_same_view_does_not_publish_under_another_ref(qapp):
    window, coord = _make_coord()
    manager = window.view_manager
    state_a = manager.get(0)
    state_a.view_id = "view-a"
    idx_b = manager.new_view()
    manager.get(idx_b).view_id = "view-b"

    canvas = FakeCanvas("#abcdef")
    stack = _FakeStack()
    host = _TimeHost(coord, manager, canvas, stack)
    ref_a = _ref("view-a")
    ref_b = _ref("view-b")
    coord.bind_canvas(canvas, ref_a)
    coord.request_capture(ref_a, canvas, "seed")
    _flush()
    grabs_after_seed = canvas.grab_calls
    assert coord.store.get(ref_a) is not None

    host._render_view_to_canvas(0, canvas, update_primary_ui=True)
    _flush()

    assert coord.store.get(ref_b) is None
    assert coord.bound_ref_for(canvas) == ref_a
    assert canvas.grab_calls == grabs_after_seed
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_time_split_is_two_refs_and_analysis_split_is_one_composite(qapp):
    window, coord = _make_coord()
    manager = window.view_manager
    manager.get(0).view_id = "view-a"
    idx_b = manager.new_view()
    manager.get(idx_b).view_id = "view-b"
    primary = FakeCanvas("#111111")
    secondary = FakeCanvas("#222222")
    ref_a = _ref("view-a")
    ref_b = _ref("view-b")
    coord.bind_canvas(primary, ref_a)
    coord.bind_canvas(secondary, ref_b)
    coord.request_capture(ref_a, primary, "split-primary")
    coord.request_capture(ref_b, secondary, "split-secondary")
    _flush()
    assert coord.store.get(ref_a) is not None
    assert coord.store.get(ref_b) is not None

    secondary.hide()
    secondary.markup_revision += 1
    coord.request_capture(ref_b, secondary, "hidden-secondary")
    _flush()
    assert coord.store.get(ref_b).captured_digest != coord.current_digest_for(ref_b)

    pane_a = FakeCanvas("#010101")
    pane_b = FakeCanvas("#020202")
    page = FakePage([pane_a, pane_b])
    fft_manager = ViewManager(state_factory=AnalysisViewState)
    window.analysis_managers["fft"] = fft_manager
    fft_manager.get(0).view_id = "fft-a"
    window.pages["fft"] = page
    fft_ref = _ref("fft-a", "fft")
    coord.request_visible_section_capture("fft", "analysis-split")
    _flush()
    assert page.combined_calls == 1
    assert pane_a.grab_calls == 0
    assert pane_b.grab_calls == 0
    assert coord.store.get(fft_ref) is not None

    hidden_page = FakePage([FakeCanvas("#030303")])
    hidden_page.hide()
    window.pages["fft"] = hidden_page
    hidden_page.markup_revision = 4
    coord.request_visible_section_capture("fft", "hidden-page")
    _flush()
    assert hidden_page.combined_calls == 0

    primary.deleteLater()
    secondary.deleteLater()
    page.deleteLater()
    hidden_page.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_each_capture_trigger_obeys_canvas_stability_contract(qapp):
    window, coord = _make_coord()
    window.view_manager.get(0).view_id = "view-a"
    canvas = FakeCanvas()
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "seed")
    _flush()
    record = coord.store.get(ref)
    assert record is not None
    first_digest = record.captured_digest

    canvas.markup_revision += 1
    changed = coord.current_digest_for(ref)
    assert changed != first_digest

    for attr, value in (
        ("_quality_state", "yellow"),
        ("_interaction_state", "interactive"),
        ("_refresh_pending", True),
    ):
        canvas._quality_state = "green"
        canvas._interaction_state = "idle"
        canvas._refresh_pending = False
        setattr(canvas, attr, value)
        grabs = canvas.grab_calls
        coord.request_capture(ref, canvas, f"unstable-{attr}")
        _flush()
        assert canvas.grab_calls == grabs
        kept = coord.store.get(ref)
        assert kept is not None
        assert kept.captured_digest == first_digest

    canvas._quality_state = "green"
    canvas._interaction_state = "idle"
    canvas._refresh_pending = False
    coord.request_capture(ref, canvas, "stable-retry")
    _flush()
    updated = coord.store.get(ref)
    assert updated is not None
    assert updated.captured_digest == changed
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_transient_overlays_hidden_but_markup_revision_is_captured(qapp):
    window, coord = _make_coord()
    state = window.view_manager.get(0)
    state.view_id = "view-a"
    state.cursor_mode = "single"
    canvas = FakeCanvas()
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    without_markup = coord.current_digest_for(ref)
    canvas.markup_revision = 2
    with_markup = coord.current_digest_for(ref)
    assert with_markup != without_markup
    state.name = "ignored"
    state.tab_color = "#ffffff"
    assert coord.current_digest_for(ref) == with_markup
    state.cursor_mode = "dual"
    assert coord.current_digest_for(ref) != with_markup
    state.cursor_mode = "single"
    assert coord.current_digest_for(ref) == with_markup

    canvas._cursor_item._value = 0.1
    hover_a = coord.current_digest_for(ref)
    canvas._cursor_item._value = 9.9
    assert coord.current_digest_for(ref) == hover_a

    canvas._cursor.dual = True
    canvas._cursor.ax = 1.0
    canvas._cursor.bx = 2.0
    with hide_transient_overlays(canvas):
        assert canvas._cursor_item.isVisible() is False
        assert canvas._armed_item.isVisible() is True
        assert canvas._scale_box.isVisible() is False
        assert canvas._remark_item.isVisible() is True
    canvas._cursor.dual = False
    with hide_transient_overlays(canvas):
        assert canvas._cursor_item.isVisible() is False
        assert canvas._armed_item.isVisible() is True
        assert canvas._scale_box.isVisible() is False
        assert canvas._remark_item.isVisible() is True
    assert canvas._cursor_item.isVisible() is True
    assert canvas._scale_box.isVisible() is True

    coord.request_capture(ref, canvas, "overlay")
    _flush()
    assert canvas.cursor_visible_at_grab is False
    assert canvas.armed_visible_at_grab is True
    assert canvas.remark_visible_at_grab is True
    assert canvas.scale_box_visible_at_grab is False
    assert canvas._cursor_item.isVisible() is True
    assert canvas._remark_item.isVisible() is True
    assert canvas._scale_box.isVisible() is True
    assert read_markup_revision(canvas) == 2
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


class _FakeReadoutPill:
    def __init__(self) -> None:
        self._visible = True
        self._primary = "A 12.0"
        self._detail_text = "B 24.0"
        self._detail = SimpleNamespace(text=lambda: self._detail_text)

    def isVisible(self) -> bool:
        return self._visible

    def primary_text(self) -> str:
        return self._primary

    def has_detail(self) -> bool:
        return True


class _PillStack:
    def __init__(self) -> None:
        self._pill = _FakeReadoutPill()

    def _pill_for_canvas(self, _canvas):
        return self._pill


def test_dual_cursor_geometry_survives_canvas_rebind(qapp):
    """UVL-A11: rebound canvas must not empty the old ref's armed geometry."""
    from mf4_analyzer.ui.ultraview_state import STATUS_FRESH, derive_preview_status

    window, coord = _make_coord()
    manager = window.view_manager
    state_a = manager.get(0)
    state_a.view_id = "view-a"
    state_a.cursor_mode = "dual"
    idx_b = manager.new_view()
    state_b = manager.get(idx_b)
    state_b.view_id = "view-b"
    state_b.cursor_mode = "off"
    canvas = FakeCanvas()
    canvas._cursor.dual = True
    canvas._cursor.ax = 1.5
    canvas._cursor.bx = 3.5
    ref_a = _ref("view-a")
    ref_b = _ref("view-b")
    coord.bind_canvas(canvas, ref_a)
    coord.request_capture(ref_a, canvas, "dual-armed")
    _flush()
    record = coord.store.get(ref_a)
    assert record is not None
    captured = record.captured_digest
    assert captured == coord.current_digest_for(ref_a)

    coord.bind_canvas(canvas, ref_b)
    current = coord.current_digest_for(ref_a)
    assert current == captured
    assert derive_preview_status(
        True, True, captured, current
    ) == STATUS_FRESH
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_pill_fingerprint_survives_hidden_source_page(qapp):
    """UVL-A17: hiding the source page must not flip a captured card to stale."""
    from mf4_analyzer.ui.ultraview_state import STATUS_FRESH, derive_preview_status

    window, coord = _make_coord()
    stack = _PillStack()
    window.chart_stack = stack
    state = window.view_manager.get(0)
    state.view_id = "view-a"
    state.cursor_mode = "dual"
    canvas = FakeCanvas()
    canvas._cursor.dual = True
    canvas._cursor.ax = 1.0
    canvas._cursor.bx = 2.0
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "pill-visible")
    _flush()
    record = coord.store.get(ref)
    assert record is not None
    captured = record.captured_digest
    assert captured == coord.current_digest_for(ref)

    stack._pill._visible = False
    canvas.hide()
    current = coord.current_digest_for(ref)
    assert current == captured
    assert derive_preview_status(
        True, True, captured, current
    ) == STATUS_FRESH
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_capture_dedupes_and_rejects_late_binding_or_digest(qapp):
    window, coord = _make_coord()
    manager = window.view_manager
    manager.get(0).view_id = "view-a"
    idx_b = manager.new_view()
    manager.get(idx_b).view_id = "view-b"
    canvas = FakeCanvas()
    ref_a = _ref("view-a")
    ref_b = _ref("view-b")
    coord.bind_canvas(canvas, ref_a)
    coord.request_capture(ref_a, canvas, "first")
    coord.request_capture(ref_a, canvas, "second")
    assert canvas.grab_calls == 0
    _flush()
    assert canvas.grab_calls == 1
    first_digest = coord.store.get(ref_a).captured_digest

    coord.request_capture(ref_a, canvas, "repeat")
    _flush()
    assert canvas.grab_calls == 1
    assert coord.store.get(ref_a).captured_digest == first_digest

    canvas.markup_revision += 1
    coord.request_capture(ref_a, canvas, "late-digest")
    canvas.markup_revision += 1
    live = coord.current_digest_for(ref_a)
    _flush()
    assert coord.store.get(ref_a).captured_digest == live
    assert canvas.grab_calls == 2

    canvas.markup_revision += 1
    coord.request_capture(ref_a, canvas, "late-bind")
    coord.bind_canvas(canvas, ref_b)
    _flush()
    assert coord.store.get(ref_a).captured_digest == live
    assert coord.store.get(ref_b) is None
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_refresh_page_updates_card_chrome_when_preview_record_unchanged(qapp):
    window, coord = _make_coord()
    page = UltraViewPage()
    page.resize(320, 240)
    page.show()
    window.chart_stack = SimpleNamespace(
        page_ultraview=page,
        current_mode=lambda: "time",
        cursor_pill_snapshot=lambda: None,
        restore_cursor_pill_snapshot=lambda *_a, **_k: None,
        clear_cursor_pill=lambda: None,
        split_active=lambda: False,
        secondary_canvas=lambda: None,
        focused_canvas=lambda: None,
    )
    state = window.view_manager.get(0)
    state.view_id = "view-a"
    state.name = "Alpha"
    state.tab_color = "#111111"
    canvas = FakeCanvas()
    ref = _ref("view-a")
    add_ref(coord.board, ref)
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "open")
    _flush()
    coord.refresh_page()
    card = page.card_widget("time", "view-a")
    assert card is not None
    assert card.model().title == "Alpha"
    assert card.model().tab_color == "#111111"
    window.view_manager.rename(0, "转向力矩")
    window.view_manager.set_color(0, "#ff3366")
    coord.refresh_page()
    card = page.card_widget("time", "view-a")
    assert card.model().title == "转向力矩"
    assert card.model().tab_color == "#ff3366"
    page.deleteLater()
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_preview_path_never_calls_restore_or_source_replot(qapp):
    source = _COORDINATOR_PATH.read_text(encoding="utf-8")
    for name in _FORBIDDEN_SOURCE_NAMES:
        assert name not in source

    window, coord = _make_coord()
    window.view_manager.get(0).view_id = "view-a"
    canvas = FakeCanvas()
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "preview")
    _flush()
    assert window.restore_calls == 0
    assert window.plot_time_calls == 0
    assert coord.store.get(ref) is not None
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_markup_revision_add_move_remove_clear(qapp, monkeypatch):
    from mf4_analyzer.ui.pg_canvases import TimeDomainCanvasPG

    canvas = TimeDomainCanvasPG()
    canvas.resize(640, 360)
    canvas.show()
    QCoreApplication.processEvents()
    t = np.linspace(0.0, 1.0, 32)
    y = np.sin(2.0 * np.pi * t)
    canvas.plot_channels(
        [("speed", True, t, y, "#1769e0", "rpm", "fid-1")],
        mode="subplot",
    )
    manager = canvas._annotations
    assert manager.markup_revision == 0
    monkeypatch.setattr(
        manager,
        "_nearest_data_point",
        lambda _pos: ("speed", 0.25, 0.5, "#1769e0", "rpm"),
    )
    manager._add_remark(QPoint(120, 100))
    assert manager.markup_revision == 1
    text = manager.remarks[0]["text"]
    text.setPos(text.pos().x() + 6.0, text.pos().y() + 6.0)
    QCoreApplication.processEvents()
    assert manager.markup_revision == 2
    manager._remove_remark_by_index(0)
    assert manager.markup_revision == 3
    manager.clear_remarks()
    assert manager.markup_revision == 3
    manager._add_remark(QPoint(120, 100))
    assert manager.markup_revision == 4
    manager.clear_remarks()
    assert manager.markup_revision == 5
    manager.clear_remarks()
    assert manager.markup_revision == 5
    canvas.deleteLater()


def _payload_fn_dump(name: str) -> str:
    tree = ast.parse(_COORDINATOR_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.dump(node)
    raise AssertionError(f"missing function {name}")


def test_payload_builders_do_not_read_active_page_or_canvas_fallback():
    analysis = _payload_fn_dump("_analysis_payload")
    time_fn = _payload_fn_dump("_time_payload")
    assert "_analysis_page" not in analysis
    assert "canvas_time" not in analysis
    assert "canvas_time" not in time_fn
    widget = _payload_fn_dump("_widget_for_ref")
    assert "canvas_time" not in widget
    assert "_analysis_page" not in widget


def test_inactive_analysis_digest_ignores_active_page_runtime(qapp):
    window, coord = _make_coord()
    fft_manager = ViewManager(state_factory=AnalysisViewState)
    window.analysis_managers["fft"] = fft_manager
    state_a = fft_manager.get(0)
    state_a.view_id = "fft-a"
    state_a.panes = [PaneState(sources=[("f1", "torque")])]
    idx_b = fft_manager.new_view()
    state_b = fft_manager.get(idx_b)
    state_b.view_id = "fft-b"
    state_b.panes = [PaneState(sources=[("f1", "torque")])]
    pane = FakeCanvas()
    page = FakePage([pane])
    window.pages["fft"] = page
    ref_a = _ref("fft-a", "fft")
    ref_b = _ref("fft-b", "fft")
    coord.bind_canvas(page, ref_a)
    digest_a = coord.current_digest_for(ref_a)
    assert digest_a is not None

    coord.bind_canvas(page, ref_b)
    page._panes.append(FakeCanvas())
    pane.markup_revision = 7
    digest_a_inactive = coord.current_digest_for(ref_a)
    digest_b = coord.current_digest_for(ref_b)
    assert digest_a_inactive == digest_a
    assert digest_b != digest_a

    coord.bind_canvas(page, ref_a)
    pane.markup_revision = 8
    assert coord.current_digest_for(ref_a) != digest_a
    page.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_time_ref_does_not_fallback_to_active_canvas(qapp):
    window, coord = _make_coord()
    manager = window.view_manager
    manager.get(0).view_id = "view-a"
    idx_b = manager.new_view()
    manager.get(idx_b).view_id = "view-b"
    canvas_a = FakeCanvas("#111111")
    canvas_b = FakeCanvas("#222222")
    window.canvas_time = canvas_b
    ref_a = _ref("view-a")
    ref_b = _ref("view-b")
    coord.bind_canvas(canvas_b, ref_b)
    canvas_b.markup_revision = 9
    unbound = coord.current_digest_for(ref_a)
    coord.bind_canvas(canvas_a, ref_a)
    canvas_a.markup_revision = 0
    baseline = coord.current_digest_for(ref_a)
    assert unbound == baseline
    canvas_a.markup_revision = 3
    changed = coord.current_digest_for(ref_a)
    assert changed != baseline
    coord.bind_canvas(canvas_a, None)
    canvas_b.markup_revision = 99
    assert coord.current_digest_for(ref_a) == changed
    canvas_a.deleteLater()
    canvas_b.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_same_cache_key_different_view_ids_isolate_generation(qapp):
    window, coord = _make_coord()
    fft_manager = ViewManager(state_factory=AnalysisViewState)
    window.analysis_managers["fft"] = fft_manager
    fft_manager.get(0).view_id = "fft-a"
    idx_b = fft_manager.new_view()
    fft_manager.get(idx_b).view_id = "fft-b"
    key = ("fft", "shared")
    window._analysis_pins.add("fft", "fft-a", 0, key)
    window._analysis_pins.add("fft", "fft-b", 0, key)
    ref_a = _ref("fft-a", "fft")
    ref_b = _ref("fft-b", "fft")
    result = object()
    coord.notify_result_stored("fft", "fft-a", 0, key, result)
    digest_a = coord.current_digest_for(ref_a)
    digest_b_before = coord.current_digest_for(ref_b)
    coord.notify_result_stored("fft", "fft-b", 0, key, object())
    assert coord.current_digest_for(ref_a) == digest_a
    assert coord.current_digest_for(ref_b) != digest_b_before
    coord.notify_result_stored("fft", "fft-a", 0, key, object())
    assert coord.current_digest_for(ref_a) != digest_a
    coord.clear()
    coord.deleteLater()


def test_inactive_result_bumps_generation_without_grabbing_active_canvas(qapp):
    window, coord = _make_coord()
    fft_manager = ViewManager(state_factory=AnalysisViewState)
    window.analysis_managers["fft"] = fft_manager
    fft_manager.get(0).view_id = "fft-a"
    idx_b = fft_manager.new_view()
    fft_manager.get(idx_b).view_id = "fft-b"
    key = ("fft", "k")
    window._analysis_pins.add("fft", "fft-a", 0, key)
    window._analysis_pins.add("fft", "fft-b", 0, key)
    page = FakePage([FakeCanvas()])
    window.pages["fft"] = page
    ref_a = _ref("fft-a", "fft")
    ref_b = _ref("fft-b", "fft")
    coord.bind_canvas(page, ref_b)
    coord.request_capture(ref_b, page, "active")
    _flush()
    grabs = page.combined_calls
    digest_b = coord.current_digest_for(ref_b)
    coord.notify_result_stored("fft", "fft-a", 0, key, object())
    assert page.combined_calls == grabs
    assert coord.result_generation_for("fft", "fft-a", 0, key) == 1
    assert coord.current_digest_for(ref_b) == digest_b
    assert coord.current_digest_for(ref_a) is not None
    page.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_result_generation_uses_weakref_identity_not_recycled_id(qapp):
    """UVL-A12: generation tracks live object identity, not integer ``id()``.

    Policy: bump unless the previous identity token still points at this
    result (``is``). Weakref when the object supports it; after the first
    object is deleted and collected, a new object must bump even if
    CPython reused the address. Values that cannot be weakly referenced
    (``object()``, tuples) keep a strong token — same live object must not
    bump, a replacement must.
    """
    class _Probe:
        pass

    window, coord = _make_coord()
    key = ("fft", "uvl-a12")
    first = _Probe()
    coord.notify_result_stored("fft", "fft-a", 0, key, first)
    assert coord.result_generation_for("fft", "fft-a", 0, key) == 1
    coord.notify_result_stored("fft", "fft-a", 0, key, first)
    assert coord.result_generation_for("fft", "fft-a", 0, key) == 1

    del first
    gc.collect()
    second = _Probe()
    identity = getattr(coord, "_result_identity", None)
    if isinstance(identity, dict):
        slot = coord._generation_slot("fft", "fft-a", 0, key)
        identity[slot] = id(second)
    coord.notify_result_stored("fft", "fft-a", 0, key, second)
    assert coord.result_generation_for("fft", "fft-a", 0, key) == 2

    bare = ("fft", "no-weakref")
    token = object()
    coord.notify_result_stored("fft", "fft-a", 0, bare, token)
    assert coord.result_generation_for("fft", "fft-a", 0, bare) == 1
    coord.notify_result_stored("fft", "fft-a", 0, bare, token)
    assert coord.result_generation_for("fft", "fft-a", 0, bare) == 1
    coord.notify_result_stored("fft", "fft-a", 0, bare, object())
    assert coord.result_generation_for("fft", "fft-a", 0, bare) == 2
    coord.clear()
    coord.deleteLater()


def test_reset_restore_shutdown_clear_runtime_ledger(qapp):
    window, coord = _make_coord()
    manager = window.view_manager
    manager.get(0).view_id = "view-a"
    canvas = FakeCanvas()
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    canvas.markup_revision = 4
    changed = coord.current_digest_for(ref)
    assert coord._runtime.get(ref) is not None
    coord.reset_project_state()
    assert coord._runtime.get(ref) is None
    coord.bind_canvas(canvas, ref)
    canvas.markup_revision = 5
    coord.current_digest_for(ref)
    assert coord._runtime.get(ref) is not None
    coord.restore_project_state(None)
    assert coord._runtime.get(ref) is None
    coord.bind_canvas(canvas, ref)
    coord.current_digest_for(ref)
    coord.shutdown()
    assert coord._runtime.get(ref) is None
    canvas.deleteLater()
    coord.deleteLater()
    assert changed is not None


def test_digest_unavailable_keeps_old_image_stale(qapp):
    from mf4_analyzer.ui.ultraview_state import STATUS_MISSING, STATUS_STALE

    window, coord = _make_coord()
    manager = window.view_manager
    manager.get(0).view_id = "view-a"
    canvas = FakeCanvas()
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "seed")
    _flush()
    record = coord.store.get(ref)
    assert record is not None and record.image is not None
    manager.views[:] = []
    assert coord.current_digest_for(ref) is None
    exists = coord._ref_exists(ref)
    assert exists is False
    from mf4_analyzer.ui.chart_stack.ultraview.preview_store import PreviewStore
    from mf4_analyzer.ui.ultraview_state import derive_preview_status

    assert derive_preview_status(
        True,
        PreviewStore.image_valid(record.image),
        record.captured_digest,
        None,
    ) == STATUS_STALE
    assert derive_preview_status(True, False, None, None) == STATUS_MISSING
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def _analysis_capture_setup(window, section, panes, view_id="view-a"):
    manager = ViewManager(state_factory=AnalysisViewState)
    window.analysis_managers[section] = manager
    state = manager.get(0)
    state.view_id = view_id
    state.panes = [PaneState(sources=[("f1", "ch")]) for _ in panes]
    page = FakePage(panes)
    window.pages[section] = page
    return page, _ref(view_id, section)


def test_capture_skips_publish_when_all_panes_have_no_result(qapp):
    from mf4_analyzer.ui.ultraview_state import (
        STATUS_MISSING,
        derive_preview_status,
    )

    window, coord = _make_coord()
    for section in ("fft", "fft_time", "frf", "order"):
        pane_a = FakeCanvas("#010101")
        pane_b = FakeCanvas("#020202")
        pane_a._has_result = False
        pane_b._has_result = False
        page, ref = _analysis_capture_setup(
            window, section, [pane_a, pane_b], view_id=f"{section}-empty"
        )
        coord.bind_canvas(page, ref)
        coord.request_capture(ref, page, "empty-all-panes")
        _flush()
        assert page.combined_calls == 0, section
        assert pane_a.grab_calls == 0, section
        assert pane_b.grab_calls == 0, section
        assert coord.store.get(ref) is None, section
        assert derive_preview_status(
            True, False, None, coord.current_digest_for(ref)
        ) == STATUS_MISSING
        page.deleteLater()
        pane_a.deleteLater()
        pane_b.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_capture_no_result_preserves_existing_preview_as_stale(qapp):
    from mf4_analyzer.ui.chart_stack.ultraview.preview_store import PreviewStore
    from mf4_analyzer.ui.ultraview_state import STATUS_STALE, derive_preview_status

    window, coord = _make_coord()
    pane = FakeCanvas("#445566")
    page, ref = _analysis_capture_setup(
        window, "fft_time", [pane], view_id="fft-time-stale"
    )
    coord.bind_canvas(page, ref)
    coord.request_capture(ref, page, "seed")
    _flush()
    record = coord.store.get(ref)
    assert record is not None and PreviewStore.image_valid(record.image)
    seeded_digest = record.captured_digest
    seeded_image = record.image

    pane._has_result = False
    pane.markup_revision += 1
    coord.request_capture(ref, page, "cleared-result")
    _flush()
    kept = coord.store.get(ref)
    assert kept is not None
    assert kept.image is seeded_image
    assert kept.captured_digest == seeded_digest
    assert page.combined_calls == 1
    assert derive_preview_status(
        True,
        PreviewStore.image_valid(kept.image),
        kept.captured_digest,
        coord.current_digest_for(ref),
    ) == STATUS_STALE
    page.deleteLater()
    pane.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_capture_no_result_without_prior_image_stays_missing(qapp):
    window, coord = _make_coord()
    pane = FakeCanvas()
    pane._has_result = False
    page, ref = _analysis_capture_setup(window, "frf", [pane], view_id="frf-missing")
    coord.bind_canvas(page, ref)
    coord.request_capture(ref, page, "never-computed")
    _flush()
    assert coord.store.get(ref) is None
    assert page.combined_calls == 0
    page.deleteLater()
    pane.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_capture_allows_composite_when_one_pane_has_result(qapp):
    window, coord = _make_coord()
    live = FakeCanvas("#101010")
    empty = FakeCanvas("#202020")
    empty._has_result = False
    page, ref = _analysis_capture_setup(
        window, "order", [live, empty], view_id="order-partial"
    )
    coord.bind_canvas(page, ref)
    coord.request_capture(ref, page, "partial-split")
    _flush()
    assert page.combined_calls == 1
    assert coord.store.get(ref) is not None
    page.deleteLater()
    live.deleteLater()
    empty.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_time_capture_skips_when_canvas_has_no_curves(qapp):
    window, coord = _make_coord()
    window.view_manager.get(0).view_id = "view-a"
    canvas = FakeCanvas()
    canvas.has_result = None
    canvas._quality_state = "red"
    canvas._curve_count = 0
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "empty-time")
    _flush()
    assert canvas.grab_calls == 0
    assert coord.store.get(ref) is None
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_time_digest_stable_when_numpy_wrappers_churn(qapp):
    """Presentation digest must not include ndarray ids from to_numpy wrappers."""
    window, coord = _make_coord()
    window.view_manager.get(0).view_id = "view-a"
    window.view_manager.get(0).checked = [("fid-1", "rpm")]
    samples = np.linspace(0.0, 1.0, 32)

    class _Column:
        def __init__(self, values):
            self._values = np.asarray(values, dtype=np.float64)

        def to_numpy(self, copy=False):
            return self._values.copy()

    class _Frame:
        columns = ("rpm",)

        def __init__(self, values):
            self._col = _Column(values)

        def __getitem__(self, key):
            return self._col

    window.files = {
        "fid-1": SimpleNamespace(
            data=_Frame(samples),
            time_array=np.linspace(0.0, 1.0, 32),
        )
    }
    ref = _ref("view-a")
    first = coord.current_digest_for(ref)
    second = coord.current_digest_for(ref)
    assert first is not None
    assert first == second
    window.files["fid-1"].data._col._values[:] = 7.0
    assert coord.current_digest_for(ref) != first
    coord.clear()
    coord.deleteLater()


def test_time_canvas_dense_raster_captures_when_native_curve_count_is_zero(qapp):
    """Ready raster covers native PlotCurveItems; curve_count is then 0."""
    window, coord = _make_coord()
    window.view_manager.get(0).view_id = "view-a"
    canvas = FakeCanvas()
    canvas.has_result = None
    canvas._quality_state = "green"
    canvas._curve_count = 0
    canvas._render_path = "dense-raster"
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "dense-raster")
    _flush()
    assert canvas.grab_calls == 1
    record = coord.store.get(ref)
    assert record is not None
    assert record.image is not None
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_time_canvas_channel_lines_capture_when_quality_curve_count_is_zero(qapp):
    window, coord = _make_coord()
    window.view_manager.get(0).view_id = "view-a"
    canvas = FakeCanvas()
    canvas.has_result = None
    canvas._quality_state = "red"
    canvas._curve_count = 0
    canvas._channel_lines = {"torque": object()}
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "channel-lines")
    _flush()
    assert canvas.grab_calls == 1
    assert coord.store.get(ref) is not None
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_time_canvas_with_curves_captures_when_aa_stays_red(qapp):
    """AA red means native non-AA plot, not an empty canvas (dense EPS traces)."""
    window, coord = _make_coord()
    window.view_manager.get(0).view_id = "view-a"
    canvas = FakeCanvas()
    canvas.has_result = None
    canvas._quality_state = "red"
    canvas._curve_count = 6
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "dense-non-aa")
    _flush()
    assert canvas.grab_calls == 1
    record = coord.store.get(ref)
    assert record is not None
    assert record.image is not None
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_time_canvas_yellow_aa_waits_then_captures(qapp):
    window, coord = _make_coord()
    window.view_manager.get(0).view_id = "view-a"
    canvas = FakeCanvas()
    canvas.has_result = None
    canvas._quality_state = "yellow"
    canvas._curve_count = 4
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "aa-pending")
    _flush()
    assert canvas.grab_calls == 0
    assert coord.store.get(ref) is None
    canvas._quality_state = "green"
    coord.request_capture(ref, canvas, "aa-settled")
    _flush()
    assert canvas.grab_calls == 1
    assert coord.store.get(ref) is not None
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_lru_cleared_image_recaptures_same_digest(qapp):
    window, coord = _make_coord()
    window.view_manager.get(0).view_id = "view-a"
    canvas = FakeCanvas()
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "first")
    _flush()
    assert canvas.grab_calls == 1
    record = coord.store.get(ref)
    assert record is not None
    digest = record.captured_digest
    record.image = None
    coord.request_capture(ref, canvas, "after-lru")
    _flush()
    assert canvas.grab_calls == 2
    restored = coord.store.get(ref)
    assert restored is not None
    assert restored.captured_digest == digest
    assert restored.image is not None
    assert restored.image.isNull() is False
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_capture_ignores_destroyed_canvas_without_stale_publish(qapp):
    window, coord = _make_coord()
    window.view_manager.get(0).view_id = "view-a"
    canvas = FakeCanvas()
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "first")
    _flush()
    assert canvas.grab_calls == 1
    old_digest = coord.store.get(ref).captured_digest
    canvas.markup_revision += 1
    coord.request_capture(ref, canvas, "queued")
    sip.delete(canvas)
    _flush()
    record = coord.store.get(ref)
    assert record is not None
    assert record.captured_digest == old_digest
    coord.clear()
    coord.deleteLater()


def _visible_sheet(window):
    sheet = QWidget()
    sheet.resize(120, 80)
    sheet.show()
    window._ultraview_sheet = sheet
    return sheet


def test_idle_capture_coalesces_range_signals(qapp):
    window, coord = _make_coord()
    sheet = _visible_sheet(window)
    window.view_manager.get(0).view_id = "view-a"
    state = window.view_manager.get(0)
    canvas = FakeCanvas()
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "open")
    _flush()
    assert canvas.grab_calls == 1
    first = coord.store.get(ref).captured_digest

    for _ in range(5):
        canvas.visible_range_changed.emit()
        canvas.cursor_info.emit("t=0.1s")
    assert canvas.grab_calls == 1
    state.xlim = (0.2, 0.8)
    canvas.visible_range_changed.emit()
    assert canvas.grab_calls == 1
    QTest.qWait(_IDLE_CAPTURE_MS + 80)
    _flush()
    assert canvas.grab_calls == 2
    updated = coord.store.get(ref)
    assert updated is not None
    assert updated.captured_digest != first
    pan_digest = updated.captured_digest
    canvas.markup_revision += 1
    canvas.markup_revision_changed.emit()
    QTest.qWait(_IDLE_CAPTURE_MS + 80)
    _flush()
    assert canvas.grab_calls == 3
    marked = coord.store.get(ref)
    assert marked is not None
    assert marked.captured_digest != pan_digest
    sheet.deleteLater()
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_idle_cursor_info_does_not_project_each_signal(qapp):
    window, coord = _make_coord()
    sheet = _visible_sheet(window)
    page = UltraViewPage()
    page.resize(240, 180)
    page.show()
    window.chart_stack = SimpleNamespace(
        page_ultraview=page,
        current_mode=lambda: "time",
        cursor_pill_snapshot=lambda: None,
        restore_cursor_pill_snapshot=lambda *_a, **_k: None,
        clear_cursor_pill=lambda: None,
        split_active=lambda: False,
        secondary_canvas=lambda: None,
        focused_canvas=lambda: None,
    )
    window.view_manager.get(0).view_id = "view-a"
    canvas = FakeCanvas()
    ref = _ref("view-a")
    add_ref(coord.board, ref)
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "open")
    _flush()
    coord._push_preview(ref)

    refreshes = []
    orig_refresh = page._refresh_projection

    def counted_refresh():
        refreshes.append(1)
        orig_refresh()

    page._refresh_projection = counted_refresh
    digest_calls = []
    orig_digest = coord.current_digest_for

    def counted_digest(target):
        digest_calls.append(target)
        return orig_digest(target)

    coord.current_digest_for = counted_digest
    canvas.markup_revision += 1

    for _ in range(20):
        canvas.cursor_info.emit("t=0")
        qapp.processEvents()
    assert refreshes == []
    assert digest_calls == []

    QTest.qWait(_IDLE_CAPTURE_MS + 80)
    _flush()
    assert 1 <= len(refreshes) <= 4
    assert digest_calls
    sheet.deleteLater()
    page.deleteLater()
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_digest_changed_requeues_and_publishes(qapp):
    window, coord = _make_coord()
    window.view_manager.get(0).view_id = "view-a"
    canvas = FakeCanvas()
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "first")
    _flush()
    first = coord.store.get(ref).captured_digest
    grabs = canvas.grab_calls

    canvas.markup_revision += 1
    coord.request_capture(ref, canvas, "stale-queue")
    canvas.markup_revision += 1
    live = coord.current_digest_for(ref)
    assert live != first
    _flush()
    record = coord.store.get(ref)
    assert record is not None
    assert record.captured_digest == live
    assert canvas.grab_calls == grabs + 1
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_digest_changed_retry_is_capped(qapp):
    window, coord = _make_coord()
    window.view_manager.get(0).view_id = "view-a"
    canvas = FakeCanvas()
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "first")
    _flush()

    details = []
    orig_warn = coord._warn_capture

    def spy_warn(target, widget, reason, detail):
        details.append(detail)
        return orig_warn(target, widget, reason, detail)

    coord._warn_capture = spy_warn
    n = {"i": 0}

    def moving(_target):
        n["i"] += 1
        return f"moving-{n['i']}"

    coord.current_digest_for = moving
    coord.request_capture(ref, canvas, "oscillate")
    _flush(24)
    assert details.count("digest-changed") == _DIGEST_RETRY_LIMIT + 1
    assert "digest-retry-exhausted" in details
    after = list(details)
    _flush(12)
    assert details == after
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_idle_pending_per_ref_not_starved_by_other_canvas(qapp):
    window, coord = _make_coord()
    sheet = _visible_sheet(window)
    manager = window.view_manager
    manager.get(0).view_id = "view-a"
    idx_b = manager.new_view()
    manager.get(idx_b).view_id = "view-b"
    canvas_a = FakeCanvas("#111111")
    canvas_b = FakeCanvas("#222222")
    ref_a = _ref("view-a")
    ref_b = _ref("view-b")
    coord.bind_canvas(canvas_a, ref_a)
    coord.bind_canvas(canvas_b, ref_b)
    coord.request_capture(ref_a, canvas_a, "open")
    coord.request_capture(ref_b, canvas_b, "open")
    _flush()
    grabs_b = canvas_b.grab_calls

    canvas_b.markup_revision += 1
    canvas_b.markup_revision_changed.emit()
    for _ in range(8):
        canvas_a.cursor_info.emit("hover")
        QTest.qWait(30)
    _flush()
    assert canvas_b.grab_calls == grabs_b + 1
    sheet.deleteLater()
    canvas_a.deleteLater()
    canvas_b.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_idle_does_not_schedule_when_sheet_hidden(qapp):
    window, coord = _make_coord()
    window.view_manager.get(0).view_id = "view-a"
    canvas = FakeCanvas()
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "open")
    _flush()
    grabs = canvas.grab_calls
    window.view_manager.get(0).xlim = (0.1, 0.4)
    canvas.visible_range_changed.emit()
    QTest.qWait(_IDLE_CAPTURE_MS + 80)
    _flush()
    assert canvas.grab_calls == grabs
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_grab_image_prefers_presentation_pixmap(qapp):
    window, coord = _make_coord()
    window.view_manager.get(0).view_id = "view-a"
    calls = []

    class _Stack:
        def grab_presentation_pixmap(self, target, *, scale=1.0):
            calls.append((target, scale))
            pix = QPixmap(32, 24)
            pix.fill(QColor("#ff00ff"))
            return pix

    window.chart_stack = _Stack()
    canvas = FakeCanvas("#000000")
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "pill")
    _flush()
    assert calls == [(canvas, 1.0)]
    record = coord.store.get(ref)
    assert record is not None
    assert record.image is not None
    pixel = record.image.pixelColor(2, 2)
    assert pixel.red() > 200 and pixel.blue() > 200 and pixel.green() < 80
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def _page_stack(page, **extra):
    fields = dict(
        page_ultraview=page,
        current_mode=lambda: "time",
        cursor_pill_snapshot=lambda: None,
        restore_cursor_pill_snapshot=lambda *_a, **_k: None,
        clear_cursor_pill=lambda: None,
        split_active=lambda: False,
        secondary_canvas=lambda: None,
        focused_canvas=lambda: None,
        canvas_time=None,
    )
    fields.update(extra)
    return SimpleNamespace(**fields)


def test_add_from_tab_binds_primary_when_focus_is_secondary(qapp):
    window, coord = _make_coord()
    manager = window.view_manager
    manager.get(0).view_id = "view-a"
    idx_b = manager.new_view()
    manager.get(idx_b).view_id = "view-b"
    manager.set_active(0)
    manager.set_split(idx_b)
    primary = FakeCanvas("#cc1111")
    secondary = FakeCanvas("#11cc44")
    window.chart_stack = _page_stack(
        None,
        canvas_time=primary,
        split_active=lambda: True,
        secondary_canvas=lambda: secondary,
        focused_canvas=lambda: secondary,
    )
    ref_a = _ref("view-a")
    ref_b = _ref("view-b")
    coord.bind_canvas(secondary, ref_b)
    coord.request_capture(ref_b, secondary, "partner")
    _flush()
    partner_grabs = secondary.grab_calls
    partner_digest = coord.store.get(ref_b).captured_digest

    coord.add_from_source_tab("time", "view-a")
    _flush()
    assert coord.bound_ref_for(primary) == ref_a
    assert coord.bound_ref_for(secondary) == ref_b
    assert primary.grab_calls >= 1
    assert secondary.grab_calls == partner_grabs
    record_a = coord.store.get(ref_a)
    assert record_a is not None
    pixel = record_a.image.pixelColor(2, 2)
    assert pixel.red() > 150 and pixel.green() < 80
    assert coord.store.get(ref_b).captured_digest == partner_digest
    primary.deleteLater()
    secondary.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_add_from_tab_binds_partner_when_focus_is_primary(qapp):
    window, coord = _make_coord()
    manager = window.view_manager
    manager.get(0).view_id = "view-a"
    idx_b = manager.new_view()
    manager.get(idx_b).view_id = "view-b"
    manager.set_active(0)
    manager.set_split(idx_b)
    primary = FakeCanvas("#cc1111")
    secondary = FakeCanvas("#11cc44")
    window.chart_stack = _page_stack(
        None,
        canvas_time=primary,
        split_active=lambda: True,
        secondary_canvas=lambda: secondary,
        focused_canvas=lambda: primary,
    )
    ref_a = _ref("view-a")
    ref_b = _ref("view-b")
    coord.bind_canvas(primary, ref_a)
    coord.request_capture(ref_a, primary, "active")
    _flush()
    primary_grabs = primary.grab_calls

    coord.add_from_source_tab("time", "view-b")
    _flush()
    assert coord.bound_ref_for(secondary) == ref_b
    assert coord.bound_ref_for(primary) == ref_a
    assert secondary.grab_calls >= 1
    assert primary.grab_calls == primary_grabs
    record_b = coord.store.get(ref_b)
    assert record_b is not None
    pixel = record_b.image.pixelColor(2, 2)
    assert pixel.green() > 150 and pixel.red() < 80
    primary.deleteLater()
    secondary.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_reset_clears_page_preview_caches(qapp):
    window, coord = _make_coord()
    page = UltraViewPage()
    page.resize(320, 240)
    page.show()
    window.chart_stack = _page_stack(page)
    window.view_manager.get(0).view_id = "view-a"
    canvas = FakeCanvas()
    ref = _ref("view-a")
    add_ref(coord.board, ref)
    coord.bind_canvas(canvas, ref)
    coord.request_capture(ref, canvas, "open")
    _flush()
    coord.refresh_page()
    assert page._previews
    coord.reset_project_state()
    assert page._previews == {}
    assert page._statuses == {}
    assert page._ref_exists == {}
    page.deleteLater()
    canvas.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_restore_resets_sheet_session(qapp):
    window, coord = _make_coord()
    page = UltraViewPage()
    page.resize(320, 240)
    page.show()
    window.chart_stack = _page_stack(page)
    window.view_manager.get(0).view_id = "view-a"
    add_ref(coord.board, _ref("view-a"))
    coord.refresh_page()
    page.show_focus("time", "view-a")
    page.arm_replacement("time", "view-a")
    page.set_presentation_active(True)
    assert page.focus_layer().isVisible()
    coord.restore_project_state(None)
    assert page.focus_layer().isVisible() is False
    assert page.replacement_ref() is None
    assert page.is_presentation_active() is False
    assert page._previews == {}
    page.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_destroyed_canvas_drops_binding_and_allows_rehook(qapp):
    window, coord = _make_coord()
    window.view_manager.get(0).view_id = "view-a"
    canvas = FakeCanvas()
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    ident = id(canvas)
    assert ident in coord._bindings
    assert ident in coord._hooked_ids
    sip.delete(canvas)
    _flush()
    assert ident not in coord._bindings
    assert ident not in coord._hooked_ids
    assert ident not in coord._destroy_watched
    replacement = FakeCanvas()
    coord.bind_canvas(replacement, ref)
    assert id(replacement) in coord._hooked_ids
    replacement.cursor_info.emit("t=0")
    replacement.deleteLater()
    coord.clear()
    coord.deleteLater()


def test_repeated_project_reset_does_not_stack_destroyed_receivers(qapp, monkeypatch):
    calls = {"n": 0}
    original = UltraViewCoordinator._on_canvas_destroyed

    def wrapped(self, *args, **kwargs):
        calls["n"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(UltraViewCoordinator, "_on_canvas_destroyed", wrapped)
    window, coord = _make_coord()
    canvas = FakeCanvas()
    ref = _ref("view-a")
    coord.bind_canvas(canvas, ref)
    payload = coord.to_project_payload()
    for _ in range(8):
        coord.reset_project_state()
        coord.restore_project_state(payload)
        coord.bind_canvas(canvas, ref)
    sip.delete(canvas)
    _flush()
    assert calls["n"] == 1
    coord.clear()
    coord.deleteLater()

