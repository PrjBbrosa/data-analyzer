# Chart Hint System Design

Date: 2026-06-01
Branch: `plan/pyqtgraph-timedomain-migration`
Scope: Analyzer chart-area hint text — what to show, where, and how it rotates.
Companion inventory: `docs/analyzer/ui-hints.md` (raw candidate list). This design
*curates* that inventory and defines runtime behavior; the inventory is the source
of candidate strings, this file is the source of product decisions.

## Problem

Hint copy currently lives as loose constants in `chart_stack.py`
(`_TOOL_HINTS`, `_BOTTOM_HINT_PERSISTENT`, `_BOTTOM_HINT_CONTEXT`,
`_NAV_SHORTCUTS`, `_TIME_CARD_SHORTCUTS`). The inventory doc proposes ~30
candidate hints. If we show most of them, the hint bar becomes a scrolling
manual that users tune out — the opposite of discoverability.

We need a curation rule and a small runtime so the bar stays a *nudge toward
hidden power features*, not a help screen.

## Curation Principle

Show a hint only if **both** are true:

1. **No visible affordance** — the interaction has no button, label, or obvious
   cursor that reveals it. Modifier-wheel zoom, click-curve-then-drag-Y,
   click-spectrogram-for-slice qualify; "click the pan button" does not.
2. **Real payoff** — knowing it changes how the user works, not just trivia.

Two more rules keep it from feeling like a manual:

- **Tooltips own exact shortcuts, but one hint advertises they exist.** The bar
  never renders a shortcut *table* — each toolbar/segmented button keeps its
  `Alt+…` in its tooltip. But nothing on screen tells the user *which* controls
  even have shortcuts, so one dedicated discovery hint says "they exist, hover to
  see them" (see "Discovery" below). Exact keys stay in tooltips; the bar only
  points at them.
- **One context hint at a time**, short imperative "做 X → 得到 Y" (≤ ~22 full-width
  chars), gated to the current mode, and never repeated for something the user
  just did.

## Curated Content

Tier S = the meaningful operation points (hidden + high payoff). Tier A =
secondary, rotate after S. Everything not listed is intentionally dropped from
the bar (still reachable; some move to tooltips).

### Persistent (always-on, left side — universal hidden interactions)

| id | text | why it earns a slot |
| --- | --- | --- |
| `wheel.zoom_x` | `Ctrl + 滚轮 缩放 X` | modifier-only, invisible |
| `wheel.zoom_y` | `Shift + 滚轮 缩放 Y` | modifier-only, invisible |
| `chart.options` | `双击图面 打开图表选项` | no affordance for the dialog |

### Discovery — "this exists" (one-time, retire-on-use)

Some capabilities have **no on-screen cue that they exist at all** (not just a
hidden *how* — an invisible *what*). Each discovery hint advertises one such
capability and retires permanently the first time the user actually exercises it.
The retirement is persisted, so it never nags across relaunches.

Mechanics: a **single discovery slot** fed by a priority-ordered queue. Show the
highest-priority not-yet-retired item, one at a time; when its retire trigger
fires, flip its persisted flag and advance to the next. Never show more than one
discovery hint at once, and cap the shipped set so first launch is a nudge, not a
"did you know" wall.

| id | priority | text | retire trigger | ship |
| --- | --- | --- | --- | --- |
| `toolbar.shortcuts_exist` | 100 | `顶部按钮支持快捷键，悬停按钮即可查看` | any `Alt+…` shortcut fires | now |
| `chart.copy_image` | 95 | `复制按钮可导出带游标读数的图片，并打开标注编辑器` | first copy-as-image | now |
| `chart.right_click_menu` | 90 | `右键图表 → 查看全部 · 轴范围 · 网格 等选项` | first chart right-click | now |
| `channel.right_click` | 80 | `左侧通道右键 → 设为叠加图左轴` | first channel right-click | now |
| `view.history` | 60 | `图表可后退/前进到上一个视图（Alt+Z）` | first back/forward use | later |

Separate surface — `markup.capabilities` shows once **inside the markup editor**
the first time it opens (`裁剪 / 箭头 / 文字 / 序号，支持撤销`), retiring after the
editor has been opened once. It rides the editor's own one-shot flag, not the
chart bar's discovery queue. (later)

`chart.copy_image` supersedes the old context hint `chart.copy_includes_cursor`
(its text already states "带游标读数"), and `channel.right_click` supersedes the
rotating `overlay.left_axis` — both are dropped from the rotation below to avoid
saying the same thing twice.

### Rotating context — Tier S

| id | mode gate | text |
| --- | --- | --- |
| `overlay.drag_y` | time + overlay | `点击曲线后拖动 → 单独调该通道 Y 轴` |
| `subplot.wheel_target` | time + subplot | `滚轮作用于鼠标所在子图` |
| `cursor.dual_ab` | dual cursor | `点 A 点 B → 显示 ΔT 与区间统计` |
| `spectrogram.slice` | fft-vs-time | `点击谱图某一时刻 → 查看该帧频率切片` |
| `annotation.mode` | fft/order + annotation on | `左键添加标注 · 右键删除最近一处` |

### Rotating context — Tier A

| id | mode gate | text |
| --- | --- | --- |
| `subplot.shift_y` | time + subplot | `Shift + 滚轮 缩放当前子图 Y` |
| `zoom.guard` | overlay + zoom mode | `框选缩放时，拖框优先于选择曲线` |

(`toolbar.shortcuts_exist` is not in this rotation — it has its own one-time
discovery treatment above.)

### Dropped from the bar (rationale)

- Per-key `Alt+1…Alt+5`, `Alt+R/Z/G/B` lists → live in tooltips, not the bar.
- `右键图表 → 网格`, `关闭游标会清空读数卡`, `阶次图也支持复制/标注` → obvious or
  low payoff; would pad the bar toward manual-feel.
- `叠加时先把主信号设为左轴` (advice, not an operation) → drop.

## Surfaces

| surface | content | behavior |
| --- | --- | --- |
| Bottom bar — left | Persistent (≤3) | always visible while a chart card is shown |
| Bottom bar — right | One rotating context hint | mode-gated, slow rotation, pauses during interaction |
| Bottom bar — discovery | One queued "this exists" hint | highest-priority not-yet-retired item; each retires on first use (persisted) |
| Markup editor | `markup.capabilities` | one-shot inside the editor on first open (own flag) |
| Button tooltip | Exact command + shortcut | one per button; owns all `Alt+…` strings |

## Runtime Shape

A single registry module is the source of truth; the bar reads from it.

```
mf4_analyzer/ui/hints.py
```

```python
@dataclass(frozen=True)
class Hint:
    id: str
    text: str
    surface: str                 # "persistent" | "context" | "discovery"
    tier: str = "S"              # "S" | "A" (context only)
    modes: frozenset[str] = frozenset()        # {"time"} etc; empty = any
    plot_modes: frozenset[str] = frozenset()   # {"overlay"} / {"subplot"}
    cursor_modes: frozenset[str] = frozenset() # {"dual"} ...
    requires: frozenset[str] = frozenset()     # {"cursor_active","annotation_on"}
    retire_on: str | None = None  # discovery only: event id that retires it
    priority: int = 50

def persistent_hints() -> tuple[str, ...]
def context_hints(state: HintState) -> tuple[Hint, ...]    # filtered + priority-sorted
def discovery_hint(state: HintState) -> Hint | None        # top not-yet-retired
def shortcut_tooltip(action_key: str) -> str | None
```

`HintState` is a small immutable snapshot the chart card already knows:
`mode`, `plot_mode`, `cursor_mode`, `mouse_mode`, `chart_kind`,
`annotation_on`, `discovered` (persisted set of retired discovery ids — e.g.
`{"toolbar.shortcuts_exist"}` once a shortcut has fired), `recently_used`
(context ids to suppress this session).

Retire triggers map an in-app event to a discovery id; the chart card calls a
small `mark_discovered(id)` that adds it to the persisted `discovered` set. Wire
points: the nav/time-card shortcut handlers → `toolbar.shortcuts_exist`; the copy
button → `chart.copy_image`; the chart `customContextMenuRequested` →
`chart.right_click_menu`; `MultiFileChannelWidget._on_context_menu` →
`channel.right_click`; the view back/forward action → `view.history`.

## Behavior Rules

- Persistent left text is fixed and deterministic (no rotation).
- Right side shows `context_hints(state)`, highest priority first, one at a time,
  advancing every 8–12 s.
- **Pause** rotation during active drag / pan / zoom-box / cursor drag.
- **Refresh immediately** on explicit mode change (overlay↔subplot, cursor
  on/off, entering FFT-vs-Time) and show the top hint for the new state.
- **Suppress** a hint whose interaction the user just performed (id in
  `recently_used`) for the rest of the session.
- **Discovery slot** shows `discovery_hint(state)` — the highest-priority item
  whose id is not in `discovered`. When the user first exercises that capability,
  the wired retire trigger adds its id to the persisted `discovered` set; the slot
  advances to the next item, or goes empty once all are retired. At most one
  discovery hint is visible at a time, and never re-appears after relaunch.
- Tier S exhausts before Tier A within a state.
- No Markdown is parsed at runtime; `hints.py` is authoritative.

## Acceptance Criteria

- The persistent bar shows exactly the three universal hints; no shortcut table
  ever appears there.
- Switching to overlay surfaces `overlay.drag_y` first; switching to subplot
  surfaces `subplot.wheel_target` first; dual cursor surfaces `cursor.dual_ab`.
- A hint is not shown again after its interaction is performed in the session.
- Every toolbar button with a shortcut exposes it via tooltip.
- On a fresh profile the discovery slot shows `toolbar.shortcuts_exist` first;
  after a shortcut fires it shows `chart.copy_image`, then `chart.right_click_menu`,
  then `channel.right_click` — each only until its own capability is first used.
- A retired discovery id never reappears, including after relaunch (persisted
  `discovered` set); when all shipped items are retired the slot is empty.
- Existing hint strings/shortcuts that survive curation still appear; removed
  ones are gone from the bar but reachable as before.

## Tests

- `hints.py` unit tests: `context_hints` filtering by mode/plot_mode/cursor_mode,
  priority order, Tier S before A, `recently_used` suppression.
- chart_stack regression: persistent bar text equals the three curated lines;
  context layer asks the registry (no hard-coded context strings left).
- Discovery queue: `discovery_hint` returns items in priority order, skipping ids
  in `discovered`; `mark_discovered(id)` removes one and exposes the next; an
  empty queue returns `None`; the `discovered` set round-trips through the
  persisted store (reload keeps retired items hidden).
- A doc-sync test (Phase 5) that every id in this design exists in `hints.py`.
