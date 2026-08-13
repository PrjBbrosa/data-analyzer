# UltraView 产品技术报告评审（Claude）

> 日期：2026-08-12
> 评审对象：`docs/analyzer/reviews/2026-08-12-ultraview-product-technical-report.md`（Codex，DRAFT FOR CLAUDE REVIEW）
> 附带核对：`docs/analyzer/ui-prototypes/2026-08-12-ultraview-interactive-demo.html`（全文通读）
> 代码证据基线：HEAD `3678227b`（报告快照 `ffdee19c` 之后 63 文件变动，本评审引用的行号均为当前实际值；核对方法：三路独立代码核查——View 身份/项目 IO、模式扇出穷举、抓图路径与渲染稳定性）

## 0. 结论

**维持 GO for P0，产品定位（只读快照投影 Board）正确，且与代码现实吻合。**
但报告有 **4 个技术前提经核查不成立或不完整**（F1–F4），照原文实施会分别导致：零计算承诺出现假阳性证明、预览系统性抓到空白/中间态帧、旧版本打开新项目未捕获崩溃、以及一块报告未计入的大额实现成本。另有 6 处需要在实现前改写措辞或收窄边界（F5–F10）。逐条见 §2。

原型本身作为交互方向成立：布局模板、四态表达、拖拽+按钮双路径、临时放大、演示模式都可直接映射；原型已知偏差（缩容静默截断、替换不进托盘、状态模拟按钮）报告均已声明不带入成品，核对无遗漏新增项。

## 1. 判定总表

| # | 严重级 | 报告位置 | 一句话判定 |
|---|---|---|---|
| F1 | 🔴 P0 阻断 | §8.3 / §6.1.6 | 零计算证明的探针选错：FFT 区完全绕开 `AnalysisJobService`，按 submit 计数会对最大的分区假阳性放行 |
| F2 | 🔴 P0 阻断 | §7.3.1 / §2.2-4 | 「渲染完成且稳定时抓图」前提不存在：全库没有 post-paint 信号；View 切换后 100ms 内新 View 绑的是空数组 |
| F3 | 🔴 P0 阻断 | §4.10 | `.tlproj` 兼容双雷：`current_mode="ultraview"` 会让旧版本未捕获崩溃；升 `SCHEMA_VERSION` 会让旧版本打不开一切新项目 |
| F4 | 🔴 P0 阻断 | §4.2 / §10.1 | 「View 库使用现有全局侧栏位置」没有现成挂点，是全方案最大的未计入成本；建议改为页内库 |
| F5 | 🟠 实现前修正 | §6.2.4 / Q10 | 第六模式扇出清单缺至少 12 处，其中 2 处是不登记就崩的硬雷 |
| F6 | 🟠 实现前修正 | §7.4 / Q3 | presentation digest 按 to_dict 计算会漏 4 类进了像素的状态（markup、游标位置、全局 filter、派生通道） |
| F7 | 🟠 实现前修正 | §4.9 / §7.6 | Retina 上 `grab_pixmap(scale=2)` 是 no-op、AA 不可负担时 2× 被静默打回 1×；内存预算按 1× 估算偏低 4 倍 |
| F8 | 🟠 实现前修正 | §7.3.7 / §3.3 | 1×1 fallback 的 `isNull()` 为 False，判废必须用尺寸阈值；退出 split 后 secondary 只隐藏不销毁，抓隐藏 widget 必得 1×1 |
| F9 | 🟠 实现前修正 | §3.2 | section 词汇有两套（GUI `order` vs batch `order_time`）且字面量散落 ≥6 处无中心定义 |
| F10 | 🟡 建议调整 | §4.8 / §5 / Q6 | UI 逻辑四处建议调整：砍画布缩放、QWidget 网格替代 QGraphicsScene、砍常驻 0-jobs 文案、加满入托盘 |

## 2. P0 阻断项详述

### F1 零计算证明的探针选错了

报告 §6.1.6 称「`AnalysisJobService.submit/submit_batch` 是可监控的任务入口……可用作零计算回归测试的探针」，§8.3 的验收也只数这两个方法。**核查不属实**：

- FFT 区全程不经过 job service——`_fft_mixin.py` 对 `_analysis_jobs` 零引用，主路径在 GUI 线程同步内联计算（`mf4_analyzer/ui/main_window/_fft_mixin.py:277` `_fft_compute_arrays`）后直接 `_store_analysis_result('fft', ...)`（`:285-286`）；legacy 单信号回退 `_do_fft_single`（`:303` 起）同样同步。
- 走服务的只有三区：order（`_order_mixin.py:409`）、fft_time（`fft_time_coordinator.py:135`）、frf（`frf_coordinator.py:118`）。
- 真正的**唯一写入漏斗是 `_store_analysis_result`**（`_analysis_mixin.py:837-858`，docstring 自称 "Single write funnel"，`:850` 是全仓唯一的 analysis cache put，共 5 个调用点）。

**修正**：`test_ultraview_job_isolation.py` 的探针改为三层同时计数——① 四个 `do_fft/do_fft_time/do_frf/do_order_time` 入口派发次数；② `submit/submit_batch`；③ `_store_analysis_result` 的新 key 写入。三者在 §8.3 的操作序列内归因 UltraView 的计数都必须为 0。§8.2 的禁调清单本身正确，不用改。

### F2 「渲染完成且稳定时抓图」前提在代码里不存在

报告 §7.3.1 要求「在当前绘制已经稳定且非 job-running 时抓取」。核查结论：**当前代码没有任何「最终质量帧已画完」的信号，且有一个报告未知的空白帧陷阱**：

- 唯一可订阅的 `quality_status_changed`（`canvas.py:281`）发射在 `_glw.update()` 之后、实际 paint 之前（`quality.py:694-705`）——green ≠ 像素已上屏，拿它当完成信号系统性早一帧。
- 全库唯一跑在 paint 之后的钩子是 `quality.py:87-127` 那个 `__class__`-swap 的 `paintEvent` 计时器，它的设计前提是交互帧零成本，刻意不发信号。
- **空白帧陷阱**：`_view_mixin.py:330` `defer_first_frame=(state.xlim is not None)` 一路传到 `overlay_axes.py:324-325` `bind_t = bind_s = np.empty(0)`——任何带保存视窗的 View 切换后头 ~100ms（`canvas.py:1070-1072` → interaction settle），曲线绑的是**空数组**。切换后立刻抓「新 View」= 抓到有轴无线的白图。
- 交互期降桶帧：`grab_pixmap` 自带 AA 临时强制（`renderer.py:910-912`），但**不重采样数据**——settle 前抓到的就是 coarse 桶。
- 热图侧：`heatmap_canvas.py:1444` 与 `analysis_section_page.py:486-490` 各有一个 `QTimer.singleShot(0, ...)` 的二次布局，结果写入后同步抓图必然抓到左轴未统一、slice panel 错位的中间态（好消息：无异步 LOD，不会抓到低分辨率占位图）。

**修正**（写进 spec 的具体抓图契约）：

1. View 切换抓图的**唯一安全挂点是 `_render_view_to_canvas` 入口**（`_view_mixin.py:306-323` 这 18 行内，旧 scene 完好），抓的是**旧 View**；并用「目标 idx ≠ 画布当前 View」排除 `_replot_canvas_for_view`（`:561-576`）的同 View 重绘，否则会把旧帧存错槽位。
2. 「进入 UltraView 前抓当前可见 View」「分析结果写入后抓」两个时机统一走组合稳定判据：`quality_status().state == 'green'` ∧ `dense_raster.quality_status()` green（`dense_raster.py:279-292`）∧ `_interaction_state == 'idle'` ∧ `not _refresh_pending`，满足后再 `singleShot(0)` 一轮让 paint 落地；不满足则跳过并保留旧预览（报告已有此回退，保留）。
3. 分析区的抓图触发点挂 `_store_analysis_result` 之后的绘制完成侧（调用方 `_plot_*` 之后延迟 ≥1 个事件循环轮），热图可加用 `layout_geometry_changed`（`heatmap_canvas.py:226`）。
4. 去重：按 `(ref, digest)` 防抖，digest 未变则跳过重复抓图（回答报告 Q4 的「重复抓图」担忧）。
5. post-paint 信号（给 `paintEvent` 钩子加节流 queued signal）留作 P1 优化，P0 不碰交互热路径。

### F3 `.tlproj` 兼容是双向雷，报告的「递增 schema 版本」方向反了

报告 §4.10 说「从当前项目 schema 版本递增到下一个可用版本」。核查发现两个具体机制让这个方向变成最差选项：

- **顶层版本是白名单+硬抛**：`SCHEMA_VERSION = 2`、`SUPPORTED_SCHEMA_VERSIONS = {1, 2}`（`project_io.py:17-18`），不在白名单直接 `raise UnsupportedProjectVersion`（`:93-100`）。升到 3 意味着**所有**新保存的项目（哪怕根本没碰 UltraView）旧版本一律打不开。仓库先例（`analysis_view_state.py:28-31`）是字段存在性容错、刻意不看版本号。
- **`current_mode` 是现成的崩溃链**：`ProjectDocument` 已有 `current_mode` 字段（`project_io.py:44`），读取端无白名单（`:121` 原样透传）。旧版本打开「在 UltraView 模式下保存」的项目：`_project_io_mixin.py:1737-1739` `toolbar._set_mode("ultraview")` → toolbar 软保护放行 emit（`toolbar.py:369-372`）→ `window.py:1605` → `stack.py:821` `_MODE_TO_INDEX[mode]` → **未捕获 `KeyError: 'ultraview'` 传播出 `open_project()`**。报告对此只字未提。

**修正**：

1. `ultraview` 字段**纯增量、不升 `SCHEMA_VERSION`**，读取走 `raw.get("ultraview", None)`。代价是旧版本打开→再保存会丢 UltraView 布局（静默忽略未知键），这个代价明确写进 spec 接受。
2. **`current_mode` 永不写 `"ultraview"`**：保存时若当前在 UltraView，映射回用户最近所在的源模式（coordinator 记一个 `last_source_mode`）。这同时消解了「重开项目直接落在全 missing 画布」的 UX 问题——用户总是先回到源工作区，预览随使用自然回补。
3. 防御性顺手改（只救未来版本，也要做）：`project_io.py:121` 读取端加白名单降级到 `"time"`；`stack.py:821` / `inspector.py:273` 硬下标改 `.get` 容错。

### F4 「View 库放全局左侧栏」没有挂点，是最大的未计入成本

报告 §4.2「左侧 View 库使用现有全局侧栏位置」、§10.1「左侧从文件/通道导航切换成 View 库」。核查结论：**左侧根本没有「按模式换面板」的机制**：

- 左中右是一个静态 QSplitter，`FileNavigator` 全程单实例不换（`window.py:313-333`）；`SidePanelController` 完全不感知 mode（`side_panels.py:205-260`，grep `mode` 零命中），且硬绑 `panel=self.navigator`（`window.py:360`）。
- 现有唯一按模式变化的是 `channel_tree.py:1289-1310` `set_projection_role` 的三态 role——改的是通道树**列语义**，装不下 View 卡片列表。
- 要换面板必须把左栏改成 QStackedWidget 并动 `self.navigator` 的 5+ 处直呼点（`window.py:382-383, 1616, 1633, 3040-3047` 及 `_analysis_mixin` 多处）+ `SidePanelController` 接线。

**修正（产品设计层面，不是硬啃重构）**：View 库放进 **UltraViewPage 页内**（中央页面自带左栏，原型的三栏布局在页内实现）。理由：

- ChartStack 换页是现成机制，页内布局零新增全局耦合；
- 全局 navigator 在 UltraView 模式保持原样（通道树对总览无意义但无害），或经 SidePanelController 现有的 HIDDEN/PEEK 状态自动收起——两者都不需要动侧栏架构；
- 演示模式「隐藏左右侧栏」也变成页内行为，可逆恢复更简单。

右侧 Inspector **维持报告方案**（全局 Inspector 加第五个 ctx）：`inspector.py:209-219` 的 `_ContextualStack` 是现成的分模式机制，扩展点明确（`:267-279` 加键、`:328-357` 加第三条路径、`:317-322` 加白名单）。左右不对称是合理的——一边有现成机制一边没有。

## 3. 实现前必须修正的技术细节（F5–F9）

### F5 第六模式扇出完整清单（回答报告 Q10）

报告 §6.2.4 列了 toolbar / Inspector / Navigator projection / mode route / hints / quickref / project I/O。**核查另发现以下缺项**，按危害排序：

**不登记就崩：**
- `stack.py:795-806` `hint_bar_for_mode()` 末尾 `raise KeyError(mode)`，被 `window.py:440-441` 的 `mode_changed` 无条件调用——UltraViewPage 必须提供可搬运的 hint bar（或改造该逻辑）。
- `window.py:1595-1648` `_on_mode_changed` 是 `if mode == 'time' / elif mode in analysis_managers` 二分，UltraView 两边都不属于会**静默无路由**（navigator projection role 残留上一模式），必须显式加第三分支。
- `inspector.py:267-279` `set_mode` 与 `:328-357` `_place_range_group_for_mode` 的硬下标 KeyError（后者还需要「既非 time 展开、也非分析内嵌」的第三条路径）。

**不登记则静默破相：**
- `style.qss:1182-1186` 逐个列举五个 segment 值，新按钮不加就没有 min-width/padding/字重；`icons.py:260-310` 需加 `mode_ultraview()`。
- 顶栏**没有窄宽压缩逻辑**（`_TOOLBAR_COMPACT_WIDTH` 是图表卡片工具栏的）。窗口最小 1100×640（`window.py:115`），第六按钮 ≈ +82px 会挤破 mode zone 居中（`toolbar.py:304-317` 镜像逻辑）。需实测 1100px 并决定：icon-only 压缩态 / 调 QSS min-width / 抬最小宽度。
- `_project_io_mixin.py:1506-1509` 保存前按「time / analysis」二分捕获活动 View，UltraView 是第三种情况会被漏掉。
- `_view_mixin.py:197-209` Alt+N 的四 section 白名单（UltraView 下 Alt+N 语义要定义，否则落到时域切换）；`window.py:749-762` `_visible_view_tabbar` 映射。
- `stack.py:326-334 / 957-986 / 1043` 四处硬列举遍历（`_all_cards`、`mark_discovered`、`set_annotation_enabled`、图片复制分支）。
- 帮助系统：`help/__init__.py:15-23` `_GUIDE_FILES` 登记 + 新 `ultraview-guide.html`，否则 Inspector 帮助链接 fallback 到 manual；`tools/gen_help_screenshots.py:49` `PANEL_MODES` 与 `tests/test_gen_help_screenshots.py:6` 的精确四元组断言。

**会红的既有测试契约（改动时一并同步，不是回归）：**
`tests/ui/test_toolbar.py:61-87`（five_exact_mode_names）、`tests/ui/test_chart_stack.py:115-119`（`count() == 5`）、`tests/ui/test_quickref.py:108-116/128-133`（组标题字符串「五个分析模式」+ 五行 desc 精确相等）、`tests/ui/test_hints.py:253-268`（rotation pool anchor 四组合）与 `:315-323`（`frozenset` 精确相等）、`tests/test_project_io.py` / `tests/ui/test_project_session.py` 的 `current_mode` 往返。快捷键若要配，必须先登记 `hints.py:140` `_SHORTCUTS`（`test_quickref.py:82` 契约锁定）。

### F6 presentation digest 的字段修正（回答报告 Q3）

`ViewState.to_dict()`（13 字段）/ `AnalysisViewState.to_dict()`（8 键，panes 展开 10 键）作 digest 基底方向正确，weighting / `db_reference(_mode)` 已在 `params` 内无需额外。但有 4 类**进了抓图像素、却不在 to_dict** 的状态：

| 状态 | 证据 | 处理建议 |
|---|---|---|
| markup 批注 | 从不落盘（`markup/serialization.py:18-19` session-local）；批注点/引线/文本是 scene item 会被抓进图（`remarks.py:101/114/123`） | markup 存储侧暴露一个递增计数器，纳入 digest |
| 游标/hover 线 | 只有 mode 落盘，位置在 canvas 上（`cursor.py:238-242/311-314/391-394`，zValue 1000/1100，会被抓进图） | **抓图时临时隐藏瞬态游标/hover item**（grab 上下文管理器），游标位置不进 digest——否则动一下游标就 stale |
| 全局 filter 显示 | 项目级单例 `{enabled, spec, show_original, show_filtered}`（`_project_io_mixin.py:1791-1800`），直接影响时域像素 | filter payload hash 纳入**时域** View 的 digest |
| 派生通道 | 内存态不落盘（`dialogs/channel_editor.py`） | 由「已解析数据 revision」承担（报告 §7.4 已有该项，确认其来源必须覆盖派生通道的增删改） |

另确认：`PaneState.source_time_view_id` 的往返丢失是被测试钉死的故意行为（`test_project_session.py:116`），digest 用内存态计算不受影响。

### F7 Retina 分辨率语义与内存预算

- `renderer.py:947-954` 用**逻辑宽度 × eff_scale** 算目标尺寸，而 Retina 上 `grab()` 的 raw 尺寸已是逻辑 ×2——`scale=2` 时 `scaled()` 尺寸相等直接原样返回，**2× 请求在 Retina 上是 no-op**（1× 屏上才真放大）。
- AA 不可负担时（`renderer.py:893-894` `_export_aa_affordable()` False）`eff_scale` 被静默打回 1×——密集图的预览分辨率不可预测。
- 热图路径（`heatmap_canvas.py:1911-1940`）无宽度上限、无 AA 闸门、无条件 2× smooth 放大——与时域是两套策略。
- DPR 归一化已有**三份拷贝**（`chart_stack/_helpers.py:68-75`、`analysis_section_page.py:247-250`、`markup/editor.py:67-73`），PreviewStore 别写第四份，抽取共用。

**修正**：PreviewStore 统一存 DPR 归一化到 1.0 的 QImage（raw 像素保留）；整板 2× 导出定义为「用存储的 raw 像素离屏合成」，不逐卡再放大；§7.6 内存预算按 **raw 像素**记账——报告的 19.2 MiB 六图估算在 Retina 实际约 77 MiB，「默认最长边 1200–1600px」应明确指 raw 像素，超出即入库时降采样（放大层是唯一高分辨率消费者）。

### F8 判废与 split 生命周期

- `renderer.py:922-924` 的 1×1 透明 fallback `isNull()` 为 **False**——报告 §7.3.7 说的「不能伪装成功」要落成机制：入库判废用尺寸阈值（如 `w < 8 or h < 8`），不是 null 检查。
- 退出 split 只是 `setVisible(False)` 不销毁（`stack.py:767-769`），对隐藏 widget `grab()` 会级联到 1×1 兜底——抓 secondary 前必须查 `split_active()`（`stack.py:408-413`）。split 双抓已有生产先例（`stack.py:491-492`），报告 §3.3 的双卡片方案可行性确认。
- 顺带：两条既有合成路径的 gutter 规则不一致（`_combined_split_pixmap` 固定 8px vs `grab_combined_pixmap` `4×scale`），UltraView 导出合成时按自己的产品常量走，别继承任何一个。

### F9 词汇与常量

- GUI 五区词汇 `{time, fft, fft_time, frf, order}` 与 batch/presets 的 `order_time`（`analysis_presets.py:22`、`batch.py:444`）是**两套不可互换的字符串**。UltraView 的 `ViewRef.section` 用 GUI 词汇，持久化读入时校验白名单。
- section 集合没有中心定义，字面量散落 ≥6 处（`analysis_context.py:88-100`、`stack.py:1043`、`_view_mixin.py:206`、`hints.py:445/502`、`inspector.py:273` 等）。P0 至少在 `ultraview_state.py` 里定义自己的 `SECTIONS` 常量作为单一来源；顺手收敛全局散落字面量不属于本次范围（会碰状态所有权之外的一堆文件），可另立小任务。

## 4. 页面 UI 逻辑调整建议（F10 展开）

1. **砍掉 70–125% 画布缩放**。卡片是像素预览，缩放没有信息增益；「适应窗口」+「临时放大」已覆盖两端需求。砍掉后 QGraphicsView 的 pan/zoom/fit 理由消失，见下条。原型用 CSS `zoom` 实现，恰说明它只是演示便利。
2. **QWidget 网格替代 QGraphicsScene**（回答报告 Q6）。QWidget 卡片天然获得 QSS 一致性、焦点链、tooltip、可访问性和标准 widget 拖放；卡片 chrome（标题/状态带）始终按 UI 字号渲染，小窗口下不随整板缩小。报告担心的「导出可复现」由**离屏合成**保住：`layouts.py` 纯几何函数以固定 1600×900×scale 版面算 slot 矩形，导出/复制走 QPainter 离屏拼装存储的预览 QImage——屏上布局与导出版面共用同一几何函数，但互不牵制。`QGraphicsScene.render` 整板导出的唯一优势随缩放功能一起消失。
3. **状态栏常驻「UltraView 未提交任何分析任务」与对比轨道的 `0 JOBS` 徽标不进成品**。零计算是工程契约，由 F1 修正后的测试看守；对用户是噪音。空态卡片上「UltraView 不会后台计算」的一次性文案保留（那是在解释为什么没图）。
4. **加满时入未放置托盘，不是拒绝**。原型加满弹 toast 拒绝；成品统一为「容量驱动的移位都进托盘」：布局缩容溢出、替换被顶掉、板满时添加，三者同一机制；用户显式「移出画布」才是真移除。托盘需要一个可见的常驻面（建议画布下沿可折叠条），并随 `unplaced` 持久化（回答报告 Q8：是，要持久化）。
5. **「重新绑定」复用替换流**，不做独立选择器对话框——原型已经是这么演示的（toast 引导拖拽替换），成品保持，orphaned 卡片上的按钮只是聚焦 View 库。
6. **放大层默认不超过 raw 像素 100%**（fit 优先），避免 1× 屏上把 1200px 预览吹到全屏的伪清晰；Retina 存的 raw 2× 像素在这里正好兑现价值。
7. **卡片加右键菜单**（打开原 View / 临时放大 / 替换 / 移出 / 复制本卡图像），桌面惯例；Inspector 按钮与其并存。单卡复制顺手实现（预览 QImage 已在手）。
8. 双击=放大维持原型语义；放大层底部把「打开原 View」做成**按钮**（原型只有说明文字）。

## 5. 对报告 §14 十个问题的逐条回答

1. **预览像素持久化**：P0 不持久化，立场维持；但 F3 的 `current_mode` 映射让重开项目总是落在源工作区，配合既有恢复重算语义，预览会随使用自然回补，「全 missing 画布」只在重开后直奔 UltraView 时出现。sidecar（PNG 压缩，`<项目名>.tlproj.previews/` 或单 zip，每卡 ~100–300KB）列为 **P1 第一项**而非可选杂项——「保存 Board 供评审」是核心场景，P0 的 PNG 导出只覆盖了一半。
2. **2–6 图模板**：够。6 图已是 1280px 屏的可读上限；8 图/自由网格等 P0 使用证据。维持报告结论。
3. **digest 字段**：见 F6，四处遗漏及处理方案。
4. **抓图时机**：三个时机方向对但规格要重写，见 F2（旧 View 挂点 + 组合稳定判据 + 延迟一轮 + digest 防抖去重）。
5. **打开原 View 后的恢复重算**：维持源工作区语义，不清 pending。补充两个必须写进实现的理由：UltraView 误调 `_render_analysis_view_from_cache` 不仅触发计算，还会**烧掉一次性恢复令牌且本次不出图**（`_analysis_mixin.py:886-911`：`discard` 在复检前，命中后直接 `return`），且 `do_fft` 入口可能弹模态框并回写 View 状态（`_fft_mixin.py:226/228`）。测试补一条：UltraView 全操作序列前后 `_analysis_restore_pending` 集合不变。
6. **QGraphicsItem vs QWidget**：QWidget，见 §4.2。
7. **复用 cache invalidation 还是新建 source revision**：都不要。用**按需计算的 digest**（进入/显示 UltraView 时对每张卡现算并与捕获时快照比较），不维护第二套推送式 revision 计数——推送式意味着给每条编辑路径插桩，漏一条就是静默 stale 失灵，这正是报告自己担心的「第二套错误的 cache identity」。cache/pin 事件只作为触发重算 digest 的信号源。
8. **托盘持久化**：是，见 §4.4；orphaned 在托盘中保持 orphaned，重新绑定=替换流。
9. **导出**：PNG + 复制足够，PDF 从 P0 砍掉（位图嵌入的 PDF 对评审场景无增量，字体/分辨率契约白付）。
10. **遗漏扇出**：见 F5 完整清单。

## 6. 修订后的 P0 边界

**新增进 P0 的**：
- 兼容决策二则（ultraview 字段不升 schema；`current_mode` 保存映射，加读取端白名单防御）；
- 修正后的零计算探针（三层计数）+ `_analysis_restore_pending` 不变式测试;
- 抓图契约四则（旧 View 挂点、组合稳定判据、分析侧延迟一轮、尺寸阈值判废）;
- 源工作区侧「加入总览」动作（报告 §7.3.3 提了时机但 P0 交付清单漏了入口本身——它是最便宜的 fresh 路径和发现面）;
- 未放置托盘的可见 UI + 持久化;
- 帮助页登记 + hints/quickref 同步（走 `/update-hints`）;
- 顶栏 1100px 宽度实测与压缩策略。

**从 P0 移除的**：
- 画布 70–125% 缩放（连带 QGraphicsView 方案）;
- PDF 导出;
- 全局左侧栏换面板（View 库改页内）;
- 状态栏常驻零计算文案。

**维持报告原样的**：只读投影五承诺、`(section, view_id)` 身份、2/4/6 模板 + 主图比例、四态模型、临时放大、演示模式、对比轨道与量纲/范围提示（提示基于 PreviewRecord 轴元数据，不做字符串比较——原型的 range 字符串 Set 比较仅为演示）、每项目单 Board、P1 独立渲染器 / P2 单卡活化的证据门槛。

## 7. 建议实施顺序（按 owner 拆分）

1. **契约冻结**（owner: 状态/序列化）：`ultraview_state.py` DTO + `SECTIONS` 常量 + digest 字段表（含 F6 四补丁）+ 兼容决策落 spec；红测先行：job isolation（三层探针）、restore-pending 不变式、state ownership 白名单不扩大。
2. **PreviewStore + 抓图管线**（owner: pg_canvas）：DPR 归一化共用 helper 抽取、尺寸判废、组合稳定判据、三个挂点（`_render_view_to_canvas` 入口 / `_store_analysis_result` 后延迟 / 进入 UltraView 前）、split_active 守卫；用真实 canvas 锁 time-line / heatmap / FRF / 双 pane / split 五种抓图。
3. **UltraViewPage 骨架**（owner: chart_stack）：页内三区（库 / 画布 / 托盘条）、`layouts.py` 纯几何、QWidget 卡片四态、键盘操作与右键菜单。
4. **模式接入**（owner: main_window）：F5 清单逐项登记（`_helpers` 索引、stack 第六页、hint bar、`_on_mode_changed` 第三分支、toolbar+QSS+icon、Inspector ctx + range group 第三路径、保存捕获第三分支、Alt+N 语义），同步改 F5 所列测试契约。
5. **项目持久化**（owner: project_io）：增量字段、`current_mode` 映射、round-trip、orphaned 恢复、旧项目/旧版本兼容测试（含「ultraview 字段被旧版静默丢弃」的显式用例）。
6. **导出与演示**（owner: chart_stack）：离屏合成 PNG/复制（共用 layouts 几何）、演示模式、Esc 优先级。
7. **收尾验收**（owner: 集成）：hints/quickref/帮助页、自动截图 diff（复用「视觉验收自动化」范式：两侧真机渲染 + 哈希对比）、前景 Cocoa 验收、PreviewStore 内存探针（raw 像素记账）。

P1 排序调整：sidecar 预览持久化提为 P1-1；post-paint 信号为 P1-2；缓存独立渲染器维持「有证据再做」。

## 8. 证据边界

本评审的全部 file:line 均在 HEAD `3678227b` 复核。未做的：真机内存/帧耗测量（报告 §15 已列为未证明项，维持）；1100px 顶栏挤压是按 QSS 常量推算的，实施第 4 步时需实测截图确认。
