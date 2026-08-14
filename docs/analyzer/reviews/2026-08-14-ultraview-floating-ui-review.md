# UltraView 浮岛 UI 评审（c4e8f6d1）+ P3 收口修复核对（09262e15）

日期：2026-08-14 · 审查者：Claude（接线审查子代理 + 修复核对子代理 + 主审截图
目检 17 张 offscreen 快照并交叉验证）
对象：`c4e8f6d1 feat(ultraview): add Miro-style narrow floating canvas`
（+2939/−183，契约 `2026-08-14-ultraview-miro-narrow-rail-spec.md` 方案 B）与
`09262e15 fix(ultraview): 收口 P3 执行评审的视口/手势缺陷`。

## 0. 总判定

- **09262e15（P3 收口）：收口。** 判定书 19 项修 18 项（唯一未动的 V10 是
  「疑似低危、部分既有」项，提交信息未声称覆盖，诚实）；高危 V1/V2/G1 修法
  正确且带回归测试；文档对账 3/3 落实；浮岛大提交未回退任何修复。
  验证组 251 passed / 0 failed。follow-up：V10、FOCUS 收敛端到端测试。
- **c4e8f6d1（浮岛 UI）：架构与护栏一等，工作流有三处死胡同 + 一批观感瑕疵，
  修复前不判收口。** 包装式改造（旧控件 façade 化，信号对账零遗漏）、digest/
  payload 纯净、四护栏全绿、新测试为实质断言。但「替换/重绑」「未放置」两条
  高频工作流被浮岛化断裂（实测确认），且视觉细节欠打磨。
- 测试：浮岛三新文件 + mode_integration + 入口/hints/quickref/ui_kit
  **253 passed / 0 failed**。

## 1. 09262e15 核对摘要

高危：V1（`focus_grab_scale` 按 target/0.75 一次补足 + 「下次抓取增益 <1px
即视为已达上限」停抓闭环）、V2（切板前快照 viewport + switching 全程
`_restoring_viewport` 包住投影）、G1（`PanSession` 记发起按键，release 按键
配对才结束；`begin_board_pan` 先取消在途手势）——均 FIXED 带测试。
中危 V3-V5/G2/G3/G6/G7 与低危批量（V6-V9/G4/G5/G8/G9/V-c/V-d）全部 FIXED；
G6 越界改判非法并区分「移出网格」「重叠」两个 toast，V8 用「文本框聚焦时禁用
快捷键」替代吞键，比判定书建议更优。小缺口：G3 托盘折叠态落点未测、FOCUS
上限停抓分支无直测。`79549678`（空会话禁保存钮）无副作用。

## 2. 浮岛 UI：架构与护栏（审过放心的部分）

包装非替代：BoardSwitcher/BoardToolbar/HintBar 隐藏为 façade，Library/
CompareRail/Tray 复用为画布覆盖层；**旧 connect 面零删除**，不存在信号迁移
遗漏。双入口状态同步（zoom 双写、set_board 全面同步、blockSignals 正确）无
漂移。浮层状态全部内存态，digest/payload/schema 纯净。QDrag 崩溃防护延续并
扩展到 viewport restore。护栏实测全绿：新 connect 零 lambda；新 327 行 QSS
无 border 简写；icons.py 分层干净；floating_layout 有 AST 守卫强制 Qt-free；
CanvasHost 不用 WA_TranslucentBackground（paintEvent 自绘点阵底）。
三个新测试文件是实质断言非冒烟壳。

## 3. 问题清单（接线审查 + 截图目检交叉确认，按严重度）

### 高（工作流死胡同，实测确认）
1. **「替换为…」/孤儿重绑 arm 后库不打开**：`focus_search()` 作用于隐藏浮层，
   用户点完菜单毫无反应（`page.py:1458`）。修法：`arm_replacement` 内先
   `_open_panel(PANEL_LIBRARY)`。
2. **轨道点「未放置」得到空浮层**：420×280 浮层出现但 body 折叠（实测
   `body visible: False`），只见标题「未放置 · 2」，内容要**再点一次**才展开
   ——截图 `unplaced_1280` 里那块空白正是它（`page.py:693-710`）。修法：
   `_open_panel(PANEL_UNPLACED)` 时 `set_expanded(True)`。旧测试的替代版恰好
   丢了「body 可见」断言，掩盖了此回归。
3. **库里「定位」未放置 View 无可见反应**：只改了内部 expanded 标志，浮层
   不开（`page.py:1776-1777`）。修法：unplaced 分支改开 PANEL_UNPLACED。

### 中
4. **rail 未放置徽章从未 resize**：实测 100×30、x=−11，渲染成横贯窄轨的
   绿条盖住图标（截图可见；`chrome.py:386-400`）。修法：`set_badge` 后
   `adjustSize()`/固定尺寸。
5. **空槽点击引导去一个关着的库**，feedback 文案还写「左侧 View 库」（旧 UI
   方位；`page.py:1625-1630`）。修法：无选择时先开库 + 更新文案。
6. **Board 菜单只能 ±1 排序**：从第 8 移到第 1 要开 7 次菜单；无 per-item
   复制/重命名/删除，偏离 spec §5.1（`page.py:727-780`）。
7. **spec §5.4 漏斗 warning dot 未实现**（轴不一致只剩状态岛文字）。
8. **card context 工具条不避让 chrome**：顶行卡片选中时叠在 Board/Global 岛
   上挡点击；BoardOverview 打开时仍被 raise 到其上，且 overview 期间缩放簇
   被整体盖住不可点（`floating_layout.py:260-291`、`page.py:681-686`）。
9. **QSS 死选择器一批**：`ultraViewNavigationZoomLabel`（实际 objectName 是
   `ultraViewNavZoomLabel`，缩放标签无样式）、`QFrame#ultraViewBoardPopover`
   （实为 QMenu）、Library/Filter/Unplaced Popover、StatusIslandText、
   UnplacedBadge 均无对应 widget；spec「等宽数字」落空（`style.qss:4406+`）。
10.（疑似）**状态岛 warning/error 变色可能不生效**：`set_status` 只 repolish
   岛自身，QSS 规则打在后代 QLabel 上需同步 repolish 子件（`chrome.py:740-746`），
   真机验证。

### 低 / 观感（主审截图目检）
11. 拖拽中关浮层的延迟保护只覆盖 library，tray/filter 被直接 hide（违 spec
    §7.2 字面，无 qFatal 风险）。
12. 缩容自动打开未聚焦新进入项；free-grid→模板溢出因 layout_id 不变不触发。
13. **底部浮层带永久盖住底行卡片 footer**：缩放簇/只读 chip 压住画布底缘
    ~40px（narrow_1280 的「基线 H1」、grid_6_1440 的 g3/g5 footer 均被盖）——
    floating_layout 文档字符串明示的取舍，但建议给画布加底部 content margin
    或浮层 hover 半透明。
14. **岛内容后拖白边**：布局岛约 60% 空白、筛选条右侧长空白、库浮层 224px
    低于 spec 的 264-288。岛尺寸未按内容收缩。
15. **演示模式右上胶囊保持全宽**只剩一个图标居中，两侧空白；孤儿卡在演示
    模式仍显示「重新绑定/从总览移除」交互按钮。
16. 任一左侧岛打开都盖住主卡标题行（hero 布局标题不可读）；rail 全高白条
    只有顶部 4 图标，下方大段留白（Miro 惯例是贴内容收缩）。
17. 杂项：resize 双重布局（sync+deferred）；隐藏 switcher 仍每次全量重建
    tabs（无用功，`page.py:1133`）；布局弹层是 QComboBox 非 spec §5.3 的八
    模板缩略图；未放置空状态无说明文案；verify 工具直调私有方法；plan 8 提交
    压成 1 个、Task 0 parity 冻结测试与 Task 7 零计算序列 probe 未补。
18.（疑似，待真机）连续快照中出现「触发钮 checked 但岛不可见」的组合
    （card_context/grid_6 快照右上中键高亮无岛）——可能是 harness 顺序残留，
    真机点一遍岛开关确认 checked 态与岛可见性严格同步。

## 4. 建议收口顺序

1. 高危三连 #1/#2/#3（全是「点了没反应」级的工作流断裂，各一行级修法）+
   #5 文案（同族）。
2. #4 徽章、#9 QSS 死选择器、#10 状态岛变色——观感三件套，一批修。
3. #8 card context/overview 避让、#13 底缘遮挡、#14 岛尺寸收缩。
4. spec 对齐决策：#6 Board 菜单排序、#7 warning dot、#17 布局缩略图——
   要么补实现要么改 spec 承认裁剪（走护栏纪律）。
5. 补 plan 欠的 Task 0 parity 冻结测试与零计算序列 probe；#18 真机点检
   随下一次 Cocoa 验收一并做。
