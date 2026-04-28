---
role: pyqt-ui
tags: [qss, stylesheet, subcontrol, arrow, affordance, spinbox, combobox, qtawesome, hidpi]
created: 2026-04-28
updated: 2026-04-28
cause: insight
supersedes: []
---

## Context

The Inspector spinboxes (Fs / RPM系数 / 最大阶次 / 阶次分辨率 / 时间分辨率
/ 动态范围) and combo boxes (转速 / FFT点数 / 模式) had right-gutter
buttons that were invisible at rest — users only discovered the click
target on hover, when the `:hover` background tint painted. The QSS
already styled `QComboBox::drop-down`, `QSpinBox::up-button`, and
`QSpinBox::down-button` with `border: none; background-color: transparent`
but never declared `::down-arrow` or `::up-arrow`.

## Lesson

Once you partially style a Qt subcontrol (button rectangle), Qt
**suppresses the platform-default indicator glyph** and expects you to
provide the arrow yourself. Without an explicit `::down-arrow` /
`::up-arrow` rule the gutter renders as a blank rectangle and the
affordance is invisible. Pair the arrow rule with a faint resting tint
(`#fafbfd`) and a `:disabled` arrow color (`#cbd5e1`) so the control
reads as interactive at rest and as inactive when greyed.

Two ways to supply the glyph were considered:

1. **`image: url("...")` to a rasterized vector** (preferred). Render
   `mdi6.menu-up` / `mdi6.menu-down` from qtawesome to per-state PNGs
   under a per-user cache dir, substitute the absolute paths into a
   QSS template at startup. HiDPI is automatic via
   `pixmap.setDevicePixelRatio` so the `image:` rule renders crisp at
   any scale factor.
2. **CSS border-triangle hack** (`image: none; border-left: 4px solid
   transparent; border-right: 4px solid transparent; border-top: 5px
   solid <color>; width: 0; height: 0`). No asset, but the triangle
   width is fixed by the border math so it does not visually scale
   with the gutter button and HiDPI amplifies its blocky edge.
   **Rejected** for this codebase because button-width alignment is
   fragile: tweaking `width: 22px` on the gutter or `padding-right` on
   the spinbox changes the perceived offset of the triangle, and
   `:pressed` cannot move the glyph at all.

## How to apply

When styling QSS for input subcontrols, treat each subcontrol pair as
a unit: any time you declare `::drop-down` / `::up-button` /
`::down-button`, also declare the matching `::down-arrow` /
`::up-arrow` rule and `:hover` / `:pressed` / `:disabled` variants.

Prefer the **qtawesome → QPixmap → QSS `image: url(...)`** path:

- Render at `devicePixelRatio * logical_px` and call
  `pixmap.setDevicePixelRatio(ratio)` so QSS resolves the image at
  logical-px crispness on HiDPI screens.
- Cache PNGs under `~/.mf4-analyzer-cache/icons/` with filenames that
  embed `(icon_name, color, pixel_size, qtawesome_version)` so an
  upgrade or palette change auto-invalidates without manual cleanup.
- On Windows, **always normalize the `url(...)` path to forward
  slashes** — backslashes are silently dropped by Qt's QSS parser and
  the rule has no visible effect.
- Call `ensure_icon_cache()` AFTER `QApplication(sys.argv)`; qtawesome
  emits `UserWarning: You need to have a running QApplication` if
  invoked pre-app and the screen DPR cannot be read.
- Make the resting button background faintly tinted (`#fafbfd`, not
  fully transparent) so the click target is visible without hover.

Implementation reference: `mf4_analyzer/ui/icons.py::ensure_icon_cache`,
template loader in `mf4_analyzer/app.py::_load_stylesheet`.
