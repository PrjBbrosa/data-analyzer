# UltraView 标注对象（便签 + 箭头）—— 实施 plan

- 日期：2026-08-15 · 状态：**待授权**（spec DRAFT 同步待批）
- spec：`docs/analyzer/specs/2026-08-15-ultraview-annotation-notes-arrows-spec.md`
  （决策 D1–D8 与交互规范以 spec 为准，本文只排施工顺序与验收）
- 基线：`main@374eb176`。**硬前置**：本 plan 与 layout-and-material-polish /
  viewport-inspect-fixes / board-popover 三批共享 `page.py` `widgets.py`
  `gesture.py` `viewport.py`，必须等它们合入后再动工，动手前 `git status`
  对账并把本文行号锚点全部重定位。
- 规模预估：约 6 个工作 Task + 1 个收尾 Task，是一个完整 feature 批次
  （对齐 P3 的 spec/plan 范式），不是 polish 顺手活。

## §0 执行护栏

- 聚焦回归集：`pytest tests/ui -k ultraview`；收尾全量两条命令对账 CLAUDE.md
  2026-08-15 基线（主体 6978/13/9，9 红为既有顺序污染）。
- 每 Task 先红后绿；纯函数层（吸附/锚点/命中）先写 Qt-free 单测再接 UI。
- 禁区：卡片整格移动/碰撞规划/替换意图环合同不动；preview digest 不动（D8）；
  状态所有权与 backref 白名单不扩；新连接不用 lambda；`signal/` 不碰。
- 真机 Cocoa 验收强制（帧率 + 视觉），offscreen 只当排版草稿；验收自动化
  （截图/计时脚本，不丢人工清单）。
- 收尾 `/update-hints` 同步 hints/quickref；帮助页与 `test_help_content` 契约同批。

## Task 0：地基核实（硬前置，产出回填本文）

- [ ] **passthrough 保真 characterization（D6 的前置门）**：写测试证明 board 级
  未知键（模拟 `annotations`）经 load → 无关 mutation → save 后逐字节保留
  （`ultraview_state.py` 的 `passthrough` 机制 + coordinator 序列化路径）。
  **红了先修 passthrough 再继续本 plan**；绿了把证据行号回填此处。
- [ ] 手势状态机挂点：`gesture.py` 当前命中判定入口与优先级实现位置；确认
  「标注手柄 > 便签 > 箭头线 > 卡片 > 空白」可以插在单一 owner 内（spec §4.1），
  不需要第二输入路径。
- [ ] 透明层范式：`ghost_overlay.py` 的层生命周期/脏矩形更新方式，作为
  `annotations.py` 层的模板；确认与 ghost 层的 z 序关系（标注层在卡上、
  ghost 在最上）。
- [ ] 坐标链路：屏幕（zoom 缩放后的 `GridMetrics`，spike option B）与导出
  （`export_grid_metrics` 1600 宽）各自的 metrics 获取点；确认标注映射两侧
  可注入同一份纯函数。
- [ ] undo 快照：每板历史当前快照的字段面与恢复路径，确认 `annotations`
  列表进快照的改动点。
- [ ] 画布空白右键：确认当前空白无 contextMenu（起草时核实：仅卡片
  `widgets.py:1547,2122` 与旧 tab `widgets.py:634` 有），新增入口不与平移/
  框选手势冲突。

## Task 1：数据模型 + 纯函数层（Qt-free）

- [ ] `ultraview_state.py`：`NoteAnnotation` / `ArrowEndpoint` /
  `ArrowAnnotation` dataclass、`UltraViewBoardState.annotations` 字段、
  序列化/反序列化（additive、非法项丢弃 + `_warn`、未知 kind 透传）、
  D7 上限校验、坐标 clamp。
- [ ] 标注操作函数（同文件既有风格，返回 warnings）：`add_annotation` /
  `move_annotation` / `resize_note` / `set_note_text` / `set_annotation_color` /
  `set_arrow_style` / `set_arrow_endpoint` / `delete_annotations` /
  目标移除时的箭头退化函数（供卡片删除/移入未放置路径调用）。
- [ ] 几何纯函数（Qt-free）：`snap_fine(value, metrics)`（1/8 单元格）·
  `annotation_rect_px` · `auto_anchor_point(rect, toward)` ·
  `segment_hit(point, a, b, tol)` · 参考线求解（给定拖动矩形与视口内对象边
  集合 → 最近水平/垂直吸附线）。
- [ ] 测试：全部纯函数参数化单测（吸附步长严格相等、auto 锚点在边界方程上、
  命中容差边界、上限拒绝、序列化往返、未知 kind 透传、退化语义）。

## Task 2：状态接线 + undo + 持久化

- [ ] 标注操作接入每板 undo 栈（单条原子；文本编辑 = 提交时一条）；
  `mark_workspace_mutated` 全路径覆盖（D8）。
- [ ] 卡片删除/移入未放置路径调用箭头退化 + toast「箭头已脱离目标」。
- [ ] 载入/保存端到端：满载 50 对象 Board 往返字节级一致（spec 验收 5）；
  与 Task 0 characterization 组成双向证据。
- [ ] 模板模式（D5）：`layout_mode` 切换不动 annotations 数据；free_grid 侧
  可见性开关落在渲染层（Task 3）。

## Task 3：渲染层 `annotations.py`

- [ ] 新协作者：标注层 widget（透明层范式，`WA_TranslucentBackground` +
  paintEvent 兜底）；便签 = 子 QWidget（QSS 走 `ui_kit`，色板 6 语义色）；
  箭头/连接点/参考线/选中手柄 = paintEvent 绘制；`_owned_names` 声明状态归属。
- [ ] zoom 映射：屏幕 metrics → 逐便签 setGeometry + 箭头重画；线宽/字号随
  zoom（下限 1 物理 px）；LOD：<40% 便签只画色块（spec §4.2）。
- [ ] 脏矩形更新：拖动中只 update 受影响区域并集；不做整板缓冲每帧新分配
  （S5）。
- [ ] 演示模式：渲染保留、编辑面（手柄/连接点/右键）全关。
- [ ] 测试：offscreen 排版级——LOD 档位切换、zoom 下 rect 映射与纯函数一致、
  演示模式无编辑面；视觉观感留到 Task 7 真机。

## Task 4：手势与吸附

- [ ] gesture 状态机扩展：命中优先级（spec §4.1）、便签移动/8 向 resize
  （细 lattice + Shift 保比）、箭头端点拖动（悬停锚定高亮）、混合框选与
  组移动（有卡整组整格 / 纯标注细 lattice）、Delete、Esc 分层。
- [ ] 参考线：拖动中求解 + 层渲染 + 吸附覆盖 lattice；Alt 全关吸附。
- [ ] 创建入口：画布空白右键菜单（添加便签/添加箭头）；便签 hover 4 连接点
  拖出箭头（路径 A）；右键两击放置（路径 B，Esc 取消）。
- [ ] 卡片手势回归：P3 全套（整格移动/碰撞/意图环/框选）零变化——参数化
  跑现有测试集证明。
- [ ] 测试：真实鼠标事件（QTest 合成）驱动移动/吸附/锚定/退化/组移动；
  吸附断言用与实现同一份 metrics 计算期望值。

## Task 5：编辑与样式

- [ ] 便签双击编辑：内嵌 QTextEdit、IME 提交、点外/Esc 提交、空文本新便签
  自动删除、2000 字符上限；undo 一条。
- [ ] 色板 popover（便签+箭头共用，浮岛风格）；箭头样式小工具条
  （实/虚线、单/双箭头）。
- [ ] QSS：新增规则过 border 简写 lint；便签深浅色对比过可读性检查。
- [ ] 测试：编辑提交/取消/上限、色板换色 undo、样式切换持久化。

## Task 6：导出与整板复制

- [ ] `compositor.py`：导出路径按 `export_grid_metrics` 调同一份映射纯函数把
  标注画进 PNG 1×/2× 与整板复制；演示/导出不触发任何重抓（零计算）。
- [ ] parity 验收：同板屏幕 100% 截帧 vs 导出 1×，标注中心映射偏差 ≤1 px
  （spec 验收 2）——比相对位置与样式，不比两侧字号常量（parity 护栏思想）。
- [ ] minimap/整板概览 V1 不画标注；真机走查若观感割裂，补色块表示并回填
  spec 批注。

## Task 7：发现性面、帮助与真机收尾

- [ ] `/update-hints`：新增手势全量进 hints/quickref（右键创建、连接点拖出、
  Alt 关吸附、双击编辑）；契约测试同步。
- [ ] `help/ultraview-guide.html` 新段落 + `test_help_content` 对账。
- [ ] 真机 Cocoa 验收（自动化脚本挂 `tools/verify_ultraview_visuals.py`）：
  - 视觉：便签/箭头/参考线/连接点截图归档 `docs/analyzer/verify/`；
  - 性能：24 卡 + 50 标注连续缩放与拖动帧时间，不劣于无标注基线 10%
    （spec 验收 6），读数归档；
  - 手感：吸附/锚定/编辑真机走查（offscreen 不算数）。
- [ ] 全量两条命令对账基线；miro-narrow-rail spec 加日期批注（画布新增标注
  层，入口清单更新）。
