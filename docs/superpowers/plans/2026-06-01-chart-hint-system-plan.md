# Chart Hint System Implementation Plan

Date: 2026-06-01
Branch: `plan/pyqtgraph-timedomain-migration`
Design: `docs/superpowers/specs/2026-06-01-chart-hint-system-design.md`
Inventory: `docs/analyzer/ui-hints.md`

Goal: move chart hints into a curated registry and a rotating context layer,
without regressing current behavior. Land in small, independently shippable
phases. Each phase keeps the suite green.

## Current anchors (verified)

- `mf4_analyzer/ui/chart_stack.py`: `_TOOL_HINTS:167`, `_BOTTOM_HINT_PERSISTENT:175`,
  `_BOTTOM_HINT_CONTEXT:183`, `_NAV_SHORTCUTS:213`, `_TIME_CARD_SHORTCUTS:223`;
  consumed at `_hint_persistent:906`, `_context_hint_key:1056`, `_TOOL_HINTS.get:1070`,
  `_TIME_CARD_SHORTCUTS:1162`.
- `mf4_analyzer/ui/widgets/__init__.py`: `MultiFileChannelWidget._on_context_menu`
  with the `设为左轴` action (`overlay.left_axis` discoverability).
- Right-click menu labels (`查看全部 / X 轴范围 / Y 轴范围 / 鼠标操作 / 网格`) in
  `pg_canvases.py`.

## Phase 1 — Registry module, no behavior change

- Add `mf4_analyzer/ui/hints.py` with the `Hint` dataclass, `HintState`, and
  `persistent_hints()` / `context_hints()` / `shortcut_tooltip()`.
- Seed it from the **curated** set in the design (not the full inventory).
- Re-express the surviving `chart_stack` constants as registry lookups; keep
  `chart_stack` rendering identical (persistent bar text must be byte-identical
  to today's three-segment string until Phase 2 intentionally changes it).
- Tests: `tests/ui/test_hints.py` — dataclass filtering, priority, Tier S before
  A, suppression. `test_chart_stack` unchanged and green.

## Phase 2 — Wire the bottom bar to the registry

- `_context_hint_key()` → build a `HintState` from the card and call
  `context_hints(state)`; render `[0]` on the right.
- Persistent left side reads `persistent_hints()` (the three curated lines).
- Remove now-dead `_BOTTOM_HINT_CONTEXT` entries that were dropped by curation;
  keep parity for ones that survive.
- Tests: assert the context layer comes from the registry (patch the registry,
  see the bar follow); persistent text equals the three curated lines.

## Phase 3 — Rotation engine

- Add a `QTimer` (8–12 s) on the right-side label; advance through
  `context_hints(state)` round-robin.
- Pause on active drag / pan / zoom-box / cursor drag (reuse the card's existing
  interaction flags); resume after.
- Refresh + jump to top hint on explicit mode change (overlay↔subplot, cursor
  on/off, FFT-vs-Time enter).
- Track `recently_used` ids per session; filter them out.
- Tests: simulated mode switches pick the right top hint; performing an
  interaction adds its id to `recently_used` and drops it from rotation; rotation
  paused flag honored.

## Phase 4 — Discovery queue ("this exists") + tooltips

Advertise invisible *capabilities* one at a time, retiring each permanently the
first time it is used. These answer "does this feature exist at all", which no
button or label conveys.

- Add a persisted `discovered` set (QSettings, one key holding the retired ids)
  and a `mark_discovered(id)` helper. `discovery_hint(state)` returns the
  highest-priority item whose id is not in `discovered`, else `None`.
- Render the discovery slot in the bar from `discovery_hint`; at most one at a
  time; empty slot when all retired.
- Ship these items (priority order) and wire each retire trigger:
  - `toolbar.shortcuts_exist` → nav/time-card shortcut handlers fire.
  - `chart.copy_image` → the copy button click (`copy_image_requested`).
  - `chart.right_click_menu` → chart `customContextMenuRequested`.
  - `channel.right_click` → `MultiFileChannelWidget._on_context_menu`.
- Defer `view.history` (wire to the back/forward action) and the
  `markup.capabilities` editor-side one-shot to a later pass.
- Tooltips: ensure every toolbar/segmented button tooltip includes its exact key
  from `_NAV_SHORTCUTS` / `_TIME_CARD_SHORTCUTS` via `shortcut_tooltip` — keys
  live in tooltips, the bar only advertises they exist. Remove any per-key
  enumeration from the bar.
- Drop the superseded items: rotating `overlay.left_axis` (now
  `channel.right_click`) and `chart.copy_includes_cursor` (folded into
  `chart.copy_image`).
- Tests: `discovery_hint` skips ids in `discovered` and returns them in priority
  order; `mark_discovered` advances the slot and round-trips through the persisted
  store (reload keeps them hidden); each wired trigger marks its id; each shortcut
  action's button tooltip contains its key; the bar exposes no multi-shortcut
  string.

## Phase 5 — Doc-sync guard

- Test that every `id` in the design doc's curated tables exists as a `Hint`
  definition in `hints.py` (parse the spec tables, diff against registry ids), so
  the spec and runtime cannot silently drift. Items marked `ship: later`
  (`view.history`, `markup.capabilities`) must be *defined* but may be unwired —
  the guard checks definitions, not wiring.
- Optionally invert later: generate the spec tables from the registry.

## Out of scope (per design Non-Goals)

- No onboarding wizard, no modal tutorial, no runtime Markdown parsing.
- No new chart-toolbar redesign; no removal of existing tooltips/shortcuts.
- User-suppressible toggle and icons-in-bar are deferred (design "Open Decisions").

## Risk / rollback

- Each phase is independently revertable; Phase 1 is pure refactor with identical
  output, so a regression there is a behavior diff in tests, not in the field.
- Rotation (Phase 3) is the only timing-sensitive part; ship it behind the
  existing card lifecycle and gate with the interaction-pause flags already used
  by the cursor/pan code.
