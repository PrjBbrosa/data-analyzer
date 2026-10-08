"""AnalysisSectionPage: one analysis section's page in the ChartStack.

Layout (spec §4):
    [card pane 0 | card pane 1?]   <- QSplitter(Horizontal)
    [ViewTabBar]                   <- per-section instance

Pane semantics: split lives INSIDE the active view (state.panes), unlike
the time-domain split_pairs pairing. Focus routing mirrors the
time-domain _focused_card pattern (chart_stack.py:1986-2040): click a
pane → it becomes the target for source assignment.

V6 delivers the standalone, testable container only. V7 wires it into
ChartStack/MainWindow (state capture/apply, tabbar signal handling).
"""
from __future__ import annotations

import logging
from contextlib import contextmanager

import numpy as np
from PyQt5.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .image_utils import pixmap_as_device_pixels
from .view_tabbar import ViewTabBar
from .widgets.ultraview_entry import (
    UltraViewEntryButton,
    UltraViewRailFitter,
    make_ultraview_separator,
)
from ..ui_kit.motion import POLICY_LIGHT
from ..ui_kit.qt_lifecycle import as_weak_callable

logger = logging.getLogger(__name__)

_FOCUS_ACCENT = "#2d7ff9"
# A comparison region narrower than this stacks its own 1–2 panes vertically.
# The single-view page stays horizontal; the threshold applies only while a
# cross-view pair is mounted.
_NARROW_PANE_REGION_PX = 420
# Each cross-view region keeps a usable width. The single-view splitter
# does not take this minimum, so in-view alignment stays unchanged.
_COMPARISON_REGION_MIN_PX = 180


class AnalysisPageReadiness:
    """Page-owned chart resource lifecycle (Task 2 / plan §3.2).

    Coordinators (Task 3) may read this; they must not own a second copy.
    Never persisted to project / preset / QSettings.
    """

    UNINITIALIZED = "uninitialized"
    PREPARING = "preparing"
    READY = "ready"
    FAILED = "failed"

# Slim compare-toggle row chrome. Transparent container (lesson
# no-gray-bg-embedded-widgets): an embedded custom QWidget hosting the
# tabbar + toggles must NOT paint the default platform grey, so the row
# frame stays translucent and only the buttons carry chrome.
_COMPARE_ROW_QSS = """
QWidget#analysisCompareRow {
    background-color: #fbfcff;
    border-top: 1px solid #dbe3ee;
    /* Same reason as #timeViewBottomDock in style.qss: this row is the last
     * child of the ChartStack card and spans its full width, so an opaque
     * fill with square corners would overpaint the card's rounded bottom
     * corners. Radii track ChartStack's border-radius (7px). */
    border-bottom-left-radius: 7px;
    border-bottom-right-radius: 7px;
}
QToolButton#analysisCompareToggle {
    min-height: 22px;
    max-height: 22px;
    background: transparent;
    border: 1px solid #d4d8de;
    border-radius: 4px;
    padding: 0 8px;
    color: #5b6471;
    font-size: 11px;
}
QToolButton#analysisCompareToggle:hover { border-color: #b6c6e6; }
QToolButton#analysisCompareToggle:checked {
    background: #eaf2ff;
    border-color: #2d7ff9;
    color: #1f5fd0;
}
QToolButton#analysisCompareToggle:disabled { color: #b8bdc6; }
"""


def _pane_index_for_object(cards, obj):
    """Map a card, its canvas, or the canvas viewport back to a pane index."""
    for i, card in enumerate(cards):
        if obj is card:
            return i
        canvas = getattr(card, "canvas", None)
        if canvas is not None:
            if obj is canvas:
                return i
            glw = getattr(canvas, "_glw", None)
            if glw is not None:
                try:
                    viewport = glw.viewport()
                except Exception:
                    viewport = None
                if viewport is not None and obj is viewport:
                    return i
        if isinstance(obj, QWidget) and card.isAncestorOf(obj):
            return i
    return None


def _link_canvases(canvas_a, canvas_b, linked):
    """X-link two panes. Heatmaps (``_img``) also share Y."""
    vb0 = _primary_vb(canvas_a)
    vb1 = _primary_vb(canvas_b)
    if vb0 is None or vb1 is None:
        return
    if linked:
        vb1.setXLink(vb0)
        if hasattr(canvas_a, "_img") and hasattr(canvas_b, "_img"):
            vb1.setYLink(vb0)
        return
    try:
        vb1.setXLink(None)
    except RuntimeError:
        return
    try:
        vb1.setYLink(None)
    except RuntimeError:
        return


class AnalysisPaneHost(QWidget):
    """One view's pane stack inside a cross-view comparison.

    The section page keeps the single tab bar. This host is only the peer
    view's cards and splitter — not a second ``AnalysisSectionPage``.
    """

    pressed = pyqtSignal(int)

    def __init__(self, page, parent=None):
        super().__init__(parent)
        self._page = page
        self._cards = []
        self._focused = 0
        self._linked = False
        self._levels_locked = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._split = QSplitter(Qt.Horizontal, self)
        self._split.setChildrenCollapsible(False)
        lay.addWidget(self._split)

    def pane_count(self) -> int:
        return len(self._cards)

    def cards(self):
        return list(self._cards)

    def card_at(self, idx):
        if idx < 0 or idx >= len(self._cards):
            return None
        return self._cards[idx]

    def canvas_at(self, idx):
        card = self.card_at(idx)
        if card is None:
            return None
        return getattr(card, "canvas", None)

    def set_pane_count(self, count: int) -> None:
        count = max(1, min(2, int(count)))
        while len(self._cards) < count:
            card = self._page._make_card(event_filter=self)
            self._cards.append(card)
            self._split.addWidget(card)
        while len(self._cards) > count:
            self._drop_card(self._cards.pop())
        if self._focused >= len(self._cards):
            self._focused = 0
        self.apply_width_orientation()
        self._apply_focus_style()

    def set_focused_index(self, idx: int) -> None:
        if not self._cards:
            return
        self._focused = max(0, min(int(idx), len(self._cards) - 1))
        self._apply_focus_style()

    def clear_focus_markers(self) -> None:
        for card in self._cards:
            marker = getattr(card, "set_focus_marker", None)
            if callable(marker):
                marker(None)

    def set_linked(self, linked: bool) -> None:
        self._linked = bool(linked)
        if len(self._cards) < 2:
            return
        _link_canvases(
            self._cards[0].canvas, self._cards[1].canvas, self._linked,
        )

    def set_levels_locked(self, locked: bool) -> None:
        """In-view color lock for this region only."""
        self._levels_locked = bool(locked)
        canvases = self._heatmap_canvases()
        for canvas in canvases:
            try:
                canvas.levels_changed.disconnect(self._on_locked_levels)
            except TypeError:
                pass
        if not self._levels_locked or len(canvases) < 2:
            return
        for canvas in canvases:
            canvas.levels_changed.connect(self._on_locked_levels)

    def apply_width_orientation(self) -> None:
        self._page._apply_region_orientation(self._split, len(self._cards))

    def teardown(self) -> None:
        try:
            self.pressed.disconnect(self._page._on_peer_pane_pressed)
        except TypeError:
            pass
        while self._cards:
            self._drop_card(self._cards.pop())

    def eventFilter(self, obj, event):  # noqa: N802 - Qt API
        if event.type() == QEvent.MouseButtonPress:
            idx = _pane_index_for_object(self._cards, obj)
            if idx is not None:
                self.pressed.emit(idx)
        return super().eventFilter(obj, event)

    def _heatmap_canvases(self):
        out = []
        for card in self._cards:
            canvas = getattr(card, "canvas", None)
            if canvas is not None and hasattr(canvas, "_img") and hasattr(canvas, "_cbar"):
                out.append(canvas)
        return out

    def _on_locked_levels(self, lo, hi) -> None:
        if not self._levels_locked:
            return
        for canvas in self._heatmap_canvases():
            self._page._set_canvas_levels(canvas, lo, hi, auto=False)

    def _apply_focus_style(self) -> None:
        accent = self._page._active_view_focus_accent()
        for i, card in enumerate(self._cards):
            marker = getattr(card, "set_focus_marker", None)
            if callable(marker):
                marker(accent if i == self._focused else None)

    def _drop_card(self, card) -> None:
        try:
            card.removeEventFilter(self)
        except RuntimeError:
            pass
        canvas = getattr(card, "canvas", None)
        if canvas is not None:
            try:
                canvas.removeEventFilter(self)
            except RuntimeError:
                pass
        try:
            card.setParent(None)
        except RuntimeError:
            return
        card.deleteLater()


def _primary_vb(canvas):
    """Return a canvas's MAIN-row ViewBox, tolerant of the two pg canvas shapes.

    PgHeatmapCanvas exposes the single main PlotItem as ``canvas._plot``;
    PgLineCanvas has NO ``_plot`` — it has two fixed rows ``_plot_amp`` +
    ``_plot_time`` (the preview row follows the amp row's X navigation),
    so linking the two canvases' AMP ViewBoxes propagates to the whole line
    figure. A naive ``canvas._plot.vb`` AttributeErrors on the line canvas.
    """
    plot = getattr(canvas, '_plot', None)
    if plot is None:
        plot = getattr(canvas, '_plot_amp', None)
    return plot.vb if plot is not None else None


class AnalysisSectionPage(QWidget):
    focus_changed = pyqtSignal(int)          # focused pane index
    link_toggled = pyqtSignal(bool)
    # V8: user-driven EDGE toggle of a compare option. Carries the
    # state.compare key ('x_linked' / 'levels_locked') and the new value so
    # MainWindow can write it back onto the active view's state. This is the
    # producer that closes the compare write-back loop (V7 only READ
    # state.compare to drive set_linked). Distinct from ``link_toggled``,
    # which set_linked fires non-edge (every apply, incl. programmatic) — the
    # button's toggled(bool) is a TRUE edge, so the two must not be conflated.
    compare_toggled = pyqtSignal(str, bool)
    pane_added = pyqtSignal(object)
    pane_removing = pyqtSignal(object)
    # Cross-view focus. Carries the clicked view id and pane. The page does
    # not guess whether the user wanted an in-view split.
    comparison_focus_requested = pyqtSignal(str, int)
    # Cross-view camera / color-scale flags. Distinct from compare_toggled,
    # which writes AnalysisViewState.compare for the in-view pane pair.
    comparison_display_toggled = pyqtSignal(str, bool)

    def __init__(
        self,
        *,
        section: str,
        manager,
        card_factory,
        parent=None,
        defer_charts: bool = False,
    ):
        super().__init__(parent)
        self.section = section
        self.manager = manager
        self._card_factory = card_factory
        self._defer_charts = bool(defer_charts)
        self._readiness = AnalysisPageReadiness.UNINITIALIZED
        self._prepare_error = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._split = QSplitter(Qt.Horizontal, self)
        self._split.setChildrenCollapsible(False)
        self._layout_sync_pending = False
        self._cards = []
        self._toolbar = None
        self._focused = 0
        self._previous_focused = 0
        self._linked = False
        self._levels_locked = False
        self._color_projection_depth = 0
        self._peer_host = None
        self._view_split = None
        self._host_view_id = ""
        self._peer_view_id = ""
        self._comparison_focus_is_host = True
        self._comparison_expanded = False
        self._suppress_focus_emit = False
        self._suppress_color_policy_echo = False
        self._split.splitterMoved.connect(self._schedule_heatmap_layout_sync)
        # Lightweight prepare/fail chrome (Task 3). Not a permanent progress bar;
        # cancellable by leaving the section. Never persisted.
        self._prepare_banner = QLabel(self)
        self._prepare_banner.setObjectName("analysisPrepareBanner")
        self._prepare_banner.setAlignment(Qt.AlignCenter)
        self._prepare_banner.setWordWrap(True)
        self._prepare_banner.setStyleSheet(
            "QLabel#analysisPrepareBanner {"
            " background-color: rgba(251, 252, 255, 230);"
            " color: #5b6471;"
            " font-size: 13px;"
            " padding: 16px;"
            " border: none;"
            "}"
        )
        self._prepare_banner.hide()
        if not self._defer_charts:
            self._cards = [self._make_card()]
            self._split.addWidget(self._cards[0])
            detach_toolbar = getattr(self._cards[0], 'detach_toolbar', None)
            if (
                callable(detach_toolbar)
                and getattr(self._cards[0], 'toolbar', None) is not None
            ):
                lay.addWidget(detach_toolbar(self))
                self._toolbar = self._cards[0].toolbar
                self._configure_shared_toolbar()
        lay.addWidget(self._split, stretch=1)

        self.manager.active_changed.connect(self.refresh_focus_style)
        self.manager.views_changed.connect(self.refresh_focus_style)
        # Swallows the toggled(bool) edge during programmatic
        # sync_compare_buttons so state→button seeding never loops back as a
        # compare_toggled write. Set before the buttons are wired.
        self._suppress_compare_edge = False

        # Bottom row: [ViewTabBar ........... 关闭对比窗格 | 联动缩放? | 锁定色阶? | UltraView].
        # Compare toggles stay on THIS page (not inside the shared ViewTabBar).
        # UltraView Dock is always the last clickable item of the host row.
        # Manager + tabbar exist before charts so deferred pages keep View
        # identity and early signal wiring (plan §3.3).
        self._compare_row = QWidget(self)
        self._compare_row.setObjectName("analysisCompareRow")
        self._compare_row.setAttribute(Qt.WA_StyledBackground, True)
        # 2026-06-13: this bottom row is the analysis section's view-tab bar.
        # Give it the same chrome as the time-domain dock (#timeViewBottomDock):
        # a light #fbfcff bar with a 1px top divider, so the View 1/2/3 tabs
        # read as a real bar instead of floating on the page. An explicit
        # background (not the old WA_TranslucentBackground + transparent QSS)
        # is what paints the bar — WA_StyledBackground keeps it from falling
        # back to the platform grey (lesson no-gray-bg-embedded-widgets).
        self._compare_row.setStyleSheet(_COMPARE_ROW_QSS)
        row = QHBoxLayout(self._compare_row)
        row.setContentsMargins(0, 0, 8, 0)
        row.setSpacing(6)

        # ViewTabBar's ctor is (manager, parent) — pass the manager, NOT self.
        # Analysis split adds/removes pane 2 inside the ACTIVE view, unlike
        # TimeDomain's two-View merge/pair semantics.
        self.tabbar = ViewTabBar(
            manager,
            self._compare_row,
            section=self.section,
            split_action_mode='active_pane',
            active_split_provider=self.pane_count,
            comparison_open_provider=self.cross_view_comparison_open,
            focused_pane_provider=self.focused_index,
            split_action_labels={
                'split': "添加对比窗格",
                'replace': "添加对比窗格",
                'clear': "关闭对比窗格",
            },
        )
        self.tabbar.set_motion_policy(POLICY_LIGHT)
        row.addWidget(self.tabbar, 1)

        self.btn_link = self._make_toggle(
            "联动缩放", "两个分屏同步缩放/平移（X 轴，热力图含 Y 轴）")
        self.btn_lock_levels = self._make_toggle(
            "锁定色阶", "两个热力图共用同一色阶范围；拖动一格 colorbar 另一格跟随")
        self.btn_view_link = self._make_toggle(
            "联动两 View", "两个 View 的相机一起移动；不改变分析时间和数值参数")
        self.btn_view_levels = self._make_toggle(
            "锁定两 View 色阶", "两个热图共用色阶；色阶不一致时不锁定")
        self.btn_view_expand = self._make_command(
            "展开焦点", "展开当前焦点区域，另一侧保留可返回的宽度")
        row.addWidget(self.btn_link, 0, Qt.AlignVCenter)
        row.addWidget(self.btn_lock_levels, 0, Qt.AlignVCenter)
        row.addWidget(self.btn_view_link, 0, Qt.AlignVCenter)
        row.addWidget(self.btn_view_levels, 0, Qt.AlignVCenter)
        row.addWidget(self.btn_view_expand, 0, Qt.AlignVCenter)
        self.ultraview_separator = make_ultraview_separator(self._compare_row)
        self.ultraview_entry = UltraViewEntryButton(self._compare_row)
        row.addWidget(self.ultraview_separator, 0, Qt.AlignVCenter)
        row.addWidget(self.ultraview_entry, 0, Qt.AlignVCenter)
        self._ultraview_rail_fitter = UltraViewRailFitter(
            host=self._compare_row,
            tabbar=self.tabbar,
            entry=self.ultraview_entry,
            extra_widgets=(
                self.btn_link,
                self.btn_lock_levels,
                self.btn_view_link,
                self.btn_view_levels,
                self.btn_view_expand,
            ),
        )
        self.btn_link.toggled.connect(self._on_link_button_toggled)
        self.btn_lock_levels.toggled.connect(self._on_lock_button_toggled)
        self.btn_view_link.toggled.connect(self._on_view_link_toggled)
        self.btn_view_levels.toggled.connect(self._on_view_levels_toggled)
        self.btn_view_expand.clicked.connect(self._on_expand_clicked)
        # 联动缩放 + 锁定色阶 defaults mirror AnalysisViewState.compare.
        # Seed under suppression so no compare_toggled fires at construction.
        self.sync_compare_buttons(x_linked=True, levels_locked=True)
        self.set_linked(True)
        self.set_levels_locked(True)

        lay.addWidget(self._compare_row)

        self._apply_focus_style()
        self._refresh_compare_buttons()
        self._sync_card_hint_bars()
        if not self._defer_charts:
            self._readiness = AnalysisPageReadiness.READY
        self._sync_prepare_banner()

    # -- deferred chart readiness (Task 2) -------------------------------
    def readiness(self) -> str:
        return self._readiness

    def is_ready(self) -> bool:
        return self._readiness == AnalysisPageReadiness.READY

    def prepare_error(self):
        """Last prepare failure, or None. Never persisted."""
        return self._prepare_error

    def peek_cards(self):
        """Return existing cards without creating charts."""
        return list(self._cards)

    def peek_pane_canvas(self, idx: int):
        """Non-creating canvas lookup; None when missing or out of range."""
        if idx < 0 or idx >= len(self._cards):
            return None
        return getattr(self._cards[idx], "canvas", None)

    def ensure_ready(self) -> None:
        """Synchronously materialize the primary chart card if deferred.

        Idempotent: preparing/ready pages do not build a second instance.
        Does not change ChartStack mode, focus, dirty state, or camera.
        Task 3 idle preload treats one page ensure as a single timer step.
        """
        if self._readiness in (
            AnalysisPageReadiness.READY,
            AnalysisPageReadiness.PREPARING,
        ):
            return
        if not self._defer_charts and self._cards:
            self._readiness = AnalysisPageReadiness.READY
            self._sync_prepare_banner()
            return
        self._readiness = AnalysisPageReadiness.PREPARING
        self._prepare_error = None
        self._sync_prepare_banner()
        try:
            self._materialize_primary_card()
            self._readiness = AnalysisPageReadiness.READY
            self._sync_prepare_banner()
        except Exception as exc:
            self._prepare_error = exc
            logger.exception(
                "AnalysisSectionPage(%s) chart prepare failed", self.section,
            )
            self._cleanup_partial_primary_card()
            self._readiness = AnalysisPageReadiness.FAILED
            self._sync_prepare_banner()
            raise

    def show_preparing_status(self) -> None:
        """Surface the lightweight preparing chrome without forcing ensure."""
        if self._readiness == AnalysisPageReadiness.READY:
            return
        if self._readiness == AnalysisPageReadiness.UNINITIALIZED:
            # Visible intent only; readiness owner stays uninitialized until ensure.
            self._prepare_banner.setText("正在准备图表…\n可切换到其他分区取消等待")
            self._prepare_banner.show()
            self._prepare_banner.raise_()
            self._layout_prepare_banner()
            return
        self._sync_prepare_banner()

    def _sync_prepare_banner(self) -> None:
        banner = getattr(self, "_prepare_banner", None)
        if banner is None:
            return
        if self._readiness == AnalysisPageReadiness.READY:
            banner.hide()
            return
        if self._readiness == AnalysisPageReadiness.PREPARING:
            banner.setText("正在准备图表…\n可切换到其他分区取消等待")
            banner.show()
            banner.raise_()
            self._layout_prepare_banner()
            return
        if self._readiness == AnalysisPageReadiness.FAILED:
            detail = self._prepare_error
            msg = str(detail).strip() if detail else "未知错误"
            if len(msg) > 160:
                msg = msg[:157] + "…"
            banner.setText(f"图表准备失败：{msg}\n再次进入本分区可重试")
            banner.show()
            banner.raise_()
            self._layout_prepare_banner()
            return
        banner.hide()

    def _layout_prepare_banner(self) -> None:
        banner = getattr(self, "_prepare_banner", None)
        split = getattr(self, "_split", None)
        if banner is None or split is None or not banner.isVisible():
            return
        banner.setGeometry(split.geometry())

    def resizeEvent(self, event):  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._layout_prepare_banner()
        self._update_comparison_orientation()
        if self._view_split is not None:
            self._apply_comparison_minimums()
            if self._comparison_expanded:
                self._apply_comparison_sizes()

    def _materialize_primary_card(self) -> None:
        if self._cards:
            return
        card = self._make_card()
        self._cards = [card]
        self._split.addWidget(card)
        detach_toolbar = getattr(card, "detach_toolbar", None)
        if callable(detach_toolbar) and getattr(card, "toolbar", None) is not None:
            lay = self.layout()
            toolbar = detach_toolbar(self)
            # Splitter is index 0 while deferred (no toolbar yet).
            lay.insertWidget(0, toolbar)
            self._toolbar = card.toolbar
            self._configure_shared_toolbar()
        self._apply_focus_style()
        self._refresh_compare_buttons()
        self._sync_card_hint_bars()
        self.tabbar.refresh_split_controls()

    def _cleanup_partial_primary_card(self) -> None:
        """Drop a half-built primary card after prepare failure."""
        while self._cards:
            card = self._cards.pop()
            try:
                card.removeEventFilter(self)
            except Exception:
                pass
            canvas = getattr(card, "canvas", None)
            if canvas is not None:
                try:
                    canvas.removeEventFilter(self)
                except Exception:
                    pass
            try:
                card.setParent(None)
            except Exception:
                pass
            try:
                card.deleteLater()
            except Exception:
                pass
        self._toolbar = None

    # -- pane management -----------------------------------------------
    def _make_card(self, event_filter=None):
        card = self._card_factory()
        # Keep the card eligible for the shared #chartCard chrome. Focus itself
        # is painted by _ChartCard.set_focus_marker(), matching TimeDomain.
        card.setAttribute(Qt.WA_StyledBackground, True)
        filt = self if event_filter is None else event_filter
        card.installEventFilter(filt)
        canvas = getattr(card, 'canvas', None)
        if canvas is not None:
            signal = getattr(canvas, 'layout_geometry_changed', None)
            if signal is not None:
                try:
                    signal.connect(self._schedule_heatmap_layout_sync)
                except Exception:
                    pass
            levels_rebased = getattr(canvas, 'levels_rebased', None)
            if levels_rebased is not None:
                try:
                    levels_rebased.connect(self._on_canvas_levels_rebased)
                except Exception:
                    pass
            colorbar_restored = getattr(canvas, 'colorbar_restored', None)
            if colorbar_restored is not None:
                try:
                    colorbar_restored.connect(self._on_colorbar_restored)
                except Exception:
                    pass
            canvas.installEventFilter(filt)
            glw = getattr(canvas, '_glw', None)
            if glw is not None:
                try:
                    viewport = glw.viewport()
                except Exception:
                    viewport = None
                if viewport is not None:
                    viewport.installEventFilter(filt)
        return card

    def pane_count(self) -> int:
        return len(self._cards)

    def pane_canvas(self, idx: int):
        """Return canvas for pane ``idx``.

        Requires charts to be ready (eager pages always are). Callers that
        must not create should use :meth:`peek_pane_canvas`. ChartStack
        compatibility aliases call :meth:`ensure_ready` first.
        """
        if not self._cards:
            raise RuntimeError(
                f"AnalysisSectionPage({self.section!r}) charts are not ready; "
                "call ensure_ready() first"
            )
        return self._cards[idx].canvas

    def grab_combined_pixmap(self, scale: float = 2.0):
        """Return this page's own panes composited side-by-side.

        The cross-view peer is not included. Explicit comparison export uses
        :meth:`grab_export_pixmap`.
        """
        return self._compose_pixmaps(self._card_pixmaps(self._cards, scale), scale)

    def grab_export_pixmap(self, scale: float = 2.0):
        """Combined export. An open comparison composites host and peer."""
        host = self.grab_combined_pixmap(scale)
        if self._peer_host is None:
            return host
        peer = self._compose_pixmaps(
            self._card_pixmaps(self.peer_cards(), scale), scale,
        )
        sides = [
            pix for pix in (host, peer)
            if pix is not None and not pix.isNull()
        ]
        return self._compose_pixmaps(sides, scale)

    def grab_view_pixmap(self, view_id, scale: float = 2.0):
        """Pixels of one real view. A peer canvas is not the host composite."""
        if (
            self._peer_host is not None
            and str(view_id) == str(self._peer_view_id)
        ):
            return self._compose_pixmaps(
                self._card_pixmaps(self.peer_cards(), scale), scale,
            )
        return self.grab_combined_pixmap(scale)

    def grab_focused_pixmap(self, scale: float = 2.0):
        """Single-chart export follows the focused view, not A+B."""
        if self._peer_host is not None and not self._comparison_focus_is_host:
            return self.grab_view_pixmap(self._peer_view_id, scale)
        if self._host_view_id:
            return self.grab_view_pixmap(self._host_view_id, scale)
        return self.grab_combined_pixmap(scale)

    def view_id_for_canvas(self, canvas) -> str:
        if canvas is None:
            return ""
        for card in self.peer_cards():
            if getattr(card, "canvas", None) is canvas:
                return str(self._peer_view_id)
        for card in self._cards:
            if getattr(card, "canvas", None) is canvas:
                if self._host_view_id:
                    return str(self._host_view_id)
                break
        if not self.manager.views:
            return ""
        try:
            state = self.manager.get(self.manager.active)
        except (IndexError, TypeError):
            return ""
        return str(getattr(state, "view_id", "") or "")

    def export_target(self, combined: bool = False) -> dict:
        """Identity of an export. Combined names both views; single names one pane."""
        if combined and self._peer_host is not None:
            host_name = self._view_label(self._host_view_id)
            peer_name = self._view_label(self._peer_view_id)
            return {
                "kind": "comparison",
                "view_ids": [str(self._host_view_id), str(self._peer_view_id)],
                "label": f"{host_name} + {peer_name}",
            }
        view_id = str(self._host_view_id or "")
        pane = self.focused_index()
        if self._peer_host is not None and not self._comparison_focus_is_host:
            view_id = str(self._peer_view_id)
            pane = int(getattr(self._peer_host, "_focused", 0))
        elif not view_id:
            view_id = self.view_id_for_canvas(None) or self._active_view_id()
        return {
            "kind": "pane",
            "view_id": view_id,
            "pane_index": int(pane),
        }

    def _comparison_export_filename(self) -> str:
        if self._peer_host is None:
            return ""
        label = str(self.export_target(combined=True).get("label") or "")
        cleaned = label.replace("/", " ").replace("\\", " ").strip()
        if not cleaned:
            return ""
        return f"{cleaned}.png"

    def _view_label(self, view_id) -> str:
        target = str(view_id or "")
        for state in self.manager.views:
            if str(getattr(state, "view_id", "")) == target:
                return str(getattr(state, "name", "") or target)
        return target

    def _active_view_id(self) -> str:
        if not self.manager.views:
            return ""
        try:
            state = self.manager.get(self.manager.active)
        except (IndexError, TypeError):
            return ""
        return str(getattr(state, "view_id", "") or "")

    def _card_pixmaps(self, cards, scale: float):
        """Grab one region's cards. Null grabs are skipped."""
        stack = self.parent()
        controller = getattr(stack, "_pinned_cursors", None)
        flush = getattr(controller, "flush_layout", None)
        if callable(flush):
            flush()
        compositor = getattr(self, "_pin_chrome_compositor", None)
        pixes = []
        for card in cards:
            canvas = getattr(card, "canvas", None)
            if canvas is None:
                continue
            grab = getattr(canvas, "grab_pixmap", None)
            if not callable(grab):
                continue
            pix = grab(scale=scale)
            if pix is None or pix.isNull():
                continue
            pix = pixmap_as_device_pixels(pix)
            if pix is None or pix.isNull():
                continue
            if callable(compositor):
                try:
                    compositor(pix, canvas)
                except RuntimeError:
                    logger.warning(
                        "pin chrome compositor failed for canvas %r",
                        canvas,
                        exc_info=True,
                    )
            pixes.append(pix)
        return pixes

    def _compose_pixmaps(self, pixes, scale: float):
        """Lay pixmaps left to right. One pixmap is returned unchanged."""
        from PyQt5.QtGui import QPainter, QPixmap

        if not pixes:
            return None
        if len(pixes) == 1:
            return pixes[0]
        gap = max(1, int(round(4 * scale)))
        width = sum(pix.width() for pix in pixes) + gap * (len(pixes) - 1)
        height = max(pix.height() for pix in pixes)
        out = QPixmap(width, height)
        out.fill(Qt.white)
        painter = QPainter(out)
        x = 0
        for pix in pixes:
            painter.drawPixmap(x, 0, pix)
            x += pix.width() + gap
        painter.end()
        return out

    def enter_split(self) -> None:
        self.ensure_ready()
        if len(self._cards) >= 2:
            return
        card = self._make_card()
        self._cards.append(card)
        detach_toolbar = getattr(card, 'detach_toolbar', None)
        if self._toolbar is not None and callable(detach_toolbar):
            hidden_toolbar = detach_toolbar(card)
            hidden_toolbar.hide()
        self._split.addWidget(card)
        total = max(2, self._split.width())
        left = max(1, total // 2)
        self._split.setSizes([left, max(1, total - left)])
        self._configure_shared_toolbar()
        self._inherit_shared_mouse_mode(card)
        self.set_linked(self._linked)
        self.set_levels_locked(self._levels_locked)
        self._apply_focus_style()
        self._refresh_compare_buttons()
        self._sync_card_hint_bars()
        self.tabbar.refresh_split_controls()
        self._schedule_heatmap_layout_sync()
        canvas = getattr(card, "canvas", None)
        if canvas is not None:
            self.pane_added.emit(canvas)

    def _configure_shared_toolbar(self) -> None:
        toolbar = getattr(self, '_toolbar', None)
        if toolbar is None:
            return
        toolbar._action_delegate_provider = as_weak_callable(
            self._focused_nav_delegate
        )
        toolbar._peer_toolbars_provider = as_weak_callable(self._peers_for_primary)
        toolbar._save_pixmap_provider = as_weak_callable(
            self.grab_export_pixmap
        )
        toolbar._export_name_provider = as_weak_callable(
            self._comparison_export_filename
        )
        self._connect_toolbar_highlight(toolbar)
        if self._cards:
            self._cards[0]._annotation_target_provider = as_weak_callable(
                self._focused_annotation_card
            )
            self._cards[0]._annotation_view_token_provider = as_weak_callable(
                self._annotation_view_token
            )
        if len(self._cards) > 1:
            secondary = self._cards[1].toolbar
            secondary._peer_toolbars_provider = as_weak_callable(
                self._peers_for_secondary
            )
            self._connect_toolbar_highlight(secondary)
        if self._cards:
            self._cards[0]._options_canvas_provider = as_weak_callable(
                self.focused_canvas
            )
            set_cursor_target = getattr(
                self._cards[0], 'set_frequency_cursor_target_provider', None)
            if callable(set_cursor_target):
                # The primary card's toolbar is detached before ``_focused``
                # is initialized in __init__; default to pane 0 during that
                # construction-only interval. Hold the provider weakly so the
                # card cannot keep the section page alive past teardown.
                set_cursor_target(as_weak_callable(self._frequency_cursor_card))
                sync_cursor = getattr(
                    self._cards[0], 'sync_frequency_cursor_control', None)
                if callable(sync_cursor):
                    sync_cursor()

    def _frequency_cursor_card(self):
        if self._peer_host is not None and not self._comparison_focus_is_host:
            card = self._peer_host.card_at(getattr(self._peer_host, "_focused", 0))
            if card is not None:
                return card
        return self._cards[getattr(self, '_focused', 0)]

    def _focused_nav_delegate(self):
        if self._focused <= 0 or self._focused >= len(self._cards):
            return None
        return getattr(self._cards[self._focused], 'toolbar', None)

    def _focused_annotation_card(self):
        if not self._cards:
            return None
        idx = getattr(self, "_focused", 0)
        idx = max(0, min(int(idx), len(self._cards) - 1))
        return self._cards[idx]

    def _annotation_view_token(self):
        if self._peer_host is not None and not self._comparison_focus_is_host:
            return ("analysis", self.section, self._peer_view_id)
        view_id = self.manager.active
        try:
            view_id = self.manager.get(self.manager.active).view_id
        except (AttributeError, IndexError, TypeError):
            pass
        if self._peer_host is None:
            return ("analysis", self.section, self.manager.active)
        return ("analysis", self.section, view_id)

    def _visible_peer_toolbars(self, card):
        """Visible same-page toolbars other than ``card``.

        Hidden sections and a pane that has left split are not targets.
        The detached secondary toolbar widget stays hidden on purpose; the
        card's visibility is what decides membership.
        """
        if card is None or len(self._cards) < 2:
            return []
        peers = []
        for other in self._cards:
            if other is card:
                continue
            try:
                visible = other.isVisible()
            except RuntimeError:
                continue
            if not visible:
                continue
            toolbar = getattr(other, "toolbar", None)
            if toolbar is not None:
                peers.append(toolbar)
        return peers

    def _peers_for_primary(self):
        if not self._cards:
            return []
        return self._visible_peer_toolbars(self._cards[0])

    def _peers_for_secondary(self):
        if len(self._cards) < 2:
            return []
        return self._visible_peer_toolbars(self._cards[1])

    def _peer_toolbars(self):
        return self._peers_for_primary()

    def _inherit_shared_mouse_mode(self, card):
        shared = getattr(self, "_toolbar", None)
        toolbar = getattr(card, "toolbar", None)
        if shared is None or toolbar is None or toolbar is shared:
            return
        if toolbar.mode != shared.mode:
            toolbar.set_mouse_mode(shared.mode)

    def _connect_toolbar_highlight(self, toolbar):
        if toolbar is None or getattr(toolbar, "_section_highlight_connected", False):
            return
        toolbar.mouse_mode_changed.connect(self._sync_shared_nav_highlight)
        toolbar._section_highlight_connected = True

    def _sync_shared_nav_highlight(self, *_args):
        toolbar = getattr(self, "_toolbar", None)
        if toolbar is None or not self._cards:
            return
        focused = self._focused_annotation_card()
        source = getattr(focused, "toolbar", None)
        toolbar.paint_nav_highlight(getattr(source, "mode", ""))

    def _sync_shared_annotation_button(self):
        if not self._cards:
            return
        sync = getattr(self._cards[0], "sync_annotation_button", None)
        if callable(sync):
            sync()

    def focused_canvas(self):
        self.ensure_ready()
        if self._peer_host is not None and not self._comparison_focus_is_host:
            canvas = self._peer_host.canvas_at(self._peer_host._focused)
            if canvas is not None:
                return canvas
        return self.pane_canvas(self.focused_index())

    def exit_split(self) -> None:
        if len(self._cards) < 2:
            return
        canvas = getattr(self._cards[1], "canvas", None)
        if canvas is not None:
            self.pane_removing.emit(canvas)
        self.set_linked(False)
        # Tear down level-lock signal wiring before the pane is destroyed.
        self._disconnect_level_lock_handlers(self._heatmap_canvases())
        card = self._cards.pop(1)
        secondary_toolbar = getattr(card, "toolbar", None)
        if secondary_toolbar is not None and getattr(
            secondary_toolbar, "_section_highlight_connected", False
        ):
            try:
                secondary_toolbar.mouse_mode_changed.disconnect(
                    self._sync_shared_nav_highlight
                )
            except TypeError:
                pass
            secondary_toolbar._section_highlight_connected = False
        if secondary_toolbar is not None:
            secondary_toolbar._peer_toolbars_provider = None
            secondary_toolbar.discard_pending_history()
        card.removeEventFilter(self)
        card.setParent(None)
        card.deleteLater()
        self.set_focused_index(0)
        self._previous_focused = 0
        self._apply_focus_style()
        self._refresh_compare_buttons()
        self._sync_card_hint_bars()
        self.tabbar.refresh_split_controls()
        self._schedule_heatmap_layout_sync()

    def _sync_card_hint_bars(self) -> None:
        """Analysis compare panes do not show per-card shortcut hint bands."""
        show = len(self._cards) == 1
        for card in self._cards:
            bar = getattr(card, '_hint_bar', None)
            if bar is not None:
                bar.setVisible(show)

    # -- focus ----------------------------------------------------------
    def focused_index(self) -> int:
        return self._focused

    def previous_focused_index(self) -> int:
        return self._previous_focused

    def set_focused_index(self, idx: int) -> None:
        idx = max(0, min(idx, len(self._cards) - 1))
        if idx == self._focused:
            self._apply_focus_style()
            self._sync_frequency_cursor_control()
            self._sync_shared_nav_highlight()
            self._sync_shared_annotation_button()
            return
        self._previous_focused = self._focused
        self._focused = idx
        self._apply_focus_style()
        self._sync_frequency_cursor_control()
        self._sync_shared_nav_highlight()
        self._sync_shared_annotation_button()
        if not self._suppress_focus_emit:
            self.focus_changed.emit(idx)

    def _sync_frequency_cursor_control(self) -> None:
        if not self._cards:
            return
        sync = getattr(self._cards[0], 'sync_frequency_cursor_control', None)
        if callable(sync):
            sync()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and self._peer_host is not None:
            idx = self._index_for_object(obj)
            if idx is not None:
                # A press on the host while the peer is focused must not emit
                # focus_changed first: that would capture the peer's sources
                # into the host pane. The comparison handler captures first.
                if self._comparison_focus_is_host:
                    self.set_focused_index(idx)
                else:
                    self.comparison_focus_requested.emit(self._host_view_id, idx)
                return super().eventFilter(obj, event)
        if event.type() == QEvent.MouseButtonPress and len(self._cards) > 1:
            idx = self._index_for_object(obj)
            if idx is not None:
                self.set_focused_index(idx)
        return super().eventFilter(obj, event)

    def _index_for_object(self, obj):
        """Map a filtered object (card, its canvas, or canvas viewport) back to
        its pane index, mirroring chart_stack._card_for_object. The
        isAncestorOf fallback catches any deeper child that bubbled a press."""
        return _pane_index_for_object(self._cards, obj)

    def _active_view_focus_accent(self) -> str:
        try:
            accent = self.manager.get(self.manager.active).tab_color
        except Exception:
            accent = None
        if not accent or not QColor(accent).isValid():
            return _FOCUS_ACCENT
        return accent

    def refresh_focus_style(self, *_args) -> None:
        self._apply_focus_style()

    def _apply_focus_style(self) -> None:
        focus_accent = self._active_view_focus_accent()
        comparison = self._peer_host is not None
        host_focused = self._comparison_focus_is_host or not comparison
        for i, card in enumerate(self._cards):
            if comparison:
                focused = host_focused and i == self._focused
            else:
                focused = i == self._focused and len(self._cards) > 1
            marker = getattr(card, 'set_focus_marker', None)
            if callable(marker):
                marker(focus_accent if focused else None)
            # Drop the legacy per-card focus border so the pyqtgraph data area
            # does not get inset by 1px and the shared #chartCard QSS wins.
            if card.styleSheet():
                card.setStyleSheet("")

    # -- compare: linked zoom (spec §6.1) --------------------------------
    def set_linked(self, linked: bool) -> None:
        self._linked = bool(linked)
        if len(self._cards) < 2:
            return
        c0 = self._cards[0].canvas
        c1 = self._cards[1].canvas
        vb0 = _primary_vb(c0)
        vb1 = _primary_vb(c1)
        if vb0 is None or vb1 is None:
            return
        if self._linked:
            vb1.setXLink(vb0)
            # Heatmaps compare on BOTH axes (spec §6.1); line sections X only.
            # _img is the heatmap's ImageItem — absent on PgLineCanvas.
            if hasattr(c0, '_img') and hasattr(c1, '_img'):
                vb1.setYLink(vb0)
        else:
            vb1.setXLink(None)
            vb1.setYLink(None)
        self.link_toggled.emit(self._linked)

    def is_linked(self) -> bool:
        return self._linked

    # -- compare: locked color levels (spec §6.1) -----------------------
    def _heatmap_canvases(self):
        """Canvases that carry an ImageItem + colorbar (heatmap sections).

        Line sections (FFT) have no ``_img``/``_cbar`` — level locking is a
        no-op there and the toggle button stays hidden.
        """
        out = []
        for card in self._cards:
            canvas = getattr(card, 'canvas', None)
            if canvas is not None and hasattr(canvas, '_img') and \
                    hasattr(canvas, '_cbar'):
                out.append(canvas)
        return out

    def _schedule_heatmap_layout_sync(self) -> None:
        if self._layout_sync_pending:
            return
        self._layout_sync_pending = True
        QTimer.singleShot(0, self.sync_heatmap_layouts)

    def sync_heatmap_layouts(self) -> None:
        """Align plot-area geometry across split analysis panes.

        QSplitter only equalizes the outer cards. Each pyqtgraph PlotItem
        still auto-sizes its title and axes independently, so split panes can
        drift by several pixels. Pin pane-local reserves to shared maxima.
        """
        self._layout_sync_pending = False
        canvases = [
            c for c in self._heatmap_canvases()
            if hasattr(c, 'prepare_split_layout_alignment')
            and hasattr(c, 'heatmap_layout_metrics')
            and hasattr(c, 'apply_split_layout_alignment')
            and hasattr(c, 'recommended_split_title_width')
        ]
        if len(canvases) < 2:
            for c in canvases:
                try:
                    c.reset_split_layout_alignment()
                except Exception:
                    pass
        else:
            title_width = min(c.recommended_split_title_width() for c in canvases)
            for c in canvases:
                c.prepare_split_layout_alignment(title_width)

            metrics = [c.heatmap_layout_metrics() for c in canvases]
            left_width = max(m.get('left_axis_width', 0.0) for m in metrics)
            colorbar_width = max(m.get('colorbar_axis_width', 0.0) for m in metrics)
            main_bottom_height = max(
                m.get('main_bottom_axis_height', 0.0) for m in metrics)
            slice_bottom_height = max(
                m.get('slice_bottom_axis_height', 0.0) for m in metrics)

            for c in canvases:
                c.apply_split_layout_alignment(
                    left_axis_width=left_width,
                    main_bottom_axis_height=main_bottom_height,
                    slice_bottom_axis_height=slice_bottom_height,
                    colorbar_axis_width=colorbar_width,
                )

            metrics = [c.heatmap_layout_metrics() for c in canvases]
            slice_right_reserve = max(
                m.get('slice_right_reserve', 0.0) for m in metrics)
            for c in canvases:
                c.apply_split_layout_alignment(
                    left_axis_width=left_width,
                    main_bottom_axis_height=main_bottom_height,
                    slice_bottom_axis_height=slice_bottom_height,
                    slice_right_reserve=slice_right_reserve,
                    colorbar_axis_width=colorbar_width,
                )

        line_canvases = [
            c for c in (
                getattr(card, 'canvas', None) for card in self._cards
            )
            if hasattr(c, 'prepare_split_layout_alignment')
            and hasattr(c, 'line_layout_metrics')
            and hasattr(c, 'apply_split_layout_alignment')
            and hasattr(c, 'recommended_split_title_width')
        ]
        if len(line_canvases) < 2:
            for c in line_canvases:
                try:
                    c.reset_split_layout_alignment()
                except Exception:
                    pass
        else:
            title_width = min(c.recommended_split_title_width() for c in line_canvases)
            for c in line_canvases:
                c.prepare_split_layout_alignment(title_width)

            metrics = [c.line_layout_metrics() for c in line_canvases]
            left_width = max(m.get('left_axis_width', 0.0) for m in metrics)
            amp_bottom_height = max(
                m.get('amp_bottom_axis_height', 0.0) for m in metrics)
            time_bottom_height = max(
                m.get('time_bottom_axis_height', 0.0) for m in metrics)

            # Right reserves are intentionally NOT cross-synced for line canvases.
            # The time-preview overlay Y-axes (one per extra source) are a per-pane
            # feature that already occupy their own layout columns. Pushing the
            # global-max reserve (spacer + overlay) onto every pane's right SPACER
            # double-counts the overlay width — it shrank both panes' plot areas and
            # inset an overlay-free pane by the other pane's overlay reserve. Each
            # pane keeps the thin frame set by prepare() and is inset only by its
            # OWN overlay axes; the FFT spectrum row (no overlay) stays aligned via
            # the shared left-axis width and bottom-axis heights below.
            for c in line_canvases:
                c.apply_split_layout_alignment(
                    left_axis_width=left_width,
                    amp_bottom_axis_height=amp_bottom_height,
                    time_bottom_axis_height=time_bottom_height,
                )

        frf_canvases = [
            c for c in (getattr(card, 'canvas', None) for card in self._cards)
            if hasattr(c, 'prepare_frf_layout_alignment')
            and hasattr(c, 'frf_layout_metrics')
            and hasattr(c, 'apply_frf_layout_alignment')
        ]
        if len(frf_canvases) < 2:
            for c in frf_canvases:
                c.reset_frf_layout_alignment()
        else:
            for c in frf_canvases:
                c.prepare_frf_layout_alignment()
            metrics = [c.frf_layout_metrics() for c in frf_canvases]
            left_width = max(m.get('left_axis_width', 0.0) for m in metrics)
            for c in frf_canvases:
                c.apply_frf_layout_alignment(left_axis_width=left_width)

    def _is_heatmap_section(self) -> bool:
        if not self._cards:
            # Deferred: section identity is enough; do not build a chart.
            return self.section in {"fft_time", "order"}
        canvas = getattr(self._cards[0], 'canvas', None)
        return canvas is not None and hasattr(canvas, '_img')

    def set_levels_locked(self, locked: bool) -> None:
        """Lock/unlock a shared color scale across the two heatmap panes.

        On lock: compute the COMBINED min/max across both panes'
        ``_matrix_disp`` and push it to both ``_img`` + ``_cbar`` (wrapped in
        ``blockSignals`` so the programmatic ``setLevels`` cannot masquerade
        as a user drag — M2: ``setLevels`` is silent, but block defensively),
        then subscribe each canvas's ``levels_changed`` (emitted only on a
        real colorbar drag) to ``_on_locked_levels_changed`` so a drag on one
        pane propagates to the other. On unlock: disconnect.

        pg signals expose no "is this slot connected?" query, so re-locking
        disconnects first (guarded by ``try/except TypeError`` for the
        not-connected case) before reconnecting — otherwise repeated locks
        multi-connect and a single drag would fire propagation N times.
        """
        self._levels_locked = bool(locked)
        canvases = self._heatmap_canvases()
        # Always disconnect first (idempotent re-lock + clean unlock).
        self._disconnect_level_lock_handlers(canvases)
        if not self._levels_locked or len(canvases) < 2:
            self._refresh_compare_buttons()
            return
        if not self._color_projection_depth:
            lo, hi = self._combined_levels(canvases)
            if lo is not None:
                for c in canvases:
                    self._set_canvas_levels(c, lo, hi)
        for c in canvases:
            c.levels_changed.connect(self._on_locked_levels_changed)
            policy = getattr(c, "color_policy_committed", None)
            if policy is not None:
                policy.connect(self._on_locked_color_policy)
        self._refresh_compare_buttons()

    def is_levels_locked(self) -> bool:
        return self._levels_locked

    def _disconnect_level_lock_handlers(self, canvases) -> None:
        for c in canvases:
            try:
                c.levels_changed.disconnect(self._on_locked_levels_changed)
            except TypeError:
                pass
            policy = getattr(c, "color_policy_committed", None)
            if policy is None:
                continue
            try:
                policy.disconnect(self._on_locked_color_policy)
            except TypeError:
                pass

    @contextmanager
    def color_projection_batch(self):
        """Defer lock unions while a render transaction prepares its panes.

        The transaction owner settles final levels explicitly after all panes
        have been painted; unwinding this guard never publishes an interim union.
        """
        self._color_projection_depth += 1
        try:
            yield
        finally:
            self._color_projection_depth -= 1

    def _on_canvas_levels_rebased(self) -> None:
        if self._color_projection_depth or not self._levels_locked:
            return
        canvases = self._heatmap_canvases()
        if len(canvases) < 2:
            return
        if not all(getattr(c, 'has_result', lambda: False)() for c in canvases):
            return
        self.set_levels_locked(True)

    def _on_colorbar_restored(self, lo: float, hi: float) -> None:
        """Double-click restore: copy the restored window onto locked siblings.

        Distinct from ``_on_canvas_levels_rebased``, which re-locks using
        the combined auto range of both matrices and would undo the restore.
        """
        if not self._levels_locked:
            return
        for canvas in self._heatmap_canvases():
            self._set_canvas_levels(canvas, float(lo), float(hi), auto=False)

    @staticmethod
    def _combined_levels(canvases):
        """Merged (min, max) across every pane's display-space matrix.

        Falls back to each ``_img``'s current levels when a pane has no
        matrix yet (e.g. one pane computed, the other still empty)."""
        los, his = [], []
        for c in canvases:
            lv = c._img.getLevels()
            if lv is not None and lv[0] is not None:
                lo = float(lv[0])
                hi = float(lv[1])
                if np.isfinite(lo) and np.isfinite(hi) and hi > lo:
                    los.append(lo)
                    his.append(hi)
                    continue
            m = getattr(c, '_matrix_disp', None)
            if m is not None and np.size(m):
                lo = float(np.nanmin(m))
                hi = float(np.nanmax(m))
                if np.isfinite(lo) and np.isfinite(hi) and hi > lo:
                    los.append(lo)
                    his.append(hi)
        if not los:
            return None, None
        return min(los), max(his)

    @staticmethod
    def _set_canvas_levels(canvas, lo, hi, *, auto=None) -> None:
        """Project image, colorbar and slice without publishing a user edit."""
        if auto is None:
            auto = canvas._z_color_auto
        canvas.project_color_levels(bool(auto), float(lo), float(hi))

    def _on_locked_color_policy(self, z_auto, lo: float, hi: float) -> None:
        """Manual chart-options levels follow a locked sibling.

        Auto policy is not a colorbar drag, and this echo must not re-enter
        ``levels_changed`` handling.
        """
        if not self._levels_locked or self._suppress_color_policy_echo:
            return
        if bool(z_auto):
            return
        self._suppress_color_policy_echo = True
        try:
            for canvas in self._heatmap_canvases():
                self._set_canvas_levels(canvas, float(lo), float(hi), auto=False)
        finally:
            self._suppress_color_policy_echo = False

    def _on_locked_levels_changed(self, lo: float, hi: float) -> None:
        """A user dragged one pane's colorbar while locked → apply the same
        (lo, hi) to every heatmap pane. The source canvas skips ColorBarItem
        ``setLevels`` while its handle is down (``colorbar_interaction_active``)
        so ``lo_prv`` is not rewritten mid-drag; ImageItem on the source is
        already owned by ColorBarItem._update_items."""
        if not self._levels_locked:
            return
        for c in self._heatmap_canvases():
            self._set_canvas_levels(c, float(lo), float(hi), auto=False)

    # -- compare toggle buttons -----------------------------------------
    def _make_toggle(self, text, tooltip):
        btn = self._make_command(text, tooltip)
        btn.setCheckable(True)
        return btn

    def _make_command(self, text, tooltip):
        btn = QToolButton(self._compare_row)
        btn.setObjectName("analysisCompareToggle")
        btn.setText(text)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setFixedHeight(22)
        return btn

    def _on_link_button_toggled(self, on: bool) -> None:
        if self._suppress_compare_edge:
            return
        region = self._focused_comparison_region()
        if region is None:
            self.set_linked(on)
        else:
            region.set_linked(on)
        self.compare_toggled.emit('x_linked', bool(on))

    def _on_lock_button_toggled(self, on: bool) -> None:
        if self._suppress_compare_edge:
            return
        region = self._focused_comparison_region()
        if region is None:
            self.set_levels_locked(on)
        else:
            region.set_levels_locked(on)
        self.compare_toggled.emit('levels_locked', bool(on))

    def _on_view_link_toggled(self, on: bool) -> None:
        if self._suppress_compare_edge:
            return
        self.comparison_display_toggled.emit('axis_linked', bool(on))

    def _on_view_levels_toggled(self, on: bool) -> None:
        if self._suppress_compare_edge:
            return
        self.comparison_display_toggled.emit('levels_locked', bool(on))

    def _on_expand_clicked(self) -> None:
        if self._comparison_expanded:
            self.return_to_comparison_layout()
        else:
            self.expand_focused_comparison()

    def sync_compare_buttons(self, *, x_linked, levels_locked) -> None:
        """State → buttons (NO edge emit).

        Called by MainWindow on view switch / init to seed the toggle states
        from ``state.compare`` without firing ``compare_toggled`` (which would
        write the value straight back, a no-op loop). Guarded by
        ``_suppress_compare_edge`` so the resulting ``toggled`` signals are
        swallowed by the handlers above."""
        self._suppress_compare_edge = True
        try:
            self.btn_link.setChecked(bool(x_linked))
            self.btn_lock_levels.setChecked(bool(levels_locked))
        finally:
            self._suppress_compare_edge = False
        self._refresh_compare_buttons()

    def sync_comparison_display_buttons(self, *, axis_linked, levels_locked) -> None:
        """Relation flags → cross-view buttons, without writing state.compare."""
        self._suppress_compare_edge = True
        try:
            self.btn_view_link.setChecked(bool(axis_linked))
            self.btn_view_levels.setChecked(bool(levels_locked))
        finally:
            self._suppress_compare_edge = False
        self._refresh_compare_buttons()

    def _refresh_compare_buttons(self) -> None:
        """Visibility/enabled state: compare toggles only matter while split.
        锁定色阶 is heatmap-only (line sections have no colorbar).
        Cross-view controls stay hidden until a peer region is mounted."""
        if self._peer_host is not None and not self._comparison_focus_is_host:
            split = self._peer_host.pane_count() > 1
        else:
            split = len(self._cards) > 1
        self.btn_link.setVisible(split)
        self.btn_lock_levels.setVisible(split and self._is_heatmap_section())
        open_pair = self._peer_host is not None
        self.btn_view_link.setVisible(open_pair)
        self.btn_view_levels.setVisible(
            open_pair and self.section in {"fft_time", "order"}
        )
        self.btn_view_expand.setVisible(open_pair)
        if open_pair:
            self.btn_view_expand.setText(
                "返回并排" if self._comparison_expanded else "展开焦点"
            )
        fitter = getattr(self, '_ultraview_rail_fitter', None)
        if fitter is not None:
            fitter.schedule()

    # -- cross-view comparison regions ----------------------------------
    def show_comparison_peer(self, host_view_id, peer_view_id, peer_pane_count) -> None:
        """Mount a second view region beside this page's panes.

        The existing splitter becomes the host region. One tab bar stays on
        the page. ``peer_pane_count`` is 1 or 2, never a third page.
        """
        self.ensure_ready()
        self._host_view_id = str(host_view_id)
        self._peer_view_id = str(peer_view_id)
        if self._view_split is None:
            lay = self.layout()
            index = lay.indexOf(self._split)
            self._view_split = QSplitter(Qt.Horizontal, self)
            self._view_split.setObjectName("analysisComparisonSplit")
            self._view_split.setChildrenCollapsible(False)
            lay.insertWidget(max(index, 0), self._view_split, 1)
            self._view_split.addWidget(self._split)
            self._peer_host = AnalysisPaneHost(self, self._view_split)
            self._peer_host.setObjectName("analysisComparisonPeer")
            self._peer_host.pressed.connect(self._on_peer_pane_pressed)
            self._view_split.addWidget(self._peer_host)
        self._peer_host.set_pane_count(peer_pane_count)
        self._comparison_expanded = False
        self._apply_comparison_minimums()
        self._apply_comparison_sizes()
        self._update_comparison_orientation()
        self._refresh_compare_buttons()

    def hide_comparison_peer(self) -> None:
        """Return the page to its single-view splitter. Pins are not touched."""
        if self._view_split is None and self._peer_host is None:
            self._comparison_focus_is_host = True
            self._comparison_expanded = False
            self._split.setMinimumWidth(0)
            self._refresh_compare_buttons()
            return
        host = self._peer_host
        self._peer_host = None
        if host is not None:
            try:
                host.pressed.disconnect(self._on_peer_pane_pressed)
            except TypeError:
                pass
            host.teardown()
        view_split = self._view_split
        self._view_split = None
        if view_split is not None:
            lay = self.layout()
            index = lay.indexOf(view_split)
            self._split.setParent(self)
            lay.insertWidget(max(index, 0), self._split, 1)
            view_split.setParent(None)
            view_split.deleteLater()
        self._comparison_focus_is_host = True
        self._comparison_expanded = False
        self._host_view_id = ""
        self._peer_view_id = ""
        self._split.setMinimumWidth(0)
        self._split.setOrientation(Qt.Horizontal)
        self._apply_focus_style()
        self._refresh_compare_buttons()

    def mark_comparison_focus(self, view_id, pane_index) -> None:
        pane_index = int(pane_index)
        if str(view_id) == str(self._host_view_id):
            self._comparison_focus_is_host = True
            if self._peer_host is not None:
                self._peer_host.clear_focus_markers()
            self._suppress_focus_emit = True
            try:
                self.set_focused_index(pane_index)
            finally:
                self._suppress_focus_emit = False
        else:
            self._comparison_focus_is_host = False
            if self._peer_host is not None:
                self._peer_host.set_focused_index(pane_index)
            self._apply_focus_style()
        self._refresh_compare_buttons()
        self._sync_frequency_cursor_control()

    def card_for_view_pane(self, view_id, pane_index):
        if self._peer_host is not None and str(view_id) == str(self._peer_view_id):
            return self._peer_host.card_at(int(pane_index))
        if self._peer_host is not None and str(view_id) != str(self._host_view_id):
            return None
        if pane_index < 0 or pane_index >= len(self._cards):
            return None
        return self._cards[pane_index]

    def peer_cards(self):
        if self._peer_host is None:
            return []
        return self._peer_host.cards()

    def _focused_comparison_region(self):
        if self._peer_host is not None and not self._comparison_focus_is_host:
            return self._peer_host
        return None

    def cross_view_comparison_open(self) -> bool:
        return self._peer_host is not None

    def expand_focused_comparison(self) -> None:
        """Give the focused region the spare width. The other side stays visible."""
        if self._view_split is None or self._peer_host is None:
            return
        self._comparison_expanded = True
        self._apply_comparison_minimums()
        self._apply_comparison_sizes()
        self._refresh_compare_buttons()

    def return_to_comparison_layout(self) -> None:
        """Restore a side-by-side pair. Does not change pane counts."""
        self._comparison_expanded = False
        if self._view_split is not None:
            self._apply_comparison_sizes()
        self._refresh_compare_buttons()

    def _comparison_region_minimum(self) -> int:
        split = self._view_split
        total = 0
        if split is not None:
            total = int(split.width() or self.width() or 0)
        if total <= 2:
            return 1
        return max(1, min(_COMPARISON_REGION_MIN_PX, total // 2))

    def _comparison_sizes(self):
        split = self._view_split
        total = 2
        if split is not None:
            total = max(2, int(split.width() or self.width() or 2))
        minimum = max(1, min(_COMPARISON_REGION_MIN_PX, total // 2))
        if not self._comparison_expanded or total < minimum * 2:
            half = max(1, total // 2)
            return [half, max(1, total - half)]
        rest = minimum
        main = max(1, total - rest)
        if self._comparison_focus_is_host:
            return [main, rest]
        return [rest, main]

    def _apply_comparison_sizes(self) -> None:
        if self._view_split is None:
            return
        self._view_split.setSizes(self._comparison_sizes())

    def _apply_comparison_minimums(self) -> None:
        if self._view_split is None:
            return
        minimum = self._comparison_region_minimum()
        self._split.setMinimumWidth(minimum)
        if self._peer_host is not None:
            self._peer_host.setMinimumWidth(minimum)

    def _on_peer_pane_pressed(self, idx: int) -> None:
        self.comparison_focus_requested.emit(self._peer_view_id, int(idx))

    def _update_comparison_orientation(self) -> None:
        if self._view_split is None:
            return
        self._apply_region_orientation(self._split, len(self._cards))
        if self._peer_host is not None:
            self._peer_host.apply_width_orientation()

    def _apply_region_orientation(self, splitter, pane_count) -> None:
        if int(pane_count) < 2:
            splitter.setOrientation(Qt.Horizontal)
            return
        width = splitter.width()
        if width <= 0:
            width = splitter.parentWidget().width() if splitter.parentWidget() else 0
        vertical = 0 < width < _NARROW_PANE_REGION_PX
        orientation = Qt.Vertical if vertical else Qt.Horizontal
        if splitter.orientation() == orientation:
            return
        splitter.setOrientation(orientation)
        # Horizontal widths are not useful vertical heights. In particular a
        # newly mounted host may still have its pre-layout minimum width ratio.
        # Rebalance only on orientation changes, preserving later user drags.
        extent = max(
            splitter.height() if vertical else splitter.width(),
            splitter.minimumSizeHint().height() if vertical else splitter.minimumSizeHint().width(),
            1,
        )
        splitter.setSizes([extent] * int(pane_count))
