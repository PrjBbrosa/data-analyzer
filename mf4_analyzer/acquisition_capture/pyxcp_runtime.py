"""Pinned pyxcp 0.29.14 runtime construction for Vector XCP sessions.

Only this module knows how the application maps a ``TransportConfig`` and A2L
``IF_DATA XCP`` facts into pyxcp's configuration object.  It intentionally has
no module-level pyxcp import: optional native imports remain behind the
existing isolated subprocess probe.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any

from can_logger.p0.ifdata_xcp import IfDataXcp
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig


class PyXcpRuntimeError(RuntimeError):
    """The installed pyxcp runtime cannot satisfy the pinned contract."""


class DiscardDaqPolicy:
    """Structural policy for short Test Connection sessions.

    pyxcp 0.29 transports require only an object with ``feed`` and an
    ``xcp_master`` attribute.  Live capture replaces this with
    ``BoundedDaqPolicy``; Test Connection deliberately discards any incidental
    DAQ traffic.
    """

    xcp_master: Any | None = None

    def feed(self, _category: Any, _counter: int, _timestamp: int, _payload: bytes) -> None:
        return

    def finalize(self) -> None:
        return


@dataclass
class PyXcpRuntime:
    """One pyxcp-owned CAN transport and its Master instance."""

    master: Any
    application: Any
    policy: Any
    _connected: bool = False
    _closed: bool = False

    @classmethod
    def open(
        cls,
        transport: TransportConfig,
        ifdata: IfDataXcp,
        policy: Any | None = None,
    ) -> "PyXcpRuntime":
        """Construct the pinned CAN/Vector runtime without a caller-owned bus."""

        surface = _load_pyxcp_surface()
        policy = policy if policy is not None else DiscardDaqPolicy()
        application = _build_application(surface.create_application_from_config, transport, ifdata)
        try:
            master = surface.Master("can", config=application, policy=policy)
        except Exception as exc:  # noqa: BLE001 - preserve vendor exception context
            raise PyXcpRuntimeError(f"pyxcp 0.29 Master construction failed: {exc}") from exc
        return cls(master=master, application=application, policy=policy)

    def connect(self) -> Any:
        if self._closed:
            raise PyXcpRuntimeError("cannot CONNECT a closed pyxcp runtime")
        response = self.master.connect()
        self._connected = True
        return response

    def disconnect(self) -> None:
        if self._closed or not self._connected:
            return
        try:
            self.master.disconnect()
        finally:
            self._connected = False

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.disconnect()
        finally:
            try:
                finalize = getattr(self.policy, "finalize", None)
                if callable(finalize):
                    finalize()
            finally:
                close = getattr(getattr(self.master, "transport", None), "close", None)
                if callable(close):
                    close()
                self._closed = True

    def diagnostics(self) -> dict[str, Any]:
        can = self.application.transport.can
        return {
            "transport": "CAN",
            "interface": can.interface,
            "app_name": can.vector.app_name,
            "channel": can.channel,
            "bitrate": can.bitrate,
            "data_bitrate": can.data_bitrate if can.fd else None,
            "can_fd": bool(can.fd),
            "sample_point_applied": False,
            "timing_source": "driver_automatic",
            "command_id": can.can_id_master,
            "response_id": can.can_id_slave,
            "timeout_s": self.application.transport.timeout,
            "connected": self._connected,
            "closed": self._closed,
        }


@dataclass(frozen=True)
class _PyXcpSurface:
    Master: Any
    create_application_from_config: Any


def _load_pyxcp_surface() -> _PyXcpSurface:
    """Run the native-import probe, then dynamically load the pinned surface."""

    from mf4_analyzer.acquisition_capture.backends import _ensure_pyxcp_import_safe

    _ensure_pyxcp_import_safe()
    try:
        master_module = importlib.import_module("py" + "xcp.master")
        config_module = importlib.import_module("py" + "xcp.config")
    except Exception as exc:  # noqa: BLE001 - native package surface
        raise PyXcpRuntimeError(f"pyxcp 0.29 import failed: {exc}") from exc
    return _PyXcpSurface(
        Master=master_module.Master,
        create_application_from_config=config_module.create_application_from_config,
    )


def _canonical_can_id(identifier: int, extended: bool) -> int:
    """Encode pyxcp's bit-31 extended-ID convention from parsed A2L facts."""

    raw = int(identifier)
    if raw < 0:
        raise PyXcpRuntimeError(f"negative CAN identifier: {raw}")
    if extended:
        if raw > 0x1FFFFFFF:
            raise PyXcpRuntimeError(f"extended CAN identifier out of range: 0x{raw:X}")
        return raw | 0x80000000
    if raw > 0x7FF:
        raise PyXcpRuntimeError(f"standard CAN identifier out of range: 0x{raw:X}")
    return raw


def _build_application(factory: Any, transport: TransportConfig, ifdata: IfDataXcp) -> Any:
    """Create one real pyxcp configuration object with explicit CAN mapping."""

    if transport.sample_point != 75.0 or transport.fd_sample_point != 70.0:
        raise PyXcpRuntimeError(
            "custom sample points are not applied by the pinned pyxcp Vector "
            "runtime; timing_source is driver automatic. Reset legacy values "
            f"to sample_point=75.0/fd_sample_point=70.0 (got "
            f"sample_point={transport.sample_point}, "
            f"fd_sample_point={transport.fd_sample_point})"
        )

    # pyxcp 0.29.14's General.seed_n_key_dll is a non-null Unicode trait.
    # Keep TransportConfig's user-facing None semantics, but never feed None to
    # the real trait/config factory.
    seed_and_key_dll = (
        str(transport.seed_and_key_dll) if transport.seed_and_key_dll else ""
    )
    app = factory(
        {
            "Transport": {
                "CAN": {
                    "interface": "vector",
                    "channel": str(transport.channel),
                    "bitrate": int(transport.bitrate),
                    "fd": bool(transport.can_fd),
                    "data_bitrate": int(transport.data_bitrate) if transport.can_fd else None,
                    "can_id_master": _canonical_can_id(ifdata.cmd_id, ifdata.cmd_id_extended),
                    "can_id_slave": _canonical_can_id(ifdata.resp_id, ifdata.resp_id_extended),
                }
            },
            "General": {"seed_n_key_dll": seed_and_key_dll},
        }
    )
    # ``create_application_from_config`` builds components before applying the
    # mapping, so layer/vector-specific traits remain explicit assignments.
    app.transport.layer = "CAN"
    app.transport.timeout = float(transport.timeout_s)
    app.transport.can.interface = "vector"
    app.transport.can.channel = str(transport.channel)
    app.transport.can.bitrate = int(transport.bitrate)
    app.transport.can.fd = bool(transport.can_fd)
    app.transport.can.data_bitrate = int(transport.data_bitrate) if transport.can_fd else None
    app.transport.can.can_id_master = _canonical_can_id(ifdata.cmd_id, ifdata.cmd_id_extended)
    app.transport.can.can_id_slave = _canonical_can_id(ifdata.resp_id, ifdata.resp_id_extended)
    app.transport.can.vector.app_name = transport.app_name
    app.general.seed_n_key_dll = seed_and_key_dll
    return app
