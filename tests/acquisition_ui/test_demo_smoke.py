"""Demo entry smoke (Stage 4).

Pins:

- ``python -m mf4_analyzer.acquisition_ui --self-test`` exits with code 0.
- ``RingBuffer.watermark_changed`` is bridged to the Qt slot
  ``MainWindow.set_target_fps`` — emitting the signal directly toggles
  the live timer interval between the 30 fps and 10 fps constants.
"""

from __future__ import annotations

import subprocess
import sys

from mf4_analyzer.acquisition_capture import thresholds
from mf4_analyzer.acquisition_ui.main_window import CockpitMainWindow


def test_self_test_exits_zero():
    """Run the self-test entrypoint as a subprocess so we exercise the
    real argv parser + headless launch path.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mf4_analyzer.acquisition_ui",
            "--demo",
            "--self-test",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"self-test exit {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_ring_buffer_watermark_bridge_to_fps(qapp):
    """Emit the watermark signal directly and assert the slot fires.

    No recorder required — the test pokes the shim's ``emit`` API.
    """
    window = CockpitMainWindow()
    # Start in green / 30 fps.
    assert window._target_fps == thresholds.LIVE_FPS_NORMAL

    # Emit a red watermark → 10 fps.
    window._ring.watermark_changed.emit("red")
    assert window._target_fps == thresholds.LIVE_FPS_DEGRADED
    # Interval reflects fps.
    assert window._live_timer.interval() == int(
        1000 / thresholds.LIVE_FPS_DEGRADED
    )

    # Back to green → 30 fps.
    window._ring.watermark_changed.emit("green")
    assert window._target_fps == thresholds.LIVE_FPS_NORMAL
    assert window._live_timer.interval() == int(
        1000 / thresholds.LIVE_FPS_NORMAL
    )

    window.close()


def test_red_drop_sustained_emits_auto_stop(qapp):
    """``red_drop_sustained`` ⇒ ``auto_stop_requested`` Qt signal fires."""
    window = CockpitMainWindow()
    fired = []
    window.auto_stop_requested.connect(lambda reason: fired.append(reason))
    window._ring.watermark_changed.emit("red_drop_sustained")
    assert fired == ["ring_buffer"]
    window.close()
