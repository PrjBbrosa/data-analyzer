"""Vector hardware health probe and XCP connection smoke probe."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

from can_logger.p0.ifdata_xcp import IfDataXcp
from mf4_analyzer.acquisition_capture.health import HwHealth
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
from mf4_analyzer.acquisition_capture.xcp_auth import (
    XcpAuthError,
    unlock_resources_if_needed,
)


@dataclass(frozen=True)
class TestXcpConnectionResult:
    ok: bool
    resource_byte: int | None
    latency_ms: int | None
    error: str | None


def _load_vector_canlib():
    """Return the python-can ``vector`` package object.

    Historically this returned the ``canlib`` submodule and callers
    reached for ``canlib.get_application_config`` / ``canlib.get_channel_count``
    — neither attribute has ever existed at module level in python-can.
    The real surface is ``VectorBus.get_application_config(app, channel)``
    (a ``@staticmethod``) and ``vector.get_channel_configs()``. We now
    return the package so the caller can access both via the documented
    public API.
    """

    from can.interfaces import vector  # type: ignore[import-not-found]

    return vector


def _hw(
    *,
    ok: bool,
    error: str | None,
    driver_version: str | None,
    channel_count: int,
) -> HwHealth:
    return HwHealth(
        ok=ok,
        driver_version=driver_version,
        channel_count=channel_count,
        last_probe_ts=time.monotonic(),
        error=error,
    )


def _decode_dll_version(packed: int) -> str | None:
    """Decode ``XLdriverConfig.dllVersion`` into ``"major.minor.build"``.

    The Vector XL API packs the version as
    ``major << 24 | minor << 16 | build`` (16 low bits). See
    ``XL Driver Library Description`` §xlGetDriverConfig.
    """

    if not isinstance(packed, int) or packed <= 0:
        return None
    major = (packed >> 24) & 0xFF
    minor = (packed >> 16) & 0xFF
    build = packed & 0xFFFF
    return f"{major}.{minor}.{build}"


def _read_driver_version(vector_pkg) -> str | None:
    try:
        cfg = vector_pkg.canlib._get_xl_driver_config()
    except Exception:  # noqa: BLE001 - best-effort; version is informational
        return None
    return _decode_dll_version(int(getattr(cfg, "dllVersion", 0)))


def vector_hw_probe(transport: TransportConfig) -> HwHealth:
    if not sys.platform.startswith("win"):
        return _hw(
            ok=False,
            error="Vector backend requires Windows",
            driver_version=None,
            channel_count=0,
        )

    try:
        vector_pkg = _load_vector_canlib()
    except Exception as exc:  # noqa: BLE001 - driver load surface
        return _hw(
            ok=False,
            error=f"vxlapi DLL not loadable: {exc}",
            driver_version=None,
            channel_count=0,
        )

    # Enumerate hardware channels first — this also exercises the driver,
    # so a totally broken DLL surface fails fast here rather than later.
    try:
        channel_configs = vector_pkg.get_channel_configs()
    except Exception as exc:  # noqa: BLE001 - driver API surface
        return _hw(
            ok=False,
            error=f"get_channel_configs failed: {exc}",
            driver_version=None,
            channel_count=0,
        )
    channel_count = len(channel_configs)
    driver_version = _read_driver_version(vector_pkg)

    # Confirm the requested app slot + channel is mapped to hardware. This
    # is the same lookup ``can.Bus(interface="vector", app_name=..., channel=...)``
    # runs internally; failing here gives a clearer error than waiting for
    # bus open to fall over.
    try:
        from can.interfaces.vector import (  # type: ignore[import-not-found]
            VectorBus,
        )
        from can.interfaces.vector.exceptions import (  # type: ignore[import-not-found]
            VectorInitializationError,
        )
    except Exception as exc:  # noqa: BLE001 - python-can absent / API moved
        return _hw(
            ok=False,
            error=f"python-can vector backend unavailable: {exc}",
            driver_version=driver_version,
            channel_count=channel_count,
        )

    try:
        VectorBus.get_application_config(transport.app_name, transport.channel)
    except VectorInitializationError as exc:
        return _hw(
            ok=False,
            error=(
                f"Vector application {transport.app_name!r} channel "
                f"{transport.channel} not mapped to hardware: {exc}"
            ),
            driver_version=driver_version,
            channel_count=channel_count,
        )
    except Exception as exc:  # noqa: BLE001 - driver API surface
        return _hw(
            ok=False,
            error=f"VectorBus.get_application_config failed: {exc}",
            driver_version=driver_version,
            channel_count=channel_count,
        )

    if transport.channel >= channel_count:
        return _hw(
            ok=False,
            error=f"channel {transport.channel} not present (count={channel_count})",
            driver_version=driver_version,
            channel_count=channel_count,
        )

    return _hw(
        ok=True,
        error=None,
        driver_version=driver_version,
        channel_count=channel_count,
    )


def test_xcp_connection(
    transport: TransportConfig,
    ifdata: IfDataXcp,
) -> TestXcpConnectionResult:
    runtime = None
    try:
        try:
            from mf4_analyzer.acquisition_capture.pyxcp_runtime import PyXcpRuntime

            runtime = PyXcpRuntime.open(transport, ifdata)
        except Exception as exc:  # noqa: BLE001 - surface driver error
            return TestXcpConnectionResult(
                ok=False,
                resource_byte=None,
                latency_ms=None,
                error=f"pyxcp Vector runtime init failed: {exc}",
            )
        master = runtime.master
        started = time.monotonic()
        try:
            response = runtime.connect()
        except TimeoutError as exc:
            return TestXcpConnectionResult(
                ok=False,
                resource_byte=None,
                latency_ms=None,
                error=(
                    f"ECU 未在 {int(transport.timeout_s * 1000)} ms 内响应 "
                    f"(cmd_id=0x{ifdata.cmd_id:03X}): {exc}"
                ),
            )
        except Exception as exc:  # noqa: BLE001 - pyxcp error surface
            return TestXcpConnectionResult(
                ok=False,
                resource_byte=None,
                latency_ms=None,
                error=f"XCP CONNECT 失败：{exc}",
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        resource = int(getattr(response, "resource", 0) or 0)

        if transport.seed_and_key_dll:
            try:
                unlock_resources_if_needed(
                    master=master,
                    connect_response=response,
                    seed_and_key_dll=transport.seed_and_key_dll,
                )
            except XcpAuthError as exc:
                try:
                    master.disconnect()
                except Exception:  # noqa: BLE001 - best-effort cleanup
                    pass
                return TestXcpConnectionResult(
                    ok=False,
                    resource_byte=resource,
                    latency_ms=latency_ms,
                    error=f"Seed&Key 失败：{exc}",
                )

        return TestXcpConnectionResult(
            ok=True,
            resource_byte=resource,
            latency_ms=latency_ms,
            error=None,
        )
    finally:
        if runtime is not None:
            try:
                runtime.close()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
