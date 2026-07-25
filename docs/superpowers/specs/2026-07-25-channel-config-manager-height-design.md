# Channel Configuration Manager Default Height Design

## Goal

Keep the bottom save and cancel controls of the Channel Configuration Manager
visible on a 768px-tall Windows display with its taskbar shown.

## Change

`ChannelConfigManagerDialog` keeps its existing 1180px default width. Its
default height changes from 790px to 680px; its existing 680px minimum height
is retained. The channel table and configuration list already scroll, so the
smaller initial viewport does not remove any controls or data.

## Scope

Only the dialog's initial size changes. Do not alter its sidebar width,
contents, save/discard behavior, scrolling, or other dialogs.

## Verification

Add a UI test that constructs `ChannelConfigManagerDialog` and asserts the
1180x680 default size and 940x680 minimum size. Run that focused test with Qt
offscreen, then inspect the dialog at the default size to ensure the footer
controls remain part of its visible layout.
