---
role: pyqt-ui
tags: [layout, inspector, splitter, qframe, wa-styledbackground, max-width, rework-risk]
created: 2026-04-26
updated: 2026-04-26
cause: rework
supersedes: []
---

## Context

The Precision Light R3 紧凑化 pass shipped three regressions that the
user spotted in the same screenshot session:

1. Toggling "使用选定范围" (a checkbox that reveals two ``QDoubleSpinBox``
   range inputs) made the right Inspector pane look visibly wider —
   the 开始/结束 spinboxes were ``QSizePolicy.Expanding`` with no
   ``setMaximumWidth``, so they grew to consume whatever slack the
   splitter slot offered.
2. The "信号源" / "分析信号" cards inside the tinted FFT/Order
   contextual cards rendered as opaque white rectangles, breaking the
   tinted-card bleed-through. Root cause: the wrapper ``QFrame`` was
   created with ``setAttribute(Qt.WA_StyledBackground, True)`` but the
   project's QSS had no paired rule for the wrapper's objectName, so
   the global ``QFrame { background-color: #ffffff }`` rule painted
   it white. Even after removing the explicit attribute, Qt's
   stylesheet polish re-enables the styled-bg flag whenever a global
   ``QFrame {...}`` rule matches the widget — so the QSS override IS
   the load-bearing fix.
3. Tool-button icons (rebuild-time in the Inspector, file-row close
   and the navigator kebab) had ~30px outer chrome around 16px icons;
   the user described it as "占了太多位置". ``setMaximumWidth(30)`` on
   the host button isn't enough because the global
   ``QPushButton { min-height: 26px; padding: 4px 10px; ... }`` rule
   cascades into ``[role="tool"]`` and inflates the chrome.

## Lesson

Three coupled rules govern this kind of pane:

1. **Cap the content widget, then left-anchor it.** Any
   ``QScrollArea`` body inside a splitter pane that can grow with the
   splitter must call ``body.setMaximumWidth(<form-natural-width>)``
   AND sit inside an ``addStretch``-padded host so the cap visibly
   leaves a right-side gap when the splitter widens. Without the cap,
   every ``QSizePolicy.Expanding`` child fights the cap by stretching;
   with the cap, the form column stays anchored at its natural width
   and Expanding children resolve to ``min(maxWidth, host_width)``.

2. **Wrapper QFrames need paired QSS rules.** A custom-header pattern
   that wraps a section in a ``QFrame`` (e.g. to dock an action button
   on the title bar) must add an explicit
   ``Inspector QFrame#<objectName> { background-color: transparent;
   border: none; }`` rule whenever the surrounding container is a
   tinted contextual card. Removing the explicit
   ``setAttribute(Qt.WA_StyledBackground, True)`` is necessary but
   not sufficient — a global ``QFrame { background: #fff }`` rule
   re-enables the flag during polish.

3. **Tool buttons must escape the global button rule.** Calling
   ``setFixedSize(QSize(24, 24))`` is overridden in practice by the
   global ``QPushButton { min-height: 26px; padding: 4px 10px; ... }``
   stylesheet because Qt's CSS sizing math adds (min-height + padding +
   border) to compute the actual minimumSize. The fix is to scope the
   tool-button QSS selector via ``[role="tool"]`` and explicitly zero
   out ``min-width`` / ``min-height`` there so the ``setFixedSize``
   on the host widget governs.

## How to apply

Whenever the user reports that "toggling X makes the pane wider /
narrower" or that a card "变成白底了", or that an icon button "占了太多
位置":

- Diagnose at the container, not the leaf. The leaf widget is almost
  always doing what its size policy says; the bug is in an unbounded
  parent or a clobbering global QSS rule.
- For width-toggle defects, add ``setMaximumWidth`` on the scroll
  body AND a trailing stretch in a host layout. Verify in a visual
  smoke test at three pane widths: narrow (≤ minWidth), default
  (the spec's `setSizes` slot), and wide (1.5×~3× the default). The
  visible right-gap at the wide end is the *correct* outcome, not a
  bug.
- For wrapper-QFrame white-bleed defects, add a paired QSS rule keyed
  on the wrapper's ``objectName`` and verify by reading the rendered
  ``palette().window()`` or by exercising the affected mode in the
  live app.
- For tool-button outer-chrome defects, never rely on
  ``setMaximumWidth`` alone. Combine ``setFixedSize`` on the host with
  a scoped QSS rule that sets ``min-width: 0; min-height: 0;`` on the
  ``[role="tool"]`` selector. Keep the icon size unchanged (16x16).
