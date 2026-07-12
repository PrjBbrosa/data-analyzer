---
role: pyqt-ui
tags: [collapsible-section, mapto, geometry, offscreen, layout, sizehint, default-collapsed, tour-script]
created: 2026-07-12
updated: 2026-07-12
cause: insight
supersedes: []
---

## Context

The dB-reference UI tour (Task 10) drove a REAL, embedded `DbReferenceControl`
inside each Inspector Contextual (`fftContextual`/`fftTimeContextual`/
`orderContextual`) through `control.mapTo(ctx, control.rect().topLeft())` to
prove "compound rect stays inside the Inspector content rect" — the exact
pattern an existing offscreen unit test already used successfully against a
standalone, directly-resized Contextual. Embedded inside the real `MainWindow`
after loading a file + calling `do_fft()`, the SAME call returned nonsense: an
x-coordinate of 391 against a `ctx.rect()` width of only 272. No Qt warning
was printed; `control.isAncestorOf`/the parent chain walk both confirmed `ctx`
genuinely was an ancestor of `control`.

## Lesson

The Inspector's "谱参数" params section (which HOSTS the compound control)
defaults COLLAPSED (`_CollapsibleParamSection`, matches
`tests/ui/conftest.py`'s own isolate-qsettings docstring). While collapsed,
`set_body`'s body widget stays `setVisible(False)` — and a widget chain that
is never actually shown is never actually LAID OUT by Qt: the top of that
hidden chain (here a `QGroupBox` several levels up) sits at Qt's raw
un-initialized default size, `640x480`, while widgets ABOVE and BELOW it in
the same chain can still report seemingly-normal geometry. `mapTo()` walks
the REAL parent chain and faithfully sums these inconsistent offsets — it
does not detect or warn about a hidden/unlaid-out ancestor, it just returns
whatever the (garbage) intermediate geometries add up to. Waiting longer with
extra `processEvents()` pumps does NOT self-heal this; a hidden widget never
gets a layout pass no matter how many event-loop iterations you give it.

## How to apply

Before running any `mapTo`/`rect()`-based geometry proof against a widget
embedded inside a REAL, production Inspector/collapsible-section host
(not a standalone widget built directly by the test), first confirm every
ancestor collapsible section is expanded (`section.set_expanded(True)`) and
pump events once. If a geometry check against a live-embedded widget returns
coordinates wildly outside the expected container's `rect()` (frequently
exactly `640x480` or a multiple/offset of it) with no Qt runtime warning, that
is the signature of an unlaid-out HIDDEN ancestor, not a real overflow bug —
check `widget.isVisible()` up the parent chain before treating it as a defect.
