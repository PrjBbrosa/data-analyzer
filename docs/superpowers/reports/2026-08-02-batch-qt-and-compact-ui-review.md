# 批处理 Qt 渲染迁移 + 紧凑 UI 合并包 — 外部 Review

**日期：** 2026-08-02  
**审查范围：** `main` @ `78e091a`（合并 tip）  
**上游线：**
- Qt 渲染迁移：`612bdd5` → `020a251`（`codex/batch-qt-render-migration`）
- 紧凑 UI 重设计：`85054ce`（`codex/batch-compact-ui-redesign`）
- 合并：`78e091a merge: integrate compact batch workflow`

**总评：** Qt 渲染迁移**源码侧可接受**（与 codex 自验收一致：macOS GO / Windows NO-GO）。紧凑 UI 合入后引入若干**用户可见缺陷**和一处**合并语义冲突**；合包鲁棒性还不够发布级。

---

## 1. 结论一览

| 维度 | 判定 | 说明 |
|---|---|---|
| Qt 渲染迁移实现质量 | **强** | 架构、线程、PNG-only、B1–B4、CJK、主题、心跳证据扎实 |
| 与原 plan/spec 偏差 | **合理加固** | codex 的 plan 修订（DPM 时机、envelope、migration_warnings、B3 producer 分派）是真加固 |
| 紧凑 UI 重设计 | **部分完成** | 离屏视觉大体合格；macOS 前台验收未做；若干交互缺陷 |
| 合并 `78e091a` | **PNG-only 幸存 / 线宽冲突** | 格式契约正确；`image_line_width` 被 UI 硬编码回 1.0 |
| 测试 | **聚焦绿 / 全量基线对齐** | 批处理聚焦 448 passed；全量与 61-fail 基线同族（UI split 系） |
| Windows 冻结发布 | **NO-GO** | 与 codex 一致，缺四组 onedir smoke |
| 是否需要后续优化 | **需要** | 见配套 spec |

---

## 2. Qt 渲染迁移 — 做得好的地方

1. **包边界清晰**：`batch_render.py` 薄门面；实现在 `batch_render_qt/`；`batch.py` 仍保持无顶层 Qt 导入。
2. **线程模型正确**：`BlockingQueuedConnection` 调度；QWidget 建/画在 GUI 线程；PNG 编码留调用方线程（`32ab5e5`）。
3. **显示级包络**：dense/high-raster 用 `positions_envelope`，不污染 `BatchSeries` / 分析数值 / CSV。
4. **PNG-only 五层一致**：`batch_image_options`、`batch_recipe._duck_outputs`、`batch_preset_io` 旧 pdf/svg→png + `migration_warnings`、冻结验收、smoke。
5. **B 缺陷吸收**：
   - B1 双 Y 轴色随曲线（验收 PNG 与 Cocoa 真数据均可见）
   - B3 source 分组 panel title=channel（`batch.py` producer 分派）
   - B4 header 用 `display_name`，不泄漏绝对路径 / JSON
6. **证据链可复核**：
   - 聚焦渲染/线程套件本机复跑：**448 passed**
   - Cocoa 真数据矩阵 + 1000-PNG 心跳 `max_gap_ms=88.35`、`over_100ms_count=0` 与报告一致
   - 分组验收 CLI `status=success`，resume 字节/mtime 不变

### 2.1 与原 plan 的偏差（均为加固，非偷工）

| 项 | 原 plan | codex | 评价 |
|---|---|---|---|
| DPI 元数据时机 | 渲染前可写 | `painter.end()` 后写 DPM | 必要（AxisItem QPicture） |
| 曲线 AA | 恒 True | 成本门 + envelope | 必要（响应性） |
| B3 语义 | renderer 猜 | producer 分派 + renderer 只消费 | 更干净 |
| 旧格式兼容 | recipe 可静默 | 仅可信 importer；`_duck_outputs` fail-closed | 更安全 |
| 线宽默认 | 1.0 | 1.5（对齐 timedomain） | 正确，但被 UI 合并冲掉 |

---

## 3. 已确认缺陷（按严重度）

### P1 — 用户可见 / 契约破损

#### D1. `get_outputs()` 硬编码线宽 1.0，冲掉 Qt 线 1.5 默认（合并语义冲突）

- **位置：** `mf4_analyzer/ui/drawers/batch/output_panel.py:736`
- **证据：** `BatchOutput.image_line_width` / `OUTPUT_DEFAULTS` / `BatchRenderOptions` 均为 **1.5**；UI 隐藏 combo 默认索引也是 1.5；`get_outputs()` 却写死 `1.0`。
- **影响：** 合包后所有 GUI 批处理出图比单文件 timedomain 与 CLI/默认配方更细，视觉对齐目标打折。
- **来源：** `85054ce` 固定导出契约 vs `020a251` 线宽上调；`78e091a` 未调和。

#### D2. FFT 模式丢失 dB ↔ Linear 入口

- **位置：** `combo_amp_unit` 挂在色阶（Z）行（`_helpers.py:928`）；FFT 时 `_set_z_axis_visible(False)` 整行隐藏（`output_panel.py:582`）。
- **证据：** `1080-fft-applied.png` 坐标卡只有 dB 参考 / 频率 / 幅值，无单位切换；`1080-fft-vs-time.png` 因色阶行可见而保留 dB 下拉。
- **影响：** 纯 FFT 批处理无法从 UI 切到线性幅值（默认被锁在 dB）。

#### D3. 幂等点击当前方法会清空已应用预设

- **位置：** `method_buttons.py:73-76`（同方法仍 emit）→ `analysis_panel.py:290-292`（`clear_selection=True`）。
- **影响：** 用户再次点击已选中的「FFT」会取消预设卡选中，状态回到「未应用预设」。

#### D4. 方法切换时管线校验用旧轴状态

- **位置：** `sheet.py:332-338` 连接顺序：`_recompute_pipeline_status` **先于** `apply_method_defaults`。
- **影响：** 从 FFT（Hz 手动范围）切到时域时，一次校验可能读到旧轴参数，短暂误报 blocked / 错误摘要。下一次任意 changed 会纠正，但仍是竞态型 UX 缺陷。

### P2 — 渲染 / 架构鲁棒性

#### D5. subplot 有面板标题时抹掉 Y 轴单位标签

- **位置：** `batch_render_qt/_builder.py:774-780`
- **证据：** 探针 `subplot-units.png`：上/下板仅有 `acc`/`speed` 内嵌标题，无 `Amplitude (g)` / `Amplitude (rpm)`。
- **影响：** 相对旧 matplotlib 路径的信息回归；多单位 subplot 报告读图成本上升。

#### D6. 渲染器经 `mf4_analyzer.ui` 导入，拉入 `MainWindow` 顶层链

- **位置：** `_fonts.py` → `ui.pg_canvas.fonts`；`_builder.py` → `ui.pg_canvas.*`；而 `ui/__init__.py` 顶层 `from .main_window import MainWindow`。
- **影响：**
  1. CLI/冻结路径的「渲染后端探测失败 → data-only 降级」会把**任意 UI ImportError** 吞成「图片后端不可用」，静默面过大。
  2. 导入成本与耦合上升（本机探测约 0.45s，可接受但结构脆弱）。

#### D7. 全量 `tests/ui` 在 Qt 迁移线上可复现 SIGSEGV（非批处理主路径，但门禁不稳）

- **堆栈：** `db_reference_dialog.py:117` `ScientificReferenceSpinBox has been deleted` → Fatal SIGSEGV。
- **Bisect：**
  - `c1b3cef`（基座）：**不崩**，`60 failed, 2641 passed`
  - `020a251`（Qt 线 tip）：**崩**
  - `main` 用 `-v` 有时能跑完（60 fail），用 `-q`/全量管道曾崩 — **顺序/时序敏感**
- **判定：** 不阻塞「批处理出图正确性」，但说明合包后的「无 SIGSEGV」声明不可复现为稳定性质；需单独修 lifecycle，不能再当 Gate PASS 背书。

### P3 — 清理 / 潜在

| ID | 问题 | 备注 |
|---|---|---|
| D8 | `get_outputs()` 固定 `resume_policy="none"` 且 `apply_outputs` 不写回 resume | 恢复按钮已隐藏，属潜伏死代码；若再启用会「必 blocked」 |
| D9 | `_dispatch._APP` 赋值后几乎不用；`aboutToQuit` 与 emit 间有微小窗口 | 低危 |
| D10 | `save_png` 无 `QImage.isNull()` 检查 | 极端分配失败会写出坏文件 |
| D11 | `findings.md` / `progress.md` / `task_plan.md` 进 main，且含本机绝对路径 | 仓库卫生；85054ce 加重 |
| D12 | 紧凑 UI remediation：**macOS 前台验收未执行** | 计划自行标注 |
| D13 | 离屏截图小问题：dB 摘要重复、「目标信号」1080 截断 | 视觉 polish |

---

## 4. 测试与证据（本轮独立复核）

| 检查 | 结果 |
|---|---|
| 批处理聚焦（renderer/runner/smoke/acceptance/…） | **448 passed** |
| 分组时域验收 CLI | **status=success**，resume 事实齐全 |
| 边界探针（双 Y 手动 Y / 主题 / 长文本 / NaN / 空序列 / 像素+DPI） | 行为符合契约；手动双 Y 抛错与旧 mpl **一致**（非回归） |
| 验收 PNG + Cocoa 真数据目视 | B1/B3/B4/CJK/主题 OK |
| 紧凑 UI 聚焦（[审查紧凑批处理UI重设计](272b2d67-e428-4995-bcfd-2ae77f229de4)） | **179 passed**；24 张离屏截图 |
| 全量相对 Batch1 基线 | 失败集仍以 `tests/ui/test_split_*` 为主；**无新增批处理失败** |
| Windows onedir | **仍缺**（维持 NO-GO） |

---

## 5. 鲁棒性总评

**渲染内核：** 对生产路径（GUI worker → marshal → PNG、旧预设迁移、分组 resume、CJK 双重证明）已经偏强，测试密度高。

**合包弱点：**
1. UI 契约层有「控件显示 ≠ `get_outputs()` 真相」的固定导出设计，却留下会误导的线宽/格式冲突。
2. 方法/预设状态机有幂等与时序 bug。
3. 渲染器↔UI 包导入耦合放大降级静默面。
4. 全量 UI 套件 SIGSEGV 使「无段错误」不能再当发布论据。

**发布建议：**
- macOS 源码日构建 / 内部试用：可，但应先修 D1–D4（或明确接受）。
- Windows 冻结发布：维持 **NO-GO**，直至四组 smoke + D7 稳定。

配套实施说明见  
`docs/superpowers/specs/2026-08-02-batch-post-merge-hardening-design.md`。
