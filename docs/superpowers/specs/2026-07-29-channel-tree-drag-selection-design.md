# Channel Tree Drag-Selection Design

## Goal

Prevent accidental multi-selection in the channel tree by disabling selection
changes caused by dragging the left mouse button across rows. Preserve every
intentional selection and channel-membership workflow already in use.

## Interaction Contract

- A plain left click on a channel row selects that row only.
- Holding the left mouse button and moving across rows does not extend or alter
  the row selection.
- `Ctrl+click` adds or removes non-adjacent rows from the selection.
- `Shift+click` selects a contiguous range.
- Clicking a checkbox continues to add or remove channels from the current
  view. When multiple selected channel rows are batch-toggled through a
  checkbox, the existing confirmation remains in place.
- Right-click actions continue to use the blue row selection for batch actions
  such as merging channels onto a shared axis.
- Dragging the scrollbar remains unaffected.

The blue row selection and the checkbox state remain deliberately separate:
selection identifies the target of a batch command, while checkboxes identify
which channels belong to the current view.

## Implementation Boundary

The channel-tree widget should suppress only the selection update that Qt
normally performs during a left-button drag over tree rows, regardless of
keyboard modifiers. It must not change the tree's `ExtendedSelection` mode
because that mode provides the existing `Ctrl` and `Shift` click behavior.
Checkbox hit handling, expansion,
context menus, keyboard navigation, and file/raster parent rows remain as they
are unless a regression test shows they are directly affected.

The channel-tree quick reference should describe the remaining gestures as
`Ctrl+click` for non-adjacent selection and `Shift+click` for range selection.

## Verification

Automated UI tests must demonstrate that:

1. A plain left-button drag from one channel row across other channel rows does
   not create or change a multi-row selection.
2. Plain clicking still performs normal single selection.
3. `Ctrl+click` still creates a non-adjacent multi-selection.
4. `Shift+click` still creates a contiguous range selection.
5. Checkbox clicks and confirmed batch checkbox changes still work exactly
   once.

Run the focused channel-widget and quick-reference tests after implementation.

## Non-goals

- Replacing row selection with checkbox state.
- Adding a dedicated batch-selection mode.
- Removing multi-selection or shared-axis batch actions.
- Changing chart drag, pan, or box-zoom gestures.
