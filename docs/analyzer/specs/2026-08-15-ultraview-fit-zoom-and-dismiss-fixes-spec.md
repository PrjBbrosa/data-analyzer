# UltraView 适配、缩放与浮层消隐三处修正 设计

> 状态：**设计定稿，未实施**。实施计划见
> `docs/analyzer/plans/2026-08-15-ultraview-fit-zoom-and-dismiss-fixes-plan.md`。
> 基线：`claude/ultraview-library-geometry-material@27e0cf90`（含
> `94934485` 固定逻辑画布与默认适应视口）。本文四节各自独立，可分别落地。
>
> 四条都由用户在真机使用中报出，并已在离屏（`QT_QPA_PLATFORM=offscreen`）
> **确定性复现**——它们全是几何/事件路由的逻辑缺陷，不是 paint 成本问题，
> 所以离屏证据在这里是充分的（与 CLAUDE.md「验真机渲染」不冲突：本文不做
> 任何性能或观感断言）。复现脚本见 plan Task 0。

## 0. 涉及的既有常量（全部保持不变，除 §4 一条）

| 常量 | 值 | 位置 |
|---|---|---|
| `GRID_COLUMNS` / `MAX_GRID_ROWS` | 12 / — | `free_grid.py` |
| `GRID_ROW_HEIGHT` / `GRID_MIN_COLUMN_WIDTH` | 88 / 96 | `free_grid.py:34-35` |
| `BOARD_PADDING` / `SLOT_GUTTER` | 16 / 12 | `layouts.py:17-18` |
| `CARD_HEADER_HEIGHT` + `CARD_FOOTER_HEIGHT` = `MIN_CARD_CHROME_HEIGHT` | 34 + 24 = **58** | `layouts.py:27-29` |
| `BASE_BOARD_SIZE` | (1600, 900) | `layouts.py:16` |
| `GRID_MIN_VISIBLE_ROWS` / `GRID_SPARE_ROWS` | 10 / 2 | `free_grid.py:36-39` |
| `ZOOM_MIN` / `ZOOM_MAX` | 0.25 / **2.0 → 3.0（§4）** | `viewport.py:18-19` |
| `LOD_FOOTER_HIDE` / `LOD_TITLE_ONLY_ZOOM` | 0.60 / 0.40 | `viewport.py:26-27` |
| `MAX_PREVIEW_RAW_EDGE` | 1600 | `preview_store.py:22` |

1× 网格（`screen_grid_metrics([])`）实测：列宽 **119**、行高 **88**、间距 **12**。

---

## 1. 「按原图比例」无视卡片当前尺寸

### 1.1 现状

`free_grid.fit_rect_for_aspect()`（`free_grid.py:197-229`）在**全部合法跨度**
（列 `GRID_MIN_COLUMN_SPAN..GRID_MAX_COLUMN_SPAN` × 行同理）里穷举，排序键是
`(|ratio - target|, |area - origin_area|, area)`。原点行列不动，**跨度不设上界**，
面积只在比值完全打平时才起作用。于是结果只由原图比例决定，与卡片当前大小无关。

实测（原图 5:4，1× 网格）：

| 当前卡 | 像素 | 结果 | 像素 | |
|---|---|---|---|---|
| 4×6（高瘦） | 512×588 | **7×8** | 905×788 | ⚠️ 变大 |
| 10×3（扁宽） | 1298×288 | **7×8** | 905×788 | ⚠️ 变大 |
| 6×4（已接近比例） | 774×388 | **7×8** | 905×788 | ⚠️ 变大 |
| 2×2，原图 4:1 | 250×188 | 4×2 | 512×188 | ⚠️ 变大 |

三个起点完全不同的卡按下去都跳到同一个 7×8——用户描述的「直接自适应到原始
图片的尺寸」。

### 1.2 目标语义：contain（只缩不放）

**以卡片当前跨度为上界，只缩一边，让卡片比例匹配原图。** 用户给的判据：

- 图 10×8（比 1.25），框 10×16 → 宽是瓶颈，保 10、高压到 8
- 同图，框 20×8 → 高是瓶颈，保 8、宽压到 10

即「把原图比例内接进当前卡的包围盒」。注意两点，都必须按**像素**而不是格数算：

1. 格子不是正方形（列 119+12 vs 行 88+12）；
2. 卡片高度里有 `MIN_CARD_CHROME_HEIGHT = 58` 的标题+页脚，比例针对**绘图区**
   （现有实现已经这样扣，保留）。

### 1.3 规则

候选集从「全部合法跨度」收紧为：

```
GRID_MIN_COLUMN_SPAN ≤ col_span ≤ origin.column_span
GRID_MIN_ROW_SPAN    ≤ row_span ≤ origin.row_span
```

排序键改为 `(|ratio - target|, -area)`：**比例误差最小；同误差取面积最大**。
后者是防退化的关键——网格离散，2×2 与 4×4 可能给出同一比值，取大的那个才符合
「只缩到刚好」而不是「缩到最小」。

推论（都要写进用例）：

- 结果恒是原矩形的**子集**（原点不动 + 跨度只减），所以这条路径**不可能与邻卡
  重叠**，`plan_layout(..., LAYOUT_RESIZE)` 必然 accepted。`ultraview_coordinator.py:1490`
  的「目标位置与其他卡片重叠」toast 对本路径变为不可达；防御性保留，不删。
- 已经是最小跨度、或比例已匹配时 `wanted == item.rect`，调用方
  （`ultraview_coordinator.py:1487`）已有 early-return，不产生空操作提交。
- 卡片只会变小，不会挤走别人——这也让「模板模式下该操作不可用」的既有约束不受影响。

### 1.4 不做

- 不允许放大到超出当前卡（用户明确「缩成」）。想变大用尺寸预设或拖边角。
- 不改原点：卡片左上角钉住，缩的是右/下边。

---

## 2. 画布空白点击不关 View 库

### 2.1 现状（实测）

| 点击落点 | View 库 |
|---|---|
| 自由网格**之外**的画布带（滚动视口 / board host） | ✅ 缩回 |
| 自由网格**内部**的空白格 | ❌ 不缩回（连点多次都不缩） |

关闭浮层的逻辑只有两处入口：`page.eventFilter` 监听 `_board_scroll.viewport()`
（`page.py:1905-1909`）与 `CanvasHost.mousePressEvent` / `eventFilter`
（`chrome.py:406-418`，最终走 `_close_from_canvas_click()`，它会尊重
`overlay_closes_on_canvas` 即 pin 状态）。

而 `FreeGridBoard.mousePressEvent`（`widgets.py:3198-3218`）把空白处的按下
**自己吃掉了**：清选中 → `begin_marquee` → `event.accept()`，从不通知 page。
Qt 的事件过滤器只对**安装到的那个 widget** 生效，祖先收不到已被子控件接收的
press，所以那两处入口根本没有机会执行。

### 2.2 为什么「+view 之后」才暴露

自由网格的尺寸随内容增长。实测同一 1600×900 视口：

| | 自由网格尺寸 | 相对视口位置 | 可见空白归属 |
|---|---|---|---|
| 加卡片前 | 1217×776 | (78, 64) | 四周留一圈属于视口 → 点那里能缩回 |
| 加卡片后 | 1600×1020 | (78, 64) | **盖满可见区** → 处处是 FreeGridBoard → 缩不回 |

所以这不是 `+view` 动作本身的 bug，而是「画布空白」这块区域**换了归属 widget**。
用户看到的「正常能缩回、+view 之后不能」是同一个洞在两种几何下的两种表现。

### 2.3 修法

在 `FreeGridBoard.mousePressEvent` 的空白分支里，**先请求关闭当前浮层，再**清
选中 / 起框选（两件事互不冲突，顺序只影响一帧内的可见性）。关闭必须**走既有的
canvas-click 通道**而不是直接 `hide()`：

- 尊重 pin（`ViewLibraryPanel` 的图钉 → `set_overlay_close_on_canvas(..., close=False)`，
  `page.py:923`）；
- 尊重拖拽期延后（`page._close_active_panel` 在 `_drag_kind is not None` 时把关闭
  推迟到 `_on_drag_finished`，`page.py:904-905`）——从库里拖卡到画布的落点 press
  不能顺手把库关掉。

实现形态：`CanvasHost._close_from_canvas_click()` 提升为公开
`close_from_canvas_click()`；`UltraViewPage` 加一个转发方法（例如
`notify_canvas_click()`），`FreeGridBoard` 经既有的 `_page_of(self)` 调用它。
不新增信号、不新增 `.connect(lambda`（`tests/ui/test_no_lambda_signal_connections.py`
是 shrink-only 棘轮）。

### 2.4 范围界定

- **只覆盖空白按下**。落在卡片上的按下维持现状（不关浮层）——「选中卡片」与
  「库里挑一个去替换」（`arm_replacement`，`page.py:1792`）是并存的合法流程。
- 模板模式（`BoardGrid`）要同样检查：凡是自己 accept 空白 press 的画布控件，都
  必须走同一条通道。落地时以「点画布任意空白都能关掉未 pin 的浮层」为验收口径，
  而不是只修自由网格。
- 未 pin 的**任何**浮层（库 / 未放置托盘 / 筛选 / 布局 / Board 弹层）都按同一
  规则消隐；这条通道本来就是按 `_active_overlay` 工作的，不给库开特例。

---

## 3. 「适应」适应的是空画布，且停在左上角

### 3.1 现状（实测）

`zoom_fit()`（`page.py:1086-1093`）：

```python
size = canvas.unzoomed_size()        # 固定逻辑画布整体
fit  = self._content_fit_rect()      # 浮层安全区（chrome-safe）
self._park_zoom(fit_zoom((size.w, size.h), (fit.w, fit.h)))
```

`unzoomed_size()` 对自由网格是 `(board_width, board_height)`，而 `grid_metrics`
（`free_grid.py:159-170`）给的行数是 `max(GRID_MIN_VISIBLE_ROWS, 占用行 + GRID_SPARE_ROWS)`
——**至少 10 行**。`_park_zoom` 随后把画布停到 `_fit_origin()`，即安全区**左上角**。

4 张卡实测：逻辑画布 **1600×1020**，安全区 1910×976 → 缩放 **0.957**，原点
(78, 64)。用户截图里的 **123%** 是同一机制在其视口宽度下的解（≈ 视口宽 / 1600）。

于是：卡片只占画布左上一小块 → 「适应」之后就是**缩在左上角 + 一大片空**。

### 3.2 目标语义：适应**内容**并居中

「适应」= 把**已放置卡片的包围盒**放进浮层安全区，等比缩放（可放大可缩小），
并**居中**。空板（无卡片）退回现状（适应逻辑画布），否则新板会得到一个无意义的
无穷缩放。

### 3.3 规则

1. 两个画布各自提供 1× 内容包围盒：
   - 自由网格：对每个 placement 取 `rect_to_pixels(rect, base_metrics)` 求并集；
   - 模板模式：对已占用 slot 取 `unzoomed_slot_rect` 求并集。
   - 无内容 → 返回 `None`。
2. `zoom_fit()`：内容盒为 `None` → 走现状分支；否则
   `zoom, center = zoom_to_rect(content_rect, (fit.width, fit.height), margin=0.08)`
   → `_apply_zoom_and_center(zoom, center)`。
3. **视口尺寸用 `_content_fit_rect()` 而不是原始视口**——这是与 `zoom_to_card`
   （`page.py:1126`，用原始视口）的**故意区别**：适应必须保住既有契约
   「适应把卡片停在浮层安全区」（`test_canvas_is_full_bleed_and_fit_parks_cards_in_the_safe_zone`），
   而双击铺满一张卡允许伸到工具栏下。
4. `zoom_to_rect` 的 8% 余量沿用，不新增常量。
5. 结果照常经 `clamp_zoom` 收进 `[ZOOM_MIN, ZOOM_MAX]`——单张小卡会顶到 §4 的
   300% 上限，这是预期。

### 3.4 连带影响

- 「新板默认适应视口」（`94934485`）走同一入口：新板无卡 → 现状分支，行为不变。
- 演示模式下 `_content_fit_rect()` 返回整个 stage，居中语义自动跟随，无需特判。
- 整板概览（`show_overview`）是另一条只读投影路径，不受影响。

---

## 4. 缩放上限 200% → 300%

`ZOOM_MAX = 2.0` → **3.0**（`viewport.py:19`）。`ZOOM_MIN` / `ZOOM_BUTTON_STEP`
/ LOD 三档（0.60 / 0.40 / 滞回 0.04）全部不动——LOD 都在低端。

扇出面（一处漏掉就会自相矛盾）：

| 面 | 现状 |
|---|---|
| `tests/ui/test_ultraview_viewport.py` | `clamp_zoom(8) == ZOOM_MAX`（仍成立）；`viewport.set_zoom(3.0) == ZOOM_MAX` 会退化成恒真，**改喂 5.0**；`set_board_zoom(2.0) == ZOOM_MAX` 两处（215 / 922）与 983-988 一处要改用 `ZOOM_MAX` 常量而不是字面量 |
| `mf4_analyzer/ui/quickref.py:510` | 「范围 25%–200%」 |
| `mf4_analyzer/help/ultraview-guide.html:111` | 「范围 <b>25%–200%</b>」 |
| `docs/analyzer/specs|plans/2026-08-15-ultraview-fixed-canvas-and-autofit-*` | 正文若写了 200% 需同步（历史文档只在**仍被契约钉住**时才改，见 CLAUDE.md） |

**已知副作用，本批不处理**：卡片预览是位图，`preview_store.MAX_PREVIEW_RAW_EDGE = 1600`
封顶，residency 按 `card.preview_display_size()`（已含缩放与 dpr，`widgets.py:1851`）
请求。300% 下一张 6 列卡约 905 逻辑 px → 2715 px × dpr 2 = 5430，被压到 1600
→ **放大到 300% 时预览会比 200% 更软**。这是位图预览的固有代价，不是本批引入；
要治得动抓图分辨率与内存帽（`MAX_PREVIEW_RAW_EDGE`、residency 分级），涉及
UltraView 预览内存策略，另立一批。落地时在 plan 留一条 follow-up，不在本批放宽
任何内存帽。

---

## 5. 机械护栏（新增/更新）

| 守卫 | 位置 | 断言 |
|---|---|---|
| contain-fit 只缩不放 | `tests/ui/test_ultraview_free_grid.py` | 对 4×6 / 10×3 / 6×4 同一原图，结果跨度**各不相同**且逐维 ≤ 原跨度；结果是原矩形子集 |
| contain-fit 不退化 | 同上 | 同比例误差下取面积最大（2×2 与 4×4 同比时取 4×4） |
| 画布空白点击消隐 | `tests/ui/test_ultraview_page.py` | 自由网格**内部**空白 press → 未 pin 的活动浮层关闭；已 pin → 不关；拖拽中 → 延后到 `_on_drag_finished` |
| 适应=适应内容并居中 | `tests/ui/test_ultraview_viewport.py` | 卡片包围盒占安全区 ≥ 80%（某一维）；内容中心与安全区中心对齐（±2 px）；空板走现状分支 |
| 适应仍在安全区 | 既有 `test_canvas_is_full_bleed_and_fit_parks_cards_in_the_safe_zone` | 不改一行照过 |
| 缩放上限 | `tests/ui/test_ultraview_viewport.py` | `clamp_zoom(5.0) == ZOOM_MAX == 3.0`；文案面三处与常量一致（可加一条扫描用例） |
| lambda 棘轮 / 分层 | 既有 | 不许新增 lambda 信号连接；`ui_kit` 不 import `ui` |

## 6. 验收

| 项 | 改前（实测） | 改后目标 |
|---|---|---|
| 4×6 / 10×3 / 6×4 按原图比例（5:4） | 全部 → 7×8（且变大） | 三者互不相同，逐维只减 |
| 自由网格内部空白点击（库已开、未 pin） | 不关闭（连点无效） | 一次点击关闭 |
| 同上但库已 pin | 不关闭 | 仍不关闭 |
| 4 卡「适应」 | zoom 0.957，内容占安全区宽 ~57%，停左上 | 内容填满安全区（含 8% 余量），居中 |
| 单卡「适应」 | 受逻辑画布压制 | 顶到 `ZOOM_MAX = 3.0` |
| 空板「适应」 | 适应逻辑画布 | 不变 |
| 缩放上限 | 200% | 300%，文案三处同步 |

离屏即可完成全部验收（几何与事件路由）。**唯一需要真机的**是一次观感确认：
300% 下预览的软化程度是否可接受（§4 已知副作用）。

## 7. 风险与回退

- **contain 后卡片可能变得很小**：比例极端（如 8:1）的原图配一张窄卡时，行跨度会
  压到 `GRID_MIN_ROW_SPAN`。这是「只缩不放」的必然结果，用户已确认接受；下限由
  既有 `GRID_MIN_*_SPAN` 兜住，不会出现 0 跨度。
- **空白点击关浮层可能误伤框选起手**：框选仍在同一次 press 里开始，只是浮层同时
  关掉；若发现「想框选却先被关浮层打断视线」，可改为 release 时关——回退点单一。
- **适应居中改变了既有肌肉记忆**：左上角停靠是 `94934485` 引入的新行为（此前也是
  fit 到画布），改成居中属于修正而非再次翻转。
- 三处修改互不耦合，可单独回退；§4 是一行常量。
