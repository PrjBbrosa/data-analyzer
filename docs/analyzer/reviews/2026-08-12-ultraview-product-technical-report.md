# TraceLab UltraView 最终目标、功能逻辑与技术路线报告

> 日期：2026-08-12  
> 状态：`DRAFT FOR CLAUDE REVIEW`（产品与技术方案，尚未进入实现）  
> 代码证据复核快照：`ffdee19c`，`APP_VERSION = v7.9.9`（共享工作树在撰写期间有其他任务推进；实现前应按当时 HEAD 重定位行号）  
> 交互原型：[`docs/analyzer/ui-prototypes/2026-08-12-ultraview-interactive-demo.html`](../ui-prototypes/2026-08-12-ultraview-interactive-demo.html)

## 0. 结论先行

**结论：当前 PyQt5 + pyqtgraph 技术栈可以实现 UltraView，建议进入 P0。**

UltraView 的正确定位不是“再做一个能计算的大图表页”，而是：

> 把时域、频谱、时频、FRF、阶次中已经存在的 View，以只读预览卡片投影到同一张大画布，帮助用户一次观察 4～6 个工况、位置或分析结果；画布只负责引用、布局、比较和导出，不提交分析任务，也不反向修改源 View。

推荐技术路线是：

1. 用 `(section, view_id)` 引用源 View，不用名称或列表下标做身份。
2. 源 View 在真实可见画布完成渲染时，生成有版本信息的 `QImage` 预览。
3. UltraView 中央区使用 `QGraphicsView/QGraphicsScene` 组合只读图片卡片，不挂载或复用源图表 QWidget。
4. P0 只消费预览存储，不调用任何现有计算入口，也不走可能触发项目恢复重算的缓存恢复入口。
5. `.tlproj` 只保存画布定义、布局和 View 引用，不保存数值结果或 Qt 对象；预览缺失时明确显示“无可用结果”。

这条路线改动可控、性能可预估，也最符合“全局对比而非二次分析”的原始目标。

## 1. 用户问题与机会

当前工作流一次只能在中心画布中查看一个 View，或使用左右分屏比较两个图。用户若要比较四个工况、多个测试位置，或把时域异常、FFT 峰值、时频漂移、FRF 和阶次放在一起，需要反复切换模式与 View，容易出现三个问题：

- 视觉记忆负担大，前一个图的范围、峰值和趋势很快丢失；
- 不同模式之间来回切换，问题链条被界面结构切断；
- 当前双图分屏适合精细联动，不适合 4～6 图的全局扫描。

UltraView 要补的是“多结果阅读层”，而不是新的分析算法或另一套 View 系统。

## 2. 产品最终目标

### 2.1 一句话目标

用户能在一个固定、可保存、可导出的全局画布中，同时放置来自五个现有分析区的多个 View，并快速发现趋势一致、峰值迁移、频带异常、工况差异和跨域关联。

### 2.2 产品承诺

UltraView 必须同时满足以下五条：

1. **全局可见**：常用屏幕上一次可读 4～6 张图，不依赖频繁切换。
2. **只读投影**：卡片不拥有分析参数、数据源或结果，只引用源 View。
3. **零隐式计算**：进入 UltraView、添加/移动卡片、切布局、缩放、筛选、演示和导出都不提交分析任务。
4. **状态诚实**：预览是最新、已过期、从未生成，还是源 View 已删除，必须一眼可辨。
5. **身份稳定**：View 改名、重排或存在同名通道时，卡片仍指向原对象。

### 2.3 非目标

P0 明确不做：

- 不在 UltraView 内修改源 View 的通道、参数、坐标范围、滤波或标注；
- 不同时创建 4～6 套完整 pyqtgraph 活画布；
- 不在卡片内提供实时游标、框选、滚轮轴缩放或跨图联动；
- 不把 UltraView 变成 Batch 报表编辑器；
- 不宣称导出真正的矢量曲线；源图是像素预览时，SVG 也只是嵌入位图；
- 不把 HTML 原型中的“场景切换”和“状态模拟按钮”带进产品。

需要精细操作时，用户通过“打开原 View”回到拥有该状态和计算能力的原工作区。

## 3. 术语与身份模型

### 3.1 三层对象

| 对象 | 责任 | 是否拥有计算状态 |
|---|---|---:|
| 源 View | 通道/文件、参数、坐标、光标、分析结果的真实所有者 | 是 |
| PreviewRecord | 某次成功渲染产生的图像与版本元数据 | 否 |
| UltraView Card | 引用 PreviewRecord，并保存位置、尺寸角色和显示选项 | 否 |

### 3.2 唯一身份

每张卡片的源引用固定为：

```text
ViewRef = (section, view_id)

section ∈ {time, fft, fft_time, frf, order}
```

不能用 `View 1`、显示名称、通道短名或 View 列表下标作为身份。现有时域 `ViewState` 已有持久化 `view_id`，见 `mf4_analyzer/ui/view_state.py:39-55`；分析 `AnalysisViewState` 也有 `view_id`，见 `mf4_analyzer/ui/analysis_view_state.py:164-176`。

现有五个 section 各自使用 ViewManager，单 manager 上限为 12，见 `mf4_analyzer/ui/view_state.py:19-23` 和 `mf4_analyzer/ui/main_window/window.py:384-419`。UltraView 的卡片容量是阅读密度约束，不应直接复用或硬编码 `MAX_VIEWS`。

### 3.3 分屏语义

- **时域 View**：一张 UltraView 卡片只代表一个 `ViewState`。即使源工作区正在左右比较两个时域 View，也应分别抓取两张预览，避免“卡片中再嵌套一次 View 对比”。
- **分析 View**：一个 `AnalysisViewState` 自己可以拥有 1～2 个 pane，因此一张卡片应完整保留该 View 的单 pane 或双 pane 结构。现有 `AnalysisSectionPage.grab_combined_pixmap()` 已支持这种合成，见 `mf4_analyzer/ui/analysis_section_page.py:217-267`。

## 4. 最终功能逻辑

### 4.1 入口与退出

推荐在顶部模式段增加一个紧凑入口：

- 按钮显示名：`总览`；
- Tooltip / 页面品牌名：`UltraView 全局对比`；
- 它是独立工作区，不称为第六种分析算法；
- 离开源模式进入 UltraView 前，先捕获当前可见源 View 的最新预览；
- 从卡片点击“打开原 View”时，按 `section + view_id` 定位，不按旧下标定位；
- 返回 UltraView 时恢复画布布局和选择状态。

当前代码只登记了五个模式：`mf4_analyzer/ui/chart_stack/_helpers.py:45-52`；顶部工具栏也只创建五个模式按钮：`mf4_analyzer/ui/toolbar.py:142-162`。因此实现不能只增加一个按钮，还必须同步扩展 ChartStack、Inspector、模式路由、帮助提示和项目恢复。

需要注意：现有“进入时域模式会按已勾选通道安排一次绘制”，见 `mf4_analyzer/ui/main_window/window.py:1551-1584`。因此 P0 的“0 次分析任务”不应被误写成“整个应用绝不发生任何绘图工作”；强约束是 UltraView 自身只读、不提交分析 job，也不为了补预览主动渲染隐藏 View。

### 4.2 View 库

左侧 View 库使用现有全局侧栏位置，按五个 section 分组展示所有 View：

- 搜索 View 名称、section 和来源摘要；
- 显示颜色、名称、section、图轴类型、范围和预览状态；
- 点击 `+` 或拖到空槽添加；
- 拖到已有卡片上执行替换；
- 已在当前 Board 中的 View 显示勾选，不重复添加；
- 同名 View 不合并；
- 预览缺失不阻止添加，卡片显示明确空状态；
- 提供键盘/按钮替代操作，不能把拖拽作为唯一入口。

P0 推荐每个项目一个 Board，标准布局容量 2～6 张卡片。View 库仍可列出所有 section 的全部 View。

### 4.3 布局系统

P0 使用“模板 + 受控比例”，不做无限自由摆放：

| 模板 | 容量 | 主要用途 |
|---|---:|---|
| 左右双图 / 上下双图 | 2 | 从当前双图比较平滑过渡 |
| 2 × 2 等分 | 4 | 同类四工况 |
| 主图 + 3 辅图 | 4 | 一个问题主线 + 三个证据 |
| 上方主图 + 3 辅图 | 4 | 宽时域/时频主图 + 三个细节 |
| 3 × 2 矩阵 | 6 | 多工况全局扫描 |

行为规则：

- 主/辅区分割比例可拖动，Inspector 同时提供 `±5%` 和“设为主图”；
- 卡片可拖拽换位，Inspector 提供“前移/后移/移到槽位”；
- 切换到容量更小的模板时，超出的卡片进入“未放置”托盘，**不能像 HTML 原型一样静默截断**；
- 空槽保留“添加 View”入口；
- 同一 Board 内默认禁止重复引用同一个 View；
- 布局改变只修改 UltraView 状态，不修改源 View。

固定模板优先于任意自由缩放，原因是它能保证卡片有最低可读尺寸、导出可复现、项目格式稳定，也能让 1280px 与 1600px 屏幕得到一致结构。自由网格可作为 P1 后续能力。

### 4.4 卡片内容

每张卡片至少包含：

- View 颜色点和完整名称；
- section 标签（时域、频谱、时频、FRF、阶次）；
- 数据源/信号摘要；
- X 轴类别、单位和范围；
- 图像预览；
- 状态指示；
- “临时放大”和“打开原 View”入口。

P0 卡片不直接修改图像内部对象。选中卡片只改变 UltraView Inspector 的目标，不改变源模式当前 View。

### 4.5 对比轨道

画布上方提供轻量“对比轨道”：

- 全部；
- 仅看时间轴；
- 仅看频率轴；
- 仅看时频轴；
- 仅看阶次轴。

“仅看”在 P0 中采用降低非目标卡片透明度的方式，保持布局位置稳定，不真正删除或重排卡片。

系统还应基于 PreviewRecord 的轴元数据给出两类提示：

- 同轴类别但单位不同：`量纲不一致`；
- 同轴类别和单位相同，但 X 范围不同：`X 范围不一致`。

这里不做自动范围同步，也不宣称跨域数值可直接比较；提示的目的只是防止视觉误读。

### 4.6 四态投影模型

| 状态 | 判定 | 卡片表现 | 用户动作 |
|---|---|---|---|
| `fresh` 最新 | 预览 revision 与源 View 当前 presentation revision 一致 | 正常显示 | 放大 / 打开原 View |
| `stale` 源已变化 | 有旧预览，但源 View 的图像相关状态已改变 | 保留旧图 + 醒目标带 | 打开原 View，确认后离开时刷新 |
| `missing` 无结果 | View 存在，但从未产生可用预览 | 空状态，不绘制伪数据 | 打开原 View并由用户决定是否计算 |
| `orphaned` 源已删除 | `(section, view_id)` 已找不到 | 保留槽位、标题快照与删除提示 | 重新绑定 / 移出画布 |

状态必须由真实数据推导。HTML 原型的状态按钮只用于展示四态，不进入成品。

建议以下变化只更新卡片元数据而不把图像标 stale：View 改名、标签颜色改变。以下变化会推进 presentation revision：通道/源、计算参数、显示参数、X/Y 范围、plot mode、过滤显示、pane 结构、图像内容或结果 generation 改变。

### 4.7 临时放大与返回源 View

- 双击卡片或点击放大按钮：打开同一张只读预览的大图层；支持缩放、平移和 Esc 退出，但仍不创建活图表。
- 点击“打开原 View”：退出 UltraView，定位到源 section 和源 View；精细游标、缩放、参数修改和显式计算都在原工作区完成。
- 源 View 不存在时不跳转，改为提供“重新绑定”。
- 从源工作区返回 UltraView 前捕获最新预览；若捕获成功，状态变为 `fresh`。

“打开原 View”属于离开 UltraView 的导航动作。若产品保留现有“项目打开后分析 View 首次显示自动重算”的策略，这次重算应归属源分析工作区，而不是 UltraView；界面和测试必须能区分这两条路径。

### 4.8 缩放、适应窗口与演示

- 中央画布支持 70%～125% 缩放和滚动浏览；
- “适应窗口”使用 board bounding rect 计算缩放，不改卡片尺寸权重；
- 演示模式临时隐藏左右侧栏和编辑工具，整板适应窗口；
- Esc 按优先级关闭放大层、退出演示、关闭弹出菜单；
- 退出演示时恢复原侧栏可见性和宽度。

### 4.9 导出

P0 推荐：

- `复制整板图像`；
- `导出 PNG`，支持 1×/2×，复用现有高 DPI 上限策略；
- 可选 `导出 PDF`，内部允许嵌入位图。

不建议把“SVG”作为 P0 产品承诺，因为卡片来源是 QImage/QPixmap 快照，导出不会自动变成矢量曲线。HTML 原型当前的 SVG 只导出布局摘要，并明确写了这一限制，见原型 `1015-1020` 行。

导出内容必须包含 Board 名、卡片标题、来源摘要、状态标记和完整布局；不应只导出当前视口。

### 4.10 项目保存与恢复

`.tlproj` 保存语义状态，不保存 Qt 对象、数值结果或进程内缓存：

```json
{
  "ultraview": {
    "schema": 1,
    "board": {
      "board_id": "board-uuid",
      "name": "整车问题总览",
      "layout_id": "hero_four",
      "primary_ratio": 0.67,
      "show_titles": true,
      "show_sources": true,
      "placements": [
        {
          "slot_id": "primary",
          "section": "time",
          "view_id": "view-uuid"
        }
      ],
      "unplaced": []
    }
  }
}
```

持久化规则：

- 保存：Board 名称、布局 ID、比例、卡片引用、未放置引用、说明显示选项；
- 不保存：选中卡片、临时轴筛选、焦点弹层、演示状态、QImage/QPixmap、数值缓存；
- 旧项目没有 `ultraview` 时加载为空 Board；
- 实现时从当前项目 schema 版本递增到“下一个可用版本”，不能假定届时仍一定是 v2；
- View 的 fid remap 由源 View 自己完成，UltraView 只跟随稳定 `view_id`；
- 找不到 View 时恢复为 `orphaned`，不能静默删除位置。

当前 `ProjectDocument` 只含 files、time views、analysis views 和 filter，见 `mf4_analyzer/ui/project_io.py:41-50`；保存路径也没有 UltraView 字段，见 `mf4_analyzer/ui/main_window/_project_io_mixin.py:1558-1580`。当前项目文件明确是 reference-only，见 `mf4_analyzer/ui/project_io.py:1-6`。

项目重开后立即显示上次像素预览，需要引入 sidecar 或在 JSON 中嵌图，会改变 reference-only、体积和移动语义。**P0 推荐不持久化像素**：恢复布局后如无本会话预览，诚实显示 `missing`。是否增加可选 preview sidecar 应由 Claude 重点评审，但不应悄悄混入 P0。

## 5. HTML 原型到 PyQt 成品的操作映射

原型是交互方向，不是实现证明。每个可见操作必须映射到真实 Qt 控件和状态转移：

| HTML 原型动作/状态 | PyQt 成品映射 | 状态转移/约束 |
|---|---|---|
| 顶部 `UltraView` 模式 | `Toolbar.btn_mode_ultraview` + `ChartStack` 新页面 | 捕获离开源 View 的预览，再切工作区；不计算 |
| View 库分组、搜索 | 全局 Navigator 的 UltraView page | 查询五个 manager，以 `(section, view_id)` 组织 |
| 点击 `+ 添加 View` | View 行按钮 / 空槽按钮 | 添加引用；重复项仅高亮已有卡片 |
| 从库拖到空槽 | Qt drag MIME `section + view_id` | 插入卡片，不复制源状态 |
| 拖到已有卡片 | 卡片 drop target | 替换引用，旧引用回到未放置区 |
| 卡片拖动换位 | `QGraphicsItem` drag 或 Inspector 移位 | 只改 placement |
| 布局菜单 | UltraView toolbar layout menu | 套用模板；溢出进入未放置区，不截断 |
| 主图比例 `±` | Inspector spin/buttons + 可拖分割线 | 更新 layout weight，范围受限 |
| “设为主图” | Inspector action | 与主槽交换 |
| 对比轨道 | Board 顶部过滤 chips | 非目标卡片变淡，位置不变 |
| 范围不一致提示 | 轴元数据比较器 | 只提示，不联动坐标 |
| 最新/已变/无结果/已删除 | PreviewStore 派生状态 | 不提供成品中的模拟切换按钮 |
| 双击临时放大 | 只读 preview dialog/overlay | 同图放大；Esc 返回 |
| 打开原 View | coordinator 导航 | 按稳定 ID 定位，随后由原工作区负责交互/计算 |
| 替换 / 移出 | Inspector actions | 源 View 保留；位置可复用 |
| 显示说明/数据源 | BoardState 显示选项 | 只影响卡片 chrome |
| 缩放 / 适应窗口 | `QGraphicsView` transform / `fitInView` | 不改持久化卡片比例 |
| 演示模式 | SidePanelController + UltraViewPage | 隐藏编辑侧栏并可逆恢复 |
| 导出 SVG（原型） | 产品改为 scene render 的 PNG/复制 | 输出真实整板，不输出摘要占位图 |
| 三个场景按钮 | Demo-only | P0 不实现；未来可演化为 Board 模板/预设 |

原型中已经表达了只读投影、`0 JOBS`、四类布局、四态卡片、拖拽与按钮回退、临时放大、演示和导出入口，相关结构见原型 `575-659`、`694-733`、`795-1029` 行。

## 6. 当前代码可行性证据

### 6.1 已具备的基础

1. **稳定 View 身份已有**：时域和分析 View 都已持久化 `view_id`，不需要再发明身份层，见 `mf4_analyzer/ui/view_state.py:39-77`、`mf4_analyzer/ui/analysis_view_state.py:164-188`。
2. **源 View 状态已经隔离**：分析 View 自带 panes、params、compare 和 attachments，见 `mf4_analyzer/ui/analysis_view_state.py:164-188`。
3. **分析结果已有 per-section 缓存和 View pinning**：缓存容量与 pinned provider 已存在，见 `mf4_analyzer/ui/main_window/window.py:392-419`；pin 以 `(section, view_id, pane_idx)` 为槽位，见 `mf4_analyzer/ui/main_window/_state_holders.py:98-138`。
4. **抓图能力已有**：时域 renderer 有 `grab_pixmap(scale)` 和高 DPI 上限，见 `mf4_analyzer/ui/pg_canvas/renderer.py:865-924`；热图包含 QWidget overlay 的抓图路径，见 `mf4_analyzer/ui/pg_canvas/heatmap_canvas.py:1911-1940`；分析双 pane 已有组合抓图，见 `mf4_analyzer/ui/analysis_section_page.py:223-267`。
5. **现有 ChartStack 已是中心工作区切换器**：使用 `QStackedWidget` 管理五页，见 `mf4_analyzer/ui/chart_stack/stack.py:57-94` 和 `180-200`；增加 UltraView 页符合现有拓扑。
6. **现有任务服务有清晰提交边界**：`AnalysisJobService.submit/submit_batch` 是可监控的任务入口，见 `mf4_analyzer/ui/analysis_jobs.py:132-170`，可用作零计算回归测试的探针。

### 6.2 不能直接复用的部分

1. **不能把同一个 canvas QWidget 放进多个卡片**。Qt QWidget 只有一个 parent，重新挂载会把源页面中的图拿走；所以必须快照，或创建独立渲染实例。
2. **不能把所有非活动 View 当成现成的活图表**。当前时域只有主 canvas 和按需 secondary，见 `mf4_analyzer/ui/chart_stack/stack.py:73-94`；分析页也只有每 section 的 1～2 个真实 pane，见 `mf4_analyzer/ui/analysis_section_page.py:217-289`。非活动 View 本质上是状态与缓存。
3. **不能从 UltraView 直接调用 `_render_analysis_view_from_cache()`**。该函数通常只读缓存，但对 `_analysis_restore_pending` 有一次自动重算例外，见 `mf4_analyzer/ui/main_window/_analysis_mixin.py:867-908`。项目恢复会把有源 View 全部加入该队列，见 `mf4_analyzer/ui/main_window/_project_io_mixin.py:1687-1710`；现有测试也明确要求自动重算，见 `tests/ui/test_project_session.py:437-467`。
4. **不能只改 ChartStack**。顶部 toolbar、Inspector、Navigator projection、mode route、hints、quickref 和 project I/O 都只认识现有五个模式。比如 Inspector guide 的合法模式只列到 order，见 `mf4_analyzer/ui/inspector.py:286-295`。

## 7. 推荐技术架构

### 7.1 模块归属

建议新增以下窄模块：

```text
mf4_analyzer/ui/
├── ultraview_state.py                 # 无 QWidget；Board/ViewRef/Placement 序列化 DTO
├── chart_stack/ultraview/
│   ├── page.py                        # 中央 UltraViewPage
│   ├── scene.py                       # QGraphicsScene、选择、拖拽、整板导出
│   ├── card_item.py                   # 只读 QImage 卡片和状态 overlay
│   ├── layouts.py                     # 模板与纯几何计算
│   └── preview_store.py               # PreviewRecord、像素预算、状态派生
└── main_window/
    └── ultraview_coordinator.py        # manager 信号、抓图、导航、持久化装配
```

归属原则：

- `chart_stack/` 继续拥有中心画布组合与卡片呈现；
- `ultraview_state.py` 不导入 MainWindow 或分析计算代码；
- `UltraViewCoordinator` 是唯一跨 section 协调者，MainWindow 只持有一个 collaborator，不新增分散的多文件裸状态；
- `project_io.py` 只收发普通 dict，不导入 Qt 图像对象；
- 不把新实现塞进 `ui/canvases.py` 或 `ui/pg_canvases.py` 兼容 facade。

现有 `tests/ui/test_main_window_state_ownership.py:1-70` 是 shrink-only ratchet；实现不应为 UltraView 扩大白名单。

### 7.2 核心状态结构

```python
@dataclass(frozen=True)
class UltraViewRef:
    section: str
    view_id: str

@dataclass
class CardPlacement:
    slot_id: str
    ref: UltraViewRef

@dataclass
class UltraViewBoardState:
    board_id: str
    name: str
    layout_id: str
    primary_ratio: float
    placements: list[CardPlacement]
    unplaced: list[UltraViewRef]
    show_titles: bool = True
    show_sources: bool = True

@dataclass
class PreviewRecord:
    ref: UltraViewRef
    image: QImage | None
    captured_revision: str | None
    source_revision: str | None
    axis_kind: str
    x_unit: str
    x_range: tuple[float, float] | None
    captured_at: datetime | None
    title_snapshot: str
```

`PreviewRecord.status` 由当前 ref 是否存在、是否有 image、两个 revision 是否相等派生，不作为可随意写入的第五份真相。

### 7.3 预览产生时机

P0 不为所有 View 后台重画，采用事件驱动抓图：

1. 离开当前源 View、源模式或进入 UltraView 前，在当前绘制已经稳定且非 job-running 时抓取当前可见源 View；若尚未稳定则跳过并保留旧预览；
2. 一次分析结果成功写入缓存并完成可见渲染后，刷新对应 View 预览；
3. 用户在当前可见源 View 上执行“加入 UltraView”时，立即抓取；
4. View 发生图像相关编辑但尚未重新抓图时，只推进 source revision，使旧预览进入 `stale`；
5. View 删除后不删 Board 卡片，只转为 `orphaned`；
6. 预览发布事件必须携带捕获时的 `section + view_id + source_revision`；异步结果晚到时，若 View 已删除或 revision 已变化，只能丢弃该帧，不能把旧结果标成 fresh；
7. 预览抓取失败要记录 warning 并显示 `missing/stale`，不能用 1×1 透明 fallback 伪装成功。

现有 `_render_view_to_canvas()` 是时域 View 应用与绘制的集中路径，见 `mf4_analyzer/ui/main_window/_view_mixin.py:305-350`；分析结果写入已有 `_store_analysis_result()` 单一入口，见 `mf4_analyzer/ui/main_window/_analysis_mixin.py:834-855`。实现应围绕这些真实完成点发布预览，而不是轮询所有 manager。

### 7.4 Revision 计算

推荐为每个 View 计算稳定 presentation digest：

- 时域：`ViewState.to_dict()` 中影响图像的字段 + 已解析数据 revision + filter display revision；
- 分析：`AnalysisViewState.to_dict()` 中 panes/params/compare + 绑定的实际 cache key/result generation + 显示参数；
- 排除：View 名称、tab_color、列表下标和当前选中状态；
- 使用稳定 JSON 序列化后 hash，不使用 Python 进程随机 hash。

不能只比较时间戳。时间戳可显示，但不能作为正确性身份。

### 7.5 大画布实现

推荐固定 scene 坐标，例如 1600 × 900：

- `QGraphicsView` 负责 pan、zoom、fit-to-window；
- `LayoutEngine` 将模板和比例变成各 slot 的 `QRectF`；
- `UltraViewCardItem` 自绘标题、边框、状态和 QImage；
- 卡片移动只交换 slot，不保存任意屏幕像素坐标；
- scene export 通过 `QPainter + QGraphicsScene.render()` 输出完整 board rect；
- 所有 QPixmap 创建与 QWidget 抓取必须在 GUI 线程；PreviewStore 优先持有 `QImage`，显示时再在 GUI 线程转换。

不推荐给每张卡片嵌一个 `QGraphicsProxyWidget` + 完整 pyqtgraph canvas。六张活画布会引入多套 ViewBox、信号、timer、hover 和 GPU/CPU 绘制成本，也容易产生“只是总览却比分析页更重”的反效果。

### 7.6 内存预算

一张 1200 × 700、RGBA32 的未压缩图约 3.2 MiB；六张约 19.2 MiB。若宽高都放大到 2×，六张会接近 77 MiB，尚未计入 QPixmap/Qt 复制。

P0 建议：

- PreviewStore 按总像素做 LRU 预算，而不是只按条目数；
- 默认最长边 1200～1600 px；
- 只保留 Board 中引用项和最近访问项的高分辨率图；
- 非 Board 项可保留较小缩略图或淘汰；
- 导出 2× 时不无条件把所有预览再放大 2×，避免伪清晰和瞬时内存峰值；
- 清项目、删除 View、关闭窗口时对称清理图像和信号。

具体像素预算应由真实六图 Cocoa 探针决定，而不是在方案阶段写死。

## 8. “零计算”技术契约

### 8.1 允许的动作

UltraView 内允许：

- 查 ViewManager 的普通状态；
- 从 PreviewStore 读 QImage 和元数据；
- scene 布局、缩放、选择、过滤、演示和导出；
- 导航到源 View；
- 接收源工作区已完成渲染后发布的预览。

### 8.2 禁止的动作

UltraView 页面和 coordinator 在 UltraView 操作链上不得调用：

- `do_fft()`、`do_fft_time()`、`do_frf()`、`do_order_time()`；
- `_recompute_analysis_section()`；
- `AnalysisJobService.submit()` / `submit_batch()`；
- `_render_analysis_view_from_cache()`；
- `_render_view_to_canvas()` 或 `_plot_time_on_canvas()` 去生成非当前 View 的隐藏预览。

原因不仅是性能。当前 `_render_analysis_view_from_cache()` 的注释虽然写“切换不自动计算”，实际还承担项目恢复的一次性重算例外，见 `mf4_analyzer/ui/main_window/_analysis_mixin.py:321-375` 和 `867-908`。UltraView 必须有独立的纯 preview read 路径，不能依赖调用者记得清 `_analysis_restore_pending`。

### 8.3 可执行证明

应新增测试，在以下操作前后记录任务服务提交计数：

```text
进入 UltraView
→ 添加 6 个 View
→ 切 4 种布局
→ 拖拽/按钮换位
→ 切轴筛选
→ 放大/退出
→ 演示/退出
→ 导出 PNG
→ 打开/保存只含 UltraView 布局的项目
```

预期：`AnalysisJobService.submit + submit_batch` 的 UltraView 归因提交数为 **0**。

UI 上的 `0 JOBS` 只能作为反馈，不能替代这个测试。

## 9. 分阶段技术路线

### P0：只读快照 Board（推荐现在实现）

交付内容：

- `总览 / UltraView` 模式入口；
- 一个项目级 Board；
- View 库、搜索、添加、替换、移出、重排；
- 2/4/6 图固定模板和主图比例；
- fresh/stale/missing/orphaned 四态；
- 只读临时放大、打开原 View；
- 轴类型筛选和范围/单位提示；
- zoom、fit、presentation；
- 复制整板图和 PNG 导出；
- Board 引用与布局的项目持久化；
- 零分析任务证明。

P0 的核心优势是：不需要重构数值计算，也不需要同时实例化多套活 canvas。

### P1：缓存结果到预览的独立渲染器（有证据再做）

目标：即使某个 View 当前没有可见 QWidget，只要分析数值缓存仍在，也能在不计算的情况下重建预览。

约束：

- 只能读取已有 cache result；cache miss 仍显示 `missing`；
- 独立 renderer 不投影共享 Navigator/Inspector，不修改当前 View；
- Qt 对象全部在 GUI 线程；
- 复用现有 canvas presenter/DTO，不能复制 FFT/FRF/Order 数值算法；
- renderer parity 只证明路径一致，还要有 owner-level 正确性测试和真实图像 diff。

P1 只有在 P0 使用证据证明“缺失预览太多”时再做。

### P2：单卡片临时活化（可选）

若用户确实需要在总览中移动游标或局部缩放，可一次只把选中卡片提升为独立 live canvas，其余卡片仍是图片。退出选中态后释放 live canvas 并回写新预览。

P2 不允许六张卡片全部常驻 live，也不允许把源 QWidget 重新 parent 到 UltraView。

## 10. 最终成品效果

### 10.1 默认画面

用户点击顶部“总览”后：

- 左侧从文件/通道导航切换成按模式分组的 View 库；
- 中央是一张浅色大画布，默认 `主图 + 3 辅图`；
- 上方显示 Board 名、布局、添加、适应窗口、导出、缩放和演示；
- 画布上沿显示对比轨道、轴类别数量和范围一致性；
- 右侧 Inspector 显示所选卡片的布局角色、比例、显示项和操作；
- 底部明确显示“UltraView 未提交任何分析任务”。

卡片使用源 View 的颜色与名称，但有稳定的 section 标签和来源摘要。用户无需记住“刚才那张图是什么”。

### 10.2 典型工作流

```text
在时域发现 6.2 s 冲击
→ 在频谱 View 确认 118 Hz 峰值
→ 在时频 View 看到峰值只在换挡阶段出现
→ 在阶次 View 对照 6 阶脊线
→ 进入 UltraView
→ 把四个已有 View 放入“主图 + 3 辅图”
→ 仅看频率轴或调整主图比例
→ 临时放大核对
→ 导出整板 PNG 用于评审
```

整个 UltraView 阶段不重新计算。某个结果过期时仍保留上次图像并标注“源已变化”，用户决定是否返回原 View 重新计算。

### 10.3 异常与空状态

- 没有 View：中央显示“先在任意分析区创建 View”，左侧仍可查看已有空 View；
- View 有源但从未计算：显示“尚无可用结果，UltraView 不会后台计算”；
- 源 View 改了参数：旧图保留，右上角显示 stale；
- 源 View 删除：卡片位置和标题快照保留，可重新绑定；
- 小屏：侧栏可收起，Board 可 fit；卡片不降到不可读尺寸；
- 切换小容量模板：超出项进入未放置区，不丢引用。

交互 HTML 已经可演示三种场景、四种模板、搜索/添加、卡片换位、比例、轴筛选、四态、临时放大、缩放、演示和摘要导出；但其折线和热图是示意 SVG，不是 TraceLab 实际输出。

## 11. 验收标准

### 11.1 功能验收

- [ ] 能把 time / fft / fft_time / frf / order 的 View 混合放入同一 Board。
- [ ] 至少支持 2、4、6 图布局；主图比例可调整并持久化。
- [ ] View 改名/重排后引用不漂移；同名 View 不合并。
- [ ] 时域 split 的两个 View 分别成为卡片；分析双 pane 作为一个 View 完整预览。
- [ ] 布局缩容不静默丢卡片。
- [ ] fresh/stale/missing/orphaned 状态由真实状态派生。
- [ ] 打开原 View 能按 `view_id` 找到正确对象。
- [ ] UltraView 操作不修改源 View 参数、源、坐标或缓存绑定。
- [ ] 保存/重开项目后 Board 布局和 orphaned 状态正确恢复。
- [ ] 导出包含整板而不是当前可见 viewport。
- [ ] `submit/submit_batch` 归因计数为 0。

### 11.2 自动化测试建议

新增：

```text
tests/ui/test_ultraview_state.py
tests/ui/test_ultraview_preview_store.py
tests/ui/test_ultraview_page.py
tests/ui/test_ultraview_job_isolation.py
tests/ui/test_ultraview_navigation.py
```

扩展：

```text
tests/test_project_io.py
tests/ui/test_project_session.py
tests/ui/test_main_window_state_ownership.py
tests/ui/test_import_boundaries.py
tests/ui/test_hints.py
tests/ui/test_quickref.py
```

重点边界：空 View、重复名称、删除/重排、项目 fid remap、split、cache miss、抓图 null/1×1 fallback、非有限坐标范围、DPR、关闭项目时清理、异步 job 完成时 View 已删除。

### 11.3 视觉与性能验收

- [ ] 1280 × 800、1600 × 900、Retina/高 DPI 各完成正常、selected、stale、missing、orphaned、演示截图。
- [ ] 自动比较截图，检查卡片裁切、文字溢出、状态遮挡、空槽和侧栏恢复。
- [ ] 前景 macOS Cocoa 验证与 offscreen Qt 验证分开记录。
- [ ] 六图切换布局、缩放和演示无明显主线程长停顿。
- [ ] PreviewStore 像素预算和淘汰策略有可观测统计。
- [ ] 导出 2× 不超过既定内存峰值，失败有用户可见反馈。

建议 focused gate 从新测试开始，再带上项目/边界门：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest \
  tests/ui/test_ultraview_state.py \
  tests/ui/test_ultraview_preview_store.py \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_job_isolation.py \
  tests/ui/test_ultraview_navigation.py \
  tests/test_project_io.py \
  tests/ui/test_project_session.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_import_boundaries.py
```

UI 实现完成后还要按产品契约同步 `mf4_analyzer/ui/hints.py` 和 `mf4_analyzer/ui/quickref.py`，不能只靠新按钮自解释。

## 12. 主要风险与控制

| 风险 | 影响 | 控制 |
|---|---|---|
| 误用缓存恢复入口触发计算 | 违反核心承诺 | 独立 PreviewStore 读路径 + job submit 计数测试 |
| 六张 live canvas | 卡顿、Qt 生命周期复杂 | P0 全部 QImage；P2 最多一张临时 live |
| View 用下标定位 | 重排后指错图 | 只用 `(section, view_id)` |
| 改参数后仍显示旧图且无提示 | 误判结果 | revision 派生 stale，保留旧图但醒目标注 |
| 切小布局静默丢引用 | 用户数据/组织丢失 | 未放置托盘，不截断 |
| 项目中嵌预览导致膨胀 | 文件巨大、移动语义变化 | P0 不持久化像素；sidecar 另立决策 |
| 预览抓取发生在错误线程 | Qt crash | QWidget grab/QPixmap 限定 GUI 线程，存储 QImage |
| 新模式只改一半路由 | toolbar/Inspector/恢复失配 | mode、hints、quickref、project round-trip 联合门 |
| SVG 名义矢量、实际位图 | 用户期待错误 | P0 明确 PNG/复制，PDF 可嵌位图 |
| 同轴提示误导跨量纲比较 | 错误结论 | 同时比较 axis kind、unit、range，只做警告不联动 |

## 13. 建议实施顺序

1. 冻结 `UltraViewRef / BoardState / 四态 / 零计算` 契约，先写纯状态和 job-isolation 红测。
2. 建 PreviewStore 与像素预算，用现有真实 canvas 抓图测试锁住 time、line、heatmap、FRF、双 pane。
3. 建 `QGraphicsScene` Board 和模板几何，先完成 2×2 与主图+3，再补 3×2。
4. 接 View 库、Inspector、稳定 ID 导航和 source revision 信号。
5. 扩展 toolbar / ChartStack / Inspector mode route / hints / quickref。
6. 扩展项目 schema、round-trip、旧项目迁移和 orphaned 恢复。
7. 完成整板导出、演示模式、内存探针和自动截图 diff。
8. 最后进行前景 Cocoa 验收；没有真实证据前，不启动 P1 hidden/cache renderer。

## 14. 需要 Claude 重点审查的问题

请 Claude 不只补功能清单，而是按 `P0 阻断 / P1 优化 / P2 远期` 给出 findings，并重点挑战：

1. P0 不持久化预览像素，项目重开后可能出现 `missing`，是否符合用户预期？是否值得引入显式 sidecar？
2. 2～6 图模板是否足够，还是首版必须支持 8 图或自由网格？若增加，最低可读尺寸如何证明？
3. presentation revision 的字段集合是否遗漏了会改变像素的状态，尤其 filter、annotation、dB reference、time range 与 FRF 双端源？
4. 分析结果完成、View 切换、模式切换三个抓图时机是否覆盖所有 fresh 路径，是否会重复抓图或抓到半渲染帧？
5. “打开原 View”后现有项目恢复自动重算应如何向用户解释？本报告倾向保留既有源工作区语义，不允许 UltraView 为满足宣传口径去清除 pending restore；如果产品要求导航后也绝对不重算，应单独修改并迁移项目恢复契约。
6. `QGraphicsItem` 自绘卡片与 QWidget card 的可访问性、键盘焦点、拖拽和 QSS 一致性，哪条实现成本更合理？
7. 预览失效是否应复用现有 cache invalidation 事件，还是另建 source revision；如何避免第二套错误的 cache identity？
8. Layout 缩容的“未放置托盘”是否应持久化，删除/重新绑定的状态迁移是否完备？
9. P0 导出只做 PNG/复制是否足够；若需要 PDF，分辨率、字体和位图嵌入契约是什么？
10. 新模式接入是否还有本报告未列出的 mode-specific 分支、测试或帮助文档入口？

Claude 的评审输出建议包含：

- 严重级别和用户可见影响；
- 精确 `file:line` 证据；
- 对本报告每一项改动的建议措辞；
- 一份修订后的 P0 边界；
- 若判断可实施，再给出按 owner 拆分的任务序列，而不是直接开始大范围编码。

## 15. 当前证据边界

已确认：

- 当前代码结构、View 身份、缓存 pinning、抓图接口、项目 schema、模式路由和项目恢复重算例外；
- HTML 原型文件存在，默认和窄窗口主要状态已做真实浏览器检查；
- 原型的场景、布局、搜索/添加、按钮换位、状态、焦点、缩放、演示和 Inspector 交互可运行；
- 原型没有控制台错误。

尚未证明：

- 原生 PyQt UltraView 的前景视觉效果；
- 六张真实 TraceLab 预览同时驻留的内存和交互帧耗；
- native drag/drop 的 macOS 行为；
- 项目 sidecar 方案；
- Windows frozen 包中的最终显示与导出。

因此本报告的实施判断是 **GO for P0 design/implementation**，不是“功能已完成”。
