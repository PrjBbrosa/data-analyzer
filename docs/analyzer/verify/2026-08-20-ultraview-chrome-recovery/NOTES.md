# Offscreen structure对照（非 Cocoa 验收）

- 日期：2026-08-20
- 状态：**CODE COMPLETE / FOREGROUND UNVERIFIED**
- 对照原型：`docs/analyzer/ui-prototypes/screenshots/2026-08-20-ultraview-miro-authoring/`
- 本目录 PNG 由 `render_offscreen.py` 在 `QT_QPA_PLATFORM=offscreen` 下抓取。
  **不能**写成 Cocoa 视觉验收。

## 结构对照

| 抓图 | 对照点 | 结论 |
|---|---|---|
| `selected-card-toolbar.png` | 工具条贴在选中卡片上方，不是钉死 `y=56`；Spine 为 `TIME`；卡片动作 open/sync/focus/fit/复制图；无 Duplicate；Delete 在 `⋯` | 符合 T1/T2/T3/T4 |
| `selected-shape-toolbar.png` | Spine `SHAPE`；类型/填充/描边/线宽/线型/圆角/文字；Delete 不在常驻行 | 符合 T2/T4 |
| `sticky-flyout.png` | 色板 +「固定连续创建」按内容收紧，无 248×220 空盒 | 符合 T5 |
| `compact-800x560.png` | 宽按钮溢出（同步/复制图进 More）；工具条仍单行；rail 仍是 Select/Sticky/Text/Shapes | 符合 T1 compact / E1 |

## Release rail

offscreen 图中创作段为指针、便签、文字、形状四枚，**没有** Connector / Draw 入口。这是 E1：D5 命中门未在 Cocoa 前台验收前保持收回。

## 预览白底

卡片预览仍是不透明蓝块（测试 `FakePreview`），D9 不在本 Spec。
