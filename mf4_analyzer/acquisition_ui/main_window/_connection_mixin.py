"""ConnectionMixin: connection attempts, backend swap, and probes for CockpitMainWindow."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from mf4_analyzer.acquisition_capture.backends import (
    FakeRecorderBackend,
    RecorderBackendUnavailableError,
)
from mf4_analyzer.acquisition_capture.health import (
    CanHealth,
    DaqHealth,
    HwHealth,
    RecHealth,
    XcpHealth,
)
from mf4_analyzer.acquisition_capture.session import SelectedMeasurement
from mf4_analyzer.acquisition_capture import thresholds

logger = logging.getLogger(__name__)


class ConnectionMixin:
    """Domain mixin: connection attempts, Vector backend swap, and health probes.

    All methods become CockpitMainWindow instance methods.
    They may only reference ``self.*`` attributes set in
    ``CockpitMainWindow.__init__``.

    QMessageBox monkeypatch anchor:
    Tests patch ``mf4_analyzer.acquisition_ui.main_window.QMessageBox.open``.
    All QMessageBox construction in this mixin resolves the class via
    ``sys.modules`` at call time so patches applied to the package
    namespace are visible here.
    """

    def _invalidate_owned_vector_backend(self) -> None:
        if not self._owns_vector_backend:
            return
        self._stop_backend_best_effort(self._backend)
        self._backend = FakeRecorderBackend()
        self._owns_vector_backend = False
        self._update_backend_badge()

    def _update_backend_badge(self) -> None:
        badge = getattr(self, "_backend_badge", None)
        if badge is None:
            return
        if self._owns_vector_backend:
            text = "后端: Vector"
        elif isinstance(self._backend, FakeRecorderBackend):
            text = "后端: FAKE·演示" if self._allow_fake_backend else "后端: FAKE"
        else:
            text = "后端: " + type(self._backend).__name__.replace(
                "RecorderBackend", ""
            )
        badge.setText(text)

    def _begin_connection_attempt(self) -> None:
        """Start connection attempt. Triggers backend start + live timer."""
        self._connection_ever_attempted = True
        selection = self._left_pane.current_selection() if hasattr(self, "_left_pane") else []
        if not selection and self._initial_pool:
            # Auto-select first measurement so the demo can start the
            # backend without a real A2L click-through.
            self._left_pane._set_measurement_selected(
                self._initial_pool[0].name, True
            )
            selection = self._left_pane.current_selection()
        # T1-3: if transport + IF_DATA + a real pool are all present,
        # try to swap the default Fake backend for a real Vector one.
        # The swap is a no-op when any precondition is missing OR when
        # the caller injected a non-Fake backend at construction time
        # (preserving the existing test-injection pattern).
        if not self._maybe_swap_to_vector_backend(selection=selection):
            self._reset_connection_attempt_state()
            return
        self._update_backend_badge()
        if not selection:
            # Demo seed: only allowed after preconditions resolve to a
            # non-vehicle path (demo fake or caller-injected backend).
            selection = [SelectedMeasurement(name="DemoSignal")]
        try:
            self._backend.start(selection)
        except Exception as exc:  # noqa: BLE001 - keep cockpit responsive
            logger.exception("backend start failed: %s", exc)
            self._reset_connection_attempt_state()
            if self._owns_vector_backend:
                self._invalidate_owned_vector_backend()
            else:
                self._stop_backend_best_effort(self._backend)
            self._status.showMessage(f"连接失败: {exc}")
            return
        self._connection_attempt_started = time.monotonic()
        self._stream_start_ts = self._connection_attempt_started
        self._first_frame_ts = None
        self._fake_xcp_connected = True
        self._fake_rec_state = "off"
        self._fake_can_load_pct = 12.5
        # Start timers if not yet running.
        if not self._health_timer.isActive():
            self._health_timer.start()
        if not self._live_timer.isActive():
            self._live_timer.start()
        # Seed the center pane with cards（pin 模型见 spec §G6）。
        if self._left_pane.current_selection():
            self._refresh_center_cards()
        else:
            self._refresh_center_cards(explicit=selection)

    def _maybe_swap_to_vector_backend(
        self,
        *,
        selection: Sequence[SelectedMeasurement] | None = None,
    ) -> bool:
        """Replace the default FakeRecorderBackend with a real Vector
        backend when all preconditions are satisfied.

        Preconditions (all must hold):

        - Current ``self._backend`` is a :class:`FakeRecorderBackend`
          instance. If the caller injected another backend at
          construction time (tests, replay, etc.) we never swap — we
          would break the injection contract.
        - ``self._transport_config`` is set (operator visited Settings).
        - ``self._ifdata_xcp`` is set (operator picked a real A2L).
        - ``self._left_pane._pool`` has at least one MeasurementSummary.

        On a missing precondition: no swap, status bar shows a hard
        ``[FAKE]`` warning so operators don't ship vehicle tests in
        fake mode by accident.

        On a precondition satisfied but Vector construction fails
        (non-Windows, missing python-can, etc.): same hard
        ``[FAKE]`` warning with the underlying reason inline.
        """

        if self._external_backend and not isinstance(self._backend, FakeRecorderBackend):
            return True  # respect caller-injected backend

        if selection is None:
            selection = (
                self._left_pane.current_selection()
                if hasattr(self, "_left_pane")
                else ()
            )

        # Preconditions that operators control.
        missing: list[str] = []
        if self._transport_config is None:
            missing.append("Transport 未配置")
        if self._ifdata_xcp is None:
            missing.append("A2L IF_DATA 未加载")
        if not selection:
            missing.append("measurement selection 为空")
        if not hasattr(self, "_left_pane") or not self._left_pane._pool:
            missing.append("measurement pool 为空")

        if missing:
            self._invalidate_owned_vector_backend()
            if self._allow_fake_backend:
                self._status.showMessage("Demo backend 已启用 · 不录真实 ECU")
                return True
            self._status.showMessage(
                "[FAKE backend] 不录真实 ECU: " + "; ".join(missing)
            )
            self._warn_connection_preconditions(missing)
            return False

        self._invalidate_owned_vector_backend()
        try:
            from mf4_analyzer.acquisition_capture.backends import (
                VectorXcpRecorderBackend,
            )

            measurements = {
                m.name: m for m in self._left_pane._pool
            }
            new_backend = VectorXcpRecorderBackend(
                transport=self._transport_config,
                ifdata=self._ifdata_xcp,
                measurements=measurements,
            )
        except RecorderBackendUnavailableError as exc:
            if self._allow_fake_backend:
                self._status.showMessage(
                    f"Demo backend 已启用 · Vector 不可用：{exc}"
                )
                return True
            self._status.showMessage(
                f"[FAKE backend] Vector 不可用：{exc}"
            )
            self._warn_connection_preconditions([self._status.currentMessage()])
            return False
        except Exception as exc:  # noqa: BLE001 — UI must stay responsive
            if self._allow_fake_backend:
                self._status.showMessage(
                    f"Demo backend 已启用 · Vector 构造失败：{exc}"
                )
                return True
            self._status.showMessage(
                f"[FAKE backend] Vector 构造失败：{exc}"
            )
            self._warn_connection_preconditions([self._status.currentMessage()])
            return False

        self._backend = new_backend
        self._owns_vector_backend = True
        self._update_backend_badge()
        self._status.showMessage(
            f"Vector backend 已就绪 · "
            f"App={self._transport_config.app_name} · "
            f"Ch={self._transport_config.channel}"
        )
        return True

    def _warn_connection_preconditions(self, problems: list[str]) -> None:
        # Runtime sys.modules lookup so test patches on
        # mf4_analyzer.acquisition_ui.main_window.QMessageBox are visible.
        import sys as _sys
        _pkg = _sys.modules.get("mf4_analyzer.acquisition_ui.main_window")
        _QMessageBox = getattr(_pkg, "QMessageBox", None) if _pkg is not None else None
        if _QMessageBox is None:
            _QMessageBox = QMessageBox
        box = _QMessageBox(self)
        box.setIcon(_QMessageBox.Warning)
        box.setWindowTitle("连接 ECU 前置条件")
        box.setText(
            "无法开始真实 ECU 连接：\n\n" + "\n".join(f"• {p}" for p in problems)
        )
        box.setWindowModality(Qt.WindowModal)
        self._connection_warning_box = box
        if self.isVisible():
            box.open()

    # ------------------------------------------------------------------
    # Probes — feed the HealthAggregator from Cockpit state.
    # ------------------------------------------------------------------

    def _probe_hw(self) -> HwHealth:
        # Demo path: simulate a working HW once the user clicks connect.
        if self._allow_fake_backend and (
            self._connection_attempt_started is not None or self._fake_xcp_connected
        ):
            return HwHealth(
                ok=True,
                driver_version="demo-fake",
                channel_count=1,
                last_probe_ts=time.monotonic(),
                error=None,
            )
        if self._transport_config is None:
            return HwHealth(
                ok=False,
                driver_version=None,
                channel_count=0,
                last_probe_ts=time.monotonic(),
                error="transport not configured",
                probed=self._connection_ever_attempted,
            )
        from mf4_analyzer.acquisition_capture.vector_hw_probe import vector_hw_probe

        return vector_hw_probe(self._transport_config)

    def _probe_can(self) -> CanHealth:
        if self._owns_vector_backend:
            status = self._backend.status()
            return CanHealth(
                bus_load_pct=None,
                channels=(),
                bus_error_count=status.bus_error_count,
            )
        return CanHealth(
            bus_load_pct=self._fake_can_load_pct,
            channels=(),
            bus_error_count=0,
        )

    def _probe_xcp(self) -> XcpHealth:
        if self._owns_vector_backend:
            return XcpHealth(
                connected=self._backend.status().started,
                slave_id=None,
                last_response_age_s=None,
                consecutive_timeouts=0,
                attempted=self._connection_ever_attempted,
            )
        return XcpHealth(
            connected=self._fake_xcp_connected,
            slave_id=0x55 if self._fake_xcp_connected else None,
            last_response_age_s=0.0,
            consecutive_timeouts=0,
            attempted=self._connection_ever_attempted,
        )

    def _probe_daq(self) -> DaqHealth:
        if self._owns_vector_backend:
            diagnostics = getattr(self._backend, "diagnostics", lambda: {})()
            overflow: list[str] = []
            if diagnostics.get("frame_overflow_count", 0):
                overflow.append("frame queue overflow")
            if diagnostics.get("sample_overflow_count", 0):
                overflow.append("sample queue overflow")
            capacity = {}
            if self._ifdata_xcp is not None:
                capacity = {
                    event.name: event.max_odt_entries
                    for event in self._ifdata_xcp.available_events
                }
            return DaqHealth(event_capacity=capacity, overflow=tuple(overflow))
        return DaqHealth()

    def _probe_rec(self) -> RecHealth:
        last_age = 0.0
        if self._fake_last_rx_monotonic is None:
            last_age = thresholds.REC_LAST_RX_RED_MIN_S if self._fake_xcp_connected else 0.0
        else:
            last_age = max(0.0, time.monotonic() - self._fake_last_rx_monotonic)
        write_rate = 0.0
        if self._capture_controller is not None and self._fake_rec_state == "recording":
            try:
                count = int(self._capture_controller.writer.write_count)
            except Exception:  # noqa: BLE001 - health probe must stay best-effort
                count = None
            if count is not None:
                now = time.monotonic()
                if self._write_rate_prev is not None:
                    prev_count, prev_ts = self._write_rate_prev
                    dt = now - prev_ts
                    if dt > 0:
                        write_rate = max(0.0, (count - prev_count) / dt)
                self._write_rate_prev = (count, now)
        else:
            self._write_rate_prev = None
        return RecHealth(
            state=self._fake_rec_state,  # type: ignore[arg-type]
            ring_buffer_fill_pct=self._ring.level_pct,
            dropped_frames=self._ring.dropped_frames,
            write_rate_bps=write_rate,
            last_rx_age_s=last_age,
            writer_thread_alive=self._fake_rec_state == "recording",
            evidence=(
                self._fake_last_rx_monotonic is not None
                or self._fake_rec_state != "off"
            ),
        )
