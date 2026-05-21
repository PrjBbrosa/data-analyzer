"""Tests for ``RingBuffer`` watermark transitions and drop accounting.

Pins the watermark bands from spec §Threshold Contract:

| fill_pct   | level                |
|------------|----------------------|
| 0-50       | green                |
| 50-70      | yellow_low           |
| 70-85      | red                  |
| 85-95      | red_drop             |
| >=95       | red_drop_sustained   |

Also pins ``dropped_frames`` increment behavior and the
``watermark_changed`` signal emission.
"""

from __future__ import annotations

import pytest

from mf4_analyzer.acquisition_capture.ring_buffer import RingBuffer


def _fill_to_pct(ring: RingBuffer, pct: float) -> None:
    """Fill the buffer to roughly ``pct`` percent of capacity."""
    target = int(round(ring.capacity * pct / 100.0))
    # If we are over target, drain first; otherwise push items.
    current = int(round(ring.capacity * ring.level_pct / 100.0))
    if target < current:
        ring.drain()
        current = 0
    for i in range(target - current):
        ring.put(("ch", float(i), 0.0))


def test_watermark_green_below_50():
    ring = RingBuffer(capacity=100)
    levels: list[str] = []
    ring.watermark_changed.connect(lambda lvl: levels.append(lvl))
    # 0..49 = green; no transition because we start at green.
    for i in range(49):
        ring.put(("ch", float(i), 0.0))
    assert ring.watermark == "green"
    assert levels == []


def test_watermark_transitions_through_bands():
    """50% -> yellow_low, 70% -> red, 85% -> red_drop, 95% -> red_drop_sustained."""
    ring = RingBuffer(capacity=100)
    seen: list[str] = []
    ring.watermark_changed.connect(lambda lvl: seen.append(lvl))

    # Push to 55 -> yellow_low (50..70).
    for i in range(55):
        ring.put(("ch", float(i), 0.0))
    assert ring.watermark == "yellow_low"
    assert seen[-1] == "yellow_low"

    # Push to 75 -> red (70..85).
    for i in range(55, 75):
        ring.put(("ch", float(i), 0.0))
    assert ring.watermark == "red"
    assert seen[-1] == "red"

    # Push to 90 -> red_drop (85..95).
    for i in range(75, 90):
        ring.put(("ch", float(i), 0.0))
    assert ring.watermark == "red_drop"
    assert seen[-1] == "red_drop"

    # Push to 100 -> red_drop_sustained (>=95).
    for i in range(90, 100):
        ring.put(("ch", float(i), 0.0))
    assert ring.watermark == "red_drop_sustained"
    assert "red_drop_sustained" in seen


def test_watermark_emit_only_on_transition():
    """No duplicate emits for samples within the same band."""
    ring = RingBuffer(capacity=100)
    seen: list[str] = []
    ring.watermark_changed.connect(lambda lvl: seen.append(lvl))
    # Walk green -> yellow_low; then add 10 more samples inside yellow_low.
    for i in range(55):
        ring.put(("ch", float(i), 0.0))
    yellow_count = seen.count("yellow_low")
    for i in range(55, 65):
        ring.put(("ch", float(i), 0.0))
    # Still yellow_low — no additional emits.
    assert seen.count("yellow_low") == yellow_count


def test_dropped_frames_accumulates_on_overflow():
    ring = RingBuffer(capacity=4)
    for i in range(10):
        ring.put(("ch", float(i), 0.0))
    # Capacity 4, pushed 10 ⇒ 6 evictions.
    assert ring.dropped_frames == 6
    assert ring.capacity == 4
    # Buffer is still full at capacity.
    assert ring.level_pct == 100.0


def test_drain_empties_and_returns_green():
    ring = RingBuffer(capacity=100)
    seen: list[str] = []
    ring.watermark_changed.connect(lambda lvl: seen.append(lvl))
    for i in range(80):
        ring.put(("ch", float(i), 0.0))
    assert ring.watermark == "red"
    drained = ring.drain()
    assert len(drained) == 80
    assert ring.watermark == "green"
    assert seen[-1] == "green"


def test_red_drop_since_tracks_entry_and_exit():
    ring = RingBuffer(capacity=100)
    # Below red_drop -> None.
    for i in range(80):
        ring.put(("ch", float(i), 0.0))
    assert ring.red_drop_since is None
    # Cross into red_drop.
    for i in range(80, 90):
        ring.put(("ch", float(i), 0.0))
    assert ring.red_drop_since is not None
    entered = ring.red_drop_since
    # Stay in band for a moment, sustained time grows. Use the injected
    # ``now`` seam so the test is independent of OS timer granularity.
    sustained = ring.red_drop_sustained_for(now=entered + 0.01)
    assert sustained > 0.0
    # Drop back to green via drain.
    ring.drain()
    assert ring.red_drop_since is None
    assert ring.red_drop_sustained_for() == 0.0
    assert entered  # silence linter


def test_max_depth_tracks_high_water():
    ring = RingBuffer(capacity=10)
    for i in range(5):
        ring.put(("ch", float(i), 0.0))
    assert ring.max_depth == 5
    ring.drain()
    for i in range(8):
        ring.put(("ch", float(i), 0.0))
    assert ring.max_depth == 8


def test_capacity_must_be_positive():
    with pytest.raises(ValueError, match="capacity"):
        RingBuffer(capacity=0)
