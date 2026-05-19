"""Vector hardware access probe — Windows-only.

Four-stage layered diagnostic, each failure carries its own exit code
so the action board's failure-triage table maps 1:1 to the operator's
console.

Exit codes (T3-3):

- ``0``  — all four stages green.
- ``1``  — vxlapi DLL not loadable. Vector Hardware Configurator install
           is missing or broken.
- ``2``  — Vector application name (``--app-name``) not configured in
           Vector Hardware Config. Operator must create the slot.
- ``3``  — Requested channel index not present on the configured HW.
- ``4``  — CAN bus open failed (driver / bitrate / hardware contention).
- ``9``  — Uncategorized exception (printed verbatim).
- ``10`` — Not Windows. Operator ran this on the wrong machine; the
           Vector backend cannot work off Windows.

python-can is imported lazily so this module can be imported on
macOS/Linux for static checks without the Vector driver.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Exit codes — keep the numbers stable; the action board references them.
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_DRIVER = 1
EXIT_APP = 2
EXIT_CHANNEL = 3
EXIT_BUS = 4
EXIT_UNCATEGORIZED = 9
EXIT_NOT_WINDOWS = 10


@dataclass(frozen=True)
class StageResult:
    """One probe stage outcome.

    ``ok`` decides whether the cascade continues. ``label`` is the line
    prefix printed for the operator; ``detail`` is the human-readable
    summary appended to that line. ``error`` is non-empty only when
    ``ok`` is False.
    """

    label: str
    ok: bool
    detail: str
    error: str = ""


@dataclass(frozen=True)
class ProbeReport:
    """Full layered result returned by :func:`probe_stages`.

    ``failed_stage`` is the first non-OK stage label, or ``None`` when
    everything passed. ``exit_code`` is the resolved exit code.
    """

    stages: list[StageResult] = field(default_factory=list)
    failed_stage: str | None = None
    exit_code: int = EXIT_OK


# ---------------------------------------------------------------------------
# Public helpers (kept for back-compat with prior callers / tests).
# ---------------------------------------------------------------------------


def _ensure_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError(
            "Vector interface is only supported on Windows; current platform: "
            f"{sys.platform}"
        )


def list_vector_channels() -> list:
    _ensure_windows()
    from can.interfaces import vector  # type: ignore[import-not-found]

    return list(vector.get_channel_configs())


def open_vector_bus(*, channel: int, bitrate: int, app_name: str):
    _ensure_windows()
    import can  # type: ignore[import-not-found]

    return can.Bus(
        interface="vector", channel=channel, bitrate=bitrate, app_name=app_name
    )


# ---------------------------------------------------------------------------
# Stage probes.
#
# Each stage is a thin wrapper around the public helper, designed for
# patching in tests. Each catches the specific exception class
# corresponding to that stage's failure mode and downgrades to a
# StageResult so the cascade can keep recording — we still want to know
# whether channels enumerate after a DLL load even if it failed.
# ---------------------------------------------------------------------------


def _stage_driver() -> StageResult:
    """Stage 1: load/open the Vector XL driver via python-can's canlib."""

    try:
        from can.interfaces import vector  # type: ignore[import-not-found]

        canlib = vector.canlib  # type: ignore[attr-defined]
        xldriver = getattr(canlib, "xldriver", None)
        if xldriver is None:
            raise RuntimeError("Vector API has not been loaded")
        xldriver.xlOpenDriver()
        xldriver.xlCloseDriver()
    except Exception as exc:  # noqa: BLE001 - driver load surface
        return StageResult(
            label="[stage1/driver]",
            ok=False,
            detail="loadable=false",
            error=f"vxlapi DLL not loadable: {exc}",
        )
    return StageResult(
        label="[stage1/driver]",
        ok=True,
        detail="loadable=true",
    )


def _stage_app(app_name: str) -> StageResult:
    """Stage 2: confirm the Vector application name is configured."""

    try:
        from can.interfaces import vector  # type: ignore[import-not-found]

        canlib = vector.canlib  # type: ignore[attr-defined]
        cfg = canlib.get_application_config(app_name)
    except LookupError as exc:
        return StageResult(
            label="[stage2/app]",
            ok=False,
            detail=f'name="{app_name}"  configured=false',
            error=f"application {app_name!r} not configured: {exc}",
        )
    except AttributeError as exc:
        # Older python-can versions expose canlib differently.
        return StageResult(
            label="[stage2/app]",
            ok=False,
            detail=f'name="{app_name}"  configured=unknown',
            error=f"python-can vector.canlib surface unavailable: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 - driver surface
        return StageResult(
            label="[stage2/app]",
            ok=False,
            detail=f'name="{app_name}"  configured=false',
            error=f"get_application_config failed: {exc}",
        )

    hw = getattr(cfg, "hw_type", "?")
    driver = getattr(cfg, "driver_version", "?")
    return StageResult(
        label="[stage2/app]",
        ok=True,
        detail=f'name="{app_name}"  configured=true  hw={hw}  driver={driver}',
    )


def _stage_channel(channel_index: int) -> StageResult:
    """Stage 3: confirm the requested channel index is present."""

    try:
        channels = list_vector_channels()
    except Exception as exc:  # noqa: BLE001 - driver surface
        return StageResult(
            label="[stage3/channel]",
            ok=False,
            detail=f"index={channel_index}  present=unknown",
            error=f"list channels failed: {exc}",
        )

    count = len(channels)
    present = 0 <= channel_index < count
    if not present:
        return StageResult(
            label="[stage3/channel]",
            ok=False,
            detail=f"index={channel_index}  present=false  count={count}",
            error=f"channel {channel_index} not present (count={count})",
        )
    return StageResult(
        label="[stage3/channel]",
        ok=True,
        detail=f"index={channel_index}  present=true  count={count}",
    )


def _stage_bus(*, channel: int, bitrate: int, app_name: str) -> StageResult:
    """Stage 4: actually open + close the CAN bus."""

    try:
        bus = open_vector_bus(channel=channel, bitrate=bitrate, app_name=app_name)
    except Exception as exc:  # noqa: BLE001 - driver surface
        return StageResult(
            label="[stage4/bus]",
            ok=False,
            detail=f"open=false  bitrate={bitrate}",
            error=f"bus open failed: {exc}",
        )
    try:
        bus.shutdown()
    except Exception:  # noqa: BLE001 - best-effort cleanup
        pass
    return StageResult(
        label="[stage4/bus]",
        ok=True,
        detail=f"open=true  bitrate={bitrate}",
    )


# ---------------------------------------------------------------------------
# Orchestration.
# ---------------------------------------------------------------------------


def probe_stages(
    *, channel: int, bitrate: int, app_name: str, open_bus: bool
) -> ProbeReport:
    """Run all four stages and aggregate the outcome.

    Each stage runs independently — stage 1 driver failure does NOT
    short-circuit stage 2/3/4, because the operator wants the full
    layered picture (e.g. "driver missing AND channel out of range").
    The ``exit_code`` is the first failed stage's code; ``stages``
    holds every result.
    """

    stages: list[StageResult] = []
    stages.append(_stage_driver())
    stages.append(_stage_app(app_name))
    stages.append(_stage_channel(channel))
    if open_bus:
        stages.append(
            _stage_bus(channel=channel, bitrate=bitrate, app_name=app_name)
        )

    code_for_label = {
        "[stage1/driver]": EXIT_DRIVER,
        "[stage2/app]": EXIT_APP,
        "[stage3/channel]": EXIT_CHANNEL,
        "[stage4/bus]": EXIT_BUS,
    }
    failed_label: str | None = None
    exit_code = EXIT_OK
    for stage in stages:
        if not stage.ok:
            failed_label = stage.label
            exit_code = code_for_label.get(stage.label, EXIT_UNCATEGORIZED)
            break

    return ProbeReport(
        stages=stages,
        failed_stage=failed_label,
        exit_code=exit_code,
    )


def _print_report(report: ProbeReport, out: Any = None) -> None:
    """Pretty-print the report; writes to stdout by default."""

    stream = out if out is not None else sys.stdout
    for stage in report.stages:
        line = f"{stage.label}  {stage.detail}"
        if stage.error:
            line += f"  error={stage.error}"
        print(line, file=stream)
    if report.failed_stage is None:
        print("result: all_green", file=stream)
    else:
        print(
            f"result: stage_failed={report.failed_stage}  exit_code={report.exit_code}",
            file=stream,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Layered Vector hardware probe. Each failure stage exits "
            "with its own non-zero code so the bench-side operator can "
            "triage without log spelunking."
        )
    )
    parser.add_argument("--channel", type=int, default=0)
    parser.add_argument("--bitrate", type=int, default=500000)
    parser.add_argument("--app-name", default="Python")
    parser.add_argument(
        "--open",
        action="store_true",
        help="Also try to open the bus (stage 4). Off by default so dry-run probes don't grab the bus.",
    )
    args = parser.parse_args(argv)

    if sys.platform != "win32":
        print(
            "[stage0/platform]  windows=false  detected="
            f"{sys.platform}  (Vector backend requires Windows)",
            file=sys.stderr,
        )
        return EXIT_NOT_WINDOWS

    try:
        report = probe_stages(
            channel=args.channel,
            bitrate=args.bitrate,
            app_name=args.app_name,
            open_bus=args.open,
        )
    except Exception as exc:  # noqa: BLE001 - last-resort reporter
        print(
            f"[probe/uncategorized]  ok=false  error={exc}",
            file=sys.stderr,
        )
        return EXIT_UNCATEGORIZED

    _print_report(report)
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover - module entry
    raise SystemExit(main())
