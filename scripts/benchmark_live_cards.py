"""Real-machine perf gate for the Cockpit live sparkline cards (Task A-6).

Measures the per-frame ``refresh + paint`` wall of five 1 ms live cards each
holding a full 30 s @ 1 ms buffer (30 000 raw samples), in two cadences:

- ``normal``   — 30 fps (33 ms/frame budget), p95 refresh+paint must be < 33 ms
- ``degraded`` — 10 fps (100 ms/frame budget), p95 must be < 100 ms

WHY a script and not a pytest threshold: the paint frame is CPU-raster /
stroke-count bound (lessons ``narrow-y-overlay-cost-is-stroke-count-not-data``
+ ``project-timedomain-perf-raster-bound``), and offscreen ``QWidget.grab()``
is a *cached blit* that hides the real raster cost
(``paintevent-hook-needs-class-level-override``). So the numbers are only
trustworthy on a REAL display: run this ``--onscreen`` (default). The paint
wall is captured by a CLASS-level ``Sparkline.paintEvent`` timing wrapper
(virtual dispatch reaches a class-level override, never an instance attr),
and ``repaint()`` on a live display runs that paint synchronously.

Usage:
    .venv/bin/python scripts/benchmark_live_cards.py            # onscreen (gate)
    .venv/bin/python scripts/benchmark_live_cards.py --offscreen  # smoke only
    .venv/bin/python scripts/benchmark_live_cards.py --frames 200
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from time import perf_counter

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Cards / buffer sizing.
_N_CARDS = 5
_RASTER_S = 0.001  # 1 ms raster (the worst / densest case)
_WINDOW_S = 30.0  # preload a full honest 30 s window
_CONTAINER_W = 900
_CONTAINER_H = 720

# Per-frame budgets and inbound batch sizes for the two cadences.
_MODES = {
    "normal": {"fps": 30, "frame_dt": 1.0 / 30.0, "budget_ms": 33.0},
    "degraded": {"fps": 10, "frame_dt": 1.0 / 10.0, "budget_ms": 100.0},
}


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    k = (len(ordered) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    frac = k - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def _install_paint_probe(sparkline_cls) -> dict[str, float]:
    """Class-level ``paintEvent`` timing wrapper (per the paintevent-hook
    lesson: instance-attr / viewport swaps are never dispatched)."""
    probe = {"total": 0.0}
    base_paint = sparkline_cls.paintEvent

    def timed_paint(self, event):  # noqa: ANN001
        t0 = perf_counter()
        try:
            base_paint(self, event)
        finally:
            probe["total"] += perf_counter() - t0

    sparkline_cls.paintEvent = timed_paint
    return probe


def _run_mode(cards, sparks, clock, probe, mode_name, cfg, frames):
    from PyQt5.QtWidgets import QApplication

    frame_dt = cfg["frame_dt"]
    batch = max(1, int(round(frame_dt / _RASTER_S)))
    # Continue the stream past the preloaded 30 s window.
    stream_ts = _WINDOW_S

    frame_total_ms: list[float] = []
    frame_paint_ms: list[float] = []

    for _frame in range(frames):
        # Ingest one frame's worth of samples across all cards.
        for _ in range(batch):
            for card in cards:
                card.push_sample(stream_ts, 1000.0 + 900.0 * _sig(stream_ts))
            stream_ts += _RASTER_S
        clock[0] += frame_dt  # advance the injected monotonic clock

        probe["total"] = 0.0
        t0 = perf_counter()
        for card, spark in zip(cards, sparks):
            card.refresh()
            spark.repaint()  # synchronous real paint on a live display
        frame_ms = (perf_counter() - t0) * 1000.0
        QApplication.processEvents()

        frame_total_ms.append(frame_ms)
        frame_paint_ms.append(probe["total"] * 1000.0)

    p50 = _percentile(frame_total_ms, 50)
    p95 = _percentile(frame_total_ms, 95)
    paint_p95 = _percentile(frame_paint_ms, 95)
    budget = cfg["budget_ms"]
    passed = p95 < budget
    print(
        f"[{mode_name:8s}] {cfg['fps']:>2d} fps  frames={frames}  batch={batch}"
        f"  refresh+paint p50={p50:6.2f}ms p95={p95:6.2f}ms"
        f"  (paint-only p95={paint_p95:6.2f}ms)"
        f"  budget<{budget:.0f}ms  ->  {'PASS' if passed else 'FAIL'}"
    )
    return passed


def _sig(t: float) -> float:
    import math

    # A dense multi-tone so buckets carry real min/max spread each frame.
    return math.sin(t * 6.0) + 0.4 * math.sin(t * 61.0) + 0.2 * math.sin(t * 211.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Live-cards perf gate")
    parser.add_argument(
        "--offscreen",
        action="store_true",
        help="run offscreen (SMOKE ONLY — grab() is a cached blit, numbers "
        "are not a valid perf gate; use the default onscreen for the gate)",
    )
    parser.add_argument("--frames", type=int, default=150, help="frames per mode")
    args = parser.parse_args()

    if args.offscreen:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt5.QtWidgets import (
        QApplication,
        QVBoxLayout,
        QWidget,
    )

    from mf4_analyzer.acquisition_ui.widgets.live_cards import (
        LiveSignalCard,
        Sparkline,
    )

    app = QApplication(sys.argv)
    platform = app.platformName()
    onscreen = not args.offscreen and platform != "offscreen"
    print(
        f"platform={platform!r}  mode={'ONSCREEN (gate)' if onscreen else 'OFFSCREEN (smoke)'}"
    )
    if not onscreen:
        print(
            "  WARNING: offscreen repaint() is a cached blit — paint numbers "
            "understate the real raster wall. Not a valid perf gate."
        )

    probe = _install_paint_probe(Sparkline)

    # Shared injectable monotonic clock so the 2 Hz stats gate advances
    # realistically per frame (a real clock would make the benchmark timing
    # itself perturb the gate).
    clock = [0.0]

    container = QWidget()
    container.resize(_CONTAINER_W, _CONTAINER_H)
    layout = QVBoxLayout(container)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(4)

    cards: list[LiveSignalCard] = []
    for i in range(_N_CARDS):
        card = LiveSignalCard(
            f"Sig{i}",
            unit="rpm",
            raster="event_1ms",
            card_index=i,
            clock=lambda: clock[0],
        )
        cards.append(card)
        layout.addWidget(card)

    container.show()
    container.layout().activate()
    QApplication.processEvents()
    sparks = [c._spark for c in cards]
    print(
        f"cards={_N_CARDS}  sparkline width={sparks[0].width()}px "
        f"height={sparks[0].height()}px"
    )

    # Preload a full 30 s @ 1 ms buffer into every card (30 000 raw samples;
    # ~3000 display buckets each) BEFORE timing.
    n_pre = int(_WINDOW_S / _RASTER_S)
    for i in range(n_pre):
        ts = i * _RASTER_S
        for card in cards:
            card.push_sample(ts, 1000.0 + 900.0 * _sig(ts))
    for card in cards:
        card.refresh()
    QApplication.processEvents()
    print(
        f"preloaded {n_pre} raw samples/card -> buckets/card="
        f"{len(sparks[0]._buckets)} (<=3001), raw/card={sparks[0].sample_count}"
    )

    ok = True
    for mode_name, cfg in _MODES.items():
        ok = _run_mode(cards, sparks, clock, probe, mode_name, cfg, args.frames) and ok

    print(f"\nOVERALL: {'PASS' if ok else 'FAIL'}"
          + ("" if onscreen else "  (offscreen smoke — not a gate)"))
    return 0 if ok or not onscreen else 1


if __name__ == "__main__":
    raise SystemExit(main())
