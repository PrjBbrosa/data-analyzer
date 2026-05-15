"""Cockpit four-state machine.

Spec: ``docs/analyzer/acquisition/specs/2026-05-15-acquisition-cockpit-ui-spec.md``
§State Machine Contract.

The four states are:

    Disconnected → ConnectedIdle → Recording → ReviewModal → ConnectedIdle

Two derived predicates pin the legal transitions:

- ``healthy`` (Disconnected → ConnectedIdle):
  ``HwHealth.ok ∧ XcpHealth.connected ∧ first DAQ frame ≤ 3 s``.
- ``finalized`` (Recording → ReviewModal): writer drained, file
  handles closed, ``session_summary.json`` written, optional SHA
  computed, optional manifest entry written.

Both predicates are evaluated **outside** this module — the state
machine accepts a verdict (boolean + optional first-failure reason)
and routes the transition. This keeps the state machine Qt-free and
unit-testable without mocking Health or the writer.

The Cockpit's Qt ``MainWindow`` (in :mod:`mf4_analyzer.acquisition_ui.main_window`)
owns the QTimer that polls ``HealthAggregator.poll_once()`` and computes
the ``healthy`` predicate from the resulting ``HealthSnapshot``. This
module knows nothing about Qt — its only inputs are pre-computed
verdicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class CockpitState(str, Enum):
    """Four-state enum (string-valued so it serializes cleanly in logs)."""

    DISCONNECTED = "disconnected"
    CONNECTED_IDLE = "connected_idle"
    RECORDING = "recording"
    REVIEW_MODAL = "review_modal"


# Predicate names surfaced in the right panel when a transition fails.
# Spec §State Machine Contract `Disconnected`:
#   "the right panel surfaces the first failing predicate (`HW`, `XCP`,
#    or 'no frame received')".
HEALTHY_PREDICATE_HW = "HW"
HEALTHY_PREDICATE_XCP = "XCP"
HEALTHY_PREDICATE_FIRST_FRAME = "no frame received"


@dataclass(frozen=True)
class HealthyPredicateResult:
    """Verdict from the ``healthy`` predicate computation.

    ``healthy`` is True only when all three sub-predicates are True.
    ``first_failure`` is the first failing sub-predicate's display
    name, or ``None`` when healthy. The Cockpit right panel quotes
    this string directly.
    """

    healthy: bool
    first_failure: str | None = None

    @classmethod
    def from_components(
        cls,
        *,
        hw_ok: bool,
        xcp_connected: bool,
        first_frame_received: bool,
    ) -> "HealthyPredicateResult":
        """Build a verdict from the three component booleans.

        Order matters: spec wording fixes the surface order to
        ``HW → XCP → first frame``. The first ``False`` wins.
        """
        if not hw_ok:
            return cls(healthy=False, first_failure=HEALTHY_PREDICATE_HW)
        if not xcp_connected:
            return cls(healthy=False, first_failure=HEALTHY_PREDICATE_XCP)
        if not first_frame_received:
            return cls(healthy=False, first_failure=HEALTHY_PREDICATE_FIRST_FRAME)
        return cls(healthy=True, first_failure=None)


@dataclass
class CockpitStateMachine:
    """Pure-Python four-state machine.

    Callers drive transitions via ``request_*`` methods. Each method
    returns the new ``CockpitState``. Illegal transitions raise
    ``ValueError`` so test failures point at the exact misuse.

    ``on_change`` is an optional callback list (not Qt) used by the
    Cockpit window to refresh its right panel and main button label
    on every transition. Subscribers receive ``(old_state, new_state)``.
    """

    state: CockpitState = CockpitState.DISCONNECTED
    # Last ``healthy`` verdict — surfaced in the right panel on a
    # failed Disconnected → ConnectedIdle attempt.
    last_healthy_result: HealthyPredicateResult | None = None
    on_change: list[Callable[[CockpitState, CockpitState], None]] = field(
        default_factory=list
    )

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    def subscribe(
        self, callback: Callable[[CockpitState, CockpitState], None]
    ) -> Callable[[], None]:
        """Register a transition listener. Returns an unsubscribe function."""
        self.on_change.append(callback)

        def _unsubscribe() -> None:
            try:
                self.on_change.remove(callback)
            except ValueError:
                pass

        return _unsubscribe

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def request_connect(self, result: HealthyPredicateResult) -> CockpitState:
        """Disconnected → ConnectedIdle when ``result.healthy`` is True.

        Stays in ``Disconnected`` otherwise and stashes the verdict so
        the right panel can quote the first failing predicate.
        """
        self._require(CockpitState.DISCONNECTED)
        self.last_healthy_result = result
        if result.healthy:
            return self._goto(CockpitState.CONNECTED_IDLE)
        return self.state

    def request_disconnect(self) -> CockpitState:
        """Drop back to ``Disconnected`` from idle/recording-aborted paths.

        Used for the connection-timeout path: after 3 s without a
        first frame the caller torn-downs the session and calls this
        with the failure verdict supplied via ``last_healthy_result``.
        """
        if self.state in (CockpitState.CONNECTED_IDLE, CockpitState.DISCONNECTED):
            return self._goto(CockpitState.DISCONNECTED)
        raise ValueError(
            f"request_disconnect not legal from {self.state.value}; "
            "stop the recording first"
        )

    def request_start_recording(self) -> CockpitState:
        """ConnectedIdle → Recording.

        The caller (Cockpit window) is responsible for enforcing the
        ``red health disables record`` rule before invoking this
        method. The state machine itself has no health knowledge.
        """
        self._require(CockpitState.CONNECTED_IDLE)
        return self._goto(CockpitState.RECORDING)

    def request_stop_recording(self, *, finalized: bool) -> CockpitState:
        """Recording → ReviewModal when ``finalized`` is True.

        When ``finalized`` is False the state stays in ``Recording``
        — the caller (Stage 5) shows an error toast and lets the user
        retry stop. Stage 4 always passes ``finalized=True`` because
        the real stop/flush/finalize sequence lives in Stage 5; the
        Stage 4 review modal is a closes-itself placeholder.
        """
        self._require(CockpitState.RECORDING)
        if not finalized:
            return self.state
        return self._goto(CockpitState.REVIEW_MODAL)

    def request_review_close(self) -> CockpitState:
        """ReviewModal → ConnectedIdle (or Disconnected if session is gone).

        Spec §State Machine Contract `ReviewModal`:
          "Closing the modal returns to ``ConnectedIdle``."

        The state machine returns to idle unconditionally — the
        caller can chain ``request_disconnect`` afterwards if the
        backend session has been torn down.
        """
        self._require(CockpitState.REVIEW_MODAL)
        return self._goto(CockpitState.CONNECTED_IDLE)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require(self, expected: CockpitState) -> None:
        if self.state != expected:
            raise ValueError(
                f"transition expected current state {expected.value}, "
                f"got {self.state.value}"
            )

    def _goto(self, new_state: CockpitState) -> CockpitState:
        old = self.state
        self.state = new_state
        for cb in list(self.on_change):
            cb(old, new_state)
        return new_state
