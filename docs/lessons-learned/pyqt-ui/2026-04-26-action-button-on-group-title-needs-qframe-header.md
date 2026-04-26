---
role: pyqt-ui
tags: [groupbox, title, header, action-button, layout, inspector, qss, wa-styledbackground]
created: 2026-04-26
updated: 2026-04-26
cause: insight
supersedes: []
---

## Context

The Inspector's "分析信号" / "信号源" group titles needed an action
button (the rebuild-time icon) docked at the right edge of the title
bar — moved out of the Fs form row to free vertical space. Doing this
with a plain ``QGroupBox`` is hard because ``QGroupBox::title`` is a Qt
subcontrol painted by the style: it accepts QSS rules but cannot host
child widgets, and putting a ``QPushButton`` inside the box's QSS
``::title`` selector does nothing.

The follow-up 2026-04-26 R3 紧凑化 round added a related trap: the
custom-header pattern wraps the section in a ``QFrame`` (sig_card) that
sits visually inside an already-tinted contextual card. If the wrapper
``QFrame`` becomes styled-background-eligible — either via an explicit
``setAttribute(Qt.WA_StyledBackground, True)`` *or* via a global QSS
``QFrame { background-color: #ffffff }`` rule that auto-polishes the
flag during ``QStyle`` setup — Qt fills the wrapper with white,
breaking the tinted backdrop bleed-through ("信号源 / 分析信号 都变成白底").

## Lesson

When a section needs a title bar with an inline action button, drop
``QGroupBox`` for that group and use a plain ``QFrame`` whose layout is
``[QLabel(title), addStretch, QPushButton]``. Style the frame to match
the underline / typography that the rest of the Inspector's
``QGroupBox::title`` uses (a single QSS rule on
``Inspector QFrame#inspectorGroupHeader`` works) so the visual stays
consistent across the two flavours. The earlier alternative — keeping
the QGroupBox and re-parenting a button into it with manual
``setGeometry`` in ``resizeEvent`` — is fragile (button drifts on theme
changes, re-layouts, font metric shifts) and not worth maintaining.

**WA_StyledBackground vs. QSS coupling (2026-04-26 amendment):** the
custom-header *wrapper* QFrame must NOT be allowed to render with the
default white QFrame background. There are two failure modes:
(a) explicitly calling ``setAttribute(Qt.WA_StyledBackground, True)``
without a paired QSS rule, and (b) leaving the wrapper unattributed
but having a global QSS rule like ``QFrame { background: #fff }`` that
matches it — Qt's stylesheet polish auto-enables WA_StyledBackground in
this case, producing the same white bleed. The fix is an explicit
QSS rule keyed on the wrapper's ``objectName`` that re-transparentizes
the background:
``Inspector QFrame#fftSignalCard { background-color: transparent;
border: none; }``.

## How to apply

If you see a request like "put the rebuild button on the group title
bar" or "dock an action top-right of the section title", build a
factory like ``_make_group_header(title, action_button)`` returning a
``QFrame`` and use it in place of ``QGroupBox`` for that section. Mirror
the title typography in QSS via an ``objectName`` selector so the
custom-header section visually fits the surrounding native-QGroupBox
sections. Resist the temptation to hack ``QGroupBox::title`` with
absolute positioning — the layout-based custom header is shorter,
themeable, and robust to font / DPI changes.

For every wrapper ``QFrame`` introduced this way, also add a paired
QSS rule keyed on its ``objectName`` that transparentizes background +
border, especially when the surrounding container is a tinted
contextual card. Verify by reading
``frame.palette().window()`` after polish or by exercising the live
app in the affected mode — never assume "QFrame defaults to
transparent" when the project ships a global ``QFrame { background-
color: #fff }`` rule.
