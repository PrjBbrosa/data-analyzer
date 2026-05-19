"""``python -m mf4_analyzer.acquisition_ui`` entrypoint.

Two modes:

- ``--demo`` (default if no flag): start the Cockpit on macOS without
  Vector packages. Uses :class:`FakeRecorderBackend` and a synthesized
  measurement pool so the user sees a live stream after clicking
  "连接 ECU".
- ``--demo --self-test``: run a deterministic state-transition smoke
  and exit 0. Used by ``tests/acquisition_ui/test_demo_smoke.py`` and
  by the Stage 4 verification command in the plan.

No Vector / python-can / pyxcp imports happen at module load — the
imports inside this module are pure-Python or Qt only, and the
backend default is :class:`FakeRecorderBackend`.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def _run_self_test() -> int:
    """Deterministic state-transition smoke without showing the window.

    Exercises every legal transition once and asserts the final state
    is ``DISCONNECTED`` so a re-launch is clean. Returns 0 on success.
    """
    # Use offscreen platform unconditionally so the self-test works on
    # CI/headless macOS.
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt5.QtWidgets import QApplication

    from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
    from mf4_analyzer.acquisition_ui.state import (
        CockpitState,
        HealthyPredicateResult,
    )

    app = QApplication.instance() or QApplication(sys.argv)
    window = CockpitMainWindow()
    sm = window.state_machine

    # 1) Disconnected → ConnectedIdle via a synthetic healthy verdict.
    assert sm.state == CockpitState.DISCONNECTED, sm.state
    sm.request_connect(
        HealthyPredicateResult.from_components(
            hw_ok=True,
            xcp_connected=True,
            first_frame_received=True,
        )
    )
    assert sm.state == CockpitState.CONNECTED_IDLE, sm.state

    # 2) ConnectedIdle → Recording.
    sm.request_start_recording()
    assert sm.state == CockpitState.RECORDING, sm.state

    # 3) Recording → ReviewModal (finalized stub).
    sm.request_stop_recording(finalized=True)
    assert sm.state == CockpitState.REVIEW_MODAL, sm.state

    # 4) ReviewModal → ConnectedIdle.
    sm.request_review_close()
    assert sm.state == CockpitState.CONNECTED_IDLE, sm.state

    # 5) Back to Disconnected (legal from ConnectedIdle per spec).
    sm.request_disconnect()
    assert sm.state == CockpitState.DISCONNECTED, sm.state

    # 6) Ring-buffer watermark wiring exercised directly.
    window._on_ring_watermark_changed("red")
    assert window._target_fps == 10, window._target_fps
    window._on_ring_watermark_changed("green")
    assert window._target_fps == 30, window._target_fps

    # Defensive: ensure window can be closed without error.
    window.close()
    app.processEvents()
    return 0


def _run_demo() -> int:
    """Start the Cockpit demo window."""
    from PyQt5.QtWidgets import QApplication

    from can_logger.p0.a2l_probe import MeasurementSummary
    from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow
    from mf4_analyzer.ui_kit import load_stylesheet, setup_chinese_font

    setup_chinese_font()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")
    try:
        load_stylesheet(app)
    except Exception as exc:  # noqa: BLE001 - demo path; print and continue.
        print(f"[acquisition_ui] stylesheet load failed: {exc!r}")

    # Seed pool — three deterministic signals so the left pane shows
    # measurement rows without needing a real A2L parse.
    pool = (
        MeasurementSummary(
            name="EngSpdAvg",
            address=0x40000000,
            datatype="UWORD",
            unit="rpm",
            conversion="",
            available_events=("event_10ms",),
        ),
        MeasurementSummary(
            name="EngTrqAct",
            address=0x40000004,
            datatype="SWORD",
            unit="Nm",
            conversion="",
            available_events=("event_10ms",),
        ),
        MeasurementSummary(
            name="ThrottlePos",
            address=0x40000008,
            datatype="UWORD",
            unit="%",
            conversion="",
            available_events=("event_10ms",),
        ),
    )

    window = CockpitMainWindow(initial_pool=pool, allow_fake_backend=True)
    window.show()
    return app.exec_()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Acquisition Cockpit (Stage 4 demo)",
        prog="python -m mf4_analyzer.acquisition_ui",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Start the Cockpit with fake/replay data on macOS.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run a deterministic state-transition smoke and exit.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return _run_self_test()
    # Default: demo (the plan's verification command uses --demo).
    return _run_demo()


if __name__ == "__main__":
    sys.exit(main())
