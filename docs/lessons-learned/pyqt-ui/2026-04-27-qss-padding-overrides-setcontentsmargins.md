---
role: pyqt-ui
tags: [qss, stylesheet, contentsmargins, padding, qgroupbox, qformlayout, polish, inspector]
created: 2026-04-27
updated: 2026-04-27
cause: insight
supersedes: []
---

## Context

The Inspector A1-layout test
``test_fft_contextual_fields_fill_column_under_qss`` asserts that all
five FFT contextual fields share the same width and right edge under
the project's QSS. It kept failing with widths
``[260, 260, 251, 251, 251]`` — the sig_card form (QFrame parent) hit
the 260 cap, but the 谱参数 group (QGroupBox parent) capped at 251 even
though every field had ``setMaximumWidth(260)`` and ``_configure_form``
called ``parent.setContentsMargins(left, top, 0, bottom)`` to zero out
the QGroupBox's right margin. Calls to ``parent.setContentsMargins`` to
zero left/right kept reporting back as ``(2, 18, 2, 6)`` after polish.

## Lesson

When the global stylesheet has a ``padding`` rule on a widget class,
that rule **wins over** any ``setContentsMargins`` call on individual
widget instances. ``Inspector QGroupBox { padding: 12px 2px 6px; }``
re-applies (2, 18-ish, 2, 6) onto every QGroupBox during stylesheet
polish, silently undoing earlier Python margin tweaks. The robust fix
is an INLINE stylesheet on the specific widget that overrides only the
side(s) you care about, using the long-form ``padding-left`` /
``padding-right`` / ``padding-bottom`` (NOT the shorthand) so the
``padding-top`` value cascades from the global rule and continues to
reserve room for the QGroupBox::title baseline:

```python
g.setStyleSheet(
    "QGroupBox { padding-left: 0; padding-right: 0; padding-bottom: 0; }"
)
```

Two paired traps:

1. ``setContentsMargins`` can succeed transiently between construction
   and the next polish event, so sanity checks that print
   ``contentsMargins`` immediately after the call may show the desired
   value but the rendered widget still uses the QSS values. Always
   verify with ``contentsRect()`` AFTER the widget is shown / polished.

2. QFormLayout's label column is sized to the max ``minimumWidth`` of
   labels **within its own form**. If two forms in the same widget
   (e.g. a sig_card form and a QGroupBox form) hold labels of different
   natural widths, their label columns drift apart and the trailing
   field columns no longer share a right edge. ``_enforce_label_widths``
   gained a ``unify_columns=True`` flag that pins every label to the
   global max sizeHint so cross-form alignment is preserved.

## How to apply

Whenever a layout-tweak in Python (``setContentsMargins``,
``setSpacing``, etc.) appears to "not stick" inside an Inspector-style
widget governed by global QSS:

- Grep ``style.qss`` for matching ``padding`` / ``margin`` / ``spacing``
  rules on the widget's class or scoped object name. That rule is the
  most likely culprit.
- Override side-by-side via inline ``setStyleSheet`` using the long-
  form padding properties so untouched sides cascade from global QSS.
- Verify by printing ``contentsRect()`` after ``app.processEvents()``,
  not ``contentsMargins()`` immediately after the setter — the latter
  reports the staged value, not the post-polish render value.

For multi-form widgets where field-column alignment matters across a
sig_card-style QFrame form AND QGroupBox forms, also call
``_enforce_label_widths(self, unify_columns=True)`` at the end of
``_build`` so the label columns share a width.
