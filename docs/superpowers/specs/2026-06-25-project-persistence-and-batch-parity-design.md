# 设计：项目滤波持久化 + 批处理参数全面板对齐

- 日期：2026-06-25
- 状态：草案（待评审）
- 范围：① 滤波参数纳入项目保存（项目级全局）；② 批处理参数与主界面各分析面板对齐（FFT / 阶次 / FFT-vs-Time，**含 A 计权**）
- **明确不做**：标注（markup）持久化 —— 见 §6 决策记录
- 关联调查：本设计基于对 `project_io`、`batch`、`time_filter`、`markup`、各 `contextual_*` 面板的代码级调查（2026-06-25）

---

## 1. 背景与目标

### 1.1 目标
1. **滤波**：用户在时域设置的滤波（类型/阶数/截止/启用/显示开关），保存项目后重开能 100% 恢复，不必手动重配。
2. **批处理对齐**：批处理跑出来的结果（FFT / 阶次 / FFT-vs-Time）应与主界面单次分析使用**同一套参数**，尤其 **A/C 计权**不能丢；点「从当前单次填入」要在所有分析模式可用、且不静默丢参数。

### 1.2 当前问题（已验真）
- **滤波**：`FilterSpec` 全局存在 `inspector.filter_panel`，**不进** `ProjectDocument` / `ViewState`，重开即重置默认（`enabled=False, kind='low', cutoff=100, order=4`）。设计文档 `docs/superpowers/specs/2026-06-22-timedomain-filter-overlay-design.md` 当时 v1 范围刻意「不入项目」。
- **批处理脱节**：批处理对话框 FFT 表单只暴露 `window/nfft`（`method_buttons.py:84` `_METHOD_FIELDS["fft"]=("window","nfft")`），主面板 `get_params()` 有 18+ 项。「从当前单次填入」虽抓了全量参数（`window.py:2217`），但经 `DynamicParamForm` 只保留可见字段、`OutputPanel` 只保留 x/y/z 轴，`get_preset()` 重建时把 **weighting / db_reference / overlap / amplitude_mode / 平均** 全丢（`sheet.py:675`）。且 `_build_current_batch_preset()` 在 `fft_time` 模式直接 `return None`（`window.py:2245`）。

### 1.3 关键利好（决定成本的事实）
**计权后端三个方法全部已就绪**——runner 计算时都把 `weighting` 传给了各自算法：
- FFT：`batch.py:586` `FFTAnalyzer.compute_fft(..., weighting=...)`
- 阶次：`batch.py:616` `COTParams(..., weighting=...)`
- FFT-vs-Time：`batch.py:660` `SpectrogramParams(..., weighting=...)`

→ **A 计权对齐 = 纯 UI 暴露 + 参数透传，零算法改动。**

---

## 2. Part A — 滤波持久化（项目级全局）

### 2.1 数据来源（现状）
- `FilterSpec` 定义：`signal/filters.py:12-18` → `kind`（`'low'|'high'|'band'|'bandstop'`）、`order`（2/4/6/8）、`cutoff`、`cutoff_lo`、`cutoff_hi`。
- UI 状态（不在 FilterSpec，由 `FilterPanel` 管）：`enabled`（默认 False）、`show_original`、`show_filtered`。
- 读：`filter_panel.filter_spec()` `is_enabled()` `show_original()` `show_filtered()`（`time_filter.py:197-223`）。
- 写：`set_enabled / set_kind / set_cutoff / set_band / set_order`（`time_filter.py:183-212`）。
- 持有：`inspector.filter_panel`（`inspector.py:163`），**全局一份**，所有 view 共享、切 view 不变。

### 2.2 设计：在 `ProjectDocument` 增加顶层 `filter` 块

**序列化 schema（写入 `.tlproj`）**
```json
"filter": {
  "enabled": false,
  "spec": {
    "kind": "low",
    "order": 4,
    "cutoff": 100.0,
    "cutoff_lo": 50.0,
    "cutoff_hi": 500.0
  },
  "show_original": true,
  "show_filtered": true
}
```

**改动点**
1. `signal/filters.py`：给 `FilterSpec` 增加 `to_dict()` / `from_dict()`（纯 dataclass 映射，含字段缺省兜底）。
2. `ui/project_io.py`：
   - `ProjectDocument` 增加字段 `filter: dict | None = None`。
   - `save_project_to_json` payload 增加 `"filter"`。
   - **版本策略**：`SCHEMA_VERSION` 从 `1` 升到 `2`；`load_project_from_json` 改为**接受 `version ∈ {1,2}`**，对 `version==1` 走迁移（`filter` 缺省为 `None` = 不启用），再继续。保持「未知高版本仍拒绝」。这与 `batch_preset_io._migrate_axis_keys` 的迁移哲学一致。
3. `ui/main_window/_project_io_mixin.py`：
   - `save_project`（:552）：从 `self.inspector.filter_panel` 读 `enabled/spec/show_*` 写入 `doc.filter`。
   - `open_project`（:611）：读 `doc.filter`，按顺序调 `set_kind/set_cutoff/set_band/set_order/set_enabled` + 恢复显示开关；恢复完成后，若当前/恢复后是时域模式，触发一次重绘。
4. **缓存一致性**：时域绘制缓存键（`_plot_time_on_canvas`，`window.py:1984-2046`）必须纳入 `FilterSpec + enabled`，确保恢复滤波后曲线真重算（否则可能命中旧缓存显示未滤波曲线）。需核对现有缓存键是否已含滤波；若否，补上。

### 2.3 边界与风险
- **多采样率**：`FilterSpec` 全局一份、按各通道 `fs` 应用（`window.py:2029`），现状保留，不变。
- **Nyquist 越界**：恢复的 `cutoff` 若超过新数据 nyquist，由现有 `nyquist_guard`（`filters.py:50-77`）钳制；恢复路径需经过它，不能裸设。
- **向后兼容**：旧 v1 项目无 `filter` 键 → 迁移为「滤波关闭」，不报错。
- **新文件被旧 app 打开**：旧 app（无滤波恢复）读 v2 会被严格版本拒绝——可接受（提示升级）。若要软降级，可让旧 app 容忍，但不在本期范围。

### 2.4 测试（TDD）
- `to_dict/from_dict` 往返：四种 `kind`（含 band 双截止）+ 各 order。
- 项目往返：设滤波（启用 + band + 自定义截止 + 关 show_original）→ save → load → 断言 `filter_spec()` 全等 + `is_enabled()` + 两个 show 开关。
- v1 兼容：加载无 `filter` 字段的旧 fixture → 滤波关闭、不抛异常。
- 恢复后时域重绘包含滤波曲线（缓存未命中旧值）。

---

## 3. Part B — 批处理参数全面板对齐（含 A 计权）

### 3.1 脱节现状（字段级，已验真）

| 主面板参数 | runner 是否消费 | 对话框可输入 | 「填入当前」是否带过去 | 判定 |
|---|---|---|---|---|
| window / nfft | ✅ 三方法 | ✅ | ✅ | 对齐 |
| **weighting（A/C 计权）** | ✅ 三方法（:586/:616/:660） | ❌ | ❌ **丢** | **后端就绪，缺暴露+透传** |
| x/y/z 轴范围、time_range | ✅ | ✅(OutputPanel/InputPanel) | ✅ | 对齐 |
| overlap（FFT） + avg_mode/avg_overlap（Welch 平均） | ❌ FFT 单块 | ❌ | ❌ | 数值不一致，需改 runner（二期） |
| db_reference + amp_y（FFT dB/线性显示） | ❌ FFT 线图恒线性（`batch.py:794-798`） | ❌ | ❌ | 出图不一致，需改 runner 出图（二期） |
| remove_mean（fft_time） | ✅ fft_time | ✅ fft_time 表单 | ✅ | 对齐 |
| remark | ❌ | ❌ | ❌ | 低优先，不做 |

### 3.2 根因
1. **双轨重建丢字段**：`_build_current_batch_preset` 抓全量 → `BatchSheet.apply_preset` 经 `DynamicParamForm.apply_params` 只设可见控件、`OutputPanel.apply_axis_params` 只取轴 → `get_preset()`（`sheet.py:671-699`）从可见字段 + 轴 + rpm 重建，非可见 key 全丢。
2. **`_build_current_batch_preset` 无 `fft_time` 分支**（`window.py:2209-2245`）。
3. **`_METHOD_FIELDS` 无 weighting**（`method_buttons.py:83-87`）。

### 3.3 设计

#### B-1 参数透传（核心修复，止血「丢参数」）
让 `BatchSheet` 保留导入/填入时那些「不被任何可见控件、OutputPanel、InputPanel 拥有」的参数原样透传到 runner。
- `BatchSheet` 新增 `self._passthrough_params: dict`。
- `apply_preset(preset)`：记录 `preset.params` 中**不属于**当前方法可见字段集 / 轴字段 / rpm 字段 的 key（如 `weighting`、`db_reference`、`amplitude_mode`、`overlap`、`avg_mode`、`avg_overlap`）。
- `get_preset()`（`sheet.py:671`）合并顺序（**后者覆盖前者**）：
  ```
  params = {**self._passthrough_params, **form_params, **axis_params, **rpm_params}
  if time_range: params["time_range"] = time_range
  ```
  即：表单可编辑字段、轴、rpm 优先（用户在对话框改过的以对话框为准），其余 passthrough 兜底。
- **效果**：weighting/db_reference/amplitude_mode 等即使表单不显示，也能从「填入当前 / 导入 preset」一路带到 runner——三方法通吃，零算法改动。
- **失效场景**：用户切换方法（`set_method`）后 passthrough 是否仍适用？规则：切方法时清空与新方法不相关的 passthrough（保守），避免把 FFT 的 key 带进阶次。实现时以「方法相关 key 白名单」过滤。

#### B-2 暴露 weighting（让自由配置也能设计权）
- `_METHOD_FIELDS` 三个方法都加 `"weighting"`。
- `DynamicParamForm` 增加 weighting `QComboBox`（label「计权」），**取值集合必须与主面板 `combo_weighting` 对齐**（实现时以主面板 items 为准，常见为 `None / A / C`）。
- `get_params()/apply_params()` 增加 weighting 分支。
- 注意：weighting 一旦成为可见字段，B-1 中它就归「form 拥有」，不再走 passthrough——逻辑自洽。

#### B-3 fft_time 的「从当前填入」
- `_build_current_batch_preset`（`window.py:2209`）增加 `mode == 'fft_time'` 分支：
  - 信号取 `self.inspector.fft_time_ctx.current_signal()`（单信号）；为空返回 None。
  - `params = fft_time_ctx.get_params()`；`params['fs'] = fft_time_ctx.fs()`；带 time_range。
  - `AnalysisPreset.from_current_single(name="当前 FFT-vs-Time", method="fft_time", signal=signal, params=params)`。
- 对齐 `open_batch` 里 `current_single` 失效检测（`window.py:2174`）的既有逻辑。

#### B-4（二期 · 需单独 green-light）完全数值对齐
仅在用户确认要「像素级等同屏幕」时做，**会动 signal 核心 + 出图**：
- **FFT dB 出图**：`_build_export_scene` 的 `kind=='fft'` 分支（`batch.py:794`）支持 `amplitude_mode/db_reference`（现恒线性）。
- **FFT Welch 平均**：`_compute_fft_dataframe`（`batch.py:572`）支持 `overlap/avg_mode/avg_overlap`（现单块 FFT）。需 `signal-processing-expert` TDD 补测，保证与主面板数值一致。
> 本期默认**不含** B-4；B-1~B-3 已覆盖用户明确要的「全面板 + A 计权」且无数值算法风险。

### 3.4 preset JSON 往返
`batch_preset_io.save_preset_to_json` 已整存 `params` dict（`:57`），weighting 等天然往返；本期只需补一条**回归测试**确认 weighting 不被丢。

### 3.5 测试（TDD）
- **B-1**：FFT 模式设 weighting=A → 「填入当前」→ `get_preset().params['weighting']=='A'`；进一步 mock runner 断言 `compute_fft` 收到 `weighting='A'`。
- **B-1 覆盖序**：对话框改 window 后，window 以表单为准、weighting 仍从 passthrough 保留。
- **B-2**：weighting 下拉往返（三方法）；取值集合与主面板一致。
- **B-3**：fft_time 模式 `_build_current_batch_preset()` 不再 None；信号/参数正确。
- **B-4（若做）**：批处理 FFT 数值与主面板 `FFTAnalyzer` 在相同参数下逐点一致（含 Welch、dB）。

---

## 4. 影响面 / 文件清单

| 模块 | 文件 | 改动 |
|---|---|---|
| 滤波序列化 | `signal/filters.py` | `FilterSpec.to_dict/from_dict` |
| 项目 schema | `ui/project_io.py` | `ProjectDocument.filter` 字段 + v2 + 迁移 |
| 项目 I/O | `ui/main_window/_project_io_mixin.py` | save 捕获 / open 恢复滤波 + 重绘 |
| 时域缓存 | `ui/main_window/window.py` | 缓存键纳入 filter |
| 批处理透传 | `ui/drawers/batch/sheet.py` | `_passthrough_params` + `get_preset` 合并 |
| 批处理表单 | `ui/drawers/batch/method_buttons.py` | `_METHOD_FIELDS` 加 weighting + 控件 |
| 批处理填入 | `ui/main_window/window.py` | `_build_current_batch_preset` 加 fft_time |
| 测试 | `tests/test_project_io*.py`、`tests/ui/test_*batch*`、新增 | 上述 TDD |

---

## 5. 非目标 / 风险

- 不改各 `contextual_*` 面板的参数语义；只搬运、不重设计。
- 不把滤波接入 FFT/阶次/导出（维持「时域显示叠加」定位）。
- B-4（Welch/dB 数值对齐）单独门控，避免在止血期引入算法回归。
- UI 新增「计权」下拉属界面变更：实现前按团队约定（`feedback-ui-discuss-before-change`）以本 spec 作为评审依据，落地由 `pyqt-ui-engineer` 验真渲染。

---

## 6. 决策记录：标注（markup）不做持久化

调查（2026-06-25）结论：当前 markup 是**临时位图标注工具**——
- 在图表渲染出的**位图快照**上，用**像素/场景坐标**作画（`markup/editor.py`、`items.py`）。
- `finish_and_copy()` 把标注**拍平成 QPixmap 并丢弃标注对象**；不绑定任何 `ViewState/AnalysisViewState`；`project_io` 完全不涉及；连同一会话都不留存。

→ 若做「重开后标注叠加在重算后的活动图上」（用户的复现直觉），需先把 markup 重构为**绑定 view、数据坐标锚定的持久叠加层**，是另一个量级的工程，且需解决数据范围变化时的锚点语义。经确认，本期**不做**；记录为 backlog：**「markup 持久化叠加层」需先立独立设计**。

---

## 7. 交付顺序建议
Part A（滤波）与 Part B-1~B-3（批处理）相互独立，可并行。B-4 视用户决定再启。详见同日 plan：`docs/superpowers/plans/2026-06-25-project-persistence-and-batch-parity.md`。
