# UltraView P2 受控自由网格与单卡检查规格

- 日期：2026-08-13
- 状态：`P2-A Core IMPLEMENTED 2026-08-14；P2-B NO-GO（见 capability audit）；前景/Cocoa 与高级手势验收另行记录`
- 配套计划：
  `docs/analyzer/plans/2026-08-13-ultraview-p2-flex-grid-and-inspection-implementation.md`
- 上游 P1 规格：
  `docs/analyzer/specs/2026-08-13-ultraview-p1-scalable-board-workspace-spec.md`
- P0 产品边界：
  `docs/analyzer/specs/2026-08-12-ultraview-p0-spec.md`

## 0. 结论与产品定位

P2 在 P1 多 Board/12 图静态工作区上增加两类能力：

1. **受控自由网格**：用户可以移动卡片、调整宽高、保存自定义布局，单 Board 最多 24 张；
2. **单卡检查**：一次将一张卡片临时提升为独立 live inspection canvas，进行局部缩放、
   平移和游标读取，其余卡片仍是静态快照，并可显示兼容轴的只读引导线。

P2 不是无限画布，也不是第二套完整分析工作区。它保持三条不可突破的边界：

- Board 布局只拥有几何和引用，不拥有源分析参数；
- 同一时刻最多一个 live inspection canvas；
- Board 内操作不调用任何分析计算，cache/result 不足时检查模式不可用而不是补算。

## 1. P2 启动门槛

P2 只有在 P1 Core 完成后启动：

- 多 Board schema 2、sidecar、shared residency、12 图逻辑画布已经稳定；
- P1 完整零计算、lifecycle、Cocoa 和两进程 suite 已有当前证据；
- 12 图性能 baseline 已建立；
- P1 verification 没有 unresolved P0/P1 blocker。

若 P1 尚未完成，P2 状态为 `BLOCKED BY P1`。实施者不得一边改 schema 1→2，一边再塞入
自由 geometry schema；迁移链必须分阶段、可测试。

## 2. 用户场景

### 2.1 证据权重不同

时域主趋势需要一张很宽的卡，三个 FFT 只需标准卡，两张时频图需要更高区域。固定
3×3/4×3无法表达证据权重，用户需要在同一 Board 中组合宽图、大图和辅助图。

### 2.2 12 图以上的问题墙

复杂项目可能有 15～20 个关键 View。用户希望在一张可向下增长的大 Board 中按系统、
位置或工况排布，而不是创建大量固定模板 Board；同时仍要有容量、最小尺寸和性能边界。

### 2.3 从全局异常进入局部检查

用户在全局 Board 发现峰值或时段异常后，希望直接放大这一张、读取光标，并在几个同轴
卡片上看到同一 X 位置，而不先跳回源工作区。需要修改参数、重算或编辑标注时仍然点击
“打开原 View”。

## 3. P2 目标与非目标

### 3.1 必须交付

- 12 列、可向下增长的整数自由网格；
- 单 Board 最多 24 个 placed cards；更多 refs 进入 tray；
- 卡片拖动、键盘移动、边缘/角落 resize 和尺寸预设；
- 确定性碰撞处理、边界限制、压缩空行、撤销/重做和“整理布局”；
- 固定模板与自由网格之间的安全转换；
- 自定义 geometry 的项目持久化、迁移和完整 Board 导出；
- minimap/整板概览与快速定位；
- 单卡 live inspection：pan/zoom/cursor/Home，最多一张；
- 同轴兼容卡片上的只读 X 引导和范围提示；
- 零分析计算、内存、性能、生命周期、帮助和前景验收。

### 3.2 明确不做

- 不做任意像素坐标、浮点百分比坐标、卡片重叠或 z-order；
- 不做无限宽画布；列数固定 12，只有行向下增长；
- 不做任意旋转、叠层、连线、便签、绘图标注或报告排版；
- 不超过 24 个 placed cards；
- 不同时 live 多张卡片；
- 不从源 QWidget reparent；
- 不在 inspection 中修改源 View、参数、数据源、过滤器、轴单位或标注；
- 不在 inspection 中触发 cache restore/recompute；
- 不把 inspection 的局部范围写回 canonical PreviewRecord 并标 fresh；
- 不跨轴类别或不兼容单位自动换算/同步；
- 不做 Y 轴联动、热图 color level 联动或跨域“智能对齐”；
- 不保存 inspection session、游标位置、undo stack、selection 或 minimap viewport 到项目；
- 不以模板/原型截图替代真实运行证据。

## 4. 受控自由网格模型

### 4.1 为什么不是像素自由画布

P2 使用整数网格而不是 `x/y/width/height` 像素：

- 跨 1280/1600/Retina 屏幕稳定；
- 项目 round-trip 与导出可复现；
- hit-test、键盘移动、碰撞和 accessibility 可确定；
- 不需要保存当前窗口尺寸；
- 避免浮点漂移、半像素边框和恢复后重叠。

### 4.2 几何 DTO

```python
@dataclass(frozen=True)
class GridRect:
    column: int       # 0..11
    row: int          # 0..MAX_GRID_ROWS-1
    column_span: int  # 2..12
    row_span: int     # 2..8

@dataclass
class FreeGridPlacement:
    ref: UltraViewRef
    rect: GridRect
```

合同：

- `GRID_COLUMNS = 12`；
- `MAX_PLACED_CARDS = 24`；
- `MAX_GRID_ROWS = 48`，防止恶意/损坏项目创建无限 QWidget/图片；
- `MAX_BOARD_MEMBERSHIP = 200`：placed+tray 合计硬上限，敌意 payload 截断并 warning；
- `MAX_UI_BOARDS = 20`：UI 新建/复制上限；loader 超过 20 全部保留并 `ui_board_limit` warning；
- 最小 span `2×2`；
- 单卡最大 `12×8`；
- rect 必须在 12 列和 48 行内且互不重叠；
- UI 添加第 25 张 placed card 时进入 tray；loader 对超限合法 refs 也迁入 tray并 warning，
  不能静默删除；
- row 是逻辑身份的一部分，但 `compact` 动作允许确定性改变 row；正常打开项目不自动 compact。

`2×2` 等数字是网格单位，不是像素。像素合同（`GridMetrics`）冻结为：
`GRID_MIN_COLUMN_WIDTH = 96`、`GRID_ROW_HEIGHT = 88`、屏幕空板
`GRID_MIN_VISIBLE_ROWS = 6`。导出用 `export_grid_metrics`（`min_visible_rows=1`，
高度不垫到 900）。列宽 `max(96, usable_width // 12)`；viewport 不足则横向滚动，
不把网格单元缩到不可读。

### 4.3 尺寸预设

P2 提供可发现的尺寸角色：

| 角色 | 默认 span | 典型用途 |
|---|---:|---|
| 小 | 3×2 | 辅助 FFT/状态图 |
| 标准 | 4×3 | 普通时域/频谱 |
| 宽 | 6×3 | 时域、FRF |
| 高 | 4×5 | 时频、阶次热图 |
| 大 | 6×6 | 主要证据 |
| 横幅 | 12×4 | 全宽趋势 |

用户可以继续拖动 resize handle 调整整数 span。最小尺寸、最大尺寸和碰撞规则始终生效。
预设是快捷操作，不是新的卡片类型；同一个 View 可以随时换角色。

### 4.4 Board layout mode

每张 Board 保存：

```text
layout_mode = "template" | "free_grid"
```

- template 模式继续使用 P1 的 `layout_id/primary_ratio/CardPlacement(slot_id)`；
- free_grid 模式使用 `FreeGridPlacement(rect)`；
- 同一时刻只有一种 placement 表示是 active；codec 不允许两个集合同时生效；
- `show_titles/show_sources` 继续 Board 级；
- free grid 可保存一个默认新卡尺寸 preset，但不保存 window pixel size。

## 5. 模板与自由网格转换

### 5.1 模板 → 自由网格

切换时：

- 对 2/4/6/9/12 模板使用固定 conversion map，最大程度保持相对位置；
- 现有 placed refs 全部转换成合法 GridRect；
- tray 不变；
- 转换是一个可撤销 command；
- 原 template state 保存在本次 undo command 中，不写 transient stack 入项目；
- 保存项目后只写转换后的 free grid。

### 5.2 自由网格 → 模板

该操作可能丢失尺寸/位置，因此必须显示预览与确认：

- 按 `(row, column, stable ref)` 排序；
- 前 N 个填入目标模板 slots；
- 超出容量 refs 进入 tray；
- 不删除 membership；
- 确认前原 Board 不变；
- 转换后可立即 Undo；关闭项目后 undo stack 不恢复。

### 5.3 “整理布局”不是自动修复

`整理布局` 只在用户显式操作时执行：保持 column/span，按稳定顺序向上消除完全空行，
不横向挤压、不改变尺寸、不改变相对前后。项目加载不能自动整理合法布局，否则恢复结果
会与保存时不同。

## 6. 移动、Resize 与碰撞合同

### 6.1 手势状态机

```text
Idle
  → Pressed(card/handle)
  → DragPreview or ResizePreview
  → Commit | Cancel
```

- Press 后超过平台 drag threshold 才进入预览；
- 拖动过程只更新轻量 outline/ghost，不每帧重建全部卡片；
- Commit 一次写入 BoardState 并进入 undo stack；
- Esc、失焦、窗口关闭、Board 切换、项目 reset 取消，不留下半状态；
- source ref drag 和 card layout drag 使用不同 MIME/gesture context，不混淆。

### 6.2 碰撞策略

P2 默认 **不自动推挤其他卡片**。候选 rect 与其他卡重叠时：

- ghost 显示无效状态；
- mouse release 不提交，并给出轻量提示；
- 可通过“交换位置”命令仅在两个 rect 尺寸完全相同且互换后都合法时执行；
- 不实现连锁 reflow，避免一次拖动重排 20 张图且难以撤销。

这一策略牺牲部分“自由感”，换取确定性、低抖动和可复现导出。若以后要自动 packing，
必须单独 specification + property tests，不能在 P2 实现中临时加入。

### 6.3 键盘等价路径

- Alt/Option + Arrow：移动 1 格；
- Alt/Option + Shift + Arrow：沿对应边 resize 1 格；
- 尺寸 preset 可从卡片菜单/Inspector选择；
- Ctrl/Cmd+Z / Ctrl/Cmd+Shift+Z：Board layout undo/redo；
- 无效移动不提交 command；
- screen reader 报告当前位置与尺寸，例如“第 2 行第 1 列，宽 6 高 3”。

快捷键最终必须遵守现有应用 shortcut 冲突检查，若与 macOS 保留键冲突应调整并同步帮助，
不能只写进文档不验证。

## 7. Undo/Redo 所有权

每张 active Board 在当前工具窗会话内拥有布局 command stack：

- move、resize、preset、swap、template↔free conversion、organize 各是一条 command；
- 连续同一 resize gesture 合并为一条 command；
- add/remove/rebind 是否进入同一 stack由实现前先冻结现有P1行为；P2最低要求只覆盖geometry；
- 切 Board切换到对应内存stack；关闭工具窗可清stack但不改已提交BoardState；
- project reset/open清全部stack；
- undo stack不持久化，不进入`.tlproj`；
- command只存before/after Qt-free geometry，不持有QWidget/QImage/coordinator。

## 8. 自由网格屏幕布局、Minimap 与概览

### 8.1 像素映射

Board 宽度由 12 列和 viewport 决定，但列宽不能低于 `GRID_MIN_COLUMN_WIDTH = 96`；
不足时横向滚动。行高固定 `GRID_ROW_HEIGHT = 88`，与 column width 不强制相同，使宽图/热图
可组合。纯函数 `grid_metrics` + `rect_to_pixels` 从 `GridRect + GridMetrics` 生成 pixel
rect，screen / compositor / hit-test / 整板概览共享。导出走 `export_grid_metrics`
（裁掉 viewport 尾白），屏幕仍按 viewport 与 6 行可读地板。

### 8.2 画布增长

logical Board高度由最底 placed rect + padding决定，最多48行。删除底部卡片后可以缩短
尾部空白，但不能自动改变其他卡片row。scroll position是瞬态，不进项目。

### 8.3 Minimap

P2 在大 Board右下提供可隐藏minimap：

- 显示全部card bounds、状态颜色/section色点和当前viewport；
- 点击/拖动viewport框只滚动Board；
- minimap不显示曲线缩略图，避免第二份图像和频繁缩放；
- keyboard可聚焦并按方向/Page移动viewport；
- presentation可显示minimap或整板overview，按用户设置；该选择暂不持久化。

整板overview继续使用compositor QImage并支持点击card定位。24图时overview是全局导航，
不是读取详细曲线的替代。

## 9. 自由网格项目持久化

### 9.1 Nested schema 3

顶层项目schema继续为2；UltraView nested schema从P1的2升到3：

```json
{
  "ultraview": {
    "schema": 3,
    "workspace": {
      "active_board_id": "board-a",
      "boards": [
        {
          "board_id": "board-a",
          "name": "问题墙",
          "layout_mode": "free_grid",
          "free_grid": {
            "columns": 12,
            "default_size": "standard",
            "placements": [
              {
                "section": "time",
                "view_id": "view-1",
                "column": 0,
                "row": 0,
                "column_span": 6,
                "row_span": 3
              }
            ]
          },
          "unplaced": [],
          "show_titles": true,
          "show_sources": true
        }
      ]
    },
    "preview_sidecar": {"format": 1, "path": "…", "generation": "…"}
  }
}
```

template Board仍写layout_mode/template字段。Sidecar format无需因geometry升级；它按ref共享。

### 9.2 Schema 2 → 3

- 每张P1 Board默认 `layout_mode="template"`；
- 原layout/ratio/slot placements原样保留；
- 不自动转换为free grid；
- sidecar catalog原样沿用；
- active Board/Boards顺序不变；
- 只有用户显式转换并保存才写free-grid geometry。

### 9.3 非法 geometry legalize

loader必须确定性处理：

- columns不是12：warning并按12解释/回退；
- span/row/column超界：clamp到合法范围后若仍碰撞，则该ref进tray；
- placement重复ref：首个保留，后续忽略并warning；
- placement超过24：row-major前24保留，其余进tray；
- rect碰撞：按payload顺序保留首个，冲突ref进tray；
- 未知layout_mode：回退template `hero_left_4`，所有合法refs按顺序放置/入tray；
- 任何合法ref都不能因坏geometry静默删除。

## 10. 单卡 Live Inspection

### 10.1 定位

Inspection是Board内部的临时只读核对层。它与P0的QImage放大层不同：

- QImage focus仍用于没有render-ready result的任何卡片；
- Live Inspection只有在已有、可安全读取的render document/result时可用；
- UI文案应区分“放大预览”和“交互检查”。

### 10.2 数据来源

Inspection renderer只接受不可变的 `InspectionDocument`：

```text
ref / section / axis facts / source summary
render-ready result/model snapshot
display parameters required for visual parity
initial x/y range
```

adapter可以从以下来源建立document：

1. source View当前精确绑定且已存在的render model；
2. P1-E若已实施，安全cache result adapter；
3. 未来正式render-document seam。

禁止：

- 调用 `_render_analysis_view_from_cache()`；
- 消费 `_analysis_restore_pending`；
- 调用 `do_*` / submit / source data load；
- 从active B canvas拼出ref A的document；
- 用标题/索引代替stable ref；
- 直接借用或reparent源canvas。

若document不可用，按钮禁用并说明“仅有图片预览；打开原 View 进行交互”。

### 10.3 Canvas生命周期

- 同时最多一个 `InspectionSession`；
- 由UltraView coordinator/inspection controller拥有，canvas位于Board overlay/focus host；
- 打开第二张先完整关闭第一张，再创建/复用兼容canvas；
- Qt object只在GUI thread创建、绘制、销毁；
- Board切换、工具窗关闭、项目reset、source删除或digest变化均关闭session；
- timer/signal/queued callbacks带session generation并晚到no-op；
- FRF/heatmap/line canvas可以使用section-specific presenter，但不得把全部逻辑复制进UltraView。

### 10.4 允许的交互

- X/Y pan与zoom；
- Home/View All恢复document初始范围；
- 单游标读取X/Y；
- tooltip/crosshair；
- Esc关闭；
- “打开原 View”显式导航。

不允许：参数编辑、计算、通道选择、pane增删、markup编辑、过滤器修改、源range回写或cache写。

### 10.5 不回写 canonical preview

Inspection中的局部range是临时阅读状态，退出时：

- 不覆盖PreviewStore canonical image；
- 不改变captured digest/status；
- 不让其他Boards突然显示一个局部放大图并标fresh；
- 不写项目或sidecar；
- 可在session内提供“复制当前检查图像”，明确标注为临时检查截图，独立于Board preview。

如果未来要“保存检查视图为新View/新卡片”，需建立新身份与用户意图，不能偷改源ref预览。

## 11. 兼容轴引导（非多卡 live）

### 11.1 一向投影

Inspection card是唯一交互主卡。其他卡片保持QImage，只叠加轻量guide overlay：

- X cursor guide；
- 可选inspection当前X-range半透明窗口；
- 文本提示“超出该卡范围/单位不兼容”。

overlay由轴元数据映射到图片内容rect，不改变图片、不创建live canvas、不响应拖动。

### 11.2 兼容判定

只有同时满足才投影：

- `axis_kind`相同；
- canonical unit相同；
- 两侧range是有限、递增的数值范围；
- card preview记录了可用plot content rect/axis transform metadata；
- X值落在目标范围内，否则只显示“超出范围”提示。

`time`、`frequency`、`order`、`time_freq`不跨kind同步；`Hz`与`rpm`不自动换算；单位未知不
乐观兼容。热图只投影X方向，不联动Y/color/slice。

### 11.3 元数据扩展

P2 PreviewMeta/sidecar可增加版本化的：

```text
plot_content_rect_norm = (left, top, width, height)
x_transform = linear | log
```

这些元数据必须来自真实renderer布局/axis，不通过截图像素猜测。缺失时guide不可用但卡片
仍正常显示。它们作为 sidecar manifest format 1 的可选向后兼容字段存在：旧reader忽略，
新reader缺失时禁用guide，因此不需要只为该可选字段升级sidecar容器格式。若log轴映射未被
当前sections正式支持，则P2第一版仅linear并明确禁用log。

## 12. Inspection零计算与状态诚实

P2零计算探针覆盖：

```text
自由网格move/resize/preset/undo/redo/organize
→ minimap/overview/scroll
→ 打开/操作/关闭inspection
→ cursor/range guide
→ 复制临时检查图
→ 保存/重开项目
→ 导出24图Board
```

以下保持不变：

- 所有 `do_*` / job submit / coordinator submit计数为0；
- `_store_analysis_result` / analysis cache新写入为0；
- `_analysis_restore_pending`不变；
- source ViewState/PaneState/active/ranges/markup不变；
- canonical PreviewRecord image/digest不因inspection改变。

若source View在inspection期间由MainWindow另一侧改变，session必须检测digest/binding变化并
显示“源已变化，检查已关闭/需重新打开”，不能继续把旧document当fresh。

## 13. 24图性能、内存与虚拟化

### 13.1 静态卡片策略

24张静态QWidget+QImage在当前栈可行，但实施必须测量后决定是否需要viewport virtualization。

先实现/测量：

- 所有24 Card widgets常驻，只有QImage按residency/viewport分级；
- drag/resize只画ghost；commit后局部relayout；
- 滚动过程中不对屏外卡做平滑缩放；
- quiet settle后只更新新进入viewport的图片。

只有Cocoa benchmark显示scroll/resize p95超过目标或GUI stall>500ms，才引入Card widget
recycling。不得在没有数据时先增加复杂virtualization/lifecycle风险。

### 13.2 live inspection预算

- inspection canvas不计入静态PreviewStore，但有独立临时内存统计；
- 打开前可以降级/淘汰inactive Board高分辨率图片；
- 关闭后释放render model/canvas临时buffer并恢复static residency；
- 不缓存五种section各一张隐藏canvas；可以按当前section创建，或只缓存一个有严格lifetime
  的host；
- source result非常大时遵守现有canvas renderer/decimation策略，不复制大数组；document应
  引用不可变result或轻量DTO，而不是deepcopy全数据。

### 13.3 初始性能目标

真实Cocoa baseline需至少三轮，记录：

- 24 cards scroll/resize/move commit/undo/overview/minimap；
- inspection open/first paint/pan/zoom/cursor/close，按line/heatmap/FRF类型；
- raw pixels、RSS、inspection peak、widget count、GUI stall。

目标：layout drag/resize callback p95 `<16 ms`（ghost only）、commit p95 `<100 ms`、scroll
interactive p95 `<50 ms`、inspection open first paint `<300 ms`、任何stall `<500 ms`。
真实测量前这些是设计目标，不是已通过门禁；若合理实现仍不达标，评审应据数据修订阈值。

## 14. 导出与复制

自由网格compositor：

- 使用与screen相同的GridRect→pixel pure geometry；
- 导出完整logical Board，不只viewport；
- 保留空白区域和相对位置，但裁掉最底部无内容尾白；
- 包含Board名、卡片chrome、状态与预览；不包含handles/ghost/minimap/selection/guides/inspection；
- 1×/2×受max edge/total pixels约束；24图过高时提供明确策略：降低scale或按水平分页导出
  多张PNG，不能静默缩成不可读一张；
- 分页文件名有`-01/-02`稳定序号，manifest/toast报告页数；
- “复制整板”若超过clipboard安全像素上限则提示改用PNG分页，不做危险分配；
- “复制当前检查图像”仅复制inspection canvas并明确它不是canonical Board preview。

P2不加入PDF/SVG；分页PNG已覆盖超长Board交付。

## 15. 架构所有权

推荐新增/扩展：

```text
mf4_analyzer/ui/ultraview_state.py
  schema 3 / GridRect / free-grid legalize / conversion

mf4_analyzer/ui/chart_stack/ultraview/free_grid.py
  grid geometry、hit-test、collision、commands（Qt-free部分可拆出）

mf4_analyzer/ui/chart_stack/ultraview/widgets.py
  Card handles/ghost/minimap presentation

mf4_analyzer/ui/chart_stack/ultraview/inspection.py
  InspectionController/session lifecycle; no MainWindow import

mf4_analyzer/ui/chart_stack/ultraview/inspection_documents.py
  render-document DTO/adapters interface；section adapters放owner附近

mf4_analyzer/ui/chart_stack/ultraview/compositor.py
  free-grid dynamic/paged composition

mf4_analyzer/ui/main_window/ultraview_coordinator.py
  source facts/document routing/project lifecycle orchestration
```

约束：

- Grid/legalization/commands的中立部分Qt-free；
- Page/widget只发intent，不直接改project/source；
- InspectionDocument不持有MainWindow/QWidget/QThread；
- section renderer adapter放在已有presenter/result owner边界，不能复制数值算法；
- 不扩大MainWindow多文件mutable writes；session由coordinator/collaborator拥有；
- 使用现有pg_canvas public presenter/backref合同，不加undeclared delegate writes；
- unexpected ImportError/programming error传播，不静默降级。

## 16. 可访问性与帮助

- 卡片menu提供move/resize preset/undo/redo/organize/inspect/open source；
- resize handle有accessible name与键盘等价路径；
- ghost invalid不能只用红色，要有图标/文本/announce；
- minimap可关闭且有键盘导航；
- inspection crosshair数值可被screen reader读取，更新需节流避免朗读风暴；
- guide状态提示兼容/超范围，不以颜色唯一表达；
- hints/quickref/help明确：最多24、12列、无重叠、一次一张live、零计算、局部检查不回写源；
- shortcut冲突在产品中实测，macOS/Windows文案按实际Control/Command显示。

## 17. 验收矩阵

| ID | 结果合同 |
|---|---|
| UV-P2-A01 | schema2 template Boards确定性迁移schema3且不自动转free grid |
| UV-P2-A02 | GridRect边界、最小/最大span、12列/48行/24卡上限可legalize且ref不丢 |
| UV-P2-A03 | template↔free转换顺序/托盘/确认/Undo正确 |
| UV-P2-A04 | move/resize/preset ghost→commit/cancel状态机正确，无半提交 |
| UV-P2-A05 | collision拒绝与同尺寸swap确定，不发生隐式连锁reflow |
| UV-P2-A06 | keyboard move/resize、layout undo/redo、organize与鼠标结果一致 |
| UV-P2-A07 | 1280/1600/DPR1/2 screen/compositor geometry一致，无重叠/越界 |
| UV-P2-A08 | 24图滚动、minimap、overview定位完整且不计算 |
| UV-P2-A09 | schema3坏geometry按稳定规则clamp/入tray/warning，不静默删除ref |
| UV-P2-A10 | inspection document只来自精确ref已有result/model，不触发restore/compute |
| UV-P2-A11 | 同时最多一个inspection canvas，切card/Board/project/shutdown生命周期安全 |
| UV-P2-A12 | inspection pan/zoom/cursor/Home不修改source state或canonical preview |
| UV-P2-A13 | source digest/binding变化可关闭/作废inspection，不继续伪fresh |
| UV-P2-A14 | guide只投影axis kind/unit/range/transform兼容卡片，其他明确退化 |
| UV-P2-A15 | 24图完整/分页PNG与clipboard限额正确，不静默缩小或只导viewport |
| UV-P2-A16 | 完整P2链三层计算计数/cache写入为0，restore/source/canonical preview不变 |
| UV-P2-A17 | 24图与line/heatmap/FRF inspection三轮Cocoa benchmark有raw JSON证据 |
| UV-P2-A18 | hints/quickref/help/shortcut/accessibility与实际能力一致 |
| UV-P2-A19 | lifecycle subprocess、架构门禁、main/acquisition两进程suite正常结束 |
| UV-P2-A20 | macOS Cocoa前景完成；Windows Full/Lite frozen未跑则UNVERIFIED |

## 18. Done 定义

P2只有在以下条件同时满足时完成：

1. P1入口门槛全部PASS；
2. schema3 migration/legalization、free-grid commands与conversion有Qt-free property tests；
3. 24图screen/export/minimap/overview通过确定性和Cocoa证据；
4. inspection至少覆盖line、heatmap、FRF三种canvas/result类型，其他section有明确复用或禁用合同；
5. inspection与guides完整操作链零计算、零source写入、零canonical preview回写；
6. 生命周期子进程和两进程full suites正常结束；
7. performance目标用三轮raw samples判断，任何>500ms stall有FAIL/解释而非隐藏；
8. macOS前景完成，Windows frozen未跑明确UNVERIFIED；
9. verification逐项映射UV-P2-A01～A20及证据路径；
10. 没有把自动packing、多卡live、参数编辑或无限画布偷偷扩进交付。

## 19. 请求 Claude 重点评审

请把 P2-A Layout 与 P2-B Inspection 分开给出 GO/NO-GO，并重点挑战：

1. 12列、48行、24卡及span范围是否过度限制或仍缺少安全上限；
2. “碰撞即拒绝、不自动推挤”是否足够顺手，是否需要一个仍可确定性撤销的局部packing；
3. template↔free转换、organize和undo的持久化边界是否存在用户预期落差；
4. 24 QWidget先测量、超门禁再virtualize的路线是否合理；
5. InspectionDocument能否在当前line/heatmap/FRF owner中真正做到不装载、不计算、不污染active；
6. source result被invalidate或释放时，document/session如何获得可靠generation/lifetime通知；
7. 静态QImage上的plot-content rect与X transform能否从真实renderer稳定取得，guide是否应缩为
   inspection overlay内的数值列表而不是跨卡画线；
8. inspection copy、canonical preview、sidecar和fresh/stale语义是否已完全隔离；
9. 自由长Board的分页PNG是否需要额外的页面标题/continuation语义；
10. P2-A是否应先单独发布观察使用，再决定P2-B，而不是在一个版本里同时交付。
