# Markup Editor Hint System Design

Date: 2026-06-09
Branch: `docs/timedomain-view-tabs-plan`
Scope: Extend the curated hint system (`mf4_analyzer/ui/hints.py`) beyond the
chart area to its **first new interface — the markup (image annotation)
editor**. Companion: `2026-06-01-chart-hint-system-design.md` (the chart-area
design this builds on) and `docs/analyzer/ui-hints.md` (candidate inventory).

## Problem

The hint registry today is chart-only. It has three surfaces (`persistent`,
`discovery`, `context`), all consumed exclusively by the bottom chart bar in
`chart_stack.py` (plus one wire in `main_window.py` for channel right-click).
The app has grown several other interfaces with **zero discoverability hints**.

The highest-payoff of these is the markup editor (`mf4_analyzer/ui/markup/editor.py`),
which hides an entire keyboard/gesture vocabulary behind no on-screen cue:

- Single-key tool switch `V/A/L/R/P/T/N/C` (select/arrow/line/rect/pen/text/number/crop)
- `Ctrl+Z`/`Ctrl+Y` undo/redo, `Ctrl+C`/`Ctrl+V` copy/paste annotations
- Arrow keys move the selected annotation 1px; `Shift+arrow` moves 10px
- `Ctrl++`/`Ctrl+-`/`0` zoom; `[`/`]` line width
- Double-click a text item to edit it; `Shift+drag` constrains line/arrow to
  H/V and rect to square; `Ctrl+click` multi-selects

The registry already contains a placeholder for this — `markup.capabilities`
(`surface="discovery"`, `ship="later"`) — but it was never wired, and its text
(`裁剪 / 箭头 / 文字 / 序号，支持撤销`) describes the **visible tool buttons**,
violating the chart spec's own curation rule (show only interactions with *no
visible affordance*).

## Goals / Non-Goals

**Goals**
- Make the markup editor's hidden keyboard/gesture power discoverable, following
  the chart spec's philosophy verbatim: *tooltips own exact shortcuts; one
  discovery hint advertises they exist*.
- Reuse existing infrastructure (`Toast` widget, `hints.mark_discovered` /
  `load_discovered` persisted via `QSettings` key `chartHints/discovered`).
- Lay the registry groundwork (`scope` dimension) so later passes can add
  acquisition window / view tabbar / side panels without re-architecting.

**Non-Goals (this pass)**
- No other interface (acquisition, batch, view tabbar, side panels). Those are
  deferred; this pass is markup-only.
- No onboarding wizard, modal tutorial, or runtime Markdown parsing.
- No new rotating-context surface inside the editor — the editor gets a single
  one-shot discovery card, not a live hint bar.

## Curation (carried over from the chart spec)

Show a hint only if **both**: (1) no visible affordance, and (2) real payoff.
Tool buttons are visible, so the card never re-lists them as *what* exists — it
points at the hidden *how* (their single-key shortcuts) and at the gestures that
have no button at all.

## Design

### 1. Registry change — `mf4_analyzer/ui/hints.py`

Add a `scope` field to `Hint`:

```python
@dataclass(frozen=True)
class Hint:
    id: str
    text: str
    surface: str
    scope: str = "chart"        # NEW: "chart" | "markup" | (future) ...
    tier: str = "S"
    ...
```

Gate the chart-bar accessors so non-chart hints never leak into the chart
discovery queue or context rotation:

- `discovery_hint(state, scope="chart")` — filter `hint.scope == scope`.
  Default `"chart"` keeps every existing chart call site unchanged.
- `context_hints(state, scope="chart")` — same filter, same default.

Reshape the existing `markup.capabilities` entry:

| field | from | to |
| --- | --- | --- |
| `scope` | (none → "chart") | `"markup"` |
| `ship` | `"later"` | `"now"` |
| `text` | `裁剪 / 箭头 / 文字 / 序号，支持撤销` | `箭头键移动标注，Shift 加速 · 双击文本可编辑 · 工具支持单键切换（悬停按钮看键位）` |
| `retire_on` | `"markup_open"` | unchanged |
| `surface` | `"discovery"` | unchanged |

The editor reads it via `hints.discovery_hint(state, scope="markup")`.

### 2. Markup editor becomes a new consumer — `markup/editor.py`

**First-open discovery card.** In `showEvent` (editor.py:612):

- Guard with a per-instance flag so it fires at most once per editor lifetime.
- Read `hints.load_discovered(settings)`. If `markup.capabilities` is **not**
  retired, resolve it via `hints.discovery_hint(HintState(discovered=…),
  scope="markup")`, show it through a `Toast(self)` (parented to the **editor**,
  not the main window — the editor is a top-level `QWidget` that covers the main
  window), then call `hints.mark_discovered(settings, "markup.capabilities")`.
- Persistence makes it a true one-shot across relaunches; the per-instance flag
  prevents a re-show if `showEvent` fires twice in one session (e.g. hide/show).

**Tooltip gaps.** Tool buttons already append their letter (editor.py:930,
`f"{labels[tool]} ({tool[0].upper()})"`). Fill the buttons that still omit their
shortcut:

| button | line | from | to |
| --- | --- | --- | --- |
| undo | 950 | `撤销` | `撤销 (Ctrl+Z)` |
| redo | 962 | `重做` | `重做 (Ctrl+Y)` |
| close | 863 | `关闭` | `关闭 (Esc)` |
| style | 881 | `样式（颜色 / 线宽）` | `样式（颜色 / 线宽） · [ ] 调线宽` |

The style-button addition gives the orphan `[`/`]` keys a home (they have no
dedicated button and are intentionally left off the card).

### 3. Discovery card copy

One-shot toast, ≤ 2 short lines, highest-value no-button gestures only:

> `箭头键移动标注，Shift 加速 · 双击文本可编辑 · 工具支持单键切换（悬停按钮看键位）`

Deliberately excluded from the card (avoid the "manual wall" the chart spec
warns against): `Ctrl+click` multi-select, `Shift+drag` constraints, wheel /
`Ctrl±` / `0` zoom, `[`/`]` line width. These surface via tooltips or natural
trial.

## Surfaces (delta from the chart spec)

| surface | content | behavior |
| --- | --- | --- |
| Markup editor — toast | `markup.capabilities` | one-shot on first editor open; retires via the shared persisted `discovered` set; `Toast` parented to the editor |
| Markup editor — button tooltips | exact command + shortcut | tools already carry their letter; undo/redo/close/style get theirs filled in |

## Behavior Rules

- The card shows once, ever, per profile (persisted), and at most once per editor
  instance (per-instance flag).
- The card text names only no-visible-affordance interactions.
- Chart-bar behavior is unchanged: `discovery_hint()` / `context_hints()` default
  to `scope="chart"`, so `markup.capabilities` (now `ship="now"` but
  `scope="markup"`) never appears in the chart discovery queue.

## Acceptance Criteria

- On a fresh profile, opening the markup editor for the first time shows the
  discovery toast with the curated card text; opening it again (same or later
  session) does not.
- The chart bottom bar's discovery queue is byte-for-byte unchanged:
  `toolbar.shortcuts_exist → chart.copy_image → chart.right_click_menu →
  channel.right_click`, with `markup.capabilities` absent from it.
- The undo / redo / close / style tooltips include their shortcuts.
- A retired `markup.capabilities` stays retired after relaunch.

## Tests

- `tests/ui/test_hints.py`:
  - `markup.capabilities` has `scope == "markup"`, `ship == "now"`,
    `surface == "discovery"`.
  - `discovery_hint(state)` (default chart scope) never returns
    `markup.capabilities`; the existing `all_now` assertion is updated to filter
    `scope == "chart"` so it still proves the chart queue empties.
  - `discovery_hint(state, scope="markup")` returns `markup.capabilities` until
    its id is in `discovered`, then returns `None`.
- `tests/ui/test_markup_editor.py`:
  - First `show()` on a fresh `QSettings` surfaces the toast exactly once and
    marks it discovered; a second `show()` (now discovered) surfaces nothing.
  - undo / redo / close / style buttons expose the new shortcut strings via
    `toolTip()`.
- Doc-sync: `test_design_curated_ids_exist_in_registry` continues to pass
  (`markup.capabilities` stays in prose, not in a curated table, so it is not
  required by that test — and it is already in the registry regardless).
