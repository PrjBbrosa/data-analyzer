# UltraView 缩放锚点与临时查看同步 —— 实施 plan

- 日期:2026-08-15
- 来源:用户实测反馈四条(缩放锚点固定朝右上角 / 上限 200% 偏小 / 双击语义
  分层 / 临时查看不同步),其中**「上限 200%」一条用户裁决本批不做**。
- 基线:`main@374eb176`(post-v8-review-fixes 合入后)。
- 相关 spec:`docs/analyzer/specs/2026-08-14-ultraview-p3-canvas-interaction-spec.md`
  (画布 zoom/pan 手势契约)· `2026-08-14-ultraview-miro-narrow-rail-spec.md`。
  行为契约有变的项(Task 2 双击分层)要在对应 spec 加日期批注,不重写历史段落。
- 编写背景说明:本 plan 由 review 会话在项目子树临时 EPERM(CLAUDE.md Gotcha
  的 Downloads TCC 问题)状态下编写,**文件:行未逐一核实**,因此 Task 0 是
  硬前置:执行者先定位并把锚点行号回填到本文,再动手。方向性定性(锚点补偿
  缺失、digest 外状态不驱动缓存失效)来自 2026-08-15 全盘 review 期间对同一
  代码的深读,置信度高;涉及「现状究竟是什么」的两处存疑点已明确标注。

## §0 执行护栏

- 本机验证:`TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest tests/ui -k ultraview -q`
  为聚焦回归集(当前应为 502 passed 起点);收尾跑全量两条命令
  (主体 `--ignore=tests/acquisition_ui` + 该目录单独),对账基线见 CLAUDE.md
  2026-08-15 段(主体 6978/9/13,9 红为既有顺序污染,单跑绿,不算新增)。
- 每项修复配「能抓住原缺陷」的测试,先红后绿。
- 禁区:不动碰撞规划的硬契约(普通移动不改尺寸/全有全无)、LOD 阈值表、
  `.connect(lambda` 棘轮(新连接用 bound method/partial)、各棘轮白名单。
- 视觉/手感项(缩放跟手、临时查看重抓观感)offscreen 只当排版草稿,
  最终要 Cocoa 真机操作确认,不许拿单测绿宣告手感通过。
- UI 交互有增删改(Task 2 双击分层),收尾用 `/update-hints` 同步
  `ui/hints.py` 与 `ui/quickref.py` 两个发现性面。

## Task 0:定位与现状核实(硬前置,产出回填本文)

- [x] 缩放入口定位(`mf4_analyzer/ui/chart_stack/ultraview/`):
  - 数学原语:`viewport.py` `zoom_at`(~L124;旧名 `zoom_at_cursor` 为别名)。
  - 页面收口:`page.py` `_zoom_at`(~L1235)。Ctrl+滚轮 `handle_zoom_wheel`
    (~L1215)、捏合 `handle_pinch`(~L1223)、工具栏 ± `zoom_in`/`zoom_out`
    (~L1029) → `set_board_zoom`(~L1023,缺光标时锚视口中心)。
- [x] **存疑点 A(朝右上角)**:不是缺补偿,也不是 `AlignRight`。
  `_sync_board_stack_geometry` 曾把 host 做成 ≥ viewport,scrollbar max=0,
  `setValue` 把补偿钳到 0;内容钉在 **fit 原点**(轨右侧、顶岛下方的
  chrome-safe 左上)。用户看到的「右上」是相对轨道/顶栏的 fit 角。
  补偿后再按 fit 居中会把锚点再推走。修复:`_place_canvas_for_scroll`
  (~L2344)负 scroll → 左/上 pad,超出 max → 撑 host;zoom 后禁止再 fit-center。
- [x] 双击链路:卡片 `widgets.py` `UltraViewCard.mouseDoubleClickEvent`
  (~L1992) → `page.handle_card_double_click`(~L1372)。临时查看宿主是
  `FocusLayer`(`widgets.py` ~L4166;footer「临时查看 · 不改变源 View ·
  不超过原始像素 100%」)。`page._on_focus`(~L1969)先 `show_focus` 再
  `focus_requested`;coordinator `_on_focus`(~L1555)负责 stale 重抓。
- [x] **存疑点 B → 方案 A**:双击原为单向 `zoom_to_card`,不是 toggle。
  已铺满再双击原先会再跑一遍铺满(抖动),不进临时查看。
- [x] 缓存缺口:新鲜度原为 `PreviewStore.captured_digest`。Board viewport
  在 digest 外(`84e38391`);源 View 的 xlim/cursor_mode 等在 digest 里,
  但 `schedule_idle_capture` / `_on_idle_source_signal` 在 UltraView sheet
  **隐藏时直接 return**,单面板改缩放不重抓。关 overlay 只清
  `FocusLayer._image`,store 仍是旧帧;关整个 sheet 再开才走 refresh/capture。
  单 cursor hover 不得进 digest / 不得 bump revision(lesson
  `ultraview-idle-digest-keeps-armed-cursor`)。修复:会话内
  `_presentation_revision` + `PreviewRecord.captured_revision`,show 时
  digest+revision 校验,stale 则 FOCUS 重抓 +「同步中」角标。

## Task 1:缩放锚点跟随光标(bug 修复)

- [x] 抽一个统一原语(viewport 内):
  `zoom_at(anchor_vp, factor)`:取光标下板坐标
  `board_pt = (scroll + anchor_vp) / zoom_old`,clamp 新缩放,回设
  `scroll = board_pt * zoom_new - anchor_vp`,保证锚点不动。
- [x] **三类入口全部收口到该原语**:Ctrl+滚轮与捏合锚光标;工具栏 ±/快捷键
  锚视口中心。修一个漏一个是本项最大风险,禁止各入口各写一份补偿。
- [x] Task 0 存疑点 A 的干扰逻辑(居中/对齐)与锚点补偿的先后次序要显式定序
  (补偿后再居中会把锚点又推走)。
- [x] 测试:参数化「光标在四角+中心 × 放大/缩小」,断言缩放前后光标下的板
  坐标不变(容差 ≤1px);捏合路径若 offscreen 难驱动,用事件合成或把手势
  归一成对 `zoom_at` 的调用断言。
- [x] 边界:缩放到 clamp 上下限时锚点补偿不得引入滚动跳变;板小于视口
  (无滚动条)时补偿应退化为 no-op 不报错。

## Task 2:双击语义分层——已铺满再双击进入临时查看

按 Task 0 存疑点 B 的结论二选一,**不要两个都做**:

- [x] **方案 A(现状双击为单向铺满时)**:状态机分层——双击未铺满卡 → 铺满
  (现状不动);双击已铺满的同一张卡 → 打开该 View 的临时查看;退出铺满
  维持现有出口(Esc/其他)。连续 4 连击(两次双击)按此状态机自然落位,
  写一条用例钉住(铺满 → 临时查看,而不是抖动)。
- [ ] **方案 B(现状双击为 toggle 时)**:保留 toggle 不动,临时查看入口改
  Shift+双击,并在卡片 hover chrome 加一个显式「放大查看」按钮兜发现性
  (纯手势入口发现性差)。方案 B 落地前把取舍(为何不占用二次双击)写进
  spec 批注。
- [x] 无论 A/B:临时查看已打开时再次双击不得叠开第二层 overlay(幂等);
  与卡片选中/替换意图环/演示模式的组合态各写一条冲突用例。
- [x] spec 批注(P3 交互 spec 手势表)+ 收尾 `/update-hints`。
- [x] **依赖**:本 Task 验收必须在 Task 3 合入之后做(否则二次双击进的是
  旧帧,验收结论失真)。

## Task 3:临时查看与源 View 状态同步(bug 修复,优先级最高)

- [x] 根因按 Task 0 核实,预期形状:临时查看缓存按 digest 判新鲜,而
  zoom/cursor 等呈现态在 digest 外 → 数据不变则复用旧帧;关闭销毁缓存才
  被迫重抓。修法 a+b 组合:
  - **a. 呈现修订号**:为 digest 外的呈现态(缩放、cursor、标注等会改变
    渲染结果的状态)加单调递增 revision,源 View 每次变更 +1;临时查看的
    缓存键/新鲜度判据 = digest + revision。
  - **b. show 时校验重抓**:overlay 每次显示先比对 revision,不新鲜就异步
    重抓(复用 FOCUS 高分重抓机制),期间显示旧帧 + 「同步中」角标,抓完
    换帧——不许静默糊帧,也不许同步阻塞。
- [x] 保住「不改变源 View」单向契约:只有源 → 临时的同步,临时查看内的任何
  操作不得反写 revision 或源状态(写一条守卫用例)。
- [x] 测试:精确复现用户路径(开临时查看 → 关 → 改缩放/cursor → 再开),
  断言新帧(修复前红);再断「数据与呈现态都没变时重开不触发重抓」
  (防把缓存修成永远失效)。
- [x] 注意 revision 落不落盘:若呈现态本身随项目持久化,revision 只需会话内
  内存计数,不进项目文件、不进 digest(别把 digest 语义改宽,那是
  `84e38391` 的刻意边界)。

## 收尾

- [x] 聚焦回归集全绿(`tests/ui -k ultraview` + hints/quickref/QSS border/
  lambda 棘轮:**532 passed**)。全量两条命令:
  主体 `--ignore=tests/acquisition_ui`:**6998 passed / 11 failed /
  13 skipped**;`tests/acquisition_ui`:**359 passed**。11 红里 9 条与
  `2026-08-15-post-v8-batch-review.md` §6 顺序污染集同名;另 2 条
  (`test_qss_palette_ratchet` 天花板从 244 收到 241、
  `test_qss_selector_liveness` 钉死的 `chrome.py` 行号)来自同 worktree
  里并行的 library/chrome QSS 改动,不是本 plan 的 zoom/inspect 逻辑。
- [ ] Cocoa 真机操作确认:四角缩放跟手、双击分层手感、临时查看重开即新。
- [x] `/update-hints` 同步;spec 批注落盘;本文 Task 0 的回填与各复选框勾完。
- [x] 「上限 200%」的放宽(含高分重抓触发条件扩展)本批明确不做,如后续要做
  另立条目,前置阅读本文编写背景与 2026-08-15 讨论记录。
