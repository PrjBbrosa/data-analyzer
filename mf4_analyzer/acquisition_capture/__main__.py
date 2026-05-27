"""CLI entry: ``python -m mf4_analyzer.acquisition_capture``.

Capture-first MVP CLI:
- ``--backend {fake,replay,vector}`` — vector requires Vector hardware
  + Windows + ``--a2l`` + transport flags (see ``--help``).
- ``--duration <seconds>`` — required, governs auto-stop.
- ``--output <path>`` — MF4 destination; sidecar JSON lives next to it.
- ``--signals <name>[,<name>...]`` — A2L measurement names (verbatim).
- ``--segment <seconds>`` — optional segment-marker cadence.

Vector-only flags (T1-4):
- ``--a2l <path>`` — A2L file; populates IF_DATA XCP + measurement map.
- ``--app-name <str>`` — Vector application name (default ``Python``).
- ``--channel <int>`` — Vector channel index (default 0).
- ``--bitrate <int>`` — classic CAN bitrate (default 500000).
- ``--can-fd`` — enable CAN-FD; pair with ``--data-bitrate``.
- ``--data-bitrate <int>`` — CAN-FD data-phase bitrate.
- ``--seed-key-dll <path>`` — Seed&Key DLL (optional; required when
  ECU returns ``RESOURCE.DAQ`` locked).

Exit codes:
- ``0`` — MF4 finalized and closed (quality warnings allowed).
- ``2`` — config error.
- ``3`` — writer error.
- ``4`` — capture exception.
- ``5`` — sidecar write error.
- ``6`` — vector backend construction error (driver / app / Windows).

Ctrl-C performs a clean stop/flush. Vector / pyxcp / python-can are
NOT imported at module import time (lazy inside ``VectorXcpRecorderBackend``).
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from mf4_analyzer.acquisition_capture.backends import (
    FakeRecorderBackend,
    RecorderBackend,
    RecorderBackendUnavailableError,
    ReplayRecorderBackend,
)
from mf4_analyzer.acquisition_capture.controller import CaptureController
from mf4_analyzer.acquisition_capture.session import (
    SelectedMeasurement,
    SessionConfig,
)
from mf4_analyzer.acquisition_capture.transport_config import TransportConfig
from mf4_analyzer.acquisition_capture.writer import Mf4WriterError


_DATATYPE_PAYLOAD_BYTES = {
    "UBYTE": 1,
    "SBYTE": 1,
    "UWORD": 2,
    "SWORD": 2,
    "ULONG": 4,
    "SLONG": 4,
    "A_UINT64": 8,
    "A_INT64": 8,
    "FLOAT32_IEEE": 4,
    "FLOAT64_IEEE": 8,
    "u8": 1,
    "s8": 1,
    "u16": 2,
    "s16": 2,
    "u32": 4,
    "s32": 4,
    "f32": 4,
    "u64": 8,
    "s64": 8,
    "f64": 8,
}


def _parse_signals(spec: str) -> tuple[SelectedMeasurement, ...]:
    names = [tok.strip() for tok in spec.split(",") if tok.strip()]
    if not names:
        raise argparse.ArgumentTypeError("--signals requires at least one name")
    return tuple(SelectedMeasurement(name=n) for n in names)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mf4_analyzer.acquisition_capture",
        description=(
            "Capture-first MVP CLI for the Acquisition Cockpit. "
            "Runs a fake/replay backend, writes a finalized MF4, and "
            "emits a <basename>.session_summary.json sidecar next to it."
        ),
    )
    parser.add_argument(
        "--backend",
        choices=("fake", "replay", "vector"),
        default="fake",
        help=(
            "recorder backend. 'vector' requires Windows + Vector hardware "
            "and the --a2l / --app-name / --channel / --bitrate flags."
        ),
    )
    parser.add_argument(
        "--a2l",
        type=Path,
        default=None,
        help="A2L file (required when --backend vector)",
    )
    parser.add_argument(
        "--app-name",
        type=str,
        default="Python",
        help="Vector application name (default 'Python')",
    )
    parser.add_argument(
        "--channel",
        type=int,
        default=0,
        help="Vector channel index (default 0)",
    )
    parser.add_argument(
        "--bitrate",
        type=int,
        default=500000,
        help="classic CAN bitrate (default 500000)",
    )
    parser.add_argument(
        "--can-fd",
        action="store_true",
        default=False,
        help="enable CAN-FD",
    )
    parser.add_argument(
        "--data-bitrate",
        type=int,
        default=2000000,
        help="CAN-FD data-phase bitrate (only used with --can-fd)",
    )
    parser.add_argument(
        "--seed-key-dll",
        type=Path,
        default=None,
        help="Seed&Key DLL path (only required when ECU RESOURCE.DAQ is locked)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        required=True,
        help="capture duration in seconds (governs auto-stop)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="output MF4 path (must end with .mf4)",
    )
    parser.add_argument(
        "--signals",
        type=_parse_signals,
        default=_parse_signals("EngineSpeed,Throttle,Steering"),
        help="comma-separated A2L measurement names (default: 3 synthetic signals)",
    )
    parser.add_argument(
        "--segment",
        type=float,
        default=None,
        help="optional segment marker cadence in seconds",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.05,
        help="capture-loop poll interval in seconds (default 50 ms)",
    )
    return parser


def _payload_bytes_for_datatype(datatype: str, fallback: int) -> int:
    if datatype in _DATATYPE_PAYLOAD_BYTES:
        return _DATATYPE_PAYLOAD_BYTES[datatype]
    upper = datatype.upper()
    if upper in _DATATYPE_PAYLOAD_BYTES:
        return _DATATYPE_PAYLOAD_BYTES[upper]
    lower = datatype.lower()
    if lower in _DATATYPE_PAYLOAD_BYTES:
        return _DATATYPE_PAYLOAD_BYTES[lower]
    return fallback


def _event_rate_hz(cycle_time_ms: float, fallback: float) -> float:
    if cycle_time_ms <= 0:
        return fallback
    return 1000.0 / cycle_time_ms


def _bind_vector_selected(
    selected: Sequence[SelectedMeasurement],
    *,
    summary,
    ifdata,
) -> tuple[SelectedMeasurement, ...]:
    """Resolve CLI-selected names into DAQ-ready measurements."""

    measurements = {m.name: m for m in summary.measurements}
    event_by_name = {event.name: event for event in ifdata.available_events}
    bound: list[SelectedMeasurement] = []
    for sel in selected:
        measurement = measurements.get(sel.name)
        if measurement is None:
            raise SystemExit(
                f"signal {sel.name!r} not found in A2L summary; "
                "cannot start vector capture"
            )
        if not measurement.available_events:
            raise SystemExit(
                f"signal {sel.name!r} has no available DAQ event in A2L summary; "
                "cannot start vector capture"
            )
        event_name = next(
            (event for event in measurement.available_events if event in event_by_name),
            None,
        )
        if event_name is None:
            summary_events = ", ".join(repr(event) for event in measurement.available_events)
            ifdata_events = ", ".join(repr(event) for event in event_by_name) or "<none>"
            raise SystemExit(
                f"signal {sel.name!r} available event(s) {summary_events} "
                f"not in IF_DATA available_events ({ifdata_events}); "
                "cannot start vector capture"
            )
        event_info = event_by_name[event_name]
        bound.append(
            SelectedMeasurement(
                name=sel.name,
                unit=measurement.unit or sel.unit,
                event=event_name,
                event_rate_hz=_event_rate_hz(
                    float(event_info.cycle_time_ms),
                    sel.event_rate_hz,
                ),
                payload_bytes=_payload_bytes_for_datatype(
                    str(measurement.datatype or ""),
                    sel.payload_bytes,
                ),
                address_hex=f"0x{int(measurement.address):08X}",
            )
        )
    return tuple(bound)


def _make_backend(args: argparse.Namespace) -> RecorderBackend:
    name = args.backend
    if name == "fake":
        return FakeRecorderBackend()
    if name == "replay":
        return ReplayRecorderBackend()
    if name == "vector":
        return _make_vector_backend(args)
    # argparse choices guard upstream, but keep this explicit.
    raise SystemExit(f"unknown backend: {name}")


def _make_vector_backend(args: argparse.Namespace) -> RecorderBackend:
    """Construct a :class:`VectorXcpRecorderBackend` from CLI args.

    Lazy-imports the backend so non-vector invocations don't drag in
    ``python-can`` / ``pyxcp``. Raises :class:`SystemExit(6)` with a
    user-readable message on any precondition failure — that exit code
    is reserved for "vector backend construction" so operators can
    distinguish "config" (2) from "couldn't reach hardware" (6).
    """

    if args.a2l is None:
        raise SystemExit("--backend vector requires --a2l <path>")
    if not args.a2l.exists():
        raise SystemExit(f"--a2l file not found: {args.a2l}")

    from mf4_analyzer.acquisition_capture.backends import VectorXcpRecorderBackend
    from can_logger.p0.a2l_probe import load_measurement_summary
    from can_logger.p0.ifdata_xcp import parse_ifdata_xcp_file

    try:
        summary = load_measurement_summary(str(args.a2l), limit=None)
    except Exception as exc:  # noqa: BLE001 - reporter
        raise SystemExit(f"A2L parse failed: {exc}") from exc

    try:
        ifdata_blocks = parse_ifdata_xcp_file(args.a2l)
    except Exception as exc:  # noqa: BLE001 - reporter
        raise SystemExit(f"A2L IF_DATA parse failed: {exc}") from exc
    if not ifdata_blocks:
        raise SystemExit(
            f"A2L {args.a2l} has no usable IF_DATA XCP block "
            "(parser may have rejected an XCPplus-only ECU; see followup report)"
        )
    ifdata = ifdata_blocks[0]

    transport = TransportConfig(
        app_name=args.app_name,
        channel=args.channel,
        bitrate=args.bitrate,
        can_fd=args.can_fd,
        data_bitrate=args.data_bitrate,
        seed_and_key_dll=(str(args.seed_key_dll) if args.seed_key_dll else None),
    )
    measurements = {m.name: m for m in summary.measurements}
    args.signals = _bind_vector_selected(
        args.signals,
        summary=summary,
        ifdata=ifdata,
    )

    try:
        return VectorXcpRecorderBackend(
            transport=transport,
            ifdata=ifdata,
            measurements=measurements,
        )
    except RecorderBackendUnavailableError as exc:
        raise SystemExit(f"vector backend unavailable: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - construction reporter
        raise SystemExit(f"vector backend init failed: {exc}") from exc


def _make_session_config(args: argparse.Namespace) -> SessionConfig:
    return SessionConfig(
        output_mf4=Path(args.output),
        selected=args.signals,
        duration_s=float(args.duration),
        backend=args.backend,
        segment_seconds=args.segment,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        config = _make_session_config(args)
    except ValueError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    try:
        backend = _make_backend(args)
    except SystemExit as exc:
        # _make_vector_backend raises SystemExit(6 / message) on hardware
        # / A2L / driver problems. Map message-only SystemExits to 6.
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 6
        raise
    if args.backend == "vector" and config.selected != args.signals:
        try:
            config = _make_session_config(args)
        except ValueError as exc:
            print(f"config error: {exc}", file=sys.stderr)
            return 2
    controller = CaptureController(config, backend)

    # Ctrl-C → clean stop. Re-raising on second Ctrl-C lets the user
    # force-quit; first Ctrl-C just flips the loop predicate.
    stop_requested = {"v": False}

    def _on_sigint(signum, frame):  # noqa: ARG001
        if stop_requested["v"]:
            raise KeyboardInterrupt
        stop_requested["v"] = True

    previous_handler = signal.signal(signal.SIGINT, _on_sigint)

    try:
        controller.start()
        while controller.running and not stop_requested["v"]:
            controller.poll_step()
            time.sleep(args.poll_interval)
        summary = controller.stop()
    except Mf4WriterError as exc:
        print(f"writer error: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 - last-chance reporter
        print(f"capture failed: {exc}", file=sys.stderr)
        return 4
    finally:
        signal.signal(signal.SIGINT, previous_handler)

    try:
        sidecar = summary.write_sidecar(config.output_mf4)
    except OSError as exc:
        print(f"sidecar write error: {exc}", file=sys.stderr)
        return 5

    # Quality warnings DO NOT fail the run — spec §Capture-First Cut.
    print(
        "capture done: "
        f"mf4={summary.output_mf4} sidecar={sidecar} "
        f"duration_s={summary.duration_s:.3f} "
        f"rx={summary.rx_count} write={summary.write_count} "
        f"dropped={summary.dropped_frames} "
        f"warnings={len(summary.warnings)}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry
    raise SystemExit(main())
