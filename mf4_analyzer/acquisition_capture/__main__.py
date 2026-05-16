"""CLI entry: ``python -m mf4_analyzer.acquisition_capture``.

Stage 2 CLI-first MVP per plan line ~167 ("Capture-First Cut"):
- ``--backend {fake,replay}`` — Vector path is gated to Stage 8.
- ``--duration <seconds>`` — required, governs auto-stop.
- ``--output <path>`` — MF4 destination; sidecar JSON lives next to it.
- ``--signals <name>[,<name>...]`` — A2L measurement names (verbatim).
- ``--segment <seconds>`` — optional segment-marker cadence.

Exit codes:
- ``0`` — MF4 finalized and closed (quality warnings allowed).
- non-zero — writer / config / file-IO failure.

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
    ReplayRecorderBackend,
)
from mf4_analyzer.acquisition_capture.controller import CaptureController
from mf4_analyzer.acquisition_capture.session import (
    SelectedMeasurement,
    SessionConfig,
)
from mf4_analyzer.acquisition_capture.writer import Mf4WriterError


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
        choices=("fake", "replay"),
        default="fake",
        help="recorder backend (vector path is Stage-8 gated)",
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


def _make_backend(name: str) -> RecorderBackend:
    if name == "fake":
        return FakeRecorderBackend()
    if name == "replay":
        return ReplayRecorderBackend()
    # argparse choices guard upstream, but keep this explicit.
    raise SystemExit(f"unknown backend: {name}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        config = SessionConfig(
            output_mf4=Path(args.output),
            selected=args.signals,
            duration_s=float(args.duration),
            backend=args.backend,
            segment_seconds=args.segment,
        )
    except ValueError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    backend = _make_backend(args.backend)
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
