"""Recording escalation ladder — view-model + banner overlay (Spec §B5+B6).

Two concerns live here:

1. A pure view-model — :func:`escalation_state` maps a ``HealthSnapshot``
   (+ an explicitly-passed ``disk_free_bytes``) to an :class:`EscalationState`
   of ``(level, issues)``, and :func:`effective_chip_levels` folds the issue
   severities back onto the five chip levels. **All severity is delegated to
   the existing band helpers** in
   :mod:`mf4_analyzer.acquisition_capture.preflight_estimates`
   (``band_dropped_frames`` / ``band_disk_remaining`` / ``band_ring_buffer`` /
   ``band_rec_last_rx_age_s``) — no new thresholds are written here, and the
   frozen ``HealthSnapshot`` gains no disk field (disk is passed in).

2. :class:`EscalationBar` — a single-row banner that lives as an **overlay
   just above the** ``QStatusBar`` (never inside the body layout), so its
   appear/disappear cannot reflow the splitter or the ``LiveCardGrid``.

The banner is the *severity/alarm* channel; the neutral recording facts
(duration / disk-time / samples / size / write-rate) stream in the
``QStatusBar`` message. The two are separate widgets and never overlap.

``rec.write_rate_bps`` is **samples/s** (a legacy field name); it is never
interpreted as bytes/s here.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import QPoint, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from mf4_analyzer.acquisition_capture.health import HealthLevel, HealthSnapshot
from mf4_analyzer.acquisition_capture.preflight_estimates import (
    band_disk_remaining,
    band_dropped_frames,
    band_rec_last_rx_age_s,
    band_ring_buffer,
)

# Severity ranking for "worst wins" folding. ``off`` and ``green`` are equally
# non-alarming for escalation purposes.
_SEVERITY: dict[str, int] = {"off": 0, "green": 0, "yellow": 1, "red": 2}


@dataclass(frozen=True)
class EscalationIssue:
    """One escalated condition sourced from a REC-relevant band."""

    source_chip: str
    message: str
    level: HealthLevel
    reason_key: str


@dataclass(frozen=True)
class EscalationState:
    """Aggregate escalation: overall ``level`` + the contributing ``issues``.

    ``issues`` are held in a fixed *priority* order (disk, last-rx, ring,
    dropped) so :attr:`reason_key` and the banner text are deterministic.
    """

    level: HealthLevel
    issues: tuple[EscalationIssue, ...]

    @property
    def reason_key(self) -> str | None:
        """The reason_key of the most-severe issue (ties broken by order)."""
        worst: EscalationIssue | None = None
        for issue in self.issues:
            if worst is None or _SEVERITY[issue.level] > _SEVERITY[worst.level]:
                worst = issue
        return worst.reason_key if worst is not None else None

    def top_issues(self, limit: int = 2) -> list[EscalationIssue]:
        """Up to ``limit`` issues, most-severe first (stable within a tier)."""
        ordered = sorted(self.issues, key=lambda i: -_SEVERITY[i.level])
        return ordered[:limit]


def escalation_state(
    snapshot: HealthSnapshot,
    *,
    disk_free_bytes: int,
) -> EscalationState:
    """Map ``snapshot`` (+ disk context) to the current escalation ladder.

    Only ``yellow``/``red`` bands become issues; a clean recording yields an
    empty issue tuple and ``level == "green"``. Every severity call routes
    through an existing band helper — this function introduces no thresholds.
    """
    rec = snapshot.rec
    issues: list[EscalationIssue] = []

    # Priority order (disk & last-rx are the operationally urgent ones).
    disk_level = band_disk_remaining(disk_free_bytes)
    if disk_level in ("yellow", "red"):
        gb = disk_free_bytes / (1024 ** 3)
        issues.append(
            EscalationIssue("REC", f"磁盘剩余 {gb:.2f} GB", disk_level, "disk")
        )

    rx_level = band_rec_last_rx_age_s(rec.last_rx_age_s)
    if rx_level in ("yellow", "red"):
        issues.append(
            EscalationIssue(
                "REC", f"最近帧延迟 {rec.last_rx_age_s:.1f}s", rx_level, "last_rx"
            )
        )

    ring_level = band_ring_buffer(rec.ring_buffer_fill_pct)
    if ring_level in ("yellow", "red"):
        issues.append(
            EscalationIssue(
                "REC", f"缓冲 {rec.ring_buffer_fill_pct:.0f}%", ring_level, "ring"
            )
        )

    dropped_level = band_dropped_frames(rec.dropped_frames)
    if dropped_level in ("yellow", "red"):
        issues.append(
            EscalationIssue(
                "REC", f"丢帧 {rec.dropped_frames}", dropped_level, "dropped"
            )
        )

    overall: HealthLevel = "green"
    for issue in issues:
        if _SEVERITY[issue.level] > _SEVERITY[overall]:
            overall = issue.level
    return EscalationState(overall, tuple(issues))


def effective_chip_levels(
    snapshot: HealthSnapshot,
    state: EscalationState,
) -> dict[str, HealthLevel]:
    """Fold escalation issues back onto the five chip levels (worst wins).

    disk / ring / dropped / last-rx all map to the ``REC`` chip so the banner
    can never be red while the REC chip stays green.
    """
    levels: dict[str, HealthLevel] = dict(snapshot.levels())
    for issue in state.issues:
        current = levels.get(issue.source_chip, "off")
        if _SEVERITY[issue.level] > _SEVERITY.get(current, 0):
            levels[issue.source_chip] = issue.level
    return levels


# ---------------------------------------------------------------------------
# Banner overlay
# ---------------------------------------------------------------------------

# Precision-Light tinted bands. Kept on the widget (dynamic stylesheet) so the
# surface color follows the escalation level, not a global QSS property rule.
_BAR_STYLE = {
    "yellow": (
        "#escalationBar { background: #fef3e2; border-top: 1px solid #f0b866; }"
    ),
    "red": (
        "#escalationBar { background: #fdeceb; border-top: 1px solid #ef9a9a; }"
    ),
}
_TEXT_COLOR = {"yellow": "#92610a", "red": "#9a1c1c"}
_DOT_COLOR = {"yellow": "#d97706", "red": "#dc2626"}


class EscalationBar(QWidget):
    """Single-row escalation banner overlaid above the ``QStatusBar``.

    Contract (plan Task B-3):

    - :meth:`apply` takes an :class:`EscalationState`.
      ``green`` recovers (stop, hide, clear the ack latch); ``yellow`` shows a
      nudge (up to 2 issues); ``red`` shows the banner and — via the wired
      ``applied`` signal — pulses the health-strip REC chip on entry or when
      the ``reason_key`` changes.
    - :meth:`acknowledge` collapses (hides) the banner but keeps the latch, so
      the same reason stays dismissed; a *different* reason or a green→red
      recovery re-arms it.
    - :meth:`reanchor` repositions the overlay above a status bar; the
      appear/disappear never touches the body geometry (this widget is not in
      any layout).
    """

    #: Emitted whenever :meth:`apply` runs, carrying the ``EscalationState``.
    #: The owner wires this to ``HealthStrip.apply_escalation`` so a single
    #: ``apply(state)`` drives both the banner and the chip pulse/summary.
    applied = pyqtSignal(object)

    #: Emitted when the operator acknowledges (collapses) the banner.
    acknowledged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("escalationBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(30)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 10, 0)
        layout.setSpacing(9)

        self._dot = QLabel(self)
        self._dot.setObjectName("escalationBarDot")
        self._dot.setFixedSize(9, 9)
        self._message = QLabel("", self)
        self._message.setObjectName("escalationBarMessage")
        self._message.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._ack_btn = QToolButton(self)
        self._ack_btn.setObjectName("escalationBarAck")
        self._ack_btn.setText("知道了")
        self._ack_btn.setCursor(Qt.PointingHandCursor)
        self._ack_btn.setAutoRaise(True)
        self._ack_btn.clicked.connect(self.acknowledge)

        layout.addWidget(self._dot)
        layout.addWidget(self._message, 1)
        layout.addWidget(self._ack_btn)

        self._state = EscalationState("green", ())
        self._collapsed = False
        self._latched_reason: str | None = None
        self._status_bar: QWidget | None = None

    # ------------------------------------------------------------------
    # State binding
    # ------------------------------------------------------------------

    def apply(self, state: EscalationState) -> None:
        """Drive the banner (and, via ``applied``, the strip) for ``state``."""
        self._state = state
        self.applied.emit(state)

        if state.level == "green":
            # Recovery: stop, hide, clear the ack latch so the next alarm shows.
            self._collapsed = False
            self._latched_reason = None
            self.setVisible(False)
            return

        reason = state.reason_key
        # A different reason re-arms a previously-collapsed banner.
        if self._collapsed and reason != self._latched_reason:
            self._collapsed = False
        self._latched_reason = reason

        self._message.setText(self._compose(state))
        self._apply_level_style(state.level)

        if self._collapsed:
            self.setVisible(False)
        else:
            self.setVisible(True)
            self._reposition()

    def acknowledge(self) -> None:
        """Collapse (hide) the banner but keep the reason latched."""
        self._collapsed = True
        self.setVisible(False)
        self.acknowledged.emit()

    def reset(self) -> None:
        """Fully clear the banner (stop, hide, drop the latch)."""
        self._state = EscalationState("green", ())
        self._collapsed = False
        self._latched_reason = None
        self.setVisible(False)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    @property
    def state(self) -> EscalationState:
        return self._state

    def message_text(self) -> str:
        return self._message.text()

    # ------------------------------------------------------------------
    # Placement (overlay — never in the body layout)
    # ------------------------------------------------------------------

    def reanchor(self, status_bar: QWidget | None = None) -> None:
        """Store the status bar (if given) and reposition above it."""
        if status_bar is not None:
            self._status_bar = status_bar
        self._reposition()

    def _reposition(self) -> None:
        parent = self.parentWidget()
        sb = self._status_bar
        if parent is None or sb is None:
            return
        height = self.height() or self.sizeHint().height()
        top = sb.mapTo(parent, sb.rect().topLeft()).y()
        self.setGeometry(0, max(0, top - height), parent.width(), height)
        if self.isVisible():
            self.raise_()

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compose(state: EscalationState) -> str:
        """Up to two issue messages, most-severe first, ` · `-joined."""
        return " · ".join(issue.message for issue in state.top_issues(2))

    def _apply_level_style(self, level: str) -> None:
        self.setStyleSheet(_BAR_STYLE.get(level, ""))
        dot = _DOT_COLOR.get(level, "#94a3b8")
        self._dot.setStyleSheet(
            f"background-color: {dot}; border-radius: 4px;"
        )
        text = _TEXT_COLOR.get(level, "#334155")
        self._message.setStyleSheet(f"color: {text};")
        self.setProperty("level", level)
