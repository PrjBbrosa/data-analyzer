# Analyzer UI Hints

This document tracks user-facing hint text for the Analyzer chart area. It is a
planning and product reference only for now. Runtime hint strings currently
live in `mf4_analyzer/ui/chart_stack.py`; a later implementation should move
them into a dedicated UI hint registry module.

## Goals

- Keep hidden chart interactions discoverable without adding modal tutorials.
- Keep the bottom hint bar useful as features grow.
- Make shortcut discovery explicit, especially for toolbar buttons.
- Avoid scattering hint copy across widget code without an inventory.
- Preserve a clear path for later randomized/context-aware hints.

## Current State

Runtime hints are not a standalone module yet.

| Area | Current source | Notes |
| --- | --- | --- |
| Top toolbar mode hint | `chart_stack.py` `_TOOL_HINTS` | Changes with pan/zoom/idle mode. |
| Bottom persistent hint | `chart_stack.py` `_BOTTOM_HINT_PERSISTENT` | Shows fixed shortcuts like `Ctrl + wheel`, `Shift + wheel`, double-click chart options. |
| Bottom context hint | `chart_stack.py` `_BOTTOM_HINT_CONTEXT` | Changes for pan, zoom, cursor, spectrogram states. |
| Navigation shortcuts | `chart_stack.py` `_NAV_SHORTCUTS` | `Alt+R`, `Alt+Z`, `Alt+Shift+Z`, `Alt+G`, `Alt+B`. |
| Time chart shortcuts | `chart_stack.py` `_TIME_CARD_SHORTCUTS` | `Alt+1` through `Alt+5` for split/overlay/cursor controls. |
| Channel-tree context action | `widgets/__init__.py` `MultiFileChannelWidget._on_context_menu` | Right-click channel -> `设为左轴`. |
| Pyqtgraph right-click chart menu | `pg_canvases.py` context menu reshape helpers | Keeps `查看全部`, `X 轴范围`, `Y 轴范围`, `鼠标操作`, `网格`. |

## Proposed Runtime Shape

Do this later as a separate module, not in the current cleanup.

Target module:

```text
mf4_analyzer/ui/hints.py
```

Recommended data model:

```python
Hint(
    id="time.overlay.select_drag_y",
    surface="bottom_context",
    modes={"time"},
    plot_modes={"overlay"},
    priority=90,
    text="叠加模式：点击曲线后拖动，可单独移动该通道 Y 轴",
)
```

Keep a lightweight API:

- `persistent_hints() -> tuple[str, ...]`
- `context_hints(state) -> tuple[Hint, ...]`
- `shortcut_hints() -> tuple[Hint, ...]`
- `random_hint(state, seed=None) -> Hint | None`

The UI should not parse this Markdown at runtime. This file documents product
intent; `ui/hints.py` should be the runtime source of truth.

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
| `shortcut.home` | P0 | `Alt+R：还原视图` | Rotating / shortcut group |
| `shortcut.back_forward` | P0 | `Alt+Z / Alt+Shift+Z：图表视图后退 / 前进` | Rotating / shortcut group |
| `shortcut.pan` | P0 | `Alt+G：平移模式` | Rotating / shortcut group |
| `shortcut.zoom` | P0 | `Alt+B：框选缩放` | Rotating / shortcut group |
| `shortcut.time.layout` | P0 | `Alt+1 / Alt+2：分屏 / 叠加` | Time mode rotating |
| `shortcut.cursor` | P0 | `Alt+3 / Alt+4 / Alt+5：关闭游标 / 单游标 / 双游标` | Time mode rotating |

### Time Overlay Mode

| ID | Priority | Text | Trigger / Surface |
| --- | --- | --- | --- |
| `time.overlay.select_drag_y` | P0 | `叠加模式：点击曲线后拖动，可单独移动该通道 Y 轴` | Time + overlay |
| `time.overlay.blank_deselect` | P0 | `叠加模式：点击空白区域可取消当前曲线选择` | Time + overlay |
| `time.overlay.left_axis` | P0 | `左侧通道树右键通道，可设为叠加图左轴` | Time + overlay |
| `time.overlay.primary_focus` | P1 | `多通道叠加时，先把主关注信号设为左轴更容易对比` | Time + overlay |
| `time.overlay.zoom_guard` | P1 | `框选缩放开启时，拖框优先于曲线选择` | Time + overlay + zoom |

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

## Initial Implementation Plan

### Phase 1 - Documented Inventory Only

Status: this document.

- Keep current runtime behavior unchanged.
- Use this file as the first product inventory.
- Do not introduce a runtime module yet.

### Phase 2 - Runtime Hint Registry

- Add `mf4_analyzer/ui/hints.py`.
- Move `_TOOL_HINTS`, `_BOTTOM_HINT_PERSISTENT`, `_BOTTOM_HINT_CONTEXT`,
  `_NAV_SHORTCUTS`, and `_TIME_CARD_SHORTCUTS` into structured definitions or
  expose them through compatibility functions.
- Keep `chart_stack.py` behavior identical except for importing from the new
  registry.
- Add tests that prove existing hint text and shortcuts still appear.

### Phase 3 - Context-Aware Rotation

- Keep the left side of the bottom bar persistent.
- Use the right side for rotating hints selected by current state:
  `mode`, `plot_mode`, `cursor_mode`, toolbar mouse mode, selected overlay
  channel, and active chart card.
- Rotate slowly, for example every 8-12 seconds.
- Reset/refresh immediately after explicit user actions such as switching to
  overlay, enabling a cursor, or entering FFT vs Time.
- Avoid random hints during active drag, pan, zoom, or cursor movement.

### Phase 4 - Shortcut Discoverability

- Add a rotating hint for toolbar shortcuts: `顶部按钮支持快捷键，悬停可查看`.
- Ensure every toolbar button tooltip includes its shortcut where one exists.
- Consider a future `?` or command-palette style overlay only if the hint bar
  proves insufficient.

### Phase 5 - Documentation Sync Check

- Add a small check that extracts hint IDs from this document and validates
  they exist in `ui/hints.py`, or invert the direction and generate this table
  from the runtime registry.
- Prefer generated documentation once the registry stabilizes.

## Open Decisions

- Whether the rotating hint order should be deterministic per session or truly
  random.
- Whether bottom-bar hints should include icons or stay text-only.
- Whether hints should be suppressible by users.
- Whether channel-tree hints should appear in the status bar, bottom chart bar,
  or as a one-time inline affordance.

## Non-Goals For The First Module Pass

- No onboarding wizard.
- No modal tutorial.
- No Markdown parsing at runtime.
- No large UI redesign of the chart toolbar.
- No removal of existing button tooltips or shortcuts.
