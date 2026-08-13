# UltraView P1 可扩展多 Board 工作区实施计划

- 日期：2026-08-13
- 状态：`P1 Core IMPLEMENTED 2026-08-14；当前 sidecar 为安全同步恢复，lazy load 与前景/Cocoa/全量平台验收另行记录`
- 对应规格：
  `docs/analyzer/specs/2026-08-13-ultraview-p1-scalable-board-workspace-spec.md`
- 建议分支：`feat/ultraview-p1-scalable-workspace`
- 分析起始基线：`main@9c91debf`；成稿时并行实现已推进到 `main@5e36b27a`。真正实施时
  必须改成届时已通过 P0 gate 的 HEAD

## Claude 评审结论（2026-08-13）

可行性判定：**结构可行，按下列修订执行**。规格对现状的关键判断已逐项核实为准确：
`ULTRAVIEW_SCHEMA=1` 单 Board payload、`PreviewStore.set_pinned_refs()` 单一 pin 集合、
`MAX_PREVIEW_PIXELS=16M` / `MAX_PREVIEW_RAW_EDGE=1600`、compositor 固定 1600×900
（`layouts.BASE_BOARD_SIZE`）、`save_project_to_json()` 为非原子 `write_text()`
（`_write_project_document` seam 在 `_project_io_mixin.py:400`）、计划引用的测试文件
全部存在、60 unique refs 基准与 `MAX_VIEWS=12 × 5` 区一致。

评审并入的修订（正文各 Task 已同步，执行以正文为准）：

1. **P0 gate 改锚（Task 0，最重要）**：spec §1.2 列的六条大多已在
   `5e36b27a`/`c63b633e` 关闭；真正的动工门槛是同日更晚的逻辑接线审查
   `docs/analyzer/specs/2026-08-13-ultraview-logic-wiring-review-spec.md`
   （UVL-A01…A21，配套 fixes plan）加 view-rail 入口 D1 真机验收。其中
   B1/B5（hover 线与可见性/绑定事实混进 digest）、B2/B4（每源信号全板重投影）、
   E1（页面影子缓存跨项目滞留）是 P1 sidecar 语义与多 Board 投影直接踩在上面的
   地基，未绿则 P1 的 fresh/stale 持久化和投影扩展都建立在错误行为之上。
2. **nested schema 前向兼容（Task 1）**：现 `normalize_board_payload` 对未知 schema
   回退默认 Board，重存即销毁新版数据——P2 的 schema 3 会被 P1 读者毁掉。必须定义
   确定性 passthrough 策略并测试。
3. **digest 重启稳定性（Task 6）**：sidecar「captured digest 相同才 fresh」要求
   digest 跨进程可比；需 characterization 测试钉住真实行为，不稳定则把「重开必
   stale」记录为已知限制而不是静默通过。
4. **投影合并（Task 3）**：多 Board 使 B2 类全板重投影成本按 membership 放大，
   需 no-op 短路与每 tick 合并的计数探针。
5. **托盘敌意上限（Task 1）**：tray 无上限，恶意 payload 可物化数千 TrayItem，
   legalize 增加 membership 硬上限。
6. **基线补全（Task 0）**：聚焦基线补 `test_ultraview_entry.py` 与
   `test_ultraview_probes.py`；P0 验收报告产自 Windows offscreen（主体两进程在 BLF
   对话框用例段崩溃、Cocoa/frozen UNVERIFIED），本机 macOS 需重建自己的基线读数。

## 0. 目标、执行边界和 GO 条件

本计划交付 P1 Core：多 Board、9/12 图大画布、预览 sidecar、共享驻留、动态整板导出和
完整零计算/生命周期/性能证据。缓存结果独立 renderer 只在规格 §14 的证据门槛成立后以
P1-E 执行，不能为了“完成 P1”默认启动。

执行者开始前必须：

1. 重新读取 `AGENTS.md`、当前 `git status`、P0 verification 和本 spec 全文；
2. 确认 P0 gate：spec §1.2 六条之外，逻辑接线审查 UVL-A01…A21
   （`2026-08-13-ultraview-logic-wiring-review-spec.md` + fixes plan）与 view-rail
   入口 D1 真机验收均已关闭；
3. 记录 active branch/HEAD/origin、并行 dirty paths 和 baseline tests；
4. 使用独立 feature branch；不得在正在变化的 P0/UI worktree 上直接混改；
5. 不修改历史 P0 spec 来伪造已完成状态；P1 使用新 schema/新测试/新 verification；
6. 每个行为变化先写聚焦 RED，再做最小 owner 级实现。

若 P0 gate 未满足，停止并报告 `BLOCKED BY P0`，不进入 Task 1。

## 1. 任务顺序与依赖图

```text
Task 0 P0/基线门禁
  ↓
Task 1 Workspace Qt-free 状态与 schema migration
  ↓
Task 2 9/12 模板与逻辑画布几何
  ↓
Task 3 BoardSwitcher 与多 Board 页面投影
  ↓
Task 4 共享 PreviewStore residency
  ↓
Task 5 sidecar codec / security / atomic storage
  ↓
Task 6 project save/open / Save As / lazy load
  ↓
Task 7 dynamic compositor / overview / export
  ↓
Task 8 lifecycle / zero-compute / performance hardening
  ↓
Task 9 help / visual / full-suite / foreground acceptance

Task E（条件）cache result → preview renderer
  仅在 Core 使用数据达到门槛后另行启动
```

Task 1～3 不依赖 sidecar，可先形成可交互多 Board/12 图骨架；Task 5 必须在接入项目 IO
前独立证明 hostile input 和原子写语义。

## Task 0 — 冻结 P0 gate、基线和 scope

**读取**

- `docs/analyzer/verify/2026-08-13-ultraview-p0-verification.md`
- P0 spec/completion spec/View-rail spec
- 当前 UltraView source/tests
- `git status --short --branch`

**步骤**

1. 确认 P0 verification 已映射空图有效性、单工具窗生命周期、main Inspector 不受影响、
   manager live sync、rebind、LRU 重抓、zero-compute、两进程 suite 和 Cocoa。同时确认
   逻辑接线修复计划（UVL-A01…A21）与 view-rail D1 真机验收已关闭——其中 B1/B5
   （digest 语义）、B2/B4（idle 热路径）、E1（页面影子缓存）任一未绿则本计划为
   `BLOCKED BY P0`，因为 Task 3/4/6 的设计直接建立在修复后的行为上。
2. 运行当前 UltraView focused baseline，并记录真实 pass/fail/exit code，不复制历史计数。
   注意 P0 验收报告产自 Windows offscreen（主体两进程异常退出、Cocoa/frozen
   UNVERIFIED）；本机 macOS 必须建立自己的读数，不得引用该报告的平台结论。
3. 检查 `main` 与 origin；创建 P1 branch。列出所有 pre-existing dirty/untracked paths，
   执行期间只 stage P1-owned files。
4. 为 `tests/ui` 使用隔离 QSettings/temp 路径；不要读取开发者真实 settings。
5. 运行 lessons selector/status；若 P0 仍有 blocker，写 review note 并停止。

**建议命令**

```bash
git status --short --branch
git log -5 --oneline --decorate

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q \
  tests/ui/test_ultraview_state.py \
  tests/ui/test_ultraview_layouts.py \
  tests/ui/test_ultraview_preview_store.py \
  tests/ui/test_ultraview_page.py \
  tests/ui/test_ultraview_capture.py \
  tests/ui/test_ultraview_export.py \
  tests/ui/test_ultraview_project_session.py \
  tests/ui/test_ultraview_mode_integration.py \
  tests/ui/test_ultraview_lifecycle_subprocess.py \
  tests/ui/test_ultraview_job_isolation.py \
  tests/ui/test_ultraview_probes.py \
  tests/ui/test_ultraview_entry.py
```

**Exit gate**：P0 prerequisite 全部有当前证据；baseline 正常结束；P1 scope 与并行改动隔离。

**建议提交**：无。

## Task 1 — Workspace Qt-free 状态与 nested schema 1→2

**修改**

- `mf4_analyzer/ui/ultraview_state.py`
- `tests/ui/test_ultraview_state.py`
- `tests/test_project_io.py`

**可新增**

- `tests/ui/test_ultraview_workspace_state.py`

**RED**

1. 新建 `UltraViewWorkspaceState(active_board_id, boards)`；默认恰好一张默认 Board。
2. 测试新建、复制、改名、删除、重排、选择：
   - board_id 唯一且稳定；
   - 名称允许重复；
   - 至少保留一 Board；
   - duplicate 复制 refs/layout/tray/flags，不复制 runtime/pixels；
   - active ID 始终合法。
3. 同 ref 可出现在不同 Board，同 Board 仍不重复。
4. schema 1 单 `board` 迁移 schema 2 `workspace.boards[]`，所有字段/合法 ref 保留。
5. 测试重复 ID、非法 active ID、空 boards、未知 layout、超过 20 Boards、重复 refs，
   warning 与 legalize 结果符合 spec。
6. loader 接受 schema 1/2；writer 只写 schema 2；outer project schema 继续为 2。
7. fuzz/参数化 payload：输入坏类型、NaN ratio、超长 name、重复 slot 不崩溃、不静默丢 ref。
8. **未知（更新）nested schema passthrough**：schema > 2 的 payload 原样保留为不透明
   blob；运行时用默认 Workspace，但用户未改动 UltraView 状态时保存必须原样写回，
   不得用默认 Workspace 覆盖；用户显式改动后写 schema 2 并 warning。禁止延续现状的
   「未知 schema → 默认 Board → 重存销毁」（P2 schema 3 依赖这条活路）。
9. **membership 硬上限**：单 Board placed+tray 总数设硬上限（建议 200）并 warning；
   敌意 payload 不得物化出无限托盘条目。

**GREEN**

1. 保留 `UltraViewBoardState` 为 Board owner；新增 Workspace owner，不把像素/Qt 放进 DTO。
2. 将旧 `board_to_payload/normalize_board_payload` 包装为明确的 workspace codec；只在必要时
   保留 compatibility alias，标注 schema 语义。
3. 提供纯操作函数：`create_board/duplicate_board/rename_board/delete_board/reorder_board/
   set_active_board`；不要在 Page/Coordinator 手写 list mutations。
4. UI 创建上限 20 在创建操作中执行；normalize 读取全部合法 Boards 并 warning。
5. 所有 warning 使用稳定 code，测试不要只匹配整段中文。
6. 记录 schema 1 旧读者的降级决策：旧读者读 schema 2 会回退默认 Board、重存丢
   Boards。若 owner 要零损失，另行实现 schema:1 `board` 镜像双写（active Board 投影，
   老字段 + 新 `workspace` 并存一个过渡版本）；否则在 spec §8 显式记录接受该损失
   （当前 UltraView 尚未随正式版发布，损失窗口极小）。

**验证**

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q \
  tests/ui/test_ultraview_state.py \
  tests/ui/test_ultraview_workspace_state.py \
  tests/test_project_io.py
```

**Exit gate**：UV-P1-A01/A02/A03；状态模块保持 Qt-free/import-safe。

**建议提交**：`feat(ui): add UltraView multi-board workspace state`

## Task 2 — 9/12 图模板与可滚动逻辑几何

**修改**

- `mf4_analyzer/ui/ultraview_state.py`
- `mf4_analyzer/ui/chart_stack/ultraview/layouts.py`
- `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`
- `tests/ui/test_ultraview_layouts.py`
- `tests/ui/test_ultraview_page.py`

**RED**

1. 为 `grid_3x3`、`grid_4x3` 冻结 row-major slot IDs 和 capacity 9/12。
2. 320×200、800×560、1280×800、1600×900 viewport 下：
   - slot rect 唯一、非重叠、在 logical Board 内；
   - 9/12 图不足时 logical Board 大于 viewport并出现正确 scroll range；
   - 2/4/6 在有空间时仍填满 viewport；
   - card chrome 不因 Board scale 变成不可读高度。
3. 模板 12→4 时前四张按稳定顺序保留，其他进当前 Board tray；4→12 不自动将 tray
   填回空槽，除非 spec 明确的用户动作调用。
4. `slot_id_at()` 在滚动/逻辑坐标下命中正确；drop 不因 viewport offset 放错槽。
5. wheel/trackpad 只滚 Board，不进入 source canvas；PageUp/Home/End 和 focus traversal 可测。
6. relayout instrumentation：同一 resize burst 最终只做一次昂贵图片 smooth rescale。

**GREEN**

1. 给纯 geometry 增加 `logical_board_size()`，输入 template/viewport/card metrics/gutter，输出
   stable logical size；不要在 widget 与 compositor 各算一套。
2. 将 BoardGrid 包装在透明 `QScrollArea`，BoardGrid 使用 logical fixed/minimum size；不让
   scroll viewport 绘制白色矩形覆盖圆角 surface。
3. 拖放坐标显式映射到 BoardGrid local；不要依赖未滚动时巧合相同的 `event.pos()`。
4. 拖动/resize 过程使用 FastTransformation 或现有缓存；quiet settle 后再 SmoothTransformation。
5. 最低卡片尺寸从字体 metrics/chrome/image target 推导；实施时用真实截图修订 spec 草案值。

**视觉探针**

- 1280×800：9 图和 12 图阅读模式、滚动到四角；
- 1600×900：同样场景；
- DPR 1/2：标题、来源、状态带、空槽和 scrollbar；
- 自动生成 contact sheet 和 geometry JSON。

**Exit gate**：UV-P1-A04/A05；无固定窗口断点掩盖 minimum geometry。

**建议提交**：`feat(ui): add scrollable nine and twelve card UltraView layouts`

## Task 3 — BoardSwitcher 与多 Board 页面投影

**新增**

- `mf4_analyzer/ui/chart_stack/ultraview/workspace.py`
- `tests/ui/test_ultraview_workspace_page.py`

**修改**

- `mf4_analyzer/ui/chart_stack/ultraview/page.py`
- `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`
- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- `tests/ui/test_ultraview_page.py`
- `tests/ui/test_ultraview_mode_integration.py`

**RED**

1. BoardSwitcher 有 current-visible、overflow、tooltip、new/menu；20 Board 的窄宽场景不裁切
   当前 tab，行高不随数量增长。
2. 五个 typed intents：create/duplicate/rename/delete/reorder/select；Page 不直接改 workspace。
3. 切换 Board：
   - 关闭 focus/replacement/presentation/overview；
   - current Board 投影、toolbar layout/name/flags、tray、selection 更新；
   - library on-board 标识只针对 active Board；
   - 不抓图、不解码、不计算。
4. 删除非空 Board确认；取消零变化；删除 inactive/active；最后一张只能 clear。
5. duplicate Board 后像素 records/image object identity 不增加。
6. Ctrl+Tab/Shift+Ctrl+Tab、前移/后移、键盘新建/重命名路径可用。
7. Coordinator 只连接一次五 manager signals，与 Board 数无关；reset/shutdown 对称。
8. 投影合并计数探针：同一 event-loop tick 内多次 workspace/chrome/preview 变化只
   触发一次全板级重投影；`set_preview/set_ref_status` 值未变时 no-op 短路。多 Board
   下沿用并扩展接线修复 UVL-A08 的探针量级，不得回归。

**GREEN**

1. `workspace.py` 只拥有 presentation controls/typed intents；不 import MainWindow。
2. Coordinator 成为 Workspace owner，`board` compatibility property只返回 active Board；新代码
   必须使用明确 `workspace/active_board` API。
3. `set_workspace()` 一次完成 BoardSwitcher + active Board projection，避免逐控件 signal 回写。
4. Board switch 后调 PreviewStore residency adapter，但 Task 4 前可以是记录 refs 的窄接口。
5. 更新 live manager chrome/exists 时对 workspace 所有 membership 派生，不逐 Board重新连接。
6. Page 投影数据源（`_previews/_statuses/_ref_exists` 类影子缓存）必须随 coordinator
   的 reset/restore/shutdown 一起清空（依赖接线修复 E1 的 `clear_runtime_caches()`
   已落地）；多 Board 不得把页面影子缓存扩成按 Board 复制的第二份事实。

**Exit gate**：UV-P1-A02/A03/A14/A16；独立工具窗仍为单例且 MainWindow 分析面不受影响。

**建议提交**：`feat(ui): add UltraView board switching and management`

## Task 4 — 共享 PreviewStore residency 与内存测量

**修改**

- `mf4_analyzer/ui/chart_stack/ultraview/preview_store.py`
- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- `tests/ui/test_ultraview_preview_store.py`
- `tests/ui/test_ultraview_probes.py`

**可新增**

- `mf4_analyzer/ui/chart_stack/ultraview/residency.py`
- `tools/benchmark_ultraview_workspace.py`

**RED**

1. 20 Boards 引用同一 12 refs：store records/images 仍为 12，而不是 240。
2. active placed、viewport visible、focus/export、inactive/tray 各 residency tier 排序确定。
3. 切 active Board 后旧 Board high-res refs 可 eviction，新 Board refs 可从 sidecar later restore；
   metadata/digest 不丢。
4. 12 refs 总 raw pixels 超 budget 时按显示需求降采样；所有 active placed images 保持合法尺寸，
   不产生 1×1 或 None。
5. focus 临时高分辨率关闭后释放；export touch 不永久 pin。
6. 同 digest + image evicted 仍允许 publish/recapture；沿用 P0 regression。
7. GUI-thread guard、shutdown、allocation failure、stats 正确。

**GREEN**

1. 用 immutable `ResidencyRequest(ref, tier, target_size)` 驱动单一 Store，不在 Coordinator直接
   改 `_pinned`。
2. target size 来自当前 card/focus/export logical needs；不按 Board 数乘权重。
3. 保留全局 hard pixel budget；任何常量调整前先跑测量并更新 spec/test rationale。
4. Store 只拥有内存 image/metadata；不直接 IO sidecar。

**性能探针**

输出 JSON：6/9/12 cards × DPR1/2，20 Boards/60 unique refs，raw pixels、estimated bytes、
evictions、publish/scale/switch p50/p95/max、RSS peak。不得只报告单轮最好值。

**Exit gate**：UV-P1-A07/A17；相同 ref 不按 Board 复制像素。

**建议提交**：`perf(ui): share UltraView preview residency across boards`

## Task 5 — Sidecar codec、安全校验与原子存储

**新增**

- `mf4_analyzer/ui/chart_stack/ultraview/preview_sidecar.py`
- `tests/ui/test_ultraview_preview_sidecar.py`

**RED：纯 codec 与 hostile input**

1. manifest round-trip：format/generation/ref/digest/meta/size/bytes/hash。
2. canonical ref hash 与用户显示名、路径无关；同 ref 稳定，不同 section 不碰撞。
3. 写入临时 ZIP→校验→原子 rename；模拟 QImage encode、write、close、rename 失败：
   - 不留下 final 伪成功；
   - 不删除旧 generation；
   - 返回结构化 warning。
4. 拒绝：absolute path、`../`、symlink、duplicate entry、unknown format、manifest hash mismatch、
   PNG hash mismatch、单图边长/像素/字节超限、总解压预算超限、ZIP bomb ratio。
5. 一张坏图只拒绝该 ref；manifest 全局不可信则拒绝 generation。
6. reader 先使用 metadata/QImageReader size 预检，再 decode；测试 instrumentation 证明未提前
   解码所有 images。
7. 路径解析必须限制在项目 sibling sidecar directory；外部绝对路径不读取。

**GREEN**

1. Sidecar module 不 import MainWindow/analysis compute，不使用 pickle。
2. 将 manifest DTO 与 QImage encode/decode分层；纯 path/ZIP validation 可在无 QApplication
   子进程导入。
3. image encode/decode/publish 的 GUI-thread策略显式；如果 QImageReader 在 worker 读取，最终
   QImage 交付/Store mutation仍只在 GUI thread且有平台测试。最保守实现是在 GUI thread分批。
4. 全部 errors 带 code/ref/path context，日志不得包含敏感源路径之外的不必要数据。

**Exit gate**：UV-P1-A08/A09；安全输入边界和 crash-free退化有自动化证据。

**建议提交**：`feat(project): add validated UltraView preview sidecar storage`

## Task 6 — Project session、Save As 与 lazy load

**修改**

- `mf4_analyzer/ui/project_io.py`
- `mf4_analyzer/ui/main_window/_project_io_mixin.py`
- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- `tests/test_project_io.py`
- `tests/ui/test_ultraview_project_session.py`
- `tests/ui/test_ultraview_lifecycle_subprocess.py`

**RED**

1. Save schema 2 Workspace + sidecar relative generation/hash；QImage/runtime不进 JSON。
2. schema 1 project 打开→单 Board恢复→不自动打开工具窗→保存为 schema 2。
3. Save As 生成新 sidecar，不引用旧相对目录；取消/解析失败/写失败保持当前 Workspace。
4. sidecar write fail：项目语义成功保存且 payload不引用新失败 generation，toast/log明确。
5. project JSON replace fail：旧 project/旧 generation仍有效，新 generation可回收但不删除旧。
6. active Board lazy load按批次运行；切 Board重排优先级；切项目/shutdown取消晚到回调。
7. digest same→fresh，different/unavailable→stale，source missing→orphaned；live chrome优先。
8. 20 Boards × 12 refs恢复时相同 ref只读取一次 manifest/图片。
9. close/open/reopen MainWindow 子进程退出码0，无 dangling timer/QImage callback。
10. digest 重启稳定性 characterization：保存→重开→源未变（同项目、同数据、同 View
    参数），placed 卡片按 sidecar captured digest 应判 fresh。若接线修复后 digest 的
    构成（游标 ledger、pill 指纹、绑定事实）仍导致跨进程不可比，测试显式钉住
    「重开即 stale」并在 spec §7.5 / verification 记录为已知限制——两种结果都必须
    被测试固定，不允许既不 fresh 也没有解释。

**GREEN**

1. Coordinator暴露 `to_project_payload(project_path)` / `restore_project_state(payload, project_path)`
   等明确 API；不要把 path 写成新的 MainWindow散落状态。
2. 当前 `save_project_to_json()` 是直接 `Path.write_text()`；在保留其公共函数签名和
   `_write_project_document()` 测试 seam 的前提下，将实现升级为同目录唯一临时文件、
   flush/close、成功 `os.replace`，并测试encode/write/replace失败不损坏旧项目。
3. Project + sidecar orchestration严格按spec事务次序，只通过上述一个JSON write seam；不要
   在coordinator另造第二套项目writer。
4. `SidecarLoadQueue` 由 coordinator/holder拥有，token包含project/workspace generation+ref；
   callback执行前复核owner alive、generation、membership。
5. 恢复 Workspace语义立即可用；图片逐步出现，加载失败只改变状态反馈。

**Exit gate**：UV-P1-A01/A08/A10/A11；项目与sidecar相互引用不会出现半写成功。

**建议提交**：`feat(project): persist UltraView workspaces and previews`

## Task 7 — Dynamic compositor、overview 与完整 Board 导出

**修改**

- `mf4_analyzer/ui/chart_stack/ultraview/layouts.py`
- `mf4_analyzer/ui/chart_stack/ultraview/compositor.py`
- `mf4_analyzer/ui/chart_stack/ultraview/page.py`
- `mf4_analyzer/ui/chart_stack/ultraview/widgets.py`
- `mf4_analyzer/ui/main_window/ultraview_coordinator.py`
- `tests/ui/test_ultraview_export.py`
- `tests/ui/test_ultraview_page.py`
- `tests/ui/test_ultraview_layouts.py`

**RED**

1. 2/4/6 export baseline保持；9/12 canonical size遵守每卡可读区域、max edge/pixels。
2. 12 slots 1×/2× compositor：无重叠/越界、row-major、title/source/status/empty slot完整。
3. export只含 active Board complete logical surface，不含viewport/scrollbar/tabs/tray。
4. allocation/encode/clipboard/path失败为结构化错误；不存在partial/empty output。
5. overview复用 compositor QImage但不PNG encode；适应viewport且不upscale超过raw策略。
6. overview slot hit-test→退出overview→scroll card visible/focused；keyboard等价路径。
7. lazy loading中export不阻塞隐藏IO，按当前真实image/status输出。
8. 2× 12图内存峰值与GUI stall记录；超过defensive limit提前拒绝。

**GREEN**

1. 将 `output_size()` 改为 template-aware pure geometry；保留P0 helper compatibility只在明确
   consumer需要时。
2. `compose_board` 接收不可变Board projection/records/statuses，不读Page/MainWindow。
3. Overview widget只显示QImage+slot map，不创建12个第二套Card或live canvas。
4. 导出/overview访问推进LRU touch但用temporary residency scope，finally释放。

**Exit gate**：UV-P1-A06/A12/A13/A17。

**建议提交**：`feat(ui): compose and navigate complete large UltraView boards`

## Task 8 — 生命周期、零计算与性能加固

**修改**

- `tests/ui/test_ultraview_job_isolation.py`
- `tests/ui/test_ultraview_lifecycle_subprocess.py`
- `tests/ui/test_ultraview_probes.py`
- 仅按失败 owner 修改实现文件

**验证序列**

1. 实现 spec §13 全链，三层计算探针 + restore pending + source snapshots。
2. 反复 50 次：open/close sheet、create/switch/delete Board、open/replace project、shutdown；
   drain deferred deletes，子进程退出0。
3. 20 Boards/60 unique refs，连续100次switch；同步callback、first-image、complete-active记录
   p50/p95/max，无超500ms未解释stall。
4. 12图scroll/resize/overview/export三轮Cocoa benchmark，记录raw samples和环境。
5. 模拟sidecar慢读/坏图/项目快速切换，确保queue取消且无旧图串入新项目。
6. 运行state ownership/import boundaries/packaging gates；不扩大MainWindow state白名单。

**Exit gate**：UV-P1-A11/A15/A17/A18；任何abnormal exit/stall为UNVERIFIED/FAIL，不从前面
已完成测试推断通过。

**建议提交**：`test(ui): harden UltraView workspace isolation and lifecycle`

## Task 9 — 帮助、视觉、全套与平台验收

**修改**

- `mf4_analyzer/ui/hints.py`
- `mf4_analyzer/ui/quickref.py`
- UltraView help guide/index
- screenshot generator/tests
- 新 verification：
  `docs/analyzer/verify/2026-08-13-ultraview-p1-verification.md`

**步骤**

1. 同步多Board、9/12图、滚动、overview、sidecar退化和完整项目移交说明；不得写P2自由网格/
   live inspector。
2. 渲染矩阵：1280×800、1600×900、DPR1/2；1/6/9/12 cards；Board tabs overflow；fresh/
   stale/missing/orphaned；scroll四角；overview；sidecar loading/reject；presentation。
3. 自动geometry/pixel/contact-sheet检查后再做真实macOS Cocoa前景：trackpad scroll、drag/drop、
   Ctrl+Tab、clipboard、PNG 1×/2×、关闭/重开、Inspector/MainWindow不受影响。
4. 使用两个新进程运行全套：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q --ignore=tests/acquisition_ui

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest -q tests/acquisition_ui
```

5. Windows Full/Lite frozen未执行则写UNVERIFIED；不能用source packaging test替代。
6. `git diff --check`、lessons status、changed-file scope、verification ID mapping。

**Exit gate**：UV-P1-A16/A18/A19/A20；verification逐项映射A01～A20与E01状态。

**建议提交**：`docs(ui): close UltraView P1 acceptance`

## Task E — 条件性 cache result → preview renderer

**状态**：默认 `DEFERRED BY EVIDENCE GATE`。

只有产品 owner接受规格 §14 数据，或明确改为硬需求后，才先写独立补充spec/plan，至少包含：

1. 各section render-document DTO和cache lookup身份；
2. 明确禁止 `_render_analysis_view_from_cache()`、restore pending和任何`do_*`；
3. GUI-thread hidden host生命周期、一次一个render、取消与late-callback；
4. FFT/FFT-Time/FRF/Order owner-level正确性 + visible-path parity + real image diff；
5. cache miss/mixed split pane/orphaned/stale语义；
6. time-domain是否有render-ready model的单独GO/NO-GO；
7. 性能与内存预算。

不得在Task 5/6中顺手实现隐藏renderer。

## 2. 建议提交序列

1. `feat(ui): add UltraView multi-board workspace state`
2. `feat(ui): add scrollable nine and twelve card UltraView layouts`
3. `feat(ui): add UltraView board switching and management`
4. `perf(ui): share UltraView preview residency across boards`
5. `feat(project): add validated UltraView preview sidecar storage`
6. `feat(project): persist UltraView workspaces and previews`
7. `feat(ui): compose and navigate complete large UltraView boards`
8. `test(ui): harden UltraView workspace isolation and lifecycle`
9. `docs(ui): close UltraView P1 acceptance`

每次提交前只 stage 对应 owner files，运行 `git diff --cached --check` 和适当聚焦测试。若当前
worktree仍有用户/其他agent改动，使用新worktree或逐hunk stage，不得整目录add。

## 3. 最终 Done Checklist

- [ ] P0 prerequisites当前PASS；
- [ ] schema1→2 migration和multi-Board Qt-free tests PASS；
- [ ] 2/4/6/9/12 screen/export geometry PASS；
- [ ] multiple Boards共享preview identity，内存不按Board复制；
- [ ] sidecar atomic/security/Save As/failure degradation PASS；
- [ ] active lazy load与shutdown/项目切换取消PASS；
- [ ] overview和完整12图导出PASS；
- [ ] P1 full operation zero-compute PASS；
- [ ] lifecycle subprocess正常退出；
- [ ] performance JSON与三轮Cocoa raw samples已记录；
- [ ] hints/quickref/help与实际能力一致；
- [ ] main suite与acquisition_ui两进程正常结束；
- [ ] Cocoa foreground PASS；Windows未跑则UNVERIFIED；
- [ ] verification逐项映射UV-P1-A01～A20；
- [ ] Task E有明确数据门槛判定，不以模糊“以后再做”结案；
- [ ] commit/stage不含并行dirty work。

## 4. 验收 ID → 实施任务映射

| 验收 ID | 主要任务 |
|---|---|
| UV-P1-A01 | Task 1、Task 6 |
| UV-P1-A02 | Task 1、Task 3 |
| UV-P1-A03 | Task 1、Task 3、Task 4 |
| UV-P1-A04 | Task 2 |
| UV-P1-A05 | Task 2、Task 9 |
| UV-P1-A06 | Task 7 |
| UV-P1-A07 | Task 4 |
| UV-P1-A08 | Task 5、Task 6 |
| UV-P1-A09 | Task 5、Task 6 |
| UV-P1-A10 | Task 6 |
| UV-P1-A11 | Task 6、Task 8 |
| UV-P1-A12 | Task 2、Task 7 |
| UV-P1-A13 | Task 7 |
| UV-P1-A14 | Task 3、Task 8 |
| UV-P1-A15 | Task 8 |
| UV-P1-A16 | Task 3、Task 9 |
| UV-P1-A17 | Task 4、Task 7、Task 8 |
| UV-P1-A18 | Task 8、Task 9 |
| UV-P1-A19 | Task 9 |
| UV-P1-A20 | Task 9 |
| UV-P1-E01 | Task E，只有证据门槛成立后 |
