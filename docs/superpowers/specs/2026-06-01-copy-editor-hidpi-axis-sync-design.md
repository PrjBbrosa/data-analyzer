# Copy Editor HiDPI And Axis Sync Fix Design

Date: 2026-06-01
Branch: `plan/pyqtgraph-timedomain-migration`
Scope: Time-domain copy image, markup editor image fit, and pyqtgraph X-axis tick synchronization.

## Problem

Three live UI defects share a narrow surface around copied chart pixmaps and pyqtgraph range propagation:

1. Copying a time-domain chart in cursor mode captures the cursor lines and min/max markers, but the floating cursor statistics pill can be missing from the copied image.
2. On macOS Retina displays, the markup editor can open the copied image as a small image in the upper-left with a large empty/black area to the right and bottom. The same flow is less visible on Windows because DPR is usually 1.
3. After zooming in overlay mode and switching back to subplot mode, or after setting X limits through the right-click axis controls, the plotted curves move to the requested X window but the bottom X-axis tick labels can remain stuck at the old numbers.

## Root Cause

The copy/editor issues are caused by inconsistent `QPixmap.devicePixelRatioF()` handling. The editor sizes its `QGraphicsScene` from physical `pixmap.width()/height()`, while `QGraphicsPixmapItem` displays a high-DPI pixmap in logical units (`width / DPR`, `height / DPR`). The copy path also composites the `CursorPill` with scaled physical coordinates into a pixmap whose painter may use logical DPR coordinates.

The X-axis issue is caused by `TimeDomainCanvasPG._propagate_xlim_to_siblings()` blocking ViewBox signals while syncing sibling ranges. That prevents feedback loops, but it also prevents the linked bottom `AxisItem` from receiving the range-change notification it needs to update tick labels. The ViewBox range changes, so the curves move; the AxisItem display range stays stale.

## Design

Normalize copied chart pixmaps before they enter the clipboard/editor path:

- Convert high-DPI copied pixmaps to DPR 1.0 image-space pixmaps for downstream clipboard, thumbnail, and editor use.
- Composite the cursor pill in the same normalized pixel coordinate system as the target pixmap.
- Keep the existing export-size cap and do not alter the FFT/order copy paths beyond accepting normalized pixmaps when they already arrive as DPR 1.

Make the markup editor scene size match the displayed pixmap:

- Use the background pixmap item's `boundingRect()` or a helper equivalent to define the scene rect.
- Keep render output dimensions equal to the source image's actual pixel content after DPR normalization.

Keep pyqtgraph tick labels synchronized with programmatic range propagation:

- After a signal-blocked sibling `setXRange`, explicitly update the sibling's bottom `AxisItem` range to the same `(lo, hi)`.
- Apply the same explicit AxisItem sync when seeding data-union ranges or restoring a captured X range.
- Preserve the signal-blocking guard to avoid range-change ping-pong.

## Acceptance Criteria

- A copied time-domain image with visible cursor statistics includes the statistics pill in the final pixmap.
- A DPR 2 source pixmap opens in the markup editor with scene bounds matching the visible image bounds, not double-sized physical bounds.
- Programmatic subplot sync and overlay-to-subplot restore both update the visible bottom X-axis tick range.
- Existing cursor, copy, markup, and pyqtgraph focused tests remain green.

## Tests

- Add a chart-stack regression that uses a DPR 2 copied pixmap and verifies the pill is actually painted inside the image bounds.
- Add a markup editor regression where a DPR 2 pixmap produces a scene rect matching `QGraphicsPixmapItem.boundingRect()`.
- Add pyqtgraph regressions that assert the bottom AxisItem range updates when:
  - the primary subplot range propagates to the bottom subplot;
  - an overlay aux ViewBox range propagates to the X-master bottom axis;
  - overlay mode range is preserved when switching back to subplot mode.
