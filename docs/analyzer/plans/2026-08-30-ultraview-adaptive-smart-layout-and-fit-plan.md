# UltraView 自适应智能排版与 Fit 实施计划

- 日期：2026-08-30
- 状态：READY FOR IMPLEMENTATION
- 对应规格：
  [`2026-08-30-ultraview-adaptive-smart-layout-and-fit-spec.md`](../specs/2026-08-30-ultraview-adaptive-smart-layout-and-fit-spec.md)
- 设计基线：`main` @ `db92d41cace2b4b97fa6a6c8ba7234c085d1722a`
- 本文档任务：只交付 plan/spec，没有修改产品源码或测试

## 0. 实施结论

这不是再调几个 `GRID_*` 常量，也不是给现有 first-fit 多套一层循环。实施必须先统一几何，再建立 Qt-free Smart Layout solver，最后才接 WWT、预览 settle、UI 动作和前台验收。

工作顺序固定为：

```text
事实与红测
  → canonical metrics
  → Smart Layout solver
  → WWT topology adapter
  → preview settle transaction
  → UI action semantics
  → capture quality / persistence
  → foreground + integration gates
```

任何 wave 都不得先在 `MainWindow` 或 widget 中写另一套局部算法。

## 1. 范围和边界

### 本轮实施范围

- neutral Smart Layout DTO、候选生成、确定性求解、fallback；
- neutral canonical screen/export metrics；
- WWT native rect → semantic topology facts；
- Free Grid Smart Layout 与 Compact Arrange 两种命令；
- WWT preview group 的 quiet/deadline/single-settle；
- preview resolution stale/recapture；
- Undo/Redo、project restore、Board lifecycle；
- hints、quickref、用户指南与前台验证脚本。

### 明确不做

- 不改 WWT 解析、公式、曲线绑定、Y fit 或颜色；
- 不改 analysis View 上限与计算；
- 不改 Template Layout、author object 或项目 schema；
- 不从 WWT 毫米大小推断永久 hero 标记；
- 不把 real `testdoc/` 加入 Git；
- 不顺手重构 `window.py` 或 compatibility facade。

## 2. 基线与先行检查

实施者开始前记录：

```bash
git status --short --branch
git rev-parse HEAD
pgrep -af "pytest|probe_view_switch_quality" || true
```

保留所有无关 dirty/untracked 文件。若相关 owner 文件已有并发修改，先停止并协调；不得覆盖或回滚。

不跑 pre-change full suite。先运行现有 owner baseline：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_ultraview_native_layout.py \
  tests/ui/test_wwt_board_projection.py \
  tests/ui/test_ultraview_free_grid.py \
  tests/ui/test_ultraview_card_fit.py \
  tests/ui/test_ultraview_capture.py \
  tests/ui/test_ultraview_viewport.py -q
```

记录当前“保持 span”“宽卡约为窄卡两倍”等旧断言；它们是需要替换的旧产品合同，不得为了兼容而把新 solver 再扭回旧行为。

## 3. T0 — 先写失败合同，不先写 solver

**Owner tests**

- 新增 `tests/test_ultraview_smart_layout.py`：纯 Python、无 Qt；
- 扩展 `tests/ui/test_ultraview_native_layout.py`：真实 WWT→UltraView owner seam；
- 扩展 `tests/ui/test_wwt_board_projection.py`：settle/事务；
- 扩展 `tests/ui/test_ultraview_free_grid.py`：动作语义；
- 必要时新增 `tests/ui/test_ultraview_smart_layout_integration.py`，不要把所有行为堆进一个超大测试文件。

**先红的字面测试**

1. canonical planner/screen/export 对同一 `GridRect` 产生完全相同的 1× outer rect；
2. aspect fitting 扣除 header/footer/padding 后，`reading_fill >= 0.82`；
3. U-Can synthetic 输出两组 `1,3,4` / `2,5,6,7`，View 7 不向上漂；
4. balanced ordinary reading-area ratio `<=1.35`；
5. 7 个 preview aspect 的正序、逆序和固定随机排列得到相同 rect；
6. 2/3/4/7/8/9/12/13/24 与 aspect/topology 矩阵满足 hard constraints；
7. 锁定卡无解时 `accepted=False` 且输入未变；
8. 4096 visit cap 触发确定性 fallback；
9. settle quiet/deadline 只提交一次；
10. settle 前 move 取消自动提交，late preview 不改 revision/history/camera。

**T0 exit**

- 新测试因缺接口/旧语义稳定失败；
- fixture 不依赖本机 `testdoc/`；
- 失败原因不是 Qt 生命周期、随机 seed 或真实 QSettings 污染。

## 4. T1 — 统一 neutral grid metrics

**Owner files**

- `mf4_analyzer/ultraview_core/grid_geometry.py`
- `mf4_analyzer/ultraview_core/native_layout.py`
- `mf4_analyzer/ui/chart_stack/ultraview/free_grid.py`
- `mf4_analyzer/ui/chart_stack/ultraview/compositor.py`（仅消费 neutral metrics）

**实现**

1. 在 neutral owner 提供 canonical 1× screen/export metrics；
2. 删除 native planner 自己拼 96px column metrics 的实现；
3. screen/export/native 共享 pitch 和 `rect_to_pixels`；
4. 保留 viewport zoom 为 metrics 的统一倍乘，不让当前窗口宽度进入 GridRect 规划；
5. 不把 UI package 反向 import 到 `ultraview_core`。

**红转绿**

- metric parity；
- DPR 1/2 logical rect parity；
- screen/export 同 rect；
- import boundary subprocess tests。

**T1 stop rule**

若 compositor 依赖现有 1600px contract 而 neutral 化会改变历史导出尺寸，先补 artifact parity 并把迁移写进 spec；不得静默改变 PNG 字面尺寸。

## 5. T2 — 实现 Qt-free Smart Layout solver

**Owner files**

- 新增 `mf4_analyzer/ultraview_core/smart_layout.py`
- 若 DTO 过多，可新增 `mf4_analyzer/ultraview_core/smart_layout_types.py`
- `tests/test_ultraview_smart_layout.py`

**实现顺序**

1. 不变量验证、稳定排序和 identity 去重；
2. outer rect → inner reading box → contain preview 几何；
3. 冻结 target viewport，完成数量/密度分档的最小 reading-box 约束；
4. 每卡最多 6 个 span 候选；
5. topology-preserving row/skyline pack；
6. 字典序 score vector；
7. locked obstacle；
8. 4096 visit cap 与 equal-grid fallback；
9. structured diagnostics 与零 mutation reject。

**禁止**

- 不用 display title 做 key/tie-break；
- 不在 solver 内读 PreviewStore、QSettings 或 viewport widget；
- 不用一个任意浮点总分让 unreadable 与 whitespace 抵消；
- 不以 wall-clock 毫秒决定搜索提前结束；
- 不捕获 `Exception` 后静默 first-fit。

**T2 exit**

- 全部纯 solver 矩阵绿；
- 同一输入重复 100 次逐字相同；
- 所有 fallback 都有 reason/diagnostic；
- `search_visits <= 4096`。

## 6. T3 — WWT semantic topology adapter

**Owner files**

- `mf4_analyzer/ultraview_core/native_layout.py`
- `tests/_helpers/wwt_factory.py`
- `tests/ui/test_ultraview_native_layout.py`

**实现**

1. `plan_native_layout` 不再直接把毫米缩成最终 span；它先输出 `SmartCardFact` 或等价 neutral facts；
2. 行聚类改为稳定中心线/重叠比例合同，覆盖 bridge rect；
3. source order 和 source column 明确冻结；
4. source salience 使用对数/中位数压缩，只在 `preserve_salience` 生效；
5. exact duplicate 变成同 source row 的 stack/continuation，而非 Manhattan nearest-up；
6. 调用 Smart Layout 得到最终 rect，再沿用既有 apply transaction/cap/warning taxonomy。

**真实边界测试**

至少一个 WWT import flow 调真实 UltraView projection seam，断言：

- 原子成功；
- warning-bearing placement 仍完整 commit；
- reject 零 mutation；
- U-Can 7 placed、顺序与面积比满足 spec。

真实 `testdoc/wwt/U-Can_D6-CSER double_00479.wwt` 只作存在时 optional smoke；缺失不是 owner test skip 的理由。

## 7. T4 — Preview group settle transaction

**Owner files**

- `mf4_analyzer/ui/main_window/ultraview_workspace_controller.py`
- 现有 state holder 或新 controller-local dataclass；禁止写进 `MainWindow`
- `tests/ui/test_wwt_board_projection.py`
- `tests/ui/test_ultraview_placement_history.py`

**实现**

1. pending group 记录 Board id、refs、import revision、冻结 target viewport、captured aspect facts、quiet/deadline token；
2. import membership 后显示稳定 provisional geometry；
3. 事件只更新 facts，并重启 250ms quiet timer；
4. all-ready、250ms quiet、1200ms deadline 三者任一触发同一个 idempotent settle；
5. settle 先核对 Board 仍存在、active workspace 相同、layout revision 未被用户改变；
6. solver 成功后一次 history/dirty/refresh/zoom-fit；
7. solver reject、stale token、用户 touch 均零 mutation；
8. clear/restore/destroy 对称停 timer、断 signal、清 holder。

**测试方法**

- 使用 fake clock/显式 timer trigger，不写 `sleep()`；
- aspect 到达顺序使用参数化 permutations；
- 断言 history 条数、layout revision、zoom invocation 次数；
- parentless Qt 对象显式 teardown，并 drain deferred deletes。

**T4 stop rule**

若无法在不扩宽 `tests/ui/test_main_window_state_ownership.py` whitelist 的情况下实现，停止并把状态继续下沉到 workspace controller/holder；禁止放宽 ratchet。

## 8. T5 — 分清四个 UI 动作

**Owner files**

- `mf4_analyzer/ui/chart_stack/ultraview/free_grid.py`
- `mf4_analyzer/ui/chart_stack/ultraview/board_context_controller.py`
- 新增 `mf4_analyzer/ui/chart_stack/ultraview/smart_layout_settings.py`，只拥有轻量策略/密度设置面
- `mf4_analyzer/ui/chart_stack/ultraview/page.py`（仅 signal/callback wiring）
- `mf4_analyzer/ui/hints.py`
- `mf4_analyzer/ui/quickref.py`
- `docs/analyzer/user-guide/user-guide.html` 的 UltraView 章节

**实现**

- 现“自动排版”入口改为 Smart Layout，默认调用 `balanced/auto`；
- 旧 `plan_auto_arrange()` 保留为 position-only 能力，并在 UI 命名为“紧凑排列”；
- “按原图比例”继续调用 `solve_card_fit()`，不走整组 solver；
- “适应内容”继续只调用 `zoom_fit()`；
- Board 设置提供三策略、三密度和“保留锁定卡片”；
- 菜单保持直接、扁平；高级低层权重不出现在 UI。

兼容边界：现有 `auto_arrange_requested` signal 与 facade 方法保留为 Smart Layout 的兼容入口；新增 position-only 的 `compact_arrange_requested`。不得让兼容名称继续调用旧 first-fit，却在 UI 上宣称“智能排版”。

**交互红测**

- `tests/ui/test_ultraview_page.py`
- `tests/ui/test_ultraview_context_author_ui.py`
- `tests/ui/test_ultraview_recovery_r5.py`
- `tests/ui/test_ultraview_compatibility.py`
- `tests/ui/test_quickref.py`
- 每个动作只改变合同允许的状态维度；
- Smart Layout/Compact Arrange 均是一个 Undo step；
- Card Fit 不移动无冲突邻居之外的整组；
- Board Fit 的 placement snapshot 不变；
- shortcut/menu/hints/quickref 文案一致。

若新增 signal connection，运行 `tests/ui/test_no_lambda_signal_connections.py`；不得新增 `.connect(lambda ...)`。

## 9. T6 — Preview 质量与 recapture

**Owner files**

- `mf4_analyzer/ui/main_window/ultraview_capture_coordinator.py`
- `mf4_analyzer/ui/chart_stack/ultraview/preview_store.py`（仅必要接口）
- `mf4_analyzer/ui/chart_stack/ultraview/layouts.py`
- `tests/ui/test_ultraview_capture.py`
- `tests/ui/test_ultraview_free_grid.py`

**实现**

1. 目标 reading box 超过缓存 logical size 1.25× 时标 `resolution_stale`；
2. 按目标 logical size × current DPR 请求重抓；
3. 保持 QImage/no-upscale/display-aspect 现有合同；
4. recapture 只更新 preview，不触发 Smart Layout；
5. dense-raster Time View 继续按 plotted ink 判断有内容；
6. digest 继续使用稳定 samples facts，不重新引入 ndarray wrapper id。

**T6 exit**

- Retina 与 DPR=1 同一逻辑 geometry；
- 大卡不因小缓存被 Card Fit 压缩；
- recapture 不增加 history/revision/zoom；
- destroyed View/Board 不接收 stale frame。

## 10. T7 — 用户意图、Undo 与恢复闭环

**Owner files**

- `mf4_analyzer/ultraview_core/board_ops.py`（只放 Board 模型操作）
- `mf4_analyzer/ui/main_window/ultraview_workspace_controller.py`
- placement history/project session 既有 owner
- `tests/ui/test_ultraview_placement_history.py`
- `tests/ui/test_ultraview_project_session.py`

**覆盖**

- 显式 lock 与本轮 implicit touch 分离；
- locked 无解整笔 reject；
- provisional/settle 未被用户 touch 时合成一个导入 Undo；
- touch 后封口并取消 settle；
- Undo/Redo 不触发二次自动排版；
- save/reopen rect 相同，不读当前 preview/DPR 重算；
- Board delete/switch/clear/restore/destroy 无 stale timer 写入。

除非确认要持久化新的语义状态，否则不得升级 schema。仅保存最终 rect 时无需 schema bump。

## 11. T8 — 文档、诊断与可发现性

同步更新：

- `mf4_analyzer/ui/hints.py`
- `mf4_analyzer/ui/quickref.py`
- analyzer 用户指南 UltraView 部分
- 必要的帮助截图（只在真实前台截图生成后更新）

用户文案只解释结果和可行动项：

- “锁定卡片占用空间，布局未改变”；
- “已使用等大网格完成降级排版”；
- “预览分辨率较低，打开源 View 后可更新”。

内部 `search_visits`、score vector、fallback code 进入 diagnostics/log，不塞进普通 toast。

## 12. T9 — 验证门禁

### 12.1 Focused owner gates

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_ultraview_smart_layout.py \
  tests/ui/test_ultraview_native_layout.py \
  tests/ui/test_wwt_board_projection.py \
  tests/ui/test_ultraview_smart_layout_integration.py \
  tests/ui/test_ultraview_free_grid.py \
  tests/ui/test_ultraview_card_fit.py \
  tests/ui/test_ultraview_capture.py \
  tests/ui/test_ultraview_placement_history.py \
  tests/ui/test_ultraview_viewport.py -q
```

若最终没有新增 integration 文件，从命令中删除该路径并在验证记录说明 owner tests 落在哪里；不得留下不存在的命令。

### 12.2 Boundary gates

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_import_boundaries.py \
  tests/test_native_import_boundaries.py \
  tests/ui/test_main_window_state_ownership.py \
  tests/ui/test_no_lambda_signal_connections.py -q
```

若改动 `_CanvasBackref` 声明，再加：

```bash
TMPDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m pytest \
  tests/ui/test_pg_canvas_backref_invariants.py -q
```

本规格不改 QSS border、signal math、Batch 或 packaging；对应门禁不因“UI 文件改了”而机械运行。

### 12.3 Deterministic artifacts

生成但不默认提交：

- `.state/ultraview-smart-layout/u-can-layout.json`
- `.state/ultraview-smart-layout/layout-matrix.json`
- `.state/ultraview-smart-layout/cocoa-geometry.json`

artifact 至少包含 policy、facts digest、placements、reading fill、board fill、size ratio、search visits 和 fallback reason。

### 12.4 macOS Cocoa foreground

运行真实 app，使用 U-Can：

1. 导入并等待 settle；
2. 验证 View 1–7 顺序、两组拓扑、无浮动 View 7；
3. 记录 100% 和 Board Fit 截图；
4. 实测每张 outer/reading/image rect；
5. 验证 Smart Layout、Compact Arrange、Card Fit、Board Fit 四个动作；
6. settle 前 move、lock reject、Undo/Redo、保存重开；
7. 切换 Retina/非 Retina 可用屏幕时检查 logical geometry。

不能只看截图“感觉不错”；必须把 U-Can §18 数字合同写入 geometry artifact。

### 12.5 Windows Full/Lite frozen

至少验证：WWT 导入、settle、四动作、Undo/Redo、保存重开、125%/150% DPI。源码级 Windows 检查不能替代 frozen executable。

### 12.6 Full suite owner

这是跨 neutral core、workspace controller、Free Grid 与 project state 的集成改动，稳定 milestone 允许跑一次完整门禁。只由集成负责人运行；开始前确认同 checkout 没有其他 full pytest。

按仓库合同使用两个新鲜、串行进程：

```bash
TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest --ignore=tests/acquisition_ui

TMPDIR=/tmp MPLCONFIGDIR=/tmp QT_QPA_PLATFORM=offscreen PYTHONPATH=. \
  .venv/bin/python -m pytest tests/acquisition_ui
```

运行前后记录 HEAD 与 dirty scope。若相关文件在 pytest 期间变化，结果为 `UNVERIFIED`，不得报 pass。

## 13. Stop rules

出现任一条件立即停止当前 wave，不用兼容补丁掩盖：

1. 需要用 display name 代替 composite ref 才能完成排序；
2. 需要扩宽 MainWindow state ownership whitelist；
3. metrics 统一导致 export artifact 变化但没有明确迁移合同；
4. solver 超预算后 fallback 仍违反 hard constraints；
5. settle 必须依赖 `sleep()` 或 preview 到达顺序才能通过；
6. 用户 touch 后自动任务仍能改 layout revision；
7. 需要升级 schema，却没有单独迁移/回退设计；
8. 相关 owner 文件出现并发修改；
9. 另一个完整 pytest 正在同 checkout 运行；
10. Cocoa 前台与 offscreen 的 geometry/LOD 结论冲突。

## 14. 实施完成清单

- [ ] T0 红测锁定新产品合同
- [ ] T1 canonical metrics 单一 owner
- [ ] T2 neutral solver 与确定性 fallback
- [ ] T3 WWT topology/duplicate 顺序
- [ ] T4 quiet/deadline/single-settle
- [ ] T5 四动作语义与 UI 设置
- [ ] T6 preview resolution recapture
- [ ] T7 lock/Undo/restore/lifecycle
- [ ] T8 hints/quickref/user guide
- [ ] Focused owner gates
- [ ] Boundary gates
- [ ] Geometry artifacts
- [ ] macOS Cocoa foreground
- [ ] Windows Full/Lite frozen
- [ ] 稳定 milestone 两段 full suite
- [ ] `git diff --check`
- [ ] lessons status 已检查；若产生新 recurring lesson 已 promotion

最终报告必须分别写：`source verified`、`offscreen verified`、`Cocoa verified/UNVERIFIED`、`Windows frozen verified/UNVERIFIED`，不得合并成一个“测试通过”。
