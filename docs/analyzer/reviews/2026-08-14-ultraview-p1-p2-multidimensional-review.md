# UltraView P1+P2 多维度详审（提交 c4b1de85）

日期：2026-08-14 · 审查者：Claude（四路并行子代理：P1 符合度 / P2 符合度 / 正确性猎虫 / 测试护栏实测）
对象：`c4b1de85 feat(ultraview): implement scalable boards and grid`（26 文件 +4069/−111）
+ 规格 `31dbd98f`（P1 spec 667 行 / P2 spec 625 行 / 两份 plan）+ `docs/analyzer/reviews/2026-08-14-ultraview-p2b-inspection-capability-audit.md`。

## 0. 总判定

**P1、P2 均不可判收口。** 状态层与安全层的实现质量是一等的（见 §7），
UltraView 自身 248 条测试全绿，P0 契约未被改坏；但存在 1 条崩溃级 + 1 条数据
丢失级 + 3 条 P0 静默失效缺陷，P1 的三根承重柱（sidecar 生命周期、惰性加载、
动态导出几何）缺失，验收证据体系（verification 文档、性能 JSON、真机记录、
help 同步）整体缺席，且 P2-A 有 6 项欠账未在任何文档承认。

建议判定书：
- **P1 Core：PARTIAL** — blocked on A08/A11/A12/A15/A17-A20。
- **P2-A Core：收口**；**P2-A Remainder：明确欠账，需补文档**。
- **P2-B：NO-GO 已文档化**（audit 诚实），但 §11 guide 裁剪需补记。

## 1. 崩溃级 / 数据丢失级（先于一切修复）

### S1 🔴 拖放落点在 `QDrag.exec_()` 嵌套事件循环内销毁拖拽源（崩溃）
三条已实测复现的路径：`LibraryRowWidget`（`widgets.py:846-853` 起拖 →
drop 后 `_after_board_mutation` → `_refresh_library` → `_rebuild`
`widgets.py:1015-1022` 无条件删全部行）；`UltraViewCard`/`FreeGridCard`
（`widgets.py:1403-1410`/`1695-1704` → 拖到未放置区后 `_discard`/
`set_free_grid` 销毁）；`TrayItem`（`widgets.py:2297-2304` → `set_refs`
`widgets.py:2395-2400`）。后果：`finally` 里 `drag_finished.emit()` 抛
`RuntimeError` 逃出重写虚函数 → PyQt5 `qFatal()` abort；且 `QDrag(self)`
以被销毁 widget 为父 → use-after-free。与
`2026-08-11-channel-tree-paint-segfault-triage.md` §4.2/4.3 僵尸 wrapper 同族。
**修法**：drop handler 的 intent 发射 `QTimer.singleShot(0, ...)` 推迟；
`finally` emit 加 `sip.isdeleted` 护栏；QDrag 父对象改稳定宿主；或重建函数在
`_drag_kind is not None` 时跳过。

### S2 🔴 自由网格 Board 存盘丢 `layout_id`/`primary_ratio`（数据丢失）
`_board_payload` free_grid 分支不写这两键（`ultraview_state.py:833-848`），
读回回落 `hero_left_4`/0.67（`:889-894`）；关闭自由网格用的正是
`board.layout_id`（`ultraview_coordinator.py:1067`）。实测：grid_3x3 + 9 卡
→ 存盘重开 → 关自由网格 = **hero_left_4，4 placed + 5 甩进托盘**（内存内往返
则正确回 9 placed）。现有测试无 free-grid payload 往返断言。

## 2. P0 静默失效三连（P2 招牌交互无声失败）

- **D1 尺寸预设碰撞 = 无声 no-op**：`ultraview_coordinator.py:1095-1104` 把
  `grid_collision` warning 直接丢弃——不刷新、不 toast、不记 history。有其他
  卡的板上选「横幅 12×4」几乎必然没反应。拖拽路径的碰撞反而有提示
  （`widgets.py:1857`），两路不一致。
- **D2/S6 靠近右/下边缘拖放静默漂移或失败**：`widgets.py:1895-1912` 的
  `_grid_at` 只夹 origin（column≤11 硬编码，`:1848-1849`），不保证
  `column+span≤12`；widget 侧用未夹取矩形过 `rect_is_available`，coordinator
  侧 `_legal_grid_rect` 夹取后再判——结果或落点远漂、或撞车被 D1 同款写法吞掉。
- **D3 任何增删卡片后 undo 栈永久死亡**：`ultraview_coordinator.py:1132-1154`
  `_apply_grid_snapshot` 要求 ref 集合完全相等，失败把条目**压回栈**——此后每次
  undo 在同一条目上重复失败，全部变 no-op。应失配即清栈并让 UI 反映。

## 3. P1 承重柱缺口

- **A08/S3 sidecar 世代无限累积**：`preview_sidecar.py:254-362` 每次保存写新
  uuid 的 `.uvpz`，无任何清理（单包上限 64 MB，存 N 次留 N 份）；零预览项目也
  建目录写包；未来 schema 项目经 `opaque_payload` 原样返回时丢刚写的
  descriptor（`ultraview_state.py:1007-1008`）→ 新包永久成孤儿。
  修法：`os.replace` 后 unlink 目录内其余 `*.uvpz`；空 store 跳过写包。
- **A11 惰性加载缺失**：`ultraview_coordinator.py:641-650` 打开项目同步解码
  **全部** Board 的 PNG，spec §7.5 明令禁止；无队列、无 generation token、
  无取消。
- **A12 动态 compositor 未做**：`compositor.py:66-68` `output_size()` 仍固定
  1600×900，只有 P2 自由网格拿到动态尺寸；12 图模板导出无 template-aware
  几何（plan Task 7 GREEN #1）。另 D7：自由网格短板导出带最多 900px 尾白。
- **A15 多 Board 集成层零测试**：`test_ultraview_mode_integration.py` /
  `job_isolation` / `lifecycle_subprocess` / `test_project_io.py` 中无一处出现
  workspace/create_board/select_board；零计算链未加入 Board 增删改排、模板切换、
  move/resize/preset/undo/organize。
- **S4 预算驱逐回收不了内存**：`preview_store.py:364-369` 只置
  `record.image=None`，卡片 `_raw_image`（`widgets.py:1318`）仍持强引用继续显
  示，`stats().raw_pixels` 低报；residency 的 `target_size`/FOCUS tier 在生产
  路径是死参数（`coordinator:569-600` 从不传），「按显示尺寸降采样、焦点保高分」
  未兑现。
- **S5 概览隐藏时仍每次投影全量重绘**：`page.py:856`/`:943` 无条件
  `set_board`→`_compose()`；模板态 1600×900（5.8 MB/次），自由网格有低行卡片时
  `grid_metrics` 出 1600×4720 → **单次 30.2 MB** 分配；一次 `refresh_page`
  （12 卡）触发 12 次整板合成。应脏标记 + 显示时惰性合成。且概览是
  `widgets.py:2165-2203` 另写的第二套渲染器，未复用 `compose_board`，必然漂移。

## 4. 中低危清单（猎虫）

- S7 演示模式概览被后台刷新关掉（`page.py:454` `set_board` 先
  `hide_overview()`，任意 `views_changed`/闲时快照触发）。
- Ctrl+Z 页面级 QShortcut 盖过 Board 名称框/搜索框的文本撤销（`page.py:248-253`）。
- `page._previews/_statuses/_ref_exists` 只增不减（`page.py:114-116,390`）。
- 20 Board 上限只挡 `+` 按钮（`page.py:303`），复制路径与 payload 恢复无限且无
  warning；托盘无硬上限（实测 5000 条零 warning）。
- `_watch_canvas_destroyed` 的 `destroyed` 连接从不断开，重复加载工程 N 次给同
  一画布连 N 次 partial（`ultraview_coordinator.py:2022-2027` vs `:632/:1466`）。
- `_on_idle_capture_timeout` sheet 不可见时提前 return 未重启定时器 →
  `_idle_pending` 滞留（`:2360-2387`）。
- `BoardSwitcher._on_tab_moved` 在 `moveTab` 信号内同步重建整条 tab bar
  （`widgets.py:484-489`），建议 singleShot 交接。
- 扩容布局会自动把托盘 ref 填回空槽（`ultraview_state.py:561-578`），与 plan
  Task 2 RED#3「4→12 不自动回填」相反，两方向均无测试。
- 最低可读尺寸口径错位：`MIN_CARD_CONTENT_SIZE=(300,180)` 被当整卡下限（含
  34+24 chrome，真实绘图区 300×122），且 1280×800 恰好不触发滚动
  （`layouts.py:24,48-74`）。
- 死代码：`free_grid.py` 的 `organized_placements`（被测试测但产品用的是
  `ultraview_state.organize_free_grid`，后者反而无幂等测试）、
  `GridGeometryCommand`、`pixels_to_grid_delta`（import 后未用）。
- 硬编码 `11`/`47` 应为 `GRID_COLUMNS-1`/`MAX_GRID_ROWS-1`（`widgets.py:1848-1849`）。
- sidecar：fsync 打在只读句柄且未 fsync 目录、恢复无逐图回读校验之外的问题
  （低危，见 P1 报告 Low 段）。

## 5. 规格与文档诚实性

诚实的部分：p2b audit（42 行）对 P2-B live inspection 判 NO-GO 且理由充分；
`E01 条件 renderer` 正确 DEFERRED。

**未文档化的裁剪/欠账（需补记）**：
1. **P2 spec §11 兼容轴 guide 整章被静默丢弃**（audit 未提；sidecar
   `SIDECAR_FORMAT=1` 也没有 §11.3 的 `plot_content_rect_norm`/`x_transform`）。
2. **P2-A 六项欠账无记录**：ghost/resize handle（A04，无 drag pixmap/overlay/
   handle，resize 只有 Alt+Shift）、同尺寸 swap（A05）、分页 PNG 与像素上限
   （A15，最坏 24 卡 2× = 3200×9712 ≈ 124 MB ARGB 无前置检查）、24 图
   benchmark（A17）、零计算探针扩展（A16）、帮助页（A18）。
3. **GridMetrics 合同未回写 spec §4.2/§8.1**（plan「评审修订 1」硬前置）：
   `GRID_MIN_COLUMN_WIDTH=96`/`GRID_ROW_HEIGHT=88` 只在 `free_grid.py:26-30`
   注释里；property tests 未写。
4. **schema 写 3 不写 2**，P1 spec §8.1 未同步；P1 plan Task 1 GREEN#6 的旧读者
   降级决策未写进 spec。
5. **P1/P2 verification 文档均不存在**（plan Task 9 交付物），A17/A19/A20 零证
   据；「另行记录」指向的文档不存在。
6. 提交纪律：plan §2 要求 10 个独立提交，实际 P1+P2 合并为 1 个 4069 行提交。

## 6. 测试与护栏实测（两次独立复跑数字一致）

| 分组 | 结果 |
|---|---|
| UltraView 14 文件 | **248 passed / 0 failed**（40.7s） |
| `tests/ui` 全目录 | **4243 passed / 2 failed**（10 分 22 秒；2 红即 lambda 棘轮） |
| 状态所有权/import 分层/QSS border/曲面分层/QSettings 隔离 | 31 passed 全绿 |
| 受牵连面（smoke/chart_card/hints/quickref/icons） | 207 passed 全绿 |

已知红现状：
- **lambda 棘轮仍红但换了主**：`ultraview/widgets.py` 已清到 0（Codex 收了）；
  超额 1 条现在在 `chart_stack/stack.py`（12→13），出处是
  `5c4d1f62 fix(fft): refine cursor readout panel` 的
  `canvas.frequency_cursor_rows.connect(lambda rows, c=canvas: ...)` ——
  **与 UltraView 无关，但需要修（bound method/partial），不是放宽白名单**。
- **裸 QLineEdit 搜索框仍红**：`ultraview/widgets.py:933-935`（P0 遗留
  `8d6d80f1`，本批未收口），应换 `SearchField`。

测试质量：两个新文件断言实质性（非冒烟壳）。空白：**恶意 ZIP 防护零测试**
（`MAX_SIDECAR_ENTRIES=512`/压缩比 100/超边长/QImageReader 预检全无用例，
plan Task 5 RED#4/#6 点名）；**自由网格修饰键解析零真实键鼠事件**（现有测试直
接 emit 信号绕过 `mousePressEvent`/`keyPressEvent`，D2 正是这样漏网）；
digest 跨进程 characterization 缺失且 P0 断言被放宽为
`in {"fresh","stale","missing"}`（`test_ultraview_project_session.py:122`，
plan Task 6 RED#10 禁止的写法）。

## 7. 审过无问题的区域（不必重复怀疑）

sidecar 安全校验（穿越/symlink/zip 成员/压缩比/manifest sha256/逐图复核/原子
写/单张坏图隔离——实现齐全，只是部分无测试）；`free_grid.py` 几何数学（对称取
整、半开区间重叠、clamp 边界、除零护栏）；`layouts.py` 排版记账；schema 合法
化（未知值全部带 warning 非静默）；PreviewStore 驻留合并与线程断言；协调器
warning 约定一致；**只读契约成立**（无从总览反写分析/时域状态的路径）；信号回
环防护；定时器生命周期（weakref + shutdown 清理）；P0 契约完好；项目 JSON 原
子写（`3ea465de`）。

## 8. 建议收口顺序（按性价比）

1. **S1 拖拽销毁时序**（崩溃）+ **S2 free_grid 存盘丢 layout_id**（数据丢失）。
2. **D1/D2/D3 静默失效三连**（含 warning→toast 接线、`_grid_at` 先夹取、undo
   失配清栈）。
3. **sidecar 生命周期闭环**：旧世代清理 + 零预览不写包 + opaque_payload 保留
   descriptor；随后 lazy load 队列 + generation token。
4. **S4/S5 内存与合成**：驱逐联动页面丢 `_raw_image`；概览脏标记惰性合成并复用
   `compose_board`；template-aware `output_size()` + 尾白裁剪。
5. **集成测试补齐**：多 Board 切换零计算链、free-grid 存盘往返、真实键鼠修饰键
   事件、恶意 ZIP 防护、20 Board/托盘上限 warning。
6. **文档补记**：audit 增补 P2-A 六项欠账与 §11 guide 裁剪；GridMetrics 合同回
   写 spec；schema 3 同步；补 P1/P2 verification 文档（真机 Cocoa + 性能 JSON）。
7. **发现性面**：help 页（至今无一个 "Board" 字样）、hints/quickref 补
   Alt+Shift 缩放、Cmd+Z 撤销、尺寸预设、整理布局、minimap、Board 管理手势、
   12 列/24 卡上限；裸搜索框换 SearchField；`stack.py` lambda 收口。

## 9. 收口核对（`60516a72`，2026-08-14 复审）

逐条对照本文件 §1-§6 复核 Cursor 的收口提交（代码 diff + HEAD 实测 + 测试复跑）。

**实质完成**：S1（`_run_ultraview_drag` 挂 `window()` 稳定宿主 + `sip.isdeleted`
护栏，页面侧 `_drag_kind` 期间转脏标记统一 flush，并落 lesson）；S2（payload 无条
件写 `layout_id`/`primary_ratio` + 端到端往返测试）；D1（两路统一
`_commit_grid_change` → toast）；D2/S6（`_grid_at` 带 span 经 `clamp_rect`，
硬编码 11/47 消失）；D3（失配清栈 + toast）；A08/S3（旧世代清理、空 store 不写包、
descriptor 覆写进 opaque_payload 防孤儿）；A11（打开只验头收字节，0 间隔 timer
每 tick 解码 2 张，带代际 token 与活动 Board 优先——注意：推迟的是解码不是 I/O，
整包字节仍一次读入，受 64MB 包上限约束，可接受）；A12/D7（`output_size(scale,
layout_id)` 模板地板 + `export_grid_metrics` 裁尾白 + `composed_slot_rects`
导出/概览共用 + `_guard_export_size` 前置拒绝）；S5（脏标记 + showEvent 惰性合成，
第二套渲染器消灭，顺带修掉演示模式概览被关）；S4 大半（`images_dropped` 信号联动
页面清 `_raw_image`）。中低危：20 Board 上限（state 层 + loader warning）、
membership 硬上限 200、Ctrl+Z 文本框守卫、`stack.py` lambda、裸搜索框换
SearchField 全部收口。文档欠账大体补齐（audit 补记六项欠账与 §11 裁剪、
GridMetrics 合同回写 spec、schema 3 同步、P1/P2 verification 文档诚实标注
offscreen/UNVERIFIED）。测试实测：UltraView 12 文件组 **229 passed / 0
failed**，原两条已知红（lambda 棘轮、搜索框）全部转绿。未发现新引入的崩溃/
正确性级问题。

**仍遗留（低危区，下批收口）**：
1. residency `target_size`/FOCUS 分层在生产路径仍未接（S4 的另一半，
   「按显示尺寸降采样、焦点保高分」未兑现）——注意它正是画布交互分析
   （`2026-08-14-ultraview-canvas-interaction-analysis.md` §5 Tier 1）里
   zoom-to-card 需要的钩子，建议留到 P3 一起接。
2. digest 跨进程 characterization 仍是放宽写法 `in {"fresh","stale","missing"}`
   （`test_ultraview_project_session.py:125`，plan Task 6 RED#10 禁止形态）。
3. 真实鼠标拖放路径仍无回归测试（S1 修复靠 sip 护栏与脏标记，但测试仍以信号
   emit 为主；真实 `keyPressEvent` 只补了 Alt 方向键）。
4. `_watch_canvas_destroyed` 重复连接、`page._previews/_statuses/_ref_exists`
   会话内只增不减、`BoardSwitcher._on_tab_moved` 同步重建——均未动。
5. 扩容自动回填仍在（`set_layout` 把托盘 refs zip 进新槽，与 plan Task 2 RED#3
   矛盾且无文档承认）——要么改行为要么补文档，二选一。
6. 超上限自由网格导出是硬拒绝（ComposeError）而非分页——已作为 A15 欠账文档化，
   用户侧表现为导出失败，提示文案需确认可理解。

**判定更新**：§0 的「P1 Core：PARTIAL」升级为 **P1 Core：实质收口（真机
Cocoa/两进程/frozen 验证仍缺，合入前必须补）**；P2-A 维持收口 + 欠账已文档化；
P2-B 维持 NO-GO 已文档化。
