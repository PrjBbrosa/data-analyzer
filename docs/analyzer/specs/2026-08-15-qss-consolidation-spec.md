# style.qss 系统性瘦身与护栏 —— 设计 spec

- 日期：2026-08-15
- 依据：本文 §5 的盘点（2026-08-15 在 `codex/v8-hardening-ultraview-polish`
  工作区实测；该分支 `style.qss` 含未提交的 UltraView 改动，行号以当时工作区为准，
  执行时须按 plan Task 1 的脚本重扫，**不要**直接照抄本文行号删）
- 配套 plan：`docs/analyzer/plans/2026-08-15-qss-consolidation-plan.md`
- 前置门：UltraView P0–P3 系列收口、`style.qss` 无未提交改动后才执行
  （§3.1 C 类名字在迁移期被刻意保留，见 `style.qss` "Legacy toolbar/compare/tray
  names stay styled while their operations move" 注释）

## 1. 为什么做 / 为什么不是「重写整理」

`style.qss` 当前 4671 行 / 141 KB，约 670 个规则块、898 个不同选择器、引用
443 个 objectName。「长」本身大部分是合理开销——QSS 无嵌套、逐状态成规则，
且大量注释承载设计依据（为什么这个值、对齐哪个原型），是资产不是冗余。
真正的问题是三类**可量化**的漂移，且每类都在持续增长、没有任何机械看守：

1. **死选择器**。443 个 objectName 与全仓字符串字面量做词边界集合对比，
   39 个在生产代码零命中（另 5 个是动态拼接/Qt 内部名的假阳性，§3.2 白名单承接）。
   涉及约 50 个规则块、350+ 行。典型成因：控件重做后旧 QSS 段没人删
   （channelConfigManager 老 QDialog 家族 19 个名字 vs 现行的
   `channelConfigManagerHtml` 段；`chartHint`/`chartHintPersistent` vs 现行的
   `chartHintBar` 家族——测试甚至已在断言旧名**不存在**）。
2. **色值漂移**。1008 处 6 位 hex 字面量、大小写归一后 252 个不同色值；
   仅蓝色系就有 `#1769e0`(53 处，即 `CONTROL_ACCENT`)、`#2d7ff9`、`#2563eb`、
   `#145fc8`、`#0f3f8f` 等近似值并存。关键事实：**token 机制已经存在**——
   `{{CONTROL_*}}`/`{{ICON_*}}` 模板（`ui_kit/control_style.CONTROL_QSS_TOKENS` +
   `ui_kit/stylesheet.load_stylesheet` 替换）已有 32 种 token、180 处引用，
   `tests/ui_kit/test_selection_signature.py` 也已在钉「选中态家族必须走 token」。
   问题只是覆盖率（约 15%）与近似色归并，不需要发明新机制。
3. **重复定义**。46 个选择器定义了 2 次以上（`QFrame#ultraViewUnplacedTray` 等
   3 次）。其中一部分是**刻意的级联覆盖**（segmented-choice 段注释明说要放在
   Inspector 规则之后；UltraView legacy 段），一部分是漂移。没有白名单区分，
   review 无从判断新增的第二处定义是有意还是事故。

不做的原因同样明确（§3.5）：大爆炸重排/按组件分章会同时踩「QSS 级联顺序即语义」
和「注释是设计档案」两条线，收益只有观感；本 spec 的路线是**删死码 + 归并近似色 +
白名单化重复块**，每一步独立可验，配三道新护栏防止回潮。

## 2. 量化收益

- 删除 ~350 行确认死规则（约 7.5%），QSS 死名从 39 → 9（仅存 UltraView
  迁移挂起段，白名单标注、收口后清零）。
- 新增护栏三道（§3.2/§3.3/§3.4 各一），三类漂移从「靠 review 记得」变成
  「红了就修」，与状态所有权棘轮同一 shrink-only 语义。
- distinct 色值从 252 开始只减不增；蓝系近似色第一批归并进既有 token。
- 46 个重复定义选择器全部获得「刻意/漂移」判定，刻意者白名单留档理由。

执行旁注（`codex/qss-consolidation`，基于 `3971d5a3`）：`style.qss`
4581→4393 行（−188）。本 HEAD 的 C 类 9 名已被 UltraView A prune，故少于
盘点估的 −350。死名 34→5（仅 `QT_INTERNAL`+`DYNAMIC`；`MIGRATION` 空）。
distinct 6-hex 247→243。重复选择器 44 项全部白名单、0 归并。Cocoa 真机
未做，是剩余门禁。

## 3. 设计决策

### 3.1 死名逐名裁决，三分类，不批量删

盘点产出的 44 个候选按证据分三类（完整清单见 §5.2）：

- **A 类·确认死（29 名）**：全仓零命中，且多数有独立退役证据——
  `BatchPresetSourceNote` 被 `tests/ui/test_batch_method_buttons.py:546` 断言
  `findChildren(...) == []`；`chartHint` 被 `tests/ui/test_chart_stack.py` 三处
  断言不在 toolbar 里；`channelDeleteList` 在 QSS 注释里自书「已退役」；
  channelConfigManager 老家族对应控件已被 HTML 版
  （`channelConfigManagerHtml`/`channelConfigHtml*`）整体替代。→ 本批删除。
- **B 类·死于生产但被契约测试钉着（1 名）**：`frfSegmentChoice` 生产代码不设此名
  （`role="frf-segment"` 亦零命中），但 `tests/ui_kit/test_selection_signature.py`
  的签名家族表里有它，删 QSS 会红。→ 先 `git log -S` 考古：若控件确已退役，
  QSS 四块与测试表行**同一提交成对删除**；若是预留能力，成对保留并在 QSS
  注释标明消费方。禁止只删一侧。
- **C 类·UltraView 迁移期挂起（9 名）**：`ultraViewPopover`/`ultraViewFilterPopover`
  等孤儿名。迁移期 legacy 名保持样式是**刻意决策**（QSS 尾段注释），且该文件
  正被在途分支改写。→ 本批**不删**，进 liveness 白名单 MIGRATION 段并回指本
  spec，由 UltraView 收口 plan 负责清删（plan Task 6 挂钩）。

判定方法的已知边界（liveness 护栏实现必须继承，§5.1 有踩坑记录）：
`setObjectName` 走 f-string / 变量传参时字面量比对会假阳性
（`f"{role}Dot"` → `frfInputDot`、`f"ultraViewRail{short_name}Button"`）。
这类名字进白名单 DYNAMIC 段并注明拼接点；逐名裁决时人工核对 construction site。

### 3.2 护栏一：QSS objectName liveness 棘轮（新测试）

`tests/ui_kit/test_qss_selector_liveness.py`：

- 从 `style.qss` 提取全部 `#objectName`（**词边界**正则，两条实现红线：
  ① `#chartHint` 不得匹配进 `#chartHintBar`、`#channelConfigManager` 不得匹配进
  `#channelConfigManagerHtml`——后接字符不得为 `[A-Za-z0-9_]`；② **不要按花括号
  配对解析块**——`{{CONTROL_*}}` 双花括号会打断配对，按选择器文本扫即可；
  hex 颜色 `#1769e0` 按「纯 hex 且长 3/6/8」排除）。
- 对照 `mf4_analyzer/` 下 `*.py` 的字符串字面量集合（测试里的 absence 断言
  不算活；`tests/` 不计入）。零命中者必须在白名单。
- 白名单三段、各附理由：`QT_INTERNAL`（`qt_scrollarea_viewport`）、
  `DYNAMIC`（4 名，各注 f-string 拼接点文件:行）、`MIGRATION`（C 类 9 名，
  回指本 spec 与 UltraView 收口 plan）。前两段常驻，MIGRATION 段与
  整表 shrink-only——语义同 `test_main_window_state_ownership` 的棘轮。

### 3.3 护栏二 + 色板收敛：扩展既有 token，不建新机制

- 归并只走 `CONTROL_QSS_TOKENS`（收口点已存在，**不新建**第二张色表）。
- **token 化判据**：一个色值出现 ≥3 处、或属于交互态家族（hover/checked/
  disabled 与 rest 成组）才 token 化；单一控件的专属色保留字面量——全量 token 化
  只添间接性，不是目标。
- 第一批只做蓝系（`CONTROL_ACCENT` 的近似值群）：逐色裁决「语义相同→归并到
  既有 token」vs「语义不同（dark/wash/hover 变体）→检查是否已有对应 token，
  没有则评估新增 token 或保留字面量」。灰系等后续批次照此模式，不在本批强求。
- **验收分层**（这是与 §3.1 删除的关键区别）：删死规则预期**零像素变化**，
  offscreen 全窗截图逐像素比对即可兜底；色板归并**预期像素变化**，必须真机
  截图对比（CLAUDE.md Gotcha「验真机渲染」），对比脚本自动输出 diff 图供裁决，
  不丢人工清单。
- 护栏：`tests/ui_kit/test_qss_palette_ratchet.py`，distinct 6 位 hex 计数
  shrink-only（起点为执行时实测值，盘点日为 252）。只此一个计数，不做 per-family
  细分——过度设计。

### 3.4 护栏三：重复定义白名单 lint

- `tests/ui_kit/test_qss_duplicate_selectors.py`：同一选择器（逗号拆分、空白
  归一）定义 ≥2 次者必须在白名单，白名单每项附理由（如「segmented-choice 须后于
  Inspector 局部规则」「UltraView legacy 迁移期保留」），shrink-only。
- 归并的保守规则：**只允许**「两块声明完全相同」或「一块是另一块严格子集」的
  显然情况；有疑义一律保留进白名单。**归并不移动块的位置**——QSS 级联对顺序
  敏感，移动即改语义；把差异并进先出现的块、删后块，也仅在两块之间没有其他
  可能命中同一 widget 的规则时才允许，否则不动。

### 3.5 明确不做

- **不重排文件、不按组件重新分章**：顺序即级联语义，注释是设计档案，重排的
  回归面与收益完全不成比例。
- **不拆多文件**：`load_stylesheet` 是单文件模板管线（icon-cache 替换 + 失败
  降级路径），Qt `setStyleSheet` 最终也是单串；拆分不减少一条规则，反而让
  顺序敏感的级联跨文件。未来若真要拆，另立 spec。
- **不引入 SCSS/预处理器**：既有 `{{TOKEN}}` 机制已够用，新工具链是打包脚本
  与四个测试契约的额外扇出面。

## 4. 验证门

- 全量按 CLAUDE.md 两条命令跑（主体 `--ignore=tests/acquisition_ui` + 该目录
  单独）；动手前记当前失败数，绝对 venv 路径。
- 既有 QSS 契约测试全绿是每个 Task 的硬门：`test_qss_border_shorthand` ·
  `test_selection_signature` · `test_compact_spinbox` · `test_view_tabbar` ·
  `test_batch_signal_picker` · `test_batch_compact_contract` · `test_inspector` ·
  `test_toolbar` · `test_qmenu_density` 等（plan Task 0 先枚举一遍再动手）。
- 视觉验收自动化：删除步 offscreen 截图哈希等同；归并步真机对比 + diff 图。

## 5. 盘点方法与数字（2026-08-15 实测）

### 5.1 方法与踩坑（liveness 测试实现的输入）

- 规模：`wc -l` 4671 行 / 141,483 B；规则块 ~670、distinct 选择器 898
  （解析前先把注释与 `url(...)`/渐变括号遮罩，否则 `qlineargradient` 的
  `stop:` 会被误当选择器）。
- 色值：`#[0-9a-fA-F]{6}` 计 1008 处 / 归一后 252 个；top：`#ffffff`×131、
  `#1769e0`×53、`#64748b`×47、`#dfe5ee`×35、`#eef2f7`×34、`#111827`×32。
- token：`{{...}}` 计 180 处 / 32 种。
- 死名：QSS objectName 集合(443) 对 `mf4_analyzer/**/*.py` 字符串字面量做
  `comm -23`，44 候选；再全仓（含 tests/tools/scripts）子串复扫甄别。
  **两次假阳性教训**：① 子串前缀（`chartHint`⊂`chartHintBar`）；② `{{TOKEN}}`
  花括号打断块解析导致 `frfSegmentChoice` 家族漏扫。词边界 + 按选择器文本扫
  之后复核通过。

### 5.2 死名清单（44 = A29 + B1 + C9 + 假阳性5）

- **A 类（29，删除）**：channelConfigManager 老 QDialog 家族 19 名（约
  260–353 行整段：channelConfigManager / -Header / -Title / -Subtitle / -Footer /
  -Toolbar / -Content / -Table / -Detail / -DetailTitle / -DetailDescription /
  -Eyebrow / -FieldLabel / -Note / -Count / -Hint / -Delete / -Create / -Search）·
  chartHint（~3283）· chartHintPersistent（~3533–3581 四块）·
  channelDeleteList（仅剩注释）· BatchPresetSourceNote（~424，有 absence 测试）·
  BatchToolbarMeta（~691）· BatchAnalysisPresetOption（~714–747 七块）·
  versionTag（~3238）· healthDisconnectButton（~1588）·
  rightMetricValue / rightMetricDetail（~1810）。
- **B 类（1，成对裁决）**：frfSegmentChoice（~2224–2247 四块 +
  `test_selection_signature.py` 表行）。
- **C 类（9，MIGRATION 白名单挂起）**：ultraViewBoardColumn ·
  ultraViewPopover · ultraViewFilterPopover · ultraViewLibraryPopover ·
  ultraViewUnplacedPopover · ultraViewUnplacedBadge · ultraViewFilterWarning ·
  ultraViewNavigationZoomLabel · ultraViewStatusIslandText。
- **假阳性（5，常驻白名单）**：frfInputDot / frfOutputDot
  （`contextual_frf.py:479` `f"{role}Dot"`）· ultraViewRailUnplacedBadge /
  ultraViewRailUnplacedButton（`ultraview/chrome.py:420/431`
  `f"ultraViewRail{short_name}…"`）· qt_scrollarea_viewport（Qt 内部名）。
