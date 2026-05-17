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
    from can.interfaces.vector import canlib  # type: ignore[import-not-found]

    return canlib


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


def vector_hw_probe(transport: TransportConfig) -> HwHealth:
    if not sys.platform.startswith("win"):
        return _hw(
            ok=False,
            error="Vector backend requires Windows",
            driver_version=None,
            channel_count=0,
        )

    try:
        canlib = _load_vector_canlib()
    except Exception as exc:  # noqa: BLE001 - driver load surface
        return _hw(
            ok=False,
            error=f"vxlapi DLL not loadable: {exc}",
            driver_version=None,
            channel_count=0,
        )

    try:
        cfg = canlib.get_application_config(transport.app_name)
    except LookupError as exc:
        return _hw(
            ok=False,
            error=(
                f"Vector application {transport.app_name!r} not configured "
                f"({exc})"
            ),
            driver_version=None,
            channel_count=0,
        )
    except Exception as exc:  # noqa: BLE001 - driver API surface
        return _hw(
            ok=False,
            error=f"get_application_config failed: {exc}",
            driver_version=None,
            channel_count=0,
        )

    try:
        channel_count = int(canlib.get_channel_count())
    except Exception:  # noqa: BLE001 - keep app probe result visible
        channel_count = 0

    driver_version = getattr(cfg, "driver_version", None)
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


def _open_vector_bus(transport: TransportConfig):
    import can  # type: ignore[import-not-found]

    kwargs = {
        "interface": "vector",
        "app_name": transport.app_name,
        "channel": transport.channel,
        "bitrate": transport.bitrate,
        "fd": transport.can_fd,
    }
    if transport.can_fd:
        kwargs["data_bitrate"] = transport.data_bitrate
    return can.Bus(**kwargs)


def _make_pyxcp_master(bus, transport: TransportConfig):
    from pyxcp.master import Master  # type: ignore[import-not-found]

    return Master("can", config={"bus": bus, "timeout": transport.timeout_s})


def test_xcp_connection(
    transport: TransportConfig,
    ifdata: IfDataXcp,
) -> TestXcpConnectionResult:
    bus = None
    try:
        try:
            bus = _open_vector_bus(transport)
        except Exception as exc:  # noqa: BLE001 - surface driver error
            return TestXcpConnectionResult(
                ok=False,
                resource_byte=None,
                latency_ms=None,
                error=f"CAN 总线打开失败：{exc}",
            )

        master = _make_pyxcp_master(bus, transport)
        started = time.monotonic()
        try:
            response = master.connect()
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

        try:
            master.disconnect()
        except Exception:  # noqa: BLE001 - connection already proven
            pass
        return TestXcpConnectionResult(
            ok=True,
            resource_byte=resource,
            latency_ms=latency_ms,
            error=None,
        )
    finally:
        if bus is not None:
            try:
                bus.shutdown()
            except Exception:  # noqa: BLE001 - best-effort cleanup
                pass
