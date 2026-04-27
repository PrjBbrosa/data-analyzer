---
role: pyqt-ui
tags: [popup, focus-out, clearfocus, focus-policy, qframe, qpopup, testing, offscreen]
created: 2026-04-27
updated: 2026-04-27
cause: insight
supersedes: []
---

## Context

`SignalPickerPopup` is a chips-display button + frameless `QFrame` popup
(`Qt.Popup` window flag) containing a `QLineEdit` search box and a
`QListWidget`. The brief specified a focus-out auto-close semantic with a
test that simulated click-away by calling `p._popup.clearFocus()` after
`show_popup()`. The natural PyQt5 idiom — focus the search field in
`show_popup` so the user can start typing immediately — silently broke
that test: `_popup.clearFocus()` is a no-op when `_popup` does not own
focus, so no `FocusOut` event ever fired and the popup stayed visible.

## Lesson

`QWidget.clearFocus()` only emits `FocusOut` if the widget actually has
keyboard focus. For a popup whose intended focus target is an inner
control (e.g. the search `QLineEdit`), tests that drive click-away via
`popup.clearFocus()` cannot work unless the popup frame itself currently
holds focus. The fix is to give the popup `Qt.StrongFocus` and call
`popup.setFocus()` when shown — moving the visible-focus indicator to the
inner control via a separate `setFocus()` is a layering choice, but the
*owning* focus must live on the popup frame so a programmatic
`clearFocus()` reliably triggers `FocusOut`.

## How to apply

When building a frameless popup that needs to auto-close on focus-out
AND must be testable under offscreen Qt:

1. Set `Qt.StrongFocus` on the popup frame itself (not just on inner
   controls).
2. In `show_popup()`, call `self._popup.setFocus()` so the popup frame
   owns focus when shown. If a child needs visible keyboard focus
   (search field), set it on the child *after* — but the popup frame
   keeps the underlying focus ownership for the click-away semantic.
3. Install an event filter on the popup that hides the popup on
   `QEvent.FocusOut` (and `Qt.Key_Escape` for the keyboard exit).
4. Tests can now drive the focus-out path with
   `popup._popup.clearFocus()`; under offscreen Qt this synchronously
   produces a `FocusOut` the filter consumes. Avoid relying on
   `Qt.Popup` platform-level click-outside dismissal for tests — it is
   not synthesized by the offscreen plugin.
