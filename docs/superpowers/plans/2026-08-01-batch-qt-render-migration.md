# 批处理绘图迁移 Qt/pyqtgraph —— 分批执行计划

> **For agentic workers:** 本计划按 Batch 分批交付，每个 Batch 末尾有硬性 Gate，
> Gate 不过不得进入下一批。设计依据与所有已拍板决策见
> `docs/superpowers/specs/2026-08-01-batch-qt-render-migration-design.md`（下称 Spec），
> 执行中不得重开 Spec §0 的四个决策。
> 现状事实引用：`docs/superpowers/reports/2026-08-01-batch-time-domain-wave-review.md`。

**Goal:** 批处理出图从 matplotlib Agg 迁移到 Qt/pyqtgraph 离屏渲染，曲线区视觉与
对应单文件 pyqtgraph plot 达到同等级效果，输出收缩为 PNG-only，吸收 B1–B4 渲染
缺陷，最终从产品运行时彻底移除 matplotlib。

---

## Global Constraints（所有 Batch 适用）

- TDD-first：每个产品行为变更先写红测并留下 RED 证据，再实现转绿。
- 开工基线必须是包含本 Spec/Plan 的干净 commit/独立 worktree。当前 checkout 若有
  其他未提交改动，不得直接在其中执行本计划或按 Task commit。
- 命令模板：
  `TMPDIR=/tmp QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp PYTHONPATH=. .venv/bin/python -m pytest <targets> -q`
- `mf4_analyzer/batch.py` 顶层不得 import PyQt5/pyqtgraph（惰性导入点保持惰性）。
- 不修改 `mf4_analyzer/signal/`；dB 转换必须继续调用
  `SpectrogramAnalyzer.amplitude_to_db`；导出数据不因显示模式改变。
- 不修改 timedomain UI（`mf4_analyzer/ui/pg_canvas/`、`chart_stack/`）的任何
  行为、接口、外观；只允许**只读复用**或按 Spec §2.5 提取共享常量。
- 禁 OpenGL；QPainter 与所有 curve item 都显式 AA。
- 批量 PNG 只保留 Spec §0 D4 的报告元素和单文件 Plot 绘图区；主界面模块导航、Qt/
  pyqtgraph 默认按钮、菜单、frame、scrollbar、focus rect、toolbar/status chrome 一律
  不得进入产物。每个 PlotItem 显式 `hideButtons()`、关闭 menu/交互并加结构+像素守卫。
- 全量门禁：每个 Batch 收尾跑
  `pytest -p no:randomly --ignore=tests/acquisition_ui -q`。failed nodeid 集合必须是
  Batch 1 干净基线集合的子集；只比较失败数量不算通过。
- 删除任何类/模块前，先 `rg -n "<符号>" tests/` 全测试树扫 blast radius
  （lesson `refactor/2026-06-18-mpl-canvas-retirement-test-blast-radius`）。
- 每个涉及 renderer 的 Batch 都必须运行 Spec §2.7 离屏 parity 工具，保存
  batch/reference/plot-area crop/contact sheet/evidence JSON；执行 agent 必须实际打开
  contact sheet 逐项写 PASS/FAIL，不能只看 pytest 或属性值。
- 最终验收时，协调/主 agent 必须在待验收 commit 亲自重跑完整离屏矩阵并打开四模块
  contact sheet 复核；不得只转述 worker 结论。`evidence.json` 必须绑定 commit SHA、
  Qt platformName、依赖版本和产物 SHA256。
- 离屏 parity 与真机证据分开：前者是 Batch 2/3/4 硬 Gate，后者必须在拆除
  matplotlib 依赖与打包契约前完成一次 macOS cutover 验收，并在最终阶段复验。
- 每个 Task 单独 commit 且 commit 后相关 Gate 必须绿色；如果两个动作无法形成绿色
  中间态，计划必须把它们明确合成一个原子 Task，不允许提交已知红态。
- 不并行写同一文件。
- 适用 lessons（开工前读）：`batch-render-cjk-glyph-coverage`、
  `batch-render-degradation-stops-at-probe`、`codex-visual-parity-rendered-screenshot`、
  `matplotlib-pruning-needs-frozen-render-matrix`、
  `pyqt-ui/2026-04-25-tightbbox-survives-offscreen-qt`、
  `pyqt-ui/2026-05-28-mpl-event-coupled-tests-survive-renderer-swap`。

## Agent Assignment 建议

- **Batch 0、2、3、4（渲染与 UI 面）：** `pyqt-ui-engineer`
- **Batch 1（runner 函数体逻辑修复）：** 通用 `worker`；禁止分给只允许模块搬迁、
  import/re-export 调整的 `refactor-architect`。
- **Batch 4 中 batch.py 接线：** 修改函数体/plumbing 时用通用 `worker`；纯模块搬迁才可
  使用 `refactor-architect`。
- **Batch 5（拆除/打包/搬迁）：** `refactor-architect` 或通用 `worker`，按实际是否需要
  修改函数体拆分所有权。
- **Batch 3 完成后：** `signal-processing-expert` 做一次 dB/数值不变量 review
  （只 review，不改码）
- 每个 Batch 完成后先 spec-compliance review，再 code-quality review。

## 依赖关系

```
Batch 0 (spike) ──┐
                  ├──> Batch 2 ──> Batch 3 ──> Batch 4 ──> Gate 4.5 macOS
                  │                                      └──> Batch 5 ──> Batch 6
Batch 1 (P0)   ───┘        （Batch 0 与 Batch 1 可并行）
```

---

## Batch 0：可行性 Spike（只产证据，不进产品代码）

**产出物：** `scratchpad/batch-qt-spike/`（脚本+图+数据）与
Spec 附录（追加 `## 附录 A：Spike 结论`）。

- [ ] **S0.1 离屏渲染原型**
  - 脚本构建 `GraphicsLayoutWidget`：1920×1080，含两行图头 LabelItem、facts 行、
    1 个双 Y overlay 面板（各 1 条曲线）+ 8 面板 subplot 变体 + 1 个
    ImageItem+ColorBarItem heatmap 变体。
  - `WA_DontShowOnScreen` + `show()` + `processEvents()` 路径分别在
    `QT_QPA_PLATFORM=offscreen` 与 macOS 真机 cocoa（GUI QApplication 存在时
    不闪窗）下验证。
  - 导出走 Spec §2.3 的 QImage+render 路径：验证像素尺寸精确等于请求值
    （HiDPI 机器上尤其要验）、三主题（white/transparent/dark）背景正确、
    dpi 元数据 round-trip、`QImage.setText` 元数据可读回。
  - 中文图头 `单帧振动加速度` 渲染 + 墨迹像素统计（Spec §2.6 双保险原型）。
  - 用同一份 time/fft/heatmap payload 分别驱动原型和现有单文件 canvas，生成首版
    batch/reference/crop/contact sheet；执行 agent 必须打开图片确认没有空图、漏线、
    转置、裁切或明显 AA 退化，并把判断写进 Spike 结论。
- [ ] **S0.2 线程 marshal 原型**
  - QThread worker 中调用渲染入口，经 BlockingQueuedConnection 到主线程执行；
    验证：结果回传、异常跨线程重抛、主线程开着模态 QDialog 时渲染仍可达、
    app 退出时 fail-fast。
- [ ] **S0.3 性能与内存**
  - 计时：单图 1920×1080 × {overlay, 8 面板 subplot(每面板 1e5 点), heatmap}
    各 ≥20 次取 p50/p95；4K（3840×2160）单图一次并记录进程 RSS 峰值。
  - 同时在 GUI 线程挂 50 ms heartbeat，worker 连续请求 ≥20 张图，记录最大事件循环
    间隙和超 100 ms 次数。
  - 双预算：p95 ≤ 500 ms/图（1080p）且最大 event-loop gap ≤ 200 ms；500 ms
    只是技术 STOP 线，不等于“无感知冻结”。
- [ ] **S0.4 写结论**
  - 全项通过 → 在 Spec 追加附录 A（数据+结论），Gate 放行。
  - 任一不过 → **停**，把失败项和候选替代方案（如渲染子进程）整理后交回用户
    决策；不得自行扩大方案。

**Gate 0：** 附录 A 存在且全项 PASS；离屏 contact sheet 已由执行 agent 实际打开并
逐项签字；性能与 heartbeat 双预算都通过。

---

## Batch 1：P0 前置修复（与 Batch 0 并行）

- [ ] **T1.1 修 A1：路径驱动批处理整体 blocked**
  - Files: `mf4_analyzer/batch.py`、`tests/test_batch_source_integration.py`（新增红测）
  - 先写红测：显式 `target_signals` + 纯 `source_paths`（无 `source_ids`）+
    一个物理文件出多个逻辑源。
  - 修复方向（review §1）：`_scope_source_keys` 在 `allow_source_load=False`
    且只有 `source_paths`/`file_paths` 时返回空，让 `if not tasks:` 兜底重新
    生效；或在 `_build_run_plan` 前显式检测未迁移路径。
  - 验证：
    `pytest -p no:randomly tests/test_frozen_batch_acceptance.py tests/test_batch_source_integration.py -q`
    全绿，并实跑一次 `frozen_batch_acceptance` CLI（当前仍是 CSV+PDF，照旧）。
- [ ] **T1.2 记录全量基线**
  - 在 T1.1 的干净 commit 上跑
    `pytest -p no:randomly --ignore=tests/acquisition_ui -q`；不得沿用历史 `61/57/68`
    等数字。
  - 写 `docs/superpowers/reports/2026-08-01-batch-qt-baseline.md`，记录 commit SHA、
    完整命令、passed/skipped/failed 数和全部 failed nodeid。后续 Gate 要求失败集合是
    该集合的子集，不能只比较数量。
  - 另跑默认裸 pytest 作为诊断；若仍触发现有 Qt SIGSEGV，单独记 `UNVERIFIED`，
    不得写成 PASS，也不得抹掉上面的可完成门禁。

**Gate 1：** A1 四条红测全绿；基线报告已固定 commit SHA 和 failed nodeid 集合。

---

## Batch 2：Qt 渲染核心（time + fft + 报告页）

新代码全部落在 `mf4_analyzer/batch_render_qt/`（Spec §2.1 布局），本批**不接线**
到 BatchRunner，`batch_render.py`（matplotlib）保持原样运行。测试新建
`tests/test_batch_render_qt.py`（可按主题拆多文件）。

- [ ] **T2.1 骨架：dispatch + export + theme + fonts**
  - Files: `batch_render_qt/{__init__,_dispatch,_export,_theme,_fonts}.py`、
    `mf4_analyzer/batch_image_options.py` + 测试
  - `_dispatch.ensure_app()` / `render_on_gui_thread()` 按 Spec §2.2 实现；
    线程契约测试：worker 线程 marshal 成功、异常重抛、无 app 非主线程报
    清晰 RuntimeError、已有 QCoreApplication 时 fail-fast、`warnings_out` 跨线程
    回传且公共签名与迁移前一致。
  - `_export`：QImage 精确尺寸、三主题背景、dpi 元数据、`setText` 元数据、
    恒 AA；所有 PlotDataItem 明确 `antialias=True` 并被测试内省；写 temp 路径
    （不做原子写，原子写仍归 `batch_output`）。
  - `_theme`：Spec §2.5 契约表 token 化，测试逐项锁定（含
    `FILE_PALETTES[0]` 引用同源断言）。
  - `BatchRenderOptions.line_width` 默认先改为 1.5 并加测试；旧产品 runner 此时仍会
    显式传 `BatchOutput.image_line_width=1.0`，所以不会提前改变线上 matplotlib 输出。
  - `_fonts`：CJK 解析 + `supportsCharacter` 覆盖检查 + 墨迹像素证明 helper；
    候选表与 `pg_canvas/fonts.py` 同源（直接复用或提取共享常量，二选一后
    加两侧一致性测试）。
- [ ] **T2.2 time overlay + fft（吸收 B1）**
  - Files: `batch_render_qt/_builder.py`、`_page.py` + 测试
  - 红测先行：`(color, linestyle)` 两两不同（含双 Y 跨左右轴）；≤2 Y 单位
    fail-closed 文案与现实现一致；linestyle 映射；fft 固定色 `#1769e0`；
    dB params 语义。
  - 报告页：两行图头、facts 事实条（字段与 `effective_facts` 现状一致）、
    页脚、合并图例框。
  - 红测先行：所有 PlotItem 的 auto-range button/context menu/鼠标交互关闭，导出图
    四角与 plot-area 不含 Qt/pyqtgraph 默认控件 chrome；不得复制主界面模块导航。
- [ ] **T2.3 time subplot（吸收 B2、B3）**
  - 红测先行：8 面板相邻文本 sceneBoundingRect 不相交；仅底行 X 标签；
    X 范围传播一致；B3 标题分派（source 分组→channel 名，channel 分组→文件名，
    同图语义一致）。
  - 结构断言 + 像素特征断言双写（Spec §5 分层）。
- [ ] **T2.4 B4 图面文本守卫（渲染端）**
  - 红测：原始 `group_key` 和已知 source 绝对路径不出现在任何
    LabelItem/TextItem；同时用含 `[`/`"` 的合法通道名证明不会误杀用户文本。
    渲染端只接受 display 名，plumbing 在 Batch 4。
- [ ] **T2.5 time/fft 离屏单文件 parity**
  - Files: `tools/verify_batch_qt_render_parity.py`、
    `tests/test_batch_qt_render_parity.py`、`docs/superpowers/verify/batch-qt-render/`
  - 按 Spec §2.7 生成 time 单曲线、raw+filtered、双 Y、8-panel subplot、custom-X，
    以及 fft linear/dB/manual-range 的 batch/reference/crop/contact sheet。
  - 机器断言 X/Y、range、色轮、1.5 px、linestyle、9 pt、网格/轴 pen 和无文字相交；
    执行 agent 用图片查看工具实际打开全部 contact sheet，在 evidence 表逐 case 写
    PASS/FAIL + 备注。至少提交一张 time contact sheet 和一张 fft contact sheet。

**Gate 2：** `pytest tests/test_batch_render_qt*.py -q` 全绿（offscreen）；
B1/B2/B3 红测有 RED→GREEN 证据；T2.5 所有 case 机器断言和目视检查均 PASS；
全量失败 nodeid 集合没有超出 Batch 1 基线。

---

## Batch 3：heatmap kinds（fft_time / order_time）

- [ ] **T3.1 ImageItem + ColorBarItem 渲染**
  - Files: `batch_render_qt/_builder.py`（heatmap 分支）+ 测试
  - 红测先行：turbo LUT 与 `heatmap_canvas._resolve_colormap("turbo")` 一致
    （黄金 LUT 已在 `tests/data/colormap_golden.npz`）；非法 cmap → turbo +
    warning；`z_auto=False` 时 levels=(z_floor,z_ceiling)；显式
    `axisOrder="row-major"` + `QRectF` coverage extent；colorbar 标签
    dB/Amplitude 逻辑与现状一致。
  - 用值各不相同的非对称 2×3 矩阵做四角颜色/坐标红测，必须能抓到转置、上下翻转、
    中心坐标误当 coverage 边界三类错误。
  - dB 转换调用点断言：仍走 `SpectrogramAnalyzer.amplitude_to_db`。
- [ ] **T3.2 数值不变量 review（signal-processing-expert，只 review）**
  - 核对导出矩阵与 mpl 版逐元素一致（同 payload 双渲染对比数值，不比像素）。
- [ ] **T3.3 heatmap 离屏单文件 parity**
  - 扩展 T2.5 工具，生成 fft_time/order_time 的 linear/dB、auto/manual levels、
    非对称矩阵 batch/reference/crop/contact sheet。
  - 机器断言 matrix/LUT/levels/extent 与 plot-area 四角；执行 agent 实际打开全部
    contact sheet，确认无转置、翻转、colorbar 裁切和文字重叠并逐项签字。

**Gate 3：** 4 kinds 全部可从 `batch_render_qt` 出图；review 无 blocking 发现；
T3.3 机器断言和目视检查均 PASS；全量失败 nodeid 集合没有超出 Batch 1 基线。

---

## Batch 4：接线 + PNG-only 收缩 + CLI/GUI 改造

- [ ] **T4.1 PNG-only canonical contract（先做，旧 renderer 仍可输出 PNG）**
  - Files: `mf4_analyzer/batch_image_options.py`、`mf4_analyzer/batch_recipe.py`、
    `mf4_analyzer/batch_preset_io.py`、`mf4_analyzer/batch.py`、
    `mf4_analyzer/batch_manifest.py`、`mf4_analyzer/batch_validation.py`、
    `mf4_analyzer/ui/drawers/batch/output_panel.py`、
    `mf4_analyzer/batch_render_smoke.py`、`mf4_analyzer/frozen_batch_acceptance.py`、
    `mf4_analyzer/batch_time_group_acceptance.py` + 对应测试。
  - 按 Spec §3 增加 `requested_image_format` migration provenance：旧导入
    svg/pdf→canonical png + 中文 warning；新的直接 PDF/SVG 请求仍 fail closed。
  - fingerprint 只看 canonical PNG；requested/effective 分离；resume 只复用
    effective PNG + checksum，旧 PDF/SVG artifact 不得冒充 PNG。
  - 把真正的产品默认链补齐到 1.5：`BatchOutput`、`OUTPUT_DEFAULTS`、preset 导入
    缺省、validation fallback、GUI 默认选中项，并复核 T2 已改的
    `BatchRenderOptions`；旧 preset 显式保存的 1.0 继续尊重。
  - GUI 格式下拉只留 PNG，PNG DPI 恒可用；三个 CLI 的请求/产物矩阵先收缩为 PNG，
    CJK/platform verifier 判据留到 T4.3 改。此 Task 后产品仍走 matplotlib PNG，所以
    可形成独立绿色 commit，T4.2 切换时不会再有 SVG/PDF 调用打向 PNG-only renderer。
- [ ] **T4.2 facade + B4 plumbing 原子切换**
  - Files: `mf4_analyzer/batch_render.py`、`mf4_analyzer/batch_grouping.py`、
    `mf4_analyzer/batch.py`、`tests/test_batch_renderer.py`、
    `tests/test_batch_runner.py`。
  - 先 `rg -n "_build_batch_figure|_build_export_scene|batch_render|RenderGroup" \
    tests/ mf4_analyzer/ tools/`，列出完整 blast radius。
  - `batch_render.py` 改为薄门面；公共签名保持
    `render_batch_image(..., warnings_out=None)`，不改 keyword 兼容性。
  - 删除或迁移 `BatchRunner._build_export_scene`，facade 不 re-export 已退役的
    `_build_batch_figure`。
  - `RenderGroup.display_name` 在 `batch_grouping.py` 定义/构造；`batch.py` 只把人类
    display 字段送入 context。精确断言原始 group_key/绝对路径不进图面，同时允许
    合法通道名含 `[`/`"`。
  - `BatchRunner` 对 4 种 kind 都传递 `warnings_out`，不得只在 time 路径保留 warning；
    非法 heatmap cmap 的 warning 必须进入 item/manifest。
  - `test_renderer_source_is_gui_framework_free` 反转为“禁 matplotlib”守卫，并新增
    `batch.py` 顶层无 Qt import 守卫。
- [ ] **T4.3 CLI/冻结验证器改写**
  - Files: `mf4_analyzer/batch_render_smoke.py`、
    `mf4_analyzer/frozen_batch_acceptance.py`、
    `mf4_analyzer/batch_time_group_acceptance.py`、
    `tools/verify_frozen_batch_render.py` + 对应测试。
  - smoke：矩阵 4 kinds × `("png",)`，`ok` 判据换为 Spec §2.6 双保险
    （字体覆盖 + 墨迹像素），JSON 同时记录 `QT_QPA_PLATFORM` 与 Qt platformName。
  - 冻结验收保持 T4.1 已收缩的 CSV+PNG，改写 evidence 判据与产物断言，不再
    接受或生成 PDF。
  - 时域分组验收：补 `render_layout=subplot` 与 `x_source=channel` 组合
    （review §3 指出的矩阵缺口），产出 PNG 走 B2 的不相交断言。
- [ ] **T4.4 GUI 端到端**
  - Files: `tests/ui/`（新测试）
  - pytest-qt offscreen：真实 `BatchRunnerThread` 跑一单（data+image），验证
    worker→主线程 marshal 出图成功、manifest artifact_facts 完整、UI 不死锁；
    再验 backend 不可用注入时 data-only 降级语义原样（复用现有降级测试改写）。
- [ ] **T4.5 完整离屏矩阵与双层目视签字**
  - `QT_QPA_PLATFORM=offscreen` 实跑 Spec §2.7 全矩阵：4 kind、time 五场景、heatmap
    非对称矩阵、三主题、1080p/4K、CJK、custom-X。
  - 输出到 `docs/superpowers/verify/batch-qt-render/`：至少四张按模块 contact sheet +
    `evidence.json`。执行 agent 必须逐张打开，报告每个 case 的 PASS/FAIL 与观察；
    任一漏线、转置、裁切、重叠、颜色/线宽/网格/字体明显不如单文件 plot，或混入
    Qt/pyqtgraph 默认控件与主界面导航，即 Gate 红。
  - 协调/主 agent 在 T4.2–T4.4 全部落到待验收 commit 后亲自重跑本矩阵，独立打开
    time/fft/fft_time/order_time 四张 contact sheet 复核并追加签字；worker 代验无效。

**Gate 4：** 三个 CLI 入口实跑通过；GUI e2e 绿；B1–B4 全部转绿在套件内；
完整离屏 parity 的机器断言和 agent 目视均 PASS；全量失败 nodeid 集合没有超出
Batch 1 基线。**此 Gate 后产品已完全跑在 Qt 渲染上；旧实现仅可通过原子 revert
T4.2 恢复。此时仍不得拆除 matplotlib 依赖、打包契约和旧专属验收资产。**

### Gate 4.5：matplotlib 依赖拆除前的 macOS 前台 cutover 验收

- 用真实 MF4/CSV 数据覆盖 overlay 双 Y、8-panel subplot、
  `render_group_by=channel|source`、`x_source=channel`、fft、fft_time、order_time、
  三主题和 4K。
- 同数据打开单文件 plot 与 batch PNG 并排截图；确认色轮、默认 1.5 px、网格、字体、
  轴样式、范围/levels 相当，报告元素完整，无 JSON/路径泄露。
- 连续批量出图时拖动窗口/悬停 tooltip，记录 50 ms heartbeat；最大 gap ≤200 ms，
  且人工无连续冻结感。

**Gate 4.5：** 前台截图、操作观察与 heartbeat 全 PASS 才允许进入 Batch 5；失败时仍可
整体 revert facade 切换回 matplotlib。

---

## Batch 5：matplotlib 依赖/旧契约拆除 + 打包契约重建

- [ ] **T5.1 清理旧专属测试与工具**
  - 复核 `batch_render.py` 在 T4.2 后只剩 Qt 薄门面，删除
    `tests/test_matplotlib_frozen_contract.py`、
    `tools/matplotlib_frozen_contract.py`。
  - 先跑 blast-radius grep：
    `rg -n "matplotlib|_build_batch_figure|FigureCanvasAgg|mpl\." mf4_analyzer/ tests/ tools/`
    逐条处置并在 commit message 列出。
  - 新守卫：`mf4_analyzer` 全包 `rg "^\s*(import|from) matplotlib"` 零命中的
    源码扫描测试。
- [ ] **T5.2 依赖与打包**
  - Files: `requirements.txt`、`mf4_analyzer/io/runtime_dependencies.py`、
    `tools/build_windows_folder.ps1`、`tools/build_windows_folder_lite.ps1`、
    `tools/verify_frozen_batch_render.py`、`tests/test_windows_build_script.py`、
    `tests/test_windows_runtime_dependencies.py`
  - 删 matplotlib 依赖声明与 `MPLBACKEND`/mpl-data 裁剪逻辑；PyInstaller
    excludes 加 `matplotlib`；评估 `contourpy/kiwisolver/cycler/fontTools/PIL`
    是否失去唯一使用者，逐个决定去留并记录。
  - 打包契约新增：platforms 插件含 `offscreen`；冻结烟测判据换新版。
  - `tools/` 下开发对比脚本（`fft_welch_compare.py` 等）保留，文件头注明需
    自装 matplotlib（不属产品运行时）。
  - 修 review D7：只给真正调用 `powershell.exe` 的 native-execution 用例加
    `@pytest.mark.skipif(sys.platform != "win32")`；读取/断言脚本文本的跨平台契约测试
    继续在 macOS/Linux 运行，禁止整文件 skip。
- [ ] **T5.3 lessons 维护**
  - `docs/lessons-learned/matplotlib-pruning-needs-frozen-render-matrix.md`
    标 superseded（指向本迁移）；
    `batch-render-cjk-glyph-coverage.md` 改写为 Qt 版规则；
    新增"Qt 离屏批渲染线程边界与 QApplication 生命周期"lesson；
    同步 `docs/lessons-learned/LESSONS.md` / `INDEX.md` 索引。

**Gate 5：** 全包无 matplotlib runtime import；完整离屏 parity 在拆除后复跑仍 PASS；
全量失败 nodeid 集合没有超出基线。无 Windows 机器可继续做源码收尾，但状态只能是
“源码实施完成 / Windows 发布 NO-GO”，不得伪称总验收完成。

---

## Batch 6：拆除后复验、Windows 冻结验收与报告

- [ ] **T6.1 拆除后 macOS 真机复验**
  - `TMPDIR=/tmp QT_QPA_PLATFORM=cocoa PYTHONPATH=. .venv/bin/python "MF4 Data Analyzer V1.py"`
  - 重跑 Gate 4.5 的代表矩阵，确认拆依赖/打包代码没有改变 GUI 结果。
- [ ] **T6.2 Windows onedir 双平台冻结验收**
  - 新鲜构建 full/lite onedir，先显式 `QT_QPA_PLATFORM=offscreen` 跑 4-kind PNG +
    CJK + turbo smoke，再显式 `QT_QPA_PLATFORM=windows` 用
    `WA_DontShowOnScreen` 跑同矩阵。
  - 两份 evidence JSON 必须记录不同 platform，绑定同一新 EXE SHA；旧 EXE 或旧
    evidence 不得复用。记录迁移前后 `_internal` bytes/files。
- [ ] **T6.3 验收报告**
  - 写 `docs/superpowers/reports/2026-08-XX-batch-qt-render-migration-review.md`：
    离屏四模块 contact sheet、实现 worker 与协调/主 agent 的逐 case 双签字、前台单文件
    plot 对照截图、性能/heartbeat、全量基线集合比较、Windows 双平台冻结证据与
    包体积变化。

**Gate 6（总验收）：** Spec §8 全部满足。若 Windows 双平台冻结证据缺失，报告可以
完成，但结论必须是“源码实施完成 / Windows 发布 NO-GO”，不能把总验收标 PASS。

---

## Rollback 策略

- Batch 4 之前：产品始终跑在 matplotlib 上，任何回退 = revert 对应 commit。
- Batch 4 的 T4.2（facade + B4 plumbing）是原子切换 commit，可整体 revert 回
  matplotlib PNG 路径；T4.1 PNG-only contract 可独立保留。
- Batch 5 拆除后不可低成本回退——因此 Gate 4 的完整离屏 parity 与 Gate 4.5
  macOS 前台验收必须都 PASS 才允许进入 Batch 5。
