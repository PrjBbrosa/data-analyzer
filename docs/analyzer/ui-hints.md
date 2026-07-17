# Analyzer UI Hints

This document tracks the user-facing discovery system for the Analyzer chart
area. The runtime source of truth is `mf4_analyzer/ui/hints.py`; this file is a
maintainer-facing map of its surfaces, shortcut contracts, and review rules.

## Goals

- Keep hidden chart interactions discoverable without adding modal tutorials.
- Keep the bottom hint bar useful as features grow.
- Make shortcut discovery explicit, especially for toolbar buttons.
- Keep hint copy centralized and testable.
- Let frequently used gestures retire so the footer becomes quieter over time.

## Current State

The standalone registry, context-aware rotation, discovery retirement, and
situational nudges are implemented. `chart_stack` consumes the registry through
compatibility helpers; the UI never parses this Markdown.

| Area | Current source | Notes |
| --- | --- | --- |
| Registry and state matching | `hints.py` `Hint`, `HintState`, `_HINTS` | Persistent, context, anchor, discovery, rotation, and nudge surfaces. |
| Navigation shortcuts | `hints.py` `NAV_SHORTCUTS` | `Ctrl+R`, `Ctrl+Z`, `Ctrl+Shift+Z`, `Ctrl+G`, `Ctrl+B`. |
| Time chart shortcuts | `hints.py` `TIME_CARD_SHORTCUTS` | `Ctrl+1` through `Ctrl+5` for split/overlay/cursor controls. |
| One-shot feedback | `hints.py` `_FLASH_TIPS` | Immediate copy for gestures and explicit actions. |
| Discovery persistence | `hints.py` `load_discovered`, `mark_discovered` | Stores retired discoveries in `chartHints/discovered`. |
| Channel-tree context action | `widgets/__init__.py` `MultiFileChannelWidget._on_context_menu` | Right-click channel -> `设为左轴`. |
| Pyqtgraph right-click chart menu | `pg_canvases.py` context menu reshape helpers | Keeps `查看全部`, `X 轴范围`, `Y 轴范围`, `鼠标操作`, `网格`. |
| Markup editor capability card | `markup/editor.py` `_maybe_show_capability_hint` | One-shot `markup.capabilities` toast on first open (scope="markup"); retires via shared `chartHints/discovered`. |

## Runtime API

Maintainers should use these public helpers instead of duplicating strings:

- `all_hints() -> tuple[Hint, ...]`
- `persistent_hints() -> tuple[str, ...]`
- `shortcut_tooltip(action_key) -> str`
- `context_hints(state)`, `rotation_hints(state)`
- `discovery_hint(state)`, `nudge_hint(state)`
- `load_discovered(settings)`, `mark_discovered(settings, hint_id)`

## Hint Surfaces

| Surface | Purpose | Behavior |
| --- | --- | --- |
| Top toolbar hint | Explain current mouse/navigation mode. | Immediate, deterministic, mode-driven. |
| Bottom persistent hint | Stable high-value shortcuts. | Always visible when chart card is visible. |
| Bottom rotating hint | Discoverability for hidden interactions. | Context-aware, rotates slowly, pauses on explicit mode changes. |
| Button tooltip | Exact command and shortcut. | One tooltip per toolbar/control button. |
| Channel-tree tooltip/status hint | Explain channel context actions. | Optional; use for `设为左轴` discoverability. |

## Candidate Hints

Priority legend:

- P0: should be visible in first implementation.
- P1: good rotating hints after P0 lands.
- P2: useful but avoid crowding the main hint bar.

### Persistent Shortcuts

| ID | Priority | Text | Trigger / Surface |
| --- | --- | --- | --- |
| `shortcut.wheel.x` | P0 | `Ctrl + 滚轮：缩放 X` | Bottom persistent |
| `shortcut.wheel.y` | P0 | `Shift + 滚轮：缩放 Y` | Bottom persistent |
| `chart.options.double_click` | P0 | `双击图面：图表选项` | Bottom persistent |
| `shortcut.toolbar.discover` | P0 | `顶部按钮支持快捷键，悬停可查看` | Bottom rotating |

### Toolbar Shortcuts

| ID | Priority | Text | Trigger / Surface |
| --- | --- | --- | --- |
| `shortcut.home` | P0 | `Ctrl+R：还原视图` | Rotating / shortcut group |
| `shortcut.back_forward` | P0 | `Ctrl+Z / Ctrl+Shift+Z：图表视图后退 / 前进` | Rotating / shortcut group |
| `shortcut.pan` | P0 | `Ctrl+G：平移模式` | Rotating / shortcut group |
| `shortcut.zoom` | P0 | `Ctrl+B：框选缩放` | Rotating / shortcut group |
| `shortcut.time.layout` | P0 | `Ctrl+1 / Ctrl+2：分屏 / 叠加` | Time mode rotating |
| `shortcut.cursor` | P0 | `Ctrl+3 / Ctrl+4 / Ctrl+5：关闭游标 / 单游标 / 双游标` | Time mode rotating |

### Time Overlay Mode

| ID | Priority | Text | Trigger / Surface |
| --- | --- | --- | --- |
| `overlay.drag_y` | P0 | `双击曲线或其 Y 轴 → 改颜色/范围` | Time + overlay |
| `wheel.zoom_y` | P0 | `Shift + 滚轮：缩放当前通道 Y 轴` | Time + overlay/subplot |
| `time.overlay.left_axis` | P0 | `左侧通道树右键通道，可设为叠加图左轴` | Time + overlay |
| `coaxis.merge` | P1 | `多选通道右键可合并为共轴比幅值` | Time + overlay/subplot |

### Time Subplot Mode

| ID | Priority | Text | Trigger / Surface |
| --- | --- | --- | --- |
| `time.subplot.wheel_target` | P0 | `分屏模式：鼠标在哪个子图上，滚轮就作用于哪个子图` | Time + subplot |
| `time.subplot.shift_y` | P0 | `Shift + 滚轮：缩放当前子图 Y 轴` | Time + subplot |
| `time.subplot.plain_y_pan` | P1 | `普通滚轮：平移当前子图 Y 轴` | Time + subplot |
| `time.subplot.ctrl_x` | P1 | `Ctrl + 滚轮：缩放所有子图共享 X 轴` | Time + subplot |

### Cursor Modes

| ID | Priority | Text | Trigger / Surface |
| --- | --- | --- | --- |
| `cursor.single.place` | P0 | `单游标：点击图面放置读数线` | Single cursor |
| `cursor.card.drag` | P0 | `游标读数卡可拖到合适位置` | Single / dual cursor |
| `cursor.dual.place_ab` | P0 | `双游标：第一次点击放 A，第二次点击放 B` | Dual cursor |
| `cursor.dual.stats` | P1 | `双游标会显示 ΔT 和区间统计` | Dual cursor |
| `cursor.off.clear` | P2 | `关闭游标会清空当前读数卡` | Cursor mode change |

### Chart Context Menu

| ID | Priority | Text | Trigger / Surface |
| --- | --- | --- | --- |
| `menu.right_click.chart` | P1 | `右键图表：查看全部、设置轴范围、切换鼠标操作和网格` | Any chart |
| `menu.view_all` | P1 | `右键图表 -> 查看全部：回到完整数据范围` | Any chart |
| `menu.mouse_mode` | P1 | `右键图表 -> 鼠标操作：也能切换平移 / 框选` | Any chart |
| `menu.grid` | P2 | `右键图表 -> 网格：可切换 X/Y 网格` | Any chart |

### FFT / FFT vs Time / Order

| ID | Priority | Text | Trigger / Surface |
| --- | --- | --- | --- |
| `fft.annotation` | P1 | `标注模式：左键添加标注，右键删除最近标注` | FFT / FFT vs Time / Order with annotation enabled |
| `chart.copy_image` | P1 | `复制为图片会包含游标线和读数卡` | Any chart |
| `spectrogram.slice` | P0 | `FFT vs Time：点击谱图某一时刻可查看该帧频率切片` | FFT vs Time |
| `order.context` | P2 | `阶次图同样支持图表选项、复制图片和标注` | Order |

## Maintenance Checklist

1. Review recent UI commits for new gestures, right-click actions, shortcuts,
   staged capabilities, and removed interactions.
2. Put only non-obvious interactions in the rotating footer; keep every
   operation, including file formats and ordinary buttons, in `quickref.py`.
3. Reuse `shortcut_tooltip()` for keyboard chips. Never repeat literal shortcut
   strings in the quick-reference catalog.
4. Keep every hint within `HINT_MAX_WIDTH`; gate it by mode/state and add a
   discovery or retirement signal when the gesture can be observed.
5. For staged work, pair `Hint(ship="later")` with `QuickRow(soon=True)` and
   release both flags together.
6. Run `tests/ui/test_hints.py`, `tests/ui/test_quickref.py`, and rendered panel
   checks after changing user-facing copy.

## Open Decisions

- Whether the rotating hint order should be deterministic per session or truly
  random.
- Whether bottom-bar hints should include icons or stay text-only.
- Whether hints should be suppressible by users.
- Whether channel-tree hints should appear in the status bar, bottom chart bar,
  or as a one-time inline affordance.

## Non-Goals

- No onboarding wizard.
- No modal tutorial.
- No Markdown parsing at runtime.
- No large UI redesign of the chart toolbar.
- No removal of existing button tooltips or shortcuts.
