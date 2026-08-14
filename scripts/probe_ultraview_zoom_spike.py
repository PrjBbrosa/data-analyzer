#!/usr/bin/env python3
"""UltraView P3-2 go/no-go spike: pinch delivery + 24-card rescale frame time.

This is not product code. It must be run on a real Cocoa display — numbers
from ``QT_QPA_PLATFORM=offscreen`` are not paint evidence (CLAUDE.md Gotchas).

Usage (foreground TraceLab machine, no offscreen):

    .venv/bin/python scripts/probe_ultraview_zoom_spike.py --seconds 4

Writes JSON to stdout and optionally ``--json-out``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from PyQt5.QtCore import QElapsedTimer, Qt, QTimer
from PyQt5.QtGui import (
    QColor,
    QNativeGestureEvent,
    QPainter,
    QPixmap,
    QWheelEvent,
)
from PyQt5.QtWidgets import QApplication, QLabel, QWidget


REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from mf4_analyzer.ui.chart_stack.ultraview.free_grid import (  # noqa: E402
    grid_metrics,
)
from mf4_analyzer.ui.ultraview_state import (  # noqa: E402
    FreeGridPlacement,
    GridRect,
    make_ref,
)


def _platform() -> str:
    return str(os.environ.get("QT_QPA_PLATFORM") or "native")


class SpikeBoard(QWidget):
    def __init__(self, n_cards: int = 24) -> None:
        super().__init__()
        self.setWindowTitle("UltraView zoom spike")
        self.resize(1280, 800)
        self._n = n_cards
        self._zoom = 1.0
        self._labels: list[QLabel] = []
        self._source = QPixmap(320, 180)
        self._source.fill(QColor("#2d7ff9"))
        painter = QPainter(self._source)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(self._source.rect(), Qt.AlignCenter, "preview")
        painter.end()
        for _ in range(n_cards):
            label = QLabel(self)
            label.setScaledContents(False)
            self._labels.append(label)
        self.pinch_events = 0
        self.pinch_values: list[float] = []
        self.wheel_ctrl_events = 0
        self.frame_ms: list[float] = []
        self._layout_cards()

    def event(self, event) -> bool:  # noqa: N802
        if isinstance(event, QNativeGestureEvent):
            if event.gestureType() == Qt.ZoomNativeGesture:
                self.pinch_events += 1
                self.pinch_values.append(float(event.value()))
                self._zoom = min(2.0, max(0.25, self._zoom * (1.0 + float(event.value()))))
                self._layout_cards()
                return True
        return super().event(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier):
            self.wheel_ctrl_events += 1
            delta = event.angleDelta().y()
            step = 1.08 if delta > 0 else 1 / 1.08
            self._zoom = min(2.0, max(0.25, self._zoom * step))
            self._layout_cards()
            event.accept()
            return
        super().wheelEvent(event)

    def _layout_cards(self) -> None:
        timer = QElapsedTimer()
        timer.start()
        placements = [
            FreeGridPlacement(make_ref("time", f"c{i}"), GridRect((i % 6) * 2, (i // 6) * 2, 2, 2))
            for i in range(self._n)
        ]
        vw = max(1, int(self.width() * self._zoom))
        vh = max(1, int(self.height() * self._zoom))
        metrics = grid_metrics((vw, vh), placements)
        col_w = max(8, int(metrics.column_width))
        row_h = max(8, int(metrics.row_height))
        for index, label in enumerate(self._labels):
            x = (index % 6) * (col_w + 8)
            y = (index // 6) * (row_h + 8)
            label.setGeometry(x, y, col_w, row_h)
            scaled = self._source.scaled(
                col_w,
                row_h,
                Qt.KeepAspectRatio,
                Qt.FastTransformation,
            )
            label.setPixmap(scaled)
            label.show()
        QApplication.processEvents()
        self.frame_ms.append(timer.elapsed())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=3.0)
    parser.add_argument("--cards", type=int, default=24)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    platform = _platform()
    app = QApplication.instance() or QApplication(sys.argv)
    board = SpikeBoard(args.cards)
    board.show()
    # Synthetic zoom steps even without a human pinch, so the rescale path is timed.
    zooms = [0.25, 0.4, 0.6, 1.0, 1.4, 2.0, 1.0]
    step = {"i": 0}

    def _tick() -> None:
        if step["i"] < len(zooms):
            board._zoom = zooms[step["i"]]
            board._layout_cards()
            step["i"] += 1

    timer = QTimer()
    timer.setInterval(80)
    timer.timeout.connect(_tick)
    timer.start()
    QTimer.singleShot(int(args.seconds * 1000), app.quit)
    started = time.perf_counter()
    app.exec_()
    elapsed = time.perf_counter() - started
    over_33 = sum(1 for ms in board.frame_ms if ms > 33)
    payload = {
        "platform": platform,
        "offscreen": platform == "offscreen",
        "cards": args.cards,
        "elapsed_s": round(elapsed, 3),
        "frames": len(board.frame_ms),
        "frame_ms": board.frame_ms,
        "max_frame_ms": max(board.frame_ms) if board.frame_ms else None,
        "frames_over_33ms": over_33,
        "pinch_events": board.pinch_events,
        "pinch_values_head": board.pinch_values[:8],
        "wheel_ctrl_events": board.wheel_ctrl_events,
        "zoom_insertion": {
            "preferred": "scale viewport passed into grid_metrics (call-site only)",
            "alternative": "scale column_width/row_height/gutter/padding fields",
        },
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(text)
    if args.json_out:
        args.json_out.write_text(text + "\n", encoding="utf-8")
    if platform == "offscreen":
        print("UNVERIFIED as Cocoa evidence: QT_QPA_PLATFORM=offscreen", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
