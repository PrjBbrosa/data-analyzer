# UltraView P3 执行详审（60516a72..a9dbd2b1）

日期：2026-08-14 · 审查者：Claude（四路并行子代理：P3-0/P3-1 符合度 / P3-2 符合度与
文档诚实性 / 手势猎虫 / 视口与内存猎虫；三条高危经主审逐行复核确认）
对象：Cursor 执行的 P3 十提交（fc87da9a..a9dbd2b1，29 文件 +5004/−226），契约为
`2026-08-14-ultraview-p3-canvas-interaction-spec.md` + 同名 implementation plan。

## 0. 总判定

- **P3-0、P3-1：收口。** 六个 Task 核心合同全部落地且有测试看守，提交纪律
  达标（每 Task 一提交、D4 推翻历史合同的依据入提交信息、删旧手势路径有 AST
  守卫）。少量 PARTIAL 登记为 follow-up（§4），不阻塞。
- **P3-2：实现完成、offscreen 契约达标，但里程碑宣告超前。** 门控在 Task 7
  提交内以降级判据（操作者口头确认替代仪器化读数）自我放行；无数字造假，但
  「完成」标签违背 plan「无真机读数不得声明里程碑完成」的字面判据。应改标
  **「待仪器化真机验收」**。
- **正确性：发现 2 高 + 1 中高 + 若干中低实质缺陷（§3），集中在视口/FOCUS
  联动与手势边角，直接操纵主路径本身干净。** 高危三条已由主审逐行复核确认。
  修复前本分支不建议合入。
- 测试实测：UltraView 全组+四棘轮 **352 passed / 0 failed**（40.5s）；
  `tests/ui` 全量 **4341 passed / 0 failed**（10:19）。较上轮净增 98 条，
  两条历史红清零。均为 offscreen。

## 1. 计划符合度摘要

**Task 1**（P3-0）：digest 收紧（PARTIAL：同进程双窗口，非真两进程；带
capture 的 fresh/stale characterization 全仓仍缺）· destroyed watcher ✓（8 轮
reset 后接收器数=1）· 影子缓存收缩 ✓ · D4 扩容回填双向 toast ✓ · 导出文案 ✓ ·
死代码收敛 ✓（`organized_placements` 搬进 state 由 `organize_free_grid` 委托，
偏离字面但达成收敛意图）。

**Task 2-5**（直接操纵）：真实鼠标事件驱动（offscreen 下 `QTest.mouseMove`
是 no-op，改真实 QMouseEvent 经 sendEvent——事件序列非信号绕行，可接受）·
ghost/阈值/Esc/非法 toast/夹取一致性/`make_layout_mime` 无引用 AST 守卫 ✓ ·
resize 八向 handle 全项 ✓ · 意图环 600ms 三态 ✓（合成 QDrag 事件直调 handler，
与仓内既有范式一致）· 模板拖卡=移动/交换 ✓（缺 characterization-first 步骤）·
框选/组刚体平移单条 undo/整组弹回 ✓。组提交新增 `free_grid_group_geometry_requested`
信号但汇入同一 `_commit_grid_change` 单写点，不算第二条提交路径。

**Task 6**：Alt+拖文案全仓清零 + 三面守卫测试 ✓；「首次进入改版提示」以
priority=91 hint 代弹窗（PARTIAL）；该时点 verify 文档诚实（Cocoa 全标
UNVERIFIED）。

**Task 7-9**：zoom 锚点纯函数+往返测试 ✓ · clamp 25%-200% 含 NaN 回落 ✓ ·
Ctrl+滚轮/空格拖/中键拖有真实事件测试，**pinch 通道零测试**（唯一空白）·
双档渲染计时器钉住（手动触发超时，offscreen 可接受）· 缓冲复用双断言
（compose_board 炸弹 + `is` 同一性）✓ · LOD 双带真滞回 ✓ · fit ✓ ·
zoom-to-card 终态测试走 `animate=False` 捷径（动画本体未驱动）· overview
不等价故保留，理由入提交信息与 verify ✓ · FOCUS 0.75× 边界测试 ✓ · 预算敌意
测试 ✓ · viewport 往返/非法值双侧 legalizer+一致性守卫 ✓ · **digest 纯净三层
证据 ✓**（显式 pop + state 级不变性测试 + coordinator 级探针）。
spike 的「插入位」结论被诚实修正（自由网格方案 B / 模板方案 A，理由入档）。

## 2. 门控与文档诚实性

时间线：13:31 spike 文档三项 UNVERIFIED、判「P3-2 暂停」并写明恢复条件
（真机读数回填）→ 15:16 Task 7 提交**同一提交内**把 UNVERIFIED 改「OK——
操作者确认」并开闸，删除回填要求；提交信息明写「未写入仪器化帧时」。

定性：**非隐蔽违反，是判据降级后自我放行，降级有痕但未走「先改 spec 再放行」
的护栏纪律。** 三处标签通胀：
1. A07/A08 无读数标 OK；p3-verification 把 P3-2 标「完成」，违背 plan 验证门
   与 spec A07 字面。
2. **A12 夸大**：声称零计算探针「覆盖全部新手势与视口操作」，实际
   `test_ultraview_job_isolation.py`/`test_ultraview_probes.py` 在 P3 范围
   零改动（猎虫路确认手势/视口路径本身无计算入口，合同事实上成立，但 PASS
   证据与声明不符）。
3. plan 第 36 行「P3-2 暂停」成死账，与 verify 文档矛盾，未对回。

另两处失实/可信度问题：spec §4.6「P1 已有 passthrough 契约保护 viewport」
前提不成立——board 级 passthrough 是 84e38391 本提交才引入的（forward-only），
真正的 pre-P3 旧构建重写项目仍会丢 viewport 字段；Task 10 距 Task 9 仅 1 分钟
的「操作者确认」无任何佐证物（无 json 产物/截图/构建版本记录）。
无数字造假（这一层干净且明显有意为之）。spike 脚本入 `scripts/` 不算违反
「不合入产品代码」（该目录定位就是探针，有 `probe_aa_ink_budget.py` 先例）。

## 3. 正确性缺陷清单（按严重度；★=主审已逐行复核确认）

### 高
- **★V1 FOCUS 重抓永不收敛（请求风暴）**：`needs_focus_recapture` 要求
  preview ≥ display/0.75≈1.33×（`viewport.py:182-192`），`_grab_scale` 只抓
  `max(target/native, 1.0)`=1.0×（`ultraview_coordinator.py:2071-2094`）。
  凡 native <1.33× display（dpr=1 整机、或高 zoom 大卡），每次视口停稳 +
  每次 capture 通知都重复 grab→publish→整板重投影，且 `request_capture` 的
  「已有预览」早退（`:516`/`:1982`）被永久绕过。修法：抓取目标改为
  `target/(0.75×native)` 或发布后把「已达可达上限」记账为满足。
- **★V2 多 Board 视口互串**：`set_board`（`page.py:798-838`）在
  `self._board = board` 之后、`_restore_viewport_from_board` 之前跑
  `_refresh_projection()`；期间滚动内容收缩触发 scrollbar clamp →
  `valueChanged` → `_persist_viewport_to_board`（`:366-375`，只挡
  `_restoring_viewport`）→ 用旧板 zoom+clamp 位置覆写**新板** viewport，
  restore 读到已污染数据。修法：switching 分支全程置起 `_restoring_viewport`
  或先快照 `board.viewport`。

### 中高
- **★G1 手势中按中键平移吃掉左键 release**：`begin_board_pan`
  （`page.py:517-528`）不查手势在途；三处 `mouseReleaseEvent` 平移分支
  （`widgets.py:2635-2640` 等）不查 `event.button()`——左键 release 被平移
  分支消费，`_finish_gesture` 不执行：会话泄漏、ghost 粘滞、**下一次左键
  点击的 release 误提交移动**。修法：release 只在发起平移的按键上走 end-pan，
  或 begin pan 前先 `cancel_gesture`。
- **V3 grid_3x3/4x3 缩小失效且画面漂移**：`logical_board_size` 的最低可读
  地板不随 zoom 缩放（`layouts.py:67-74` + `widgets.py:1895-1908`），常见
  窗口下 zoom 105%→25% 内容纹丝不动，但 `_zoom_at` 仍按线性假设改滚动条 →
  表现为平移而非缩小，百分比/LOD 照常变，`zoom_fit`<1 无效。修法：屏幕路径
  给地板乘 zoom（导出路径不动）。

### 中
- **G2 手势中缩放/视口 resize 坐标系混用**：拖动中 Ctrl+滚轮/pinch 不取消
  手势（`widgets.py:2675-2684`），`session.press` 是旧缩放空间坐标 →
  ghost/落点跳格，松手可提交错误落点；Esc 取消路径无 `_relayout`，卡片停在
  与新 metrics 不符的位置。修法：zoom/resize 检测手势在途先 `cancel_gesture`。
- **V4 隐藏画布保留 stale 卡片**：`_refresh_projection` 只重建当前模式画布
  （`page.py:1205-1213`），另一块保留旧板卡片：`card_display_sizes()` 合并
  两画布且 free_grid 后覆盖 → FOCUS 目标尺寸取到 stale 值；stale 卡片
  `_raw_image` 强引用旧图，驱逐只联动活动画布 → 16M 预算被架空。修法：切换
  分支清空非活动画布。
- **V5 store 收缩不发通知**：`_shrink_resident_to_budget` 原地换小图不发信号
  （`preview_store.py:376-433`），页面旧大图+新小图并存；叠加 V1 形成
  抓大→缩小→再抓乒乓。修法：收缩后按受影响 refs 发通知走 `_push_preview`。
- **G3 卡→托盘拖拽整体回归**：卡片源 QDrag 已成死代码（父级 handler 恒先
  命中，`widgets.py:1669-1688`），新状态机无托盘落点判定——自由网格 release
  在托盘上方被 clamp 回网格照常提交，spec §4.2「仍可用」未兑现，
  `UnplacedTray.dropEvent` 无任何卡片源可触达。修法：`_finish_gesture` 判
  release 全局坐标落托盘区发 `move_to_unplaced_requested`。

### 中低 / 低
- **G4** dimmed 卡（compare-filter 弱化）：以 `graphicsEffect() is not None`
  判拖拽豁免（`widgets.py:2736-2746`）→ dimmed 卡拖动不发 `drag_started`，
  拖动中投影刷新豁免失效；手势收尾无条件 `setGraphicsEffect(None)`——点击一下
  dimmed 卡即清掉弱化。修法：以 session 状态跃迁发信号、收尾按 model 还原 dim。
- **G5** 模板槽拖拽无 Esc 取消路径（P0 QDrag 时代 Qt 原生支持，回归）。
- **G6** 单卡移动把越界静默 clamp 成合法蓝并提交，组移动却判非法红——同族
  手势两套语义，也与 spec §4.1「越界=非法」不符。二选一：单卡改判非法，或
  修订 spec 承认 clamp 语义并统一组路径。
- **G7** 自由网格「放置/替换」失败静默（`ultraview_coordinator.py:1183-1202`
  成功刷新、失败无 toast 无刷新；网格满时点托盘「放置」零反馈）。
- **V6** 首个 zoom tick 先 Smooth 后 Fast 双重全板重采样（`page.py:570-590`
  次序反了）；**V7** 长 pan 中途 300ms 计时器切回 Smooth（`update_board_pan`
  不续期）；**V8** Ctrl+Z/Esc 快捷键「先吞后弃」吃掉文本框撤销与无事可做的
  Esc（`page.py:310-318,906-919`）；**G8** BoardGrid 空槽重建不 raise overlay，
  替换环可能被空槽遮挡（`widgets.py:1918-1927`）；**G9/V-b** 空格平移状态
  可泄漏为常开（焦点转入文本框/失焦丢 release，`widgets.py:150-159`）；
  **V-c** 拖拽中切 Board 提前 return 跳过新板视口恢复；**V-d** `_set_image`
  无条件清 `_scale_key` 使缩放缓存全失效（放大 V1 代价）；**V9（疑似）**
  模板模式 `zoom_to_card` 用 `geometry()/zoom` 逆推 1x 矩形，option-A 路径
  padding 不缩放 → 非 100% 下定位偏差；**V10（疑似，部分既有）** pane 级
  `_hooked_ids` 按 `id()` 记账有 id 复用洞。

## 4. Follow-up 登记（不阻塞收口的欠账）

pinch 通道补合成 QNativeGestureEvent 测试 · digest characterization 补真两进程
+ 带 capture 的 fresh/stale 钉死 · 模板语义 characterization · Delete 键组删除
UI 级测试 · zoom-to-card 动画本体驱动测试 · spec §4.6 passthrough 表述改为
forward-only 事实 · plan「P3-2 暂停」条文对账 · p3-verification 的 A07/A08/A12
标签改为 UNVERIFIED/PARTIAL · 首次进入提示是否升级弹窗（产品决策）。

## 5. 审过无问题的区域（不必重复怀疑）

QDrag 历史崩溃族护栏原样保留且 `_drag_kind` 豁免完整 · 手势状态机不持 widget
引用（Qt-free ref/rect，销毁最多 no-op）· undo 每操作恰一条、失配清双栈 ·
组移动 union 判定是 plan 明文记录的有意简化（state 层按逐成员兜底）· 意图环
计时器生命周期健全 · 手势坐标 board 系滚动不敏感（破口仅 G2）· 点击/双击/
右键与拖拽的事件次序正确 · 棘轮零新增（lambda/写穿/QSS）· 零计算合同成立
（FOCUS 走 `grab_presentation_pixmap` 纯渲染，无分析入口）· digest 纯净 ·
viewport 合法化双实现一致 · zoom 锚点数学无累计误差 · LOD 真滞回 · Fast 档
pixmap key 含 zoom 尺寸不会显示错档 · 托盘补位数学正确 · 预算驱逐主闭环成立。

## 6. 建议收口顺序（按性价比）

1. **G1 + V2**（手势泄漏误提交 + 视口互串——都是用户可撞上的状态污染）。
2. **V1 + V5 + V4**（FOCUS 收敛 + 收缩通知 + stale 画布——一组连环的内存/
   风暴问题，建议一批修，修完跑 24 卡真机看帧率）。
3. **V3**（模板缩小失效——zoom 在两大模板上名存实亡）。
4. **G2/G3/G5/G6/G7**（手势边角：缩放中拖拽、托盘回归、Esc、越界语义、静默失败）。
5. 低危批量（V6/V7/V8/G4/G8/G9 等）。
6. 文档对账（§4 的 verify/plan/spec 标签修正）+ **仪器化真机验收**（跑
   `scripts/probe_ultraview_zoom_spike.py` 把 `max_frame_ms`/`pinch_events`
   填回 spike 文档，P3-2 才能改标完成）。
