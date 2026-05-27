# TimeDomain State Preservation Design

## Goal

Keep TimeDomain plotting controls predictable while users compare different
time windows and channel combinations.

## Scope

- Changing a curve color through chart options updates the curve and its
  corresponding Y-axis styling.
- Subplot inside channel labels show the full channel name instead of a
  middle-ellipsized version.
- Non-semantic TimeDomain replots preserve the visible X window when the old
  and new data extents overlap.
- Overlay curve selection and drag returns to the default pan tool unless the
  user explicitly chose zoom.

## Behavior

Curve color changes must update the selected line, Y-axis label, Y tick labels,
the left or right Y spine, and any inside label artist bound to the same channel
name.

Inside channel labels must retain their full text. They may wrap or use compact
font sizing, but must not replace the middle of the name with `...`.

The visible X window must be preserved for these operations:

- Switching subplot/overlay mode.
- Checking, unchecking, or adding plotted channels.
- Applying channel editor changes.
- Returning to TimeDomain mode from another analysis mode when the existing
  TimeDomain plot is compatible.

The visible X window should not be preserved when the X-axis or data semantics
change:

- Applying a custom X-axis source or returning from custom X to time.
- Rebuilding a file time axis.
- Closing files or clearing all checked channels.

The chart toolbar default remains pan. Temporary internal mode changes used for
drag handling must end in pan unless zoom was explicitly active.

## Tests

- Dialog color test verifies line, axis label, ticks, spine, and inside label
  colors update together.
- Canvas label test verifies subplot inside labels keep the full channel name.
- MainWindow smoke tests verify channel changes and channel editor changes
  preserve X limits.
- ChartStack test verifies overlay curve drag preserves X limits and returns to
  pan mode.
