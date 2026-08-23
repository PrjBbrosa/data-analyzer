# UltraView Author Chrome Product Fixes — W0 Inventory

Date: 2026-08-23

## 1. Execution snapshot

```
HEAD: da932d347c3128c20a006030d1dac7e78b9584ef
branch: main
git status --short:
?? docs/analyzer/plans/2026-08-23-ultraview-author-chrome-product-fixes-plan.md
?? ssh-keygen
?? ssh-keygen.pub
running pytest: none
```

Owner file hashes at start:

| file | sha1 |
|---|---|
| author_style.py | 56ffdf2ee3e47e233babe0c71fddf1fc6f68d5e7 |
| author_chrome.py | a1850e6995f0cda654a61e6790bc3848f5f2a76b |
| author_selection.py | aa88436bce321354c5e33fbf099b3b17dde87b7d |
| author_ui_controller.py | 137a68e3fe42de0b87e81c6dd8229c722b69256b |
| chrome_popovers.py | d3cba190a3a3d5861855119ee32bd0c08f06dc52 |
| laser_cursor.py | e47a1332151e2ff9531060e64e576c554e9b1d2f |
| free_grid_board.py | f5a34f89f675d65271842caac1d0f89032992f9c |
| free_grid_author_controller.py | f7e91cd6ee1aad992c66b412489c5c5f15cb58b3 |

Path correction vs plan §4.2: live owners are under `mf4_analyzer/ui/chart_stack/ultraview/`, not `mf4_analyzer/ui/ultraview/`. `author_interaction.py` does not exist; interaction lives on `author_tools.BoardInteractionController` plus `free_grid_author_controller.py`. `author_ops.py` is `author_edits.py`.

## 2. Control matrix

| object | toolbar key | picker key | presentation | data semantic |
|---|---|---|---|---|
| Sticky | palette | palette | swatch | sticky fill token |
| Sticky | font_size | font_size | font_size | auto/12/14/18/24 |
| Sticky | shape (REMOVE visible) | shape | labels | persisted `StickyObject.shape` |
| Text | font_role | font_role | font | sans/serif/mono |
| Text | font_size | font_size | font_size | 8–72 |
| Text | bold/italic/underline | — | glyph | bool |
| Text | align | align | align | left/center/right |
| Text | list_style | list_style | list | none/bullet/number |
| Text | text_palette | text_palette | swatch | ink role |
| Text | fill_palette | fill_palette | swatch | fill role; None=transparent |
| Text | link (REMOVE visible) | — | icon | persisted `TextObject.link` |
| Shape | shape | shape | shape | closed V1 types |
| Shape | fill | fill | swatch | fill; None=transparent |
| Shape | stroke | stroke | swatch | stroke/ink |
| Shape | width | width | line_width | 1/2/4/8 |
| Shape | dash | dash | dash | solid/dashed |
| Shape | corner | corner | corner | 0/8/16/24 |
| Connector | route/start_head/end_head | same | route/head | straight/elbow; none/arrow |
| Connector | color | color | swatch | stroke |
| Connector | width/dash | same | line_width/dash | same as shape |
| Stroke | tool | tool | tool | pen/highlighter |
| Stroke | color | color | swatch | ink |
| Stroke | width | width | line_width | 2/4/8/16 |
| mixed/single | duplicate (REMOVE visible) | — | icon | `can_duplicate` stays True |

## 3. Overlay matrix

| overlay | size owner | placement owner | production QSS |
|---|---|---|---|
| selection toolbar | SelectionToolbar 48px | Page / author_ui_controller | objectName ultraViewSelectionToolbar |
| format picker | FormatChoiceFlyout content_size | author_ui_controller.format_picker_rect (6 px gap already) | ToolFlyoutSurface inner |
| Sticky/Shape/Draw/Pointer flyouts | each popover min_width | author_ui_controller | ToolFlyoutSurface |
| Layout picker | LayoutPicker sizeHint; Page._overlay_size min (360,240) uses hint | Page clamp | ultraViewLayoutPopover |
| Template/Overview/Presenter/Share/Settings | Page overlay size | Page clamp | chrome_popovers / islands |

## 4. Cursor matrix (current)

| mode | hit | hover | drag | release | owner |
|---|---|---|---|---|---|
| pan / space | any | Open/ClosedHand | locked pan | restore | viewport_controller |
| forbidden | safety | ForbiddenCursor | ForbiddenCursor | unset if was forbidden | free_grid_board.apply_safety_cursor |
| create sticky/draw | blank | CrossCursor | CrossCursor | tool cursor | free_grid_board / page._sync_tool_cursor |
| card resize handle | N/S/E/W/NE… | HANDLE_CURSORS | stays on card | unset | free_grid_board.handle_card_mouse_hover |
| author resize handle | eight handles | **missing** | no cursor lock | laser/default flash risk | selected_handle_at exists; cursor not applied |
| Laser | blank | bitmap 32×32 option B glowing disc, hotspot (16,16) | same | same | laser_cursor.py / icons.paint_laser_glow |
| Pointer | blank | unset / Arrow | — | — | pointer_cursor() None |

## 5. Stale tests to update intentionally

| file | assertion | new expectation |
|---|---|---|
| tests/ui/test_ultraview_author_chrome.py | font picker width 152–168 | 112–120 |
| tests/ui/test_ultraview_author_chrome.py | `button("shape") or button("font_role")` on default sticky toolbar | palette/font_size |
| tests/ui/test_ultraview_author_multiselect.py | `"duplicate" in keys`, toolbar.button("duplicate") | keys omit duplicate; can_duplicate True; shortcut still works |
| tests/ui/test_ultraview_author_multiselect.py | click toolbar duplicate for one-history | Ctrl/Cmd+D |
| tests/ui/test_ultraview_author_tools.py | laser pixmap 32×32, hotspot (25,5) | W6 after G-LASER; leave until then |
| tests/test_verify_ultraview_visuals.py | expected_hotspot [25,5] | W6 after G-LASER |
| tests/ui/test_quickref.py | Text 图标栏 includes 链接 | drop 链接 from visible chrome copy |
| tools/verify_ultraview_visuals.py | hotspot (25,5) | W6 after G-LASER |

## 6. Dirty files

Plan-in (this task may add):

- docs/analyzer/plans/2026-08-23-ultraview-author-chrome-product-fixes-plan.md (pre-existing untracked)
- docs/analyzer/verify/2026-08-23-ultraview-author-chrome-product-fixes/
- docs/analyzer/ui-prototypes/2026-08-23-ultraview-laser-cursor-options.html
- listed owner sources, tests, hints, quickref, tools/verify_ultraview_visuals.py

Plan-out (do not stage):

- ssh-keygen, ssh-keygen.pub
- any unrelated dirty UltraView work (none at start besides the plan file)

## 7. Lessons loaded

- Rounded Qt popups need translucent shell
- Codex Qt rounded popup chrome
- Visual parity requires rendered screenshot
- Keep headless PyQt fixtures deterministic

## 8. W0 gate

- [x] matrices and owners recorded
- [x] stale assertions listed
- [x] product behavior unchanged in this inventory-only wave
- Fail-first tests land in W1–W5 with the owner change of that wave
