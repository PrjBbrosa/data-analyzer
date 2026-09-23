"""Local, interruptible presentation-only chart page transitions.

Business owners commit their View/Section state before this controller sees a
request.  The controller can crossfade two already-correct temporary pixmaps,
or fade one outgoing pixmap over a naturally painted live target; it never
renders data, restores axes, submits compute, or persists state.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from PyQt5.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QPainter, QPixmap
from PyQt5.QtWidgets import QApplication, QWidget

from ...diagnostics import throttled
from ...ui_kit.motion import (
    MotionPolicy,
    POLICY_OFF,
    ValueDriver,
    duration_ms,
    resolve_policy,
    selection_easing,
)


# Production user-navigation admission. Split, programmatic restore, and
# uncomputed cache-miss targets stay on the direct-terminal path.
PAGE_TRANSITION_ENABLED_SECTIONS = ("time", "fft", "fft_time", "frf", "order")

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class PresentationToken:
    """The non-persistent identity and geometry of one presentation request."""

    section: str
    view_id: str
    request_generation: int
    host_epoch: int
    rect: QRect
    device_pixel_ratio: float
    pane_signature: tuple = ()


class TransitionOverlay(QWidget):
    """A transparent-for-input local compositor for one source/target pair."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._source = QPixmap()
        self._target = QPixmap()
        self._progress = 0.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.hide()

    def set_frames(self, source: QPixmap, target: QPixmap | None = None) -> None:
        self._source = QPixmap(source)
        self._target = QPixmap(target) if target is not None else QPixmap()
        self._progress = 0.0
        self.update()

    def set_progress(self, progress: float) -> None:
        self._progress = max(0.0, min(1.0, float(progress)))
        self.update()

    def clear_frames(self) -> None:
        self._source = QPixmap()
        self._target = QPixmap()
        self._progress = 0.0
        self.update()

    def set_target(self, target: QPixmap) -> None:
        self._target = QPixmap(target)
        self._progress = 0.0
        self.update()

    def has_source(self) -> bool:
        return not self._source.isNull()

    def has_target(self) -> bool:
        return not self._target.isNull()

    def image_bytes(self) -> int:
        """Conservative RGBA accounting for the two retained endpoints."""
        return sum(
            max(0, int(pix.width())) * max(0, int(pix.height())) * 4
            for pix in (self._source, self._target)
            if not pix.isNull()
        )

    def composite_snapshot(self) -> QPixmap:
        """Materialize the currently visible mix without grabbing a widget."""
        if self._source.isNull():
            return QPixmap()
        dpr = max(1.0, float(self.devicePixelRatioF()))
        result = QPixmap(
            max(1, int(round(self.width() * dpr))),
            max(1, int(round(self.height() * dpr))),
        )
        result.setDevicePixelRatio(dpr)
        result.fill(Qt.transparent)
        painter = QPainter(result)
        try:
            self._paint_frames(painter, QRect(QPoint(0, 0), self.size()))
        finally:
            painter.end()
        return result

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt callback spelling
        painter = QPainter(self)
        try:
            self._paint_frames(painter, self.rect())
        finally:
            painter.end()

    def _paint_frames(self, painter: QPainter, target: QRect) -> None:
        if self._source.isNull():
            return
        if self._target.isNull():
            painter.setOpacity(1.0 - self._progress)
            painter.drawPixmap(target, self._source)
            painter.setOpacity(1.0)
            return
        progress = self._progress
        painter.setOpacity(1.0 - progress)
        painter.drawPixmap(target, self._source)
        painter.setOpacity(progress)
        painter.drawPixmap(target, self._target)
        painter.setOpacity(1.0)


class PageTransitionController(QObject):
    """Own a single local page-transition session for one chart-stack host.

    The caller supplies images only after it has independently proved both
    endpoints are safe to capture.  A stale target is ignored; interruption
    materializes the current blend as the next source, retaining at most two
    images.  ``finished`` only releases presentation resources.
    """

    transition_started = pyqtSignal(object)
    transition_finished = pyqtSignal(object)
    transition_cancelled = pyqtSignal(str)

    _CHART_INPUT_EVENTS = frozenset(
        {
            QEvent.MouseButtonPress,
            QEvent.MouseButtonRelease,
            QEvent.MouseButtonDblClick,
            QEvent.MouseMove,
            QEvent.Wheel,
            QEvent.ContextMenu,
            QEvent.KeyPress,
            QEvent.KeyRelease,
        }
    )

    def __init__(
        self,
        host: QWidget,
        *,
        policy: MotionPolicy | None = None,
    ) -> None:
        super().__init__(host)
        self._host = host
        self._policy = resolve_policy(policy)
        self._overlay = TransitionOverlay(host)
        self._source_token = None
        self._source_is_local_endpoint = False
        self._target_token = None
        # The overlay remains transparent to hit testing so QWidget routes an
        # event to the real chart viewport.  These direct target filters are
        # therefore the input fence; the overlay attribute is visual plumbing,
        # not the policy that makes a covered chart safe to operate.
        self._target_ready = False
        self._input_targets = ()
        self._frozen_input_targets = []
        self._input_target_destroyed_slots = []
        self._application_filter_installed = False
        self._generation = 0
        self._target_ack_watchdog_token = None
        self._target_ack_watchdog = QTimer(self)
        self._target_ack_watchdog.setSingleShot(True)
        self._target_ack_watchdog.setInterval(1000)
        self._target_ack_watchdog.timeout.connect(
            self._on_target_ack_watchdog_timeout,
        )
        self._driver = ValueDriver(
            self, on_value=self._on_progress, easing=selection_easing(),
        )
        self._driver.clock().finished.connect(self._finish)
        host.installEventFilter(self)

    def motion_policy(self) -> MotionPolicy:
        return self._policy

    def set_motion_policy(self, policy: MotionPolicy | None) -> None:
        self._policy = resolve_policy(policy)
        if not self._policy.interpolates():
            self.cancel("motion-off")

    def is_pending(self) -> bool:
        return self._source_token is not None and self._target_token is None

    def is_active(self) -> bool:
        return self._driver.is_active()

    def input_state(self) -> str:
        """Return the presentation state relevant to chart input routing."""
        if self._source_token is None:
            return "idle"
        if not self._target_ready:
            return "pending"
        return "ready"

    def image_bytes(self) -> int:
        return self._overlay.image_bytes()

    def invalidates_identity(self, section: str, view_id: str) -> bool:
        """Cancel only when a removed/replaced View belongs to this handoff."""
        identity = (str(section), str(view_id))
        return any(
            token is not None
            and (token.section, token.view_id) == identity
            for token in (self._source_token, self._target_token)
        )

    def local_source_endpoint(self, section: str, view_id: str) -> QPixmap:
        """Return the exact outgoing endpoint, only when it was locally read.

        A rapid redirect materializes an A/B blend as its next source.  That
        blend is valid for the compositor but is not a faithful B preview, so
        callers such as UltraView must fall back to their ordinary capture in
        that exceptional case.
        """
        token = self._source_token
        if (
            not self._source_is_local_endpoint
            or token is None
            or token.section != str(section)
            or token.view_id != str(view_id)
        ):
            return QPixmap()
        return QPixmap(self._overlay._source)

    def capture_local_endpoint(
        self, widget: QWidget, *, exclude_overlay: bool = False,
    ) -> QPixmap:
        """Copy one already-visible local surface without export settlement.

        This deliberately calls no canvas ``grab_pixmap``/flush helper.  It is
        valid only for a visible child of this controller's host and never
        becomes a steady cache.  Target capture briefly hides the compositor
        so the target endpoint cannot accidentally contain the old source;
        callers invoke that branch only after a natural-paint acknowledgement.
        """
        if (
            widget is None
            or not (widget is self._host or self._host.isAncestorOf(widget))
            or not widget.isVisible()
            or widget.width() <= 0
            or widget.height() <= 0
        ):
            return QPixmap()
        restore_overlay = bool(exclude_overlay and self._overlay.isVisible())
        if restore_overlay:
            self._overlay.hide()
        try:
            return widget.grab(widget.rect())
        except RuntimeError:
            return QPixmap()
        finally:
            if restore_overlay and self._source_token is not None:
                self._overlay.show()
                self._overlay.raise_()

    def begin_transition(
        self,
        *,
        source_section: str,
        source_view_id: str,
        target_section: str,
        target_view_id: str,
        source_pixmap: QPixmap | None,
        pane_signature: tuple = (),
        overlay_rect: QRect | None = None,
    ) -> PresentationToken | None:
        """Begin one request and return the exact token a target must ack."""
        generation = self._generation + 1
        host_rect = QRect(self._host.rect())
        overlay = (
            QRect(overlay_rect) if overlay_rect is not None else QRect(host_rect)
        )
        if overlay.width() <= 0 or overlay.height() <= 0:
            overlay = QRect(host_rect)
        common = {
            "request_generation": generation,
            "host_epoch": id(self._host),
            "rect": host_rect,
            "device_pixel_ratio": float(self._host.devicePixelRatioF()),
            "pane_signature": tuple(pane_signature),
        }
        source = PresentationToken(
            section=str(source_section), view_id=str(source_view_id), **common,
        )
        target = PresentationToken(
            section=str(target_section), view_id=str(target_view_id), **common,
        )
        if not self.begin_departure(
            source, source_pixmap, overlay_rect=overlay,
        ):
            return None
        if self.arm_target(target):
            return target
        self.cancel("target-not-armable")
        return None

    def watch_target_ack(self, token: PresentationToken) -> bool:
        """Fail closed if a requested natural target paint never arrives.

        The timer never marks a target ready or starts an animation.  It only
        drops an old cover so the real target can remain the visible source of
        truth instead of leaving a permanent pending image after a platform
        paint suppression edge case.
        """
        if token != self._target_token or self.is_active():
            return False
        self._target_ack_watchdog_token = token
        self._target_ack_watchdog.start()
        return True

    def begin_departure(
        self,
        token: PresentationToken,
        pixmap: QPixmap,
        *,
        overlay_rect: QRect | None = None,
    ) -> bool:
        """Hold a captured outgoing endpoint while the target restores."""
        if not self._policy.interpolates():
            self.cancel("departure-not-eligible")
            return False
        # While A -> B is visibly in flight, a user can immediately select C.
        # The B token is then both the prior target and the next departure; it
        # is valid precisely because the currently displayed blend is used as
        # the new source.  Repeating the original departure is still a no-op.
        if self._source_token == token:
            return False
        prior_composite = self._overlay.has_source()
        captured = QPixmap(pixmap) if pixmap is not None else QPixmap()
        if prior_composite and not captured.isNull():
            # ChartStack captured the actual visible A/B composition before
            # this redirect.  It is the only valid source for the production
            # one-image path, where B lives below a transparent overlay.
            source = captured
        elif prior_composite and self._overlay.has_target():
            # A two-image transition already owns both endpoints, so its local
            # composition is complete without another QWidget capture.
            source = self._overlay.composite_snapshot()
        elif prior_composite:
            # Never restart from transparent A alone: reveal the real terminal
            # target instead of manufacturing a discontinuous handoff.
            self.cancel("redirect-source-unavailable")
            return False
        else:
            source = captured
        if source.isNull():
            self.cancel("departure-empty")
            return False
        self._driver.stop_and_keep()
        self._thaw_input_target_updates()
        self._clear_input_targets()
        self._generation += 1
        self._target_ack_watchdog.stop()
        self._target_ack_watchdog_token = None
        self._source_token = token
        self._source_is_local_endpoint = not prior_composite
        self._target_token = None
        self._target_ready = False
        self._install_application_filter()
        geom = QRect(overlay_rect) if overlay_rect is not None else QRect(token.rect)
        if geom.width() <= 0 or geom.height() <= 0:
            geom = QRect(token.rect)
        self._overlay.setGeometry(geom)
        self._overlay.set_frames(source)
        self._overlay.show()
        self._overlay.raise_()
        self.transition_started.emit(token)
        return True

    def constrain_overlay_to(self, rect: QRect) -> bool:
        """Crop the held source to a host-local subset without scaling.

        Cross-section chrome (View tabs, bottom docks) can sit inside the
        stacked host.  The cover must not stretch old pixels to a new size.
        """
        if self._source_token is None:
            return False
        current = QRect(self._overlay.geometry())
        clipped = current.intersected(QRect(rect))
        if clipped.width() <= 0 or clipped.height() <= 0:
            self.cancel("overlay-rect-empty")
            return False
        if clipped == current:
            return True
        source = self._overlay._source
        if source.isNull():
            self.cancel("overlay-source-empty")
            return False
        dpr = max(1.0, float(source.devicePixelRatioF()))
        physical = QRect(
            int(round((clipped.x() - current.x()) * dpr)),
            int(round((clipped.y() - current.y()) * dpr)),
            int(round(clipped.width() * dpr)),
            int(round(clipped.height() * dpr)),
        ).intersected(source.rect())
        if physical.width() <= 0 or physical.height() <= 0:
            self.cancel("overlay-crop-empty")
            return False
        cropped = source.copy(physical)
        cropped.setDevicePixelRatio(dpr)
        held_target = self._overlay._target
        if held_target.isNull():
            self._overlay.set_frames(cropped)
        else:
            target_crop = held_target.copy(physical)
            target_crop.setDevicePixelRatio(dpr)
            self._overlay.set_frames(cropped, target_crop)
        self._overlay.setGeometry(clipped)
        return True

    def arm_target(self, token: PresentationToken) -> bool:
        """Mark the exact target expected from a later natural-paint ack."""
        if self._source_token is None or token == self._source_token:
            return False
        if token.request_generation != self._source_token.request_generation:
            return False
        self._target_token = token
        self._target_ready = False
        return True

    def watch_input_targets(self, token: PresentationToken, targets) -> bool:
        """Fence only chart hit surfaces while a visible source covers them.

        A pending target drops input; once its natural paint is acknowledged,
        the first chart event settles the presentation and continues through
        the very same Qt delivery.  No event is stored or replayed.
        """
        if token != self._target_token or self._source_token is None:
            return False
        self._clear_input_targets()
        widgets = []
        for target in tuple(targets or ()):
            for widget in self._input_widgets_for(target):
                if widget not in widgets:
                    widgets.append(widget)
        for widget in widgets:
            slot = self._on_input_target_destroyed
            try:
                widget.installEventFilter(self)
                widget.destroyed.connect(slot)
            except RuntimeError:
                continue
            self._input_targets += (widget,)
            self._input_target_destroyed_slots.append((widget, slot))
        return bool(self._input_targets)

    def raise_overlay(self) -> None:
        """Keep the local cover above sibling pin widgets."""
        if self._overlay.isVisible():
            self._overlay.raise_()

    def accept_target(
        self, token: PresentationToken, pixmap: QPixmap | None = None,
    ) -> bool:
        """Start after a matching natural target paint acknowledgement.

        Passing no pixmap fades the held source over the real target that has
        already painted below the transparent input overlay.  This is the
        production path: it keeps B's crossfade without a second synchronous
        target grab.  Tests and other measured callers can still provide a
        target endpoint when that has independently been admitted.
        """
        if (
            not self._policy.interpolates()
            or token != self._target_token
            or token.rect != self._host.rect()
            or not self._overlay.isVisible()
            or self.is_active()
        ):
            return False
        if pixmap is not None and not pixmap.isNull():
            self._overlay.set_target(pixmap)
        self._target_ack_watchdog.stop()
        self._target_ack_watchdog_token = None
        self._target_ready = True
        # The admitted target has already painted.  Overlay frames are the
        # same presentation, so further GraphicsView replays are duplicate
        # work; quality/update requests stay queued until this cover lifts.
        QTimer.singleShot(0, self._freeze_input_target_updates)
        self._driver.snap(0.0)
        self._driver.go(
            1.0, duration_ms=duration_ms("page_transition", self._policy),
        )
        return self._driver.is_active()

    def cancel(self, reason: str) -> None:
        """Release temporary images; business/render state deliberately stays."""
        had_session = self._source_token is not None or self._target_token is not None
        self._generation += 1
        self._target_ack_watchdog.stop()
        self._target_ack_watchdog_token = None
        self._driver.stop_and_keep()
        self._source_token = None
        self._source_is_local_endpoint = False
        self._target_token = None
        self._target_ready = False
        self._clear_input_targets()
        self._remove_application_filter()
        self._overlay.hide()
        self._overlay.clear_frames()
        self._thaw_input_target_updates()
        if had_session:
            self.transition_cancelled.emit(str(reason))

    def close(self) -> None:
        self.cancel("close")

    def eventFilter(self, watched, event):  # noqa: N802 - Qt callback spelling
        if watched in self._input_targets:
            if event.type() in self._CHART_INPUT_EVENTS:
                state = self.input_state()
                if state == "pending":
                    return True
                if state == "ready":
                    # Returning False lets the original target process this
                    # exact event once after the temporary cover is gone.
                    self.cancel("covered-chart-input-ready")
                    return False
            elif event.type() in self._input_invalidation_events():
                # Ordinary expose/paint is not semantic invalidation: the
                # overlay's own frames and later quality paints must be
                # allowed to reach the already-admitted target.  Content
                # replacement is signalled by the canvas owner.
                self.cancel("target-surface-invalidated")
                return False
        if watched is self._host:
            kind = event.type()
            if kind in self._host_invalidation_events():
                self.cancel("host-geometry-or-lifecycle")
            elif kind == QEvent.LayoutRequest:
                # A page switch may legitimately request layout without moving
                # this local compositor.  Check on the next turn and cancel
                # only if the endpoint rectangle was actually invalidated.
                QTimer.singleShot(0, self._cancel_if_host_rect_changed)
        elif (
            watched is QApplication.instance()
            and event.type() in self._application_invalidation_events()
        ):
            self.cancel("application-inactive")
        return super().eventFilter(watched, event)

    def _on_progress(self, value) -> None:
        self._overlay.set_progress(float(value))

    def _finish(self) -> None:
        if not self._driver.is_active() and self._target_token is not None:
            token = self._target_token
            self._source_token = None
            self._source_is_local_endpoint = False
            self._target_token = None
            self._target_ready = False
            self._clear_input_targets()
            self._remove_application_filter()
            self._overlay.hide()
            self._overlay.clear_frames()
            self._thaw_input_target_updates()
            self.transition_finished.emit(token)

    def _on_target_ack_watchdog_timeout(self) -> None:
        token = self._target_ack_watchdog_token
        self._target_ack_watchdog_token = None
        if token is not None and token == self._target_token and not self.is_active():
            throttled(
                _LOG,
                "page-transition:target-paint-timeout",
                logging.WARNING,
                "page transition target paint ack timed out "
                "(target-paint-timeout): section=%s view=%s request_generation=%s",
                getattr(token, "section", None),
                getattr(token, "view_id", None),
                getattr(token, "request_generation", None),
            )
            self.cancel("target-paint-timeout")

    def _cancel_if_host_rect_changed(self) -> None:
        token = self._source_token
        if token is not None and token.rect != self._host.rect():
            self.cancel("host-layout-geometry")

    @staticmethod
    def _input_widgets_for(target):
        if isinstance(target, QWidget):
            yield target
        graphics_widget = getattr(target, "_glw", None)
        viewport = getattr(graphics_widget, "viewport", None)
        if callable(viewport):
            try:
                viewport = viewport()
            except RuntimeError:
                viewport = None
        if isinstance(viewport, QWidget):
            yield viewport

    @staticmethod
    def _input_invalidation_events():
        events = {
            QEvent.Resize,
            QEvent.Move,
            QEvent.Hide,
            QEvent.Close,
            QEvent.ParentChange,
        }
        dpr_change = getattr(QEvent, "DevicePixelRatioChange", None)
        if dpr_change is not None:
            events.add(dpr_change)
        return events

    @classmethod
    def _host_invalidation_events(cls):
        events = {
            QEvent.Resize,
            QEvent.Hide,
            QEvent.Close,
            QEvent.WindowDeactivate,
            QEvent.WindowStateChange,
        }
        dpr_change = getattr(QEvent, "DevicePixelRatioChange", None)
        if dpr_change is not None:
            events.add(dpr_change)
        return events

    @staticmethod
    def _application_invalidation_events():
        return {
            event_type
            for event_type in (
                getattr(QEvent, "ApplicationDeactivate", None),
                getattr(QEvent, "ApplicationStateChange", None),
            )
            if event_type is not None
        }

    def _install_application_filter(self) -> None:
        if self._application_filter_installed:
            return
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self)
        self._application_filter_installed = True

    def _remove_application_filter(self) -> None:
        if not self._application_filter_installed:
            return
        app = QApplication.instance()
        if app is not None:
            try:
                app.removeEventFilter(self)
            except RuntimeError:
                pass
        self._application_filter_installed = False

    def _clear_input_targets(self) -> None:
        for widget, slot in self._input_target_destroyed_slots:
            try:
                widget.removeEventFilter(self)
                widget.destroyed.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._input_target_destroyed_slots.clear()
        self._input_targets = ()

    def _freeze_input_target_updates(self) -> None:
        """Drop duplicate exposes of the already-admitted live target.

        Overlay opacity changes are presentation-only.  They must not replay
        curve painting.  Queued quality ``update()`` calls resume on thaw.
        """
        if not self._target_ready or self._source_token is None:
            return
        self._thaw_input_target_updates()
        frozen = []
        for widget in self._input_targets:
            try:
                if widget.updatesEnabled():
                    widget.setUpdatesEnabled(False)
                    frozen.append(widget)
            except RuntimeError:
                continue
        self._frozen_input_targets = frozen

    def _thaw_input_target_updates(self) -> None:
        for widget in self._frozen_input_targets:
            try:
                widget.setUpdatesEnabled(True)
            except RuntimeError:
                pass
        self._frozen_input_targets = []

    def _on_input_target_destroyed(self, *_args) -> None:
        if self._source_token is not None:
            self.cancel("target-surface-destroyed")
