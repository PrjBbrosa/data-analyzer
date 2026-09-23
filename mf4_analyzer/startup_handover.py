"""App-owned Qt bridge for splash → main-window handover.

``StartupFeedback`` stays stdlib-only. This module owns the GUI-thread reveal
of the main window: one show, no nested event loops, no blocking I/O.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class StartupHandover:
    """Unique owner of main-window reveal after splash invisibility (or fallback)."""

    def __init__(
        self,
        app,
        window,
        feedback,
        *,
        on_show: Callable[[], None] | None = None,
    ) -> None:
        from PyQt5.QtCore import QObject, Qt, pyqtSignal, pyqtSlot

        self._app = app
        self._window = window
        self._feedback = feedback
        self._on_show = on_show
        self._show_called = False
        self._started = False
        self._closed = False
        self._first_frame = False
        owner = self

        class _Bridge(QObject):
            reveal = pyqtSignal(object)

            def __init__(self, parent) -> None:
                super().__init__(parent)
                self.reveal.connect(self._deliver, type=Qt.QueuedConnection)

            @pyqtSlot(object)
            def _deliver(self, payload: object) -> None:
                owner._on_reveal(payload)

        parent = app if isinstance(app, QObject) else None
        self._bridge = _Bridge(parent)
        self._listener = self._on_feedback_event

    @property
    def show_called(self) -> bool:
        return self._show_called

    @property
    def first_frame_seen(self) -> bool:
        return self._first_frame

    def mark_first_frame(self) -> None:
        """Timing-only: real main-window Paint; never drives splash.finish."""

        self._first_frame = True
        try:
            from mf4_analyzer.startup_timing import record_splash_event

            record_splash_event(
                "main_first_frame",
                session=getattr(self._feedback, "session", None),
            )
        except Exception:
            logger.exception("main_first_frame diagnostic failed")

    def begin(self) -> None:
        """Arm the listener first, then request finish (avoid missing a fast ACK)."""

        if self._started or self._closed:
            return
        self._started = True
        feedback = self._feedback
        feedback.add_listener(self._listener)
        # Finish before spawn / disabled / already dead → reveal without waiting.
        feedback.finish()
        # If finish already decided reveal synchronously via listener, done.
        # Otherwise the queued reveal signal will arrive on the GUI thread.
        snap = feedback.snapshot()
        if snap.get("degraded") or snap.get("fail_reason") == "disabled":
            self._on_reveal(
                {
                    "event": "can_reveal",
                    "session": feedback.session,
                    "reason": "disabled",
                    "hidden": False,
                    "hidden_reason": None,
                    "handover_failed": False,
                    "child_exit_code": None,
                    "force_terminated": False,
                }
            )

    def close(self) -> None:
        """Symmetric teardown: drop listener, disconnect signal, release bridge."""

        if self._closed:
            return
        self._closed = True
        try:
            self._feedback.remove_listener(self._listener)
        except Exception:
            logger.exception("startup handover listener remove failed")
        try:
            self._bridge.reveal.disconnect()
        except (TypeError, RuntimeError):
            pass
        self._bridge.deleteLater()
        self._bridge = None  # type: ignore[assignment]

    def _on_feedback_event(self, payload: dict[str, Any]) -> None:
        """I/O / watchdog thread entry — marshal to the GUI bridge when needed."""

        if self._closed:
            return
        if not isinstance(payload, dict):
            return
        if payload.get("event") != "can_reveal":
            return
        bridge = self._bridge
        if bridge is None:
            return
        from PyQt5.QtCore import QThread

        body = dict(payload)
        # Same-thread: invoke directly so tests / nested calls do not depend on
        # a queued event that never runs while the GUI thread is blocked.
        if QThread.currentThread() is bridge.thread():
            self._on_reveal(body)
            return
        try:
            bridge.reveal.emit(body)
        except RuntimeError:
            # Bridge already deleted.
            return

    def _on_reveal(self, payload: object) -> None:
        """GUI thread: show the main window exactly once."""

        if self._closed or self._show_called:
            return
        # Cancellation / app teardown must not be revived by a late ACK.
        app = self._app
        try:
            from PyQt5 import sip
            from PyQt5.QtCore import QObject

            for widget in (app, self._window):
                if isinstance(widget, QObject) and sip.isdeleted(widget):
                    return
        except (ImportError, RuntimeError, TypeError):
            pass
        if not isinstance(payload, dict):
            return
        session = payload.get("session")
        if session is not None and session != self._feedback.session:
            return
        self._show_called = True
        try:
            from mf4_analyzer.startup_timing import record_splash_event

            record_splash_event(
                "main_show_called",
                session=self._feedback.session,
                detail={
                    "reason": payload.get("reason"),
                    "hidden_reason": payload.get("hidden_reason"),
                    "handover_failed": payload.get("handover_failed"),
                },
            )
        except Exception:
            logger.exception("main_show_called diagnostic failed")
        try:
            self._window.show()
        except RuntimeError:
            return
        if self._on_show is not None:
            try:
                self._on_show()
            except Exception:
                logger.exception("startup handover on_show failed")
