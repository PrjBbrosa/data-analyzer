# UltraView P3：画布交互改版 + 遗留收口 Implementation Plan

日期：2026-08-14 · 作者：Claude · 状态：**DRAFT / NOT AUTHORIZED FOR EXECUTION**
Spec：`docs/analyzer/specs/2026-08-14-ultraview-p3-canvas-interaction-spec.md`
里程碑：**P3-0 遗留收口 → P3-1 直接操纵 → P3-2 视口变换**。每个里程碑可独立
交付；P3-2 受 Task 0 spike 结果门控。

## 0. 动工前置（gate）

1. 用户批准 spec（含 §3 四条默认裁决 D1–D4；任何一条被推翻先改 spec 再动工）。
2. `codex/ultraview-p1-p2` 分支的 P1/P2 真机验收补齐或明确豁免——本包改写手势层，
   若老手势永不真机验收即被替换，须在提交信息里记录该决定，避免验收账目断链。
3. 基线记录（动手前实测并写进本节，不许事后补）：
   ```bash
   TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
     tests/ui/test_ultraview_state.py tests/ui/test_ultraview_page.py \
     tests/ui/test_ultraview_free_grid.py tests/ui/test_ultraview_export.py \
     tests/ui/test_ultraview_preview_sidecar.py tests/ui/test_ultraview_preview_store.py \
     tests/ui/test_ultraview_layouts.py tests/ui/test_ultraview_project_session.py \
     tests/ui/test_ultraview_job_isolation.py tests/ui/test_ultraview_entry.py \
     tests/ui/test_ultraview_probes.py tests/ui/test_ultraview_mode_integration.py -q
   ```
   2026-08-14 于 `60516a72`：**229 passed / 0 failed**。另跑四个棘轮
   （state ownership / backref / lambda / import boundary）确认全绿。

## Milestone P3-0：遗留收口

### Task 0 — 真机 spike（P3-2 的 go/no-go，先做）
- 产出：`docs/analyzer/verify/2026-08-14-ultraview-zoom-spike.md`。
- 内容：临时脚本（不合入产品代码）在真机 Cocoa 验证——
  a) QNativeGestureEvent pinch 在 PyQt5 下的事件到达率与增量质量；
  b) 24 卡 QWidget 逐卡 setGeometry + pixmap Fast 重采样的连续缩放帧率；
  c) zoom 因子进 `grid_metrics` 的两种插入位（缩放入参视口 vs 缩放 metrics 字段）
     哪个改动面小。
- 判据（spec §9）：掉帧或 pinch 不可靠 → P3-2 暂停，改评估 Tier 2；其余任务照常。

### Task 1 — 小项收口（多维评审 §9 的 2/4/5/6）
- RED：
  1. digest 跨进程 characterization：两进程同一项目断言**具体状态**（fresh，或
     钉住"重开即 stale"为已知限制），删除 `in {"fresh","stale","missing"}` 放宽
     写法（`test_ultraview_project_session.py:125`）。
  2. `_watch_canvas_destroyed`：同一画布重复 load 项目 N 次后 `destroyed`
     接收器计数不随 N 增长。
  3. `page._previews/_statuses/_ref_exists`：移除 ref / 切 Board / reset 后
     缓存键集合收缩（不再只增不减）。
  4. 扩容回填（D4）：4→12 模板切换，托盘卡补位 + toast「已从托盘补位 N 张」；
     反向 12→4 溢出进托盘也有既有 warning——两方向都断言。
  5. 导出超限拒绝文案：断言 ComposeError 消息含具体尺寸与上限、以 toast 呈现。
- GREEN：逐条实现；`BoardSwitcher._on_tab_moved` 同步重建改 singleShot 交接；
  清理死代码（`GridGeometryCommand` 若 Task 3 不用则删、`organized_placements`
  与产品用的 `organize_free_grid` 二选一收敛——留产品那个并补幂等测试）。
  **注意**：`pixels_to_grid_delta` 不删，Task 2 转正。
- 同步：P1 plan Task 2 RED#3（`docs/analyzer/plans/2026-08-13-ultraview-p1-scalable-board-workspace-implementation.md`）「4→12 不自动将 tray 填回」由本 spec **D4** 推翻——保留 `set_layout` 回填 + toast「已从托盘补位 N 张」+ 双向测试。历史 plan 条文不改写，以本 spec 与提交信息为准。

## Milestone P3-1：直接操纵（去修饰键）

### Task 2 — 移动状态机 + ghost 层
- RED（全部用 QTest 真实鼠标事件驱动，禁止信号 emit 绕行——多维评审 §6 点名的空白）：
  1. 按下卡片拖过阈值进入移动态，ghost 出现且跟随；未过阈值 = 点击选中不变。
  2. 合法落点松手：几何一次提交、单条 undo；非法落点：弹回 + toast、undo 栈不变。
  3. 拖动中 Esc 取消 = 弹回、无提交。
  4. 落点判定与 coordinator `_legal_grid_rect` 同一夹取矩形（D2/S6 不回归）。
  5. 旧 layout-MIME QDrag 路径删除后，`make_layout_mime` 无引用（AST 或 grep 断言）。
- GREEN：新协作者 `gesture.py`（状态机）+ `ghost_overlay.py`（ghost/高亮/徽标/
  框选统一画层，透明背景 paintEvent 兜底）；复用 `pixels_to_grid_delta`/
  `candidate_move`/`rect_is_available`；提交走既有 `geometry_requested` intent。
  状态归属入协作者 `_owned_names`；无 lambda 连接。

### Task 3 — resize handle
- RED：真实事件——八向 handle 命中区 ≥8px、光标形状、拖动吸附整数格且
  span 徽标数值正确、Shift 保持比例、非法弹回、单条 undo；span clamp
  （2..12 / 2..8）在 handle 路径不可越。
- GREEN：handle 画在 ghost 层（选中态），resize 映射 `candidate_resize`；
  Alt+方向键/Alt+Shift+方向键键盘通道保留并复测。

### Task 4 — 数据操作重新安置 + 模板模式语义统一
- RED：
  1. 库/托盘拖入：空白放置；悬停已有卡 <0.6s 无环、≥0.6s 出环、环内松手替换、
     环外取消（真实 QDrag 事件序列）。
  2. 卡对卡替换旧路径（自由网格普通拖到另一卡）不再触发替换。
  3. 模板模式：拖卡到空槽 = 移动、到占用槽 = 交换，直接操纵实现，语义与 P0 等价
     （characterization 先钉现状再迁移）。
  4. 右键「替换为…」菜单路径可用。
- GREEN：意图环入 ghost 层；模板槽拖拽从 QDrag 迁到状态机；库/托盘 QDrag 保留
  且 `_run_ultraview_drag` 护栏不动。

### Task 5 — 多选与组操作
- RED：框选命中规则（相交即选）、Shift 加减选、组刚体平移原子提交单条 undo、
  组内任一非法整组弹回、Delete/Backspace 作用全组、Esc 清选。
- GREEN：选择集归 gesture 协作者；组移动 = 并集矩形合法性判定（spec §9 简化）。

### Task 6 — 发现性面与 P3-1 验收
- `/update-hints` 全量同步 hints/quickref；帮助页重写手势节，断言无
  「Alt+拖」残留（UV-P3-A15）；首次进入改版提示。
- 跑基线全组 + 棘轮；P3-1 真机 Cocoa 冒烟（拖动跟手性、ghost 无残影）记入
  verify 文档。

## Milestone P3-2：视口变换（受 Task 0 spike 门控）

### Task 7 — zoom/pan 核心
- RED：zoom-at-cursor 锚点数学（纯函数先行：光标下逻辑点缩放前后视口坐标不变）；
  25%–200% clamp；Ctrl+滚轮/pinch/空格拖/中键拖各通道；双档渲染（手势中 Fast、
  静止 300ms Smooth）用计时器测试钉住；缓冲复用断言（无每帧整板 ARGB 新分配）。
- GREEN：zoom 因子按 spike 结论插入 `grid_metrics`/`slot_rects` 映射；
  工具条 −/%/＋/fit/100%。

### Task 8 — 档位与 LOD
- RED：fit-to-board 档位数学；LOD 60%/40% 阈值带滞回不抖动；双击卡片
  zoom-to-card 动画终态 = 卡充满视口；overview 点击跳转能力在 fit 档位下等价
  （等价成立才允许退役 overview，否则保留并记录）。
- GREEN：LOD 在固定 chrome 档间切换；FocusLayer 保留，验收后单独提裁撤决定。

### Task 9 — FOCUS tier 接线 + 视口态持久化
- RED：显示尺寸超现存预览 0.75× 触发 FOCUS 重抓、离开降回、
  `MAX_PREVIEW_PIXELS` 预算不破（复用既有敌意预算测试模式）；
  viewport payload 往返、旧读者 passthrough 不销毁、非法值 clamp+warning、
  **digest 不含 viewport**（探针断言）。
- GREEN：打通 `set_pinned_refs`/residency `target_size` 生产路径（多维评审 S4
  另一半）；payload 增 digest 外 `viewport` 字段。

### Task 10 — 真机验收与收官
- `docs/analyzer/verify/2026-08-14-ultraview-p3-verification.md`：24 卡真机
  Cocoa 缩放/平移帧率读数（UV-P3-A07/A08）、Retina、两进程 digest、零计算探针
  全量（UV-P3-A12）。offscreen 结果一律标注不可替代真机。
- 版本扇出面检查（若发版）：`app_meta.APP_VERSION` 及 CLAUDE.md 列的全部同步点。

## 提交纪律

每 Task 一个提交（Task 1 可拆小项多提交）；改 P2 plan 合同（D4）与删除旧手势
路径（Task 2 RED#5）必须在提交信息里写明依据与指向本 spec；护栏（棘轮/探针）
只许收紧。

## 验证门

- 每 Task 收尾：UltraView 12 文件组 + 四棘轮全绿。
- 里程碑收尾：`tests/ui` 全目录（预期基线见 CLAUDE.md，主体与
  `tests/acquisition_ui` 分两条命令）。
- P3-1/P3-2 各一次真机 Cocoa 验收，产物入 `docs/analyzer/verify/`——
  **无真机读数不得声明里程碑完成**。
