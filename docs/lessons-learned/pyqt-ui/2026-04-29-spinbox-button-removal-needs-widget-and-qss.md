---
role: pyqt-ui
tags: [qss, stylesheet, subcontrol, spinbox, button-symbols, native-style, double-protection]
created: 2026-04-29
updated: 2026-04-29
cause: insight
supersedes: []
---

## Context

Wave 2a (2026-04-29) removed the up/down stepper from every QSpinBox /
QDoubleSpinBox in the Inspector so the right gutter could be reclaimed
for the numeric value (e.g. ``20000.00 Hz`` was being clipped behind a
24 px button column on a 360 px Inspector). The first attempt only
collapsed the four QSS subcontrols (``::up-button`` / ``::down-button``
/ ``::up-arrow`` / ``::down-arrow``) to ``width: 0; height: 0; image:
none`` — visually clean on Linux Fusion but Qt's native Cocoa /
``QFusionStyle`` on Windows still painted a stepper because the
QAbstractSpinBox button-symbols setting drives the platform style
independently of the QSS subcontrol geometry.

## Lesson

Hiding a spinbox stepper requires **both** sides of the contract:

1. QSS that collapses every subcontrol to zero AND removes the arrow
   glyph — otherwise the QSS-aware paint path leaves a visible gutter
   even with NoButtons set.
2. Widget-side ``spin.setButtonSymbols(QAbstractSpinBox.NoButtons)`` at
   every construction site — otherwise the native-style paint path
   (which ignores QSS subcontrol-zero rules) still draws the stepper on
   macOS / Windows native styles.

Either alone is insufficient. The construction-site call is the
authoritative one because Qt routes its sizing math through
``buttonSymbols()`` BEFORE the stylesheet polish event resolves, so
``QStyle.subControlRect(SC_SpinBoxUp)`` already returns zero-width
once NoButtons is set — the QSS rules are belt-and-braces for
platforms whose style engine partially respects QSS.

## How to apply

When asked to "remove the spin buttons" or "make the spinbox a plain
text field":

- Add a tiny helper at the call-site module:
  ``def _no_buttons(spin): spin.setButtonSymbols(
  QAbstractSpinBox.NoButtons); return spin``. Wrap every constructor:
  ``self.spin_x = _no_buttons(QDoubleSpinBox())``. This is greppable
  and survives copy-paste in new sections.
- In ``style.qss``, collapse the four spinbox subcontrols to zero
  (``QSpinBox::up-button, QDoubleSpinBox::up-button, ::down-button {
  width: 0; height: 0; border: none; background: transparent; }`` plus
  the matching ``::up-arrow / ::down-arrow { image: none; width: 0;
  height: 0; }``). Use long-form ``padding-left`` / ``padding-right``
  per ``2026-04-27-qss-padding-overrides-setcontentsmargins.md`` so
  global top/bottom padding cascades.
- Keep ``QComboBox::drop-down`` and its ``::down-arrow`` rule UNTOUCHED
  — combos still need the affordance, and partially styling the combo
  drop-down without an explicit arrow rule re-triggers
  ``2026-04-28-qss-subcontrol-needs-explicit-arrow-glyph.md``.
- Verify both legs in tests: assert
  ``spin.buttonSymbols() == QAbstractSpinBox.NoButtons`` AND assert
  ``QStyle.subControlRect(QStyle.CC_SpinBox, opt, SC_SpinBoxUp,
  spin).width() == 0`` after ``app.processEvents()`` — the first
  catches missing ``setButtonSymbols`` calls, the second catches QSS
  regressions that re-introduce a gutter despite NoButtons.
