"""Shared screen-budget and window/popover placement.

Owners compute content (wrap, scroll, action layout) first; this module
only plans client/frame rectangles and applies size then position. All
rectangles are logical pixels. Qt screen lookup stays in the thin helpers
below so the planner can be tested with injected rectangles.

Do not multiply rectangles by DPR. Do not persist screen caps as project
state. Do not set a window maximum to the screen size — users may still
enlarge inside the work area.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PyQt5.QtCore import QEvent, QObject, QPoint, QRect, QSize, QTimer, Qt
from PyQt5.QtWidgets import QApplication, QLayout, QWidget

try:
    from PyQt5 import sip
except ImportError:  # pragma: no cover - sip is part of PyQt5
    sip = None


SCREEN_MARGIN = 8
COMPACT_WORK_WIDTH = 640
COMPACT_WORK_HEIGHT = 360
ANCHOR_GAP = 8
# Unshown decorated windows have no native frame yet. This is an estimate
# used only before Show; after Show the real frameGeometry is measured.
_ESTIMATED_TITLE_INSETS = (1, 28, 1, 1)

POSITION_CENTER = "center"
POSITION_BELOW = "below"
POSITION_ABOVE = "above"
POSITION_EMBEDDED = "embedded"


def _alive(obj) -> bool:
    if obj is None:
        return False
    if sip is not None and sip.isdeleted(obj):
        return False
    return True


def _call_int(value) -> int:
    return int(value() if callable(value) else value)


@dataclass(frozen=True)
class IntRect:
    """Qt-compatible rectangle: ``right`` / ``bottom`` are inclusive."""

    x: int
    y: int
    width: int
    height: int

    @property
    def left(self) -> int:
        return self.x

    @property
    def top(self) -> int:
        return self.y

    @property
    def right(self) -> int:
        if self.width <= 0:
            return self.x - 1
        return self.x + self.width - 1

    @property
    def bottom(self) -> int:
        if self.height <= 0:
            return self.y - 1
        return self.y + self.height - 1

    def adjusted(self, dx1: int, dy1: int, dx2: int, dy2: int) -> "IntRect":
        width = self.width - dx1 + dx2
        height = self.height - dy1 + dy2
        return IntRect(self.x + dx1, self.y + dy1, max(0, width), max(0, height))

    def contains_rect(self, other: "IntRect") -> bool:
        if other.width <= 0 or other.height <= 0:
            return True
        if self.width <= 0 or self.height <= 0:
            return False
        return (
            other.left >= self.left
            and other.top >= self.top
            and other.right <= self.right
            and other.bottom <= self.bottom
        )

    def to_qrect(self) -> QRect:
        return QRect(self.x, self.y, self.width, self.height)

    def to_size(self) -> "Size":
        return Size(self.width, self.height)


@dataclass(frozen=True)
class Size:
    width: int
    height: int

    def to_qsize(self) -> QSize:
        return QSize(self.width, self.height)


@dataclass(frozen=True)
class FrameInsets:
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0

    @property
    def horizontal(self) -> int:
        return max(0, self.left) + max(0, self.right)

    @property
    def vertical(self) -> int:
        return max(0, self.top) + max(0, self.bottom)


@dataclass(frozen=True)
class GeometryPlan:
    client: IntRect
    frame: IntRect
    compact: bool
    needs_scroll: bool
    margin_used: int
    action_vertical: bool = False


def as_rect(value) -> IntRect:
    """Accept ``IntRect``, Qt ``QRect``, or ``(x, y, w, h)``."""
    if isinstance(value, IntRect):
        return value
    if isinstance(value, QRect):
        return IntRect(value.x(), value.y(), value.width(), value.height())
    if isinstance(value, tuple) and len(value) == 4:
        return IntRect(int(value[0]), int(value[1]), int(value[2]), int(value[3]))
    if hasattr(value, "x") and hasattr(value, "width"):
        return IntRect(
            _call_int(value.x),
            _call_int(value.y),
            _call_int(value.width),
            _call_int(value.height),
        )
    raise TypeError(f"unsupported rectangle {type(value)!r}")


def as_size(value) -> Size:
    if isinstance(value, Size):
        return value
    if isinstance(value, QSize):
        return Size(value.width(), value.height())
    if isinstance(value, tuple) and len(value) == 2:
        return Size(int(value[0]), int(value[1]))
    if hasattr(value, "width") and hasattr(value, "height"):
        return Size(_call_int(value.width), _call_int(value.height))
    raise TypeError(f"unsupported size {type(value)!r}")


def as_point(value) -> QPoint:
    if isinstance(value, QPoint):
        return value
    if isinstance(value, tuple) and len(value) == 2:
        return QPoint(int(value[0]), int(value[1]))
    if hasattr(value, "x") and hasattr(value, "y"):
        return QPoint(_call_int(value.x), _call_int(value.y))
    raise TypeError(f"unsupported point {type(value)!r}")


def effective_margin(
    available: IntRect,
    frame: FrameInsets,
    requested: int = SCREEN_MARGIN,
) -> int:
    """Shrink the safety margin rather than emit a negative client budget."""
    requested = max(0, int(requested))
    max_w = max(0, available.width - frame.horizontal) // 2
    max_h = max(0, available.height - frame.vertical) // 2
    return min(requested, max_w, max_h)


def client_budget(
    available: IntRect,
    frame: FrameInsets,
    margin: int = SCREEN_MARGIN,
) -> Size:
    used = effective_margin(available, frame, margin)
    width = available.width - 2 * used - frame.horizontal
    height = available.height - 2 * used - frame.vertical
    return Size(max(0, width), max(0, height))


def constrain_client_size(
    preferred: Size,
    budget: Size,
    *,
    content_minimum: Size | None = None,
) -> tuple[Size, bool, bool]:
    """Cap preferred size to the budget. Content minimum cannot break it.

    ``needs_scroll`` is true when the caller's content minimum exceeds the
    fitted client. ``compact`` is true when the fitted size is below the
    preferred size or the budget itself is a compact work area.
    """
    width = max(0, min(max(0, preferred.width), budget.width))
    height = max(0, min(max(0, preferred.height), budget.height))
    needs_scroll = False
    if content_minimum is not None:
        min_w = max(0, content_minimum.width)
        min_h = max(0, content_minimum.height)
        needs_scroll = min_w > width or min_h > height
        # Prefer the content minimum only while it still fits the budget.
        width = max(width, min(min_w, budget.width))
        height = max(height, min(min_h, budget.height))
        width = min(width, budget.width)
        height = min(height, budget.height)
    compact = (
        width < preferred.width
        or height < preferred.height
        or budget.width <= COMPACT_WORK_WIDTH
        or budget.height <= COMPACT_WORK_HEIGHT
        or needs_scroll
    )
    return Size(max(0, width), max(0, height)), compact, needs_scroll


def _safe_area(available: IntRect, margin: int) -> IntRect:
    return available.adjusted(margin, margin, -margin, -margin)


def _clamp_frame(frame: IntRect, safe: IntRect) -> IntRect:
    if safe.width <= 0 or safe.height <= 0:
        return IntRect(safe.x, safe.y, 0, 0)
    width = min(max(0, frame.width), safe.width)
    height = min(max(0, frame.height), safe.height)
    x = min(max(frame.x, safe.left), safe.right - width + 1)
    y = min(max(frame.y, safe.top), safe.bottom - height + 1)
    return IntRect(x, y, width, height)


def _center_frame(frame_size: Size, host: IntRect | None, safe: IntRect) -> IntRect:
    ref = host if host is not None and host.width > 0 and host.height > 0 else safe
    x = ref.x + (ref.width - frame_size.width) // 2
    y = ref.y + (ref.height - frame_size.height) // 2
    return _clamp_frame(IntRect(x, y, frame_size.width, frame_size.height), safe)


def _popover_frame(
    frame_size: Size,
    anchor: IntRect,
    safe: IntRect,
    *,
    gap: int,
    prefer: str,
) -> IntRect:
    below_y = anchor.bottom + 1 + gap
    above_y = anchor.top - gap - frame_size.height
    x = anchor.right - frame_size.width + 1
    first_y = below_y if prefer == POSITION_BELOW else above_y
    second_y = above_y if prefer == POSITION_BELOW else below_y
    candidate = IntRect(x, first_y, frame_size.width, frame_size.height)
    if safe.contains_rect(candidate):
        return candidate
    flipped = IntRect(x, second_y, frame_size.width, frame_size.height)
    if safe.contains_rect(flipped):
        return flipped
    return _clamp_frame(candidate, safe)


def plan_geometry(
    available,
    preferred,
    *,
    frame: FrameInsets | None = None,
    margin: int = SCREEN_MARGIN,
    content_minimum=None,
    host=None,
    anchor=None,
    position: str = POSITION_CENTER,
    gap: int = ANCHOR_GAP,
    prefer_below: bool = True,
) -> GeometryPlan:
    """Plan client and frame rectangles for one window or popover.

    ``position`` is ``center`` (ordinary window), ``below`` / ``above``
    (anchored popover), or ``embedded`` (host-local flyout, no screen rule).
    """
    frame = frame or FrameInsets()
    if position == POSITION_EMBEDDED:
        host_rect = as_rect(available if host is None else host)
        used = max(0, min(int(margin), host_rect.width // 2, host_rect.height // 2))
        budget = Size(
            max(0, host_rect.width - 2 * used),
            max(0, host_rect.height - 2 * used),
        )
        client_size, compact, needs_scroll = constrain_client_size(
            as_size(preferred),
            budget,
            content_minimum=None if content_minimum is None else as_size(content_minimum),
        )
        safe = _safe_area(host_rect, used)
        placed = _center_frame(client_size, host_rect, safe)
        return GeometryPlan(
            client=placed,
            frame=placed,
            compact=compact,
            needs_scroll=needs_scroll,
            margin_used=used,
        )

    work = as_rect(available)
    used = effective_margin(work, frame, margin)
    budget = client_budget(work, frame, used)
    pref = as_size(preferred)
    content = None if content_minimum is None else as_size(content_minimum)
    client_size, compact, needs_scroll = constrain_client_size(
        pref, budget, content_minimum=content,
    )
    frame_size = Size(
        client_size.width + frame.horizontal,
        client_size.height + frame.vertical,
    )
    safe = _safe_area(work, used)
    host_rect = None if host is None else as_rect(host)
    if position in (POSITION_BELOW, POSITION_ABOVE) or anchor is not None:
        if anchor is None:
            raise ValueError("anchored placement requires an anchor rectangle")
        prefer = POSITION_BELOW if prefer_below and position != POSITION_ABOVE else POSITION_ABOVE
        if position == POSITION_ABOVE:
            prefer = POSITION_ABOVE
        placed_frame = _popover_frame(
            frame_size, as_rect(anchor), safe, gap=max(0, int(gap)), prefer=prefer,
        )
    else:
        placed_frame = _center_frame(frame_size, host_rect, safe)
    client = IntRect(
        placed_frame.x + frame.left,
        placed_frame.y + frame.top,
        max(0, placed_frame.width - frame.horizontal),
        max(0, placed_frame.height - frame.vertical),
    )
    action_vertical = compact and client_size.width < pref.width
    return GeometryPlan(
        client=client,
        frame=placed_frame,
        compact=compact,
        needs_scroll=needs_scroll,
        margin_used=used,
        action_vertical=action_vertical,
    )


def resolve_target_screen(
    *,
    anchor_global=None,
    widget: QWidget | None = None,
    parent: QWidget | None = None,
):
    """Pick the QScreen for a window or popover. Last resort is primary."""
    app = QApplication.instance()
    if app is None:
        return None

    def _screen_at(point):
        if point is None:
            return None
        try:
            return QApplication.screenAt(as_point(point))
        except RuntimeError:
            return None

    if anchor_global is not None:
        point = anchor_global
        if isinstance(point, QRect) or isinstance(point, IntRect):
            rect = as_rect(point)
            point = QPoint(rect.x + rect.width // 2, rect.y + rect.height // 2)
        elif hasattr(point, "center") and callable(point.center):
            point = point.center()
        screen = _screen_at(point)
        if screen is not None:
            return screen

    target = widget
    if target is not None and _alive(target):
        try:
            if target.isVisible() and target.isWindow():
                handle = target.windowHandle()
                if handle is not None and handle.screen() is not None:
                    return handle.screen()
                screen = _screen_at(target.frameGeometry().center())
                if screen is not None:
                    return screen
        except RuntimeError:
            pass
        if parent is None:
            parent = target.parentWidget()

    if parent is not None and _alive(parent):
        try:
            top = parent.window()
            if top is not None and _alive(top):
                handle = top.windowHandle()
                if handle is not None and handle.screen() is not None:
                    return handle.screen()
                screen = _screen_at(top.frameGeometry().center())
                if screen is not None:
                    return screen
        except RuntimeError:
            pass

    return app.primaryScreen()


def resolve_available_rect(
    *,
    anchor_global=None,
    widget: QWidget | None = None,
    parent: QWidget | None = None,
) -> IntRect:
    screen = resolve_target_screen(
        anchor_global=anchor_global, widget=widget, parent=parent,
    )
    if screen is None:
        return IntRect(0, 0, 1920, 1080)
    try:
        return as_rect(screen.availableGeometry())
    except RuntimeError:
        return IntRect(0, 0, 1920, 1080)


def frame_insets_of(widget: QWidget | None) -> FrameInsets:
    """Measure native frame insets; estimate only when the window is hidden."""
    if widget is None or not _alive(widget):
        return FrameInsets()
    try:
        if widget.isWindow() and widget.isVisible():
            frame = widget.frameGeometry()
            geo = widget.geometry()
            left = geo.x() - frame.x()
            top = geo.y() - frame.y()
            right = frame.right() - geo.right()
            bottom = frame.bottom() - geo.bottom()
            if left >= 0 and top >= 0 and right >= 0 and bottom >= 0:
                return FrameInsets(left, top, right, bottom)
        handle = widget.windowHandle()
        if handle is not None:
            margins = handle.frameMargins()
            return FrameInsets(
                max(0, margins.left()),
                max(0, margins.top()),
                max(0, margins.right()),
                max(0, margins.bottom()),
            )
    except RuntimeError:
        return FrameInsets()
    flags = widget.windowFlags()
    frameless = bool(flags & Qt.FramelessWindowHint)
    if widget.isWindow() and not frameless:
        left, top, right, bottom = _ESTIMATED_TITLE_INSETS
        return FrameInsets(left, top, right, bottom)
    return FrameInsets()


def _release_size_conflicts(widget: QWidget, client: Size) -> None:
    layout = widget.layout()
    if layout is not None:
        layout.setSizeConstraint(QLayout.SetNoConstraint)
    min_size = widget.minimumSize()
    if min_size.width() > client.width or min_size.height() > client.height:
        widget.setMinimumSize(
            min(min_size.width(), client.width),
            min(min_size.height(), client.height),
        )
    max_size = widget.maximumSize()
    if max_size.width() < client.width or max_size.height() < client.height:
        widget.setMaximumSize(
            max(max_size.width(), client.width),
            max(max_size.height(), client.height),
        )


def _shrink_unaccounted_frame(widget: QWidget, planned_frame: IntRect) -> None:
    """If live chrome exceeds the insets used to plan, shrink the client.

    Tests may stub ``frame_insets_of`` to zero while the shown widget still
    has a native frame. Planning then treats client size as frame size, and
    the real frame overflows the safe area by a few pixels.
    """
    if not widget.isVisible():
        return
    try:
        actual = as_rect(widget.frameGeometry())
    except RuntimeError:
        return
    extra_w = actual.width - planned_frame.width
    extra_h = actual.height - planned_frame.height
    if extra_w <= 0 and extra_h <= 0:
        return
    target_w = max(0, widget.width() - extra_w)
    target_h = max(0, widget.height() - extra_h)
    previous_max = widget.maximumSize()
    widget.setMaximumSize(target_w, target_h)
    widget.resize(target_w, target_h)
    widget.setMaximumSize(previous_max)


def move_in_screen(widget: QWidget, pos: QPoint) -> None:
    """Move a window using screen coordinates, including before the first Show.

    Parented ``Qt.Popup`` widgets have no ``windowHandle`` until they are
    shown or ``winId()`` runs. ``QWidget.move`` in that state is
    parent-local, so ``move`` then ``show`` lands on the parent the first
    time and only uses screen coordinates afterwards.
    """
    if not _alive(widget):
        return
    if widget.isWindow() and widget.windowHandle() is None:
        widget.winId()
    widget.move(pos)


def _plan_move_origin(widget: QWidget, plan: GeometryPlan) -> QPoint:
    """Choose the origin ``QWidget.move`` expects for this plan.

    Top-level ``move()`` places the outer frame, including native chrome.
    ``plan.client`` is the inner rectangle after those insets, so using it
    would stack the decoration offset a second time. Embedded / host-local
    plans keep ``client == frame`` in parent coordinates.
    """
    if widget.isWindow():
        return QPoint(plan.frame.x, plan.frame.y)
    return QPoint(plan.client.x, plan.client.y)


def apply_plan(
    widget: QWidget,
    plan: GeometryPlan,
    *,
    release_conflicts: bool = True,
) -> bool:
    """Resize the client, then move by the frame origin for top-level windows.

    Returns True when geometry actually changed. Hidden windows and the
    post-show correction share this convention: estimate insets before the
    native frame exists, then re-apply with measured ``frameGeometry()``.
    """
    if not _alive(widget):
        return False
    client = plan.client
    if release_conflicts:
        _release_size_conflicts(widget, Size(client.width, client.height))
    before = (widget.x(), widget.y(), widget.width(), widget.height())
    widget.resize(client.width, client.height)
    move_in_screen(widget, _plan_move_origin(widget, plan))
    _shrink_unaccounted_frame(widget, plan.frame)
    after = (widget.x(), widget.y(), widget.width(), widget.height())
    return after != before


def plan_for_widget(
    widget: QWidget,
    preferred,
    *,
    parent: QWidget | None = None,
    content_minimum=None,
    position: str = POSITION_CENTER,
    anchor=None,
    anchor_widget: QWidget | None = None,
    gap: int = ANCHOR_GAP,
    margin: int = SCREEN_MARGIN,
    clamp_width_to_parent: bool = False,
    host=None,
) -> GeometryPlan:
    parent = parent if parent is not None else widget.parentWidget()
    anchor_global = None
    anchor_rect = None
    if anchor_widget is not None and _alive(anchor_widget):
        try:
            top_left = anchor_widget.mapToGlobal(anchor_widget.rect().topLeft())
            anchor_rect = IntRect(
                top_left.x(),
                top_left.y(),
                anchor_widget.width(),
                anchor_widget.height(),
            )
            anchor_global = QPoint(
                top_left.x() + anchor_widget.width() // 2,
                top_left.y() + anchor_widget.height() // 2,
            )
        except RuntimeError:
            anchor_rect = None
    if anchor is not None:
        anchor_rect = as_rect(anchor)
        anchor_global = QPoint(
            anchor_rect.x + anchor_rect.width // 2,
            anchor_rect.y + anchor_rect.height // 2,
        )
    if position == POSITION_EMBEDDED:
        available = host if host is not None else (
            parent.rect() if parent is not None and _alive(parent) else widget.rect()
        )
        return plan_geometry(
            available,
            preferred,
            frame=FrameInsets(),
            margin=margin,
            content_minimum=content_minimum,
            host=available,
            position=POSITION_EMBEDDED,
        )
    available = resolve_available_rect(
        anchor_global=anchor_global, widget=widget, parent=parent,
    )
    insets = frame_insets_of(widget)
    pref = as_size(preferred)
    if clamp_width_to_parent and parent is not None and _alive(parent) and parent.width() > 0:
        pref = Size(min(pref.width, max(0, parent.width() - 24)), pref.height)
    host_rect = None
    if parent is not None and _alive(parent):
        try:
            top = parent.window()
            geo = top.frameGeometry() if top is not None else parent.frameGeometry()
            host_rect = as_rect(geo)
        except RuntimeError:
            host_rect = None
    return plan_geometry(
        available,
        pref,
        frame=insets,
        margin=margin,
        content_minimum=content_minimum,
        host=host_rect,
        anchor=anchor_rect,
        position=position,
        gap=gap,
    )


def fit_window(
    widget: QWidget,
    preferred,
    *,
    parent: QWidget | None = None,
    content_minimum=None,
    clamp_width_to_parent: bool = False,
    margin: int = SCREEN_MARGIN,
) -> GeometryPlan:
    """Fit an ordinary window: content owner must already be measurable."""
    plan = plan_for_widget(
        widget,
        preferred,
        parent=parent,
        content_minimum=content_minimum,
        position=POSITION_CENTER,
        clamp_width_to_parent=clamp_width_to_parent,
        margin=margin,
    )
    apply_plan(widget, plan)
    return plan


def fit_popover(
    widget: QWidget,
    anchor_widget: QWidget,
    *,
    preferred=None,
    gap: int = ANCHOR_GAP,
    prefer_below: bool = True,
    margin: int = SCREEN_MARGIN,
    content_minimum=None,
) -> GeometryPlan:
    """Place a popover using final size: below, then above, then clamp."""
    if preferred is None:
        if widget.layout() is not None:
            widget.layout().activate()
        hint = widget.sizeHint().expandedTo(widget.minimumSizeHint())
        preferred = (max(hint.width(), widget.width()), max(hint.height(), widget.height()))
    plan = plan_for_widget(
        widget,
        preferred,
        parent=anchor_widget,
        content_minimum=content_minimum,
        position=POSITION_BELOW if prefer_below else POSITION_ABOVE,
        anchor_widget=anchor_widget,
        gap=gap,
        margin=margin,
    )
    apply_plan(widget, plan)
    return plan


class GeometryRelayout(QObject):
    """Instance-level coalesced relayout. Parent is the host widget."""

    def __init__(self, host: QWidget, apply: Callable[[], None]):
        super().__init__(host)
        self._host = host
        self._apply = apply
        self._pending = False
        self._running = False
        self._last_signature = None
        self._bound_screen = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._run)
        host.installEventFilter(self)
        host.destroyed.connect(self._on_host_destroyed)

    def request(self) -> None:
        if self._pending or not _alive(self) or not _alive(self._host):
            return
        self._pending = True
        self._timer.start()

    def notify_content_changed(self) -> None:
        """QLabel text changes have no generic Qt event; owners must call this."""
        self.request()

    def cancel(self) -> None:
        self._pending = False
        if _alive(self._timer):
            self._timer.stop()
        self._unbind_screen()

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self._host and _alive(self._host):
            kind = event.type()
            if kind in (QEvent.Show, QEvent.FontChange, QEvent.StyleChange):
                self.request()
            elif kind == QEvent.Hide:
                self._unbind_screen()
        return False

    def _run(self) -> None:
        self._pending = False
        if self._running or not _alive(self) or not _alive(self._host):
            return
        self._running = True
        try:
            self._bind_screen()
            self._apply()
            if _alive(self._host):
                geo = self._host.frameGeometry()
                signature = (geo.x(), geo.y(), geo.width(), geo.height())
                if signature == self._last_signature:
                    return
                self._last_signature = signature
        finally:
            self._running = False

    def _bind_screen(self) -> None:
        if not _alive(self._host):
            return
        handle = self._host.windowHandle()
        if handle is None:
            return
        screen = handle.screen()
        if screen is self._bound_screen:
            return
        self._unbind_screen()
        self._bound_screen = screen
        handle.screenChanged.connect(self._on_screen_changed)
        if screen is not None:
            screen.availableGeometryChanged.connect(self._on_available_changed)

    def _unbind_screen(self) -> None:
        if not _alive(self._host):
            self._bound_screen = None
            return
        handle = self._host.windowHandle()
        if handle is not None:
            try:
                handle.screenChanged.disconnect(self._on_screen_changed)
            except TypeError:
                pass
        if self._bound_screen is not None:
            try:
                self._bound_screen.availableGeometryChanged.disconnect(
                    self._on_available_changed
                )
            except TypeError:
                pass
        self._bound_screen = None

    def _on_screen_changed(self, _screen=None) -> None:
        self._unbind_screen()
        self.request()

    def _on_available_changed(self, *_args) -> None:
        self.request()

    def _on_host_destroyed(self, *_args) -> None:
        self._pending = False
        self._bound_screen = None
        if _alive(self._timer):
            self._timer.stop()


def clamp_frame_rect(frame, available, margin: int = SCREEN_MARGIN) -> IntRect:
    """Clamp a frame rectangle into the work-area safe region."""
    work = as_rect(available)
    used = effective_margin(work, FrameInsets(), margin)
    return _clamp_frame(as_rect(frame), _safe_area(work, used))


def nudge_into_work_area(
    widget: QWidget,
    *,
    parent: QWidget | None = None,
    margin: int = SCREEN_MARGIN,
    content_minimum=None,
) -> GeometryPlan | None:
    """Correct overflow only. Do not restore a default preferred size."""
    if not _alive(widget):
        return None
    available = resolve_available_rect(widget=widget, parent=parent)
    insets = frame_insets_of(widget)
    used = effective_margin(available, insets, margin)
    safe = _safe_area(available, used)
    current = as_rect(widget.frameGeometry())
    if safe.contains_rect(current):
        return None
    preferred = Size(
        max(0, current.width - insets.horizontal),
        max(0, current.height - insets.vertical),
    )
    plan = plan_geometry(
        available,
        preferred,
        frame=insets,
        margin=used,
        content_minimum=content_minimum,
        host=current,
        position=POSITION_CENTER,
    )
    apply_plan(widget, plan)
    return plan


def install_geometry_relayout(host: QWidget, apply: Callable[[], None]) -> GeometryRelayout:
    existing = getattr(host, "_tracelab_geometry_relayout", None)
    if isinstance(existing, GeometryRelayout) and _alive(existing):
        return existing
    controller = GeometryRelayout(host, apply)
    host._tracelab_geometry_relayout = controller
    return controller
